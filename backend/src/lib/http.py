"""API Gateway (HTTP API, payload v2) helpers."""
import json
from decimal import Decimal


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"not serializable: {type(o)}")


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def user_id(event):
    """Cognito `sub` from the JWT authorizer; None if the route isn't authorized."""
    claims = (event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {}))
    return claims.get("sub")


def json_body(event):
    """Returns (body_dict, error_response)."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return None, response(400, {"error": "Body must be valid JSON"})
    if not isinstance(body, dict):
        return None, response(400, {"error": "Body must be a JSON object"})
    return body, None
