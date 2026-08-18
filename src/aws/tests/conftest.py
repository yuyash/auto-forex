from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest

from autoforex.aws import DynamoDbTaskStore


@pytest.fixture
def dynamodb_live_store() -> Iterator[DynamoDbTaskStore]:
    """Create and delete an isolated table on DynamoDB or DynamoDB Local."""
    table_prefix = os.getenv("AUTO_FOREX_TEST_DYNAMODB_TABLE")
    if not table_prefix:
        pytest.skip("AUTO_FOREX_TEST_DYNAMODB_TABLE is required for live DynamoDB tests")
    endpoint_url = os.getenv("AUTO_FOREX_TEST_DYNAMODB_ENDPOINT_URL")
    table_name = f"{table_prefix}-{uuid4()}"
    store = DynamoDbTaskStore.from_table_name(
        table_name,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-west-2"),
        endpoint_url=endpoint_url,
        enable_point_in_time_recovery=endpoint_url is None,
    )
    store.create_schema()
    try:
        yield store
    finally:
        store.client.delete_table(TableName=table_name)
