# auto-forex-protobuf

`auto-forex-protobuf` distributes the generated Python protobuf messages and
gRPC service bindings used by AutoForex clients and
`auto-forex-server`.

The distribution is installed as `auto-forex-protobuf` and imported from
`autoforex.protobuf`. The wire package is versioned as
`autoforex.task.v1`.

> **Project status:** Alpha. Treat incompatible message or service changes as
> protocol-breaking changes and introduce a new wire namespace.

## Requirements

- Python 3.14 or newer
- `protobuf` 6.x
- `grpcio` compatible with the version declared by the generated bindings

## Installation

```bash
pip install auto-forex-protobuf
```

The package is installed automatically with `auto-forex-server`.

## Imports

```python
from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from autoforex.protobuf.task.v1 import task_service_pb2_grpc as task_grpc
```

The generated modules are:

- `task_service_pb2`: messages, enums, and descriptors;
- `task_service_pb2_grpc`: client stub, server base class, and registration
  helpers.

Do not import the third-party `protobuf` distribution as an AutoForex module.

## Client example

```python
import grpc

from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from autoforex.protobuf.task.v1 import task_service_pb2_grpc as task_grpc

with grpc.insecure_channel("127.0.0.1:50051") as channel:
    client = task_grpc.TaskServiceStub(channel)
    response = client.GetHealth(task_pb.GetHealthRequest(), timeout=5)
    print(response.status)
```

Use `grpc.secure_channel()` and deployment-specific channel credentials for a
TLS or mTLS server.

## Task service

`autoforex.task.v1.TaskService` exposes:

| RPC | Purpose |
| --- | --- |
| `GetHealth` | Check server dependency and worker health |
| `ListServerInstances` | Discover live server endpoints and capabilities |
| `StartBacktest` | Start a historical backtest |
| `StartTrading` | Start a live or dry-run trading task |
| `GetTask` | Fetch one task |
| `ListTasks` | List tasks, optionally by observed status |
| `PauseTask` | Persist and apply a pause request |
| `ResumeTask` | Continue a paused task |
| `StopTask` | Persist and apply a stop request |
| `RestartTask` | Start a fresh run for an existing definition |
| `RecoverTask` | Reconcile and continue a recovery-required run |

## Important message semantics

### Service discovery

`ListServerInstances` returns registrations whose heartbeat TTL is still live.
Each `ServerInstance` contains its instance ID, advertised host and port,
transport-security mode, package version, heartbeat timestamps, capabilities,
and deployment metadata. Discovery supplies endpoints; clients or an external
load balancer remain responsible for connection selection and retry behavior.

### Idempotent starts

`StartBacktestRequest` and `StartTradingRequest` require a client-generated
UUID in `request_id`. Repeating the same ID with the same request returns the
original task. Reusing the ID for a different request is rejected by the
server.

### Status and execution disposition

`Task.status` is the observed Core task state. `Task.execution_disposition` is
the durable requested/recovery state retained across server restarts. Clients
should inspect both fields.

Execution dispositions include:

- running;
- paused;
- stopped;
- completed;
- failed;
- recovery required.

### Component references

RPC messages refer to registered components by name:

- `StrategyReference`
- `DataSourceReference`
- `ProviderReference`
- `AccountReference`

The server resolves these names from its configured registry. RPC requests
cannot provide arbitrary Python module or class names.

### Strategy parameters

`StrategyReference.parameters` is a `google.protobuf.Struct`. Keep values
JSON-compatible and validate them against the selected strategy before
starting long-running tasks.

## Compatibility policy

- Field numbers are permanent once published.
- Existing fields must not be repurposed.
- New optional fields and enum values should preserve old client behavior.
- Breaking service or message changes require a new namespace such as
  `autoforex.task.v2`.
- Clients should tolerate enum values introduced by newer servers.

## Regenerating bindings

Generated files are committed to the repository. Contributors regenerate them
from `src/protobuf` with:

```bash
uv sync
uv run python -m grpc_tools.protoc \
  -I proto \
  --python_out=src \
  --pyi_out=src \
  --grpc_python_out=src \
  proto/autoforex/protobuf/task/v1/task_service.proto
```

Never edit `task_service_pb2.py`, `task_service_pb2.pyi`, or
`task_service_pb2_grpc.py` manually.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

This package contains contracts only. Server implementation belongs in
`auto-forex-server`; client orchestration belongs in the consuming
application.
