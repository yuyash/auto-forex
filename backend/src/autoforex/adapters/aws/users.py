"""Read enabled streams from DynamoDB Users."""

from __future__ import annotations

from typing import Any

from autoforex.ports.settings import UserStreamSettings


class DynamoDbUserStreamRepository:
    index_name = "stream_status-index"

    def __init__(self, table: Any, environment: str) -> None:
        self._table = table
        self._stream_status = f"{environment}#ENABLED"

    def active_streams(self) -> tuple[UserStreamSettings, ...]:
        items: list[dict[str, Any]] = []
        request: dict[str, Any] = {
            "IndexName": self.index_name,
            "KeyConditionExpression": "stream_status = :status",
            "ExpressionAttributeValues": {":status": self._stream_status},
        }
        while True:
            response = self._table.query(**request)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            request["ExclusiveStartKey"] = last_key

        return tuple(
            UserStreamSettings(
                user_id=item["user_id"],
                username=item.get("username", ""),
                oanda_environment=item["oanda_environment"],
                account_id=item["oanda_account_id"],
                secret_id=item["oanda_secret_id"],
                symbols=tuple(item["symbols"]),
            )
            for item in items
        )
