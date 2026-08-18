"""Environment-backed server process settings."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from autoforex.core import DomainModel
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PersistenceBackend(StrEnum):
    """Supported durable task-state backends."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    DYNAMODB = "dynamodb"


class TransportSecurityMode(StrEnum):
    """Supported gRPC transport-security modes."""

    PLAINTEXT = "plaintext"
    TLS = "tls"
    MTLS = "mtls"


class ServiceDiscoveryBackend(StrEnum):
    """Supported server instance registry backends."""

    PERSISTENCE = "persistence"
    AWS_CLOUD_MAP = "aws_cloud_map"


class CsvDataSourceSettings(DomainModel):
    """Configuration for one named CSV market-data source."""

    tick_paths: tuple[Path, ...] = ()
    candle_paths: tuple[Path, ...] = ()
    encoding: str = "utf-8"

    @model_validator(mode="after")
    def _require_paths(self) -> CsvDataSourceSettings:
        if not self.tick_paths and not self.candle_paths:
            raise ValueError("CSV data source requires tick_paths or candle_paths")
        return self


class ServerSettings(BaseSettings):
    """Configuration for the AutoForex gRPC daemon."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUTO_FOREX_SERVER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = Field(default=50051, ge=0, le=65535)
    grpc_workers: int = Field(default=8, ge=1)
    task_workers: int = Field(default=4, ge=1)
    shutdown_grace_seconds: float = Field(default=10.0, ge=0)
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0)
    lease_duration_seconds: float = Field(default=30.0, gt=0)
    lease_renewal_seconds: float = Field(default=10.0, gt=0)
    reconciliation_interval_seconds: float = Field(default=1.0, gt=0)

    service_discovery_enabled: bool = False
    service_discovery_backend: ServiceDiscoveryBackend = ServiceDiscoveryBackend.PERSISTENCE
    service_discovery_advertised_host: str | None = None
    service_discovery_heartbeat_interval_seconds: float = Field(default=5.0, gt=0)
    service_discovery_ttl_seconds: float = Field(default=20.0, gt=0)
    service_discovery_capabilities: tuple[str, ...] = ("task-service-v1",)
    service_discovery_metadata: dict[str, str] = Field(default_factory=dict)
    cloud_map_service_id: str | None = None
    cloud_map_namespace_name: str | None = None
    cloud_map_service_name: str | None = None
    cloud_map_region_name: str | None = None
    cloud_map_endpoint_url: str | None = None

    transport_security: TransportSecurityMode = TransportSecurityMode.PLAINTEXT
    tls_certificate_path: Path | None = None
    tls_private_key_path: Path | None = None
    tls_client_ca_path: Path | None = None
    allow_plaintext_non_loopback: bool = False
    authorization_rules: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    persistence_backend: PersistenceBackend = PersistenceBackend.SQLITE
    database_url: str = "sqlite:///auto-forex-server.db"
    database_echo: bool = False

    dynamodb_table_name: str = "auto-forex-server"
    dynamodb_region_name: str | None = None
    dynamodb_endpoint_url: str | None = None
    dynamodb_consistent_reads: bool = True
    dynamodb_enable_point_in_time_recovery: bool = True

    enable_oanda: bool = False
    oanda_provider_name: str = "oanda"
    enable_athena: bool = False
    athena_data_source_name: str = "athena"
    csv_data_sources: dict[str, CsvDataSourceSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_persistence(self) -> ServerSettings:
        if self.persistence_backend == PersistenceBackend.SQLITE:
            if not self.database_url.startswith("sqlite"):
                raise ValueError("SQLite backend requires a sqlite database_url")
        if self.persistence_backend == PersistenceBackend.POSTGRESQL:
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("PostgreSQL backend requires a postgresql database_url")
        if self.lease_renewal_seconds >= self.lease_duration_seconds:
            raise ValueError("lease_renewal_seconds must be less than lease_duration_seconds")
        if self.service_discovery_heartbeat_interval_seconds >= self.service_discovery_ttl_seconds:
            raise ValueError(
                "service_discovery_heartbeat_interval_seconds must be less than "
                "service_discovery_ttl_seconds"
            )
        if self.service_discovery_enabled:
            advertised_host = self.service_discovery_advertised_host or self.host
            if advertised_host in {"0.0.0.0", "::", "[::]"}:
                raise ValueError(
                    "service discovery requires service_discovery_advertised_host "
                    "when binding a wildcard host"
                )
        if self.service_discovery_backend == ServiceDiscoveryBackend.AWS_CLOUD_MAP:
            required_cloud_map_fields = {
                "cloud_map_service_id": self.cloud_map_service_id,
                "cloud_map_namespace_name": self.cloud_map_namespace_name,
                "cloud_map_service_name": self.cloud_map_service_name,
            }
            missing = [name for name, value in required_cloud_map_fields.items() if not value]
            if missing:
                raise ValueError("AWS Cloud Map service discovery requires: " + ", ".join(missing))
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        if (
            self.transport_security == TransportSecurityMode.PLAINTEXT
            and self.host not in loopback_hosts
            and not self.allow_plaintext_non_loopback
        ):
            raise ValueError("plaintext gRPC is restricted to loopback by default")
        if self.transport_security in {
            TransportSecurityMode.TLS,
            TransportSecurityMode.MTLS,
        }:
            if self.tls_certificate_path is None or self.tls_private_key_path is None:
                raise ValueError("TLS requires certificate and private-key paths")
        if self.transport_security == TransportSecurityMode.MTLS:
            if self.tls_client_ca_path is None:
                raise ValueError("mTLS requires a client CA path")
            if not self.authorization_rules:
                raise ValueError("mTLS requires explicit authorization_rules")
        return self
