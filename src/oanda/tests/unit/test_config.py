from __future__ import annotations

from pydantic import SecretStr

from autoforex.oanda.config import OandaEnvironment, OandaSettings


class TestConfig:
    def test_default_hosts_follow_environment(self) -> None:
        assert OandaEnvironment.PRACTICE.default_hostname == "api-fxpractice.oanda.com"
        assert OandaEnvironment.LIVE.default_hostname == "api-fxtrade.oanda.com"
        assert OandaEnvironment.PRACTICE.default_stream_hostname == "stream-fxpractice.oanda.com"
        assert OandaEnvironment.LIVE.default_stream_hostname == "stream-fxtrade.oanda.com"

    def test_settings_resolve_default_and_explicit_hosts(self) -> None:
        settings = OandaSettings(account_id="001", access_token=SecretStr("token"))
        explicit = OandaSettings(
            account_id="001",
            access_token=SecretStr("token"),
            hostname="localhost",
            stream_hostname="stream.localhost",
        )

        assert settings.resolved_hostname == "api-fxpractice.oanda.com"
        assert settings.resolved_stream_hostname == "stream-fxpractice.oanda.com"
        assert explicit.resolved_hostname == "localhost"
        assert explicit.resolved_stream_hostname == "stream.localhost"
