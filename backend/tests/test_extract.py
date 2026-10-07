import pytest
from fakes import fake_response, text_block, tool_use

import extract_deadlines as ex
from lib import llm


def test_user_message_has_pages_and_term_start():
    msg = ex.build_user_message(["intro", "A1 due Oct 4"], "2026-09-08")
    assert "<term_start>2026-09-08</term_start>" in msg
    assert "[Page 2]\nA1 due Oct 4" in msg


def test_unknown_term_start_says_so():
    assert "unknown" in ex.build_user_message(["x"], None)


def test_parses_tool_call():
    resp = fake_response(
        text_block("Here you go"),
        tool_use(ex.TOOL_NAME, {"courseCode": "CS 1", "courseTitle": None, "deadlines": [{"title": "A1"}]}),
        stop_reason="tool_use",
    )
    out = ex.parse_tool_call(resp)
    assert out == {"courseCode": "CS 1", "courseTitle": None, "deadlines": [{"title": "A1"}]}


def test_missing_tool_call_raises_retryable_format_error():
    with pytest.raises(ex.ExtractionFormatError):
        ex.parse_tool_call(fake_response(text_block("I found 3 deadlines...")))


def test_extract_sends_cached_system_prompt_and_tool(monkeypatch):
    captured = {}

    def fake_create(operation, **kwargs):
        captured.update(kwargs, operation=operation)
        return fake_response(tool_use(ex.TOOL_NAME, {"courseCode": None, "courseTitle": None, "deadlines": []}),
                             stop_reason="tool_use")

    monkeypatch.setattr(llm, "create", fake_create)
    ex.extract(["page"], "2026-09-08")
    assert captured["operation"] == "extract_deadlines"
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert captured["tools"] == [ex.TOOL]
    assert "tool_choice" not in captured          # forced tool choice is rejected on Opus 5.5


def test_examples_in_prompt_match_schema_field_names():
    required = set(ex.TOOL["input_schema"]["properties"]["deadlines"]["items"]["required"])
    assert all(f'"{field}"' in ex.SYSTEM_PROMPT for field in required)
