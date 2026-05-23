"""Unit tests for BacktestTaskViewSet."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework import status as http_status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.trading.enums import TaskStatus
from apps.trading.services.task_capacity import TaskAdmissionDecision, QueueCapacitySnapshot
from apps.trading.tasks.service import TaskCapacityError, TaskSubmissionError, TaskValidationError
from apps.trading.views.backtest import BacktestTaskViewSet
from apps.trading.views.throttles import TaskDataRateThrottle

factory = APIRequestFactory()


def _make_task(pk=1, task_status=TaskStatus.CREATED, execution_id=None, name="bt-1"):
    task = MagicMock()
    task.pk = pk
    task.id = pk
    task.status = task_status
    task.execution_id = execution_id or uuid4()
    task.name = name
    task.instrument = "EUR_USD"
    task.start_time = None
    task.end_time = None
    return task


def _build_viewset(action="start"):
    vs = BacktestTaskViewSet()
    vs.action = action
    vs.kwargs = {"pk": 1}
    vs.format_kwarg = None
    vs.task_service = MagicMock()
    return vs


def _drf_post(data=None, query=""):
    django_req = factory.post(f"/{query}", data=data or {}, format="json")
    django_req.user = MagicMock(pk=1, id=1)
    drf_req = Request(django_req, parsers=[])
    drf_req._user = django_req.user
    drf_req._full_data = data or {}
    return drf_req


def _drf_get(query=""):
    django_req = factory.get(f"/{query}")
    django_req.user = MagicMock(pk=1, id=1)
    drf_req = Request(django_req)
    drf_req._user = django_req.user
    return drf_req


class TestGetSerializerClass:
    """Tests for get_serializer_class."""

    def test_uses_task_data_throttle_scope(self):
        assert BacktestTaskViewSet.throttle_classes == [TaskDataRateThrottle]
        assert TaskDataRateThrottle.scope == "task_data"

    def test_returns_create_serializer_for_create(self):
        vs = _build_viewset(action="create")
        cls = vs.get_serializer_class()
        assert cls.__name__ == "BacktestTaskCreateSerializer"

    def test_returns_create_serializer_for_update(self):
        vs = _build_viewset(action="update")
        cls = vs.get_serializer_class()
        assert cls.__name__ == "BacktestTaskCreateSerializer"

    def test_returns_create_serializer_for_partial_update(self):
        vs = _build_viewset(action="partial_update")
        cls = vs.get_serializer_class()
        assert cls.__name__ == "BacktestTaskCreateSerializer"

    def test_returns_default_serializer_for_list(self):
        vs = _build_viewset(action="list")
        cls = vs.get_serializer_class()
        assert cls.__name__ == "BacktestTaskListSerializer"

    def test_returns_default_serializer_for_retrieve(self):
        vs = _build_viewset(action="retrieve")
        cls = vs.get_serializer_class()
        assert cls.__name__ == "BacktestTaskSerializer"


class TestTaskDataRateThrottle:
    """Tests for resilient task data throttling."""

    def test_allows_request_when_cache_get_hits_redis_limit(self, monkeypatch):
        class UnavailableCache:
            def get(self, *_args, **_kwargs):
                raise RedisConnectionError("max number of clients reached")

        throttle = TaskDataRateThrottle()
        monkeypatch.setattr(throttle, "cache", UnavailableCache())

        assert throttle.allow_request(_drf_get(), MagicMock()) is True

    def test_allows_request_when_cache_set_hits_redis_limit(self, monkeypatch):
        class SetUnavailableCache:
            def get(self, *_args, **_kwargs):
                return []

            def set(self, *_args, **_kwargs):
                raise RedisConnectionError("max number of clients reached")

        throttle = TaskDataRateThrottle()
        monkeypatch.setattr(throttle, "cache", SetUnavailableCache())

        assert throttle.allow_request(_drf_get(), MagicMock()) is True


class TestResumeValidationPayload:
    """Tests for structured resume validation responses."""

    def test_resume_config_error_payload_is_structured(self):
        exc = TaskValidationError("blocked")
        exc.resume_config_error = {
            "code": "resume_task_fields_changed",
            "restart_required": True,
            "blocked_fields": ["pip_size"],
            "safe_fields": ["commission_per_trade"],
        }

        payload = BacktestTaskViewSet._resume_validation_payload(exc)

        assert payload["error_code"] == "resume_task_fields_changed"
        assert payload["restart_required"] is True
        assert payload["blocked_fields"] == ["pip_size"]
        assert payload["safe_fields"] == ["commission_per_trade"]


class TestGetQueryset:
    """Tests for get_queryset."""

    @patch("apps.trading.views.backtest.BacktestTask")
    def test_filters_by_user(self, MockModel):
        request = _drf_get()
        vs = _build_viewset(action="list")
        vs.request = request

        qs = MagicMock()
        MockModel.objects.filter.return_value = qs
        qs.select_related.return_value = qs
        qs.order_by.return_value = qs

        vs.get_queryset()
        MockModel.objects.filter.assert_called_once_with(user=1)
        qs.select_related.assert_called_once_with("config", "user", "oanda_candle_filter_account")

    @patch("apps.trading.views.backtest.BacktestTask")
    def test_filters_by_status_param(self, MockModel):
        request = _drf_get(query="?status=running")
        vs = _build_viewset(action="list")
        vs.request = request

        qs = MagicMock()
        MockModel.objects.filter.return_value = qs
        qs.select_related.return_value = qs
        qs.filter.return_value = qs
        qs.order_by.return_value = qs

        vs.get_queryset()
        qs.select_related.assert_called_once_with("config", "user", "oanda_candle_filter_account")
        qs.filter.assert_any_call(status="running")


class TestPerformCreate:
    """Tests for perform_create."""

    def test_sets_user_from_request(self):
        request = _drf_post()
        vs = _build_viewset(action="create")
        vs.request = request

        serializer = MagicMock()
        vs.perform_create(serializer)
        serializer.save.assert_called_once_with(user=request.user)

    @patch("apps.trading.views.backtest.logger")
    def test_integrity_error_with_unique_name(self, mock_logger):
        from django.db import IntegrityError
        from rest_framework.exceptions import ValidationError

        request = _drf_post()
        vs = _build_viewset(action="create")
        vs.request = request

        serializer = MagicMock()
        serializer.save.side_effect = IntegrityError("unique_user_backtest_task_name")

        with pytest.raises(ValidationError):
            vs.perform_create(serializer)


class TestStart:
    """Tests for start action."""

    def test_start_success(self):
        task = _make_task(task_status=TaskStatus.CREATED)
        vs = _build_viewset(action="start")
        vs.get_object = MagicMock(return_value=task)
        vs.get_serializer = MagicMock(return_value=MagicMock(data={"id": 1}))
        vs.task_service.start_task.return_value = task

        request = _drf_post()
        vs.request = request

        response = vs.start(request, pk=1)
        assert response.status_code == 200
        assert response.data == {"id": 1}
        vs.task_service.start_task.assert_called_once_with(task, user=request.user)

    def test_start_wrong_status_returns_400(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="start")
        vs.get_object = MagicMock(return_value=task)

        request = _drf_post()
        vs.request = request

        response = vs.start(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST

    def test_start_stopped_task_suggests_restart(self):
        task = _make_task(task_status=TaskStatus.STOPPED)
        vs = _build_viewset(action="start")
        vs.get_object = MagicMock(return_value=task)

        request = _drf_post()
        vs.request = request

        response = vs.start(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST
        assert "restart" in response.data["detail"]

    def test_start_validation_error_returns_400(self):
        task = _make_task(task_status=TaskStatus.CREATED)
        vs = _build_viewset(action="start")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.start_task.side_effect = TaskValidationError("bad config")

        request = _drf_post()
        vs.request = request

        response = vs.start(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Invalid start request for current task state"
        assert response.data["detail"] == "bad config"

    def test_start_submission_error_returns_500(self):
        task = _make_task(task_status=TaskStatus.CREATED)
        vs = _build_viewset(action="start")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.start_task.side_effect = TaskSubmissionError("celery down")

        request = _drf_post()
        vs.request = request

        response = vs.start(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_start_capacity_error_returns_409(self):
        task = _make_task(task_status=TaskStatus.CREATED)
        vs = _build_viewset(action="start")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.start_task.side_effect = TaskCapacityError(
            "queue full",
            decision=TaskAdmissionDecision(
                allowed=False,
                reason="queue full",
                details=(QueueCapacitySnapshot(queue="backtest", used=1, limit=1),),
                required_stops=(
                    {
                        "queue": "backtest",
                        "count": 1,
                        "task_type": "backtest task",
                        "message": "Stop at least 1 backtest task.",
                    },
                ),
            ),
        )

        request = _drf_post()
        vs.request = request

        response = vs.start(request, pk=1)
        assert response.status_code == http_status.HTTP_409_CONFLICT
        assert response.data["error"] == "Task capacity exhausted"
        assert response.data["required_stops"][0]["task_type"] == "backtest task"

    def test_start_unexpected_error_returns_500(self):
        task = _make_task(task_status=TaskStatus.CREATED)
        vs = _build_viewset(action="start")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.start_task.side_effect = Exception("unexpected")

        request = _drf_post()
        vs.request = request

        response = vs.start(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR


class TestStop:
    """Tests for stop action."""

    def test_stop_success(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="stop")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.stop_task.return_value = True

        request = _drf_post()
        vs.request = request

        response = vs.stop(request, pk=1)
        assert response.status_code == http_status.HTTP_202_ACCEPTED
        assert response.data == {
            "message": "Task stop requested",
            "command": "stop",
            "task_id": str(task.pk),
            "previous_status": TaskStatus.RUNNING.value,
            "next_status": TaskStatus.STOPPING.value,
            "status": TaskStatus.STOPPING.value,
            "accepted": True,
            "mode": "graceful",
        }
        vs.task_service.stop_task.assert_called_once_with(
            task.pk,
            mode="graceful",
            drain_duration_minutes=None,
            user=request.user,
        )

    def test_stop_drain_response_reports_draining(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="stop")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.stop_task.return_value = True

        request = _drf_post(data={"mode": "drain", "drain_duration_minutes": 15})
        vs.request = request

        response = vs.stop(request, pk=1)
        assert response.status_code == http_status.HTTP_202_ACCEPTED
        assert response.data["mode"] == "drain"
        assert response.data["previous_status"] == TaskStatus.RUNNING.value
        assert response.data["next_status"] == TaskStatus.DRAINING.value
        assert response.data["status"] == TaskStatus.DRAINING.value
        vs.task_service.stop_task.assert_called_once_with(
            task.pk,
            mode="drain",
            drain_duration_minutes=15,
            user=request.user,
        )

    def test_stop_failure_returns_500(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="stop")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.stop_task.return_value = False

        request = _drf_post()
        vs.request = request

        response = vs.stop(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_stop_value_error_returns_400(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="stop")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.stop_task.side_effect = ValueError("not stoppable")

        request = _drf_post()
        vs.request = request

        response = vs.stop(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST

    def test_stop_unexpected_error_returns_500(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="stop")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.stop_task.side_effect = Exception("boom")

        request = _drf_post()
        vs.request = request

        response = vs.stop(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR


class TestPause:
    """Tests for pause action."""

    def test_pause_success(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="pause")
        vs.get_object = MagicMock(return_value=task)
        vs.get_serializer = MagicMock(return_value=MagicMock(data={"id": 1}))
        vs.task_service.pause_task.return_value = True

        request = _drf_post()
        vs.request = request

        response = vs.pause(request, pk=1)
        assert response.status_code == 200
        vs.task_service.pause_task.assert_called_once_with(task.pk, user=request.user)

    def test_pause_not_running_returns_400(self):
        task = _make_task(task_status=TaskStatus.CREATED)
        vs = _build_viewset(action="pause")
        vs.get_object = MagicMock(return_value=task)

        request = _drf_post()
        vs.request = request

        response = vs.pause(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST

    def test_pause_failure_returns_500(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="pause")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.pause_task.return_value = False

        request = _drf_post()
        vs.request = request

        response = vs.pause(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_pause_exception_returns_500(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="pause")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.pause_task.side_effect = Exception("fail")

        request = _drf_post()
        vs.request = request

        response = vs.pause(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR


class TestRestart:
    """Tests for restart action."""

    def test_restart_success(self):
        task = _make_task(task_status=TaskStatus.STOPPED)
        vs = _build_viewset(action="restart")
        vs.get_object = MagicMock(return_value=task)
        vs.get_serializer = MagicMock(return_value=MagicMock(data={"id": 1}))
        vs.task_service.restart_task.return_value = task

        request = _drf_post()
        vs.request = request

        response = vs.restart(request, pk=1)
        assert response.status_code == 200
        assert response.data == {"id": 1}
        vs.task_service.restart_task.assert_called_once_with(task.pk, user=request.user)

    def test_restart_value_error_returns_400(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="restart")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.restart_task.side_effect = ValueError("retry limit")

        request = _drf_post()
        vs.request = request

        response = vs.restart(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Invalid restart request for current task state"
        assert "retry limit" not in response.data["detail"]

    def test_restart_task_validation_error_returns_detail(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="restart")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.restart_task.side_effect = TaskValidationError("risk limit")

        request = _drf_post()
        vs.request = request

        response = vs.restart(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Invalid restart request for current task state"
        assert response.data["detail"] == "risk limit"

    def test_restart_capacity_error_returns_409(self):
        task = _make_task(task_status=TaskStatus.STOPPED)
        vs = _build_viewset(action="restart")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.restart_task.side_effect = TaskCapacityError(
            "publisher full",
            decision=TaskAdmissionDecision(
                allowed=False,
                reason="publisher full",
                details=(QueueCapacitySnapshot(queue="backtest_publisher", used=1, limit=1),),
            ),
        )

        request = _drf_post()
        vs.request = request

        response = vs.restart(request, pk=1)
        assert response.status_code == http_status.HTTP_409_CONFLICT
        assert response.data["detail"] == "publisher full"

    def test_restart_runtime_error_returns_500(self):
        task = _make_task(task_status=TaskStatus.STOPPED)
        vs = _build_viewset(action="restart")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.restart_task.side_effect = RuntimeError("celery down")

        request = _drf_post()
        vs.request = request

        response = vs.restart(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_restart_unexpected_error_returns_500(self):
        task = _make_task(task_status=TaskStatus.STOPPED)
        vs = _build_viewset(action="restart")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.restart_task.side_effect = Exception("boom")

        request = _drf_post()
        vs.request = request

        response = vs.restart(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR


class TestResume:
    """Tests for resume action."""

    def test_resume_success(self):
        task = _make_task(task_status=TaskStatus.PAUSED)
        vs = _build_viewset(action="resume")
        vs.get_object = MagicMock(return_value=task)
        vs.get_serializer = MagicMock(return_value=MagicMock(data={"id": 1}))
        vs.task_service.resume_task.return_value = task

        request = _drf_post()
        vs.request = request

        response = vs.resume(request, pk=1)
        assert response.status_code == 200
        vs.task_service.resume_task.assert_called_once_with(task.pk, user=request.user)

    def test_resume_not_paused_returns_400(self):
        task = _make_task(task_status=TaskStatus.RUNNING)
        vs = _build_viewset(action="resume")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.resume_task.side_effect = TaskValidationError("invalid state")

        request = _drf_post()
        vs.request = request

        response = vs.resume(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST

    def test_resume_value_error_not_found_returns_400(self):
        task = _make_task(task_status=TaskStatus.PAUSED)
        vs = _build_viewset(action="resume")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.resume_task.side_effect = TaskValidationError("does not exist")

        request = _drf_post()
        vs.request = request

        response = vs.resume(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST

    def test_resume_value_error_returns_400(self):
        task = _make_task(task_status=TaskStatus.PAUSED)
        vs = _build_viewset(action="resume")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.resume_task.side_effect = TaskValidationError("invalid state")

        request = _drf_post()
        vs.request = request

        response = vs.resume(request, pk=1)
        assert response.status_code == http_status.HTTP_400_BAD_REQUEST

    def test_resume_bare_value_error_returns_500(self):
        """A bare ``ValueError`` escaping from the service is treated as an
        unexpected internal error and must not surface its raw message."""
        task = _make_task(task_status=TaskStatus.PAUSED)
        vs = _build_viewset(action="resume")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.resume_task.side_effect = ValueError("leaky internal detail")

        request = _drf_post()
        vs.request = request

        response = vs.resume(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "leaky internal detail" not in str(response.data)

    def test_resume_runtime_error_returns_500(self):
        task = _make_task(task_status=TaskStatus.PAUSED)
        vs = _build_viewset(action="resume")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.resume_task.side_effect = RuntimeError("celery down")

        request = _drf_post()
        vs.request = request

        response = vs.resume(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_resume_unexpected_error_returns_500(self):
        task = _make_task(task_status=TaskStatus.PAUSED)
        vs = _build_viewset(action="resume")
        vs.get_object = MagicMock(return_value=task)
        vs.task_service.resume_task.side_effect = Exception("boom")

        request = _drf_post()
        vs.request = request

        response = vs.resume(request, pk=1)
        assert response.status_code == http_status.HTTP_500_INTERNAL_SERVER_ERROR
