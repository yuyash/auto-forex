"""Read operational settings from AWS AppConfig."""

from __future__ import annotations

import json
from typing import Any

from autoforex.ports.settings import OperationalSettings


class AppConfigSettingsProvider:
    def __init__(
        self,
        application_id: str,
        environment_id: str,
        profile_id: str,
        client: Any,
    ) -> None:
        self._application_id = application_id
        self._environment_id = environment_id
        self._profile_id = profile_id
        self._client = client
        self._token: str | None = None
        self._current = OperationalSettings(False, 30)
        self.next_poll_interval_seconds = 30

    def get(self) -> OperationalSettings:
        if self._token is None:
            response = self._client.start_configuration_session(
                ApplicationIdentifier=self._application_id,
                EnvironmentIdentifier=self._environment_id,
                ConfigurationProfileIdentifier=self._profile_id,
                RequiredMinimumPollIntervalInSeconds=15,
            )
            self._token = response["InitialConfigurationToken"]

        response = self._client.get_latest_configuration(ConfigurationToken=self._token)
        self._token = response["NextPollConfigurationToken"]
        self.next_poll_interval_seconds = max(response.get("NextPollIntervalInSeconds", 30), 15)
        content = response["Configuration"].read()
        if not content:
            return self._current

        value = json.loads(content)
        self._current = OperationalSettings(
            ingestion_enabled=value.get("ingestion_enabled", False),
            reconnect_max_delay_seconds=value.get("reconnect_max_delay_seconds", 30),
        )
        return self._current
