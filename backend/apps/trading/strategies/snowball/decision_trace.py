"""Decision trace objects for Snowball tick processing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.conf import settings

from apps.trading.dataclasses.tick import Tick
from apps.trading.events import StrategyEvent
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState


@dataclass(frozen=True, slots=True)
class SnowballDecisionTraceRecord:
    """One phase-level Snowball decision trace record."""

    phase: str
    outcome: str
    reason: str
    cycle_id: int | None
    direction: str
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable trace record."""
        return {
            "phase": self.phase,
            "outcome": self.outcome,
            "reason": self.reason,
            "cycle_id": self.cycle_id,
            "direction": self.direction,
            "event_count": self.event_count,
        }


@dataclass(slots=True)
class SnowballDecisionTrace:
    """Per-tick collection of Snowball phase decisions."""

    tick_timestamp: datetime
    enabled: bool = False
    records: list[SnowballDecisionTraceRecord] = field(default_factory=list)

    def record(
        self,
        *,
        phase: str,
        outcome: str,
        reason: str,
        cycle: SnowballCycle | None = None,
        event_count: int = 0,
    ) -> None:
        """Append one decision trace record."""
        if not self.enabled:
            return
        self.records.append(
            SnowballDecisionTraceRecord(
                phase=phase,
                outcome=outcome,
                reason=reason,
                cycle_id=cycle.cycle_id if cycle is not None else None,
                direction=cycle.direction.value if cycle is not None else "",
                event_count=event_count,
            )
        )

    def record_events(
        self,
        *,
        phase: str,
        cycle: SnowballCycle,
        events: list[StrategyEvent],
        no_event_reason: str,
    ) -> None:
        """Record whether a phase mutated state or skipped with a reason."""
        if not self.enabled:
            return
        if events:
            self.record(
                phase=phase,
                outcome="events",
                reason="phase_emitted_events",
                cycle=cycle,
                event_count=len(events),
            )
            return
        self.record(
            phase=phase,
            outcome="skipped",
            reason=no_event_reason,
            cycle=cycle,
            event_count=0,
        )

    def to_dict(self, *, max_records: int) -> dict[str, Any]:
        """Return the latest trace records as a JSON-serializable mapping."""
        records = self.records[-max_records:] if max_records > 0 else []
        return {
            "tick_timestamp": self.tick_timestamp.isoformat(),
            "records": [record.to_dict() for record in records],
        }


class DisabledSnowballDecisionTrace:
    """Shared no-op trace used when decision tracing is disabled."""

    enabled = False

    def record(
        self,
        *,
        phase: str,
        outcome: str,
        reason: str,
        cycle: SnowballCycle | None = None,
        event_count: int = 0,
    ) -> None:
        _ = phase, outcome, reason, cycle, event_count

    def record_events(
        self,
        *,
        phase: str,
        cycle: SnowballCycle,
        events: list[StrategyEvent],
        no_event_reason: str,
    ) -> None:
        _ = phase, cycle, events, no_event_reason


DISABLED_SNOWBALL_DECISION_TRACE = DisabledSnowballDecisionTrace()


class SnowballDecisionTraceRecorder:
    """Persist the latest Snowball decision trace into strategy metrics."""

    def __init__(
        self,
        *,
        metrics_key: str = "snowball_decision_trace",
        max_records: int = 64,
        enabled: bool | None = None,
    ) -> None:
        self.metrics_key = metrics_key
        self.max_records = max_records
        self.enabled = (
            bool(getattr(settings, "SNOWBALL_DECISION_TRACE_ENABLED", False))
            if enabled is None
            else enabled
        )
        self._disabled_metric_removed = False

    def start_tick(self, *, tick: Tick) -> SnowballDecisionTrace | DisabledSnowballDecisionTrace:
        """Create an empty trace for the tick being processed."""
        if not self.enabled or self.max_records <= 0:
            return DISABLED_SNOWBALL_DECISION_TRACE
        return SnowballDecisionTrace(
            tick_timestamp=tick.timestamp,
            enabled=True,
        )

    def persist(
        self,
        *,
        ss: SnowballStrategyState,
        trace: SnowballDecisionTrace | DisabledSnowballDecisionTrace,
    ) -> None:
        """Store the latest trace as compact JSON in Snowball metrics."""
        if not trace.enabled:
            if not self._disabled_metric_removed:
                ss.metrics.pop(self.metrics_key, None)
                self._disabled_metric_removed = True
            return
        self._disabled_metric_removed = False
        ss.metrics[self.metrics_key] = json.dumps(
            trace.to_dict(max_records=self.max_records),
            separators=(",", ":"),
        )
