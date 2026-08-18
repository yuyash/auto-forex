# auto-forex-server

`auto-forex-server` is a long-running gRPC service for starting, supervising,
recovering, and inspecting AutoForex backtest and live-trading tasks. It
combines Core execution, protobuf contracts, registered strategies, market
data sources, providers, durable persistence, and transport security.

The distribution is installed as `auto-forex-server` and imported as
`autoforex.server`.

> **Project status:** Alpha. Use practice accounts and isolated infrastructure
> until persistence, recovery, security, and operational procedures have been
> validated for the deployment.

## Requirements

- Python 3.14 or newer
- A writable SQLite location for the default single-host configuration
- PostgreSQL or DynamoDB for multi-host deployments
- TLS certificates and client authorization rules for remote production access

## Installation

The base installation includes Core, protobuf contracts, and Snowball:

```bash
pip install auto-forex-server
```

AWS, OANDA, and PostgreSQL support are explicit extras:

| Extra | Installs | Required when |
| --- | --- | --- |
| `aws` | `auto-forex-aws` | DynamoDB persistence or Athena data |
| `oanda` | `auto-forex-oanda` | OANDA provider |
| `postgresql` | `psycopg[binary]` | PostgreSQL persistence |
| `all` | All optional dependencies | Full deployment |

```bash
pip install "auto-forex-server[aws]"
pip install "auto-forex-server[oanda]"
pip install "auto-forex-server[postgresql]"
pip install "auto-forex-server[all]"
```

Optional dependencies are loaded only when their feature is configured. A
missing extra raises `OptionalDependencyError` with the exact installation
command, for example:

```text
OANDA provider support requires the optional 'oanda' dependencies; install them with `pip install "auto-forex-server[oanda]"`
```

## Quick start

The default configuration binds a plaintext listener to loopback and stores
state in `auto-forex-server.db`. It is installed inside the Python package and
is used when no external configuration is selected:

```bash
auto-forex-server
```

Generate an editable copy, validate it, and start the server:

```bash
auto-forex-server-config init --target auto-forex-server.yaml
auto-forex-server-config validate --config auto-forex-server.yaml
auto-forex-server --config auto-forex-server.yaml
```

Check the service with the protobuf client:

```python
import grpc

from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from autoforex.protobuf.task.v1 import task_service_pb2_grpc as task_grpc

with grpc.insecure_channel("127.0.0.1:50051") as channel:
    client = task_grpc.TaskServiceStub(channel)
    print(client.GetHealth(task_pb.GetHealthRequest(), timeout=5).status)
```

Plaintext access is intentionally restricted to loopback by default.

## Responsibilities

The server owns:

- durable task snapshots and component bindings;
- idempotent task submission and lifecycle control;
- backtest and live-trading worker supervision;
- automatic task recovery after process or host failure;
- distributed ownership leases and fencing tokens;
- persistence-backed or AWS Cloud Map service discovery;
- a durable broker execution journal and provider reconciliation;
- gRPC TLS/mTLS, authorization, and audit logging;
- schema migration, health reporting, and OS service templates.

RPC clients select explicitly registered component names. They cannot load
arbitrary Python classes or send provider credentials through gRPC.

## Configuration

The server combines three configuration sources. Later sources have higher
precedence:

1. the selected YAML file, or the packaged default YAML;
2. the selected `.env` file;
3. process environment variables.

Select files with command-line options:

```bash
auto-forex-server \
  --config /etc/autoforex/server.yaml \
  --env-file /etc/autoforex/server.env
```

The equivalent selector variables are
`AUTO_FOREX_SERVER_CONFIG_FILE` and `AUTO_FOREX_SERVER_ENV_FILE`. The default
environment file is `.env`.

Python wheels cannot safely create a mutable file in an arbitrary system
directory during installation. The wheel therefore installs an immutable
default YAML resource, and the configuration command materializes a copy at an
explicit location:

```bash
auto-forex-server-config init --target /etc/autoforex/server.yaml
```

The command creates parent directories, writes atomically, and refuses to
replace an existing file unless `--overwrite` is supplied.

### Environment references

Any YAML string can reference an environment variable:

```yaml
database_url: "postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST:-localhost}/autoforex"
tls_private_key_path: "${AUTOFOREX_TLS_PRIVATE_KEY}"
```

- `${NAME}` requires a non-missing variable.
- `${NAME:-fallback}` uses the fallback when the variable is missing or empty.
- References are resolved recursively in mappings and lists.
- Values from the selected `.env` file are available to references.
- Process environment values take precedence over `.env` values.

Keep credentials out of YAML and source control. Place them in the process
environment, a permission-restricted `.env` file, or the deployment platform's
secret manager.

Duplicate YAML keys, unknown top-level settings, missing required environment
references, and invalid values fail before persistence or the gRPC listener is
started. Validate deployment configuration independently with:

```bash
auto-forex-server-config validate \
  --config /etc/autoforex/server.yaml \
  --env-file /etc/autoforex/server.env
```

