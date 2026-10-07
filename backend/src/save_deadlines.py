"""Pipeline step 5: write validated deadlines. Replaces earlier rows, so retries are idempotent.

Output: {"deadlineCount": n} under $.saved
"""
from decimal import Decimal

from lib import aws, db


def handler(event, context):
    syllabus_id = event["syllabusId"]
    owner = event["ownerId"]
    validated = event["validated"]

    db.delete_items(syllabus_id, "DEADLINE#")
    with aws.table().batch_writer() as batch:
        for n, d in enumerate(validated["deadlines"], start=1):
            item = {
                "pk": db.syllabus_pk(syllabus_id),
                "sk": f"DEADLINE#{n:03d}",
                "gsi1pk": db.user_pk(owner),
                "gsi1sk": db.deadline_gsi_sk(syllabus_id, n, d["dueDate"]),
                "syllabusId": syllabus_id,
                "courseCode": validated.get("courseCode") or event.get("filename"),
                **{k: v for k, v in d.items() if v is not None},
            }
            if "weightPercent" in item:
                item["weightPercent"] = _decimal(item["weightPercent"])
            batch.put_item(Item=item)

    meta_update = {
        "courseCode": validated.get("courseCode"),
        "courseTitle": validated.get("courseTitle"),
        "deadlineCount": len(validated["deadlines"]),
        "warnings": validated.get("warnings", []),
    }
    aws.table().update_item(
        Key={"pk": db.syllabus_pk(syllabus_id), "sk": "META"},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in meta_update),
        ExpressionAttributeNames={f"#{k}": k for k in meta_update},
        ExpressionAttributeValues={f":{k}": v for k, v in meta_update.items()},
    )
    return {"deadlineCount": len(validated["deadlines"])}


def _decimal(value):
    return Decimal(str(value))
