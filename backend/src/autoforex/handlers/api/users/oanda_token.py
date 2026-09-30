"""Store the authenticated user's OANDA token in Secrets Manager."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from autoforex.handlers.api.common import (
    RequestError,
    error_response,
    json_body,
    required_string,
    response,
    subject,
)

_secrets = boto3.client("secretsmanager")
_table = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE_NAME"])


def _secret_id(user_id: str) -> str:
    digest = hashlib.sha256(user_id.encode()).hexdigest()
    return f"auto-forex/{os.environ['DEPLOYMENT_ENVIRONMENT']}/oanda/{digest}"


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        user_id = subject(event)
    except RequestError as error:
        return error_response(401, str(error))
    try:
        token = required_string(json_body(event), "token")
    except RequestError as error:
        return error_response(400, str(error))

    if not _table.get_item(Key={"user_id": user_id}, ConsistentRead=True).get("Item"):
        return error_response(404, "User profile not found.")

    secret_id = _secret_id(user_id)
    secret_string = json.dumps({"token": token}, separators=(",", ":"))
    try:
        _secrets.create_secret(
            Name=secret_id,
            SecretString=secret_string,
            Description="OANDA API token managed by auto-forex",
            Tags=[{"Key": "Project", "Value": "auto-forex"}],
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceExistsException":
            return error_response(500, "OANDA token registration failed.")
        try:
            _secrets.put_secret_value(SecretId=secret_id, SecretString=secret_string)
        except ClientError:
            return error_response(500, "OANDA token registration failed.")

    _table.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET oanda_secret_id = :secret_id, updated_at = :now",
        ExpressionAttributeValues={
            ":secret_id": secret_id,
            ":now": datetime.now(UTC).isoformat(),
        },
        ConditionExpression="attribute_exists(user_id)",
    )
    return response(200, {"registered": True})