All settings can also be overridden with variables prefixed by
`AUTO_FOREX_SERVER_`. Nested environment values use `__` as the delimiter.

### Listener and workers

| YAML key | Environment override | Default | Meaning |
| --- | --- | --- | --- |
| `host` | `AUTO_FOREX_SERVER_HOST` | `127.0.0.1` | Listener host |
| `port` | `AUTO_FOREX_SERVER_PORT` | `50051` | Listener port |
| `grpc_workers` | `AUTO_FOREX_SERVER_GRPC_WORKERS` | `8` | gRPC worker threads |
| `task_workers` | `AUTO_FOREX_SERVER_TASK_WORKERS` | `4` | Task execution workers |
| `shutdown_grace_seconds` | `AUTO_FOREX_SERVER_SHUTDOWN_GRACE_SECONDS` | `10` | Graceful gRPC shutdown |

### Ownership and reconciliation

| YAML key | Default |
| --- | --- |
| `heartbeat_interval_seconds` | `5` |
| `lease_duration_seconds` | `30` |
| `lease_renewal_seconds` | `10` |
| `reconciliation_interval_seconds` | `1` |

Lease renewal must be shorter than lease duration.

### Registered components

Snowball is registered as the `snowball` strategy by default. Configure CSV,
OANDA, and Athena components with:

```yaml
csv_data_sources:
  history:
    tick_paths:
      - "${MARKET_DATA_ROOT}/USDJPY.csv"
    encoding: "utf-8"

enable_oanda: true
oanda_provider_name: "oanda"

enable_athena: true
athena_data_source_name: "athena"
```

Keep provider-specific values in the environment:

```env
MARKET_DATA_ROOT=/data
OANDA_ACCOUNT_ID=001-001-1234567-001
OANDA_ACCESS_TOKEN=replace-with-a-secret
OANDA_ENVIRONMENT=practice
AWS_ATHENA_OUTPUT_BUCKET=my-athena-results
```

The required OANDA and AWS packages are validated at startup when enabled.
Provider credentials and Athena settings are validated when their configured
components are constructed.

## Persistence

### SQLite

SQLite is the default and is intended for one active server process:

```yaml
persistence_backend: "sqlite"
database_url: "sqlite:///auto-forex-server.db"
```

### PostgreSQL

Install `auto-forex-server[postgresql]`:

```yaml
persistence_backend: "postgresql"
database_url: "postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST:-localhost}/autoforex"
```

### DynamoDB

Install `auto-forex-server[aws]`:

```yaml
persistence_backend: "dynamodb"
dynamodb_table_name: "auto-forex-server"
dynamodb_region_name: "us-west-2"
```

Optional DynamoDB settings include endpoint URL, consistent reads, and
point-in-time recovery.

Schema migrations run before task recovery and listener startup. The server
refuses to open a schema newer than the running binary.

## Service discovery

Service discovery is opt-in. Each enabled server registers its stable
process-level `instance_id`, advertised gRPC endpoint, transport mode, package
version, capabilities, metadata, and heartbeat expiration.

The persistence registry is recommended when all instances already share
PostgreSQL or DynamoDB:

```yaml
host: "0.0.0.0"
allow_plaintext_non_loopback: true

service_discovery_enabled: true
service_discovery_backend: "persistence"
service_discovery_advertised_host: "${SERVER_PRIVATE_IP}"
service_discovery_heartbeat_interval_seconds: 5
service_discovery_ttl_seconds: 20
service_discovery_capabilities:
  - "task-service-v1"
service_discovery_metadata:
  region: "${DEPLOYMENT_REGION}"
  zone: "${DEPLOYMENT_ZONE}"
```

With SQLite, the registry is local to one server and therefore does not form a
multi-host discovery plane. PostgreSQL and DynamoDB registrations are shared
by every server using the same database or table.

AWS Cloud Map is available through the `aws` extra:

```bash
pip install "auto-forex-server[aws]"
```

```yaml
service_discovery_enabled: true
service_discovery_backend: "aws_cloud_map"
service_discovery_advertised_host: "${SERVER_PRIVATE_IP}"
service_discovery_heartbeat_interval_seconds: 5
service_discovery_ttl_seconds: 20

cloud_map_service_id: "${CLOUD_MAP_SERVICE_ID}"
cloud_map_namespace_name: "internal.example"
cloud_map_service_name: "autoforex-server"
cloud_map_region_name: "us-west-2"
```

For Cloud Map DNS namespaces, advertise an IP address accepted by the
configured Cloud Map service. Custom metadata and expiration timestamps are
stored as instance attributes. Clean shutdown deregisters immediately;
instances left by process or host failure are excluded after their advertised
TTL.

Discover live instances through gRPC:

```python
response = client.ListServerInstances(task_pb.ListServerInstancesRequest())
for instance in response.instances:
    print(instance.instance_id, instance.host, instance.port)
```

`ListServerInstances` provides endpoint discovery, not traffic distribution.
Use client-side selection or a load balancer such as a Kubernetes Service,
HAProxy, or a cloud load balancer for routing and connection retry.

