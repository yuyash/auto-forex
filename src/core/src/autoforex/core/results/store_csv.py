"""CSV result store."""

from __future__ import annotations

import csv
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.store_contracts import ResultBatch
from autoforex.core.results.store_rows import ResultRowMapper, ResultRowReader

type ResultRecord = StrategyEventRecord | TradeSummary | CycleSummary | TaskSummary | ProfitMetric


class CsvResultStore:
    """Append task results to CSV files under a directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._known_keys: dict[str, set[tuple[str, ...]]] = {}
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        self._append_unique_many(
            "strategy_events.csv",
            (ResultRowMapper.event(record),),
            key_fields=("event_id",),
        )

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        self._append_many(
            "trade_summaries.csv",
            (ResultRowMapper.trade(summary),),
        )

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary snapshot."""
        self._append_many(
            "cycle_summaries.csv",
            (ResultRowMapper.cycle(summary),),
        )

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary snapshot."""
        self._append_many(
            "task_summaries.csv",
            (ResultRowMapper.task(summary),),
        )

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        self._append_unique_many(
            "profit_metrics.csv",
            (ResultRowMapper.metric(metric),),
            key_fields=("metric_id",),
        )

    def save_batch(self, batch: ResultBatch) -> None:
        """Persist a batch of result records."""
        if batch.events:
            self._append_unique_many(
                "strategy_events.csv",
                tuple(ResultRowMapper.event(record) for record in batch.events),
                key_fields=("event_id",),
            )
        if batch.trades:
            self._append_many(
                "trade_summaries.csv",
                tuple(ResultRowMapper.trade(summary) for summary in batch.trades),
            )
        if batch.cycles:
            self._append_many(
                "cycle_summaries.csv",
                tuple(ResultRowMapper.cycle(summary) for summary in batch.cycles),
            )
        if batch.tasks:
            self._append_many(
                "task_summaries.csv",
                tuple(ResultRowMapper.task(summary) for summary in batch.tasks),
            )
        if batch.metrics:
            self._append_unique_many(
                "profit_metrics.csv",
                tuple(ResultRowMapper.metric(metric) for metric in batch.metrics),
                key_fields=("metric_id",),
            )

    def event_records(self, task_id: object | None = None) -> tuple[StrategyEventRecord, ...]:
        """Return persisted strategy event records."""
        return self._read_many("strategy_events.csv", ResultRowReader.event, task_id=task_id)

    def trade_summaries(self, task_id: object | None = None) -> tuple[TradeSummary, ...]:
        """Return persisted trade summaries."""
        return self._read_latest_many(
            "trade_summaries.csv",
            ResultRowReader.trade,
            task_id=task_id,
            key=lambda record: (record.task_id, record.trade_id),
        )

    def cycle_summaries(self, task_id: object | None = None) -> tuple[CycleSummary, ...]:
        """Return persisted cycle summaries."""
        return self._read_latest_many(
            "cycle_summaries.csv",
            ResultRowReader.cycle,
            task_id=task_id,
            key=lambda record: (record.task_id, record.cycle_id),
        )

    def task_summaries(self, task_id: object | None = None) -> tuple[TaskSummary, ...]:
        """Return persisted task summaries."""
        return self._read_latest_many(
            "task_summaries.csv",
            ResultRowReader.task,
            task_id=task_id,
            key=lambda record: (record.task_id,),
        )

    def profit_metrics(self, task_id: object | None = None) -> tuple[ProfitMetric, ...]:
        """Return persisted profit metrics."""
        return self._read_many("profit_metrics.csv", ResultRowReader.metric, task_id=task_id)

    def _append_unique_many(
        self,
        filename: str,
        rows: tuple[Mapping[str, Any], ...],
        *,
        key_fields: tuple[str, ...],
    ) -> None:
        if not rows:
            return
        path = self.directory / filename
        new_rows = tuple(
            {key: ResultRowMapper.csv_value(value) for key, value in row.items()} for row in rows
        )
        fieldnames = tuple(new_rows[0].keys())
        with self._lock:
            existing_keys = self._known_keys_for(filename, path, key_fields=key_fields)
            rows_to_append: list[dict[str, str]] = []
            queued_keys: set[tuple[str, ...]] = set()
            for row in new_rows:
                row_key = tuple(row[field] for field in key_fields)
                if row_key in existing_keys or row_key in queued_keys:
                    continue
                rows_to_append.append(row)
                queued_keys.add(row_key)
            if not rows_to_append:
                return
            write_header = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerows(rows_to_append)
            existing_keys.update(queued_keys)

    def _append_many(
        self,
        filename: str,
        rows: tuple[Mapping[str, Any], ...],
    ) -> None:
        if not rows:
            return
        path = self.directory / filename
        new_rows = tuple(
            {key: ResultRowMapper.csv_value(value) for key, value in row.items()} for row in rows
        )
        fieldnames = tuple(new_rows[0].keys())
        with self._lock:
            write_header = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerows(new_rows)

    def _read_many[RecordT: ResultRecord](
        self,
        filename: str,
        mapper: Callable[[Mapping[str, Any]], RecordT],
        *,
        task_id: object | None,
    ) -> tuple[RecordT, ...]:
        path = self.directory / filename
        if not path.exists():
            return ()
        with self._lock, path.open(newline="", encoding="utf-8") as handle:
            rows = tuple(csv.DictReader(handle))
        records = tuple(mapper(row) for row in rows)
        if task_id is None:
            return records
        return tuple(record for record in records if str(record.task_id) == str(task_id))

    def _read_latest_many[RecordT: ResultRecord, KeyT](
        self,
        filename: str,
        mapper: Callable[[Mapping[str, Any]], RecordT],
        *,
        task_id: object | None,
        key: Callable[[RecordT], KeyT],
    ) -> tuple[RecordT, ...]:
        records = self._read_many(filename, mapper, task_id=task_id)
        latest: dict[KeyT, RecordT] = {}
        for record in records:
            latest[key(record)] = record
        return tuple(latest.values())

    def _known_keys_for(
        self,
        filename: str,
        path: Path,
        *,
        key_fields: tuple[str, ...],
    ) -> set[tuple[str, ...]]:
        if filename in self._known_keys:
            return self._known_keys[filename]
        keys: set[tuple[str, ...]] = set()
        if path.exists():
            with path.open(newline="", encoding="utf-8") as handle:
                keys = {
                    tuple(existing.get(field, "") for field in key_fields)
                    for existing in csv.DictReader(handle)
                }
        self._known_keys[filename] = keys
        return keys
