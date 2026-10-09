"""Pipeline step 3: syllabus text -> structured deadlines with Claude.

Bedrock's Messages endpoint has no structured-outputs mode, and newer models (Opus 5.5, Sonnet 5.5)
reject a forced tool_choice. To keep the model swappable, the prompt asks for exactly one
`record_course_outline` call and the validate step re-checks every field in code.
The tool schema is the contract.

Output: {"courseCode", "courseTitle", "deadlines": [...]} under $.extraction
"""
from extract_text import load_pages
from lib import llm

TOOL_NAME = "record_course_outline"

DEADLINE_TYPES = ["assignment", "quiz", "midterm", "final_exam", "project", "lab", "presentation",
                  "participation", "other"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

TOOL = {
    "name": TOOL_NAME,
    "description": "Record every graded deliverable and exam found in the course outline.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["courseCode", "courseTitle", "deadlines"],
        "properties": {
            "courseCode": {"type": ["string", "null"], "description": "e.g. COMPSCI 3GC3"},
            "courseTitle": {"type": ["string", "null"]},
            "deadlines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "type", "dueDate", "dueTime", "week", "weekday",
                                 "weightPercent", "sourceText", "page"],
                    "properties": {
                        "title": {"type": "string", "description": "Short name, e.g. 'Assignment 2'"},
                        "type": {"type": "string", "enum": DEADLINE_TYPES},
                        "dueDate": {"type": ["string", "null"], "description": "YYYY-MM-DD, only if stated or derivable"},
                        "dueTime": {"type": ["string", "null"], "description": "24h HH:MM if stated"},
                        "week": {"type": ["integer", "null"], "description": "Course week number if the outline uses weeks"},
                        "weekday": {"type": ["string", "null"], "enum": WEEKDAYS + [None]},
                        "weightPercent": {"type": ["number", "null"], "description": "Share of final grade, 0-100"},
                        "sourceText": {"type": "string", "description": "Verbatim snippet (max ~200 chars) supporting this item"},
                        "page": {"type": ["integer", "null"], "description": "1-based page the snippet is on"},
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = f"""You extract graded deadlines from university course outlines (syllabi).

Read the whole outline, then call the `{TOOL_NAME}` tool exactly once with every graded item: \
assignments, quizzes, labs, projects, presentations, midterms, final exams, participation. \
Do not answer in prose; the tool call is the only output that is used.

Rules:
- One entry per dated instance. "Assignment 1 due Sept 20, Assignment 2 due Oct 4" is two entries. \
If a recurring item has no individual dates ("weekly quizzes, best 8 of 10, 10% total"), record one \
entry with the total weight and put the rule in the title, e.g. "Weekly quizzes (best 8 of 10)".
- dueDate is YYYY-MM-DD. Use it only when the outline states a calendar date, or when a week number \
plus the term start date given to you pins the date down. Never invent a date.
- When the outline gives a week ("Week 7", "in week 10 tutorial") set `week`, and `weekday` if a day \
is stated. If you also computed dueDate from the term start, keep both.
- When the timing is vague ("during the final exam period", "TBA"), leave dueDate, week and weekday null.
- weightPercent is the share of the final grade as a number (15% -> 15). If a weight is split \
("two midterms, 20% each"), give each entry its own weight. Leave it null if not stated.
- sourceText quotes the outline verbatim so a student can verify the entry. page is the page marker \
the snippet appears under.
- Ignore readings, lecture topics, office hours and non-graded events.

<example>
<term_start>2026-01-05</term_start>
<outline>
[Page 2]
Evaluation: Assignment 1 (10%) due Friday Jan 23 at 11:59pm. Assignment 2 (10%) due Feb 13.
Midterm test (25%) in class, Week 7. Final exam (55%) scheduled by the Registrar.
</outline>
<tool_input>
{{"courseCode": null, "courseTitle": null, "deadlines": [
 {{"title": "Assignment 1", "type": "assignment", "dueDate": "2026-01-23", "dueTime": "23:59", "week": null, "weekday": "Fri", "weightPercent": 10, "sourceText": "Assignment 1 (10%) due Friday Jan 23 at 11:59pm", "page": 2}},
 {{"title": "Assignment 2", "type": "assignment", "dueDate": "2026-02-13", "dueTime": null, "week": null, "weekday": null, "weightPercent": 10, "sourceText": "Assignment 2 (10%) due Feb 13", "page": 2}},
 {{"title": "Midterm test", "type": "midterm", "dueDate": null, "dueTime": null, "week": 7, "weekday": null, "weightPercent": 25, "sourceText": "Midterm test (25%) in class, Week 7", "page": 2}},
 {{"title": "Final exam", "type": "final_exam", "dueDate": null, "dueTime": null, "week": null, "weekday": null, "weightPercent": 55, "sourceText": "Final exam (55%) scheduled by the Registrar", "page": 2}}
]}}
</tool_input>
</example>

<example>
<term_start>2026-09-08</term_start>
<outline>
[Page 1]
PSYCH 1X03 - Introduction to Psychology
[Page 3]
Labs (5 x 4% = 20%): submitted Thursdays of weeks 3, 5, 7, 9 and 11.
Term project: proposal (5%) Oct 10; final report (25%) Dec 5, 5:00 PM.
</outline>
<tool_input>
{{"courseCode": "PSYCH 1X03", "courseTitle": "Introduction to Psychology", "deadlines": [
 {{"title": "Lab 1", "type": "lab", "dueDate": "2026-09-24", "dueTime": null, "week": 3, "weekday": "Thu", "weightPercent": 4, "sourceText": "Labs (5 x 4% = 20%): submitted Thursdays of weeks 3, 5, 7, 9 and 11.", "page": 3}},
 {{"title": "Lab 2", "type": "lab", "dueDate": "2026-10-08", "dueTime": null, "week": 5, "weekday": "Thu", "weightPercent": 4, "sourceText": "Labs (5 x 4% = 20%): submitted Thursdays of weeks 3, 5, 7, 9 and 11.", "page": 3}},
 {{"title": "Lab 3", "type": "lab", "dueDate": "2026-10-22", "dueTime": null, "week": 7, "weekday": "Thu", "weightPercent": 4, "sourceText": "Labs (5 x 4% = 20%): submitted Thursdays of weeks 3, 5, 7, 9 and 11.", "page": 3}},
 {{"title": "Lab 4", "type": "lab", "dueDate": "2026-11-05", "dueTime": null, "week": 9, "weekday": "Thu", "weightPercent": 4, "sourceText": "Labs (5 x 4% = 20%): submitted Thursdays of weeks 3, 5, 7, 9 and 11.", "page": 3}},
 {{"title": "Lab 5", "type": "lab", "dueDate": "2026-11-19", "dueTime": null, "week": 11, "weekday": "Thu", "weightPercent": 4, "sourceText": "Labs (5 x 4% = 20%): submitted Thursdays of weeks 3, 5, 7, 9 and 11.", "page": 3}},
 {{"title": "Term project proposal", "type": "project", "dueDate": "2026-10-10", "dueTime": null, "week": null, "weekday": null, "weightPercent": 5, "sourceText": "proposal (5%) Oct 10", "page": 3}},
 {{"title": "Term project final report", "type": "project", "dueDate": "2026-12-05", "dueTime": "17:00", "week": null, "weekday": null, "weightPercent": 25, "sourceText": "final report (25%) Dec 5, 5:00 PM", "page": 3}}
]}}
</tool_input>
</example>

Week 1 is the week containing the term start date; weeks start on Monday."""


class ExtractionFormatError(Exception):
    """Model didn't call the tool. Retried by Step Functions."""


def build_user_message(pages, term_start):
    outline = "\n".join(f"[Page {i}]\n{text}" for i, text in enumerate(pages, start=1))
    term = term_start or "unknown (do not compute dates from week numbers)"
    return (
        f"<term_start>{term}</term_start>\n<outline>\n{outline}\n</outline>\n\n"
        f"Call {TOOL_NAME} with every graded item in this outline."
    )


def extract(pages, term_start):
    response = llm.create(
        "extract_deadlines",
        max_tokens=16000,
        thinking={"type": "adaptive"},       # Sonnet 4.6 only thinks when asked to
        output_config={"effort": "medium"},
        # Stable prefix (tools + system) gets an explicit cache breakpoint.
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[TOOL],
        messages=[{"role": "user", "content": build_user_message(pages, term_start)}],
    )
    return parse_tool_call(response)


def parse_tool_call(response):
    call = next((b for b in response.content if b.type == "tool_use" and b.name == TOOL_NAME), None)
    if call is None:
        raise ExtractionFormatError(f"Model did not call {TOOL_NAME} (stop_reason={response.stop_reason})")
    data = call.input           # the SDK parses tool input into a dict
    deadlines = data.get("deadlines")
    return {
        "courseCode": data.get("courseCode"),
        "courseTitle": data.get("courseTitle"),
        "deadlines": deadlines if isinstance(deadlines, list) else [],
    }


def handler(event, context):
    pages = load_pages(event["bucket"], event["text"]["textKey"])
    return extract(pages, event.get("termStart"))
