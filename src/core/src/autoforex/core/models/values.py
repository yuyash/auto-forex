"""Numeric value objects for domain-specific quantities."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, ClassVar, Self

from pydantic_core import core_schema


class DecimalValue(Decimal):
    """Decimal subtype with domain-specific validation."""

    label: ClassVar[str] = "value"
    minimum: ClassVar[Decimal | None] = None
    maximum: ClassVar[Decimal | None] = None

    def __new__(cls, value: Decimal | str = "0") -> Self:
        cls._reject_primitive_number(value)
        return Decimal.__new__(cls, str(value))

    @classmethod
    def of(cls, value: DecimalValue | Decimal | str) -> Self:
        """Coerce a raw number into this value object."""
        return cls._validate(value)

    @classmethod
    def tuple_of(cls, values: Sequence[DecimalValue | Decimal | str]) -> tuple[Self, ...]:
        """Coerce raw numbers into a tuple of this value object."""
        if not isinstance(values, Sequence) or isinstance(values, str | bytes | bytearray):
            msg = f"{cls.label} values must be provided as a sequence"
            raise TypeError(msg)
        return tuple(cls.of(value) for value in values)

    @classmethod
    def _validate(cls, value: Any) -> Self:
        if isinstance(value, cls):
            candidate = value
        else:
            candidate = cls(value)
        cls._validate_bounds(candidate)
        return candidate

    @classmethod
    def _reject_primitive_number(cls, value: Any) -> None:
        if isinstance(value, bool | int | float):
            msg = f"{cls.label} must be provided as {cls.__name__}, Decimal, or str"
            raise TypeError(msg)

    @classmethod
    def _validate_bounds(cls, value: Decimal) -> None:
        if cls.minimum is not None and value < cls.minimum:
            msg = f"{cls.label} must be greater than or equal to {cls.minimum}"
            raise ValueError(msg)
        if cls.maximum is not None and value > cls.maximum:
            msg = f"{cls.label} must be less than or equal to {cls.maximum}"
            raise ValueError(msg)

    def require_positive(self) -> Self:
        """Return self when positive, otherwise raise ValueError."""
        if self <= 0:
            msg = f"{self.label} must be greater than 0"
            raise ValueError(msg)
        return self

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Any,
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.no_info_before_validator_function(
                cls._pydantic_input,
                core_schema.union_schema(
                    [
                        core_schema.is_instance_schema(cls),
                        core_schema.decimal_schema(),
                        core_schema.str_schema(),
                    ]
                ),
            ),
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def _pydantic_input(cls, value: Any) -> Any:
        cls._reject_primitive_number(value)
        return value


class Units(DecimalValue):
    """Trade or position size units."""

    label = "units"
    minimum = Decimal("0")


class Pips(DecimalValue):
    """Price distance expressed in pips."""

    label = "pips"
    minimum = Decimal("0")


class Percent(DecimalValue):
    """Percentage value expressed on a 0-100 scale."""

    label = "percent"
    minimum = Decimal("0")


class MarginRate(DecimalValue):
    """Margin-rate ratio expressed as a decimal value."""

    label = "margin rate"
    minimum = Decimal("0")


class Confidence(DecimalValue):
    """Strategy decision confidence expressed on a 0-1 scale."""

    label = "confidence"
    minimum = Decimal("0")
    maximum = Decimal("1")
