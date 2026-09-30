"""Interfaces for operational and per-user price-stream settings."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OperationalSettings:
    ingestion_enabled: bool
    reconnect_max_delay_seconds: int

    def __post_init__(self) -> None:
        if not 1 <= self.reconnect_max_delay_seconds <= 300:
            raise ValueError("reconnect_max_delay_seconds must be between 1 and 300.")


@dataclass(frozen=True, slots=True)
class UserStreamSettings:
    user_id: str
    username: str
    oanda_environment: str
    account_id: str
    secret_id: str
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.oanda_environment not in {"practice", "live"}:
            raise ValueError("oanda_environment must be practice or live.")
        if not self.user_id or not self.account_id or not self.secret_id or not self.symbols:
            raise ValueError("User stream settings require IDs, account, secret, and symbols.")


class SettingsProvider(Protocol):
    def get(self) -> OperationalSettings: ...
