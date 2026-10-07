"""Pipeline step 4: re-check the model's output in code. Nothing reaches the database unvalidated.

- coerces types, drops entries without a title, normalises unknown types to "other"
- resolves "Week N" to a date deterministically from the term start (LLM date math is the
  classic failure mode), flagging it `dateApproximate` when no weekday was given
- rejects impossible dates/times/weights, flags dates far outside the term
- dedupes, and warns when weights don't add up to ~100%

Output: {"courseCode", "courseTitle", "deadlines", "warnings"} under $.validated
"""
import re
from datetime import date, timedelta

from extract_deadlines import DEADLINE_TYPES, WEEKDAYS

TERM_LENGTH_DAYS = 200      # generous: covers a term plus the exam period
MAX_TITLE = 200
MAX_SOURCE = 400


def week_monday(term_start, week):
    """Week 1 is the week containing term_start; weeks start Monday."""
    first_monday = term_start - timedelta(days=term_start.weekday())
    return first_monday + timedelta(weeks=week - 1)


def _parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_time(value):
    if isinstance(value, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value.strip()):
        return value.strip()
    return None


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def validate(extraction, term_start=None):
    term = _parse_date(term_start) if term_start else None
    warnings = []
    cleaned = []
    seen = set()

    for raw in extraction.get("deadlines") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()[:MAX_TITLE]
        if not title:
            warnings.append("Dropped an entry with no title.")
            continue

        kind = raw.get("type") if raw.get("type") in DEADLINE_TYPES else "other"
        week = raw.get("week") if isinstance(raw.get("week"), int) and 1 <= raw.get("week") <= 20 else None
        weekday = raw.get("weekday") if raw.get("weekday") in WEEKDAYS else None
        due = _parse_date(raw.get("dueDate"))
        if raw.get("dueDate") and due is None:
            warnings.append(f"'{title}': unreadable date {raw.get('dueDate')!r} ignored.")

        approximate = False
        if week and term:
            monday = week_monday(term, week)
            computed = monday + timedelta(days=WEEKDAYS.index(weekday)) if weekday else monday
            if due and due != computed and weekday:
                warnings.append(f"'{title}': model said {due}, week {week} {weekday} is {computed}; using {computed}.")
            if weekday or not due:
                due = computed
                approximate = not weekday
        elif week and not term:
            warnings.append(f"'{title}' is in week {week}, but no term start date was given, so it has no date.")

        if due and term and not (term - timedelta(days=14) <= due <= term + timedelta(days=TERM_LENGTH_DAYS)):
            warnings.append(f"'{title}': {due} is far outside the term starting {term}; please check.")

        weight = _number(raw.get("weightPercent"))
        if weight is not None and not 0 <= weight <= 100:
            warnings.append(f"'{title}': weight {weight}% is impossible; ignored.")
            weight = None

        key = (title.lower(), due)
        if key in seen:
            continue
        seen.add(key)

        page = raw.get("page")
        cleaned.append({
            "title": title,
            "type": kind,
            "dueDate": due.isoformat() if due else None,
            "dueTime": _parse_time(raw.get("dueTime")),
            "week": week,
            "dateApproximate": approximate,
            "weightPercent": round(weight, 2) if weight is not None else None,
            "sourceText": str(raw.get("sourceText") or "")[:MAX_SOURCE],
            "page": page if isinstance(page, int) and page > 0 else None,
        })

    if not cleaned:
        warnings.append("No graded deadlines were found in this document.")
    else:
        weights = [d["weightPercent"] for d in cleaned if d["weightPercent"] is not None]
        if weights and len(weights) == len(cleaned):
            total = round(sum(weights), 2)
            if not 95 <= total <= 105:
                warnings.append(f"Weights add up to {total}%, not 100%. Some items may be missing or double-counted.")

    cleaned.sort(key=lambda d: (d["dueDate"] is None, d["dueDate"] or "", d["title"]))
    code = extraction.get("courseCode")
    title = extraction.get("courseTitle")
    return {
        "courseCode": str(code).strip()[:40] if code else None,
        "courseTitle": str(title).strip()[:200] if title else None,
        "deadlines": cleaned,
        "warnings": warnings,
    }


def handler(event, context):
    return validate(event["extraction"], event.get("termStart"))
