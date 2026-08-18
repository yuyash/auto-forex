"""Structured metadata value object."""

from __future__ import annotations

from autoforex.core.models.mapping import MappingValueObject


class Metadata(MappingValueObject):
    """Read-only metadata wrapper for extension data."""
