"""POST /ask -> an agent that answers questions about the user's syllabi, with citations.

Body: {"question": "...", "today": "2026-10-07", "history": [{"role": "user"|"assistant", "content": "..."}]}

Instead of a hand-written classifier ("structured or fuzzy?"), Claude gets tools and picks:
structured questions ("what's due in the next two weeks and how much is it worth?") go to
DynamoDB queries; fuzzy ones ("what's the late policy in 3GC3?") go to vector search over the
syllabus text; mixed questions use both. Every fact handed to the model carries an id (D3, S2)
and the answer must cite them, so the UI can show where each claim came from.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from lib import db, llm, vectors
from lib.http import json_body, response, user_id

MAX_TURNS = 6
MAX_QUESTION_CHARS = 2000
MAX_HISTORY = 6

SYSTEM_PROMPT = """You are a study assistant for a university student. You answer questions about \
the course outlines (syllabi) they uploaded: deadlines, exam dates, grade weights, and policies.

Use the tools to look things up. Never answer from memory or guess dates and weights.
- Questions about what is due, when, or how much it's worth: use get_upcoming_deadlines or list_deadlines.
- Questions about policies, content, contacts, or anything else in the text: use search_syllabus.
- Use list_courses when you need to know which courses exist or match a course name.

Every fact you state must cite the id of the record it came from in square brackets, e.g. \
"Assignment 2 is due Oct 4 [D3]" or "late work loses 10% per day [S2]". Only cite ids that tools returned.
If the tools don't contain the answer, say you couldn't find it in their syllabi.
Dates marked approximate came from a week number; say "around" for those.
Keep answers short and scannable: a sentence or a short list. Weights are % of the final grade."""

TOOLS = [
    {
        "name": "list_courses",
        "description": "List the user's uploaded syllabi with course codes, titles and processing status.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_upcoming_deadlines",
        "description": "Deadlines due from today through the next `days` days, soonest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 366},
                "course": {"type": "string", "description": "Optional course code or name filter, e.g. '3GC3'"},
            },
            "required": ["days"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_deadlines",
        "description": "All deadlines (past, future and undated), optionally filtered by course and/or type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course": {"type": "string"},
                "type": {"type": "string", "description": "assignment, quiz, midterm, final_exam, project, lab, ..."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_syllabus",
        "description": "Semantic search over the full text of the user's syllabi. Returns the most relevant passages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "course": {"type": "string", "description": "Optional course code or name filter"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


TOOL_NAMES = {tool["name"] for tool in TOOLS}


def _course_matches(record, course):
    if not course:
        return True
    needle = course.lower().replace(" ", "")
    haystack = " ".join(str(record.get(k) or "") for k in ("courseCode", "courseTitle", "filename"))
    return needle in haystack.lower().replace(" ", "")


class Agent:
    """Runs tools for one user and keeps the registry of cite-able sources.

    Each tool method is named after its tool in TOOLS.
    """

    def __init__(self, user, today):
        self.user = user
        self.today = today
        self.sources = {}          # "D1" / "S1" -> source record
        self.tool_calls = []
        self._counts = {"D": 0, "S": 0}
        self._syllabi = None
        self._chunks = None

    # ---- data access (loaded once per request) ----
    def syllabi(self):
        """syllabusId -> META item."""
        if self._syllabi is None:
            self._syllabi = {s["syllabusId"]: s for s in db.list_syllabi(self.user)}
        return self._syllabi

    def _matching(self, deadlines, course):
        """Filter deadlines by course, matching on the deadline or its syllabus' code/title/filename."""
        return [d for d in deadlines if _course_matches({**self.syllabi().get(d["syllabusId"], {}), **d}, course)]

    def _cite(self, prefix, source):
        self._counts[prefix] += 1
        sid = f"{prefix}{self._counts[prefix]}"
        self.sources[sid] = {"id": sid, **source}
        return sid

    def _cite_deadlines(self, items):
        cited = []
        for item in items:
            record = db.public_deadline(item)
            cited.append({"id": self._cite("D", {"kind": "deadline", **record}), **record})
        return cited

    # ---- tools ----
    def list_courses(self):
        return [{
            "courseCode": s.get("courseCode"),
            "courseTitle": s.get("courseTitle"),
            "filename": s.get("filename"),
            "status": s.get("status"),
            "deadlineCount": s.get("deadlineCount"),
        } for s in self.syllabi().values()]

    def get_upcoming_deadlines(self, days, course=None):
        days = max(1, min(int(days), 366))
        end = self.today + timedelta(days=days)
        items = db.deadlines_between(self.user, self.today.isoformat(), end.isoformat())
        return {"from": self.today.isoformat(), "to": end.isoformat(),
                "deadlines": self._cite_deadlines(self._matching(items, course))}

    def list_deadlines(self, course=None, type=None):
        items = [d for d in self._matching(db.all_deadlines(self.user), course) if not type or d.get("type") == type]
        return {"deadlines": self._cite_deadlines(items)}

    def search_syllabus(self, query, course=None):
        if self._chunks is None:
            self._chunks = [
                {**c, "embedding": vectors.unpack(c["embedding"]),
                 "courseCode": s.get("courseCode"), "courseTitle": s.get("courseTitle")}
                for s in self.syllabi().values() if s.get("status") == "READY"
                for c in db.list_items(s["syllabusId"], "CHUNK#")
            ]
        pool = [c for c in self._chunks if _course_matches(c, course)]
        if not pool:
            return {"results": [], "note": "No processed syllabi match."}
        results = []
        for score, chunk in vectors.top_k(vectors.embed(query, operation="ask_search"), pool, k=5):
            source = {"kind": "passage", "syllabusId": chunk["syllabusId"],
                      "courseCode": chunk.get("courseCode"), "filename": chunk.get("filename"),
                      "page": int(chunk["page"]), "text": chunk["text"]}
            results.append({"id": self._cite("S", source), **source, "score": round(score, 3)})
        return {"results": results}

    def run_tool(self, name, args):
        self.tool_calls.append(name)
        if name not in TOOL_NAMES:
            raise ValueError(f"Unknown tool {name}")
        return getattr(self, name)(**args)


