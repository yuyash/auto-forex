"""DynamoDB persistence primitives for durable AutoForex task state."""

from __future__ import annotations

import builtins
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import UUID

import boto3
from autoforex.core import ExecutableTask, TaskNotFoundError, TaskStatus
from autoforex.core.tasks.context import ContextStore
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

_TASK_NAMESPACE = "tasks"


@dataclass(frozen=True, slots=True)
class DynamoDbDocument:
    """Versioned JSON document stored in the shared server table."""

    namespace: str
    key: str
    payload: str
    revision: int
    attributes: dict[str, Any] = field(default_factory=dict)


class DynamoDbFenceError(RuntimeError):
    """Raised when a transactional task write has a stale fencing token."""


class DynamoDbTaskStore:
    """Core TaskRegistry and generic document store backed by DynamoDB."""

    def __init__(
        self,
        *,
        table: Any,
        client: Any,
        consistent_reads: bool = True,
        enable_point_in_time_recovery: bool = True,
        kms_key_arn: str | None = None,
    ) -> None:
        self.table = table
        self.client = client
        self.consistent_reads = consistent_reads
        self.enable_point_in_time_recovery = enable_point_in_time_recovery
        self.kms_key_arn = kms_key_arn
        self._lock = RLock()
        self._contexts = ContextStore(task_getter=self.get, task_saver=self.save)
        self._fence_token_resolver: Callable[[UUID], Any] | None = None
        self._fence_intent_namespace = ""
        self._fence_running_disposition = "running"
        self._serializer = TypeSerializer()

    @classmethod
    def from_table_name(
        cls,
        table_name: str,
        *,
        profile_name: str | None = None,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        consistent_reads: bool = True,
        enable_point_in_time_recovery: bool = True,
        kms_key_arn: str | None = None,
    ) -> DynamoDbTaskStore:
        """Create a store from boto3 session settings."""
        session = boto3.Session(
            profile_name=profile_name,
            region_name=region_name,
        )
        resource = session.resource("dynamodb", endpoint_url=endpoint_url)
        client = session.client("dynamodb", endpoint_url=endpoint_url)
        return cls(
            table=resource.Table(table_name),
            client=client,
            consistent_reads=consistent_reads,
            enable_point_in_time_recovery=enable_point_in_time_recovery,
            kms_key_arn=kms_key_arn,
        )

    def create_schema(self) -> None:
        """Create the shared table and enable point-in-time recovery."""
        table_name = self.table.name
        try:
            self.client.describe_table(TableName=table_name)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise
            sse = {"Enabled": True}
            if self.kms_key_arn is not None:
                sse.update(
                    {
                        "SSEType": "KMS",
                        "KMSMasterKeyId": self.kms_key_arn,
                    }
                )
            self.client.create_table(
                TableName=table_name,
                KeySchema=[
                    {"AttributeName": "namespace", "KeyType": "HASH"},
                    {"AttributeName": "key", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "namespace", "AttributeType": "S"},
                    {"AttributeName": "key", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
                SSESpecification=sse,
            )
            self.client.get_waiter("table_exists").wait(TableName=table_name)
        if self.enable_point_in_time_recovery:
            self.client.update_continuous_backups(
                TableName=table_name,
                PointInTimeRecoverySpecification={
                    "PointInTimeRecoveryEnabled": True,
                },
            )

    def close(self) -> None:
        """Release local resources held by the store."""
        return None

    def save(self, task: ExecutableTask) -> ExecutableTask:
        """Persist a complete Core task snapshot."""
        item = {
            "namespace": _TASK_NAMESPACE,
            "key": str(task.id),
            "definition_id": str(task.definition_id),
            "task_type": task.task_type.value,
            "status": task.status.value,
            "payload": task.model_dump_json(round_trip=True),
        }
        if self._fence_token_resolver is None:
            self.table.put_item(Item=item)
            return task
        token = self._fence_token_resolver(task.id)
        active_write = task.status not in {
            TaskStatus.PAUSED,
            TaskStatus.STOPPED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        }
        condition_expression = (
            "#owner_id = :owner_id "
            "AND #lease_id = :lease_id "
            "AND #fencing_token = :fencing_token "
            "AND #lease_expires_at > :now"
        )
        expression_names = {
            "#owner_id": "owner_id",
            "#lease_id": "lease_id",
            "#fencing_token": "fencing_token",
            "#lease_expires_at": "lease_expires_at",
        }
        expression_values: dict[str, Any] = {
            ":owner_id": token.owner_id,
            ":lease_id": str(token.lease_id),
            ":fencing_token": token.fencing_token,
            ":now": datetime.now(UTC).isoformat(timespec="microseconds"),
        }
        if active_write:
            condition_expression += " AND #disposition = :running"
            expression_names["#disposition"] = "disposition"
            expression_values[":running"] = self._fence_running_disposition
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": self.table.name,
                            "Key": self._serialize(
                                {
                                    "namespace": self._fence_intent_namespace,
                                    "key": str(task.id),
                                }
                            ),
                            "ConditionExpression": condition_expression,
                            "ExpressionAttributeNames": expression_names,
                            "ExpressionAttributeValues": self._serialize(expression_values),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": self._serialize(item),
                        }
                    },
                ]
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {
                "TransactionCanceledException",
                "ConditionalCheckFailedException",
            }:
                controlled = self._task_after_control_transition(
                    task,
                    token=token,
                    active_write=active_write,
                )
                if controlled is not None:
                    return controlled
                raise DynamoDbFenceError(f"stale task fencing token: {task.id}") from exc
            raise
        return task

    def configure_fencing(
        self,
        *,
        token_resolver: Callable[[UUID], Any],
        intent_namespace: str,
    ) -> None:
        """Require an atomic intent condition for every task write."""
        self._fence_token_resolver = token_resolver
        self._fence_intent_namespace = intent_namespace

    def _task_after_control_transition(
        self,
        task: ExecutableTask,
        *,
        token: Any,
        active_write: bool,
    ) -> ExecutableTask | None:
        if not active_write:
            return None
        response = self.table.get_item(
            Key={
                "namespace": self._fence_intent_namespace,
                "key": str(task.id),
            },
            ConsistentRead=True,
        )
        intent = response.get("Item")
        if intent is None:
            return None
        token_matches = (
            str(intent.get("owner_id", "")) == token.owner_id
            and str(intent.get("lease_id", "")) == str(token.lease_id)
            and int(intent.get("fencing_token", 0)) == token.fencing_token
            and str(intent.get("lease_expires_at", ""))
            > datetime.now(UTC).isoformat(timespec="microseconds")
        )
        if (
            not token_matches
            or str(intent.get("disposition", "")) == self._fence_running_disposition
        ):
            return None
        return self.get(task.id)

    def get(self, task_id: UUID) -> ExecutableTask:
        """Return a task by id."""
        response = self.table.get_item(
            Key={"namespace": _TASK_NAMESPACE, "key": str(task_id)},
            ConsistentRead=self.consistent_reads,
        )
        item = response.get("Item")
        if item is None:
            msg = f"task not found: {task_id}"
            raise TaskNotFoundError(msg)
        return ExecutableTask.model_validate_json(item["payload"])

    def list(self, *, status: TaskStatus | None = None) -> Sequence[ExecutableTask]:
        """List tasks, optionally filtered by status."""
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("namespace").eq(_TASK_NAMESPACE),
            "ConsistentRead": self.consistent_reads,
        }
        if status is not None:
            kwargs["FilterExpression"] = Attr("status").eq(status.value)
        items = self._query_all(kwargs)
        tasks = [ExecutableTask.model_validate_json(item["payload"]) for item in items]
        return tuple(sorted(tasks, key=lambda task: task.id))

    def initialize_context(self, task: ExecutableTask, *, strategy_name: str):
        """Initialize execution context for the current task run."""
        return self._contexts.initialize(task, strategy_name=strategy_name)

    def current_context(self, task_id: UUID):
        """Return the current in-process strategy context."""
        return self._contexts.current(task_id)

    def stage_context(self, context):
        """Stage strategy context before event publication."""
        return self._contexts.stage(context)

    def save_context(self, context):
        """Persist strategy state from a runtime context."""
        return self._contexts.save(context)

    def apply_execution_response(self, response) -> None:
        """Apply an execution response to runtime accounting state."""
        self._contexts.apply_execution_response(response)

    def put_document(
        self,
        document: DynamoDbDocument,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        """Write a JSON document, optionally using optimistic concurrency."""
        kwargs: dict[str, Any] = {
            "Item": {
                "namespace": document.namespace,
                "key": document.key,
                "payload": document.payload,
                "revision": document.revision,
                **document.attributes,
            }
        }
        if expected_revision == 0:
            kwargs["ConditionExpression"] = "attribute_not_exists(#namespace)"
            kwargs["ExpressionAttributeNames"] = {"#namespace": "namespace"}
        elif expected_revision is not None:
            kwargs["ConditionExpression"] = "#revision = :expected_revision"
            kwargs["ExpressionAttributeNames"] = {"#revision": "revision"}
            kwargs["ExpressionAttributeValues"] = {
                ":expected_revision": expected_revision,
            }
        try:
            self.table.put_item(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def get_document(self, namespace: str, key: str) -> DynamoDbDocument | None:
        """Return a versioned JSON document."""
        response = self.table.get_item(
            Key={"namespace": namespace, "key": key},
            ConsistentRead=self.consistent_reads,
        )
        item = response.get("Item")
        if item is None:
            return None
        return self._document(item)

    def list_documents(self, namespace: str) -> Sequence[DynamoDbDocument]:
        """List all documents in one namespace."""
        items = self._query_all(
            {
                "KeyConditionExpression": Key("namespace").eq(namespace),
                "ConsistentRead": self.consistent_reads,
            }
        )
        return tuple(self._document(item) for item in items)

    def delete_document(self, namespace: str, key: str) -> None:
        """Delete one document."""
        self.table.delete_item(Key={"namespace": namespace, "key": key})

    def _query_all(self, kwargs: dict[str, Any]) -> builtins.list[dict[str, Any]]:
        items: builtins.list[dict[str, Any]] = []
        request = dict(kwargs)
        while True:
            response = self.table.query(**request)
            items.extend(response.get("Items", ()))
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                return items
            request["ExclusiveStartKey"] = last_key

    @staticmethod
    def _document(item: dict[str, Any]) -> DynamoDbDocument:
        return DynamoDbDocument(
            namespace=str(item["namespace"]),
            key=str(item["key"]),
            payload=str(item["payload"]),
            revision=int(item.get("revision", 0)),
            attributes={
                key: value
                for key, value in item.items()
                if key not in {"namespace", "key", "payload", "revision"}
            },
        )

    def _serialize(self, values: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {key: self._serializer.serialize(value) for key, value in values.items()}
