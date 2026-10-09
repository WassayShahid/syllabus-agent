import json

import api
import mark_failed
from lib import db


def authed(route, **extra):
    return {"routeKey": route, "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u"}}}}, **extra}


def test_api_requires_auth_and_known_route():
    assert api.handler({"routeKey": "GET /syllabi"}, None)["statusCode"] == 401
    assert api.handler(authed("GET /nope"), None)["statusCode"] == 404


def test_api_hides_other_users_syllabi(monkeypatch):
    monkeypatch.setattr(db, "get_meta", lambda sid: {"syllabusId": sid, "ownerId": "someone-else"})
    resp = api.handler(authed("GET /syllabi/{id}", pathParameters={"id": "s1"}), None)
    assert resp["statusCode"] == 404


def test_api_lists_syllabi_newest_first(monkeypatch):
    monkeypatch.setattr(db, "list_syllabi", lambda user: [
        {"syllabusId": "old", "createdAt": "2026-09-01", "pk": "x"},
        {"syllabusId": "new", "createdAt": "2026-10-01", "pk": "x"},
    ])
    body = json.loads(api.handler(authed("GET /syllabi"), None)["body"])
    assert [s["syllabusId"] for s in body["syllabi"]] == ["new", "old"]
    assert "pk" not in body["syllabi"][0]


def test_api_rejects_bad_days(monkeypatch):
    resp = api.handler(authed("GET /deadlines", queryStringParameters={"days": "soon"}), None)
    assert resp["statusCode"] == 400


def test_mark_failed_uses_user_facing_message(fake_table):
    cause = json.dumps({"errorMessage": "No selectable text found. Is this a scanned PDF?"})
    mark_failed.handler({"syllabusId": "s1", "error": {"Error": "NoTextError", "Cause": cause}}, None)
    values = fake_table.updates[0]["ExpressionAttributeValues"]
    assert values[":status"] == "FAILED" and values[":error"].startswith("No selectable text")


def test_mark_failed_friendly_for_known_errors(fake_table):
    mark_failed.handler({"syllabusId": "s1", "error": {"Error": "RetryableModelError", "Cause": "{}"}}, None)
    assert "busy" in fake_table.updates[0]["ExpressionAttributeValues"][":error"]


def test_mark_failed_without_syllabus_id_does_not_write(fake_table):
    out = mark_failed.handler({"error": {"Error": "UnknownUploadError"}}, None)
    assert out["status"] == "FAILED" and fake_table.updates == []
