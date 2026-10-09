"""Failure branch: any step's uncaught error lands here -> status FAILED with a readable reason.

Errors listed here get a friendlier message; the rest (e.g. NoTextError) already raise one.
"""
import json

from lib import db

FRIENDLY = {
    "ModelRefusalError": "The AI model declined to process this document.",
    "ExtractionFormatError": "The AI model returned an unexpected format. Try re-uploading.",
    "RetryableModelError": "The AI service was busy. Try re-uploading in a few minutes.",
    "States.Timeout": "Processing timed out.",
}


def _cause_message(cause):
    try:
        return json.loads(cause or "{}").get("errorMessage")
    except (TypeError, json.JSONDecodeError, AttributeError):
        return None


def handler(event, context):
    error = event.get("error") or {}
    name = error.get("Error", "Unknown")
    message = FRIENDLY.get(name) or _cause_message(error.get("Cause")) or "Processing failed."
    print(json.dumps({"failed": event.get("syllabusId"), "error": name, "cause": error.get("Cause")}))

    if event.get("syllabusId"):
        db.update_meta(event["syllabusId"], status="FAILED", error=message[:500])
    return {"status": "FAILED", "error": name}
