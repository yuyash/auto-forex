"""Register a user in Cognito."""

from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from autoforex.handlers.api.common import (
    RequestError,
    error_response,
    json_body,
    required_string,
    response,
)

_cognito = boto3.client("cognito-idp")


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        body = json_body(event)
        email = required_string(body, "email", maximum=320).strip().lower()
        password = required_string(body, "password", maximum=256)
        result = _cognito.sign_up(
            ClientId=os.environ["USER_POOL_CLIENT_ID"],
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
    except RequestError as error:
        return error_response(400, str(error))
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code == "UsernameExistsException":
            return error_response(409, "A user with this email already exists.")
        if code in {"InvalidParameterException", "InvalidPasswordException"}:
            return error_response(400, "The email or password does not meet the requirements.")
        return error_response(500, "User registration failed.")

    delivery = result.get("CodeDeliveryDetails", {})
    return response(
        201,
        {
            "user_id": result["UserSub"],
            "confirmation_required": not result.get("UserConfirmed", False),
            "delivery_destination": delivery.get("Destination"),
        },
    )
