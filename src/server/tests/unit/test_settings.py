from __future__ import annotations

from pathlib import Path

import pytest

from autoforex.server.settings import (
    PersistenceBackend,
    ServerSettings,
    ServiceDiscoveryBackend,
    TransportSecurityMode,
)


class TestServerSettings:
    def test_defaults_to_local_sqlite(self) -> None:
        settings = ServerSettings()

        assert settings.persistence_backend == PersistenceBackend.SQLITE
        assert settings.host == "127.0.0.1"
        assert settings.port == 50051

    def test_rejects_backend_url_mismatch(self) -> None:
        with pytest.raises(ValueError, match="PostgreSQL"):
            ServerSettings(
                persistence_backend=PersistenceBackend.POSTGRESQL,
                database_url="sqlite:///tasks.db",
            )

    def test_rejects_plaintext_on_non_loopback_by_default(self) -> None:
        with pytest.raises(ValueError, match="loopback"):
            ServerSettings(host="0.0.0.0")

    def test_requires_complete_mtls_configuration(self) -> None:
        with pytest.raises(ValueError, match="client CA"):
            ServerSettings(
                transport_security=TransportSecurityMode.MTLS,
                tls_certificate_path=Path("server.crt"),
                tls_private_key_path=Path("server.key"),
                authorization_rules={"operator": ("server.health",)},
            )

    def test_rejects_lease_renewal_at_or_after_expiry(self) -> None:
        with pytest.raises(ValueError, match="lease_renewal_seconds"):
            ServerSettings(
                lease_duration_seconds=10,
                lease_renewal_seconds=10,
            )

    def test_requires_an_advertised_host_for_wildcard_discovery(self) -> None:
        with pytest.raises(ValueError, match="advertised_host"):
            ServerSettings(
                host="0.0.0.0",
                allow_plaintext_non_loopback=True,
                service_discovery_enabled=True,
            )

    def test_requires_complete_cloud_map_configuration(self) -> None:
        with pytest.raises(ValueError, match="cloud_map_service_id"):
            ServerSettings(
                service_discovery_enabled=True,
                service_discovery_backend=ServiceDiscoveryBackend.AWS_CLOUD_MAP,
            )

    def test_requires_discovery_ttl_to_exceed_heartbeat_interval(self) -> None:
        with pytest.raises(ValueError, match="service_discovery_ttl_seconds"):
            ServerSettings(
                service_discovery_heartbeat_interval_seconds=10,
                service_discovery_ttl_seconds=10,
            )
