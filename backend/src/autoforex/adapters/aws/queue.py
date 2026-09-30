"""Publish normalized prices to SQS."""

from typing import Any

from autoforex.domain.price import Price


class SqsPricePublisher:
    def __init__(self, queue_url: str, client: Any) -> None:
        self._queue_url = queue_url
        self._client = client

    def publish(self, price: Price) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=price.message_body(),
            MessageGroupId=price.symbol,
            MessageDeduplicationId=price.deduplication_id(),
        )
