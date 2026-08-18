"""Value conversion helpers for OANDA transport requests and responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


class OandaDuration:
    """Validate transport duration settings."""

    @classmethod
    def validate(
        cls,
        value: timedelta,
        *,
        name: str,
        allow_zero: bool = False,
    ) -> timedelta:
        """Return a valid duration or raise a descriptive error."""
        if allow_zero:
            if value.total_seconds() < 0:
                raise ValueError(f"{name} must not be negative")
        elif value.total_seconds() <= 0:
            raise ValueError(f"{name} must be positive")
        return value


class OandaTransportCodec:
    """Serialize OANDA models, query values, and response bodies."""

    @classmethod
    def datetime_to_str(cls, value: Any) -> str:
        """Format a datetime value for OANDA query parameters."""
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        return str(value)

    @classmethod
    def json_body(cls, body: bytes) -> Any:
        """Decode a JSON HTTP response body."""
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    @classmethod
    def model_dump(cls, value: Any) -> Any:
        """Convert Pydantic models and containers to JSON-compatible data."""
        if value is None:
            return None
        if isinstance(value, BaseModel):
            return value.model_dump(by_alias=True, exclude_none=True, mode="json")
        if isinstance(value, Mapping):
            return {key: cls.model_dump(item) for key, item in value.items() if item is not None}
        if isinstance(value, tuple | list):
            return [cls.model_dump(item) for item in value]
        return value

    @classmethod
    def query_dump(cls, value: Any) -> dict[str, str]:
        """Convert OANDA query values to a string mapping for urlencode."""
        data = cls.model_dump(value)
        if not data:
            return {}
        if not isinstance(data, Mapping):
            msg = "query parameters must be a mapping or OandaModel"
            raise TypeError(msg)
        return {
            str(key): cls.query_value(item)
            for key, item in data.items()
            if item is not None and item != ()
        }

    @classmethod
    def query_value(cls, value: Any) -> str:
        """Serialize one query value."""
        if isinstance(value, tuple | list):
            return ",".join(cls.query_value(item) for item in value)
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, Enum):
            return str(value.value)
        if isinstance(value, datetime):
            return cls.datetime_to_str(value)
        if isinstance(value, Decimal):
            return str(value)
        return str(value)

    @classmethod
    def jsonable(cls, value: Any) -> Any:
        """Convert request payloads to values accepted by json.dumps."""
        if isinstance(value, Mapping):
            return {str(key): cls.jsonable(item) for key, item in value.items()}
        if isinstance(value, tuple | list):
            return [cls.jsonable(item) for item in value]
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return cls.datetime_to_str(value)
        if isinstance(value, Decimal):
            return str(value)
        return value
