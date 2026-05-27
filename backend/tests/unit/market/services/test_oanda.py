"""Unit tests for OANDA service."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.market.services.oanda import OandaAPIError, OandaService, OrderDirection, Position


class TestOandaService:
    """Test OANDA service."""

    def test_oanda_service_module_exists(self):
        """Test OANDA service module exists."""
        from apps.market.services import oanda

        assert oanda is not None

    def test_oanda_service_has_classes(self):
        """Test OANDA service has classes."""
        import inspect

        from apps.market.services import oanda

        classes = [
            name
            for name, obj in inspect.getmembers(oanda)
            if inspect.isclass(obj) and obj.__module__ == oanda.__name__
        ]

        # Should have service classes
        assert len(classes) > 0

    def test_close_position_dry_run_without_account_with_override_price(self):
        """Dry-run close_position should not require API client/account."""
        service = OandaService(account=None, dry_run=True)
        position = Position(
            instrument="USD_JPY",
            direction=OrderDirection.LONG,
            units=Decimal("1000"),
            average_price=Decimal("150.00"),
            unrealized_pnl=Decimal("0"),
            trade_ids=[],
            account_id="DRY-RUN",
        )

        result = service.close_position(position, override_price=Decimal("150.01"))

        assert result is not None
        assert result.instrument == "USD_JPY"
        assert result.price == Decimal("150.01")

    def test_close_position_dry_run_requires_override_price(self):
        service = OandaService(account=None, dry_run=True)
        position = Position(
            instrument="USD_JPY",
            direction=OrderDirection.LONG,
            units=Decimal("1000"),
            average_price=Decimal("150.00"),
            unrealized_pnl=Decimal("0"),
            trade_ids=[],
            account_id="DRY-RUN",
        )

        with pytest.raises(OandaAPIError):
            service.close_position(position)

    @pytest.mark.contract
    def test_execute_with_retry_retries_rate_limit_then_returns_success(self):
        """429 responses are retryable and should not create a failure event on recovery."""
        service = OandaService(account=None, dry_run=True)
        service.max_retries = 3
        service.retry_delay = 0
        service.account = SimpleNamespace(account_id="acct-1", user=SimpleNamespace(id=1))
        service.api = SimpleNamespace(order=SimpleNamespace(create=MagicMock()))
        service.event_service = SimpleNamespace(log_trading_event=MagicMock())
        service.api.order.create.side_effect = [
            SimpleNamespace(status=429, body={"errorMessage": "rate limit"}),
            SimpleNamespace(status=201, body={"orderCreateTransaction": {"id": "1"}}),
        ]

        with (
            patch("apps.market.services.oanda.time.sleep") as sleep,
            patch("apps.market.services.oanda.secrets.randbelow", return_value=0),
        ):
            response = service._execute_with_retry({"instrument": "USD_JPY", "units": "1000"})

        assert response.status == 201
        assert service.api.order.create.call_count == 2
        sleep.assert_called_once()
        service.event_service.log_trading_event.assert_not_called()

    @pytest.mark.contract
    def test_execute_with_retry_does_not_retry_non_retryable_status(self):
        """4xx responses other than 429 fail fast and emit one failure event."""
        service = OandaService(account=None, dry_run=True)
        service.max_retries = 3
        service.retry_delay = 0
        service.account = SimpleNamespace(account_id="acct-1", user=SimpleNamespace(id=1))
        service.api = SimpleNamespace(order=SimpleNamespace(create=MagicMock()))
        service.event_service = SimpleNamespace(log_trading_event=MagicMock())
        service.api.order.create.return_value = SimpleNamespace(
            status=400,
            body={"errorMessage": "invalid instrument"},
        )

        with (
            patch("apps.market.services.oanda.time.sleep") as sleep,
            patch("apps.market.services.oanda.secrets.randbelow", return_value=0),
            pytest.raises(OandaAPIError, match="Order submission failed after 3 attempts"),
        ):
            service._execute_with_retry({"instrument": "BAD", "units": "1000"})

        service.api.order.create.assert_called_once()
        sleep.assert_not_called()
        service.event_service.log_trading_event.assert_called_once()
