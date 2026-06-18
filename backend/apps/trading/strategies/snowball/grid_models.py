"""Grid models for Snowball strategy."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.state_parsing import SNOWBALL_STATE_PARSER

# ---------------------------------------------------------------------------
# Slot
# ---------------------------------------------------------------------------


@dataclass
class Slot:
    """A numbered seat inside a layer.

    Addressing: ``(layer_number, index)`` where ``index`` is 0-based.
    R0 is the layer-initial position (or the cycle-initial for L0).
    R1…R(r_max) are counter-trend retracement positions.

    States:
    - empty + not ever_closed → available for a new entry
    - occupied → holds an open entry
    - pending_rebuild → entry was closed by stop-loss, awaiting rebuild.
      The slot is logically "present" (blocks counter adds and new layers)
      but has no live entry.
    - empty + ever_closed → sealed; triggers new layer on next adverse move
    """

    index: int  # 0-based (R0=0, R1=1, …)
    entry: Entry | None = None
    ever_closed: bool = False
    pending_rebuild: StopLossClosedEntry | None = None
    build_count: int = 0

    def __post_init__(self) -> None:
        if self.build_count == 0 and (
            self.entry is not None or self.pending_rebuild is not None or self.ever_closed
        ):
            self.build_count = 1

    @property
    def is_occupied(self) -> bool:
        """True if a live entry is present."""
        return self.entry is not None

    @property
    def is_present(self) -> bool:
        """True if the slot holds a live entry OR is awaiting SL rebuild.

        Use this instead of ``is_occupied`` when you need to treat
        stop-loss-closed positions as still "there" (e.g. for counter-add
        distance calculations and layer-progression checks).
        """
        return self.entry is not None or self.pending_rebuild is not None

    @property
    def is_empty(self) -> bool:
        return self.entry is None

    @property
    def is_pending_rebuild(self) -> bool:
        """True if the slot is awaiting stop-loss rebuild."""
        return self.pending_rebuild is not None

    @property
    def is_available(self) -> bool:
        """True if this slot can accept a new entry.

        A slot with a pending rebuild is NOT available — it is reserved
        for the rebuild.
        """
        return self.entry is None and not self.ever_closed and self.pending_rebuild is None

    def fill(self, entry: Entry) -> None:
        self.entry = entry
        self.build_count += 1

    def close(self, *, refillable: bool) -> Entry | None:
        e = self.entry
        self.entry = None
        if not refillable:
            self.ever_closed = True
        return e

    def close_for_stop_loss(self, sl_snapshot: "StopLossClosedEntry") -> Entry | None:
        """Close the entry due to stop-loss and mark the slot for rebuild.

        The slot transitions to ``pending_rebuild`` state: no live entry,
        but logically present in the grid.
        """
        e = self.entry
        self.entry = None
        self.pending_rebuild = sl_snapshot
        # ever_closed stays False — the slot is reserved for rebuild
        return e

    def complete_rebuild(self, entry: Entry) -> None:
        """Fill the slot with a rebuilt entry, clearing the pending state."""
        self.entry = entry
        self.pending_rebuild = None
        self.ever_closed = False
        self.build_count += 1

    def reset(self) -> None:
        self.entry = None
        self.ever_closed = False
        self.pending_rebuild = None
        self.build_count = 0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "index": self.index,
            "entry": self.entry.to_dict() if self.entry else None,
            "ever_closed": self.ever_closed,
            "build_count": self.build_count,
        }
        if self.pending_rebuild is not None:
            d["pending_rebuild"] = self.pending_rebuild.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Slot":
        d = SNOWBALL_STATE_PARSER.require_dict(d, field_name="slot")
        raw_entry = d.get("entry")
        raw_pending = d.get("pending_rebuild")
        ever_closed = SNOWBALL_STATE_PARSER.strict_bool(
            SNOWBALL_STATE_PARSER.require(d, "ever_closed"), field_name="ever_closed"
        )
        build_count = SNOWBALL_STATE_PARSER.optional_int(d, "build_count")
        return Slot(
            index=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "index"), field_name="index"
            ),
            entry=Entry.from_dict(raw_entry) if raw_entry else None,
            ever_closed=ever_closed,
            pending_rebuild=(StopLossClosedEntry.from_dict(raw_pending) if raw_pending else None),
            build_count=(
                build_count
                if build_count is not None
                else _infer_legacy_build_count(
                    raw_entry=raw_entry,
                    raw_pending=raw_pending,
                    ever_closed=ever_closed,
                )
            ),
        )


def _infer_legacy_build_count(
    *,
    raw_entry: Any,
    raw_pending: Any,
    ever_closed: bool,
) -> int:
    """Best-effort count for persisted states created before build_count."""
    if isinstance(raw_entry, dict):
        lifecycle_count = SNOWBALL_STATE_PARSER.optional_int(raw_entry, "lifecycle_stop_loss_count")
        return max(1, 1 + (lifecycle_count or 0))
    if isinstance(raw_pending, dict):
        lifecycle_count = SNOWBALL_STATE_PARSER.optional_int(
            raw_pending, "lifecycle_stop_loss_count"
        )
        return max(1, lifecycle_count or 0)
    return 1 if ever_closed else 0


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------


@dataclass
class Layer:
    """A layer of ``r_max + 1`` slots (R0 … R(r_max)).

    R0 is the layer-initial (or cycle-initial for L1).
    R1…R(r_max) are counter-trend retracement slots.
    """

    layer_number: int  # 1-based
    slots: list[Slot] = field(default_factory=list)
    base_units: int = 1000
    refill_up_to: int = 2

    # -- Slot queries --

    def occupied_slots(self) -> list[Slot]:
        return [s for s in self.slots if s.is_occupied]

    def present_slots(self) -> list[Slot]:
        """Return slots that are occupied OR awaiting SL rebuild."""
        return [s for s in self.slots if s.is_present]

    def highest_occupied_slot(self) -> Slot | None:
        for slot in reversed(self.slots):
            if slot.is_occupied:
                return slot
        return None

    def highest_present_slot(self) -> Slot | None:
        """Highest slot that is occupied or pending rebuild."""
        for slot in reversed(self.slots):
            if slot.is_present:
                return slot
        return None

    def previous_present_slot(self, index: int) -> Slot | None:
        """Highest present slot with index lower than ``index``."""
        for slot in reversed(self.slots):
            if slot.index < index and slot.is_present:
                return slot
        return None

    def lowest_occupied_slot(self) -> Slot | None:
        for slot in self.slots:
            if slot.is_occupied:
                return slot
        return None

    def slot_at(self, index: int) -> Slot | None:
        """Return the slot at *index* (0-based), or None."""
        for s in self.slots:
            if s.index == index:
                return s
        return None

    def next_available_counter_slot(self) -> Slot | None:
        """Return the next available slot with index >= 1 (counter slots).

        Walks counter slots in order.  Returns None if a sealed or
        pending-rebuild slot is encountered before an available one,
        or all are occupied.
        """
        highest_present = self.highest_present_slot()
        for s in self.slots:
            if s.index == 0:
                continue  # skip R0 (layer-initial)
            if s.is_available:
                # Do not refill a lower slot while any higher-numbered slot
                # is still logically present; that would invert the in-layer
                # entry/TP ordering (for example reopening R3 while R4 remains
                # open or pending rebuild).
                if highest_present is not None and highest_present.index > s.index:
                    return None
                return s
            if s.is_pending_rebuild:
                # Slot is reserved for SL rebuild — skip but keep looking
                # for higher-numbered available slots.
                continue
            if s.is_empty and s.ever_closed:
                return None  # sealed → new layer needed
        return None

    @property
    def needs_new_layer(self) -> bool:
        """True if counter slots cannot accept more entries."""
        return self.next_available_counter_slot() is None

    def has_open_entries(self) -> bool:
        """True if any slot has a live entry."""
        return any(s.is_occupied for s in self.slots)

    def has_present_entries(self) -> bool:
        """True if any slot is occupied or pending rebuild."""
        return any(s.is_present for s in self.slots)

    def all_entries(self) -> list[Entry]:
        return [s.entry for s in self.slots if s.entry is not None]

    def iter_entries(self) -> Iterator[Entry]:
        for slot in self.slots:
            if slot.entry is not None:
                yield slot.entry

    def entry_count(self) -> int:
        return sum(1 for slot in self.slots if slot.entry is not None)

    # -- Close operations --

    def close_slot(self, slot_index: int, *, refillable: bool | None = None) -> Entry | None:
        """Close the entry in the slot at *slot_index*.

        If *refillable* is None, auto-determine from ``refill_up_to``:
        counter slots (index >= 1) with index <= refill_up_to are refillable.
        R0 is never auto-refillable (it's the layer-initial).
        """
        for s in self.slots:
            if s.index == slot_index and s.is_occupied:
                if refillable is None:
                    refillable = s.index >= 1 and s.index <= self.refill_up_to
                return s.close(refillable=refillable)
        return None

    def unseal_slots_above(self, index: int) -> None:
        """Reset ``ever_closed`` on slots above *index*.

        When a refillable slot is re-opened, any higher-numbered slots
        that were sealed by a previous TP close become reachable again.
        Without this reset, ``next_available_counter_slot`` would see
        the sealed slot and incorrectly trigger a new layer.
        """
        for s in self.slots:
            if s.index > index and s.ever_closed and s.entry is None and s.pending_rebuild is None:
                s.ever_closed = False

    def remove_entry(self, entry_id: int) -> None:
        """Remove an entry by ID (used by protection modes).  Seals the slot."""
        for s in self.slots:
            if s.entry is not None and s.entry.entry_id == entry_id:
                s.close(refillable=False)
                return

    # -- Serialisation --

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_number": self.layer_number,
            "slots": [s.to_dict() for s in self.slots],
            "base_units": self.base_units,
            "refill_up_to": self.refill_up_to,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Layer":
        d = SNOWBALL_STATE_PARSER.require_dict(d, field_name="layer")
        return Layer(
            layer_number=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "layer_number"), field_name="layer_number"
            ),
            slots=[
                Slot.from_dict(s)
                for s in SNOWBALL_STATE_PARSER.require_list(
                    SNOWBALL_STATE_PARSER.require(d, "slots"), field_name="slots"
                )
            ],
            base_units=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "base_units"), field_name="base_units"
            ),
            refill_up_to=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "refill_up_to"), field_name="refill_up_to"
            ),
        )

    @staticmethod
    def create(
        layer_number: int,
        r_max: int,
        base_units: int,
        refill_up_to: int = 2,
    ) -> "Layer":
        """Create a layer with R0 … R(r_max) slots (r_max + 1 total)."""
        return Layer(
            layer_number=layer_number,
            slots=[Slot(index=i) for i in range(r_max + 1)],
            base_units=base_units,
            refill_up_to=refill_up_to,
        )


# ---------------------------------------------------------------------------
# PositionGrid
# ---------------------------------------------------------------------------


@dataclass
class PositionGrid:
    """Flat, ordered collection of all positions in a cycle.

    The grid is a list of ``Layer`` objects.  Every position — including the
    cycle's first entry at L0/R0 — lives in a slot.  This eliminates the
    need for a separate ``initial_entry`` field and makes close ordering
    uniform.

    Ordering convention (grid_key = (layer, index)):
    - Front (oldest): L0/R0
    - Back  (newest): highest layer, highest index

    Normal TP closes from the back.  Shrink closes from the front.
    """

    layers: list[Layer] = field(default_factory=list)

    # -- Layer management --

    @property
    def current_layer(self) -> Layer | None:
        return self.layers[-1] if self.layers else None

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    def add_layer(self, layer: Layer) -> None:
        self.layers.append(layer)

    def find_layer(self, layer_number: int) -> Layer | None:
        for layer in self.layers:
            if layer.layer_number == layer_number:
                return layer
        return None

    # -- Entry queries --

    def all_entries(self) -> list[Entry]:
        entries: list[Entry] = []
        for layer in self.layers:
            entries.extend(layer.all_entries())
        return entries

    def iter_entries(self) -> Iterator[Entry]:
        for layer in self.layers:
            yield from layer.iter_entries()

    def entry_count(self) -> int:
        return sum(layer.entry_count() for layer in self.layers)

    def slot_for_entry(self, entry_id: int) -> tuple[Layer, Slot] | None:
        """Return the layer/slot containing an entry ID."""
        for layer in self.layers:
            for slot in layer.slots:
                if slot.entry is not None and slot.entry.entry_id == entry_id:
                    return layer, slot
        return None

    def head_entry(self) -> Entry | None:
        """Return the oldest surviving position (cycle head).

        This is the entry whose TP closes the cycle.  It is always the
        entry with the smallest grid_key among all occupied slots.
        """
        for layer in self.layers:
            lowest = layer.lowest_occupied_slot()
            if lowest is not None and lowest.entry is not None:
                return lowest.entry
        return None

    def tail_entry(self) -> Entry | None:
        """Return the newest position (highest grid_key)."""
        for layer in reversed(self.layers):
            highest = layer.highest_occupied_slot()
            if highest is not None and highest.entry is not None:
                return highest.entry
        return None

    def has_counter_entries(self) -> bool:
        """True if any position other than the head is open."""
        head = self.head_entry()
        if head is None:
            return False
        for layer in self.layers:
            for s in layer.slots:
                if s.entry is not None and s.entry.entry_id != head.entry_id:
                    return True
        return False

    def is_empty(self) -> bool:
        """True if no layer has live entries."""
        return all(not layer.has_open_entries() for layer in self.layers)

    def has_pending_rebuilds(self) -> bool:
        """True if any slot in the grid is awaiting SL rebuild."""
        return any(s.is_pending_rebuild for layer in self.layers for s in layer.slots)

    def is_fully_pending(self, f_max: int) -> bool:
        """True if the grid has all layers up to f_max and every slot is pending rebuild.

        The grid must contain exactly ``f_max`` layers (L1 … Lf)
        and every slot in every layer must be in ``pending_rebuild`` state.
        Returns False when layers have not been fully expanded yet.
        """
        if len(self.layers) < f_max:
            return False
        slots = [s for layer in self.layers for s in layer.slots]
        return len(slots) > 0 and all(s.is_pending_rebuild for s in slots)

    def pending_rebuild_slots(self) -> list[tuple["Layer", Slot]]:
        """Return all (layer, slot) pairs awaiting SL rebuild."""
        result: list[tuple[Layer, Slot]] = []
        for layer in self.layers:
            for s in layer.slots:
                if s.is_pending_rebuild:
                    result.append((layer, s))
        return result

    def first_pending_rebuild_slot(self) -> tuple["Layer", Slot] | None:
        """Return the oldest (lowest grid-key) slot awaiting SL rebuild.

        Layers are stored in ascending layer-number order and slots in
        ascending R-index order, so the first match is the lowest grid key.
        This is the effective cycle head when no live entry survives: the
        head lives in the lowest layer, which is not necessarily the current
        (top) layer.
        """
        for layer in self.layers:
            for s in layer.slots:
                if s.is_pending_rebuild:
                    return layer, s
        return None

    # -- Shrink: close from front --

    def front_entry(self) -> Entry | None:
        """Return the next shrink candidate respecting layer-preservation rules.

        Priority (within a single cycle):
        1. Lowest layer number first.
        2. Within a layer, lowest R index first.
        3. **Exception**: if a layer has exactly 1 occupied slot, check whether
           any *higher* layer has 2+ occupied slots.  If yes, skip this layer
           and let the higher layer yield a candidate (its lowest R).  If no
           higher layer has 2+ slots either, close this single position.

        This preserves the "last survivor" in a layer as long as there are
        still trimmable positions in upper layers.
        """
        layers = self.layers

        for i, layer in enumerate(layers):
            occupied_count = layer.entry_count()
            if occupied_count == 0:
                continue

            if occupied_count >= 2:
                # Multiple positions → close the lowest R
                lowest = layer.lowest_occupied_slot()
                if lowest is None:
                    return None
                return lowest.entry

            # Exactly 1 position in this layer.
            # Check if any higher layer has 2+ occupied slots.
            has_multi_above = any(upper.entry_count() >= 2 for upper in layers[i + 1 :])

            if has_multi_above:
                # Skip — upper layers still have trimmable positions
                continue

            # All layers above also have ≤1 position. Close this one.
            lowest = layer.lowest_occupied_slot()
            return lowest.entry if lowest is not None else None

        return None

    # -- Normal TP: close from back --

    def back_entry_for_tp(self) -> tuple[Entry | None, Layer | None]:
        """Return the newest counter entry eligible for TP close.

        Walks layers from newest to oldest, returning the highest occupied
        slot.  Skips the head entry (it closes via cycle TP, not counter TP).
        """
        head = self.head_entry()
        for layer in reversed(self.layers):
            highest = layer.highest_occupied_slot()
            if highest is None or highest.entry is None:
                continue
            if head is not None and highest.entry.entry_id == head.entry_id:
                continue  # don't close head via counter TP
            return highest.entry, layer
        return None, None

    # -- Remove entry (protection) --

    def remove_entry(self, entry_id: int) -> None:
        for layer in self.layers:
            layer.remove_entry(entry_id)

    # -- Serialisation --

    def to_dict(self) -> dict[str, Any]:
        return {"layers": [layer.to_dict() for layer in self.layers]}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PositionGrid":
        data = SNOWBALL_STATE_PARSER.require_dict(data, field_name="grid")
        raw_layers = SNOWBALL_STATE_PARSER.require_list(
            SNOWBALL_STATE_PARSER.require(data, "layers"), field_name="layers"
        )
        layers = [Layer.from_dict(ld) for ld in raw_layers]
        return PositionGrid(layers=layers)
