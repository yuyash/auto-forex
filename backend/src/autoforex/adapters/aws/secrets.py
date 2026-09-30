"""Resolve broker credentials from Secrets Manager."""

import json
from typing import Any


class SecretsManagerBrokerCredentialProvider:
    def __init__(self, secrets_client: Any) -> None:
        self._secrets = secrets_client

    def token_for(self, secret_id: str) -> str:
        secret = self._secrets.get_secret_value(SecretId=secret_id).get("SecretString", "")
        if not secret:
            raise ValueError(f"OANDA secret {secret_id} is empty.")
        try:
            value = json.loads(secret)
        except json.JSONDecodeError:
            return secret
        token = value.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("OANDA secret JSON must contain a non-empty token field.")
        return token
