"""Integration tests for EventService."""

from typing import Any
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.market.enums import (
    ApiType,
    MarketEventCategory,
    MarketEventSeverity,
    MarketEventType,
)
from apps.market.models import MarketEvent, OandaAccounts
from apps.market.services.events import MarketEventService


@pytest.mark.django_db
class TestMarketEventServiceIntegration:
    """Integration tests for MarketEventService."""

    def test_log_event_creates_market_event(self, user: Any) -> None:
        """Test that log_event() creates MarketEvent record."""
        account = OandaAccounts.objects.create(
            user=user,
            account_id="101-001-1234567-001",
            api_type=ApiType.PRACTICE,
        )

        service = MarketEventService()

        service.log_event(
            event_type=MarketEventType.ORDER_SUBMITTED,
            description="Test event description",
            severity=MarketEventSeverity.INFO,
            category=MarketEventCategory.MARKET,
            user=user,
            account=account,
            instrument="EUR_USD",
            details={"key": "value"},
        )

        # Verify event was created
        event = MarketEvent.objects.filter(event_type=str(MarketEventType.ORDER_SUBMITTED)).first()

        assert event is not None
        assert event.category == str(MarketEventCategory.MARKET)
        assert event.severity == str(MarketEventSeverity.INFO)
        assert event.user == user
        assert event.account == account
        assert event.instrument == "EUR_USD"
        assert event.details["key"] == "value"

    def test_log_event_without_optional_fields(self) -> None:
        """Test logging event without optional fields."""
        service = MarketEventService()

        service.log_event(
            event_type=MarketEventType.ORDER_FAILED,
            description="Simple event",
            severity=MarketEventSeverity.WARNING,
            category=MarketEventCategory.MARKET,
        )

        # Verify event was created
        event = MarketEvent.objects.filter(event_type=str(MarketEventType.ORDER_FAILED)).first()

        assert event is not None
        assert event.user is None
        assert event.account is None
        assert event.instrument == ""
        assert event.task_type == ""
        assert event.task_id is None
        assert event.execution_id is None

    def test_log_event_with_task_context(self, user: Any) -> None:
        """Test logging event with task association fields."""
        service = MarketEventService()
        task_id = "a22ce941-62f5-4932-9ad2-fc685cb8f728"
        execution_id = "6f40c66e-0a6a-4c02-b0ff-7a78f2fa3a10"

        service.log_event(
            event_type=MarketEventType.TICK_STREAM_RETRY,
            description="Stream retry",
            user=user,
            task_type="trading",
            task_id=task_id,
            execution_id=execution_id,
        )

        event = MarketEvent.objects.filter(event_type=str(MarketEventType.TICK_STREAM_RETRY)).get()
        assert event.task_type == "trading"
        assert str(event.task_id) == task_id
        assert str(event.execution_id) == execution_id

    def test_log_event_uses_default_task_context(self) -> None:
        """Test logging event uses the service-level task context."""
        task_id = uuid4()
        execution_id = uuid4()
        service = MarketEventService(task=SimpleNamespace(pk=task_id, execution_id=execution_id))

        service.log_event(
            event_type=MarketEventType.ORDER_SUBMITTED,
            description="Task-scoped order event",
        )

        event = MarketEvent.objects.filter(event_type=str(MarketEventType.ORDER_SUBMITTED)).get()
        assert event.task_type == "trading"
        assert event.task_id == task_id
        assert event.execution_id == execution_id

    def test_log_trading_event(self, user: Any) -> None:
        """Test logging trading event."""
        service = MarketEventService()

        service.log_trading_event(
            event_type=MarketEventType.ORDER_SUBMITTED,
            description="Trade executed",
            user=user,
        )

        # Verify event was created with trading category
        event = MarketEvent.objects.filter(event_type=str(MarketEventType.ORDER_SUBMITTED)).first()

        assert event is not None
        assert event.category == str(MarketEventCategory.TRADING)
