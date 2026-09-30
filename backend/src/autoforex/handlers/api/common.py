"""Shared helpers for API Gateway HTTP API Lambda handlers."""

from __future__ import annotations

import base64
import json
from typing import Any


class RequestError(ValueError):
    """An error caused by an invalid client request."""


def json_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if not isinstance(body, str) or not body:
        raise RequestError("A JSON request body is required.")
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode()
        except (ValueError, UnicodeDecodeError) as error:
            raise RequestError("The request body is not valid base64-encoded UTF-8.") from error
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise RequestError("The request body must be valid JSON.") from error
    if not isinstance(value, dict):
        raise RequestError("The request body must be a JSON object.")
    return value


def required_string(body: dict[str, Any], name: str, *, maximum: int = 4096) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RequestError(f"{name} must be a non-empty string.")
    if len(value) > maximum:
        raise RequestError(f"{name} must contain at most {maximum} characters.")
    return value


def subject(event: dict[str, Any]) -> str:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    value = claims.get("sub")
    if not isinstance(value, str) or not value:
        raise RequestError("The authenticated user identifier is missing.")
    return value


def response(status_code: int, body: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"statusCode": status_code}
    if body is not None:
        result["headers"] = {"content-type": "application/json"}
        result["body"] = json.dumps(body, separators=(",", ":"))
    return result


def error_response(status_code: int, message: str) -> dict[str, Any]:
    return response(status_code, {"message": message})
