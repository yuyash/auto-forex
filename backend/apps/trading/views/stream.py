"""Server-sent task update streams."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import connections
from django.http import Http404, StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.trading.enums import TaskStatus, TaskType
from apps.trading.models import BacktestTask, ExecutionState, TradingTask
from apps.trading.services.public_errors import (
    task_public_error_code,
    task_public_error_message,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {TaskStatus.STOPPED, TaskStatus.COMPLETED, TaskStatus.FAILED}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


class ServerSentEventRenderer(BaseRenderer):
    """Renderer used only for DRF content negotiation on SSE endpoints."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = "utf-8"

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes:
        _ = accepted_media_type
        _ = renderer_context
        if data is None:
            return b""
        if isinstance(data, bytes):
            return data
        return str(data).encode(self.charset)


class TaskEventStreamView(APIView):
    """Stream lightweight task status snapshots over Server-Sent Events."""

    permission_classes = [IsAuthenticated]
    renderer_classes = [ServerSentEventRenderer]
    poll_interval_seconds = 3

    @extend_schema(exclude=True)
    def get(self, request: Request, task_type: str, task_id: UUID) -> StreamingHttpResponse:
        task_type = self._normalize_task_type(task_type)
        # Reconstruct the identifier through the UUID constructor so only a
        # validated, canonical value (hex digits and hyphens) can ever reach
        # the response body. This rejects any malformed input up front and
        # breaks the taint flow from the URL into the SSE stream.
        task_id = UUID(str(task_id))
        task_model = self._task_model(task_type)
        user_id = request.user.pk
        try:
            exists = task_model.objects.filter(pk=task_id, user=user_id).exists()
        finally:
            connections.close_all()
        if not exists:
            raise Http404("Task not found")

        response = StreamingHttpResponse(
            self._event_stream(
                task_type=task_type,
                task_model=task_model,
                task_id=task_id,
                user_id=user_id,
            ),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    async def _event_stream(
        self,
        *,
        task_type: str,
        task_model: type[BacktestTask] | type[TradingTask],
        task_id: UUID,
        user_id: int,
    ) -> AsyncIterator[str]:
        last_payload: dict[str, Any] | None = None

        try:
            while True:
                payload = await self._fetch_snapshot(
                    task_model=task_model,
                    task_id=task_id,
                    user_id=user_id,
                    task_type=task_type,
                )
                if payload is None:
                    yield _sse("deleted", {"id": str(task_id), "task_type": task_type})
                    return

                if payload != last_payload:
                    yield _sse("snapshot", payload)
                    last_payload = payload
                else:
                    yield _sse(
                        "heartbeat",
                        {
                            "id": str(task_id),
                            "task_type": task_type,
                            "timestamp": timezone.now().isoformat(),
                        },
                    )

                if payload["status"] in TERMINAL_STATUSES:
                    return

                await asyncio.sleep(self.poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task event stream aborted")
            return

    @classmethod
    async def _fetch_snapshot(
        cls,
        *,
        task_model: type[BacktestTask] | type[TradingTask],
        task_id: UUID,
        user_id: int,
        task_type: str,
    ) -> dict[str, Any] | None:
        return await sync_to_async(cls._fetch_snapshot_sync, thread_sensitive=False)(
            task_model=task_model,
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
        )

    @staticmethod
    def _fetch_snapshot_sync(
        *,
        task_model: type[BacktestTask] | type[TradingTask],
        task_id: UUID,
        user_id: int,
        task_type: str,
    ) -> dict[str, Any] | None:
        try:
            only_fields = [
                "id",
                "status",
                "execution_id",
                "started_at",
                "completed_at",
                "updated_at",
                "status_reason_code",
                "status_reason_message",
            ]
            if task_type == TaskType.BACKTEST:
                only_fields.extend(["start_time", "end_time"])

            task = task_model.objects.only(*only_fields).filter(pk=task_id, user=user_id).first()
            if task is None:
                return None
            progress = TaskEventStreamView._compute_progress(task, task_type)
            return TaskEventStreamView._snapshot(task, task_type, progress=progress)
        finally:
            connections.close_all()

    @staticmethod
    def _snapshot(
        task: BacktestTask | TradingTask,
        task_type: str,
        *,
        progress: int | None,
    ) -> dict[str, Any]:
        return {
            "id": str(task.pk),
            "task_type": task_type,
            "status": task.status,
            "progress": progress,
            "execution_id": str(task.execution_id) if task.execution_id else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "error_message": task_public_error_message(task.status),
            "error_code": task_public_error_code(task.status),
            "status_reason_code": getattr(task, "status_reason_code", "") or None,
            "status_reason_message": getattr(task, "status_reason_message", "") or None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }

    @staticmethod
    def _compute_progress(task: BacktestTask | TradingTask, task_type: str) -> int:
        if task_type != TaskType.BACKTEST:
            return 0
        if not isinstance(task, BacktestTask):
            return 0

        if task.status == TaskStatus.COMPLETED:
            return 100
        if task.status != TaskStatus.RUNNING or not task.execution_id:
            return 0

        state = (
            ExecutionState.objects.only("last_tick_timestamp")
            .filter(
                task_type=task_type,
                task_id=task.pk,
                execution_id=task.execution_id,
            )
            .first()
        )
        if state is None or state.last_tick_timestamp is None:
            return 0

        try:
            total_seconds = (task.end_time - task.start_time).total_seconds()
            if total_seconds <= 0:
                return 0
            elapsed_seconds = (state.last_tick_timestamp - task.start_time).total_seconds()
            progress = int((elapsed_seconds / total_seconds) * 100)
        except Exception:
            return 0
        return max(0, min(progress, 99))

    @staticmethod
    def _task_model(task_type: str):
        if task_type == TaskType.BACKTEST:
            return BacktestTask
        if task_type == TaskType.TRADING:
            return TradingTask
        raise Http404("Task type not found")

    @staticmethod
    def _normalize_task_type(task_type: str) -> str:
        if task_type == "backtest":
            return "backtest"
        if task_type == "trading":
            return "trading"
        raise Http404("Task type not found")
