"""Interfaces for user-bound broker credentials."""

from typing import Protocol


class BrokerCredentialProvider(Protocol):
    def token_for(self, secret_id: str) -> str: ...
