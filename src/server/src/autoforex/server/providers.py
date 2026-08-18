"""Provider service factory for server runtime wiring."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, cast

from autoforex.core import TradingProvider

from autoforex.server.optional import require_optional_dependency

if TYPE_CHECKING:
    from autoforex.oanda import OandaSettings


class ProviderName(StrEnum):
    """Provider names supported by the server runtime."""

    OANDA = "oanda"


class ProviderFactory:
    """Create provider-specific service bundles for server runtime wiring."""

    def create(
        self,
        provider: ProviderName,
        *,
        settings: OandaSettings,
    ) -> TradingProvider:
        """Create provider-specific service implementations."""
        if provider == ProviderName.OANDA:
            return self._create_oanda_provider(settings)

        msg = f"unsupported account provider: {provider.value}"
        raise ValueError(msg)

    def _create_oanda_provider(self, settings: OandaSettings) -> TradingProvider:
        module = require_optional_dependency(
            "autoforex.oanda",
            extra="oanda",
            feature="OANDA provider support",
        )
        provider_type = module.__dict__["OandaProvider"]
        return cast(TradingProvider, provider_type.from_settings(settings))
