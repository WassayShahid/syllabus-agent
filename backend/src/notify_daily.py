"""Daily job (EventBridge schedule): email each opted-in user what's due in their window.

Days with nothing due send nothing. One user's failure (e.g. an unverified address while SES is in
sandbox mode) is logged and skipped, so it can't block everyone else's reminder.
"""
from lib import db, metrics, notify


def handler(event, context):
    today = notify.local_today()
    sent = skipped = failed = 0
    for sub in db.notification_subscribers():
        try:
            count = notify.send_digest(sub["userId"], sub["email"], int(sub.get("daysAhead", 3)), today)
            sent, skipped = (sent + 1, skipped) if count else (sent, skipped + 1)
        except Exception as e:          # noqa: BLE001 - one bad address must not stop the batch
            failed += 1
            print(f"reminder for {sub.get('userId')} failed: {e}")
    metrics.emit("notify_daily", {"EmailsSent": sent, "EmailsSkipped": skipped, "EmailsFailed": failed})
    return {"sent": sent, "skipped": skipped, "failed": failed}
