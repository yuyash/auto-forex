"""Create Users records after Cognito confirmation."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import boto3

_table = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE_NAME"])


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    attributes = event["request"]["userAttributes"]
    now = datetime.now(UTC).isoformat()
    _table.update_item(
        Key={"user_id": attributes["sub"]},
        UpdateExpression=(
            "SET username = :username, email = :email, #environment = :environment, "
            "#status = if_not_exists(#status, :status), "
            "stream_enabled = if_not_exists(stream_enabled, :disabled), "
            "created_at = if_not_exists(created_at, :now), updated_at = :now"
        ),
        ExpressionAttributeNames={"#environment": "environment", "#status": "status"},
        ExpressionAttributeValues={
            ":username": event["userName"],
            ":email": attributes.get("email", ""),
            ":environment": os.environ["DEPLOYMENT_ENVIRONMENT"],
            ":status": "ACTIVE",
            ":disabled": False,
            ":now": now,
        },
    )
    return event
