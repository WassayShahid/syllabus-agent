"""CRUD API for the frontend (one Lambda, routed on the HTTP API routeKey).

GET    /syllabi                        -> the user's syllabi, newest first
GET    /syllabi/{id}                   -> one syllabus + its deadlines (used to poll processing status)
DELETE /syllabi/{id}                   -> remove a syllabus, its rows and its files
POST   /syllabi/{id}/deadlines         -> add a deadline by hand
PATCH  /syllabi/{id}/deadlines/{n}     -> correct a deadline (title, type, date, time, weight)
DELETE /syllabi/{id}/deadlines/{n}     -> remove a deadline
GET    /deadlines                      -> all deadlines; ?days=N&today=YYYY-MM-DD for the next N days only
GET    /settings                       -> email reminder settings
PUT    /settings                       -> {"emailEnabled": bool, "daysAhead": 1|3|7|14}
POST   /settings/test-email            -> send the reminder email now (even if nothing is due)
"""
import re
from datetime import date, datetime, timedelta, timezone

from botocore.exceptions import ClientError

from lib import aws, db, notify
from lib.http import json_body, response, user_email, user_id
from validate import USER_FIELDS, clean_user_deadline


# ---------------- syllabi ----------------
def list_syllabi(user, event):
    items = sorted(db.list_syllabi(user), key=lambda m: m.get("createdAt", ""), reverse=True)
    return response(200, {"syllabi": [db.public_syllabus(m) for m in items]})


def get_syllabus(user, event):
    meta = db.get_owned_meta(event["pathParameters"]["id"], user)
    if not meta:
        return response(404, {"error": "Not found"})
    deadlines = db.list_items(meta["syllabusId"], "DEADLINE#")
    return response(200, {"syllabus": db.public_syllabus(meta),
                          "deadlines": [db.public_deadline(d) for d in deadlines]})


def delete_syllabus(user, event):
    meta = db.get_owned_meta(event["pathParameters"]["id"], user)
    if not meta:
        return response(404, {"error": "Not found"})
    syllabus_id = meta["syllabusId"]
    for key in (meta.get("s3Key"), f"text/{syllabus_id}.json"):
        if key:
            aws.s3().delete_object(Bucket=aws.bucket_name(), Key=key)
    db.delete_items(syllabus_id, "DEADLINE#")
    db.delete_items(syllabus_id, "CHUNK#")
    aws.table().delete_item(Key={"pk": db.syllabus_pk(syllabus_id), "sk": "META"})
    return response(200, {"deleted": syllabus_id})


# ---------------- deadlines ----------------
def _deadline_number(event):
    n = event["pathParameters"].get("n", "")
    return int(n) if re.fullmatch(r"\d{1,3}", n) else None


def _save_deadline(meta, n, fields, source, approximate=False):
    deadline, error = clean_user_deadline(fields)
    if error:
        return response(400, {"error": error})
    deadline["dateApproximate"] = approximate
    course = meta.get("courseCode") or meta.get("filename")
    item = db.deadline_item(meta["syllabusId"], meta["ownerId"], n, {**fields, **deadline, "source": source}, course)
    aws.table().put_item(Item=item)
    db.update_meta(meta["syllabusId"], deadlineCount=len(db.list_items(meta["syllabusId"], "DEADLINE#")))
    return response(200, {"deadline": db.public_deadline(item)})


def add_deadline(user, event):
    meta = db.get_owned_meta(event["pathParameters"]["id"], user)
    if not meta:
        return response(404, {"error": "Not found"})
    body, error = json_body(event)
    if error:
        return error
    existing = db.list_items(meta["syllabusId"], "DEADLINE#")
    n = max((int(i["sk"].split("#")[1]) for i in existing), default=0) + 1
    return _save_deadline(meta, n, {k: body.get(k) for k in USER_FIELDS}, "manual")


