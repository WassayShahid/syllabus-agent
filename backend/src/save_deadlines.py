"""Pipeline step 5: write validated deadlines. Replaces earlier rows, so retries are idempotent.

Output: {"deadlineCount": n} under $.saved
"""
from lib import aws, db


def handler(event, context):
    syllabus_id = event["syllabusId"]
    validated = event["validated"]
    course_code = validated.get("courseCode") or event.get("filename")

    db.delete_items(syllabus_id, "DEADLINE#")
    with aws.table().batch_writer() as batch:
        for n, d in enumerate(validated["deadlines"], start=1):
            batch.put_item(Item=db.deadline_item(syllabus_id, event["ownerId"], n, d, course_code))

    db.update_meta(
        syllabus_id,
        courseCode=validated.get("courseCode"),
        courseTitle=validated.get("courseTitle"),
        deadlineCount=len(validated["deadlines"]),
        warnings=validated.get("warnings", []),
    )
    return {"deadlineCount": len(validated["deadlines"])}
