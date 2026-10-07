"""Single-table layout.

  pk                  sk               gsi1pk          gsi1sk
  SYLLABUS#<id>       META             USER#<sub>      SYLLABUS#<createdAt>
  SYLLABUS#<id>       DEADLINE#<nnn>   USER#<sub>      DUE#<yyyy-mm-dd>#<id>#<nnn>   (dated)
                                                       UNDATED#<id>#<nnn>            (no date found)
  SYLLABUS#<id>       CHUNK#<nnnn>     -               -

The GSI answers the two per-user questions: "my syllabi" and "what's due between A and B".
"""
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from lib import aws

GSI = "gsi1"


def syllabus_pk(syllabus_id):
    return f"SYLLABUS#{syllabus_id}"


def user_pk(user_id):
    return f"USER#{user_id}"


def deadline_gsi_sk(syllabus_id, n, due_date):
    if due_date:
        return f"DUE#{due_date}#{syllabus_id}#{n:03d}"
    return f"UNDATED#{syllabus_id}#{n:03d}"


def _query_all(**kwargs):
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = aws.table().query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def get_meta(syllabus_id):
    return aws.table().get_item(Key={"pk": syllabus_pk(syllabus_id), "sk": "META"}).get("Item")


def get_owned_meta(syllabus_id, user_id):
    meta = get_meta(syllabus_id)
    return meta if meta and meta.get("ownerId") == user_id else None


def list_syllabi(user_id):
    return _query_all(
        IndexName=GSI,
        KeyConditionExpression=Key("gsi1pk").eq(user_pk(user_id)) & Key("gsi1sk").begins_with("SYLLABUS#"),
    )


def list_items(syllabus_id, prefix):
    return _query_all(
        KeyConditionExpression=Key("pk").eq(syllabus_pk(syllabus_id)) & Key("sk").begins_with(prefix),
    )


def deadlines_between(user_id, start_date, end_date):
    """Inclusive ISO dates. '~' sorts after '#' and digits, so it closes the range on end_date."""
    return _query_all(
        IndexName=GSI,
        KeyConditionExpression=Key("gsi1pk").eq(user_pk(user_id))
        & Key("gsi1sk").between(f"DUE#{start_date}", f"DUE#{end_date}~"),
    )


def all_deadlines(user_id):
    dated = _query_all(
        IndexName=GSI,
        KeyConditionExpression=Key("gsi1pk").eq(user_pk(user_id)) & Key("gsi1sk").begins_with("DUE#"),
    )
    undated = _query_all(
        IndexName=GSI,
        KeyConditionExpression=Key("gsi1pk").eq(user_pk(user_id)) & Key("gsi1sk").begins_with("UNDATED#"),
    )
    return dated + undated


def delete_items(syllabus_id, prefix):
    items = list_items(syllabus_id, prefix)
    with aws.table().batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    return len(items)


def plain(value):
    """DynamoDB Decimals -> int/float, recursively."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def public_deadline(item):
    """Strip key attributes before returning to clients / the model."""
    keep = ("syllabusId", "courseCode", "title", "type", "dueDate", "dueTime", "weightPercent",
            "dateApproximate", "week", "sourceText", "page")
    return {k: plain(item[k]) for k in keep if k in item and item[k] is not None}


def public_syllabus(meta):
    keep = ("syllabusId", "filename", "status", "error", "courseCode", "courseTitle", "termStart",
            "deadlineCount", "pageCount", "warnings", "createdAt", "processedAt")
    return {k: plain(meta[k]) for k in keep if k in meta and meta[k] is not None}
