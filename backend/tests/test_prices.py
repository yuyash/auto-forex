import io
import json
import os
import unittest
from decimal import Decimal

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("PRICES_TABLE_NAME", "Prices")
os.environ.setdefault("USERS_TABLE_NAME", "Users")
os.environ.setdefault("DEPLOYMENT_ENVIRONMENT", "alpha")

from autoforex.adapters.aws.appconfig import AppConfigSettingsProvider
from autoforex.adapters.aws.queue import SqsPricePublisher
from autoforex.adapters.aws.secrets import SecretsManagerBrokerCredentialProvider
from autoforex.adapters.aws.users import DynamoDbUserStreamRepository
from autoforex.domain.price import Price
from autoforex.handlers import users as user_handler
from autoforex.handlers.prices import _item


class FakeSqs:
    def __init__(self) -> None:
        self.request = None

    def send_message(self, **request: str) -> None:
        self.request = request


class FakeAppConfig:
    def start_configuration_session(self, **_request: object) -> dict[str, str]:
        return {"InitialConfigurationToken": "first"}

    def get_latest_configuration(self, **_request: object) -> dict[str, object]:
        value = {
            "ingestion_enabled": True,
            "reconnect_max_delay_seconds": 45,
        }
        return {
            "NextPollConfigurationToken": "next",
            "Configuration": io.BytesIO(json.dumps(value).encode()),
        }


class FakeSecrets:
    def get_secret_value(self, **_request: str) -> dict[str, str]:
        return {"SecretString": '{"token":"oanda-token"}'}


class FakeUsersTable:
    def __init__(self) -> None:
        self.update_request = None

    def query(self, **_request: object) -> dict[str, object]:
        return {
            "Items": [
                {
                    "user_id": "cognito-sub",
                    "username": "trader",
                    "oanda_environment": "practice",
                    "oanda_account_id": "001-001-1234567-001",
                    "oanda_secret_id": "auto-forex/alpha/oanda/hash",
                    "symbols": ["USD_JPY", "EUR_USD"],
                }
            ]
        }

    def update_item(self, **request: object) -> None:
        self.update_request = request


class PriceIngestionTest(unittest.TestCase):
    def test_price_message_has_midpoint_and_stable_deduplication_id(self) -> None:
        price = Price("USD_JPY", Decimal("150.02"), Decimal("150.00"), "2026-01-01T00:00:00Z")
        self.assertEqual(price.mid, Decimal("150.01"))
        self.assertEqual(price.message()["mid"], "150.01")
        self.assertEqual(price.deduplication_id(), price.deduplication_id())

    def test_fifo_publisher_sets_symbol_group_and_deduplication_id(self) -> None:
        client = FakeSqs()
        price = Price("EUR_USD", Decimal("1.2"), Decimal("1.1"), "time")
        SqsPricePublisher("queue-url", client).publish(price)
        self.assertEqual(client.request["MessageGroupId"], "EUR_USD")
        self.assertEqual(client.request["MessageDeduplicationId"], price.deduplication_id())

    def test_appconfig_settings_are_parsed(self) -> None:
        settings = AppConfigSettingsProvider("app", "env", "profile", FakeAppConfig()).get()
        self.assertTrue(settings.ingestion_enabled)
        self.assertEqual(settings.reconnect_max_delay_seconds, 45)

    def test_secrets_manager_resolves_token_directly(self) -> None:
        provider = SecretsManagerBrokerCredentialProvider(FakeSecrets())
        self.assertEqual(provider.token_for("auto-forex/alpha/oanda/hash"), "oanda-token")

    def test_enabled_user_streams_are_loaded_from_dynamodb(self) -> None:
        streams = DynamoDbUserStreamRepository(FakeUsersTable(), "alpha").active_streams()
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0].user_id, "cognito-sub")
        self.assertEqual(streams[0].symbols, ("USD_JPY", "EUR_USD"))

    def test_cognito_confirmation_creates_disabled_user_record(self) -> None:
        table = FakeUsersTable()
        original = user_handler._table
        user_handler._table = table
        try:
            event = {
                "userName": "trader",
                "request": {
                    "userAttributes": {
                        "sub": "cognito-sub",
                        "email": "trader@example.invalid",
                    }
                },
            }
            self.assertIs(user_handler.handler(event, None), event)
        finally:
            user_handler._table = original
        self.assertEqual(table.update_request["Key"], {"user_id": "cognito-sub"})
        self.assertFalse(table.update_request["ExpressionAttributeValues"][":disabled"])

    def test_consumer_converts_prices_to_decimal(self) -> None:
        value = _item(
            '{"symbol":"USD_JPY","ask":"150.02","bid":"150.00","mid":"150.01","created_at":"time"}'
        )
        self.assertEqual(value["mid"], Decimal("150.01"))


if __name__ == "__main__":
    unittest.main()
