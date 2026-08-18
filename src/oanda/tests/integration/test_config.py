from __future__ import annotations

from pydantic import SecretStr

from autoforex.oanda.config import OandaEnvironment, OandaSettings
from autoforex.oanda.gateway import OandaGateway


class TestConfig:
    def test_settings_integrate_with_gateway_factory_without_http(self) -> None:
        settings = OandaSettings(
            account_id="001",
            access_token=SecretStr("token"),
            environment=OandaEnvironment.PRACTICE,
            application="IntegrationTest",
        )

        gateway = OandaGateway.from_settings(settings)

        assert gateway.access_token == "token"
        assert gateway.hostname == settings.resolved_hostname
        assert gateway.stream_hostname == settings.resolved_stream_hostname
        assert gateway.application == "IntegrationTest"
