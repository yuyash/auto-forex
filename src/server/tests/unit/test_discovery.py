from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from autoforex.server.discovery import (
    CloudMapServiceRegistry,
    ServiceInstance,
    ServiceRegistrationService,
)


def service_instance(
    *,
    instance_id: str = "server-a",
    current: datetime | None = None,
) -> ServiceInstance:
    timestamp = current or datetime.now(UTC)
    return ServiceInstance(
        instance_id=instance_id,
        host="10.0.0.5",
        port=50051,
        transport_security="plaintext",
        version="0.1.1",
        started_at=timestamp,
        heartbeat_at=timestamp,
        expires_at=timestamp + timedelta(seconds=20),
        capabilities=("task-service-v1",),
        metadata={"zone": "us-west-2a"},
    )


class RecordingRegistry:
    def __init__(self) -> None:
        self.registered: list[ServiceInstance] = []
        self.deregistered: list[str] = []

    def register(self, instance: ServiceInstance) -> None:
        self.registered.append(instance)

    def deregister(self, instance_id: str) -> None:
        self.deregistered.append(instance_id)

    def list_instances(self) -> tuple[ServiceInstance, ...]:
        return tuple(self.registered)

    def is_healthy(self) -> bool:
        return True

    def close(self) -> None:
        return None


class FakeCloudMapClient:
    def __init__(self) -> None:
        self.instances: dict[str, dict[str, str]] = {}
        self.deregistered: list[str] = []
        self.closed = False

    def register_instance(self, **request: Any) -> dict[str, str]:
        self.instances[request["InstanceId"]] = request["Attributes"]
        return {"OperationId": "operation-1"}

    def deregister_instance(self, **request: Any) -> dict[str, str]:
        self.deregistered.append(request["InstanceId"])
        self.instances.pop(request["InstanceId"], None)
        return {"OperationId": "operation-2"}

    def discover_instances(self, **request: Any) -> dict[str, Any]:
        _ = request
        return {
            "Instances": [
                {
                    "InstanceId": instance_id,
                    "Attributes": attributes,
                    "HealthStatus": "HEALTHY",
                }
                for instance_id, attributes in self.instances.items()
            ]
        }

    def close(self) -> None:
        self.closed = True


class TestServiceInstance:
    def test_formats_ipv6_authority_and_filters_expired_instances(self) -> None:
        current = datetime(2026, 8, 16, tzinfo=UTC)
        instance = service_instance(current=current).evolve(host="2001:db8::1")

        assert instance.address == "[2001:db8::1]:50051"
        assert instance.is_active(at=current + timedelta(seconds=19))
        assert not instance.is_active(at=current + timedelta(seconds=20))

    def test_rejects_invalid_registration_timestamps(self) -> None:
        current = datetime(2026, 8, 16, tzinfo=UTC)

        with pytest.raises(ValueError, match="expires_at"):
            service_instance(current=current).evolve(expires_at=current)


class TestServiceRegistrationService:
    def test_registers_refreshes_endpoint_and_deregisters(self) -> None:
        current = datetime(2026, 8, 16, tzinfo=UTC)
        clock_values = iter(
            (
                current + timedelta(seconds=1),
                current + timedelta(seconds=2),
            )
        )
        registry = RecordingRegistry()
        registration = ServiceRegistrationService(
            registry,
            service_instance(current=current),
            heartbeat_interval_seconds=60,
            ttl_seconds=120,
            clock=lambda: next(clock_values),
        )

        registration.start()
        registration.update_endpoint(
            host="server.internal",
            port=51051,
            transport_security="tls",
        )
        assert registration.healthy
        registration.stop()

        assert registry.registered[0].heartbeat_at == current + timedelta(seconds=1)
        assert registry.registered[-1].host == "server.internal"
        assert registry.registered[-1].port == 51051
        assert registry.deregistered == ["server-a"]

    def test_requires_ttl_to_exceed_heartbeat_interval(self) -> None:
        with pytest.raises(ValueError, match="TTL"):
            ServiceRegistrationService(
                RecordingRegistry(),
                service_instance(),
                heartbeat_interval_seconds=10,
                ttl_seconds=10,
            )


class TestCloudMapServiceRegistry:
    def test_round_trips_registration_and_deregistration(self) -> None:
        client = FakeCloudMapClient()
        registry = CloudMapServiceRegistry(
            client=client,
            service_id="srv-123",
            namespace_name="internal.example",
            service_name="autoforex",
        )
        instance = service_instance()

        registry.register(instance)

        assert registry.list_instances() == (instance,)
        assert client.instances["server-a"]["AWS_INSTANCE_IPV4"] == "10.0.0.5"
        assert registry.is_healthy()
        registry.deregister("server-a")
        assert registry.list_instances() == ()
        registry.close()
        assert client.closed
