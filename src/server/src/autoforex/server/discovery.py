"""Service discovery models, registries, and registration lifecycle."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from ipaddress import ip_address
from threading import Event, RLock, Thread
from typing import Any, Protocol

from autoforex.core import DomainModel
from pydantic import Field, model_validator

from autoforex.server.optional import require_optional_dependency

_LOGGER = logging.getLogger(__name__)


class ServiceInstanceStatus(StrEnum):
    """Lifecycle status advertised for one server instance."""

    SERVING = "serving"
    DRAINING = "draining"


class ServiceInstance(DomainModel):
    """One discoverable AutoForex server endpoint."""

    instance_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    transport_security: str = Field(min_length=1)
    status: ServiceInstanceStatus = ServiceInstanceStatus.SERVING
    version: str = Field(min_length=1)
    started_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_times(self) -> ServiceInstance:
        for field_name in ("started_at", "heartbeat_at", "expires_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.heartbeat_at < self.started_at:
            raise ValueError("heartbeat_at must not precede started_at")
        if self.expires_at <= self.heartbeat_at:
            raise ValueError("expires_at must be later than heartbeat_at")
        return self

    @property
    def address(self) -> str:
        """Return a host:port authority, including IPv6 brackets when needed."""
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{host}:{self.port}"

    def is_active(self, *, at: datetime | None = None) -> bool:
        """Return whether this instance is serving and its TTL is live."""
        current = at or datetime.now(UTC)
        return self.status == ServiceInstanceStatus.SERVING and self.expires_at > current

    def refresh(
        self,
        *,
        at: datetime,
        ttl: timedelta,
        host: str | None = None,
        port: int | None = None,
        transport_security: str | None = None,
        status: ServiceInstanceStatus = ServiceInstanceStatus.SERVING,
    ) -> ServiceInstance:
        """Return an updated registration heartbeat."""
        return self.evolve(
            host=host or self.host,
            port=port or self.port,
            transport_security=transport_security or self.transport_security,
            status=status,
            heartbeat_at=at,
            expires_at=at + ttl,
        )


class ServiceRegistry(Protocol):
    """Storage boundary for discoverable server instances."""

    def register(self, instance: ServiceInstance) -> None:
        """Create or refresh one instance registration."""

    def deregister(self, instance_id: str) -> None:
        """Remove one instance registration."""

    def list_instances(self) -> Sequence[ServiceInstance]:
        """Return active server instances."""

    def is_healthy(self) -> bool:
        """Return whether the registry is reachable."""

    def close(self) -> None:
        """Release registry-owned resources."""


class CloudMapServiceRegistry:
    """Optional AWS Cloud Map implementation of the service registry."""

    _HOST = "AUTOFOREX_HOST"
    _TRANSPORT = "AUTOFOREX_TRANSPORT_SECURITY"
    _STATUS = "AUTOFOREX_STATUS"
    _VERSION = "AUTOFOREX_VERSION"
    _STARTED_AT = "AUTOFOREX_STARTED_AT"
    _HEARTBEAT_AT = "AUTOFOREX_HEARTBEAT_AT"
    _EXPIRES_AT = "AUTOFOREX_EXPIRES_AT"
    _CAPABILITIES = "AUTOFOREX_CAPABILITIES"
    _METADATA = "AUTOFOREX_METADATA"

    def __init__(
        self,
        *,
        client: Any,
        service_id: str,
        namespace_name: str,
        service_name: str,
    ) -> None:
        self.client = client
        self.service_id = service_id
        self.namespace_name = namespace_name
        self.service_name = service_name

    @classmethod
    def create(
        cls,
        *,
        service_id: str,
        namespace_name: str,
        service_name: str,
        region_name: str | None,
        endpoint_url: str | None,
    ) -> CloudMapServiceRegistry:
        """Create a Cloud Map registry without importing AWS dependencies eagerly."""
        boto3 = require_optional_dependency(
            "boto3",
            extra="aws",
            feature="AWS Cloud Map service discovery",
        )
        session = boto3.Session(region_name=region_name)
        client = session.client("servicediscovery", endpoint_url=endpoint_url)
        return cls(
            client=client,
            service_id=service_id,
            namespace_name=namespace_name,
            service_name=service_name,
        )

    def register(self, instance: ServiceInstance) -> None:
        """Create or refresh one Cloud Map registration."""
        attributes = {
            "AWS_INSTANCE_PORT": str(instance.port),
            self._HOST: instance.host,
            self._TRANSPORT: instance.transport_security,
            self._STATUS: instance.status.value,
            self._VERSION: instance.version,
            self._STARTED_AT: instance.started_at.astimezone(UTC).isoformat(),
            self._HEARTBEAT_AT: instance.heartbeat_at.astimezone(UTC).isoformat(),
            self._EXPIRES_AT: instance.expires_at.astimezone(UTC).isoformat(),
            self._CAPABILITIES: json.dumps(instance.capabilities, separators=(",", ":")),
            self._METADATA: json.dumps(instance.metadata, separators=(",", ":"), sort_keys=True),
        }
        try:
            address = ip_address(instance.host)
        except ValueError:
            pass
        else:
            attributes["AWS_INSTANCE_IPV4" if address.version == 4 else "AWS_INSTANCE_IPV6"] = (
                instance.host
            )
        self.client.register_instance(
            ServiceId=self.service_id,
            InstanceId=instance.instance_id,
            Attributes=attributes,
        )

    def deregister(self, instance_id: str) -> None:
        """Remove one Cloud Map registration."""
        self.client.deregister_instance(
            ServiceId=self.service_id,
            InstanceId=instance_id,
        )

    def list_instances(self) -> Sequence[ServiceInstance]:
        """Discover live AutoForex instances and filter expired registrations."""
        instances: list[ServiceInstance] = []
        next_token: str | None = None
        while True:
            request: dict[str, Any] = {
                "NamespaceName": self.namespace_name,
                "ServiceName": self.service_name,
                "HealthStatus": "ALL",
                "MaxResults": 100,
            }
            if next_token is not None:
                request["NextToken"] = next_token
            response = self.client.discover_instances(**request)
            instances.extend(self._instance(item) for item in response.get("Instances", ()))
            next_token = response.get("NextToken")
            if not next_token:
                break
        current = datetime.now(UTC)
        return tuple(
            sorted(
                (instance for instance in instances if instance.is_active(at=current)),
                key=lambda instance: instance.instance_id,
            )
        )

    def is_healthy(self) -> bool:
        """Return whether Cloud Map discovery succeeds."""
        try:
            self.list_instances()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the boto3 client when supported."""
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def _instance(self, item: Mapping[str, Any]) -> ServiceInstance:
        attributes = item.get("Attributes", {})
        host = str(
            attributes.get(self._HOST)
            or attributes.get("AWS_INSTANCE_IPV4")
            or attributes.get("AWS_INSTANCE_IPV6")
            or ""
        )
        return ServiceInstance(
            instance_id=str(item["InstanceId"]),
            host=host,
            port=int(attributes["AWS_INSTANCE_PORT"]),
            transport_security=str(attributes[self._TRANSPORT]),
            status=ServiceInstanceStatus(str(attributes[self._STATUS])),
            version=str(attributes[self._VERSION]),
            started_at=datetime.fromisoformat(str(attributes[self._STARTED_AT])),
            heartbeat_at=datetime.fromisoformat(str(attributes[self._HEARTBEAT_AT])),
            expires_at=datetime.fromisoformat(str(attributes[self._EXPIRES_AT])),
            capabilities=tuple(json.loads(str(attributes.get(self._CAPABILITIES, "[]")))),
            metadata=dict(json.loads(str(attributes.get(self._METADATA, "{}")))),
        )


