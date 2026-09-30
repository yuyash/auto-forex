import hashlib
import json
import os
import unittest
from typing import Any

from botocore.exceptions import ClientError

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("USER_POOL_CLIENT_ID", "client-id")
os.environ.setdefault("USERS_TABLE_NAME", "Users")
os.environ.setdefault("DEPLOYMENT_ENVIRONMENT", "alpha")

from autoforex.handlers.api.auth import login
from autoforex.handlers.api.users import me, oanda_token, signup


def event(body: dict[str, Any] | None = None, subject: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {}
    if body is not None:
        value["body"] = json.dumps(body)
    if subject is not None:
        value["requestContext"] = {"authorizer": {"jwt": {"claims": {"sub": subject}}}}
    return value


class FakeCognito:
    def __init__(self) -> None:
        self.sign_up_request = None
        self.auth_request = None

    def sign_up(self, **request: Any) -> dict[str, Any]:
        self.sign_up_request = request
        return {
            "UserSub": "user-sub",
            "UserConfirmed": False,
            "CodeDeliveryDetails": {"Destination": "t***@example.com"},
        }

    def initiate_auth(self, **request: Any) -> dict[str, Any]:
        self.auth_request = request
        return {
            "AuthenticationResult": {
                "AccessToken": "access",
                "IdToken": "id",
                "RefreshToken": "refresh",
                "ExpiresIn": 3600,
                "TokenType": "Bearer",
            }
        }


class FakeTable:
    def __init__(self, item: dict[str, Any] | None = None) -> None:
        self.item = item
        self.update_request = None

    def get_item(self, **_request: Any) -> dict[str, Any]:
        return {"Item": self.item} if self.item else {}

    def update_item(self, **request: Any) -> None:
        self.update_request = request


class FakeSecrets:
    def __init__(self, exists: bool = False) -> None:
        self.exists = exists
        self.create_request = None
        self.put_request = None

    def create_secret(self, **request: Any) -> None:
        self.create_request = request
        if self.exists:
            raise ClientError(
                {"Error": {"Code": "ResourceExistsException", "Message": "exists"}},
                "CreateSecret",
            )

    def put_secret_value(self, **request: Any) -> None:
        self.put_request = request


class UserApiTest(unittest.TestCase):
    def test_signup_registers_email_with_cognito(self) -> None:
        cognito = FakeCognito()
        original = signup._cognito
        signup._cognito = cognito
        try:
            result = signup.handler(
                event({"email": "Trader@Example.com", "password": "Password123!"}), None
            )
        finally:
            signup._cognito = original

        self.assertEqual(result["statusCode"], 201)
        self.assertEqual(cognito.sign_up_request["Username"], "trader@example.com")
        self.assertEqual(cognito.sign_up_request["ClientId"], "client-id")
        self.assertTrue(json.loads(result["body"])["confirmation_required"])

    def test_login_returns_cognito_jwts(self) -> None:
        cognito = FakeCognito()
        original = login._cognito
        login._cognito = cognito
        try:
            result = login.handler(
                event({"email": "trader@example.com", "password": "Password123!"}), None
            )
        finally:
            login._cognito = original

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["access_token"], "access")
        self.assertEqual(cognito.auth_request["AuthFlow"], "USER_PASSWORD_AUTH")

    def test_current_user_comes_from_jwt_subject_without_secret_id(self) -> None:
        table = FakeTable(
            {
                "user_id": "user-sub",
                "email": "trader@example.com",
                "status": "ACTIVE",
                "oanda_secret_id": "must-not-be-returned",
            }
        )
        original = me._table
        me._table = table
        try:
            result = me.handler(event(subject="user-sub"), None)
        finally:
            me._table = original

        body = json.loads(result["body"])
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["user_id"], "user-sub")
        self.assertTrue(body["oanda_token_registered"])
        self.assertNotIn("oanda_secret_id", body)

    def test_oanda_token_is_stored_under_hashed_subject(self) -> None:
        table = FakeTable({"user_id": "user-sub"})
        secrets = FakeSecrets(exists=True)
        original_table = oanda_token._table
        original_secrets = oanda_token._secrets
        oanda_token._table = table
        oanda_token._secrets = secrets
        try:
            result = oanda_token.handler(event({"token": "oanda-token"}, "user-sub"), None)
        finally:
            oanda_token._table = original_table
            oanda_token._secrets = original_secrets

        digest = hashlib.sha256(b"user-sub").hexdigest()
        expected = f"auto-forex/alpha/oanda/{digest}"
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(secrets.create_request["Name"], expected)
        self.assertEqual(secrets.put_request["SecretId"], expected)
        self.assertEqual(table.update_request["ExpressionAttributeValues"][":secret_id"], expected)

    def test_missing_json_body_is_rejected(self) -> None:
        self.assertEqual(signup.handler({}, None)["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
