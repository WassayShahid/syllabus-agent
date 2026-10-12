"""Deadline reminder emails via Amazon SES.

New AWS accounts start in the SES *sandbox*: mail can only go to verified addresses. With
SES_SANDBOX=true, turning reminders on sends the user AWS's one-click verification email first.
"""
import html
import os
from datetime import date, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

import boto3

from lib import db

DAYS_AHEAD_CHOICES = (1, 3, 7, 14)


@cache
def ses():
    return boto3.client("ses")


def configured():
    return bool(os.environ.get("NOTIFY_FROM_EMAIL"))


def sandbox():
    return os.environ.get("SES_SANDBOX", "true").lower() == "true"


def local_today():
    """'Today' where the students are, not in UTC."""
    return datetime.now(ZoneInfo(os.environ.get("NOTIFY_TIMEZONE", "America/Toronto"))).date()


def is_verified(email):
    attrs = ses().get_identity_verification_attributes(Identities=[email])["VerificationAttributes"]
    return attrs.get(email, {}).get("VerificationStatus") == "Success"


def request_verification(email):
    """Sandbox only: AWS emails the address a verification link. Returns True if one was sent."""
    if not sandbox() or is_verified(email):
        return False
    ses().verify_email_identity(EmailAddress=email)
    return True


def upcoming(user_id, today, days_ahead):
    items = db.deadlines_between(user_id, today.isoformat(), (today + timedelta(days=days_ahead)).isoformat())
    return sorted((db.public_deadline(i) for i in items), key=lambda d: (d["dueDate"], d.get("dueTime") or ""))


def _line(d):
    when = date.fromisoformat(d["dueDate"]).strftime("%a %b %d")
    if d.get("dueTime"):
        when += f" {d['dueTime']}"
    if d.get("dateApproximate"):
        when = f"~{when}"
    weight = f" ({d['weightPercent']:g}%)" if d.get("weightPercent") is not None else ""
    return when, f"{d.get('courseCode') or ''} {d['title']}".strip() + weight


def build_digest(deadlines, today, days_ahead):
    """Returns (subject, text, html)."""
    app_url = os.environ.get("APP_URL", "")
    if deadlines:
        subject = f"{len(deadlines)} deadline{'s' if len(deadlines) != 1 else ''} in the next {days_ahead} days"
        lines = [_line(d) for d in deadlines]
        intro = f"Coming up between {today:%b %d} and {today + timedelta(days=days_ahead):%b %d}:"
    else:
        subject, lines = f"Nothing due in the next {days_ahead} days", []
        intro = "Nothing is due in that window. Enjoy it."
    footer = "Turn reminders off in Settings" + (f": {app_url}settings" if app_url else ".")

    text = "\n".join([intro, "", *(f"- {w}: {t}" for w, t in lines), "", footer])
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;white-space:nowrap'><b>{html.escape(w)}</b></td>"
                   f"<td style='padding:4px 0'>{html.escape(t)}</td></tr>" for w, t in lines)
    body = (f"<p>{html.escape(intro)}</p><table style='border-collapse:collapse'>{rows}</table>"
            f"<p style='color:#666;font-size:13px'>{html.escape(footer)}</p>")
    return f"Syllabus Agent: {subject}", text, body


def send(to, subject, text, html_body):
    ses().send_email(
        Source=os.environ["NOTIFY_FROM_EMAIL"],
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": text, "Charset": "UTF-8"}, "Html": {"Data": html_body, "Charset": "UTF-8"}},
        },
    )


def send_digest(user_id, email, days_ahead, today=None, skip_if_empty=True):
    """Email the user what's due soon. Returns the number of deadlines included, or None if skipped."""
    today = today or local_today()
    deadlines = upcoming(user_id, today, days_ahead)
    if skip_if_empty and not deadlines:
        return None
    send(email, *build_digest(deadlines, today, days_ahead))
    return len(deadlines)
