"""Trading task API views."""

import logging
from logging import Logger
from typing import Any

from django.db import IntegrityError
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response

from apps.trading.models import TradingTask
from apps.trading.serializers.task import MarketEventSerializer
from apps.trading.serializers.trading import (
    TradingTaskCreateSerializer,
    TradingTaskListSerializer,
    TradingTaskSerializer,
)
from apps.trading.services.task_activity import TaskActivityQueryService
from apps.trading.views.task_base import (
    TASK_LIST_PARAMETERS,
    TaskViewSetBase,
    task_stop_response_fields,
)
from apps.trading.views.pagination import ActivityPagination
from apps.trading.views.query_params import MarketEventsQueryParamsSchemaSerializer
from apps.trading.views.throttles import TaskDataRateThrottle

logger: Logger = logging.getLogger(name=__name__)


def _integrity_constraint_id(exc: IntegrityError) -> str:
    """Extract the constraint name from an IntegrityError without leaking internals.

    Checks the psycopg2 diagnostic first, then falls back to the first
    exception arg (which Django uses to wrap the constraint name).
    The return value is only used for ``in`` checks — never sent to clients.
    """
    pg_diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    name = getattr(pg_diag, "constraint_name", None)
    if name:
        return name
    return str(exc.args[0]) if exc.args else ""


class ConflictError(APIException):
    """API exception for known business conflicts."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


@extend_schema_view(
    list=extend_schema(
        tags=["Trading"],
        parameters=[
            *TASK_LIST_PARAMETERS,
            OpenApiParameter(name="account_id", type=str, required=False),
        ],
    ),
    create=extend_schema(tags=["Trading"], responses={201: TradingTaskSerializer}),
    retrieve=extend_schema(tags=["Trading"], responses={200: TradingTaskSerializer}),
    update=extend_schema(tags=["Trading"], responses={200: TradingTaskSerializer}),
    partial_update=extend_schema(tags=["Trading"], responses={200: TradingTaskSerializer}),
    destroy=extend_schema(tags=["Trading"]),
    start=extend_schema(
        operation_id="trading_tasks_start",
        tags=["Trading"],
        responses={200: TradingTaskSerializer},
    ),
    stop=extend_schema(
        operation_id="trading_tasks_stop",
        tags=["Trading"],
        request=inline_serializer(
            "TradingTaskStopCommand",
            fields={
                "mode": serializers.CharField(
                    required=False,
                    default="graceful",
                    help_text="Stop mode. Defaults to graceful.",
                ),
                "drain_duration_minutes": serializers.IntegerField(
                    required=False,
                    min_value=1,
                    help_text="Optional drain duration override in minutes.",
                ),
            },
        ),
        responses={
            202: inline_serializer(
                "TradingTaskStopResponse",
                fields=task_stop_response_fields({"mode": serializers.CharField()}),
            ),
        },
    ),
    pause=extend_schema(
        operation_id="trading_tasks_pause",
        tags=["Trading"],
        responses={200: TradingTaskSerializer},
    ),
    resume=extend_schema(
        operation_id="trading_tasks_resume",
        tags=["Trading"],
        responses={200: TradingTaskSerializer},
    ),
    restart=extend_schema(
        operation_id="trading_tasks_restart",
        tags=["Trading"],
        responses={200: TradingTaskSerializer},
    ),
    executions=extend_schema(
        operation_id="trading_task_execution_history",
        tags=["Trading"],
    ),
    execution_detail=extend_schema(
        operation_id="trading_task_execution_detail",
        tags=["Trading"],
    ),
    copy=extend_schema(
        operation_id="trading_tasks_copy",
        tags=["Trading"],
        responses={201: TradingTaskSerializer},
    ),
)
@extend_schema(tags=["Trading"])
class TradingTaskViewSet(TaskViewSetBase):
    """ViewSet for TradingTask operations with task-centric API."""

    queryset = TradingTask.objects.none()
    serializer_class = TradingTaskSerializer
    detail_serializer_class = TradingTaskSerializer
    list_serializer_class = TradingTaskListSerializer
    create_serializer_class = TradingTaskCreateSerializer
    task_model_name = "TradingTask"
    lookup_field = "pk"
    task_type_label = "trading"
    select_related_fields = ("config", "user", "oanda_account")
    filter_field_map = {
        "status": "status",
        "config_id": "config_id",
        "account_id": "oanda_account_id",
    }

    def perform_create(self, serializer: TradingTaskCreateSerializer) -> None:
        """Set the user when creating a task."""
        try:
            serializer.save(user=self.request.user)
        except IntegrityError as exc:
            logger.error("IntegrityError creating trading task: %s", exc)
            exc_text = _integrity_constraint_id(exc)
            if "unique_user_trading_task_name" in exc_text:
                raise ConflictError(
                    {"name": ["A trading task with this name already exists."]}
                ) from exc
            if "uniq_active_trading_task_per_account" in exc_text:
                raise ConflictError(
                    {"account_id": ["This account already has an active trading task."]}
                ) from exc
            raise

    def get_stop_mode(self, request: Request) -> str:
        """Trading tasks support a configurable stop mode."""
        return request.data.get("mode", "graceful")

    def get_drain_duration_minutes(self, request: Request) -> int | None:
        """Optional per-stop drain duration override (minutes).

        Ignored unless the effective stop mode is ``drain``; a non-positive
        or non-integer value is treated as "no override".
        """
        raw = request.data.get("drain_duration_minutes")
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def get_stop_response_extras(self, request: Request) -> dict[str, Any]:
        """Include the stop mode in the response."""
        return {"mode": self.get_stop_mode(request)}

    @extend_schema(
        tags=["Trading"],
        parameters=[MarketEventsQueryParamsSchemaSerializer],
        responses={
            200: inline_serializer(
                "TaskMarketEventPaginatedResponse",
                fields={
                    "count": serializers.IntegerField(),
                    "next": serializers.CharField(allow_null=True),
                    "previous": serializers.CharField(allow_null=True),
                    "results": MarketEventSerializer(many=True),
                },
            )
        },
        description="Retrieve paginated market events associated with this trading task.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="market-events",
        throttle_classes=[TaskDataRateThrottle],
    )
    def market_events(self, request: Request, pk: str | None = None) -> Response:
        """Return market events explicitly linked to this trading task."""
        task = self.get_object()
        queryset = TaskActivityQueryService().market_events_queryset(
            request=request,
            task=task,
            task_type_label=self.task_type_label,
        )
        paginator = ActivityPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = MarketEventSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
