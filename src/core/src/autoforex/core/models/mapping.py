"""Read-only key/value value objects."""

from __future__ import annotations

from collections.abc import ItemsView, KeysView, Mapping, Sequence, ValuesView
from types import MappingProxyType
from typing import Any, Self

from pydantic import Field, field_serializer, model_validator

from autoforex.core.models.base import DomainModel


class MappingValueObject(DomainModel):
    """Base class for immutable domain objects backed by key/value data."""

    values: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, MappingValueObject):
            return {"values": data.to_dict()}
        if isinstance(data, Mapping):
            if set(data.keys()) == {"values"}:
                return data
            return {"values": dict(data)}
        return data

    @model_validator(mode="after")
    def _freeze_values(self) -> Self:
        object.__setattr__(self, "values", self._deep_freeze_mapping(self.values))
        return self

    @field_serializer("values")
    def _serialize_values(self, values: Mapping[str, Any]) -> dict[str, Any]:
        return self._deep_jsonable_mapping(values)

    @classmethod
    def of(cls, **values: Any) -> Self:
        """Create an instance from keyword values."""
        return cls(values=values)

    def get(self, key: str, default: Any = None) -> Any:
        """Return a value or default."""
        return self.values.get(key, default)

    def require(self, key: str) -> Any:
        """Return a value or raise KeyError."""
        return self.values[key]

    def with_value(self, key: str, value: Any) -> Self:
        """Return an instance with one value added or replaced."""
        return self.evolve(values={**self.values, key: value})

    def merge(self, values: MappingValueObject) -> Self:
        """Return an instance with values merged over this instance."""
        return self.evolve(values={**self.values, **values.values})

    def to_plain(self) -> dict[str, Any]:
        """Return a Python-native copy preserving tuple and frozenset values."""
        return self._deep_plain_mapping(self.values)

    def to_jsonable(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary copy."""
        return self._deep_jsonable_mapping(self.values)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary copy."""
        return self.to_jsonable()

    def keys(self) -> KeysView[str]:
        """Return keys."""
        return self.values.keys()

    def values_view(self) -> ValuesView[Any]:
        """Return values."""
        return self.values.values()

    def items(self) -> ItemsView[str, Any]:
        """Return items."""
        return self.values.items()

    def __contains__(self, key: object) -> bool:
        return key in self.values

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    @classmethod
    def _deep_freeze_mapping(cls, values: Mapping[str, Any]) -> Mapping[str, Any]:
        return MappingProxyType({key: cls._deep_freeze(value) for key, value in values.items()})

    @classmethod
    def _deep_freeze(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return MappingProxyType({key: cls._deep_freeze(item) for key, item in value.items()})
        if isinstance(value, str | bytes | bytearray):
            return value
        if isinstance(value, tuple | list):
            return tuple(cls._deep_freeze(item) for item in value)
        if isinstance(value, set | frozenset):
            return frozenset(cls._deep_freeze(item) for item in value)
        return value

    @classmethod
    def _deep_plain_mapping(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        return {key: cls._deep_plain(value) for key, value in values.items()}

    @classmethod
    def _deep_plain(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: cls._deep_plain(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return tuple(cls._deep_plain(item) for item in value)
        if isinstance(value, frozenset):
            return frozenset(cls._deep_plain(item) for item in value)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return tuple(cls._deep_plain(item) for item in value)
        return value

    @classmethod
    def _deep_jsonable_mapping(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        return {key: cls._deep_jsonable(value) for key, value in values.items()}

    @classmethod
    def _deep_jsonable(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: cls._deep_jsonable(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [cls._deep_jsonable(item) for item in value]
        if isinstance(value, frozenset):
            return [cls._deep_jsonable(item) for item in value]
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return [cls._deep_jsonable(item) for item in value]
        return value
