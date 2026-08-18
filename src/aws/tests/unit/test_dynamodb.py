from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from autoforex.core import BacktestTaskDefinition, CurrencyPair, ExecutableTask
from botocore.exceptions import ClientError

import autoforex.aws.dynamodb as dynamodb_module
from autoforex.aws import DynamoDbDocument, DynamoDbTaskStore


class FakeTable:
    name = "tasks"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        item = kwargs["Item"]
        key = (item["namespace"], item["key"])
        existing = self.items.get(key)
        condition = kwargs.get("ConditionExpression")
        if condition == "attribute_not_exists(#namespace)" and existing is not None:
            raise self._conditional_failure()
        if condition == "#revision = :expected_revision":
            expected = kwargs["ExpressionAttributeValues"][":expected_revision"]
            if existing is None or existing.get("revision") != expected:
                raise self._conditional_failure()
        self.items[key] = dict(item)
        return {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        item = self.items.get((key["namespace"], key["key"]))
        return {} if item is None else {"Item": dict(item)}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        expression = kwargs["KeyConditionExpression"].get_expression()
        namespace = expression["values"][1]
        items = [
            dict(item)
            for (item_namespace, _), item in self.items.items()
            if item_namespace == namespace
        ]
        filter_expression = kwargs.get("FilterExpression")
        if filter_expression is not None:
            filter_parts = filter_expression.get_expression()
            expected = filter_parts["values"][1]
            items = [item for item in items if item.get("status") == expected]
        return {"Items": items}

    def delete_item(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        self.items.pop((key["namespace"], key["key"]), None)
        return {}

    @staticmethod
    def _conditional_failure() -> ClientError:
        return ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "condition failed",
                }
            },
            "PutItem",
        )


class FakeClient:
    def __init__(self) -> None:
        self.backups: list[dict[str, Any]] = []
        self.transactions: list[dict[str, Any]] = []

    def describe_table(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return {"Table": {"TableStatus": "ACTIVE"}}

    def update_continuous_backups(self, **kwargs: Any) -> dict[str, Any]:
        self.backups.append(kwargs)
        return {}

    def transact_write_items(self, **kwargs: Any) -> dict[str, Any]:
        self.transactions.append(kwargs)
        return {}


class TestDynamoDbTaskStore:
    def test_from_table_name_uses_a_low_level_client_for_transactions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        table = FakeTable()
        low_level_client = FakeClient()
        resource_client = object()

        class FakeResource:
            meta = SimpleNamespace(client=resource_client)

            def Table(self, table_name: str) -> FakeTable:
                assert table_name == table.name
                return table

        class FakeSession:
            def __init__(self, **kwargs: Any) -> None:
                assert kwargs == {
                    "profile_name": None,
                    "region_name": "us-west-2",
                }

            def resource(self, name: str, *, endpoint_url: str | None) -> FakeResource:
                assert name == "dynamodb"
                assert endpoint_url == "http://localhost:8000"
                return FakeResource()

            def client(self, name: str, *, endpoint_url: str | None) -> FakeClient:
                assert name == "dynamodb"
                assert endpoint_url == "http://localhost:8000"
                return low_level_client

        monkeypatch.setattr(dynamodb_module.boto3, "Session", FakeSession)

        store = DynamoDbTaskStore.from_table_name(
            table.name,
            region_name="us-west-2",
            endpoint_url="http://localhost:8000",
        )

        assert store.table is table
        assert store.client is low_level_client
        assert store.client is not resource_client

    def test_round_trips_tasks_and_filters_status(self) -> None:
        table = FakeTable()
        store = DynamoDbTaskStore(table=table, client=FakeClient())
        definition = BacktestTaskDefinition(
            name="Replay",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition).start(at=definition.start_at)

        store.save(task)

        assert store.get(task.id) == task
        assert store.list(status=task.status) == (task,)

    def test_document_write_uses_optimistic_revision(self) -> None:
        store = DynamoDbTaskStore(table=FakeTable(), client=FakeClient())
        first = DynamoDbDocument(
            namespace="intent",
            key="task-1",
            payload="{}",
            revision=1,
        )
        stale = DynamoDbDocument(
            namespace="intent",
            key="task-1",
            payload='{"state":"stale"}',
            revision=2,
        )

        assert store.put_document(first, expected_revision=0)
        assert not store.put_document(stale, expected_revision=0)
        assert store.put_document(stale, expected_revision=1)
        assert store.get_document("intent", "task-1") == stale

    def test_create_schema_enables_point_in_time_recovery(self) -> None:
        client = FakeClient()
        store = DynamoDbTaskStore(table=FakeTable(), client=client)

        store.create_schema()

        assert client.backups == [
            {
                "TableName": "tasks",
                "PointInTimeRecoverySpecification": {
                    "PointInTimeRecoveryEnabled": True,
                },
            }
        ]

    def test_fenced_task_save_checks_intent_and_writes_in_one_transaction(self) -> None:
        table = FakeTable()
        client = FakeClient()
        store = DynamoDbTaskStore(table=table, client=client)
        definition = BacktestTaskDefinition(
            name="Fenced replay",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition)
        lease_id = uuid4()
        store.configure_fencing(
            token_resolver=lambda task_id: SimpleNamespace(
                task_id=task_id,
                owner_id="server-a",
                lease_id=lease_id,
                fencing_token=7,
            ),
            intent_namespace="task-execution-intents",
        )

        store.save(task)

        transaction = client.transactions[0]["TransactItems"]
        condition = transaction[0]["ConditionCheck"]
        write = transaction[1]["Put"]
        assert condition["TableName"] == table.name
        assert condition["Key"]["namespace"]["S"] == "task-execution-intents"
        assert condition["Key"]["key"]["S"] == str(task.id)
        assert condition["ExpressionAttributeValues"][":fencing_token"]["N"] == "7"
        assert write["TableName"] == table.name
        assert write["Item"]["namespace"]["S"] == "tasks"
        assert write["Item"]["key"]["S"] == str(task.id)
