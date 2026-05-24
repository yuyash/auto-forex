"""Strategy data endpoints shared by task viewsets."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.trading.views.throttles import TaskDataRateThrottle


class TaskStrategyDataMixin:
    """Mixin providing strategy snapshot, history, and metric endpoints."""

    task_type_label: str

    @extend_schema(
        tags=["Trading"],
        parameters=[
            OpenApiParameter("execution_id", str, required=False),
        ],
        responses={
            200: inline_serializer(
                "TaskStrategySnapshotResponse",
                fields={
                    "execution_id": serializers.CharField(allow_null=True),
                    "strategy_type": serializers.CharField(),
                    "instrument": serializers.CharField(allow_null=True),
                    "timestamp": serializers.CharField(allow_null=True),
                    "snapshot": serializers.JSONField(),
                },
            )
        },
        description="Retrieve the current strategy snapshot for a task execution.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="strategy/snapshot",
        throttle_classes=[TaskDataRateThrottle],
    )
    def strategy_snapshot(self, request: Request, pk: int | None = None) -> Response:
        from apps.trading.services.strategy_data import StrategyDataService

        task = self.get_object()  # type: ignore[attr-defined]
        return Response(
            StrategyDataService().snapshot(
                request=request,
                task=task,
                task_type_label=self.task_type_label,
            )
        )

    @extend_schema(
        tags=["Trading"],
        parameters=[
            OpenApiParameter("execution_id", str, required=False),
            OpenApiParameter("since", str, required=False),
            OpenApiParameter("until", str, required=False),
            OpenApiParameter("page", int, required=False),
            OpenApiParameter("page_size", int, required=False),
            OpenApiParameter("ordering", str, required=False),
            OpenApiParameter("granularity", str, required=False),
            OpenApiParameter("category", str, required=False),
        ],
        responses={
            200: inline_serializer(
                "TaskStrategyHistoryResponse",
                fields={
                    "execution_id": serializers.CharField(allow_null=True),
                    "strategy_type": serializers.CharField(),
                    "instrument": serializers.CharField(allow_null=True),
                    "count": serializers.IntegerField(),
                    "count_is_exact": serializers.BooleanField(required=False),
                    "next": serializers.CharField(allow_null=True),
                    "previous": serializers.CharField(allow_null=True),
                    "results": serializers.ListField(child=serializers.JSONField()),
                },
            )
        },
        description="Retrieve paginated strategy calculations, actions, and operation history.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="strategy/history",
        throttle_classes=[TaskDataRateThrottle],
    )
    def strategy_history(self, request: Request, pk: int | None = None) -> Response:
        from apps.trading.services.strategy_data import StrategyDataService

        task = self.get_object()  # type: ignore[attr-defined]
        return Response(
            StrategyDataService().history(
                request=request,
                task=task,
                task_type_label=self.task_type_label,
            )
        )

    @extend_schema(
        tags=["Trading"],
        parameters=[
            OpenApiParameter("execution_id", str, required=False),
            OpenApiParameter("since", str, required=False),
            OpenApiParameter("until", str, required=False),
            OpenApiParameter("page", int, required=False),
            OpenApiParameter("page_size", int, required=False),
            OpenApiParameter("ordering", str, required=False),
            OpenApiParameter("granularity", str, required=False),
            OpenApiParameter("metric_keys", str, required=False),
        ],
        responses={
            200: inline_serializer(
                "TaskStrategyMetricsResponse",
                fields={
                    "execution_id": serializers.CharField(allow_null=True),
                    "strategy_type": serializers.CharField(),
                    "instrument": serializers.CharField(allow_null=True),
                    "data_source": serializers.CharField(),
                    "resume_cursor_timestamp": serializers.CharField(allow_null=True),
                    "consistency_warnings": serializers.ListField(
                        child=serializers.JSONField(), required=False
                    ),
                    "ohlc_layers": serializers.JSONField(),
                    "count": serializers.IntegerField(),
                    "next": serializers.CharField(allow_null=True),
                    "previous": serializers.CharField(allow_null=True),
                    "results": serializers.ListField(child=serializers.JSONField()),
                },
            )
        },
        description="Retrieve paginated strategy metrics aligned to OHLC chart granularity.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="strategy/metrics",
        throttle_classes=[TaskDataRateThrottle],
    )
    def strategy_metrics(self, request: Request, pk: int | None = None) -> Response:
        from apps.trading.services.strategy_data import StrategyDataService

        task = self.get_object()  # type: ignore[attr-defined]
        return Response(
            StrategyDataService().metrics(
                request=request,
                task=task,
                task_type_label=self.task_type_label,
            )
        )

    @extend_schema(
        tags=["Trading"],
        parameters=[
            OpenApiParameter("execution_id", str, required=False),
            OpenApiParameter("metric_keys", str, required=False),
        ],
        responses={
            200: inline_serializer(
                "TaskStrategyLatestMetricResponse",
                fields={
                    "execution_id": serializers.CharField(allow_null=True),
                    "strategy_type": serializers.CharField(),
                    "instrument": serializers.CharField(allow_null=True),
                    "data_source": serializers.CharField(),
                    "resume_cursor_timestamp": serializers.CharField(allow_null=True),
                    "consistency_warnings": serializers.ListField(
                        child=serializers.JSONField(), required=False
                    ),
                    "result": serializers.JSONField(allow_null=True),
                },
            )
        },
        description="Retrieve the latest strategy metric snapshot without full pagination counts.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="strategy/metrics/latest",
        throttle_classes=[TaskDataRateThrottle],
    )
    def strategy_metrics_latest(self, request: Request, pk: int | None = None) -> Response:
        from apps.trading.services.strategy_data import StrategyDataService

        task = self.get_object()  # type: ignore[attr-defined]
        return Response(
            StrategyDataService().latest_metric(
                request=request,
                task=task,
                task_type_label=self.task_type_label,
            )
        )

    @extend_schema(
        tags=["Trading"],
        parameters=[
            OpenApiParameter("execution_id", str, required=False),
            OpenApiParameter("since", str, required=False),
            OpenApiParameter("until", str, required=False),
            OpenApiParameter("timezone", str, required=False),
        ],
        responses={
            200: inline_serializer(
                "TaskStrategyPeriodicMetricsResponse",
                fields={
                    "execution_id": serializers.CharField(allow_null=True),
                    "strategy_type": serializers.CharField(),
                    "instrument": serializers.CharField(allow_null=True),
                    "currency": serializers.CharField(allow_null=True),
                    "timezone": serializers.CharField(),
                    "periods": serializers.JSONField(),
                    "returns": serializers.JSONField(),
                },
            )
        },
        description=(
            "Retrieve day/week/month/year buckets for TP/SL PnL and position activity counts."
        ),
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="strategy/metrics/periodic",
        throttle_classes=[TaskDataRateThrottle],
    )
    def strategy_periodic_metrics(self, request: Request, pk: int | None = None) -> Response:
        from apps.trading.services.strategy_data import StrategyDataService

        task = self.get_object()  # type: ignore[attr-defined]
        return Response(
            StrategyDataService().periodic_metrics(
                request=request,
                task=task,
                task_type_label=self.task_type_label,
            )
        )

    @extend_schema(
        tags=["Trading"],
        parameters=[
            OpenApiParameter("execution_id", str, required=False),
            OpenApiParameter("since", str, required=False),
            OpenApiParameter("until", str, required=False),
        ],
        responses={
            200: inline_serializer(
                "TaskStrategyLossCutEventsResponse",
                fields={
                    "execution_id": serializers.CharField(allow_null=True),
                    "strategy_type": serializers.CharField(),
                    "instrument": serializers.CharField(allow_null=True),
                    "count": serializers.IntegerField(),
                    "results": serializers.ListField(child=serializers.JSONField()),
                },
            )
        },
        description=(
            "List loss-cut trades for an execution. "
            "Used by chart overlays to draw vertical reference lines marking "
            "each forced liquidation with the units closed."
        ),
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="strategy/loss-cut-events",
        throttle_classes=[TaskDataRateThrottle],
    )
    def strategy_loss_cut_events(self, request: Request, pk: int | None = None) -> Response:
        from apps.trading.services.strategy_data import StrategyDataService

        task = self.get_object()  # type: ignore[attr-defined]
        return Response(
            StrategyDataService().loss_cut_events(
                request=request,
                task=task,
                task_type_label=self.task_type_label,
            )
        )

    @extend_schema(
        tags=["Trading"],
        parameters=[
            OpenApiParameter("execution_id", str, required=False),
            OpenApiParameter("center", str, required=False),
            OpenApiParameter("since", str, required=False),
            OpenApiParameter("until", str, required=False),
            OpenApiParameter("granularity", str, required=False),
            OpenApiParameter("before_bars", int, required=False),
            OpenApiParameter("after_bars", int, required=False),
            OpenApiParameter("follow", bool, required=False),
            OpenApiParameter("merge_markers", bool, required=False),
            OpenApiParameter("account_id", str, required=False),
        ],
        responses={
            200: inline_serializer(
                "TaskSnowballNetChartResponse",
                fields={
                    "execution_id": serializers.CharField(allow_null=True),
                    "strategy_type": serializers.CharField(),
                    "instrument": serializers.CharField(allow_null=True),
                    "window": serializers.JSONField(),
                    "current": serializers.JSONField(),
                    "candles": serializers.ListField(child=serializers.JSONField()),
                    "price_lines": serializers.ListField(child=serializers.JSONField()),
                    "oscillator_lines": serializers.ListField(child=serializers.JSONField()),
                    "markers": serializers.ListField(child=serializers.JSONField()),
                },
            )
        },
        description="Retrieve SnowballNet OHLC, average-price lines, metrics, and markers.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="strategy/net-chart",
        throttle_classes=[TaskDataRateThrottle],
    )
    def strategy_net_chart(self, request: Request, pk: int | None = None) -> Response:
        from apps.trading.services.strategy_data import StrategyDataService

        task = self.get_object()  # type: ignore[attr-defined]
        return Response(
            StrategyDataService().net_chart(
                request=request,
                task=task,
                task_type_label=self.task_type_label,
            )
        )
