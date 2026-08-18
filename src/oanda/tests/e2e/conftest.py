from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta

import pytest
from autoforex.core import AccountId, CurrencyPair, Units
from pydantic import SecretStr

from autoforex.oanda import OandaEnvironment, OandaProvider, OandaSettings


@pytest.fixture(scope="session")
def oanda_settings() -> OandaSettings:
    account_id = (
        os.getenv("OANDA_ACCOUNT_ID", "").strip() or os.getenv("OANDA_ACCOUNT_NAME", "").strip()
    )
    access_token = os.getenv("OANDA_ACCESS_TOKEN", "").strip()
    if not account_id or not access_token:
        pytest.skip(
            "OANDA_ACCOUNT_ID or OANDA_ACCOUNT_NAME and OANDA_ACCESS_TOKEN "
            "are required for e2e tests"
        )

    environment = OandaEnvironment(os.getenv("OANDA_ENVIRONMENT", "practice").strip().lower())
    return OandaSettings(
        account_id=account_id,
        access_token=SecretStr(access_token),
        environment=environment,
        stream_timeout=timedelta(seconds=10),
    )


@pytest.fixture(scope="session")
def oanda_provider(oanda_settings: OandaSettings) -> Iterator[OandaProvider]:
    provider = OandaProvider.from_settings(oanda_settings)
    try:
        yield provider
    finally:
        provider.close()


@pytest.fixture(scope="session")
def mutating_oanda_provider(
    oanda_provider: OandaProvider,
    oanda_settings: OandaSettings,
) -> OandaProvider:
    if os.getenv("OANDA_ENABLE_MUTATING_E2E", "").strip() != "1":
        pytest.skip("Set OANDA_ENABLE_MUTATING_E2E=1 to run mutating OANDA e2e tests")
    if oanda_settings.environment != OandaEnvironment.PRACTICE:
        pytest.skip("Mutating OANDA e2e tests only run against the practice environment")
    return oanda_provider


@pytest.fixture(scope="session")
def mutating_units() -> Units:
    return Units(os.getenv("OANDA_MUTATING_E2E_UNITS", "1").strip())


@pytest.fixture(scope="session")
def e2e_instrument(oanda_provider: OandaProvider, oanda_settings: OandaSettings) -> CurrencyPair:
    instruments = oanda_provider.accounts.get_account_instruments(
        AccountId.of(oanda_settings.account_id)
    )
    instrument = next(
        (
            item
            for item in instruments
            if item.base.code.isalpha()
            and len(item.base.code) == 3
            and item.quote.code.isalpha()
            and len(item.quote.code) == 3
        ),
        None,
    )
    if instrument is None:
        pytest.skip("No FX currency-pair instrument available for e2e tests")
    return instrument
