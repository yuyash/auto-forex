"""Unit tests for tick data source module."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.trading.dataclasses.tick import Tick


class TestDirectBacktestTickDataSource:
    """Tests for in-process backtest tick data source."""

    def test_iter_batches_raw_ticks_without_redis(self):
        from apps.trading.tasks.source import DirectBacktestTickDataSource

        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)
        rows = iter(
            [
                {
                    "timestamp": start,
                    "bid": Decimal("157.240"),
                    "ask": Decimal("157.250"),
                    "mid": Decimal("157.245"),
                },
                {
                    "timestamp": end,
                    "bid": Decimal("157.260"),
                    "ask": Decimal("157.270"),
                    "mid": Decimal("157.265"),
                },
            ]
        )
        source = DirectBacktestTickDataSource(
            request_id="task-1",
            instrument="USD_JPY",
            start_dt=start,
            end_dt=end,
            batch_size=2,
            pip_size="0.01",
        )

        with (
            patch.object(DirectBacktestTickDataSource, "_iter_raw_ticks", return_value=rows),
            patch.object(source, "_mark_backtest_task_failed") as mark_failed,
        ):
            batches = list(source)

        assert len(batches) == 1
        assert [tick.mid for tick in batches[0]] == [Decimal("157.245"), Decimal("157.265")]
        mark_failed.assert_not_called()

    def test_close_is_noop(self):
        from apps.trading.tasks.source import DirectBacktestTickDataSource

        now = datetime(2026, 1, 1, tzinfo=UTC)
        source = DirectBacktestTickDataSource(
            request_id="task-1",
            instrument="USD_JPY",
            start_dt=now,
            end_dt=now,
        )

        source.close()


class TestRedisTickDataSourceInit:
    """Tests for RedisTickDataSource.__init__."""

    def test_init_stores_attributes(self):
        from apps.trading.tasks.source import RedisTickDataSource

        callback = MagicMock()
        source = RedisTickDataSource(
            channel="market:backtest:ticks:123",
            batch_size=50,
            trigger_publisher=callback,
        )

        assert source.channel == "market:backtest:ticks:123"
        assert source.batch_size == 50
        assert source.trigger_publisher is callback
        assert source.client is None
        assert source.pubsub is None

    def test_init_defaults(self):
        from apps.trading.tasks.source import RedisTickDataSource

        source = RedisTickDataSource(channel="test:channel")

        assert source.channel == "test:channel"
        assert source.batch_size == 100
        assert source.trigger_publisher is None


class TestRedisTickDataSourceClose:
    """Tests for RedisTickDataSource.close."""

    def test_close_cleans_up_pubsub_and_client(self):
        from apps.trading.tasks.source import RedisTickDataSource

        source = RedisTickDataSource(channel="test:channel")
        source.pubsub = MagicMock()
        source.client = MagicMock()

        source.close()

        source.pubsub.close.assert_called_once()
        source.client.close.assert_called_once()

    def test_close_handles_none_gracefully(self):
        from apps.trading.tasks.source import RedisTickDataSource

        source = RedisTickDataSource(channel="test:channel")
        source.pubsub = None
        source.client = None

        # Should not raise
        source.close()


class TestRedisTickDataSourceValidation:
    """Tests for replay tick sanity validation."""

    def test_accepts_normal_tick(self):
        from apps.trading.tasks.source import RedisTickDataSource

        tick = Tick(
            instrument="USD_JPY",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Decimal("157.240"),
            ask=Decimal("157.250"),
            mid=Decimal("157.245"),
        )

        assert RedisTickDataSource._is_valid_backtest_tick(tick) is True

    def test_rejects_tick_with_extreme_spread(self):
        from apps.trading.tasks.source import RedisTickDataSource

        tick = Tick(
            instrument="USD_JPY",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Decimal("157.545"),
            ask=Decimal("163.425"),
            mid=Decimal("160.485"),
        )

        assert RedisTickDataSource._is_valid_backtest_tick(tick) is False

    def test_close_handles_pubsub_exception(self):
        from apps.trading.tasks.source import RedisTickDataSource

        source = RedisTickDataSource(channel="test:channel")
        source.pubsub = MagicMock()
        source.pubsub.close.side_effect = Exception("pubsub error")
        source.client = MagicMock()

        # Should not raise, just log
        source.close()
        source.client.close.assert_called_once()

    def test_close_handles_client_exception(self):
        from apps.trading.tasks.source import RedisTickDataSource

        source = RedisTickDataSource(channel="test:channel")
        source.pubsub = MagicMock()
        source.client = MagicMock()
        source.client.close.side_effect = Exception("client error")

        # Should not raise
        source.close()


class TestLiveTickDataSourceInit:
    """Tests for LiveTickDataSource.__init__."""

    def test_init_stores_channel_and_instrument(self):
        from apps.trading.tasks.source import LiveTickDataSource

        source = LiveTickDataSource(
            channel="live:001-001-123:EUR_USD",
            instrument="EUR_USD",
        )

        assert source.channel == "live:001-001-123:EUR_USD"
        assert source.instrument == "EUR_USD"
        assert source.tick_granularity == "tick"
        assert source.client is None
        assert source.pubsub is None

    def test_granularity_keeps_first_tick_in_each_bucket(self):
        from apps.trading.tasks.source import LiveTickDataSource

        source = LiveTickDataSource(
            channel="live:001-001-123:EUR_USD",
            instrument="EUR_USD",
            tick_granularity="1m",
        )
        first = Tick.create(
            instrument="EUR_USD",
            timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            bid=Decimal("1.1000"),
            ask=Decimal("1.1002"),
        )
        same_bucket = Tick.create(
            instrument="EUR_USD",
            timestamp=datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC),
            bid=Decimal("1.1001"),
            ask=Decimal("1.1003"),
        )
        next_bucket = Tick.create(
            instrument="EUR_USD",
            timestamp=datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC),
            bid=Decimal("1.1004"),
            ask=Decimal("1.1006"),
        )

        assert source._should_emit_tick(first) is True
        assert source._should_emit_tick(same_bucket) is False
        assert source._should_emit_tick(next_bucket) is True

    def test_tick_granularity_keeps_every_tick(self):
        from apps.trading.tasks.source import LiveTickDataSource

        source = LiveTickDataSource(
            channel="live:001-001-123:EUR_USD",
            instrument="EUR_USD",
            tick_granularity="tick",
        )
        first = Tick.create(
            instrument="EUR_USD",
            timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            bid=Decimal("1.1000"),
            ask=Decimal("1.1002"),
        )
        second = Tick.create(
            instrument="EUR_USD",
            timestamp=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
            bid=Decimal("1.1001"),
            ask=Decimal("1.1003"),
        )

        assert source._should_emit_tick(first) is True
        assert source._should_emit_tick(second) is True


class TestLiveTickDataSourceClose:
    """Tests for LiveTickDataSource.close."""

    def test_close_cleans_up_pubsub_and_client(self):
        from apps.trading.tasks.source import LiveTickDataSource

        source = LiveTickDataSource(channel="test:channel", instrument="EUR_USD")
        source.pubsub = MagicMock()
        source.client = MagicMock()

        source.close()

        source.pubsub.close.assert_called_once()
        source.client.close.assert_called_once()

    def test_close_handles_none_gracefully(self):
        from apps.trading.tasks.source import LiveTickDataSource

        source = LiveTickDataSource(channel="test:channel", instrument="EUR_USD")
        source.pubsub = None
        source.client = None

        # Should not raise
        source.close()

    def test_close_handles_pubsub_exception(self):
        from apps.trading.tasks.source import LiveTickDataSource

        source = LiveTickDataSource(channel="test:channel", instrument="EUR_USD")
        source.pubsub = MagicMock()
        source.pubsub.close.side_effect = Exception("pubsub error")
        source.client = MagicMock()

        # Should not raise
        source.close()
        source.client.close.assert_called_once()

    def test_close_handles_client_exception(self):
        from apps.trading.tasks.source import LiveTickDataSource

        source = LiveTickDataSource(channel="test:channel", instrument="EUR_USD")
        source.pubsub = MagicMock()
        source.client = MagicMock()
        source.client.close.side_effect = Exception("client error")

        # Should not raise
        source.close()
