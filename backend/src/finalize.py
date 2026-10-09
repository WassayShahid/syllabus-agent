"""Pipeline last step: both branches done -> READY.

$.results is {"saved": {...}, "indexed": {...}} (trimmed by the Parallel state's result selector).
"""
from datetime import datetime, timezone

from lib import db


def handler(event, context):
    results = event["results"]
    db.update_meta(
        event["syllabusId"],
        status="READY",
        processedAt=datetime.now(timezone.utc).isoformat(),
        chunkCount=results["indexed"]["chunkCount"],
        pageCount=event["text"]["pageCount"],
    )
    return {"syllabusId": event["syllabusId"], "deadlineCount": results["saved"]["deadlineCount"]}
