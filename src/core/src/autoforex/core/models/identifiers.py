"""Identifier helpers for Core domain objects."""

from __future__ import annotations

from uuid import UUID, uuid7


def new_uuid() -> UUID:
    """Return a time-ordered UUIDv7 identifier."""
    return uuid7()
