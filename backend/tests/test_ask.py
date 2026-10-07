import json
from datetime import date
from decimal import Decimal

import pytest
from fakes import fake_response, text_block, tool_use

import ask
from lib import db, llm, vectors

SYLLABI = [
    {"syllabusId": "s1", "courseCode": "COMPSCI 3GC3", "courseTitle": "Graphics", "filename": "3gc3.pdf",
     "status": "READY", "deadlineCount": 2},
    {"syllabusId": "s2", "courseCode": "PSYCH 1X03", "courseTitle": "Psych", "filename": "psych.pdf",
     "status": "READY", "deadlineCount": 1},
]
DEADLINES = [
    {"pk": "SYLLABUS#s1", "sk": "DEADLINE#001", "gsi1pk": "USER#u", "syllabusId": "s1", "courseCode": "COMPSCI 3GC3",
     "title": "Assignment 1", "type": "assignment", "dueDate": "2026-10-09", "weightPercent": Decimal("10")},
    {"pk": "SYLLABUS#s2", "sk": "DEADLINE#001", "gsi1pk": "USER#u", "syllabusId": "s2", "courseCode": "PSYCH 1X03",
     "title": "Lab 3", "type": "lab", "dueDate": "2026-10-15", "weightPercent": Decimal("4")},
]


@pytest.fixture
def data(monkeypatch):
    monkeypatch.setattr(db, "list_syllabi", lambda user: SYLLABI)
    monkeypatch.setattr(db, "deadlines_between", lambda user, a, b: [d for d in DEADLINES if a <= d["dueDate"] <= b])
    monkeypatch.setattr(db, "all_deadlines", lambda user: DEADLINES)
    chunks = {
        "s1": [{"syllabusId": "s1", "filename": "3gc3.pdf", "page": Decimal(4), "text": "Late work loses 10% per day.",
                "embedding": vectors.pack([1.0, 0.0])}],
        "s2": [{"syllabusId": "s2", "filename": "psych.pdf", "page": Decimal(2), "text": "Office hours Tuesday.",
                "embedding": vectors.pack([0.0, 1.0])}],
    }
    monkeypatch.setattr(db, "list_items", lambda sid, prefix: chunks[sid])
    monkeypatch.setattr(vectors, "embed", lambda text, operation=None: [1.0, 0.1])


def script(monkeypatch, responses):
    calls = []

    def fake_create(operation, **kwargs):
        calls.append(json.loads(json.dumps(kwargs["messages"], default=lambda o: o.__dict__)))
        return responses[len(calls) - 1]

    monkeypatch.setattr(llm, "create", fake_create)
    return calls


def test_upcoming_deadlines_tool_filters_by_course(data):
    agent = ask.Agent("u", date(2026, 10, 7))
    out = agent.get_upcoming_deadlines(14, course="3gc3")
    assert [d["title"] for d in out["deadlines"]] == ["Assignment 1"]
    assert out["deadlines"][0]["id"] == "D1"
    assert out["deadlines"][0]["weightPercent"] == 10          # Decimal -> int for the model
    assert agent.sources["D1"]["kind"] == "deadline"


def test_search_returns_best_passage_with_page(data):
    agent = ask.Agent("u", date(2026, 10, 7))
    out = agent.search_syllabus("late policy")
    top = out["results"][0]
    assert (top["id"], top["page"], top["courseCode"]) == ("S1", 4, "COMPSCI 3GC3")


def test_agent_loop_runs_tools_and_returns_cited_sources(data, monkeypatch):
    calls = script(monkeypatch, [
        fake_response(tool_use("get_upcoming_deadlines", {"days": 14}, id="t1"),
                      tool_use("search_syllabus", {"query": "late penalty", "course": "3GC3"}, id="t2"),
                      stop_reason="tool_use"),
        fake_response(text_block("A1 is due Oct 9 [D1] and late work loses 10%/day [S1].")),
    ])
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u"}}}},
             "body": json.dumps({"question": "What's due soon and what's the late policy?", "today": "2026-10-07"})}
    resp = ask.handler(event, None)
    body = json.loads(resp["body"])

    assert resp["statusCode"] == 200
    assert body["toolCalls"] == ["get_upcoming_deadlines", "search_syllabus"]
    assert [c["id"] for c in body["citations"]] == ["D1", "S1"]
    # both tool results went back in ONE user message, matched by tool_use_id
    results = calls[1][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert "Today is 2026-10-07 (Wednesday)" in calls[0][0]["content"]


def test_tool_errors_are_reported_not_raised(data, monkeypatch):
    calls = script(monkeypatch, [
        fake_response(tool_use("no_such_tool", {}, id="t1"), stop_reason="tool_use"),
        fake_response(text_block("Sorry.")),
    ])
    answer = ask.run(ask.Agent("u", date(2026, 10, 7)), "hi")
    assert answer == "Sorry."
    assert calls[1][-1]["content"][0]["is_error"] is True


def test_loop_is_bounded(data, monkeypatch):
    looping = fake_response(tool_use("list_courses", {}), stop_reason="tool_use")
    script(monkeypatch, [looping] * ask.MAX_TURNS)
    assert "couldn't finish" in ask.run(ask.Agent("u", date(2026, 10, 7)), "hi")


def test_history_is_sanitised():
    turns = ask._clean_history([{"role": "assistant", "content": "hello"}, {"role": "system", "content": "x"},
                                {"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}])
    assert turns == [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]


def test_cited_ignores_unknown_ids():
    assert ask.cited("see [D1] and [D9] and [D1]", {"D1": {"id": "D1"}}) == [{"id": "D1"}]


def test_handler_validation():
    assert ask.handler({"body": "{}"}, None)["statusCode"] == 401
    auth = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u"}}}}}
    assert ask.handler({**auth, "body": "{}"}, None)["statusCode"] == 400
    assert ask.handler({**auth, "body": json.dumps({"question": "x", "today": "soon"})}, None)["statusCode"] == 400
