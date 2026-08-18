"""OANDA v20 adapter package for AutoForexV2."""

from importlib.metadata import version

from autoforex.oanda.accounts import OandaAccountManager
from autoforex.oanda.broker import OandaBroker
from autoforex.oanda.config import OandaEnvironment, OandaSettings
from autoforex.oanda.constants import OANDA_PROVIDER
from autoforex.oanda.errors import (
    OandaAdapterError,
    OandaApiError,
    OandaAuthenticationError,
    OandaAuthorizationError,
    OandaBadRequestError,
    OandaClientError,
    OandaConnectionError,
    OandaNotFoundError,
    OandaRateLimitError,
    OandaRetryableApiError,
    OandaServerError,
    OandaTimeoutError,
    OandaTransportError,
)
from autoforex.oanda.gateway import OandaGateway, OandaRetryPolicy
from autoforex.oanda.mappers import (
    OandaAccountMapper,
    OandaInstrumentMapper,
    OandaMarketDataMapper,
    OandaOrderMapper,
    OandaPositionMapper,
)
from autoforex.oanda.models import OandaModel, OandaResponse
from autoforex.oanda.provider import OandaProvider
from autoforex.oanda.snapshots import (
    OandaAccount,
    OandaAccountSummary,
    OandaOrder,
    OandaPosition,
    OandaTrade,
    OandaTransaction,
)
from autoforex.oanda.source import OandaDataSource

__all__ = [
    "OANDA_PROVIDER",
    "OandaAccount",
    "OandaAccountManager",
    "OandaAccountMapper",
    "OandaAccountSummary",
    "OandaAdapterError",
    "OandaApiError",
    "OandaAuthenticationError",
    "OandaAuthorizationError",
    "OandaBadRequestError",
    "OandaBroker",
    "OandaClientError",
    "OandaConnectionError",
    "OandaDataSource",
    "OandaEnvironment",
    "OandaGateway",
    "OandaInstrumentMapper",
    "OandaMarketDataMapper",
    "OandaModel",
    "OandaNotFoundError",
    "OandaOrder",
    "OandaOrderMapper",
    "OandaPosition",
    "OandaPositionMapper",
    "OandaProvider",
    "OandaRateLimitError",
    "OandaResponse",
    "OandaRetryPolicy",
    "OandaRetryableApiError",
    "OandaServerError",
    "OandaSettings",
    "OandaTimeoutError",
    "OandaTrade",
    "OandaTransaction",
    "OandaTransportError",
    "__version__",
]

__version__ = version("auto-forex-oanda")
