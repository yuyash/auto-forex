"""Query services for task activity resources such as trades and positions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import models
from django.db.models import (
    Case,
    CharField,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Abs, Cast
from rest_framework.request import Request

from apps.common.querying import OrderingConfig
from apps.market.models import MarketEvent
from apps.trading.enums import EventType, LogLevel
from apps.trading.models import TradingEvent
from apps.trading.models.logs import TaskLog
from apps.trading.models.orders import Order
from apps.trading.models.positions import Position
from apps.trading.models.trades import Trade
from apps.trading.services.trade_money import TradeMoneyEnricher
from apps.trading.views.pagination import ActivityPagination, TradePositionPagination
from apps.trading.views.query_params import (
    EventsQueryParams,
    LogComponentsQueryParams,
    LogsQueryParams,
    MarketEventsQueryParams,
    OrdersQueryParams,
    PositionQuery,
    TradesQueryParams,
)

PROTECTION_CLOSE_METHODS = frozenset(
    {"volatility_lock", "margin_protection", "shrink", "stop_loss"}
)
ORDER_TRADE_METHODS = frozenset(
    {"open_position", "rebuild_position", "initial_entry", "retracement", "market_entry"}
)

LOG_ORDERING = OrderingConfig(
    fields={
        "id": "id",
        "timestamp": "timestamp",
        "level": "level",
        "component": "component",
        "message": "message",
    },
    default="-timestamp",
)
EVENT_ORDERING = OrderingConfig(
    fields={
        "id": "id",
        "created_at": "created_at",
        "event_timestamp": "event_timestamp",
        "event_type": "event_type",
        "severity": "severity",
        "description": "description",
        "sequence_number": "sequence_number",
        "instrument": "instrument",
        "direction": "direction",
        "close_reason": "close_reason",
        "root_entry_id": "root_entry_id",
        "position_id": "position_id",
    },
    default="-created_at",
)
TRADE_ORDERING = OrderingConfig(
    fields={
        "id": "id",
        "timestamp": "timestamp",
        "instrument": "instrument",
        "direction": "direction",
        "units": "units",
        "price": "price",
        "execution_method": "execution_method",
        "layer_index": "layer_index",
        "retracement_count": "retracement_count",
        "description": "description",
        "position_id": "position_id",
        "order_id": "order_id",
        "oanda_trade_id": "oanda_trade_id",
        "cycle_id": "cycle_id",
        "stop_loss_price": "position__stop_loss_price",
        "replayed_at": "replayed_at",
        "updated_at": "updated_at",
        "is_rebuild": "is_rebuild",
        "is_initial_position_seed": "is_initial_position_seed",
        "sequence_number": "sequence_number",
    },
    default="-timestamp",
    tie_breakers=("sequence_number", "id"),
    legacy_direction_field="timestamp",
)
POSITION_ORDERING = OrderingConfig(
    fields={
        "id": "id",
        "instrument": "instrument",
        "direction": "direction",
        "units": "units",
        "entry_price": "entry_price",
        "entry_time": "entry_time",
        "exit_price": "exit_price",
        "exit_time": "exit_time",
        "is_open": "is_open",
        "layer_index": "layer_index",
        "retracement_count": "retracement_count",
        "planned_exit_price": "planned_exit_price",
        "planned_exit_price_formula": "planned_exit_price_formula",
        "adverse_pips": "adverse_pips",
        "stop_loss_price": "stop_loss_price",
        "is_rebuild": "is_rebuild",
        "is_initial_position_seed": "is_initial_position_seed",
        "oanda_trade_id": "oanda_trade_id",
        "replayed_at": "replayed_at",
        "updated_at": "updated_at",
        "unrealized_pnl": "unrealized_pnl",
        "realized_pnl": "_realized_pnl",
        "pnl": "_pnl",
        "pips": "_pips",
        "close_reason": "_close_reason",
    },
    default="-entry_time",
)
ORDER_ORDERING = OrderingConfig(
    fields={
        "id": "id",
        "submitted_at": "submitted_at",
        "instrument": "instrument",
        "order_type": "order_type",
        "direction": "direction",
        "units": "units",
        "status": "status",
        "broker_order_id": "broker_order_id",
        "oanda_trade_id": "oanda_trade_id",
        "requested_price": "requested_price",
        "fill_price": "fill_price",
        "filled_at": "filled_at",
        "cancelled_at": "cancelled_at",
        "stop_loss": "stop_loss",
        "error_message": "error_message",
        "replayed_at": "replayed_at",
        "updated_at": "updated_at",
        "is_dry_run": "is_dry_run",
    },
    default="-submitted_at",
)
MARKET_EVENT_ORDERING = OrderingConfig(
    fields={
        "id": "id",
        "created_at": "created_at",
        "event_type": "event_type",
        "category": "category",
        "severity": "severity",
        "instrument": "instrument",
        "description": "description",
    },
    default="-created_at",
)


class TaskActivityValueParser:
    """Parse loosely typed task-activity payload values."""

    def decimal_or_none(self, value) -> Decimal | None:
        """Convert optional values to Decimal without leaking parser errors."""
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None


class PositionSortQuery:
    """Add dashboard sort annotations for task positions."""

    def apply(self, queryset):
        """Annotate positions with computed close reason, PnL, and pips fields."""
        protection_reason = (
            Trade.objects.filter(
                position_id=OuterRef("pk"),
                execution_method__in=PROTECTION_CLOSE_METHODS,
            )
            .order_by("timestamp", "sequence_number")
            .values("execution_method")[:1]
        )
        protection_description_exists = Trade.objects.filter(
            position_id=OuterRef("pk"),
            description__startswith="[PROTECTION]",
        )
        decimal_field = DecimalField(max_digits=24, decimal_places=10)
        long_realized_pnl = ExpressionWrapper(
            (F("exit_price") - F("entry_price")) * Abs(F("units")),
            output_field=decimal_field,
        )
        short_realized_pnl = ExpressionWrapper(
            (F("entry_price") - F("exit_price")) * Abs(F("units")),
            output_field=decimal_field,
        )
        long_pips = ExpressionWrapper(
            F("exit_price") - F("entry_price"),
            output_field=decimal_field,
        )
        short_pips = ExpressionWrapper(
            F("entry_price") - F("exit_price"),
            output_field=decimal_field,
        )
        return queryset.annotate(
            _protection_reason=Subquery(protection_reason, output_field=CharField()),
            _has_protection_description=Exists(protection_description_exists),
            _close_reason=Case(
                When(is_open=True, then=Value("", output_field=CharField())),
                When(_protection_reason__isnull=False, then=F("_protection_reason")),
                When(_has_protection_description=True, then=Value("shrink")),
                default=Value("normal"),
                output_field=CharField(),
            ),
            _realized_pnl=Case(
                When(
                    is_open=False,
                    direction="long",
                    exit_price__isnull=False,
                    then=long_realized_pnl,
                ),
                When(
                    is_open=False,
                    direction="short",
                    exit_price__isnull=False,
                    then=short_realized_pnl,
                ),
                default=Value(None, output_field=decimal_field),
                output_field=decimal_field,
            ),
            _pnl=Case(
                When(is_open=True, then=F("unrealized_pnl")),
                When(
                    is_open=False,
                    direction="long",
                    exit_price__isnull=False,
                    then=long_realized_pnl,
                ),
                When(
                    is_open=False,
                    direction="short",
                    exit_price__isnull=False,
                    then=short_realized_pnl,
                ),
                default=Value(None, output_field=decimal_field),
                output_field=decimal_field,
            ),
            _pips=Case(
                When(
                    is_open=False,
                    direction="long",
                    exit_price__isnull=False,
                    then=long_pips,
                ),
                When(
                    is_open=False,
                    direction="short",
                    exit_price__isnull=False,
                    then=short_pips,
                ),
                default=F("unrealized_pnl"),
                output_field=decimal_field,
            ),
        )


class TaskActivityQueryService:
    """Build querysets and rows for task activity endpoints."""

    def __init__(
        self,
        *,
        value_parser: TaskActivityValueParser | None = None,
        position_sort_query: PositionSortQuery | None = None,
    ) -> None:
        """Initialize object collaborators for task activity queries."""
        self.value_parser = value_parser or TaskActivityValueParser()
        self.position_sort_query = position_sort_query or PositionSortQuery()

    def logs_queryset(self, *, request: Request, task, task_type_label: str):
        query = LogsQueryParams.from_request(
            request,
            default_execution_id=task.execution_id,
            default_page_size=ActivityPagination.page_size,
            max_page_size=ActivityPagination.max_page_size,
        )
        queryset = TaskLog.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution.execution_id,
        )
        if query.levels:
            resolved = [LogLevel[v] for v in query.levels if v in LogLevel.__members__]
            if resolved:
                queryset = queryset.filter(level__in=resolved)
        if query.components:
            queryset = queryset.filter(component__in=query.components)
        if query.message:
            if query.message_match == "exact":
                queryset = queryset.filter(message=query.message)
            elif query.message_match == "regex":
                queryset = queryset.filter(message__regex=query.message)
            else:
                queryset = queryset.filter(message__icontains=query.message)
        if query.position_id:
            queryset = queryset.annotate(
                _pos_id=KeyTextTransform("position_id", KeyTextTransform("context", "details")),
                _orig_pos_id=KeyTextTransform(
                    "original_position_id", KeyTextTransform("context", "details")
                ),
            ).filter(
                Q(_pos_id__startswith=query.position_id)
                | Q(_orig_pos_id__startswith=query.position_id)
            )
        if query.timestamp_range.start:
            queryset = queryset.filter(timestamp__gte=query.timestamp_range.start)
        if query.timestamp_range.end:
            queryset = queryset.filter(timestamp__lte=query.timestamp_range.end)
        if query.execution.since:
            queryset = queryset.filter(timestamp__gt=query.execution.since)
        return LOG_ORDERING.apply_to_queryset(queryset, query.ordering)

    @staticmethod
    def log_components(*, request: Request, task, task_type_label: str) -> list[str]:
        query = LogComponentsQueryParams.from_request(
            request,
            default_execution_id=task.execution_id,
        )
        return list(
            TaskLog.objects.filter(
                task_type=task_type_label,
                task_id=task.pk,
                execution_id=query.execution_id,
            )
            .values_list("component", flat=True)
            .distinct()
            .order_by("component")
        )

    def events_queryset(self, *, request: Request, task, task_type_label: str):
        query = EventsQueryParams.from_request(
            request,
            default_execution_id=task.execution_id,
        )
        queryset = TradingEvent.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution.execution_id,
        )
        if query.event_type:
            queryset = queryset.filter(event_type=query.event_type)
        if query.severity:
            queryset = queryset.filter(severity=query.severity)
        if query.scope in {"trading", "task"}:
            task_scoped_event_types = EventType.task_scoped_values()
            if query.scope == "task":
                queryset = queryset.filter(
                    Q(details__kind__startswith="task_") | Q(event_type__in=task_scoped_event_types)
                )
            else:
                queryset = queryset.filter(
                    Q(details__kind__isnull=True) | ~Q(details__kind__startswith="task_")
                ).exclude(event_type__in=task_scoped_event_types)
        if query.execution.since:
            queryset = queryset.filter(created_at__gt=query.execution.since)
        if query.created_range.start:
            queryset = queryset.filter(created_at__gte=query.created_range.start)
        if query.created_range.end:
            queryset = queryset.filter(created_at__lte=query.created_range.end)
        return EVENT_ORDERING.apply_to_queryset(queryset, query.ordering)

    def market_events_queryset(self, *, request: Request, task, task_type_label: str):
        query = MarketEventsQueryParams.from_request(
            request,
            default_execution_id=task.execution_id,
            default_page_size=ActivityPagination.page_size,
            max_page_size=ActivityPagination.max_page_size,
        )
        queryset = MarketEvent.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution.execution_id,
        )
        if query.event_type:
            queryset = queryset.filter(event_type__icontains=query.event_type)
        if query.severities:
            queryset = queryset.filter(severity__in=query.severities)
        if query.categories:
            queryset = queryset.filter(category__in=query.categories)
        if query.instrument:
            queryset = queryset.filter(instrument__iexact=query.instrument)
        if query.message:
            queryset = queryset.filter(description__icontains=query.message)
        if query.execution.since:
            queryset = queryset.filter(created_at__gt=query.execution.since)
        if query.created_range.start:
            queryset = queryset.filter(created_at__gte=query.created_range.start)
        if query.created_range.end:
            queryset = queryset.filter(created_at__lte=query.created_range.end)
        return MARKET_EVENT_ORDERING.apply_to_queryset(queryset, query.ordering)

    @staticmethod
    def orders_queryset(*, request: Request, task, task_type_label: str):
        query = OrdersQueryParams.from_request(
            request,
            default_execution_id=task.execution_id,
            default_page_size=TradePositionPagination.page_size,
            max_page_size=TradePositionPagination.max_page_size,
        )
        queryset = Order.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution.execution_id,
        )
        if query.status:
            queryset = queryset.filter(status=query.status)
        if query.order_type:
            queryset = queryset.filter(order_type=query.order_type)
        if query.direction:
            queryset = queryset.filter(direction=query.direction)
        if query.order_id:
            queryset = queryset.annotate(
                _id_str=Cast("id", output_field=models.CharField())
            ).filter(_id_str__istartswith=query.order_id)
        if query.execution.since:
            queryset = queryset.filter(updated_at__gt=query.execution.since)
        if query.timestamp_range.start:
            queryset = queryset.filter(submitted_at__gte=query.timestamp_range.start)
        if query.timestamp_range.end:
            queryset = queryset.filter(submitted_at__lte=query.timestamp_range.end)
        return ORDER_ORDERING.apply_to_queryset(queryset, query.ordering)

    def trades(
        self, *, request: Request, task, task_type_label: str
    ) -> tuple[list[dict], int, int, int]:
        query = TradesQueryParams.from_request(
            request,
            default_execution_id=task.execution_id,
        )
        queryset = Trade.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution.execution_id,
        )
        if query.direction:
            if query.direction == "buy":
                queryset = queryset.filter(direction="long")
            elif query.direction == "sell":
                queryset = queryset.filter(direction="short")
            else:
                queryset = queryset.filter(direction=query.direction)

        if query.execution.since:
            queryset = queryset.filter(updated_at__gt=query.execution.since)
        if query.timestamp_range.start:
            queryset = queryset.filter(timestamp__gte=query.timestamp_range.start)
        if query.timestamp_range.end:
            queryset = queryset.filter(timestamp__lte=query.timestamp_range.end)
        if query.cycle_id:
            queryset = queryset.filter(cycle_id=query.cycle_id)
        if query.trade_id:
            queryset = queryset.annotate(
                _id_str=Cast("id", output_field=models.CharField())
            ).filter(_id_str__istartswith=query.trade_id)
        if query.trade_kind == "order":
            queryset = queryset.filter(execution_method__in=ORDER_TRADE_METHODS)
        elif query.trade_kind == "close":
            queryset = queryset.exclude(execution_method__in=ORDER_TRADE_METHODS)

        queryset = TRADE_ORDERING.apply_to_queryset(queryset, query.ordering)

        total_count = queryset.count()
        page = query.execution.pagination.page
        page_size = query.execution.pagination.page_size
        start = (page - 1) * page_size
        rows = list(
            queryset.values(
                "id",
                "direction",
                "units",
                "instrument",
                "price",
                "price_currency",
                "execution_method",
                "layer_index",
                "retracement_count",
                "description",
                "timestamp",
                "position_id",
                "order_id",
                "oanda_trade_id",
                "cycle_id",
                "replayed_at",
                "updated_at",
                "is_rebuild",
                "is_initial_position_seed",
                stop_loss_price=models.F("position__stop_loss_price"),
                entry_price=models.F("position__entry_price"),
            )[start : start + page_size]
        )
        close_snapshots = self._close_snapshots_by_order_id(
            rows=rows,
            task=task,
            task_type_label=task_type_label,
            execution_id=query.execution.execution_id,
        )
        normalized_rows = self._normalize_trade_rows(rows, close_snapshots)
        enriched_rows = TradeMoneyEnricher.for_task(
            task=task,
            task_type_label=task_type_label,
        ).enrich_rows(normalized_rows)
        return enriched_rows, total_count, page, page_size

    @staticmethod
    def _close_snapshots_by_order_id(
        *,
        rows: list[dict],
        task,
        task_type_label: str,
        execution_id,
    ) -> dict[str, dict]:
        order_ids = {
            str(row["order_id"])
            for row in rows
            if row.get("order_id") and row.get("execution_method") not in ORDER_TRADE_METHODS
        }
        if not order_ids:
            return {}

        logs = TaskLog.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=execution_id,
            component="position.lifecycle",
            details__context__lifecycle_event__in=("CLOSED", "PARTIAL_CLOSE"),
            details__context__order_id__in=order_ids,
        ).values("details")

        snapshots: dict[str, dict] = {}
        for log in logs:
            details = log.get("details")
            context = details.get("context") if isinstance(details, dict) else None
            if not isinstance(context, dict):
                continue
            order_id = context.get("order_id")
            if order_id:
                snapshots[str(order_id)] = context
        return snapshots

    def positions_queryset(self, *, request: Request, task, task_type_label: str):
        query = PositionQuery.from_request(
            request,
            default_execution_id=task.execution_id,
            default_page_size=TradePositionPagination.page_size,
            max_page_size=TradePositionPagination.max_page_size,
        )
        queryset = Position.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution.execution_id,
        )

        if query.position_status == "open":
            queryset = queryset.filter(is_open=True)
        elif query.position_status == "closed":
            queryset = queryset.filter(is_open=False)
        if query.initial_position_filter == "initial":
            queryset = queryset.filter(is_initial_position_seed=True)
        elif query.initial_position_filter == "normal":
            queryset = queryset.filter(is_initial_position_seed=False)
        if query.direction:
            queryset = queryset.filter(direction=query.direction)
        if query.execution.since:
            queryset = queryset.filter(updated_at__gt=query.execution.since)
        if query.range.end:
            queryset = queryset.filter(entry_time__lte=query.range.end)
        if query.range.start:
            queryset = queryset.filter(
                Q(exit_time__isnull=True) | Q(exit_time__gte=query.range.start)
            )
        if query.cycle_id:
            queryset = queryset.filter(trades__cycle_id=query.cycle_id).distinct()
        if query.position_id:
            queryset = queryset.annotate(
                _id_str=Cast("id", output_field=models.CharField())
            ).filter(_id_str__istartswith=query.position_id)

        queryset = self.position_sort_query.apply(queryset)
        if query.include_trade_ids:
            queryset = queryset.prefetch_related("trades")
        queryset = POSITION_ORDERING.apply_to_queryset(queryset, query.ordering)
        return queryset, query

    def _normalize_trade_rows(
        self,
        rows,
        close_snapshots_by_order_id: dict[str, dict] | None = None,
    ) -> list[dict]:
        normalized: list[dict] = []
        for trade in rows:
            raw_direction = trade["direction"]
            if raw_direction is None:
                trade["direction"] = None
            else:
                side = str(raw_direction).lower()
                trade["direction"] = (
                    "buy" if side == "long" else "sell" if side == "short" else side
                )
            trade["pnl"] = None
            if trade["execution_method"] not in ORDER_TRADE_METHODS:
                snapshot = (
                    close_snapshots_by_order_id.get(str(trade["order_id"]))
                    if close_snapshots_by_order_id and trade.get("order_id")
                    else None
                )
                if snapshot:
                    snapshot_entry = self.value_parser.decimal_or_none(snapshot.get("entry_price"))
                    snapshot_exit = self.value_parser.decimal_or_none(snapshot.get("exit_price"))
                    if snapshot_entry is not None:
                        trade["entry_price"] = snapshot_entry
                    if snapshot_exit is not None:
                        trade["price"] = snapshot_exit

                entry_price = trade.get("entry_price")
                if entry_price is not None and trade["price"] is not None:
                    entry = Decimal(str(entry_price))
                    exit_price = Decimal(str(trade["price"]))
                    units = abs(int(trade["units"]))
                    if trade["direction"] == "buy":
                        trade["pnl"] = exit_price - entry
                    elif trade["direction"] == "sell":
                        trade["pnl"] = entry - exit_price
                    if trade["pnl"] is not None:
                        trade["pnl"] *= units
            else:
                trade.pop("entry_price", None)
            normalized.append(trade)
        return normalized
