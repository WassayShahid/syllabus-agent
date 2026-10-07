"""Pipeline last step: both branches done -> READY.

$.results is {"saved": {...}, "indexed": {...}} (trimmed by the Parallel state's result selector).
"""
from datetime import datetime, timezone

from lib import aws, db


def handler(event, context):
    results = event["results"]
    aws.table().update_item(
        Key={"pk": db.syllabus_pk(event["syllabusId"]), "sk": "META"},
        UpdateExpression="SET #s = :s, processedAt = :t, chunkCount = :c, pageCount = :p",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "READY",
            ":t": datetime.now(timezone.utc).isoformat(),
            ":c": results["indexed"]["chunkCount"],
            ":p": event["text"]["pageCount"],
        },
    )
    return {"syllabusId": event["syllabusId"], "deadlineCount": results["saved"]["deadlineCount"]}
