"""Currency, currency pair, and money value objects."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from functools import total_ordering
from logging import Logger
from typing import Any, Self

import pycountry
from pydantic import Field, model_validator

from autoforex.core.logging import get_logger
from autoforex.core.models.base import DomainModel

_LOGGER: Logger = get_logger(__name__)


class Currency(DomainModel):
    """ISO 4217 currency code."""

    code: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @classmethod
    def of(cls, value: Currency | str) -> Self:
        """Coerce a value to Currency."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, Currency):
            return data
        if isinstance(data, str):
            return {"code": data.strip().upper()}
        if isinstance(data, dict) and isinstance(data.get("code"), str):
            normalized = dict(data)
            normalized["code"] = normalized["code"].strip().upper()
            return normalized
        return data

    @model_validator(mode="after")
    def _validate_iso_4217_code(self) -> Self:
        if pycountry.currencies.get(alpha_3=self.code) is None:
            _LOGGER.debug(
                "Rejected unknown ISO 4217 currency code %s",
                self.code,
                extra={"currency": self.code},
            )
            msg = f"unknown ISO 4217 currency code: {self.code}"
            raise ValueError(msg)
        _LOGGER.debug(
            "Validated ISO 4217 currency code %s",
            self.code,
            extra={"currency": self.code},
        )
        return self

    def __str__(self) -> str:
        return self.code


class CurrencyPair(DomainModel):
    """Foreign-exchange instrument represented as base/quote currencies."""

    base: Currency
    quote: Currency

    @classmethod
    def of(
        cls,
        value: CurrencyPair | str | tuple[Currency | str, Currency | str] | list[Currency | str],
    ) -> Self:
        """Coerce a value to CurrencyPair."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, CurrencyPair):
            return data
        if isinstance(data, str):
            return cls._parse_symbol(data)
        if isinstance(data, tuple | list) and len(data) == 2:
            return {"base": data[0], "quote": data[1]}
        return data

    @model_validator(mode="after")
    def _validate_distinct_currencies(self) -> Self:
        if self.base == self.quote:
            msg = "base and quote currencies must be different"
            raise ValueError(msg)
        return self

    @classmethod
    def _parse_symbol(cls, symbol: str) -> dict[str, str]:
        normalized = symbol.strip().upper().replace("/", "_").replace("-", "_")
        if "_" in normalized:
            parts = normalized.split("_")
            if len(parts) == 2:
                _LOGGER.debug(
                    "Parsed currency pair symbol %s",
                    symbol,
                    extra={"instrument": f"{parts[0]}_{parts[1]}"},
                )
                return {"base": parts[0], "quote": parts[1]}
        if len(normalized) == 6:
            _LOGGER.debug(
                "Parsed currency pair symbol %s",
                symbol,
                extra={"instrument": f"{normalized[:3]}_{normalized[3:]}"},
            )
            return {"base": normalized[:3], "quote": normalized[3:]}

        _LOGGER.debug(
            "Rejected invalid currency pair symbol %s",
            symbol,
            extra={"instrument": symbol},
        )
        msg = f"invalid currency pair: {symbol}"
        raise ValueError(msg)

    @property
    def pip_size(self) -> Decimal:
        """Return the default FX pip size for this currency pair."""
        if self.quote.code == "JPY":
            return Decimal("0.01")
        return Decimal("0.0001")

    @property
    def symbol(self) -> str:
        """Return the canonical instrument symbol."""
        return f"{self.base}_{self.quote}"

    def __str__(self) -> str:
        return self.symbol


@total_ordering
class Money(DomainModel):
    """Monetary amount tagged with a currency."""

    amount: Decimal
    currency: Currency

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, Money):
            return data
        if isinstance(data, tuple | list) and len(data) == 2:
            cls._reject_primitive_amount(data[0])
            return {"amount": data[0], "currency": data[1]}
        if isinstance(data, Mapping) and "amount" in data:
            cls._reject_primitive_amount(data["amount"])
        return data

    @classmethod
    def of(cls, amount: Money | Decimal | str, currency: Currency | str) -> Money:
        """Create money from a numeric amount and currency."""
        expected_currency = Currency.of(currency)
        if isinstance(amount, Money):
            return amount.require_currency(expected_currency)
        return cls(amount=cls._amount_decimal(amount), currency=expected_currency)

    @classmethod
    def coerce(
        cls,
        value: Money | Decimal | str | Mapping[str, Any],
        currency: Currency | str,
    ) -> Money:
        """Coerce a raw amount or Money into the requested currency."""
        expected_currency = Currency.of(currency)
        if isinstance(value, Money):
            return value.require_currency(expected_currency)
        if isinstance(value, Mapping):
            return cls.model_validate(value).require_currency(expected_currency)
        return cls.of(value, expected_currency)

    @classmethod
    def coerce_positive(
        cls,
        value: Money | Decimal | str | Mapping[str, Any],
        currency: Currency | str,
    ) -> Money:
        """Coerce a raw amount or Money into a positive Money value."""
        return cls.coerce(value, currency).require_positive()

    @staticmethod
    def _reject_primitive_amount(value: Any) -> None:
        if isinstance(value, bool | int | float):
            raise TypeError("money amount must be provided as Money, Decimal, or str")

    @classmethod
    def _amount_decimal(cls, value: Decimal | str) -> Decimal:
        cls._reject_primitive_amount(value)
        return Decimal(str(value))

    def require_currency(self, currency: Currency) -> Self:
        """Return self when currencies match, otherwise raise ValueError."""
        expected = currency
        if self.currency != expected:
            _LOGGER.debug(
                "Rejected money currency mismatch",
                extra={
                    "currency": str(self.currency),
                    "expected_currency": str(expected),
                },
            )
            msg = f"currency mismatch: expected {expected}, got {self.currency}"
            raise ValueError(msg)
        _LOGGER.debug(
            "Validated money currency %s",
            expected,
            extra={"currency": str(expected)},
        )
        return self

    def require_positive(self) -> Self:
        """Return self when amount is positive, otherwise raise ValueError."""
        if self.amount <= 0:
            _LOGGER.debug(
                "Rejected non-positive money amount",
                extra={"currency": str(self.currency), "amount": str(self.amount)},
            )
            msg = "money amount must be greater than 0"
            raise ValueError(msg)
        return self

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __truediv__(self, divisor: Decimal | int) -> Money:
        return Money(amount=self.amount / Decimal(str(divisor)), currency=self.currency)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __lt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount < other.amount

    def __str__(self) -> str:
        amount = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{amount} {self.currency}"

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            _LOGGER.debug(
                "Rejected money operation for mismatched currencies",
                extra={
                    "currency": str(self.currency),
                    "other_currency": str(other.currency),
                },
            )
            msg = f"currency mismatch: {self.currency} != {other.currency}"
            raise ValueError(msg)
