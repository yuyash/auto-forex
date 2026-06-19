"""Shared query parameter validation and schema objects for task endpoints."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from apps.trading.views.pagination import (
    ActivityPagination,
    TradePositionPagination,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryFieldSpec:
    """Shared runtime and schema definition for query parameters."""

    name: str
    help_text: str
    kind: str
    default: object | None = None
    max_value: int | None = None
    choices: tuple[str, ...] | None = None
    allow_blank: bool = False

    def schema_field(self) -> serializers.Field:
        if self.kind == "datetime":
            return serializers.DateTimeField(
                required=False,
                allow_null=True,
                help_text=self.help_text,
            )
        if self.kind == "uuid":
            return serializers.UUIDField(
                required=False,
                allow_null=True,
                help_text=self.help_text,
            )
        if self.kind == "string":
            return serializers.CharField(
                required=False,
                allow_blank=self.allow_blank,
                help_text=self.help_text,
            )
        if self.kind == "bool":
            return serializers.BooleanField(required=False, help_text=self.help_text)
        if self.kind == "choice":
            return serializers.ChoiceField(
                required=False,
                choices=self.choices or (),
                help_text=self.help_text,
            )
        if self.kind == "int":
            return serializers.IntegerField(
                required=False,
                min_value=1,
                max_value=self.max_value,
                help_text=self.help_text,
            )
        raise ValueError(f"Unsupported query field kind: {self.kind}")

    def parse(self, value: str | None):
        if self.kind == "datetime":
            return _parse_datetime_value(value)
        if self.kind == "uuid":
            return _parse_uuid_value(value, field_name=self.name)
        if self.kind == "int":
            default = self.default if isinstance(self.default, int) else None
            return _parse_positive_int(
                value,
                field_name=self.name,
                default=default,
                max_value=self.max_value,
            )
        if self.kind == "bool":
            return str(value or "").lower() in {"1", "true", "yes", "on"}
        if self.kind == "choice":
            normalized = (value or "").lower()
            if normalized and self.choices and normalized not in self.choices:
                raise _invalid_query_param(f"{self.name} must be one of: {', '.join(self.choices)}")
            return normalized
        if self.kind == "string":
            if value is not None:
                return value
            return self.default if isinstance(self.default, str) else ""
        raise ValueError(f"Unsupported query field kind: {self.kind}")


@dataclass(frozen=True)
class QueryGroupSpec:
    """Shared schema/runtime definition for a query field group."""

    name: str
    specs: tuple[QueryFieldSpec, ...]
    description: str | None = None
    base: type[serializers.Serializer] = serializers.Serializer

    def build_serializer(self) -> type[serializers.Serializer]:
        return _build_query_schema_serializer(
            self.name,
            *self.specs,
            base=self.base,
            docstring=self.description,
        )

    def parse(self, request: Request) -> dict[str, object]:
        return _parse_query_group(
            request,
            *self.specs,
            serializer_name=f"{self.name}RuntimeSerializer",
        )


@dataclass(frozen=True)
class EndpointQuerySpec:
    """Declarative endpoint mapping to a shared query group."""

    endpoint: str
    group_key: str


def _page_size_spec(*, default: int, max_value: int) -> QueryFieldSpec:
    return QueryFieldSpec(
        name="page_size",
        kind="int",
        default=default,
        max_value=max_value,
        help_text=f"Results per page. Default {default}, maximum {max_value}.",
    )


def _query_spec_group(*specs: QueryFieldSpec) -> tuple[QueryFieldSpec, ...]:
    return specs


def _build_query_schema_serializer(
    name: str,
    *specs: QueryFieldSpec,
    base: type[serializers.Serializer] = serializers.Serializer,
    docstring: str | None = None,
) -> type[serializers.Serializer]:
    attrs = {spec.name: spec.schema_field() for spec in specs}
    if docstring:
        attrs["__doc__"] = docstring
    return cast(type[serializers.Serializer], type(name, (base,), attrs))


def _parse_query_group(
    request: Request,
    *specs: QueryFieldSpec,
    serializer_name: str,
) -> dict[str, object]:
    del serializer_name
    return {spec.name: spec.parse(request.query_params.get(spec.name)) for spec in specs}


def _parse_date_range_group(
    request: Request,
    *,
    start_spec: QueryFieldSpec,
    end_spec: QueryFieldSpec,
    serializer_name: str,
) -> tuple[datetime | None, datetime | None]:
    parsed = _parse_query_group(
        request,
        start_spec,
        end_spec,
        serializer_name=serializer_name,
    )
    start = cast(datetime | None, parsed[start_spec.name])
    end = cast(datetime | None, parsed[end_spec.name])
    if start and end and start > end:
        raise _invalid_query_param(
            f"{start_spec.name} must be earlier than or equal to {end_spec.name}"
        )
    return start, end


PAGE_SPEC = QueryFieldSpec(
    name="page",
    kind="int",
    default=1,
    help_text="Page number (1-based).",
)
EXECUTION_ID_SPEC = QueryFieldSpec(
    name="execution_id",
    kind="uuid",
    help_text="Filter by execution ID (UUID).",
)
SINCE_SPEC = QueryFieldSpec(
    name="since",
    kind="datetime",
    help_text="RFC3339 timestamp for incremental fetch.",
)
CYCLE_PAGE_SPEC = QueryFieldSpec(
    name="cycle_page",
    kind="int",
    default=1,
    help_text="Cycle list page number (1-based).",
)
CYCLE_PAGE_SIZE_SPEC = QueryFieldSpec(
    name="cycle_page_size",
    kind="int",
    default=50,
    max_value=200,
    help_text="Cycles per page. Default 50, maximum 200.",
)
CYCLE_SORT_SPEC = QueryFieldSpec(
    name="cycle_sort",
    kind="choice",
    default="asc",
    choices=("asc", "desc"),
    help_text=(
        "Cycle ordering by started_at. 'asc' for oldest first (default), 'desc' for newest."
    ),
)
CYCLE_STATUS_SPEC = QueryFieldSpec(
    name="cycle_status",
    kind="choice",
    default="all",
    choices=("all", "active", "completed", "pending"),
    help_text="Filter cycles by status.",
)
CYCLE_TRADE_ID_SPEC = QueryFieldSpec(
    name="trade_id",
    kind="string",
    allow_blank=True,
    help_text="Filter cycles containing a trade whose id starts with this value.",
)
LEVEL_SPEC = QueryFieldSpec(
    name="level",
    kind="string",
    allow_blank=True,
    help_text="Log level filter (comma-separated for multiple).",
)
COMPONENT_SPEC = QueryFieldSpec(
    name="component",
    kind="string",
    allow_blank=True,
    help_text="Logger/component name filter (comma-separated for multiple).",
)
MESSAGE_SPEC = QueryFieldSpec(
    name="message",
    kind="string",
    allow_blank=True,
    help_text="Log message text filter.",
)
MESSAGE_MATCH_SPEC = QueryFieldSpec(
    name="message_match",
    kind="choice",
    default="partial",
    choices=("partial", "exact", "regex"),
    help_text="Message filter match mode: partial, exact, or regex.",
)
POSITION_ID_SPEC = QueryFieldSpec(
    name="position_id",
    kind="string",
    allow_blank=True,
    help_text="Optional position ID prefix filter.",
)
TRADE_ID_SPEC = QueryFieldSpec(
    name="trade_id",
    kind="string",
    allow_blank=True,
    help_text="Optional trade ID prefix filter.",
)
TRADE_KIND_SPEC = QueryFieldSpec(
    name="trade_kind",
    kind="choice",
    default="all",
    choices=("all", "order", "close"),
    help_text="Filter trades by lifecycle kind: all, order, or close.",
)
ORDER_ID_SPEC = QueryFieldSpec(
    name="order_id",
    kind="string",
    allow_blank=True,
    help_text="Optional order ID prefix filter.",
)
ORDERING_SPEC = QueryFieldSpec(
    name="ordering",
    kind="string",
    default="",
    allow_blank=True,
    help_text="Sort field. Prefix with '-' for descending.",
)
TIMESTAMP_FROM_SPEC = QueryFieldSpec(
    name="timestamp_from",
    kind="datetime",
    help_text="Filter records from this RFC3339 timestamp (inclusive).",
)
TIMESTAMP_TO_SPEC = QueryFieldSpec(
    name="timestamp_to",
    kind="datetime",
    help_text="Filter records until this RFC3339 timestamp (inclusive).",
)
EVENT_TYPE_SPEC = QueryFieldSpec(
    name="event_type",
    kind="string",
    allow_blank=True,
    help_text="Event type filter.",
)
SEVERITY_SPEC = QueryFieldSpec(
    name="severity",
    kind="string",
    allow_blank=True,
    help_text="Severity filter.",
)
CATEGORY_SPEC = QueryFieldSpec(
    name="category",
    kind="string",
    allow_blank=True,
    help_text="Event category filter.",
)
INSTRUMENT_SPEC = QueryFieldSpec(
    name="instrument",
    kind="string",
    allow_blank=True,
    help_text="Instrument filter.",
)
DESCRIPTION_SPEC = QueryFieldSpec(
    name="message",
    kind="string",
    allow_blank=True,
    help_text="Event description text filter.",
)
SCOPE_SPEC = QueryFieldSpec(
    name="scope",
    kind="choice",
    choices=("all", "trading", "task"),
    help_text="Event scope filter.",
)
CREATED_FROM_SPEC = QueryFieldSpec(
    name="created_from",
    kind="datetime",
    help_text="Filter events created at or after this RFC3339 timestamp.",
)
CREATED_TO_SPEC = QueryFieldSpec(
    name="created_to",
    kind="datetime",
    help_text="Filter events created at or before this RFC3339 timestamp.",
)
DIRECTION_SPEC = QueryFieldSpec(
    name="direction",
    kind="string",
    allow_blank=True,
    help_text="Direction filter.",
)
POSITION_STATUS_SPEC = QueryFieldSpec(
    name="position_status",
    kind="choice",
    choices=("open", "closed"),
    help_text="Position status filter.",
)
INITIAL_POSITION_FILTER_SPEC = QueryFieldSpec(
    name="initial_position_filter",
    kind="choice",
    choices=("all", "initial", "normal"),
    help_text="Filter positions by initial-position seed marker.",
)
INCLUDE_TRADE_IDS_SPEC = QueryFieldSpec(
    name="include_trade_ids",
    kind="bool",
    help_text="Include position trade_ids in the response.",
)
RANGE_FROM_SPEC = QueryFieldSpec(
    name="range_from",
    kind="datetime",
    help_text="RFC3339 lower bound for the chart window.",
)
RANGE_TO_SPEC = QueryFieldSpec(
    name="range_to",
    kind="datetime",
    help_text="RFC3339 upper bound for the chart window.",
)
CYCLE_ID_SPEC = QueryFieldSpec(
    name="cycle_id",
    kind="uuid",
    help_text="Filter by cycle ID (UUID).",
)
ORDER_STATUS_SPEC = QueryFieldSpec(
    name="status",
    kind="string",
    allow_blank=True,
    help_text="Order status filter.",
)
ORDER_TYPE_SPEC = QueryFieldSpec(
    name="order_type",
    kind="string",
    allow_blank=True,
    help_text="Order type filter.",
)
INCLUDE_METRICS_SPEC = QueryFieldSpec(
    name="include_metrics",
    kind="bool",
    help_text="Include aggregate execution metrics.",
)
INCLUDE_TRADES_SPEC = QueryFieldSpec(
    name="include_trades",
    kind="bool",
    help_text=(
        "Include the full trade ledger in strategy cycle detail responses. "
        "Use the paginated trades endpoint for ordinary detail rendering."
    ),
)
ACTIVITY_PAGE_SIZE_SPEC = _page_size_spec(
    default=ActivityPagination.page_size,
    max_value=ActivityPagination.max_page_size,
)
TRADE_POSITION_PAGE_SIZE_SPEC = _page_size_spec(
    default=TradePositionPagination.page_size,
    max_value=TradePositionPagination.max_page_size,
)
TRADES_DIRECTION_SPEC = QueryFieldSpec(
    name="direction",
    kind="string",
    allow_blank=True,
    help_text="Direction filter (buy/sell/long/short).",
)
TRADES_ORDERING_SPEC = QueryFieldSpec(
    name="ordering",
    kind="string",
    default="-timestamp",
    allow_blank=True,
    help_text=(
        "Trade ordering field. Prefix with '-' for descending. "
        "Legacy values 'asc' and 'desc' are accepted for timestamp ordering."
    ),
)
TRADE_TIMESTAMP_FROM_SPEC = QueryFieldSpec(
    name="timestamp_from",
    kind="datetime",
    help_text="Filter trades executed at or after this RFC3339 timestamp.",
)
TRADE_TIMESTAMP_TO_SPEC = QueryFieldSpec(
    name="timestamp_to",
    kind="datetime",
    help_text="Filter trades executed at or before this RFC3339 timestamp.",
)
POSITIONS_RANGE_FROM_SPEC = QueryFieldSpec(
    name="range_from",
    kind="datetime",
    help_text="RFC3339 lower bound for positions overlapping a chart range.",
)
POSITIONS_RANGE_TO_SPEC = QueryFieldSpec(
    name="range_to",
    kind="datetime",
    help_text="RFC3339 upper bound for positions overlapping a chart range.",
)

ACTIVITY_PAGINATION_GROUP = _query_spec_group(PAGE_SPEC, ACTIVITY_PAGE_SIZE_SPEC)
TRADE_POSITION_PAGINATION_GROUP = _query_spec_group(
    PAGE_SPEC,
    TRADE_POSITION_PAGE_SIZE_SPEC,
)
EXECUTION_SCOPED_ACTIVITY_GROUP = _query_spec_group(
    EXECUTION_ID_SPEC,
    SINCE_SPEC,
    *ACTIVITY_PAGINATION_GROUP,
)
EXECUTION_SCOPED_TRADE_POSITION_GROUP = _query_spec_group(
    EXECUTION_ID_SPEC,
    SINCE_SPEC,
    *TRADE_POSITION_PAGINATION_GROUP,
)
DATE_RANGE_GROUP_SPECS = {
    "range": QueryGroupSpec(
        name="RangeDateWindowQueryGroup",
        specs=(RANGE_FROM_SPEC, RANGE_TO_SPEC),
    ),
    "timestamp": QueryGroupSpec(
        name="TimestampDateWindowQueryGroup",
        specs=(TIMESTAMP_FROM_SPEC, TIMESTAMP_TO_SPEC),
    ),
    "created": QueryGroupSpec(
        name="CreatedDateWindowQueryGroup",
        specs=(CREATED_FROM_SPEC, CREATED_TO_SPEC),
    ),
    "positions_range": QueryGroupSpec(
        name="PositionsRangeDateWindowQueryGroup",
        specs=(POSITIONS_RANGE_FROM_SPEC, POSITIONS_RANGE_TO_SPEC),
    ),
}


def _pagination_group(
    *,
    default_page_size: int,
    max_page_size: int,
    name: str = "PaginationRuntimeQueryGroup",
) -> QueryGroupSpec:
    return QueryGroupSpec(
        name=name,
        specs=_query_spec_group(
            PAGE_SPEC,
            _page_size_spec(default=default_page_size, max_value=max_page_size),
        ),
    )


def _execution_scoped_group(
    *,
    default_page_size: int,
    max_page_size: int,
    name: str = "ExecutionScopedRuntimeQueryGroup",
) -> QueryGroupSpec:
    pagination_group = _pagination_group(
        default_page_size=default_page_size,
        max_page_size=max_page_size,
        name=f"{name}Pagination",
    )
    return QueryGroupSpec(
        name=name,
        specs=_query_spec_group(
            EXECUTION_ID_SPEC,
            SINCE_SPEC,
            *pagination_group.specs,
        ),
    )


def _invalid_query_param(detail: str) -> ValidationError:
    return ValidationError({"code": "invalid_query_param", "detail": detail})


def _extract_validation_detail(errors: Any) -> str:
    if isinstance(errors, dict):
        for _, value in errors.items():
            nested = _extract_validation_detail(value)
            if nested:
                return nested
    elif isinstance(errors, list) and errors:
        return _extract_validation_detail(errors[0])
    elif errors:
        return str(errors)
    return "Invalid query parameters"


class QueryParamsSerializer(serializers.Serializer):
    """Base serializer for strict query validation."""

    default_error_messages = {
        "invalid_query_param": "Invalid query parameters",
    }

    @classmethod
    def parse_query_params(cls, request: Request, **kwargs):
        serializer = cls(data=request.query_params, **kwargs)
        if not serializer.is_valid():
            raise _invalid_query_param(_extract_validation_detail(serializer.errors))
        return serializer


QUERY_GROUP_SPECS = {
    "execution_scoped": QueryGroupSpec(
        name="ExecutionScopedQueryParamsSchemaSerializer",
        specs=EXECUTION_SCOPED_ACTIVITY_GROUP,
        description="OpenAPI serializer for execution-scoped task query parameters.",
    ),
    "logs": QueryGroupSpec(
        name="LogsQueryParamsSchemaSerializer",
        specs=(
            *EXECUTION_SCOPED_ACTIVITY_GROUP,
            LEVEL_SPEC,
            COMPONENT_SPEC,
            MESSAGE_SPEC,
            MESSAGE_MATCH_SPEC,
            POSITION_ID_SPEC,
            TIMESTAMP_FROM_SPEC,
            TIMESTAMP_TO_SPEC,
            ORDERING_SPEC,
        ),
        description="OpenAPI serializer for logs query parameters.",
    ),
    "log_components": QueryGroupSpec(
        name="LogComponentsQueryParamsSchemaSerializer",
        specs=(EXECUTION_ID_SPEC,),
        description="OpenAPI serializer for log component query parameters.",
        base=QueryParamsSerializer,
    ),
    "events": QueryGroupSpec(
        name="EventsQueryParamsSchemaSerializer",
        specs=(
            *EXECUTION_SCOPED_ACTIVITY_GROUP,
            EVENT_TYPE_SPEC,
            SEVERITY_SPEC,
            SCOPE_SPEC,
            CREATED_FROM_SPEC,
            CREATED_TO_SPEC,
            ORDERING_SPEC,
        ),
        description="OpenAPI serializer for task events query parameters.",
    ),
    "market_events": QueryGroupSpec(
        name="MarketEventsQueryParamsSchemaSerializer",
        specs=(
            *EXECUTION_SCOPED_ACTIVITY_GROUP,
            EVENT_TYPE_SPEC,
            SEVERITY_SPEC,
            CATEGORY_SPEC,
            INSTRUMENT_SPEC,
            DESCRIPTION_SPEC,
            CREATED_FROM_SPEC,
            CREATED_TO_SPEC,
            ORDERING_SPEC,
        ),
        description="OpenAPI serializer for task market event query parameters.",
    ),
    "strategy_events": QueryGroupSpec(
        name="StrategyEventsQueryParamsSchemaSerializer",
        specs=(
            EXECUTION_ID_SPEC,
            CYCLE_ID_SPEC,
            CYCLE_PAGE_SPEC,
            CYCLE_PAGE_SIZE_SPEC,
            CYCLE_SORT_SPEC,
            CYCLE_STATUS_SPEC,
            POSITION_ID_SPEC,
            CYCLE_TRADE_ID_SPEC,
            INCLUDE_TRADES_SPEC,
        ),
        description="OpenAPI serializer for strategy event visualization parameters.",
        base=QueryParamsSerializer,
    ),
    "trades": QueryGroupSpec(
        name="TradesQueryParamsSchemaSerializer",
        specs=(
            *EXECUTION_SCOPED_TRADE_POSITION_GROUP,
            CYCLE_ID_SPEC,
            TRADES_DIRECTION_SPEC,
            TRADES_ORDERING_SPEC,
            TRADE_TIMESTAMP_FROM_SPEC,
            TRADE_TIMESTAMP_TO_SPEC,
            TRADE_ID_SPEC,
            TRADE_KIND_SPEC,
        ),
        description="OpenAPI serializer for trades query parameters.",
    ),
    "positions": QueryGroupSpec(
        name="PositionsQueryParamsSchemaSerializer",
        specs=(
            *EXECUTION_SCOPED_TRADE_POSITION_GROUP,
            CYCLE_ID_SPEC,
            POSITION_STATUS_SPEC,
            INITIAL_POSITION_FILTER_SPEC,
            DIRECTION_SPEC,
            INCLUDE_TRADE_IDS_SPEC,
            POSITIONS_RANGE_FROM_SPEC,
            POSITIONS_RANGE_TO_SPEC,
            POSITION_ID_SPEC,
            ORDERING_SPEC,
        ),
        description="OpenAPI serializer for positions query parameters.",
    ),
    "position_lifecycle": QueryGroupSpec(
        name="PositionLifecycleQueryParamsSchemaSerializer",
        specs=(EXECUTION_ID_SPEC, POSITION_ID_SPEC),
        description="OpenAPI serializer for position lifecycle query parameters.",
        base=QueryParamsSerializer,
    ),
    "orders": QueryGroupSpec(
        name="OrdersQueryParamsSchemaSerializer",
        specs=(
            *EXECUTION_SCOPED_TRADE_POSITION_GROUP,
            ORDER_STATUS_SPEC,
            ORDER_TYPE_SPEC,
            DIRECTION_SPEC,
            ORDER_ID_SPEC,
            TIMESTAMP_FROM_SPEC,
            TIMESTAMP_TO_SPEC,
            ORDERING_SPEC,
        ),
        description="OpenAPI serializer for orders query parameters.",
    ),
    "summary": QueryGroupSpec(
        name="SummaryQueryParamsSchemaSerializer",
        specs=(EXECUTION_ID_SPEC,),
        description="OpenAPI serializer for summary query parameters.",
        base=QueryParamsSerializer,
    ),
    "executions": QueryGroupSpec(
        name="ExecutionsQueryParamsSchemaSerializer",
        specs=(*ACTIVITY_PAGINATION_GROUP, INCLUDE_METRICS_SPEC),
        description="OpenAPI serializer for execution list query parameters.",
    ),
    "execution_detail": QueryGroupSpec(
        name="ExecutionDetailQueryParamsSchemaSerializer",
        specs=(INCLUDE_METRICS_SPEC,),
        description="OpenAPI serializer for execution detail query parameters.",
        base=QueryParamsSerializer,
    ),
    "pagination": QueryGroupSpec(
        name="PaginationSchemaSerializer",
        specs=ACTIVITY_PAGINATION_GROUP,
        description="OpenAPI serializer for plain pagination parameters.",
    ),
}

ENDPOINT_QUERY_SPECS = {
    endpoint: EndpointQuerySpec(endpoint=endpoint, group_key=endpoint)
    for endpoint in (
        "execution_scoped",
        "logs",
        "log_components",
        "events",
        "market_events",
        "strategy_events",
        "trades",
        "positions",
        "position_lifecycle",
        "orders",
        "summary",
        "executions",
        "execution_detail",
        "pagination",
    )
}


def get_query_group_spec(endpoint: str) -> QueryGroupSpec:
    return QUERY_GROUP_SPECS[ENDPOINT_QUERY_SPECS[endpoint].group_key]


def _build_query_serializer_alias(endpoint: str) -> type[serializers.Serializer]:
    return get_query_group_spec(endpoint).build_serializer()


def _parse_endpoint_group(endpoint: str, request: Request) -> dict[str, object]:
    return get_query_group_spec(endpoint).parse(request)


def _resolve_date_range_group(
    start_key: str,
    end_key: str,
    group_name: str | None = None,
) -> QueryGroupSpec:
    if group_name is not None:
        return DATE_RANGE_GROUP_SPECS[group_name]

    key_map = {
        ("range_from", "range_to"): "range",
        ("timestamp_from", "timestamp_to"): "timestamp",
        ("created_from", "created_to"): "created",
    }
    group_key = key_map.get((start_key, end_key))
    if group_key is not None:
        return DATE_RANGE_GROUP_SPECS[group_key]

    return QueryGroupSpec(
        name=f"{start_key.title()}{end_key.title()}DateWindowQueryGroup",
        specs=(
            QueryFieldSpec(
                name=start_key,
                kind="datetime",
                help_text=f"RFC3339 lower bound for {start_key}.",
            ),
            QueryFieldSpec(
                name=end_key,
                kind="datetime",
                help_text=f"RFC3339 upper bound for {end_key}.",
            ),
        ),
    )


def _build_execution_scoped_query(
    request: Request,
    *,
    default_execution_id: UUID | None,
    default_page_size: int,
    max_page_size: int,
) -> ExecutionScopedQuery:
    return ExecutionScopedQuery.from_request(
        request,
        default_execution_id=default_execution_id,
        default_page_size=default_page_size,
        max_page_size=max_page_size,
    )


def _build_date_range_query(
    request: Request,
    *,
    start_key: str,
    end_key: str,
    group_name: str | None = None,
) -> DateRangeQuery:
    return DateRangeQuery.from_request(
        request,
        start_key=start_key,
        end_key=end_key,
        group_name=group_name,
    )


def _parse_datetime_value(value: str | None) -> datetime | None:
    if value:
        parsed = parse_datetime(value)
        if parsed is None:
            raise _invalid_query_param(f"Invalid datetime value: {value}")
        return parsed
    return None


def _parse_positive_int(
    value: str | None,
    *,
    field_name: str,
    default: int | None,
    max_value: int | None = None,
) -> int | None:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid_query_param(f"Invalid {field_name} parameter") from exc
    if parsed < 1:
        raise _invalid_query_param(f"{field_name} must be greater than 0")
    if max_value is not None and parsed > max_value:
        raise _invalid_query_param(f"{field_name} exceeds maximum allowed value of {max_value}")
    return parsed


def _parse_uuid_value(value: str | None, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise _invalid_query_param(f"Invalid {field_name}: {value}") from exc


def _parse_execution_id_value(value: str | None) -> UUID | None:
    return _parse_uuid_value(value, field_name="execution_id")


ExecutionScopedQueryParamsSchemaSerializer = _build_query_serializer_alias("execution_scoped")
LogsQueryParamsSchemaSerializer = _build_query_serializer_alias("logs")
LogComponentsQueryParamsSchemaSerializer = _build_query_serializer_alias("log_components")
EventsQueryParamsSchemaSerializer = _build_query_serializer_alias("events")
MarketEventsQueryParamsSchemaSerializer = _build_query_serializer_alias("market_events")
StrategyEventsQueryParamsSchemaSerializer = _build_query_serializer_alias("strategy_events")
TradesQueryParamsSchemaSerializer = _build_query_serializer_alias("trades")
PositionsQueryParamsSchemaSerializer = _build_query_serializer_alias("positions")
PositionLifecycleQueryParamsSchemaSerializer = _build_query_serializer_alias("position_lifecycle")
OrdersQueryParamsSchemaSerializer = _build_query_serializer_alias("orders")
SummaryQueryParamsSchemaSerializer = _build_query_serializer_alias("summary")
ExecutionsQueryParamsSchemaSerializer = _build_query_serializer_alias("executions")
ExecutionDetailQueryParamsSchemaSerializer = _build_query_serializer_alias("execution_detail")
PaginationSchemaSerializer = _build_query_serializer_alias("pagination")


@dataclass(frozen=True)
class PaginationParams:
    page: int
    page_size: int

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_page_size: int = 100,
        max_page_size: int = 1000,
    ) -> PaginationParams:
        pagination_group = _pagination_group(
            default_page_size=default_page_size,
            max_page_size=max_page_size,
        )
        parsed = pagination_group.parse(request)
        return cls(
            page=cast(int, parsed["page"]),
            page_size=cast(int, parsed["page_size"]),
        )


@dataclass(frozen=True)
class ExecutionScopedQuery:
    execution_id: UUID | None
    since: datetime | None
    pagination: PaginationParams

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
        default_page_size: int = 100,
        max_page_size: int = 1000,
    ) -> ExecutionScopedQuery:
        execution_group = _execution_scoped_group(
            default_page_size=default_page_size,
            max_page_size=max_page_size,
        )
        parsed = execution_group.parse(request)
        return cls(
            execution_id=cast(UUID | None, parsed["execution_id"]) or default_execution_id,
            since=cast(datetime | None, parsed["since"]),
            pagination=PaginationParams(
                page=cast(int, parsed["page"]),
                page_size=cast(int, parsed["page_size"]),
            ),
        )


@dataclass(frozen=True)
class DateRangeQuery:
    start: datetime | None
    end: datetime | None

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        start_key: str,
        end_key: str,
        group_name: str | None = None,
    ) -> DateRangeQuery:
        range_group = _resolve_date_range_group(start_key, end_key, group_name)
        start_spec, end_spec = range_group.specs
        start, end = _parse_date_range_group(
            request,
            start_spec=start_spec,
            end_spec=end_spec,
            serializer_name=f"{range_group.name}RuntimeSerializer",
        )
        return cls(start=start, end=end)


@dataclass(frozen=True)
class PositionQuery:
    execution: ExecutionScopedQuery
    cycle_id: UUID | None
    position_status: str
    initial_position_filter: str
    direction: str
    include_trade_ids: bool
    range: DateRangeQuery
    position_id: str
    ordering: str

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
        default_page_size: int = 100,
        max_page_size: int = 1000,
    ) -> PositionQuery:
        parsed = _parse_endpoint_group("positions", request)
        return cls(
            execution=_build_execution_scoped_query(
                request,
                default_execution_id=default_execution_id,
                default_page_size=default_page_size,
                max_page_size=max_page_size,
            ),
            cycle_id=cast(UUID | None, parsed["cycle_id"]),
            position_status=cast(str, parsed["position_status"]),
            initial_position_filter=cast(str, parsed["initial_position_filter"]),
            direction=cast(str, parsed["direction"]),
            include_trade_ids=cast(bool, parsed["include_trade_ids"]),
            range=_build_date_range_query(
                request,
                start_key="range_from",
                end_key="range_to",
                group_name="positions_range",
            ),
            position_id=cast(str, parsed["position_id"]).strip(),
            ordering=cast(str, parsed["ordering"]),
        )


@dataclass(frozen=True)
class PositionLifecycleQueryParams:
    execution_id: UUID | None
    position_id: str

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
    ) -> PositionLifecycleQueryParams:
        parsed = _parse_endpoint_group("position_lifecycle", request)
        position_id = cast(str, parsed["position_id"]).strip()
        if not position_id:
            raise _invalid_query_param("position_id is required")
        return cls(
            execution_id=cast(UUID | None, parsed["execution_id"]) or default_execution_id,
            position_id=position_id,
        )


@dataclass(frozen=True)
class LogsQueryParams:
    execution: ExecutionScopedQuery
    levels: list[str]
    components: list[str]
    message: str
    message_match: str
    position_id: str
    timestamp_range: DateRangeQuery
    ordering: str

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
        default_page_size: int,
        max_page_size: int,
    ) -> LogsQueryParams:
        parsed = _parse_endpoint_group("logs", request)
        level_param = cast(str, parsed["level"]) or request.query_params.get("levels", "")
        component_param = cast(str, parsed["component"]) or request.query_params.get(
            "components", ""
        )
        message = cast(str, parsed["message"])
        message_match = cast(str, parsed["message_match"]) or "partial"
        if message and message_match == "regex":
            try:
                re.compile(message)
            except re.error as exc:
                logger.warning("Invalid message regex rejected: %s", exc)
                raise _invalid_query_param("Invalid message regex pattern") from exc
        return cls(
            execution=_build_execution_scoped_query(
                request,
                default_execution_id=default_execution_id,
                default_page_size=default_page_size,
                max_page_size=max_page_size,
            ),
            levels=[v.strip().upper() for v in level_param.split(",") if v.strip()],
            components=[v.strip() for v in component_param.split(",") if v.strip()],
            message=message,
            message_match=message_match,
            position_id=cast(str, parsed["position_id"]),
            timestamp_range=_build_date_range_query(
                request,
                start_key="timestamp_from",
                end_key="timestamp_to",
                group_name="timestamp",
            ),
            ordering=cast(str, parsed["ordering"]),
        )


@dataclass(frozen=True)
class EventsQueryParams:
    execution: ExecutionScopedQuery
    event_type: str
    severity: str
    scope: str
    created_range: DateRangeQuery
    ordering: str

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
        default_page_size: int = 100,
        max_page_size: int = 1000,
    ) -> EventsQueryParams:
        parsed = _parse_endpoint_group("events", request)
        scope = cast(str, parsed["scope"]) or "all"
        return cls(
            execution=_build_execution_scoped_query(
                request,
                default_execution_id=default_execution_id,
                default_page_size=default_page_size,
                max_page_size=max_page_size,
            ),
            event_type=cast(str, parsed["event_type"]),
            severity=cast(str, parsed["severity"]),
            scope=scope,
            created_range=_build_date_range_query(
                request,
                start_key="created_from",
                end_key="created_to",
                group_name="created",
            ),
            ordering=cast(str, parsed["ordering"]),
        )


@dataclass(frozen=True)
class MarketEventsQueryParams:
    execution: ExecutionScopedQuery
    event_type: str
    severities: list[str]
    categories: list[str]
    instrument: str
    message: str
    created_range: DateRangeQuery
    ordering: str

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
        default_page_size: int = 100,
        max_page_size: int = 1000,
    ) -> MarketEventsQueryParams:
        parsed = _parse_endpoint_group("market_events", request)
        severity_param = cast(str, parsed["severity"])
        category_param = cast(str, parsed["category"])
        return cls(
            execution=_build_execution_scoped_query(
                request,
                default_execution_id=default_execution_id,
                default_page_size=default_page_size,
                max_page_size=max_page_size,
            ),
            event_type=cast(str, parsed["event_type"]).strip(),
            severities=[v.strip() for v in severity_param.split(",") if v.strip()],
            categories=[v.strip() for v in category_param.split(",") if v.strip()],
            instrument=cast(str, parsed["instrument"]).strip(),
            message=cast(str, parsed["message"]).strip(),
            created_range=_build_date_range_query(
                request,
                start_key="created_from",
                end_key="created_to",
                group_name="created",
            ),
            ordering=cast(str, parsed["ordering"]),
        )


@dataclass(frozen=True)
class TradesQueryParams:
    execution: ExecutionScopedQuery
    cycle_id: UUID | None
    direction: str
    ordering: str
    timestamp_range: DateRangeQuery
    trade_id: str
    trade_kind: str

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
        default_page_size: int = 100,
        max_page_size: int = 1000,
    ) -> TradesQueryParams:
        parsed = _parse_endpoint_group("trades", request)
        return cls(
            execution=_build_execution_scoped_query(
                request,
                default_execution_id=default_execution_id,
                default_page_size=default_page_size,
                max_page_size=max_page_size,
            ),
            cycle_id=cast(UUID | None, parsed["cycle_id"]),
            direction=cast(str, parsed["direction"]),
            ordering=cast(str, parsed["ordering"]) or "-timestamp",
            timestamp_range=_build_date_range_query(
                request,
                start_key="timestamp_from",
                end_key="timestamp_to",
                group_name="timestamp",
            ),
            trade_id=cast(str, parsed["trade_id"]).strip(),
            trade_kind=cast(str, parsed["trade_kind"]) or "all",
        )


@dataclass(frozen=True)
class OrdersQueryParams:
    execution: ExecutionScopedQuery
    status: str
    order_type: str
    direction: str
    order_id: str
    timestamp_range: DateRangeQuery
    ordering: str

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
        default_page_size: int = 100,
        max_page_size: int = 1000,
    ) -> OrdersQueryParams:
        parsed = _parse_endpoint_group("orders", request)
        return cls(
            execution=_build_execution_scoped_query(
                request,
                default_execution_id=default_execution_id,
                default_page_size=default_page_size,
                max_page_size=max_page_size,
            ),
            status=cast(str, parsed["status"]),
            order_type=cast(str, parsed["order_type"]),
            direction=cast(str, parsed["direction"]),
            order_id=cast(str, parsed["order_id"]).strip(),
            timestamp_range=_build_date_range_query(
                request,
                start_key="timestamp_from",
                end_key="timestamp_to",
                group_name="timestamp",
            ),
            ordering=cast(str, parsed["ordering"]),
        )


@dataclass(frozen=True)
class LogComponentsQueryParams:
    execution_id: UUID | None

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
    ) -> LogComponentsQueryParams:
        parsed = _parse_endpoint_group("log_components", request)
        return cls(
            execution_id=cast(UUID | None, parsed["execution_id"]) or default_execution_id,
        )


@dataclass(frozen=True)
class StrategyEventsQueryParams:
    execution_id: UUID | None
    cycle_id: UUID | None
    cycle_page: int
    cycle_page_size: int
    cycle_sort: str
    cycle_status: str
    position_id: str
    trade_id: str
    include_trades: bool

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
    ) -> StrategyEventsQueryParams:
        parsed = _parse_endpoint_group("strategy_events", request)
        return cls(
            execution_id=cast(UUID | None, parsed["execution_id"]) or default_execution_id,
            cycle_id=cast(UUID | None, parsed["cycle_id"]),
            cycle_page=cast(int, parsed["cycle_page"]),
            cycle_page_size=cast(int, parsed["cycle_page_size"]),
            cycle_sort=cast(str, parsed["cycle_sort"]) or "asc",
            cycle_status=cast(str, parsed["cycle_status"]) or "all",
            position_id=cast(str, parsed["position_id"] or "").strip(),
            trade_id=cast(str, parsed["trade_id"] or "").strip(),
            include_trades=cast(bool, parsed["include_trades"]),
        )


@dataclass(frozen=True)
class SummaryQueryParams:
    execution_id: UUID | None

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_execution_id: UUID | None,
    ) -> SummaryQueryParams:
        parsed = _parse_endpoint_group("summary", request)
        return cls(
            execution_id=cast(UUID | None, parsed["execution_id"]) or default_execution_id,
        )


@dataclass(frozen=True)
class ExecutionsQueryParams:
    pagination: PaginationParams
    include_metrics: bool

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        default_page_size: int,
        max_page_size: int,
    ) -> ExecutionsQueryParams:
        parsed = _parse_endpoint_group("executions", request)
        pagination = PaginationParams.from_request(
            request,
            default_page_size=default_page_size,
            max_page_size=max_page_size,
        )
        return cls(
            pagination=pagination,
            include_metrics=cast(bool, parsed["include_metrics"]),
        )


@dataclass(frozen=True)
class ExecutionDetailQueryParams:
    include_metrics: bool

    @classmethod
    def from_request(cls, request: Request) -> ExecutionDetailQueryParams:
        parsed = _parse_endpoint_group("execution_detail", request)
        return cls(include_metrics=cast(bool, parsed["include_metrics"]))
