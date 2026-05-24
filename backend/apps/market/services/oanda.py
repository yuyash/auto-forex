"""
OANDA API direct client for fetching orders, positions, and account details.

This module provides direct API calls to OANDA without database caching,
replacing the sync-based approach with real-time API queries.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from typing import Any

import v20
from django.conf import settings

from apps.market.enums import MarketEventSeverity, MarketEventType
from apps.market.models import OandaAccounts, TickData
from apps.market.services.broker_order_guard import BrokerOrderGuard, BrokerOrderGuardError
from apps.market.services.compliance import ComplianceService, ComplianceViolationError
from apps.market.services.events import MarketEventService
from apps.market.services.oanda_clients import (
    OandaAccountClient,
    OandaContextFactory,
    OandaOrderClient,
    OandaPositionClient,
    OandaPricingStreamClient,
    OandaTradeClient,
    OandaTransactionClient,
)
from apps.market.services.oanda_dry_run import OandaDryRunSimulator
from apps.market.services import oanda_parsing
from apps.market.services.oanda_transport import OandaOrderClientExtensions, OandaOrderTransport
from apps.market.services.oanda_retry import (
    OandaApiRequestExecutor,
    OandaRetryPolicy,
    OandaRetryService,
)
from apps.market.services.oanda_types import (
    AccountDetails,
    CancelledOrder,
    LimitOrder,
    LimitOrderRequest,
    MarketOrder,
    MarketOrderRequest,
    OandaAPIError,
    OcoOrder,
    OcoOrderRequest,
    OpenTrade,
    Order,
    OrderDirection,
    OrderState,
    OrderType,
    PendingOrder,
    Position,
    StopOrder,
    StopOrderRequest,
    StreamMessageType,
    Transaction,
)

logger: Logger = getLogger(name=__name__)

__all__ = [
    "AccountDetails",
    "CancelledOrder",
    "LimitOrder",
    "LimitOrderRequest",
    "MarketOrder",
    "MarketOrderRequest",
    "OandaAPIError",
    "OandaService",
    "OcoOrder",
    "OcoOrderRequest",
    "OpenTrade",
    "Order",
    "OrderDirection",
    "OrderState",
    "OrderType",
    "PendingOrder",
    "Position",
    "StopOrder",
    "StopOrderRequest",
    "StreamMessageType",
    "Transaction",
]


class OandaService:
    """
    Direct client for OANDA v20 API.

    Provides methods to fetch orders, positions, and account details
    directly from OANDA without database caching.

    Supports dry-run mode for backtesting and simulation.
    """

    def __init__(
        self,
        account: OandaAccounts | None = None,
        dry_run: bool = False,
        *,
        retry_policy: OandaRetryPolicy | None = None,
        retry_service: OandaRetryService | None = None,
        task: Any | None = None,
    ):
        """
        Initialize OANDA API client.

        Args:
            account: OandaAccounts instance with API credentials (optional for dry_run mode)
            dry_run: If True, simulate API calls without making actual requests
            task: Optional task context for task-scoped market event logging
        """
        self.account = account
        self.dry_run = dry_run
        self.task = task
        self.retry_policy = retry_policy or OandaRetryPolicy.short_default()
        self.max_retries = self.retry_policy.max_attempts
        self.retry_delay = self.retry_policy.backoff_base_seconds
        self.max_retry_delay = self.retry_policy.backoff_max_seconds
        self.retry_service = retry_service or OandaRetryService(
            policy=self.retry_policy,
            raise_runtime_error=False,
        )
        self.request_executor = OandaApiRequestExecutor(
            retry_service=self.retry_service,
            make_jsonable=self._make_jsonable,
        )
        self.event_service = MarketEventService(task=task)
        self.order_guard = BrokerOrderGuard()
        self.order_client_extensions = OandaOrderClientExtensions()
        self.response_parser = oanda_parsing.OandaResponseParser()
        self._account_resource_cache: dict[str, Any] | None = None
        self.context_factory = OandaContextFactory(v20_module=v20, settings_module=settings)
        self.account_client = OandaAccountClient(self)
        self.order_client = OandaOrderClient(self)
        self.trade_client = OandaTradeClient(self)
        self.position_client = OandaPositionClient(self)
        self.transaction_client = OandaTransactionClient(self)
        self.pricing_stream_client = OandaPricingStreamClient(self)

        self._dry_run_simulator = OandaDryRunSimulator(account)
        # Backward-compatible attribute used by older tests and debug tools.
        self._dry_run_positions = self._dry_run_simulator.positions

        # Only initialize API connections if we have an account
        # In dry-run mode without an account, we skip all API calls
        if account is not None:
            rest_hostname = str(account.api_hostname)
            stream_hostname = self.context_factory.stream_hostname(rest_hostname)

            self.api = self.context_factory.create_rest_context(account)

            # v20 Context uses a single hostname for both REST and streaming.
            # OANDA streams live on a different hostname (stream-*) than REST (api-*).
            # If we use the REST host for pricing.stream, OANDA returns 404.
            self.stream_hostname = stream_hostname
            self.stream_api = self.context_factory.create_stream_context(account)

            self.compliance_manager = ComplianceService(account)

            logger.info(
                "OANDA service initialized (account_id=%s, api_hostname=%s, stream_hostname=%s, dry_run=%s)",
                str(getattr(account, "account_id", "")),
                rest_hostname,
                stream_hostname,
                dry_run,
            )
        else:
            # No account - dry-run only mode
            self.api = None
            self.stream_api = None
            self.stream_hostname = None
            self.compliance_manager = None

            logger.info(
                "OANDA service initialized in dry-run mode without account (simulation only)"
            )

    @staticmethod
    def _to_stream_hostname(hostname: str) -> str:
        return OandaContextFactory.stream_hostname(hostname)

    @staticmethod
    def _make_jsonable(value: Any) -> Any:
        return oanda_parsing.OANDA_RESPONSE_PARSER.make_jsonable(value)

    @staticmethod
    def make_jsonable(value: Any) -> Any:
        return OandaService._make_jsonable(value)

    @staticmethod
    def _response_field(response: Any, field_name: str) -> Any:
        return oanda_parsing.OANDA_RESPONSE_PARSER.response_field(response, field_name)

    @staticmethod
    def _object_field(value: Any, field_name: str) -> Any:
        return oanda_parsing.OANDA_RESPONSE_PARSER.object_field(value, field_name)

    @staticmethod
    def _account_object_to_dict(account_data: Any) -> dict[str, Any]:
        return oanda_parsing.OANDA_RESPONSE_PARSER.account_object_to_dict(account_data)

    def get_account_resource(self, *, refresh: bool = False) -> dict[str, Any]:
        """Fetch the raw OANDA account resource as a dict.

        This is used to expose broker flags/parameters (e.g. `hedgingEnabled`) and
        to avoid repeated network calls by caching within this service instance.
        """
        return self.account_client.get_resource(refresh=refresh)

    def cancel_order(self, order: Order) -> CancelledOrder:
        return self.order_client.cancel_order(order)

    def close_trade(self, trade: OpenTrade, units: Decimal | None = None) -> MarketOrder:
        return self.trade_client.close_trade(trade=trade, units=units)

    def close_position(
        self,
        position: Position,
        units: Decimal | None = None,
        override_price: Decimal | None = None,
    ) -> MarketOrder:
        return self.position_client.close_position(
            position=position,
            units=units,
            override_price=override_price,
        )

    def _simulate_position_close(
        self,
        position: Position,
        units: Decimal | None = None,
        override_price: Decimal | None = None,
    ) -> MarketOrder:
        """Backward-compatible wrapper around the dry-run simulator."""
        return self._dry_run_simulator.simulate_position_close(
            position,
            units,
            override_price=override_price,
        )

    def create_limit_order(self, request: LimitOrderRequest) -> LimitOrder:
        return self.order_client.create_limit_order(request)

    def create_market_order(
        self,
        request: MarketOrderRequest,
        override_price: Decimal | None = None,
    ) -> MarketOrder:
        return self.order_client.create_market_order(
            request,
            override_price=override_price,
        )

    def create_stop_order(self, request: StopOrderRequest) -> StopOrder:
        return self.order_client.create_stop_order(request)

    def create_oco_order(self, request: OcoOrderRequest) -> OcoOrder:
        return self.order_client.create_oco_order(request)

    def get_account_details(self) -> AccountDetails:
        return self.account_client.get_details()

    def get_account_hedging_enabled(self) -> bool:
        return self.account_client.get_hedging_enabled()

    def get_account_position_mode(self) -> str:
        return self.account_client.get_position_mode()

    def get_open_positions(self, instrument: str | None = None) -> list[Position]:
        return self.position_client.get_open_positions(instrument=instrument)

    def get_trades(
        self,
        instrument: str | None = None,
        *,
        state: str = "OPEN",
        count: int = 500,
    ) -> list[OpenTrade]:
        return self.trade_client.get_trades(
            instrument=instrument,
            state=state,
            count=count,
        )

    def get_open_trades(self, instrument: str | None = None) -> list[OpenTrade]:
        return self.trade_client.get_open_trades(instrument=instrument)

    def get_pending_orders(self, instrument: str | None = None) -> list[PendingOrder]:
        return self.order_client.get_pending_orders(instrument=instrument)

    def get_order_history(
        self, instrument: str | None = None, count: int = 50, state: str = "ALL"
    ) -> list[Order]:
        return self.order_client.get_order_history(
            instrument=instrument,
            count=count,
            state=state,
        )

    def get_order(self, order_id: str) -> Order:
        return self.order_client.get_order(order_id)

    def get_transaction_history(
        self,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        page_size: int = 100,
        transaction_type: str | None = None,
    ) -> list[Transaction]:
        return self.transaction_client.get_transaction_history(
            from_time=from_time,
            to_time=to_time,
            page_size=page_size,
            transaction_type=transaction_type,
        )

    def stream_pricing_ticks(
        self,
        instruments: list[str] | str,
        *,
        snapshot: bool = True,
        include_heartbeats: bool = False,
    ) -> Iterator[TickData]:
        return self.pricing_stream_client.stream_pricing_ticks(
            instruments,
            snapshot=snapshot,
            include_heartbeats=include_heartbeats,
        )

    @staticmethod
    def _as_pending_order(order: Order) -> PendingOrder:
        return oanda_parsing.OANDA_RESPONSE_PARSER.as_pending_order(order)

    def _execute_with_retry(self, order_data: dict[str, Any]) -> Any:
        assert self.api is not None, "API client not initialized"
        assert self.account is not None, "Account not initialized"
        policy = OandaRetryPolicy(
            max_attempts=self.max_retries,
            backoff_base_seconds=self.retry_delay,
            backoff_max_seconds=self.max_retry_delay,
            jitter_ratio=self.retry_policy.jitter_ratio,
        )
        transport = OandaOrderTransport(
            api=self.api,
            account=self.account,
            event_service=self.event_service,
            logger=logger,
            retry_service=OandaRetryService(
                policy=policy,
                sleep=time.sleep,
                raise_runtime_error=False,
            ),
            error_class=OandaAPIError,
            sleep_func=time.sleep,
            randbelow_func=secrets.randbelow,
        )
        return transport.execute_order(order_data)

    def _apply_order_client_extensions(
        self,
        order_data: dict[str, Any],
        client_order_id: str | None,
    ) -> str | None:
        """Attach broker client extensions used for idempotent order creation."""
        return self.order_client_extensions.apply(order_data, client_order_id)

    def _request(
        self,
        fn: Any,
        *args: Any,
        label: str,
        expected_status: int | tuple[int, ...] = 200,
        failure_message: str | None = None,
        exception_message: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute one OANDA API request through the service retry policy."""
        return self.request_executor.request(
            fn,
            *args,
            label=label,
            expected_status=expected_status,
            failure_message=failure_message,
            exception_message=exception_message,
            **kwargs,
        )

    def _format_position(
        self, instrument: str, direction: OrderDirection, pos_data: dict[str, Any]
    ) -> Position:
        return self.response_parser.format_position(
            instrument=instrument,
            direction=direction,
            pos_data=pos_data,
            account_id=str(self.account.account_id) if self.account else "",
        )

    def _parse_iso_datetime(self, value: Any) -> datetime | None:
        return self.response_parser.parse_iso_datetime(value)

    def _parse_order(self, order: Any) -> Order:
        return self.response_parser.parse_order(order)

    def _parse_transaction(self, txn: dict[str, Any]) -> Transaction:
        return self.response_parser.parse_transaction(txn)

    def _to_decimal(self, value: Any) -> Decimal | None:
        return self.response_parser.to_decimal(value)

    def _validate_compliance(self, order_request: dict[str, Any]) -> None:
        # Skip compliance checks if no account (dry-run only mode)
        if self.account is None or self.compliance_manager is None:
            return

        is_valid, error_message = self.compliance_manager.validate_order(order_request)

        if not is_valid:
            self.event_service.log_security_event(
                event_type=MarketEventType.COMPLIANCE_VIOLATION,
                description=f"Order rejected: {error_message}",
                severity=MarketEventSeverity.WARNING,
                user=self.account.user,
                account=self.account,
                instrument=str(order_request.get("instrument") or "") or None,
                details={
                    "account_id": self.account.account_id,
                    "order_request": order_request,
                    "violation_reason": error_message,
                    "jurisdiction": self.account.jurisdiction,
                },
            )

            raise ComplianceViolationError(error_message)

    def _validate_broker_order_guard(self, *, instrument: str, units: Decimal) -> None:
        try:
            self.order_guard.validate_order(
                account=self.account,
                dry_run=self.dry_run,
                instrument=instrument,
                units=units,
            )
        except BrokerOrderGuardError as exc:
            self._log_order_guard_rejection(instrument=instrument, units=units, reason=str(exc))
            raise OandaAPIError(str(exc), internal_detail=str(exc)) from exc

    def _log_order_guard_rejection(
        self,
        *,
        instrument: str,
        units: Decimal,
        reason: str,
    ) -> None:
        if self.account is None:
            return

        try:
            self.event_service.log_security_event(
                event_type=MarketEventType.COMPLIANCE_VIOLATION,
                description=f"Broker order blocked by safety guardrails: {reason}",
                severity=MarketEventSeverity.WARNING,
                user=self.account.user,
                account=self.account,
                instrument=instrument,
                details={
                    "account_id": self.account.account_id,
                    "instrument": instrument,
                    "units": str(units),
                    "violation_reason": reason,
                },
            )
        except Exception:  # pragma: no cover - best-effort audit logging
            logger.warning(
                "Failed to log broker order guard rejection for account %s",
                getattr(self.account, "account_id", "unknown"),
                exc_info=True,
            )