def _clean_history(history):
    turns = []
    for turn in (history or [])[-MAX_HISTORY:]:
        if isinstance(turn, dict) and turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
            turns.append({"role": turn["role"], "content": turn["content"][:MAX_QUESTION_CHARS]})
    while turns and turns[0]["role"] != "user":   # first message must be from the user
        turns.pop(0)
    return turns


def run(agent, question, history=None):
    # Today's date goes in the user turn, not the system prompt, so the system prefix stays cacheable.
    messages = _clean_history(history) + [{
        "role": "user",
        "content": f"Today is {agent.today.isoformat()} ({agent.today.strftime('%A')}).\n\n{question}",
    }]
    for _ in range(MAX_TURNS):
        resp = llm.create(
            "ask",
            max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            return llm.text_of(resp)

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for call in tool_uses:
            try:
                output, is_error = agent.run_tool(call.name, dict(call.input or {})), False
            except Exception as e:          # report tool failures to the model instead of crashing
                output, is_error = {"error": str(e)}, True
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": json.dumps(output, default=str), "is_error": is_error})
        messages.append({"role": "user", "content": results})   # all results in one message
    return "Sorry, I couldn't finish looking that up. Try a more specific question."


def cited(answer, sources):
    ids = dict.fromkeys(re.findall(r"\[([DS]\d+)\]", answer))
    return [sources[i] for i in ids if i in sources]


def handler(event, context):
    user = user_id(event)
    if not user:
        return response(401, {"error": "Unauthorized"})
    body, error = json_body(event)
    if error:
        return error

    question = str(body.get("question") or "").strip()
    if not question:
        return response(400, {"error": "question is required"})
    if len(question) > MAX_QUESTION_CHARS:
        return response(400, {"error": f"question must be under {MAX_QUESTION_CHARS} characters"})
    try:
        today = date.fromisoformat(str(body["today"])) if body.get("today") else datetime.now(timezone.utc).date()
    except ValueError:
        return response(400, {"error": "today must be YYYY-MM-DD"})

    agent = Agent(user, today)
    try:
        answer = run(agent, question, body.get("history"))
    except llm.ModelRefusalError:
        return response(200, {"answer": "I can't help with that one.", "citations": [], "toolCalls": agent.tool_calls})
    except llm.RetryableModelError:
        return response(503, {"error": "The AI service is busy. Try again in a moment."})
    return response(200, {"answer": answer, "citations": cited(answer, agent.sources), "toolCalls": agent.tool_calls})
