"""Read/delete API for the frontend (one Lambda, routed on the HTTP API routeKey).

GET    /syllabi            -> the user's syllabi, newest first
GET    /syllabi/{id}       -> one syllabus + its deadlines (used to poll processing status)
DELETE /syllabi/{id}       -> remove a syllabus, its rows and its files
GET    /deadlines          -> all deadlines; ?days=N&today=YYYY-MM-DD for the next N days only
"""
from datetime import date, datetime, timedelta, timezone

from lib import aws, db
from lib.http import response, user_id


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


ROUTES = {
    "GET /syllabi": list_syllabi,
    "GET /syllabi/{id}": get_syllabus,
    "DELETE /syllabi/{id}": delete_syllabus,
    "GET /deadlines": list_deadlines,
}


def handler(event, context):
    user = user_id(event)
    if not user:
        return response(401, {"error": "Unauthorized"})
    route = ROUTES.get(event.get("routeKey"))
    if route is None:
        return response(404, {"error": "No such route"})
    return route(user, event)
