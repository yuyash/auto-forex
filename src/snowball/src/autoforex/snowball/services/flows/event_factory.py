"""Factory helpers for Snowball domain events."""

from __future__ import annotations

from dataclasses import dataclass

from autoforex.core import Metadata, Money

from autoforex.snowball.enums import CloseReason
from autoforex.snowball.events import SnowballCloseEvent, SnowballOpenEvent
from autoforex.snowball.models.entries import FilledEntry, RequestedEntry
from autoforex.snowball.models.state import Cycle


@dataclass(frozen=True, slots=True)
class SnowballEventFactory:
    """Create Snowball domain events from state transitions."""

    def open_event(
        self,
        *,
        cycle: Cycle,
        entry: RequestedEntry,
        metadata: Metadata | None = None,
    ) -> SnowballOpenEvent:
        """Return an open event for a requested entry."""
        return SnowballOpenEvent(
            cycle_id=entry.entry_id.cycle_id,
            direction=cycle.direction,
            entry=entry,
            metadata=metadata or Metadata(),
        )

    def close_event(
        self,
        *,
        cycle: Cycle,
        entry: FilledEntry,
        price: Money,
        close_reason: CloseReason,
        metadata: Metadata | None = None,
    ) -> SnowballCloseEvent:
        """Return a close event for a filled entry."""
        return SnowballCloseEvent(
            cycle_id=entry.entry_id.cycle_id,
            direction=cycle.direction,
            entry=entry,
            price=price,
            close_reason=close_reason,
            metadata=metadata or Metadata(),
        )