def update_deadline(user, event):
    meta = db.get_owned_meta(event["pathParameters"]["id"], user)
    n = _deadline_number(event)
    current = n and meta and aws.table().get_item(
        Key={"pk": db.syllabus_pk(meta["syllabusId"]), "sk": f"DEADLINE#{n:03d}"}).get("Item")
    if not current:
        return response(404, {"error": "Not found"})
    body, error = json_body(event)
    if error:
        return error
    # keep the extracted evidence (sourceText, page, week); replace only the editable fields
    kept = {k: v for k, v in db.plain(current).items()
            if k in ("sourceText", "page", "week") or k in USER_FIELDS}
    merged = {**kept, **{k: body[k] for k in USER_FIELDS if k in body}}
    source = "manual" if current.get("source") == "manual" else "edited"
    # a week-based date stays "approximate" until the user actually sets the date
    approximate = bool(current.get("dateApproximate")) and "dueDate" not in body
    return _save_deadline(meta, n, merged, source, approximate)


def delete_deadline(user, event):
    meta = db.get_owned_meta(event["pathParameters"]["id"], user)
    n = _deadline_number(event)
    if not meta or not n:
        return response(404, {"error": "Not found"})
    aws.table().delete_item(Key={"pk": db.syllabus_pk(meta["syllabusId"]), "sk": f"DEADLINE#{n:03d}"})
    db.update_meta(meta["syllabusId"], deadlineCount=len(db.list_items(meta["syllabusId"], "DEADLINE#")))
    return response(200, {"deleted": f"{n:03d}"})


def list_deadlines(user, event):
    params = event.get("queryStringParameters") or {}
    if params.get("days"):
        try:
            days = max(1, min(int(params["days"]), 366))
            today = date.fromisoformat(params["today"]) if params.get("today") else datetime.now(timezone.utc).date()
        except ValueError:
            return response(400, {"error": "days must be an integer and today YYYY-MM-DD"})
        items = db.deadlines_between(user, today.isoformat(), (today + timedelta(days=days)).isoformat())
    else:
        items = db.all_deadlines(user)
    return response(200, {"deadlines": [db.public_deadline(i) for i in items]})


# ---------------- reminder settings ----------------
def get_settings(user, event):
    settings = db.get_settings(user)
    return response(200, {**settings, "email": user_email(event), "available": notify.configured()})


def put_settings(user, event):
    if not notify.configured():
        return response(503, {"error": "Email reminders aren't set up on this deployment."})
    body, error = json_body(event)
    if error:
        return error
    enabled = body.get("emailEnabled")
    days = body.get("daysAhead", db.DEFAULT_SETTINGS["daysAhead"])
    if not isinstance(enabled, bool) or days not in notify.DAYS_AHEAD_CHOICES:
        return response(400, {"error": f"emailEnabled must be true/false; daysAhead one of {notify.DAYS_AHEAD_CHOICES}"})
    email = user_email(event)
    if enabled and not email:
        return response(400, {"error": "Your account has no email address."})

    verification_sent = notify.request_verification(email) if enabled else False
    db.put_settings(user, email, enabled, days, datetime.now(timezone.utc).isoformat())
    return response(200, {"emailEnabled": enabled, "daysAhead": days, "email": email,
                          "available": True, "verificationSent": verification_sent})


def test_email(user, event):
    if not notify.configured():
        return response(503, {"error": "Email reminders aren't set up on this deployment."})
    email = user_email(event)
    settings = db.get_settings(user)
    try:
        count = notify.send_digest(user, email, settings["daysAhead"], skip_if_empty=False)
    except ClientError as e:
        if notify.sandbox() and e.response["Error"]["Code"] == "MessageRejected":
            return response(409, {"error": "Confirm your address first: click the link in the email from "
                                           "Amazon Web Services, then try again."})
        raise
    return response(200, {"sentTo": email, "deadlineCount": count})


ROUTES = {
    "GET /syllabi": list_syllabi,
    "GET /syllabi/{id}": get_syllabus,
    "DELETE /syllabi/{id}": delete_syllabus,
    "POST /syllabi/{id}/deadlines": add_deadline,
    "PATCH /syllabi/{id}/deadlines/{n}": update_deadline,
    "DELETE /syllabi/{id}/deadlines/{n}": delete_deadline,
    "GET /deadlines": list_deadlines,
    "GET /settings": get_settings,
    "PUT /settings": put_settings,
    "POST /settings/test-email": test_email,
}


def handler(event, context):
    user = user_id(event)
    if not user:
        return response(401, {"error": "Unauthorized"})
    route = ROUTES.get(event.get("routeKey"))
    if route is None:
        return response(404, {"error": "No such route"})
    return route(user, event)
