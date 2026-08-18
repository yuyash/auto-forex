from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from autoforex.core import TaskProgress, TaskStatus, TqdmProgressReporter, new_uuid


class FakeTqdm:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.total = kwargs.get("total")
        self.updates: list[float] = []
        self.postfix = ""
        self.refresh_count = 0
        self.close_count = 0

    def update(self, amount: float) -> None:
        self.updates.append(amount)

    def set_postfix_str(self, value: str) -> None:
        self.postfix = value

    def refresh(self) -> None:
        self.refresh_count += 1

    def close(self) -> None:
        self.close_count += 1


class TestTaskProgressReporting:
    def test_tqdm_progress_reporter_shows_current_time_instead_of_counts(self) -> None:
        bars: list[FakeTqdm] = []

        def factory(**kwargs: Any) -> FakeTqdm:
            bar = FakeTqdm(**kwargs)
            bars.append(bar)
            return bar

        progress = TaskProgress(
            task_id=new_uuid(),
            task_name="Backtest USD_JPY",
            status=TaskStatus.RUNNING,
            current_at=datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
            completed_units=45,
            total_units=90,
            unit="s",
        )
        reporter = TqdmProgressReporter(
            tqdm_factory=factory,
            current_time_zone=timezone(timedelta(hours=9), "JST"),
        )

        reporter.on_start(progress)

        bar = bars[0]
        assert (
            bar.kwargs["bar_format"]
            == "{l_bar}{bar}| {postfix} [{elapsed}<{remaining}, {rate_fmt}]"
        )
        assert "{n_fmt}" not in bar.kwargs["bar_format"]
        assert "{total_fmt}" not in bar.kwargs["bar_format"]
        assert "{rate_fmt}" in bar.kwargs["bar_format"]
        assert bar.postfix == "current=2026-01-01 21:30:00 JST, status=running"
        assert bar.updates == [45.0]

    def test_tqdm_progress_reporter_preserves_custom_bar_format(self) -> None:
        bars: list[FakeTqdm] = []

        def factory(**kwargs: Any) -> FakeTqdm:
            bar = FakeTqdm(**kwargs)
            bars.append(bar)
            return bar

        progress = TaskProgress(
            task_id=new_uuid(),
            task_name="Live USD_JPY",
            status=TaskStatus.RUNNING,
            current_at=None,
            start_at=None,
            end_at=None,
            completed_units=None,
            total_units=None,
            unit="tick",
        )
        reporter = TqdmProgressReporter(tqdm_factory=factory, bar_format="custom")

        reporter.on_start(progress)

        assert bars[0].kwargs["bar_format"] == "custom"
        assert bars[0].postfix == "current=-, status=running"
