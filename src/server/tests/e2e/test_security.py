from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import grpc
import pytest
from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from autoforex.protobuf.task.v1 import task_service_pb2_grpc as task_grpc

from autoforex.server.composition import ServerApplication
from autoforex.server.process import ServerProcess
from autoforex.server.settings import ServerSettings, TransportSecurityMode


class CertificateAuthority:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.ca_key = directory / "ca.key"
        self.ca_certificate = directory / "ca.crt"

    def create(self) -> None:
        self._run(
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(self.ca_key),
            "-out",
            str(self.ca_certificate),
            "-subj",
            "/CN=AutoForex Test CA",
        )

    def issue(self, name: str, *, client: bool) -> tuple[Path, Path]:
        key = self.directory / f"{name}.key"
        request = self.directory / f"{name}.csr"
        certificate = self.directory / f"{name}.crt"
        extensions = self.directory / f"{name}.ext"
        self._run(
            "req",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(request),
            "-subj",
            f"/CN={name}",
        )
        extensions.write_text(
            (
                "extendedKeyUsage=clientAuth\n"
                if client
                else "subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n"
            ),
            encoding="ascii",
        )
        self._run(
            "x509",
            "-req",
            "-in",
            str(request),
            "-CA",
            str(self.ca_certificate),
            "-CAkey",
            str(self.ca_key),
            "-CAcreateserial",
            "-out",
            str(certificate),
            "-days",
            "1",
            "-sha256",
            "-extfile",
            str(extensions),
        )
        return certificate, key

    @staticmethod
    def _run(*arguments: str) -> None:
        subprocess.run(
            ("openssl", *arguments),
            check=True,
            capture_output=True,
            text=True,
        )


class TestMutualTlsE2E:
    def test_authenticates_certificates_and_authorizes_each_rpc(
        self,
        tmp_path: Path,
    ) -> None:
        if shutil.which("openssl") is None:
            pytest.skip("openssl is required for the mTLS E2E test")
        authority = CertificateAuthority(tmp_path)
        authority.create()
        server_certificate, server_key = authority.issue("localhost", client=False)
        operator_certificate, operator_key = authority.issue("operator", client=True)
        reader_certificate, reader_key = authority.issue("reader", client=True)
        application = ServerApplication.build(
            ServerSettings(
                port=0,
                database_url=f"sqlite:///{tmp_path / 'secure-server.db'}",
                transport_security=TransportSecurityMode.MTLS,
                tls_certificate_path=server_certificate,
                tls_private_key_path=server_key,
                tls_client_ca_path=authority.ca_certificate,
                authorization_rules={"operator": ("server.health",)},
                lease_renewal_seconds=0.1,
                lease_duration_seconds=1,
            )
        )
        process = ServerProcess.create(application)
        process.start()
        try:
            operator_channel = self._channel(
                process.grpc_server.address,
                authority.ca_certificate,
                operator_certificate,
                operator_key,
            )
            operator = task_grpc.TaskServiceStub(operator_channel)

            assert operator.GetHealth(task_pb.GetHealthRequest()).status == "serving"

            reader_channel = self._channel(
                process.grpc_server.address,
                authority.ca_certificate,
                reader_certificate,
                reader_key,
            )
            reader = task_grpc.TaskServiceStub(reader_channel)
            with pytest.raises(grpc.RpcError) as denied:
                reader.GetHealth(task_pb.GetHealthRequest())
            assert isinstance(denied.value, grpc.Call)
            assert denied.value.code() == grpc.StatusCode.PERMISSION_DENIED

            anonymous_credentials = grpc.ssl_channel_credentials(
                root_certificates=authority.ca_certificate.read_bytes()
            )
            anonymous_channel = grpc.secure_channel(
                process.grpc_server.address,
                anonymous_credentials,
            )
            anonymous = task_grpc.TaskServiceStub(anonymous_channel)
            with pytest.raises(grpc.RpcError) as unauthenticated:
                anonymous.GetHealth(task_pb.GetHealthRequest(), timeout=1)
            assert isinstance(unauthenticated.value, grpc.Call)
            assert unauthenticated.value.code() == grpc.StatusCode.UNAVAILABLE

            operator_channel.close()
            reader_channel.close()
            anonymous_channel.close()
        finally:
            process.stop()

    @staticmethod
    def _channel(
        address: str,
        ca_certificate: Path,
        certificate: Path,
        private_key: Path,
    ) -> grpc.Channel:
        credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_certificate.read_bytes(),
            private_key=private_key.read_bytes(),
            certificate_chain=certificate.read_bytes(),
        )
        return grpc.secure_channel(address, credentials)
