"""Failure branch: any step's uncaught error lands here -> status FAILED with a readable reason."""
import json

from lib import aws, db

FRIENDLY = {
    "NoTextError": None,              # message is already user-facing
    "SyllabusTooLargeError": None,
    "ModelRefusalError": "The AI model declined to process this document.",
    "ExtractionFormatError": "The AI model returned an unexpected format. Try re-uploading.",
    "RetryableModelError": "The AI service was busy. Try re-uploading in a few minutes.",
    "States.Timeout": "Processing timed out.",
}


def handler(event, context):
    error = event.get("error") or {}
    name = error.get("Error", "Unknown")
    message = FRIENDLY.get(name)
    if message is None:
        try:
            message = json.loads(error.get("Cause", "{}")).get("errorMessage")
        except (TypeError, json.JSONDecodeError):
            message = None
    message = message or "Processing failed."
    print(json.dumps({"failed": event.get("syllabusId"), "error": name, "cause": error.get("Cause")}))

    if event.get("syllabusId"):
        aws.table().update_item(
            Key={"pk": db.syllabus_pk(event["syllabusId"]), "sk": "META"},
            UpdateExpression="SET #s = :s, #e = :e",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":s": "FAILED", ":e": message[:500]},
        )
    return {"status": "FAILED", "error": name}
