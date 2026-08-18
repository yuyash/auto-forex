from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import grpc
import pytest

import autoforex.server.security as security_module
from autoforex.server.security import (
    AuthenticatedPrincipal,
    AuthorizationInterceptor,
    AuthorizationPolicy,
    GrpcServerSecurity,
    MtlsPrincipalExtractor,
    RpcPermission,
    TaskServicePermissions,
)
from autoforex.server.settings import ServerSettings, TransportSecurityMode


class RecordingSecurityContext:
    def __init__(self, common_name: bytes | str | None) -> None:
        self.common_name = common_name
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    def auth_context(self) -> dict[Any, list[bytes | str]]:
        if self.common_name is None:
            return {}
        return {"x509_common_name": [self.common_name]}

    def peer(self) -> str:
        return "ipv4:127.0.0.1:50000"

    def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise PermissionError(details)


class TestTaskServicePermissions:
    @pytest.mark.parametrize(
        ("method", "permission"),
        [
            ("/autoforex.task.v1.TaskService/GetHealth", RpcPermission.HEALTH),
            (
                "/autoforex.task.v1.TaskService/ListServerInstances",
                RpcPermission.DISCOVERY,
            ),
            ("/autoforex.task.v1.TaskService/GetTask", RpcPermission.READ),
            ("/autoforex.task.v1.TaskService/StartBacktest", RpcPermission.BACKTEST_EXECUTE),
            ("/autoforex.task.v1.TaskService/StartTrading", RpcPermission.TRADING_EXECUTE),
            ("/autoforex.task.v1.TaskService/RecoverTask", RpcPermission.CONTROL),
        ],
    )
    def test_maps_public_rpc_to_stable_permission(
        self,
        method: str,
        permission: str,
    ) -> None:
        assert TaskServicePermissions.for_method(method) == permission

    def test_unknown_rpc_has_no_implicit_permission(self) -> None:
        assert TaskServicePermissions.for_method("/unknown.Service/Call") is None


class TestMutualTlsAuthentication:
    @pytest.mark.parametrize("common_name", [b"operator", "operator"])
    def test_extracts_principal_from_transport_common_name(
        self,
        common_name: bytes | str,
    ) -> None:
        context = RecordingSecurityContext(common_name)

        principal = MtlsPrincipalExtractor().extract(cast(grpc.ServicerContext, cast(Any, context)))

        assert principal == AuthenticatedPrincipal(name="operator")

    def test_missing_common_name_is_unauthenticated(self) -> None:
        context = RecordingSecurityContext(None)

        assert (
            MtlsPrincipalExtractor().extract(cast(grpc.ServicerContext, cast(Any, context))) is None
        )

    def test_policy_supports_principal_and_global_permissions(self) -> None:
        policy = AuthorizationPolicy(
            {
                "operator": (RpcPermission.CONTROL,),
                "*": (RpcPermission.HEALTH,),
            }
        )
        principal = AuthenticatedPrincipal(name="operator")

        assert policy.allows(principal, RpcPermission.CONTROL)
        assert policy.allows(principal, RpcPermission.HEALTH)
        assert not policy.allows(principal, RpcPermission.TRADING_EXECUTE)


class TestAuthorizationInterceptor:
    def test_authorized_unary_rpc_reaches_the_service_handler(self) -> None:
        interceptor = AuthorizationInterceptor(
            AuthorizationPolicy({"operator": (RpcPermission.HEALTH,)})
        )
        handler = grpc.unary_unary_rpc_method_handler(lambda request, context: "served")
        details = SimpleNamespace(method="/autoforex.task.v1.TaskService/GetHealth")
        wrapped = interceptor.intercept_service(
            lambda ignored: handler,
            cast(grpc.HandlerCallDetails, cast(Any, details)),
        )
        context = RecordingSecurityContext(b"operator")

        result = wrapped.unary_unary(  # type: ignore[union-attr]
            SimpleNamespace(request_id="request-1"),
            cast(grpc.ServicerContext, cast(Any, context)),
        )

        assert result == "served"
        assert context.aborted is None

    @pytest.mark.parametrize(
        ("common_name", "expected_code"),
        [
            (None, grpc.StatusCode.UNAUTHENTICATED),
            (b"reader", grpc.StatusCode.PERMISSION_DENIED),
        ],
    )
    def test_rejects_missing_or_unauthorized_principal(
        self,
        common_name: bytes | None,
        expected_code: grpc.StatusCode,
    ) -> None:
        interceptor = AuthorizationInterceptor(
            AuthorizationPolicy({"operator": (RpcPermission.HEALTH,)})
        )
        handler = grpc.unary_unary_rpc_method_handler(lambda request, context: "served")
        wrapped = interceptor.intercept_service(
            lambda ignored: handler,
            cast(
                grpc.HandlerCallDetails,
                cast(
                    Any,
                    SimpleNamespace(method="/autoforex.task.v1.TaskService/GetHealth"),
                ),
            ),
        )
        context = RecordingSecurityContext(common_name)

        with pytest.raises(PermissionError):
            wrapped.unary_unary(  # type: ignore[union-attr]
                SimpleNamespace(),
                cast(grpc.ServicerContext, cast(Any, context)),
            )

        assert context.aborted is not None
        assert context.aborted[0] == expected_code


class TestGrpcServerSecurity:
    def test_plaintext_has_no_credentials_or_interceptors(self) -> None:
        security = GrpcServerSecurity(ServerSettings())

        assert not security.secure
        assert security.credentials() is None
        assert security.interceptors() == ()

    def test_mtls_reads_all_material_and_requires_client_authentication(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        certificate = tmp_path / "server.crt"
        private_key = tmp_path / "server.key"
        client_ca = tmp_path / "clients.crt"
        certificate.write_bytes(b"certificate")
        private_key.write_bytes(b"private-key")
        client_ca.write_bytes(b"client-ca")
        captured: dict[str, Any] = {}
        credentials = object()

        def create_credentials(*args: Any, **kwargs: Any) -> object:
            captured.update(args=args, kwargs=kwargs)
            return credentials

        monkeypatch.setattr(
            security_module.grpc,
            "ssl_server_credentials",
            create_credentials,
        )
        security = GrpcServerSecurity(
            ServerSettings(
                transport_security=TransportSecurityMode.MTLS,
                tls_certificate_path=certificate,
                tls_private_key_path=private_key,
                tls_client_ca_path=client_ca,
                authorization_rules={"operator": ("server.health",)},
            )
        )

        result = security.credentials()

        assert result is credentials
        assert captured["args"][0] == ((b"private-key", b"certificate"),)
        assert captured["kwargs"]["root_certificates"] == b"client-ca"
        assert captured["kwargs"]["require_client_auth"]
        assert len(security.interceptors()) == 1
