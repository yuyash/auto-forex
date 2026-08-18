"""SQLAlchemy result store."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock
from typing import Any

from sqlalchemy import MetaData as SqlMetaData
from sqlalchemy import Table, create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.store_contracts import ResultBatch
from autoforex.core.results.store_rows import ResultRowMapper, ResultRowReader
from autoforex.core.results.store_sql_schema import SqlResultTables


class SqlResultStore:
    """Persist task results into a SQL database using SQLAlchemy."""

    def __init__(self, engine: Engine | str) -> None:
        self.engine = self.create_engine(engine) if isinstance(engine, str) else engine
        self.metadata = SqlMetaData()
        self.tables = SqlResultTables(self.metadata)
        self.metadata.create_all(self.engine)
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        self._insert(
            self.tables.strategy_events,
            ResultRowMapper.event(record),
            key={"event_id": str(record.event_id)},
        )

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        self._insert(
            self.tables.trade_summaries,
            ResultRowMapper.trade(summary),
            key={"task_id": str(summary.task_id), "trade_id": summary.trade_id},
        )

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary."""
        self._insert(
            self.tables.cycle_summaries,
            ResultRowMapper.cycle(summary),
            key={"task_id": str(summary.task_id), "cycle_id": summary.cycle_id},
        )

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary."""
        self._insert(
            self.tables.task_summaries,
            ResultRowMapper.task(summary),
            key={"task_id": str(summary.task_id)},
        )

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        self._insert(
            self.tables.profit_metrics,
            ResultRowMapper.metric(metric),
            key={"metric_id": str(metric.metric_id)},
        )

    def save_batch(self, batch: ResultBatch) -> None:
        """Persist a batch of result records."""
        if batch.is_empty:
            return
        with self._lock, self.engine.begin() as connection:
            for record in batch.events:
                self._insert_with_connection(
                    connection,
                    self.tables.strategy_events,
                    ResultRowMapper.event(record),
                    key={"event_id": str(record.event_id)},
                )
            for summary in batch.trades:
                self._insert_with_connection(
                    connection,
                    self.tables.trade_summaries,
                    ResultRowMapper.trade(summary),
                    key={"task_id": str(summary.task_id), "trade_id": summary.trade_id},
                )
            for summary in batch.cycles:
                self._insert_with_connection(
                    connection,
                    self.tables.cycle_summaries,
                    ResultRowMapper.cycle(summary),
                    key={"task_id": str(summary.task_id), "cycle_id": summary.cycle_id},
                )
            for summary in batch.tasks:
                self._insert_with_connection(
                    connection,
                    self.tables.task_summaries,
                    ResultRowMapper.task(summary),
                    key={"task_id": str(summary.task_id)},
                )
            for metric in batch.metrics:
                self._insert_with_connection(
                    connection,
                    self.tables.profit_metrics,
                    ResultRowMapper.metric(metric),
                    key={"metric_id": str(metric.metric_id)},
                )

    def event_records(self, task_id: object | None = None) -> tuple[StrategyEventRecord, ...]:
        """Return persisted strategy event records."""
        return self._read_many(
            self.tables.strategy_events,
            ResultRowReader.event,
            task_id=task_id,
            order_by=("timestamp", "event_id"),
        )

    def trade_summaries(self, task_id: object | None = None) -> tuple[TradeSummary, ...]:
        """Return persisted trade summaries."""
        return self._read_many(
            self.tables.trade_summaries,
            ResultRowReader.trade,
            task_id=task_id,
            order_by=("opened_at", "trade_id"),
        )

    def cycle_summaries(self, task_id: object | None = None) -> tuple[CycleSummary, ...]:
        """Return persisted cycle summaries."""
        return self._read_many(
            self.tables.cycle_summaries,
            ResultRowReader.cycle,
            task_id=task_id,
            order_by=("cycle_id",),
        )

    def task_summaries(self, task_id: object | None = None) -> tuple[TaskSummary, ...]:
        """Return persisted task summaries."""
        return self._read_many(
            self.tables.task_summaries,
            ResultRowReader.task,
            task_id=task_id,
            order_by=("task_id",),
        )

    def profit_metrics(self, task_id: object | None = None) -> tuple[ProfitMetric, ...]:
        """Return persisted profit metrics."""
        return self._read_many(
            self.tables.profit_metrics,
            ResultRowReader.metric,
            task_id=task_id,
            order_by=("timestamp", "metric_id"),
        )

    def close(self) -> None:
        """Dispose connections owned by this result store."""
        self.engine.dispose()

    def _insert(self, table: Table, row: Mapping[str, Any], *, key: Mapping[str, Any]) -> None:
        with self._lock, self.engine.begin() as connection:
            self._insert_with_connection(connection, table, row, key=key)

    def _read_many[RecordT](
        self,
        table: Table,
        mapper: Callable[[Mapping[str, Any]], RecordT],
        *,
        task_id: object | None,
        order_by: tuple[str, ...],
    ) -> tuple[RecordT, ...]:
        statement = select(table)
        if task_id is not None:
            statement = statement.where(table.c.task_id == str(task_id))
        for column_name in order_by:
            statement = statement.order_by(table.c[column_name])
        with self._lock, self.engine.connect() as connection:
            rows = tuple(dict(row) for row in connection.execute(statement).mappings())
        return tuple(mapper(row) for row in rows)

    @staticmethod
    def _insert_with_connection(
        connection: Any,
        table: Table,
        row: Mapping[str, Any],
        *,
        key: Mapping[str, Any],
    ) -> None:
        clause = None
        for column_name, value in key.items():
            condition = table.c[column_name] == value
            clause = condition if clause is None else clause & condition
        if clause is not None:
            connection.execute(delete(table).where(clause))
        connection.execute(table.insert().values(**ResultRowMapper.sql_row(row)))

    @staticmethod
    def create_engine(url: str) -> Engine:
        """Create a SQLAlchemy engine for a database URL."""
        if url in {"sqlite://", "sqlite:///:memory:"}:
            return create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        return create_engine(url)
