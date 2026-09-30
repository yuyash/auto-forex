"""Store queued prices in DynamoDB."""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any

import boto3

logger = logging.getLogger(__name__)
_table = boto3.resource("dynamodb").Table(os.environ["PRICES_TABLE_NAME"])


def _item(body: str) -> dict[str, str | Decimal]:
    value = json.loads(body)
    try:
        return {
            "symbol": value["symbol"],
            "ask": Decimal(value["ask"]),
            "bid": Decimal(value["bid"]),
            "mid": Decimal(value["mid"]),
            "created_at": value["created_at"],
        }
    except (KeyError, InvalidOperation, TypeError) as error:
        raise ValueError("Invalid price message.") from error


def handler(event: dict[str, Any], _context: Any) -> dict[str, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        try:
            item = _item(record["body"])
            logger.info("price=%s", json.dumps(item, default=str, separators=(",", ":")))
            _table.put_item(Item=item)
        except (ValueError, KeyError, json.JSONDecodeError):
            logger.exception("failed to process price message")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
