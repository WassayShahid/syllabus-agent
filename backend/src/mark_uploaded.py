"""Pipeline step 1: S3 "Object Created" (via EventBridge) -> mark the syllabus PROCESSING.

Input:  the EventBridge event that started the state machine.
Output: the pipeline context every later step receives.
"""
from datetime import datetime, timezone
from urllib.parse import unquote_plus

from lib import aws, db


class UnknownUploadError(Exception):
    """Object wasn't registered through POST /uploads. Not retried."""


def handler(event, context):
    detail = event["detail"]
    bucket = detail["bucket"]["name"]
    key = unquote_plus(detail["object"]["key"])
    size = detail["object"].get("size", 0)
    # keys look like uploads/<syllabusId>.pdf
    syllabus_id = key.rsplit("/", 1)[-1].removesuffix(".pdf")

    try:
        meta = aws.table().update_item(
            Key={"pk": db.syllabus_pk(syllabus_id), "sk": "META"},
            UpdateExpression="SET #s = :s, sizeBytes = :size, uploadedAt = :t REMOVE #e",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={
                ":s": "PROCESSING",
                ":size": size,
                ":t": datetime.now(timezone.utc).isoformat(),
            },
            # skip objects that weren't registered via POST /uploads
            ConditionExpression="attribute_exists(pk)",
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except aws.table().meta.client.exceptions.ConditionalCheckFailedException:
        raise UnknownUploadError(f"No record for {key}")

    print(f"Processing {syllabus_id} ({size} bytes)")
    return {
        "syllabusId": syllabus_id,
        "ownerId": meta["ownerId"],
        "bucket": bucket,
        "key": key,
        "filename": meta.get("filename", ""),
        "termStart": meta.get("termStart"),
    }
