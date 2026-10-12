import json
from datetime import date
from decimal import Decimal

import pytest

import api
import notify_daily
from lib import aws, db, notify
from validate import clean_user_deadline

META = {"syllabusId": "s1", "ownerId": "u", "courseCode": "COMPSCI 3GC3", "filename": "3gc3.pdf"}


def call(route, body=None, **path):
    event = {"routeKey": route, "pathParameters": path,
             "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u", "email": "me@example.com"}}}}}
    if body is not None:
        event["body"] = json.dumps(body)
    resp = api.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


class Table:
    """In-memory stand-in for the DynamoDB table (only the calls the API makes)."""

    def __init__(self, items=()):
        self.items = {(i["pk"], i["sk"]): i for i in items}

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item

    def delete_item(self, Key):
        self.items.pop((Key["pk"], Key["sk"]), None)

    def update_item(self, **kwargs):
        pass


@pytest.fixture
def table(monkeypatch):
    t = Table([{"pk": "SYLLABUS#s1", "sk": "DEADLINE#001", "syllabusId": "s1", "title": "Midterm",
                "type": "midterm", "dueDate": "2026-10-19", "week": 7, "dateApproximate": True,
                "weightPercent": Decimal("25"), "sourceText": "Midterm (25%) in Week 7"}])
    monkeypatch.setattr(aws, "table", lambda: t)
    monkeypatch.setattr(db, "get_owned_meta", lambda sid, user: META if (sid, user) == ("s1", "u") else None)
    monkeypatch.setattr(db, "list_items", lambda sid, prefix: [i for (pk, sk), i in t.items.items()
                                                               if pk == f"SYLLABUS#{sid}" and sk.startswith(prefix)])
    return t


# ---------------- input validation ----------------
def test_clean_user_deadline_accepts_and_normalises():
    d, err = clean_user_deadline({"title": " Quiz 3 ", "type": "quiz", "dueDate": "2026-10-02",
                                  "dueTime": "09:30", "weightPercent": "2.5%"})
    assert err is None and d == {"title": "Quiz 3", "type": "quiz", "dueDate": "2026-10-02",
                                 "dueTime": "09:30", "weightPercent": 2.5}


@pytest.mark.parametrize("bad, message", [
    ({"title": ""}, "title"),
    ({"title": "x", "type": "party"}, "type"),
    ({"title": "x", "dueDate": "Oct 2"}, "dueDate"),
    ({"title": "x", "dueTime": "9am"}, "dueTime"),
    ({"title": "x", "weightPercent": 150}, "weightPercent"),
])
def test_clean_user_deadline_rejects_bad_input(bad, message):
    d, err = clean_user_deadline(bad)
    assert d is None and message in err


def test_empty_strings_clear_optional_fields():
    d, err = clean_user_deadline({"title": "Reading", "dueDate": "", "weightPercent": ""})
    assert err is None and d["dueDate"] is None and d["weightPercent"] is None


# ---------------- deadline CRUD ----------------
def test_add_deadline_gets_next_number_and_index_keys(table):
    status, body = call("POST /syllabi/{id}/deadlines", {"title": "Bonus quiz", "type": "quiz",
                                                         "dueDate": "2026-11-02", "weightPercent": 2}, id="s1")
    assert status == 200 and body["deadline"]["deadlineId"] == "002"
    item = table.items[("SYLLABUS#s1", "DEADLINE#002")]
    assert item["source"] == "manual" and item["gsi1pk"] == "USER#u"
    assert item["gsi1sk"] == "DUE#2026-11-02#s1#002"
    assert item["weightPercent"] == Decimal("2")


def test_edit_keeps_evidence_and_approximate_flag_until_date_changes(table):
    status, body = call("PATCH /syllabi/{id}/deadlines/{n}", {"title": "Midterm test"}, id="s1", n="001")
    item = table.items[("SYLLABUS#s1", "DEADLINE#001")]
    assert status == 200 and item["title"] == "Midterm test" and item["source"] == "edited"
    assert item["sourceText"] == "Midterm (25%) in Week 7" and item["dateApproximate"] is True

    call("PATCH /syllabi/{id}/deadlines/{n}", {"dueDate": "2026-10-20"}, id="s1", n="001")
    item = table.items[("SYLLABUS#s1", "DEADLINE#001")]
    assert item["dueDate"] == "2026-10-20" and item["dateApproximate"] is False
    assert item["gsi1sk"] == "DUE#2026-10-20#s1#001"


