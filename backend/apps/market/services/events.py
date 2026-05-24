"""apps.market.services.events

Market-owned event logging.

This is intentionally independent of the accounts/trading event mechanisms.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps

from apps.market.enums import MarketEventCategory, MarketEventSeverity, MarketEventType
from apps.market.models import OandaAccounts


class MarketEventService:
    """Event service that persists MarketEvent records.

    This service is intentionally side-effect-only and must never raise.
    """

    def __init__(self, *, task: Any | None = None) -> None:
        self.task = task

    def log_event(
        self,
        *,
        event_type: MarketEventType,
        description: str,
        severity: MarketEventSeverity = MarketEventSeverity.INFO,
        category: MarketEventCategory = MarketEventCategory.MARKET,
        user: Any | None = None,
        account: OandaAccounts | None = None,
        instrument: str | None = None,
        task_type: str | None = None,
        task_id: Any | None = None,
        execution_id: Any | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            MarketEvent = django_apps.get_model("market", "MarketEvent")
            resolved_task_type, resolved_task_id, resolved_execution_id = (
                self._resolve_task_context(
                    task_type=task_type,
                    task_id=task_id,
                    execution_id=execution_id,
                )
            )

            MarketEvent.objects.create(
                event_type=str(event_type),
                category=str(category),
                severity=str(severity),
                description=description,
                user=user if getattr(user, "pk", None) else None,
                account=account if getattr(account, "pk", None) else None,
                instrument=instrument or "",
                task_type=resolved_task_type,
                task_id=resolved_task_id,
                execution_id=resolved_execution_id,
                details=details or {},
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Never break request handling/tasks due to logging failures.
            return

    def _resolve_task_context(
        self,
        *,
        task_type: str | None,
        task_id: Any | None,
        execution_id: Any | None,
    ) -> tuple[str, Any | None, Any | None]:
        if task_type or task_id or execution_id:
            return task_type or "", task_id, execution_id

        task = self.task
        if getattr(task, "pk", None) is None:
            return "", None, None

        class_name = task.__class__.__name__
        resolved_task_type = "backtest" if "Backtest" in class_name else "trading"
        return (
            resolved_task_type,
            getattr(task, "pk", None),
            getattr(task, "execution_id", None),
        )

    def log_trading_event(
        self,
        *,
        event_type: MarketEventType,
        description: str,
        severity: MarketEventSeverity = MarketEventSeverity.INFO,
        user: Any | None = None,
        account: OandaAccounts | None = None,
        instrument: str | None = None,
        task_type: str | None = None,
        task_id: Any | None = None,
        execution_id: Any | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.log_event(
            event_type=event_type,
            description=description,
            severity=severity,
            category=MarketEventCategory.TRADING,
            user=user,
            account=account,
            instrument=instrument,
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
            details=details,
        )

    def log_security_event(
        self,
        *,
        event_type: MarketEventType,
        description: str,
        severity: MarketEventSeverity = MarketEventSeverity.INFO,
        user: Any | None = None,
        account: OandaAccounts | None = None,
        instrument: str | None = None,
        task_type: str | None = None,
        task_id: Any | None = None,
        execution_id: Any | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.log_event(
            event_type=event_type,
            description=description,
            severity=severity,
            category=MarketEventCategory.SECURITY,
            user=user,
            account=account,
            instrument=instrument,
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
            details=details,
        )
