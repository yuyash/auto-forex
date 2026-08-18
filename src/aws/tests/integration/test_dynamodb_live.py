from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from autoforex.core import BacktestTaskDefinition, CurrencyPair, ExecutableTask

from autoforex.aws import (
    DynamoDbDocument,
    DynamoDbFenceError,
    DynamoDbTaskStore,
)


class TestDynamoDbLiveIntegration:
    def test_versioned_document_round_trip(
        self,
        dynamodb_live_store: DynamoDbTaskStore,
    ) -> None:
        namespace = "integration-tests"
        key = str(uuid4())
        document = DynamoDbDocument(
            namespace=namespace,
            key=key,
            payload='{"status":"ok"}',
            revision=1,
        )

        assert dynamodb_live_store.put_document(document, expected_revision=0)
        assert not dynamodb_live_store.put_document(document, expected_revision=0)
        assert dynamodb_live_store.get_document(namespace, key) == document

    def test_task_registry_round_trip_and_status_filter(
        self,
        dynamodb_live_store: DynamoDbTaskStore,
    ) -> None:
        definition = BacktestTaskDefinition(
            name="DynamoDB integration replay",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition).start(at=definition.start_at)

        dynamodb_live_store.save(task)

        assert dynamodb_live_store.get(task.id) == task
        assert dynamodb_live_store.list(status=task.status) == (task,)

    def test_transactional_fencing_rejects_a_stale_owner(
        self,
        dynamodb_live_store: DynamoDbTaskStore,
    ) -> None:
        definition = BacktestTaskDefinition(
            name="DynamoDB fenced replay",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition)
        lease_id = uuid4()
        token = SimpleNamespace(
            task_id=task.id,
            owner_id="server-a",
            lease_id=lease_id,
            fencing_token=7,
        )
        dynamodb_live_store.put_document(
            DynamoDbDocument(
                namespace="task-execution-intents",
                key=str(task.id),
                payload="{}",
                revision=1,
                attributes={
                    "disposition": "running",
                    "owner_id": token.owner_id,
                    "lease_id": str(token.lease_id),
                    "fencing_token": token.fencing_token,
                    "lease_expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(
                        timespec="microseconds"
                    ),
                },
            ),
            expected_revision=0,
        )
        dynamodb_live_store.configure_fencing(
            token_resolver=lambda task_id: token,
            intent_namespace="task-execution-intents",
        )

        dynamodb_live_store.save(task)
        current = dynamodb_live_store.get_document(
            "task-execution-intents",
            str(task.id),
        )
        assert current is not None
        dynamodb_live_store.put_document(
            DynamoDbDocument(
                namespace=current.namespace,
                key=current.key,
                payload=current.payload,
                revision=current.revision + 1,
                attributes={
                    **current.attributes,
                    "owner_id": "server-b",
                    "fencing_token": 8,
                },
            ),
            expected_revision=current.revision,
        )

        with pytest.raises(DynamoDbFenceError):
            dynamodb_live_store.save(task.start(at=definition.start_at))
