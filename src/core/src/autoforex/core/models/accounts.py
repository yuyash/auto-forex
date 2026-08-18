"""Broker-neutral account value objects."""

from __future__ import annotations

from collections.abc import Mapping
from logging import Logger
from typing import Any, Self

from pydantic import AwareDatetime, Field, field_validator, model_serializer, model_validator

from autoforex.core.logging import get_logger
from autoforex.core.models.base import DomainModel
from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import Currency, Money
from autoforex.core.models.values import MarginRate

_LOGGER: Logger = get_logger(__name__)


class AccountProvider(DomainModel):
    """Provider identifier supplied by an adapter or runtime package."""

    value: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")

    @classmethod
    def of(cls, value: AccountProvider | str) -> Self:
        """Coerce a value to an account provider identifier."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, AccountProvider):
            return data
        if isinstance(data, str):
            return {"value": data.strip().lower()}
        if isinstance(data, Mapping) and isinstance(data.get("value"), str):
            normalized = dict(data)
            normalized["value"] = normalized["value"].strip().lower()
            return normalized
        return data

    @field_validator("value")
    @classmethod
    def _strip_value(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            _LOGGER.debug("Rejected blank account provider")
            msg = "account provider must not be blank"
            raise ValueError(msg)
        if normalized != value:
            _LOGGER.debug(
                "Normalized account provider",
                extra={"account_provider": normalized},
            )
        return normalized

    @model_serializer
    def _serialize(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


class AccountId(DomainModel):
    """Broker-neutral account identifier."""

    value: str = Field(min_length=1)

    @classmethod
    def of(cls, value: AccountId | str) -> Self:
        """Coerce a value to AccountId."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, AccountId):
            return data
        if isinstance(data, str):
            return {"value": data}
        return data

    @field_validator("value")
    @classmethod
    def _strip_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            _LOGGER.debug("Rejected blank account identifier")
            msg = "account identifier must not be blank"
            raise ValueError(msg)
        if normalized != value:
            _LOGGER.debug(
                "Normalized account identifier whitespace",
                extra={"account_id": normalized},
            )
        return normalized

    def __str__(self) -> str:
        return self.value


class Account(DomainModel):
    """Broker-neutral account reference used by trading tasks."""

    id: AccountId
    provider: AccountProvider | None = None
    alias: str | None = Field(default=None, min_length=1)
    metadata: Metadata = Field(default_factory=Metadata)

    @classmethod
    def of(cls, value: Account) -> Account:
        """Coerce a value to Account."""
        if not isinstance(value, Account):
            raise TypeError("account value must be an Account")
        return value

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, Account):
            return data
        if isinstance(data, str):
            return {"id": data}
        if isinstance(data, Mapping):
            normalized = dict(data)
            for key in ("provider", "alias"):
                if isinstance(normalized.get(key), str):
                    normalized[key] = normalized[key].strip()
            return normalized
        return data

    @model_validator(mode="after")
    def _log_account(self) -> Self:
        _LOGGER.debug(
            "Validated account reference %s",
            self.id,
            extra={
                "account_id": str(self.id),
                "account_provider": self.provider.value if self.provider else "",
                "account_alias": self.alias or "",
            },
        )
        return self

    def __str__(self) -> str:
        prefix = f"{self.provider.value}:" if self.provider else ""
        return f"{prefix}{self.id}"


class AccountSummary(DomainModel):
    """Broker-neutral account balance and margin summary."""

    account_id: AccountId
    currency: Currency
    alias: str | None = Field(default=None, min_length=1)
    balance: Money | None = None
    nav: Money | None = None
    margin_used: Money | None = None
    margin_available: Money | None = None
    margin_rate: MarginRate | None = None
    open_trade_count: int | None = Field(default=None, ge=0)
    open_position_count: int | None = Field(default=None, ge=0)
    pending_order_count: int | None = Field(default=None, ge=0)
    last_transaction_id: str | None = Field(default=None, min_length=1)
    created_at: AwareDatetime | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data

        normalized = dict(data)
        if normalized.get("currency") is not None:
            normalized["currency"] = Currency.of(normalized["currency"])
        currency = normalized.get("currency")
        if currency is not None:
            for field_name in ("balance", "nav", "margin_used", "margin_available"):
                if normalized.get(field_name) is not None:
                    normalized[field_name] = Money.coerce(
                        normalized[field_name],
                        currency,
                    )
        for key in ("alias", "last_transaction_id"):
            if isinstance(normalized.get(key), str):
                normalized[key] = normalized[key].strip()
        return normalized
