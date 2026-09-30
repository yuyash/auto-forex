"""Interfaces for application-user stream configuration."""

from typing import Protocol

from autoforex.ports.settings import UserStreamSettings


class UserStreamRepository(Protocol):
    def active_streams(self) -> tuple[UserStreamSettings, ...]: ...
