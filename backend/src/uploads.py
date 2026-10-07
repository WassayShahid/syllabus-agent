"""POST /uploads -> registers a syllabus and returns a presigned PUT URL.

Body: {"filename": "COMPSCI-3GC3.pdf", "termStart": "2026-09-08"}   (termStart optional)
The browser PUTs the PDF straight to S3; the file never passes through Lambda.
"""
import re
import uuid
from datetime import date, datetime, timezone

from lib import aws, db
from lib.http import json_body, response, user_id

URL_TTL_SECONDS = 300


def handler(event, context):
    owner = user_id(event)
    if not owner:
        return response(401, {"error": "Unauthorized"})

    body, error = json_body(event)
    if error:
        return error

    filename = str(body.get("filename", "")).strip()
    if not filename.lower().endswith(".pdf"):
        return response(400, {"error": "filename must end in .pdf"})

    term_start = body.get("termStart")
    if term_start is not None:
        try:
            term_start = date.fromisoformat(str(term_start)).isoformat()
        except ValueError:
            return response(400, {"error": "termStart must be YYYY-MM-DD"})

    syllabus_id = str(uuid.uuid4())
    key = f"uploads/{syllabus_id}.pdf"
    created_at = datetime.now(timezone.utc).isoformat()

    item = {
        "pk": db.syllabus_pk(syllabus_id),
        "sk": "META",
        "gsi1pk": db.user_pk(owner),
        "gsi1sk": f"SYLLABUS#{created_at}",
        "syllabusId": syllabus_id,
        "ownerId": owner,
        "filename": re.sub(r"[^\w.\- ]", "_", filename)[:200],
        "s3Key": key,
        "status": "PENDING_UPLOAD",
        "createdAt": created_at,
    }
    if term_start:
        item["termStart"] = term_start
    aws.table().put_item(Item=item)

    upload_url = aws.s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": aws.bucket_name(), "Key": key, "ContentType": "application/pdf"},
        ExpiresIn=URL_TTL_SECONDS,
    )

    return response(201, {
        "syllabusId": syllabus_id,
        "uploadUrl": upload_url,
        "key": key,
        "expiresIn": URL_TTL_SECONDS,
    })