def test_edit_rejects_bad_values_and_unknown_rows(table):
    assert call("PATCH /syllabi/{id}/deadlines/{n}", {"weightPercent": -1}, id="s1", n="001")[0] == 400
    assert call("PATCH /syllabi/{id}/deadlines/{n}", {"title": "x"}, id="s1", n="009")[0] == 404
    assert call("PATCH /syllabi/{id}/deadlines/{n}", {"title": "x"}, id="other", n="001")[0] == 404
    assert call("PATCH /syllabi/{id}/deadlines/{n}", {"title": "x"}, id="s1", n="../x")[0] == 404


def test_delete_deadline(table):
    assert call("DELETE /syllabi/{id}/deadlines/{n}", id="s1", n="001")[0] == 200
    assert ("SYLLABUS#s1", "DEADLINE#001") not in table.items


# ---------------- reminder settings ----------------
@pytest.fixture
def notifications_on(monkeypatch):
    monkeypatch.setenv("NOTIFY_FROM_EMAIL", "reminders@example.com")
    monkeypatch.setenv("SES_SANDBOX", "true")


def test_settings_unavailable_without_sender(table, monkeypatch):
    monkeypatch.delenv("NOTIFY_FROM_EMAIL", raising=False)
    assert call("GET /settings")[1]["available"] is False
    assert call("PUT /settings", {"emailEnabled": True, "daysAhead": 3})[0] == 503


def test_enabling_reminders_requests_verification_and_joins_notify_list(table, notifications_on, monkeypatch):
    requested = []
    monkeypatch.setattr(notify, "request_verification", lambda email: requested.append(email) or True)
    status, body = call("PUT /settings", {"emailEnabled": True, "daysAhead": 7})
    item = table.items[("USER#u", "SETTINGS")]
    assert status == 200 and body["verificationSent"] is True and requested == ["me@example.com"]
    assert item["gsi1pk"] == "NOTIFY" and item["daysAhead"] == 7

    status, body = call("PUT /settings", {"emailEnabled": False, "daysAhead": 7})
    assert "gsi1pk" not in table.items[("USER#u", "SETTINGS")]          # off -> not in the daily list
    assert call("PUT /settings", {"emailEnabled": True, "daysAhead": 5})[0] == 400


# ---------------- digest + daily job ----------------
def test_digest_lists_deadlines_with_weights_and_approximate_marker():
    subject, text, html_body = notify.build_digest(
        [{"dueDate": "2026-10-09", "dueTime": "23:59", "courseCode": "CS 3GC3", "title": "A1", "weightPercent": 6},
         {"dueDate": "2026-10-12", "courseCode": "CS 4ML3", "title": "Mid <term>", "dateApproximate": True}],
        date(2026, 10, 8), 7)
    assert subject == "Syllabus Agent: 2 deadlines in the next 7 days"
    assert "- Fri Oct 09 23:59: CS 3GC3 A1 (6%)" in text and "~Mon Oct 12" in text
    assert "Mid &lt;term&gt;" in html_body                                      # escaped


def test_daily_job_skips_empty_days_and_isolates_failures(monkeypatch):
    monkeypatch.setattr(db, "notification_subscribers", lambda: [
        {"userId": "a", "email": "a@x.com", "daysAhead": Decimal(3)},
        {"userId": "b", "email": "b@x.com", "daysAhead": Decimal(3)},
        {"userId": "c", "email": "c@x.com", "daysAhead": Decimal(3)},
    ])

    def fake_send(user, email, days, today):
        if user == "b":
            raise RuntimeError("Email address is not verified")
        return 2 if user == "a" else None

    monkeypatch.setattr(notify, "send_digest", fake_send)
    assert notify_daily.handler({}, None) == {"sent": 1, "skipped": 1, "failed": 1}
