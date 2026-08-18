"""SQLAlchemy schema for result stores."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Table, Text
from sqlalchemy import MetaData as SqlMetaData


@dataclass(frozen=True, slots=True)
class SqlResultTables:
    """SQLAlchemy table collection for result persistence."""

    metadata: SqlMetaData
    strategy_events: Table = field(init=False)
    trade_summaries: Table = field(init=False)
    cycle_summaries: Table = field(init=False)
    task_summaries: Table = field(init=False)
    profit_metrics: Table = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_events", self.strategy_events_table())
        object.__setattr__(self, "trade_summaries", self.trade_summaries_table())
        object.__setattr__(self, "cycle_summaries", self.cycle_summaries_table())
        object.__setattr__(self, "task_summaries", self.task_summaries_table())
        object.__setattr__(self, "profit_metrics", self.profit_metrics_table())

    def strategy_events_table(self) -> Table:
        """Build the strategy events table."""
        return Table(
            "strategy_events",
            self.metadata,
            Column("event_id", String(36), primary_key=True),
            *self.shared_event_columns(),
            Column("snowball_event", String(64)),
            Column("entry_id", String(128)),
            Column("entry_type", String(32)),
            Column("entry_role", String(64)),
            Column("retracement_count", Integer),
            Column("close_reason", String(64)),
            Column("is_rebuild", Boolean),
            Column("planned_units", String(64)),
            Column("filled_units", String(64)),
            *self.money_columns("planned_entry_price"),
            *self.money_columns("filled_entry_price"),
            *self.money_columns("planned_take_profit_price"),
            *self.money_columns("filled_take_profit_price"),
            *self.money_columns("planned_stop_loss_price"),
            *self.money_columns("filled_stop_loss_price"),
            *self.money_columns("planned_rebuild_price"),
            *self.money_columns("filled_rebuild_price"),
            *self.money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def trade_summaries_table(self) -> Table:
        """Build the trade summaries table."""
        return Table(
            "trade_summaries",
            self.metadata,
            Column("task_id", String(36), primary_key=True),
            Column("trade_id", String(128), primary_key=True),
            Column("instrument", String(16), nullable=False),
            Column("side", String(16)),
            Column("direction", String(16)),
            Column("display_id", String(128)),
            Column("cycle_id", Integer),
            Column("entry_role", String(64)),
            Column("layer_number", Integer),
            Column("slot_number", Integer),
            Column("build_number", Integer),
            Column("opened_at", DateTime(timezone=True)),
            Column("closed_at", DateTime(timezone=True)),
            Column("open_event_id", String(36)),
            Column("close_event_id", String(36)),
            Column("close_reason", String(64)),
            Column("units", String(64)),
            *self.money_columns("planned_entry_price"),
            *self.money_columns("filled_entry_price"),
            *self.money_columns("planned_take_profit_price"),
            *self.money_columns("filled_take_profit_price"),
            *self.money_columns("planned_stop_loss_price"),
            *self.money_columns("filled_stop_loss_price"),
            *self.money_columns("planned_rebuild_price"),
            *self.money_columns("filled_rebuild_price"),
            *self.money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def cycle_summaries_table(self) -> Table:
        """Build the cycle summaries table."""
        return Table(
            "cycle_summaries",
            self.metadata,
            Column("task_id", String(36), primary_key=True),
            Column("cycle_id", Integer, primary_key=True),
            Column("instrument", String(16), nullable=False),
            Column("trade_ids_json", Text),
            Column("opened_at", DateTime(timezone=True)),
            Column("closed_at", DateTime(timezone=True)),
            Column("trade_count", Integer),
            Column("open_trade_count", Integer),
            Column("closed_trade_count", Integer),
            *self.money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def task_summaries_table(self) -> Table:
        """Build the task summaries table."""
        return Table(
            "task_summaries",
            self.metadata,
            Column("task_id", String(36), primary_key=True),
            Column("instrument", String(16), nullable=False),
            Column("task_name", String(256)),
            Column("status", String(64)),
            Column("started_at", DateTime(timezone=True)),
            Column("finished_at", DateTime(timezone=True)),
            Column("trade_count", Integer),
            Column("open_trade_count", Integer),
            Column("closed_trade_count", Integer),
            *self.money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def profit_metrics_table(self) -> Table:
        """Build the profit metrics table."""
        return Table(
            "profit_metrics",
            self.metadata,
            Column("metric_id", String(36), primary_key=True),
            Column("task_id", String(36), nullable=False),
            Column("timestamp", DateTime(timezone=True), nullable=False),
            Column("instrument", String(16), nullable=False),
            *self.money_columns("realized_pl"),
            *self.money_columns("unrealized_pl"),
            *self.money_columns("total_pl"),
            Column("open_trade_count", Integer),
            Column("closed_trade_count", Integer),
            Column("interval_seconds", Integer),
            Column("metadata_json", Text),
        )

    def shared_event_columns(self) -> tuple[Column[Any], ...]:
        """Return columns shared by strategy event records."""
        return (
            Column("task_id", String(36), nullable=False),
            Column("timestamp", DateTime(timezone=True), nullable=False),
            Column("display_id", String(128)),
            Column("action", String(64), nullable=False),
            Column("instrument", String(16), nullable=False),
            Column("side", String(16)),
            Column("units", String(64)),
            *self.money_columns("price"),
            Column("decision", String(64)),
            Column("rule", String(256)),
            Column("cycle_id", Integer),
            Column("direction", String(16)),
            Column("layer_number", Integer),
            Column("slot_number", Integer),
            Column("build_number", Integer),
        )

    @staticmethod
    def money_columns(prefix: str) -> tuple[Column[Any], Column[Any]]:
        """Return amount/currency columns for a money field."""
        return (
            Column(f"{prefix}_amount", String(128)),
            Column(f"{prefix}_currency", String(3)),
        )
