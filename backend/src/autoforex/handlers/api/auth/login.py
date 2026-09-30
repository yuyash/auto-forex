"""Authenticate a Cognito user and return JWTs."""

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
        result = _cognito.initiate_auth(
            ClientId=os.environ["USER_POOL_CLIENT_ID"],
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
    except RequestError as error:
        return error_response(400, str(error))
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code == "UserNotConfirmedException":
            return error_response(403, "User confirmation is required.")
        if code == "PasswordResetRequiredException":
            return error_response(403, "A password reset is required.")
        if code in {"NotAuthorizedException", "UserNotFoundException"}:
            return error_response(401, "The email or password is incorrect.")
        return error_response(500, "Login failed.")

    authentication = result.get("AuthenticationResult")
    if not authentication:
        return error_response(401, "Additional authentication is required.")
    return response(
        200,
        {
            "access_token": authentication["AccessToken"],
            "id_token": authentication["IdToken"],
            "refresh_token": authentication.get("RefreshToken"),
            "expires_in": authentication["ExpiresIn"],
            "token_type": authentication["TokenType"],
        },
    )