When the listener binds `0.0.0.0` or `::`, an explicit
`service_discovery_advertised_host` is required. Plaintext non-loopback
listeners also require `allow_plaintext_non_loopback: true`; use a private,
trusted network when TLS is disabled.

## gRPC API

`autoforex.task.v1.TaskService` exposes:

- `GetHealth`
- `ListServerInstances`
- `StartBacktest`
- `StartTrading`
- `GetTask`
- `ListTasks`
- `PauseTask`
- `ResumeTask`
- `StopTask`
- `RestartTask`
- `RecoverTask`

Start requests require a client-generated UUID `request_id`. Retrying the same
payload with the same ID returns the existing task. Reusing an ID for a
different payload returns `ALREADY_EXISTS`.

Task responses contain both:

- observed Core `status`;
- durable `execution_disposition`, including `recovery_required`.

`RestartTask` begins a fresh run. `RecoverTask` continues the same run after
provider reconciliation; the operations are intentionally different.

## Recovery and distributed ownership

Task definitions, snapshots, requested execution state, and component bindings
are persisted separately. A desired-running task is automatically recovered:

- backtests continue strictly after the durable tick checkpoint;
- trading tasks restore strategy state and reconnect provider streams;
- reconnect snapshots already covered by the checkpoint are discarded;
- task ID and run count are retained.

Each active task has one expiring ownership lease. Writes carry a monotonically
increasing fencing token. With PostgreSQL or DynamoDB:

- only the current lease owner executes a task;
- control requests received by another instance are persisted for the owner;
- a standby instance can take over an expired or released task;
- a stale owner cannot commit checkpoints after takeover.

## Broker execution safety

Broker mutations use a durable write-ahead journal:

1. Store a stable command identity and provider cursor.
2. Dispatch the mutation.
3. Record acknowledgement and strategy application.
4. Commit the task checkpoint.

After interruption, the adapter reconciles the command before any retry.
Ambiguous mutations are not blindly resubmitted; the task enters
`recovery_required`.

This provides effectively-once behavior around an external API, not
transactional exactly-once semantics.

## TLS and authorization

Binding plaintext to a non-loopback address is rejected unless
`allow_plaintext_non_loopback: true` is explicitly set.

TLS:

```yaml
host: "0.0.0.0"
transport_security: "tls"
tls_certificate_path: "/etc/autoforex/server.crt"
tls_private_key_path: "${AUTOFOREX_TLS_PRIVATE_KEY}"
```

mTLS:

```yaml
host: "0.0.0.0"
transport_security: "mtls"
tls_certificate_path: "/etc/autoforex/server.crt"
tls_private_key_path: "${AUTOFOREX_TLS_PRIVATE_KEY}"
tls_client_ca_path: "/etc/autoforex/client-ca.crt"
authorization_rules:
  operator:
    - "*"
  reader:
    - "server.health"
    - "server.discovery"
    - "tasks.read"
```

Stable permission names are:

- `server.health`
- `server.discovery`
- `tasks.read`
- `backtests.execute`
- `trading.execute`
- `tasks.control`

Authorization logs include the certificate principal, permission, RPC method,
peer, request ID, task ID, and result. On Unix platforms, `SIGHUP` reloads
certificate files through graceful listener replacement.

## Health and shutdown

`GetHealth` reports `UNAVAILABLE` when persistence, the execution journal, or
background ownership/reconciliation workers are unhealthy.

`SIGINT` and `SIGTERM` perform graceful shutdown. Desired-running state is
preserved so another instance or a restarted process can recover the task.

## OS service definitions

Templates are included for systemd, launchd, and WinSW.

Render a definition:

```bash
auto-forex-server-service render \
  --platform systemd \
  --executable /opt/autoforex/bin/auto-forex-server \
  --configuration-file /etc/autoforex/server.yaml \
  --environment-file /etc/autoforex/server.env
```

Install to an explicit path:

```bash
auto-forex-server-service install \
  --platform systemd \
  --executable /opt/autoforex/bin/auto-forex-server \
  --configuration-file /etc/autoforex/server.yaml \
  --environment-file /etc/autoforex/server.env \
  --target /etc/systemd/system/auto-forex-server.service
```

The command does not escalate privileges and refuses to overwrite an existing
file unless `--overwrite` is supplied.

## Operational checklist

Before remote or live deployment:

- use TLS or mTLS and restrict network access;
- store provider tokens outside source control;
- use OANDA practice and trading `dry_run` during validation;
- choose PostgreSQL or DynamoDB for multi-host operation;
- configure an advertised endpoint and load-balancing strategy for clusters;
- test backup, restore, failover, and `RecoverTask`;
- monitor health, task failures, lease renewal, and broker reconciliation;
- keep client and server protobuf versions compatible.

## Development

From `src/server` in the repository:

```bash
uv sync
uv sync --extra aws
uv sync --extra oanda
uv sync --extra postgresql
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Required CI jobs also exercise PostgreSQL and DynamoDB Local persistence,
process restart, package builds, and isolated wheel installations.
