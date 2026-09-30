"""Return the authenticated user's application profile."""

from __future__ import annotations

import os
from typing import Any

import boto3

from autoforex.handlers.api.common import RequestError, error_response, response, subject

_table = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE_NAME"])


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        user_id = subject(event)
    except RequestError as error:
        return error_response(401, str(error))

    item = _table.get_item(Key={"user_id": user_id}, ConsistentRead=True).get("Item")
    if not item:
        return error_response(404, "User profile not found.")

    profile = {
        key: item[key]
        for key in (
            "user_id",
            "username",
            "email",
            "environment",
            "status",
            "stream_enabled",
            "oanda_environment",
            "oanda_account_id",
            "symbols",
            "created_at",
            "updated_at",
        )
        if key in item
    }
    profile["oanda_token_registered"] = bool(item.get("oanda_secret_id"))
    return response(200, profile)