class ServiceRegistrationService:
    """Register one process and refresh its discovery TTL in the background."""

    def __init__(
        self,
        registry: ServiceRegistry,
        instance: ServiceInstance,
        *,
        heartbeat_interval_seconds: float,
        ttl_seconds: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("service discovery heartbeat interval must be positive")
        if ttl_seconds <= heartbeat_interval_seconds:
            raise ValueError("service discovery TTL must exceed its heartbeat interval")
        self.registry = registry
        self._instance = instance
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.ttl = timedelta(seconds=ttl_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._stop = Event()
        self._thread: Thread | None = None
        self._healthy = True
        self._lock = RLock()

    @property
    def instance(self) -> ServiceInstance:
        """Return the latest locally advertised registration."""
        with self._lock:
            return self._instance

    @property
    def healthy(self) -> bool:
        """Return whether the latest registry operation succeeded."""
        with self._lock:
            thread_healthy = self._thread is None or self._thread.is_alive()
            return self._healthy and thread_healthy

    def start(self) -> None:
        """Register immediately and start periodic heartbeats."""
        with self._lock:
            if self._thread is not None:
                return
            self._refresh()
            self._thread = Thread(
                target=self._run,
                name="auto-forex-service-discovery-heartbeat",
                daemon=True,
            )
            self._thread.start()

    def update_endpoint(
        self,
        *,
        host: str,
        port: int,
        transport_security: str,
    ) -> None:
        """Publish a listener replacement without changing instance identity."""
        with self._lock:
            current = self.clock()
            self._instance = self._instance.refresh(
                at=current,
                ttl=self.ttl,
                host=host,
                port=port,
                transport_security=transport_security,
            )
            self.registry.register(self._instance)
            self._healthy = True

    def stop(self) -> None:
        """Stop heartbeats and remove the instance from discovery."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self.heartbeat_interval_seconds * 2))
        try:
            self.registry.deregister(self.instance.instance_id)
        except Exception:
            with self._lock:
                self._healthy = False
            _LOGGER.exception(
                "service discovery deregistration failed",
                extra={"instance_id": self.instance.instance_id},
            )

    def _refresh(self) -> None:
        current = self.clock()
        self._instance = self._instance.refresh(at=current, ttl=self.ttl)
        self.registry.register(self._instance)
        self._healthy = True

    def _run(self) -> None:
        while not self._stop.wait(self.heartbeat_interval_seconds):
            try:
                with self._lock:
                    self._refresh()
            except Exception:
                with self._lock:
                    self._healthy = False
                _LOGGER.exception(
                    "service discovery heartbeat failed",
                    extra={"instance_id": self.instance.instance_id},
                )
