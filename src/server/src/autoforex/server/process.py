"""Long-running AutoForex server process lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from signal import SIGINT, SIGTERM, signal
from threading import Event

from autoforex.server.composition import ServerApplication
from autoforex.server.discovery import (
    ServiceInstance,
    ServiceRegistrationService,
)
from autoforex.server.grpc_service import GrpcTaskServer, TaskGrpcService


@dataclass(slots=True)
class ServerProcess:
    """Own startup recovery, gRPC serving, and graceful shutdown."""

    application: ServerApplication
    grpc_server: GrpcTaskServer
    discovery: ServiceRegistrationService | None = None
    _stopped: Event = field(default_factory=Event, init=False, repr=False)

    @classmethod
    def create(cls, application: ServerApplication) -> ServerProcess:
        """Create the gRPC process from a composed application."""
        settings = application.settings
        grpc_server = GrpcTaskServer(
            TaskGrpcService(
                application.supervisor,
                service_registry=application.service_registry,
            ),
            host=settings.host,
            port=settings.port,
            max_workers=settings.grpc_workers,
            settings=settings,
        )
        discovery = None
        if settings.service_discovery_enabled:
            current = datetime.now(UTC)
            advertised_host = settings.service_discovery_advertised_host or settings.host
            instance = ServiceInstance(
                instance_id=application.supervisor.server_id,
                host=advertised_host,
                port=grpc_server.port,
                transport_security=settings.transport_security.value,
                version=version("auto-forex-server"),
                started_at=current,
                heartbeat_at=current,
                expires_at=current + timedelta(seconds=settings.service_discovery_ttl_seconds),
                capabilities=settings.service_discovery_capabilities,
                metadata=settings.service_discovery_metadata,
            )
            discovery = ServiceRegistrationService(
                application.service_registry,
                instance,
                heartbeat_interval_seconds=(settings.service_discovery_heartbeat_interval_seconds),
                ttl_seconds=settings.service_discovery_ttl_seconds,
            )
        return cls(
            application=application,
            grpc_server=grpc_server,
            discovery=discovery,
        )

    def start(self) -> None:
        """Recover desired-running tasks before serving requests."""
        report = self.application.supervisor.recover_active()
        report.require_complete()
        self.grpc_server.start()
        if self.discovery is not None:
            self.discovery.start()

    def run(self) -> None:
        """Install process signals, start, and block."""
        self._install_signal_handlers()
        self.start()
        self.grpc_server.wait()

    def stop(self) -> None:
        """Stop gRPC, preserve active intents, and release resources once."""
        if self._stopped.is_set():
            return
        self._stopped.set()
        settings = self.application.settings
        try:
            if self.discovery is not None:
                self.discovery.stop()
            self.grpc_server.stop(
                grace_seconds=settings.shutdown_grace_seconds,
            )
        finally:
            self.application.close()

    def _install_signal_handlers(self) -> None:
        signal(SIGINT, lambda *_: self.stop())
        signal(SIGTERM, lambda *_: self.stop())
        try:
            from signal import SIGHUP
        except ImportError:
            return
        signal(SIGHUP, lambda *_: self.reload_transport())

    def reload_transport(self) -> None:
        """Reload TLS material by replacing the gRPC listener."""
        if self._stopped.is_set():
            return
        settings = self.application.settings
        old_server = self.grpc_server
        old_server.stop(grace_seconds=settings.shutdown_grace_seconds)
        self.grpc_server = GrpcTaskServer(
            TaskGrpcService(
                self.application.supervisor,
                service_registry=self.application.service_registry,
            ),
            host=settings.host,
            port=settings.port,
            max_workers=settings.grpc_workers,
            settings=settings,
        )
        self.grpc_server.start()
        if self.discovery is not None:
            self.discovery.update_endpoint(
                host=settings.service_discovery_advertised_host or settings.host,
                port=self.grpc_server.port,
                transport_security=settings.transport_security.value,
            )
