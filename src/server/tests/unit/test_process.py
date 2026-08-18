from __future__ import annotations

from typing import Any, ClassVar, cast

import pytest

import autoforex.server.process as process_module
from autoforex.server.process import ServerProcess
from autoforex.server.settings import ServerSettings


class RecordingRecoveryReport:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def require_complete(self) -> None:
        self.events.append("recovery-validated")


class RecordingSupervisor:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.server_id = "server-a"

    def recover_active(self) -> RecordingRecoveryReport:
        self.events.append("recovered")
        return RecordingRecoveryReport(self.events)


class RecordingServiceRegistry:
    def __init__(self) -> None:
        self.registered: list[Any] = []
        self.deregistered: list[str] = []

    def register(self, instance: Any) -> None:
        self.registered.append(instance)

    def deregister(self, instance_id: str) -> None:
        self.deregistered.append(instance_id)

    def list_instances(self) -> tuple[Any, ...]:
        return tuple(self.registered[-1:])


class RecordingApplication:
    def __init__(
        self,
        events: list[str],
        *,
        settings: ServerSettings | None = None,
    ) -> None:
        self.events = events
        self.settings = settings or ServerSettings(port=0)
        self.supervisor = RecordingSupervisor(events)
        self.service_registry = RecordingServiceRegistry()

    def close(self) -> None:
        self.events.append("application-closed")


class RecordingGrpcServer:
    instances: ClassVar[list[RecordingGrpcServer]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args
        _ = kwargs
        self.events: list[str] = []
        self.address = "127.0.0.1:50051"
        self.port = 50051
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.events.append("grpc-started")

    def wait(self) -> None:
        self.events.append("grpc-waited")

    def stop(self, *, grace_seconds: float) -> None:
        self.events.append(f"grpc-stopped:{grace_seconds}")


class TestServerProcess:
    def test_start_validates_recovery_before_accepting_requests(self) -> None:
        events: list[str] = []
        application = RecordingApplication(events)
        grpc_server = RecordingGrpcServer()
        process = ServerProcess(
            application=cast(Any, application),
            grpc_server=cast(Any, grpc_server),
        )

        process.start()

        assert events == ["recovered", "recovery-validated"]
        assert grpc_server.events == ["grpc-started"]

    def test_stop_is_idempotent_and_always_closes_application(self) -> None:
        events: list[str] = []
        application = RecordingApplication(events)
        grpc_server = RecordingGrpcServer()
        process = ServerProcess(
            application=cast(Any, application),
            grpc_server=cast(Any, grpc_server),
        )

        process.stop()
        process.stop()

        assert grpc_server.events == ["grpc-stopped:10.0"]
        assert events == ["application-closed"]

    def test_reload_replaces_the_listener_without_rebuilding_application(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        RecordingGrpcServer.instances.clear()
        monkeypatch.setattr(process_module, "GrpcTaskServer", RecordingGrpcServer)
        application = RecordingApplication([])
        process = ServerProcess.create(cast(Any, application))
        old_server = cast(RecordingGrpcServer, cast(Any, process.grpc_server))

        process.reload_transport()

        assert old_server.events == ["grpc-stopped:10.0"]
        assert process.grpc_server is not old_server
        replacement = cast(RecordingGrpcServer, cast(Any, process.grpc_server))
        assert replacement.events == ["grpc-started"]

    def test_reload_is_ignored_after_shutdown(self) -> None:
        application = RecordingApplication([])
        grpc_server = RecordingGrpcServer()
        process = ServerProcess(
            application=cast(Any, application),
            grpc_server=cast(Any, grpc_server),
        )
        process.stop()

        process.reload_transport()

        assert grpc_server.events == ["grpc-stopped:10.0"]

    def test_registers_and_deregisters_a_discoverable_instance(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        RecordingGrpcServer.instances.clear()
        monkeypatch.setattr(process_module, "GrpcTaskServer", RecordingGrpcServer)
        application = RecordingApplication(
            [],
            settings=ServerSettings(
                port=0,
                service_discovery_enabled=True,
                service_discovery_heartbeat_interval_seconds=60,
                service_discovery_ttl_seconds=120,
            ),
        )
        process = ServerProcess.create(cast(Any, application))

        process.start()
        process.stop()

        assert application.service_registry.registered[-1].instance_id == "server-a"
        assert application.service_registry.registered[-1].port == 50051
        assert application.service_registry.deregistered == ["server-a"]
