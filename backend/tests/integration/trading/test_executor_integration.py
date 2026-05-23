"""Integration tests for TaskExecutor components with real DB.

Tests handle_events, load_state, save_state, save_events,
_flush_metrics, and executor __init__ methods.
External services (Redis, Celery) are mocked.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from apps.trading.dataclasses import EventExecutionResult
from apps.trading.enums import TaskType
from apps.trading.models import (
    BacktestTask,
    ExecutionMetricAggregate,
    ExecutionState,
    Metrics,
    TradingEvent,
)
from apps.trading.order import OrderService
from apps.trading.tasks.execution_state_store import ExecutionStateConflict
from apps.trading.tasks.executor import BacktestExecutor, TaskExecutor, TradingExecutor
from tests.integration.factories import (
    BacktestTaskFactory,
    OandaAccountFactory,
    StrategyConfigurationFactory,
    TradingTaskFactory,
    UserFactory,
)


def _make_executor(task: BacktestTask | None = None) -> TaskExecutor:
    """Create a TaskExecutor with mocked external dependencies."""
    if task is None:
        task = BacktestTaskFactory(status="running")
    task.execution_id = task.execution_id or uuid4()
    task.save()

    engine = MagicMock()
    data_source = MagicMock()
    event_context = MagicMock()
    event_context.task_type = TaskType.BACKTEST
    event_context.task_id = task.pk
    event_context.instrument = task.instrument
    event_context.user = task.user
    event_context.account = None

    order_service = OrderService(account=None, task=task, dry_run=True)
    state_manager = MagicMock()

    executor = TaskExecutor(
        task=task,
        engine=engine,
        data_source=data_source,
        event_context=event_context,
        order_service=order_service,
        state_manager=state_manager,
    )
    return executor


@pytest.mark.django_db
class TestHandleEvents:
    """Tests for TaskExecutor.handle_events."""

    def test_processes_events_and_updates_balance(self):
        executor = _make_executor()
        state = ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            strategy_state={},
            current_balance=Decimal("10000"),
            ticks_processed=0,
        )

        # Create a trading event that the handler will process
        event = TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            event_type="initial_entry",
            severity="info",
            description="Test entry event",
            user=executor.task.user,
            instrument="USD_JPY",
            details={
                "event_type": "initial_entry",
                "instrument": "USD_JPY",
                "direction": "long",
                "units": 1000,
                "entry_price": "150.000",
                "layer_index": 0,
            },
        )

        # Mock the event handler to avoid complex order execution
        with patch.object(
            executor.event_handler,
            "handle_event_with_replay",
            return_value=EventExecutionResult(
                realized_pnl_delta=Decimal("0"),
                realized_pnl_delta_quote=Decimal("0"),
            ),
        ):
            executor.handle_events(state, [event])

        # Balance should remain unchanged since realized_delta is 0
        assert state.current_balance == Decimal("10000")

    def test_balance_updated_on_realized_pnl(self):
        executor = _make_executor()
        state = ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            strategy_state={},
            current_balance=Decimal("10000"),
            ticks_processed=0,
        )

        event = TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            event_type="take_profit",
            severity="info",
            description="Take profit",
            user=executor.task.user,
            instrument="USD_JPY",
            details={"event_type": "take_profit"},
        )

        # Simulate a realized PnL of +250
        with patch.object(
            executor.event_handler,
            "handle_event_with_replay",
            return_value=EventExecutionResult(
                realized_pnl_delta=Decimal("250"),
                realized_pnl_delta_quote=Decimal("250"),
            ),
        ):
            executor.handle_events(state, [event])

        assert state.current_balance == Decimal("10250")


@pytest.mark.django_db
class TestLoadState:
    """Tests for TaskExecutor.load_state."""

    def test_creates_new_state(self):
        executor = _make_executor()

        state = executor.load_state()

        assert isinstance(state, ExecutionState)
        assert state.task_id == executor.task.pk
        assert state.ticks_processed == 0
        assert state.current_balance == executor.task.initial_balance
        assert ExecutionState.objects.filter(pk=state.pk).exists()

    def test_loads_existing_state(self):
        executor = _make_executor()

        # Pre-create state
        existing = ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            strategy_state={"layers": [1, 2]},
            current_balance=Decimal("12345.67"),
            ticks_processed=500,
        )

        state = executor.load_state()
        assert state.pk == existing.pk
        assert state.ticks_processed == 500
        assert state.current_balance == Decimal("12345.67")
        assert state.strategy_state == {"layers": [1, 2]}


@pytest.mark.django_db
class TestSaveState:
    """Tests for TaskExecutor.save_state."""

    def test_persists_state(self):
        executor = _make_executor()

        state = ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            strategy_state={},
            current_balance=Decimal("10000"),
            ticks_processed=0,
        )

        state.ticks_processed = 100
        state.current_balance = Decimal("10500")
        state.last_tick_timestamp = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        executor.save_state(state)

        reloaded = ExecutionState.objects.get(pk=state.pk)
        assert reloaded.ticks_processed == 100
        assert reloaded.current_balance == Decimal("10500")
        assert reloaded.last_tick_timestamp is not None

    def test_rejects_stale_state_version(self):
        executor = _make_executor()

        state = ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            strategy_state={},
            current_balance=Decimal("10000"),
            ticks_processed=0,
        )
        stale_state = ExecutionState.objects.get(pk=state.pk)

        state.ticks_processed = 1
        executor.save_state(state)

        stale_state.ticks_processed = 2
        with pytest.raises(ExecutionStateConflict):
            executor.save_state(stale_state)

        reloaded = ExecutionState.objects.get(pk=state.pk)
        assert reloaded.ticks_processed == 1


@pytest.mark.django_db
class TestSaveEvents:
    """Tests for TaskExecutor.save_events."""

    def test_bulk_creates_events(self):
        executor = _make_executor()

        # Create mock StrategyEvent objects
        mock_event_1 = MagicMock()
        mock_event_1.event_type = "initial_entry"
        mock_event_1.to_dict.return_value = {"event_type": "initial_entry", "units": 1000}

        mock_event_2 = MagicMock()
        mock_event_2.event_type = "retracement"
        mock_event_2.to_dict.return_value = {"event_type": "retracement", "units": 500}

        result = executor.save_events([mock_event_1, mock_event_2])

        assert len(result) == 2
        assert all(isinstance(e, TradingEvent) for e in result)
        assert TradingEvent.objects.filter(task_id=executor.task.pk).count() == 2

    def test_empty_events(self):
        executor = _make_executor()
        result = executor.save_events([])
        assert result == []


@pytest.mark.django_db
class TestFlushMetrics:
    """Tests for MetricsAggregator via TaskExecutor._flush_metrics."""

    def test_bulk_creates_snapshots(self):
        executor = _make_executor()
        ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            strategy_state={},
            current_balance=Decimal("10000"),
            ticks_processed=0,
        )

        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Record metrics into two different minute buckets
        executor._metrics_aggregator.record(now, {"margin_ratio": "0.05", "current_atr": "0.0012"})
        executor._metrics_aggregator.record(
            datetime(2024, 6, 1, 12, 1, 0, tzinfo=timezone.utc),
            {"margin_ratio": "0.06"},
        )

        # Flush with final=True to write all buckets
        executor._metrics_aggregator.flush(final=True)

        assert Metrics.objects.filter(task_id=executor.task.pk).count() == 2

    def test_updates_metric_watermarks(self):
        executor = _make_executor()

        first_timestamp = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        second_timestamp = datetime(2024, 6, 1, 12, 1, 0, tzinfo=timezone.utc)
        executor._metrics_aggregator.record(
            first_timestamp,
            {
                "margin_ratio": "0.05",
                "snowball_net_margin_ratio_pct": "5",
                "current_base_units": "1000",
                "open_long_units": "1200",
                "realized_pnl_quote": "10",
                "unrealized_pnl_quote": "-20",
                "open_positions": "2",
                "active_cycles": "1",
            },
        )
        executor._metrics_aggregator.record(
            second_timestamp,
            {
                "margin_ratio": "0.08",
                "snowball_net_margin_ratio_pct": "42",
                "current_base_units": "900",
                "open_short_units": "1600",
                "realized_pnl_quote": "12",
                "unrealized_pnl_quote": "-35",
                "open_positions": "3",
                "active_cycles": "2",
            },
        )

        executor._metrics_aggregator.flush(final=True)

        aggregate = ExecutionMetricAggregate.objects.get(task_id=executor.task.pk)
        assert aggregate.watermarks["margin_ratio_max"]["value"] == "0.42"
        assert aggregate.watermarks["margin_ratio_max"]["timestamp"] == second_timestamp.isoformat()
        assert (
            aggregate.watermarks["margin_ratio_max"]["source_metric"]
            == "snowball_net_margin_ratio_pct"
        )
        assert aggregate.watermarks["base_units_max"]["value"] == "1000"
        assert aggregate.watermarks["open_short_units_max"]["value"] == "1600"
        assert aggregate.watermarks["realized_pnl_max"]["value"] == "12"
        assert aggregate.watermarks["unrealized_pnl_min"]["value"] == "-35"
        assert aggregate.watermarks["open_positions_max"]["value"] == "3"
        assert aggregate.watermarks["active_cycles_max"]["value"] == "2"

    def test_tick_rate_uses_metric_record_interval(self):
        executor = _make_executor()

        first_timestamp = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        second_timestamp = datetime(2024, 6, 1, 12, 1, 0, tzinfo=timezone.utc)
        executor._metrics_aggregator.record(
            first_timestamp,
            {
                "ticks_processed": "120",
                "ticks_per_second": "999.000000",
                "execution_elapsed_seconds": "2.000000",
            },
        )
        executor._metrics_aggregator.record(
            second_timestamp,
            {
                "ticks_processed": "180",
                "ticks_per_second": "999.000000",
                "execution_elapsed_seconds": "3.000000",
            },
        )

        executor._metrics_aggregator.flush(final=True)

        first = Metrics.objects.get(task_id=executor.task.pk, timestamp=first_timestamp)
        second = Metrics.objects.get(task_id=executor.task.pk, timestamp=second_timestamp)
        assert Decimal(first.metrics["ticks_per_second"]) == Decimal("60.000000")
        assert Decimal(second.metrics["ticks_per_second"]) == Decimal("60.000000")

    def test_tick_rate_uses_previous_persisted_metric_as_anchor(self):
        executor = _make_executor()

        previous_timestamp = datetime(2024, 6, 1, 11, 58, 0, tzinfo=timezone.utc)
        current_timestamp = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        Metrics.objects.create(
            task_type=executor.task_type.value,
            task_id=executor.task.pk,
            execution_id=executor.task.execution_id,
            timestamp=previous_timestamp,
            metrics={
                "ticks_processed": "120",
                "ticks_per_second": "2.000000",
                "execution_elapsed_seconds": "10.000000",
            },
        )
        executor._metrics_aggregator.record(
            current_timestamp,
            {
                "ticks_processed": "180",
                "ticks_per_second": "999.000000",
                "execution_elapsed_seconds": "12.000000",
            },
        )

        executor._metrics_aggregator.flush(final=True)

        current = Metrics.objects.get(task_id=executor.task.pk, timestamp=current_timestamp)
        assert Decimal(current.metrics["ticks_per_second"]) == Decimal("30.000000")

    def test_tick_rate_falls_back_to_bucket_interval_without_elapsed_metrics(self):
        executor = _make_executor()

        first_timestamp = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        second_timestamp = datetime(2024, 6, 1, 12, 1, 0, tzinfo=timezone.utc)
        executor._metrics_aggregator.record(
            first_timestamp,
            {"ticks_processed": "120", "ticks_per_second": "999.000000"},
        )
        executor._metrics_aggregator.record(
            second_timestamp,
            {"ticks_processed": "180", "ticks_per_second": "999.000000"},
        )

        executor._metrics_aggregator.flush(final=True)

        first = Metrics.objects.get(task_id=executor.task.pk, timestamp=first_timestamp)
        second = Metrics.objects.get(task_id=executor.task.pk, timestamp=second_timestamp)
        assert Decimal(first.metrics["ticks_per_second"]) == Decimal("2.000000")
        assert Decimal(second.metrics["ticks_per_second"]) == Decimal("1.000000")

    def test_empty_buffer(self):
        executor = _make_executor()
        state = MagicMock()
        executor._flush_metrics(state)
        assert Metrics.objects.filter(task_id=executor.task.pk).count() == 0


@pytest.mark.django_db
class TestBacktestExecutorInit:
    """Tests for BacktestExecutor.__init__."""

    @patch("apps.trading.tasks.executor.StateManager")
    def test_creates_all_components(self, mock_state_manager_cls):
        task = BacktestTaskFactory(status="running")
        task.execution_id = uuid4()
        task.save()
        engine = MagicMock()
        data_source = MagicMock()

        executor = BacktestExecutor(task=task, engine=engine, data_source=data_source)

        assert executor.task == task
        assert executor.engine == engine
        assert executor.data_source == data_source
        assert executor.instrument == task.instrument
        assert executor.initial_balance == task.initial_balance
        assert isinstance(executor.order_service, OrderService)
        assert executor.order_service.dry_run is True
        assert executor.order_service.account is None
        mock_state_manager_cls.assert_called_once()


@pytest.mark.django_db
class TestTradingExecutorInit:
    """Tests for TradingExecutor.__init__."""

    @patch("apps.trading.tasks.executor.StateManager")
    def test_creates_all_components(self, mock_state_manager_cls):
        user = UserFactory()
        account = OandaAccountFactory(user=user)
        config = StrategyConfigurationFactory(user=user)
        task = TradingTaskFactory(user=user, oanda_account=account, config=config)
        task.execution_id = uuid4()
        task.save()
        engine = MagicMock()
        data_source = MagicMock()

        executor = TradingExecutor(task=task, engine=engine, data_source=data_source)

        assert executor.task == task
        assert executor.engine == engine
        assert executor.data_source == data_source
        assert executor.instrument == task.instrument
        assert isinstance(executor.order_service, OrderService)
        assert executor.order_service.dry_run is False
        assert executor.order_service.account == account
        mock_state_manager_cls.assert_called_once()
