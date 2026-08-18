"""Row mapping for tabular result stores."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime as DateTime
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import CurrencyPair, Money
from autoforex.core.models.values import Units
from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.strategies.execution import StrategyAction, StrategyDecisionCode, TradeSide


class ResultRowMapper:
    """Map result domain models into tabular row dictionaries."""

    @classmethod
    def event(cls, record: StrategyEventRecord) -> dict[str, Any]:
        """Map an event record."""
        row = {
            "event_id": str(record.event_id),
            "task_id": str(record.task_id),
            "timestamp": record.timestamp,
            "display_id": record.display_id,
            "action": record.action.value,
            "instrument": str(record.instrument),
            "side": None if record.side is None else record.side.value,
            "units": cls.units(record.units),
            "decision": record.decision.value,
            "rule": record.rule,
            "snowball_event": record.snowball_event,
            "cycle_id": record.cycle_id,
            "direction": record.direction,
            "entry_id": record.entry_id,
            "entry_type": record.entry_type,
            "entry_role": record.entry_role,
            "layer_number": record.layer_number,
            "slot_number": record.slot_number,
            "retracement_count": record.retracement_count,
            "build_number": record.build_number,
            "close_reason": record.close_reason,
            "is_rebuild": record.is_rebuild,
            "planned_units": cls.units(record.planned_units),
            "filled_units": cls.units(record.filled_units),
            "metadata_json": cls.metadata_json(record.metadata),
        }
        row.update(cls.money("price", record.price))
        row.update(cls.money("planned_entry_price", record.planned_entry_price))
        row.update(cls.money("filled_entry_price", record.filled_entry_price))
        row.update(cls.money("planned_take_profit_price", record.planned_take_profit_price))
        row.update(cls.money("filled_take_profit_price", record.filled_take_profit_price))
        row.update(cls.money("planned_stop_loss_price", record.planned_stop_loss_price))
        row.update(cls.money("filled_stop_loss_price", record.filled_stop_loss_price))
        row.update(cls.money("planned_rebuild_price", record.planned_rebuild_price))
        row.update(cls.money("filled_rebuild_price", record.filled_rebuild_price))
        row.update(cls.money("realized_pl", record.realized_pl))
        return row

    @classmethod
    def trade(cls, summary: TradeSummary) -> dict[str, Any]:
        """Map a trade summary."""
        row = {
            "task_id": str(summary.task_id),
            "trade_id": summary.trade_id,
            "instrument": str(summary.instrument),
            "side": None if summary.side is None else summary.side.value,
            "direction": summary.direction,
            "display_id": summary.display_id,
            "cycle_id": summary.cycle_id,
            "entry_role": summary.entry_role,
            "layer_number": summary.layer_number,
            "slot_number": summary.slot_number,
            "build_number": summary.build_number,
            "opened_at": summary.opened_at,
            "closed_at": summary.closed_at,
            "open_event_id": None if summary.open_event_id is None else str(summary.open_event_id),
            "close_event_id": (
                None if summary.close_event_id is None else str(summary.close_event_id)
            ),
            "close_reason": summary.close_reason,
            "units": cls.units(summary.units),
            "metadata_json": cls.metadata_json(summary.metadata),
        }
        row.update(cls.money("planned_entry_price", summary.planned_entry_price))
        row.update(cls.money("filled_entry_price", summary.filled_entry_price))
        row.update(cls.money("planned_take_profit_price", summary.planned_take_profit_price))
        row.update(cls.money("filled_take_profit_price", summary.filled_take_profit_price))
        row.update(cls.money("planned_stop_loss_price", summary.planned_stop_loss_price))
        row.update(cls.money("filled_stop_loss_price", summary.filled_stop_loss_price))
        row.update(cls.money("planned_rebuild_price", summary.planned_rebuild_price))
        row.update(cls.money("filled_rebuild_price", summary.filled_rebuild_price))
        row.update(cls.money("realized_pl", summary.realized_pl))
        return row

    @classmethod
    def cycle(cls, summary: CycleSummary) -> dict[str, Any]:
        """Map a cycle summary."""
        row = {
            "task_id": str(summary.task_id),
            "cycle_id": summary.cycle_id,
            "instrument": str(summary.instrument),
            "trade_ids_json": json.dumps(summary.trade_ids),
            "opened_at": summary.opened_at,
            "closed_at": summary.closed_at,
            "trade_count": summary.trade_count,
            "open_trade_count": summary.open_trade_count,
            "closed_trade_count": summary.closed_trade_count,
            "metadata_json": cls.metadata_json(summary.metadata),
        }
        row.update(cls.money("realized_pl", summary.realized_pl))
        return row

    @classmethod
    def task(cls, summary: TaskSummary) -> dict[str, Any]:
        """Map a task summary."""
        row = {
            "task_id": str(summary.task_id),
            "instrument": str(summary.instrument),
            "task_name": summary.task_name,
            "status": summary.status,
            "started_at": summary.started_at,
            "finished_at": summary.finished_at,
            "trade_count": summary.trade_count,
            "open_trade_count": summary.open_trade_count,
            "closed_trade_count": summary.closed_trade_count,
            "metadata_json": cls.metadata_json(summary.metadata),
        }
        row.update(cls.money("realized_pl", summary.realized_pl))
        return row

    @classmethod
    def metric(cls, metric: ProfitMetric) -> dict[str, Any]:
        """Map a profit metric."""
        row = {
            "metric_id": str(metric.metric_id),
            "task_id": str(metric.task_id),
            "timestamp": metric.timestamp,
            "instrument": str(metric.instrument),
            "open_trade_count": metric.open_trade_count,
            "closed_trade_count": metric.closed_trade_count,
            "interval_seconds": metric.interval_seconds,
            "metadata_json": cls.metadata_json(metric.metadata),
        }
        row.update(cls.money("realized_pl", metric.realized_pl))
        row.update(cls.money("unrealized_pl", metric.unrealized_pl))
        row.update(cls.money("total_pl", metric.total_pl))
        return row

    @staticmethod
    def money(prefix: str, value: Money | None) -> dict[str, str | None]:
        """Map a Money value into amount/currency columns."""
        if value is None:
            return {f"{prefix}_amount": None, f"{prefix}_currency": None}
        return {f"{prefix}_amount": str(value.amount), f"{prefix}_currency": value.currency.code}

    @staticmethod
    def units(value: Units | None) -> str | None:
        """Map Units into text."""
        return None if value is None else str(value)

    @staticmethod
    def metadata_json(metadata: Metadata) -> str:
        """Map metadata into stable JSON text."""
        return json.dumps(metadata.to_jsonable(), ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def csv_value(value: Any) -> str:
        """Map one row value into CSV text."""
        if value is None:
            return ""
        if isinstance(value, DateTime):
            return value.isoformat()
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @classmethod
    def sql_row(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        """Map a row into SQLAlchemy-compatible values."""
        return {key: cls.sql_value(value) for key, value in row.items()}

    @staticmethod
    def sql_value(value: Any) -> Any:
        """Map one row value into a SQL-compatible scalar."""
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, CurrencyPair):
            return str(value)
        if isinstance(value, Units):
            return str(value)
        return value


class ResultRowReader:
    """Map tabular result rows back into domain models."""

    @classmethod
    def event(cls, row: Mapping[str, Any]) -> StrategyEventRecord:
        """Return a strategy event record from a row."""
        instrument = cls.instrument(row["instrument"])
        return StrategyEventRecord(
            event_id=cls.uuid(row["event_id"]),
            task_id=cls.uuid(row["task_id"]),
            timestamp=cls.datetime(row["timestamp"]),
            display_id=cls.text(row.get("display_id")),
            action=StrategyAction(cls.text(row["action"])),
            instrument=instrument,
            side=cls.trade_side(row.get("side")),
            units=cls.units(row.get("units")),
            price=cls.money(row, "price"),
            decision=StrategyDecisionCode(cls.text(row["decision"])),
            rule=cls.text(row.get("rule")),
            metadata=cls.metadata(row.get("metadata_json")),
            snowball_event=cls.text(row.get("snowball_event")),
            cycle_id=cls.integer(row.get("cycle_id")),
            direction=cls.text(row.get("direction")),
            entry_id=cls.text(row.get("entry_id")),
            entry_type=cls.text(row.get("entry_type")),
            entry_role=cls.text(row.get("entry_role")),
            layer_number=cls.integer(row.get("layer_number")),
            slot_number=cls.integer(row.get("slot_number")),
            retracement_count=cls.integer(row.get("retracement_count")),
            build_number=cls.integer(row.get("build_number")),
            close_reason=cls.text(row.get("close_reason")),
            is_rebuild=cls.boolean(row.get("is_rebuild")),
            planned_units=cls.units(row.get("planned_units")),
            filled_units=cls.units(row.get("filled_units")),
            planned_entry_price=cls.money(row, "planned_entry_price"),
            filled_entry_price=cls.money(row, "filled_entry_price"),
            planned_take_profit_price=cls.money(row, "planned_take_profit_price"),
            filled_take_profit_price=cls.money(row, "filled_take_profit_price"),
            planned_stop_loss_price=cls.money(row, "planned_stop_loss_price"),
            filled_stop_loss_price=cls.money(row, "filled_stop_loss_price"),
            planned_rebuild_price=cls.money(row, "planned_rebuild_price"),
            filled_rebuild_price=cls.money(row, "filled_rebuild_price"),
            realized_pl=cls.money(row, "realized_pl"),
        )

    @classmethod
    def trade(cls, row: Mapping[str, Any]) -> TradeSummary:
        """Return a trade summary from a row."""
        return TradeSummary(
            task_id=cls.uuid(row["task_id"]),
            trade_id=cls.text(row["trade_id"]),
            instrument=cls.instrument(row["instrument"]),
            side=cls.trade_side(row.get("side")),
            direction=cls.text(row.get("direction")),
            display_id=cls.text(row.get("display_id")),
            cycle_id=cls.integer(row.get("cycle_id")),
            entry_role=cls.text(row.get("entry_role")),
            layer_number=cls.integer(row.get("layer_number")),
            slot_number=cls.integer(row.get("slot_number")),
            build_number=cls.integer(row.get("build_number")),
            opened_at=cls.optional_datetime(row.get("opened_at")),
            closed_at=cls.optional_datetime(row.get("closed_at")),
            open_event_id=cls.optional_uuid(row.get("open_event_id")),
            close_event_id=cls.optional_uuid(row.get("close_event_id")),
            close_reason=cls.text(row.get("close_reason")),
            units=cls.units(row.get("units")),
            planned_entry_price=cls.money(row, "planned_entry_price"),
            filled_entry_price=cls.money(row, "filled_entry_price"),
            planned_take_profit_price=cls.money(row, "planned_take_profit_price"),
            filled_take_profit_price=cls.money(row, "filled_take_profit_price"),
            planned_stop_loss_price=cls.money(row, "planned_stop_loss_price"),
            filled_stop_loss_price=cls.money(row, "filled_stop_loss_price"),
            planned_rebuild_price=cls.money(row, "planned_rebuild_price"),
            filled_rebuild_price=cls.money(row, "filled_rebuild_price"),
            realized_pl=cls.money(row, "realized_pl"),
            metadata=cls.metadata(row.get("metadata_json")),
        )

    @classmethod
    def cycle(cls, row: Mapping[str, Any]) -> CycleSummary:
        """Return a cycle summary from a row."""
        instrument = cls.instrument(row["instrument"])
        return CycleSummary(
            task_id=cls.uuid(row["task_id"]),
            cycle_id=cls.integer(row["cycle_id"]) or 0,
            instrument=instrument,
            trade_ids=tuple(json.loads(cls.text(row.get("trade_ids_json")) or "[]")),
            opened_at=cls.optional_datetime(row.get("opened_at")),
            closed_at=cls.optional_datetime(row.get("closed_at")),
            trade_count=cls.integer(row.get("trade_count")) or 0,
            open_trade_count=cls.integer(row.get("open_trade_count")) or 0,
            closed_trade_count=cls.integer(row.get("closed_trade_count")) or 0,
            realized_pl=cls.money(row, "realized_pl") or Money.of("0", instrument.quote),
            metadata=cls.metadata(row.get("metadata_json")),
        )

    @classmethod
    def task(cls, row: Mapping[str, Any]) -> TaskSummary:
        """Return a task summary from a row."""
        return TaskSummary(
            task_id=cls.uuid(row["task_id"]),
            instrument=cls.instrument(row["instrument"]),
            task_name=cls.text(row.get("task_name")),
            status=cls.text(row.get("status")),
            started_at=cls.optional_datetime(row.get("started_at")),
            finished_at=cls.optional_datetime(row.get("finished_at")),
            trade_count=cls.integer(row.get("trade_count")) or 0,
            open_trade_count=cls.integer(row.get("open_trade_count")) or 0,
            closed_trade_count=cls.integer(row.get("closed_trade_count")) or 0,
            realized_pl=cls.money(row, "realized_pl"),
            metadata=cls.metadata(row.get("metadata_json")),
        )

    @classmethod
    def metric(cls, row: Mapping[str, Any]) -> ProfitMetric:
        """Return a profit metric from a row."""
        instrument = cls.instrument(row["instrument"])
        zero = Money.of("0", instrument.quote)
        return ProfitMetric(
            metric_id=cls.uuid(row["metric_id"]),
            task_id=cls.uuid(row["task_id"]),
            timestamp=cls.datetime(row["timestamp"]),
            instrument=instrument,
            realized_pl=cls.money(row, "realized_pl") or zero,
            unrealized_pl=cls.money(row, "unrealized_pl") or zero,
            total_pl=cls.money(row, "total_pl") or zero,
            open_trade_count=cls.integer(row.get("open_trade_count")) or 0,
            closed_trade_count=cls.integer(row.get("closed_trade_count")) or 0,
            interval=timedelta(seconds=cls.integer(row.get("interval_seconds")) or 0),
            metadata=cls.metadata(row.get("metadata_json")),
        )

    @staticmethod
    def text(value: Any) -> str:
        """Return a row value as text."""
        if value is None:
            return ""
        return str(value)

    @classmethod
    def integer(cls, value: Any) -> int | None:
        """Return a row value as an integer."""
        if value is None or value == "":
            return None
        return int(value)

    @classmethod
    def boolean(cls, value: Any) -> bool:
        """Return a row value as a boolean."""
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return False
        return str(value).lower() in {"1", "true", "yes"}

    @classmethod
    def uuid(cls, value: Any) -> UUID:
        """Return a row value as a UUID."""
        return UUID(str(value))

    @classmethod
    def optional_uuid(cls, value: Any) -> UUID | None:
        """Return a row value as an optional UUID."""
        if value is None or value == "":
            return None
        return cls.uuid(value)

    @classmethod
    def datetime(cls, value: Any) -> DateTime:
        """Return a row value as a datetime."""
        parsed = cls.optional_datetime(value)
        if parsed is None:
            msg = "datetime value is required"
            raise ValueError(msg)
        return parsed

    @classmethod
    def optional_datetime(cls, value: Any) -> DateTime | None:
        """Return a row value as an optional datetime."""
        if value is None or value == "":
            return None
        if isinstance(value, DateTime):
            return value
        return DateTime.fromisoformat(str(value))

    @classmethod
    def instrument(cls, value: Any) -> CurrencyPair:
        """Return a row value as a currency pair."""
        return CurrencyPair.of(str(value))

    @classmethod
    def trade_side(cls, value: Any) -> TradeSide | None:
        """Return a row value as an optional trade side."""
        if value is None or value == "":
            return None
        return TradeSide(str(value))

    @classmethod
    def units(cls, value: Any) -> Units | None:
        """Return a row value as optional units."""
        if value is None or value == "":
            return None
        return Units.of(str(value))

    @classmethod
    def money(cls, row: Mapping[str, Any], prefix: str) -> Money | None:
        """Return a row money pair."""
        amount = row.get(f"{prefix}_amount")
        currency = row.get(f"{prefix}_currency")
        if amount is None or amount == "" or currency is None or currency == "":
            return None
        return Money.of(str(amount), str(currency))

    @classmethod
    def metadata(cls, value: Any) -> Metadata:
        """Return row metadata."""
        if value is None or value == "":
            return Metadata()
        if isinstance(value, Metadata):
            return value
        if isinstance(value, Mapping):
            return Metadata.model_validate(value)
        return Metadata.model_validate(json.loads(str(value)))
