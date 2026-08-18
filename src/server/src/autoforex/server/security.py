"""gRPC transport security, authentication, and authorization."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import grpc

from autoforex.server.settings import ServerSettings, TransportSecurityMode

_LOGGER = logging.getLogger(__name__)


class RpcPermission:
    """Stable permission names used by the task service."""

    HEALTH = "server.health"
    DISCOVERY = "server.discovery"
    READ = "tasks.read"
    BACKTEST_EXECUTE = "backtests.execute"
    TRADING_EXECUTE = "trading.execute"
    CONTROL = "tasks.control"


class TaskServicePermissions:
    """Map fully-qualified RPC methods to required permissions."""

    _BY_METHOD: ClassVar[dict[str, str]] = {
        "/autoforex.task.v1.TaskService/GetHealth": RpcPermission.HEALTH,
        "/autoforex.task.v1.TaskService/ListServerInstances": RpcPermission.DISCOVERY,
        "/autoforex.task.v1.TaskService/GetTask": RpcPermission.READ,
        "/autoforex.task.v1.TaskService/ListTasks": RpcPermission.READ,
        "/autoforex.task.v1.TaskService/StartBacktest": RpcPermission.BACKTEST_EXECUTE,
        "/autoforex.task.v1.TaskService/StartTrading": RpcPermission.TRADING_EXECUTE,
        "/autoforex.task.v1.TaskService/PauseTask": RpcPermission.CONTROL,
        "/autoforex.task.v1.TaskService/ResumeTask": RpcPermission.CONTROL,
        "/autoforex.task.v1.TaskService/StopTask": RpcPermission.CONTROL,
        "/autoforex.task.v1.TaskService/RestartTask": RpcPermission.CONTROL,
        "/autoforex.task.v1.TaskService/RecoverTask": RpcPermission.CONTROL,
    }

    @classmethod
    def for_method(cls, method: str) -> str | None:
        """Return the permission required by an RPC."""
        return cls._BY_METHOD.get(method)


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Authenticated client identity derived from transport credentials."""

    name: str


class MtlsPrincipalExtractor:
    """Extract an mTLS client common name from gRPC auth context."""

    def extract(self, context: grpc.ServicerContext) -> AuthenticatedPrincipal | None:
        """Return the authenticated principal, if present."""
        auth_context = context.auth_context()
        values = auth_context.get("x509_common_name") or auth_context.get(b"x509_common_name")
        if not values:
            return None
        value = values[0]
        name = value.decode() if isinstance(value, bytes) else str(value)
        return AuthenticatedPrincipal(name=name)


class AuthorizationPolicy:
    """Permission policy keyed by authenticated principal name."""

    def __init__(self, rules: Mapping[str, Sequence[str]]) -> None:
        self._rules = {
            principal: frozenset(permissions) for principal, permissions in rules.items()
        }

    def allows(self, principal: AuthenticatedPrincipal, permission: str) -> bool:
        """Return whether a principal has a permission."""
        permissions = self._rules.get(principal.name, frozenset())
        wildcard = self._rules.get("*", frozenset())
        return permission in permissions or "*" in permissions or permission in wildcard


class AuthorizationInterceptor(grpc.ServerInterceptor):
    """Enforce mTLS principal permissions before service dispatch."""

    def __init__(
        self,
        policy: AuthorizationPolicy,
        *,
        extractor: MtlsPrincipalExtractor | None = None,
    ) -> None:
        self.policy = policy
        self.extractor = extractor or MtlsPrincipalExtractor()

    def intercept_service(
        self,
        continuation: Callable,
        handler_call_details: grpc.HandlerCallDetails,
    ):
        """Wrap unary RPC handlers with authorization."""
        handler = continuation(handler_call_details)
        if handler is None or handler.unary_unary is None:
            return handler
        method = str(getattr(handler_call_details, "method", ""))
        permission = TaskServicePermissions.for_method(method)
        if permission is None:
            return handler

        def authorized(request, context):
            principal = self.extractor.extract(context)
            allowed = principal is not None and self.policy.allows(principal, permission)
            request_id = str(getattr(request, "request_id", "") or "")
            task_id = str(getattr(request, "task_id", "") or "")
            _LOGGER.info(
                "gRPC authorization decision",
                extra={
                    "rpc_method": method,
                    "principal": "" if principal is None else principal.name,
                    "permission": permission,
                    "authorized": allowed,
                    "peer": context.peer(),
                    "request_id": request_id,
                    "task_id": task_id,
                },
            )
            if principal is None:
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "client identity is required")
            if not allowed:
                context.abort(grpc.StatusCode.PERMISSION_DENIED, "permission denied")
            return handler.unary_unary(request, context)

        return grpc.unary_unary_rpc_method_handler(
            authorized,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


class CertificateSource:
    """Read TLS material from deployment-managed files."""

    @staticmethod
    def read(path: Path) -> bytes:
        """Return certificate or key bytes."""
        return path.read_bytes()


class GrpcServerSecurity:
    """Build gRPC credentials and interceptors from validated settings."""

    def __init__(
        self,
        settings: ServerSettings,
        *,
        certificates: CertificateSource | None = None,
    ) -> None:
        self.settings = settings
        self.certificates = certificates or CertificateSource()

    @property
    def secure(self) -> bool:
        """Return whether the listener uses TLS."""
        return self.settings.transport_security != TransportSecurityMode.PLAINTEXT

    def credentials(self) -> grpc.ServerCredentials | None:
        """Create fresh server credentials from certificate files."""
        if not self.secure:
            return None
        certificate_path = self.settings.tls_certificate_path
        private_key_path = self.settings.tls_private_key_path
        if certificate_path is None or private_key_path is None:
            raise RuntimeError("TLS certificate configuration is incomplete")
        root_certificates = None
        require_client_auth = self.settings.transport_security == TransportSecurityMode.MTLS
        if require_client_auth:
            client_ca_path = self.settings.tls_client_ca_path
            if client_ca_path is None:
                raise RuntimeError("mTLS client CA configuration is incomplete")
            root_certificates = self.certificates.read(client_ca_path)
        return grpc.ssl_server_credentials(
            (
                (
                    self.certificates.read(private_key_path),
                    self.certificates.read(certificate_path),
                ),
            ),
            root_certificates=root_certificates,
            require_client_auth=require_client_auth,
        )

    def interceptors(self) -> tuple[grpc.ServerInterceptor, ...]:
        """Create authentication and authorization interceptors."""
        if self.settings.transport_security != TransportSecurityMode.MTLS:
            return ()
        return (
            AuthorizationInterceptor(
                AuthorizationPolicy(self.settings.authorization_rules),
            ),
        )
