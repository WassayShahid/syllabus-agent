"""Pipeline step 5: write validated deadlines. Replaces earlier rows, so retries are idempotent.

Output: {"deadlineCount": n} under $.saved
"""
from decimal import Decimal

from lib import aws, db


def _dynamo(value):
    """DynamoDB rejects Python floats."""
    return Decimal(str(value)) if isinstance(value, float) else value


def handler(event, context):
    syllabus_id = event["syllabusId"]
    validated = event["validated"]
    course_code = validated.get("courseCode") or event.get("filename")

    db.delete_items(syllabus_id, "DEADLINE#")
    with aws.table().batch_writer() as batch:
        for n, d in enumerate(validated["deadlines"], start=1):
            batch.put_item(Item={
                "pk": db.syllabus_pk(syllabus_id),
                "sk": f"DEADLINE#{n:03d}",
                "gsi1pk": db.user_pk(event["ownerId"]),
                "gsi1sk": db.deadline_gsi_sk(syllabus_id, n, d["dueDate"]),
                "syllabusId": syllabus_id,
                "courseCode": course_code,
                **{k: _dynamo(v) for k, v in d.items() if v is not None},
            })

    db.update_meta(
        syllabus_id,
        courseCode=validated.get("courseCode"),
        courseTitle=validated.get("courseTitle"),
        deadlineCount=len(validated["deadlines"]),
        warnings=validated.get("warnings", []),
    )
    return {"deadlineCount": len(validated["deadlines"])}
