"""API Gateway (HTTP API, payload v2) helpers."""
import json

from lib.db import plain


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(plain(body)),
    }


def _claims(event):
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})


def user_id(event):
    """Cognito `sub` from the JWT authorizer; None if the route isn't authorized."""
    return _claims(event).get("sub")


def user_email(event):
    """Verified sign-in email from the Cognito ID token."""
    return _claims(event).get("email")


def json_body(event):
    """Returns (body_dict, error_response)."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return None, response(400, {"error": "Body must be valid JSON"})
    if not isinstance(body, dict):
        return None, response(400, {"error": "Body must be a JSON object"})
    return body, None
