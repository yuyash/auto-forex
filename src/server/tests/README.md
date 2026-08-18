# Server Test Strategy

The server test suite separates fast component behavior, composed behavior, and
user-visible process scenarios.

## Unit Tests

`tests/unit` verifies one server module at a time with in-memory collaborators.
Every handwritten module under `src/server` has a corresponding
`test_<module>.py` file. The architecture test enforces this convention.

Unit tests cover:

- value-object validation and serialization;
- task submission identity and fingerprinting;
- lease and fencing state transitions;
- execution-journal compare-and-swap behavior;
- SQL and DynamoDB adapter-specific error handling;
- dependency composition and settings selection;
- gRPC mapping, failure status, authentication, and authorization;
- process, service-manager, and command-line lifecycles.

Unit tests do not require network services.

## Integration Tests

`tests/integration` composes related classes around a real embedded SQLite
database or a configured external backend.

The durable persistence contract runs unchanged against:

- SQLite;
- PostgreSQL when `AUTO_FOREX_TEST_POSTGRESQL_URL` is set;
- DynamoDB or DynamoDB Local when
  `AUTO_FOREX_TEST_DYNAMODB_ENDPOINT_URL` is set.

The contract verifies task snapshots, immutable bindings, desired execution
state, optimistic concurrency, execution-journal indexing, checkpoint
filtering, and health checks.

Other integration scenarios verify:

- Core task execution through server-managed dependencies;
- lease exclusion, fencing, takeover, and remote control;
- crash recovery without duplicate broker submission;
- manual recovery for ambiguous broker outcomes;
- checkpoint and strategy-state restoration.

## End-to-End Tests

`tests/e2e` starts a real gRPC listener and exercises it through generated
protobuf clients.

Scenarios cover:

- idempotent task submission and conflicting request reuse;
- backtest process restart from the last durable checkpoint;
- live-trading restart with restored strategy state;
- the complete backtest lifecycle: health, start, pause, resume, complete,
  restart, get, and filtered list;
- user-triggered recovery of a review-required task without starting a new run;
- mTLS client authentication and method authorization;
- process restart through PostgreSQL and DynamoDB Local.

Shared fixtures provide representative market ticks, deterministic condition
waiting, persistence lifecycle management, and guaranteed process/channel
cleanup.

## External Backends

The GitHub Actions `server-backends` job starts PostgreSQL 17 and DynamoDB Local
2.6.1, waits for both services, and runs the persistence contracts, backend
restart scenarios, and AWS DynamoDB store integration tests.

For local execution:

```bash
docker run --rm --detach --name autoforex-postgresql-tests \
  -e POSTGRES_DB=autoforex \
  -e POSTGRES_USER=autoforex \
  -e POSTGRES_PASSWORD=autoforex \
  -p 55432:5432 postgres:17

docker run --rm --detach --name autoforex-dynamodb-tests \
  -p 58000:8000 amazon/dynamodb-local:2.6.1 \
  -jar DynamoDBLocal.jar -sharedDb -inMemory
```

Run the backend scenarios with:

```bash
AWS_ACCESS_KEY_ID=test \
AWS_SECRET_ACCESS_KEY=test \
AWS_DEFAULT_REGION=us-west-2 \
AUTO_FOREX_TEST_POSTGRESQL_URL=postgresql+psycopg://autoforex:autoforex@127.0.0.1:55432/autoforex \
AUTO_FOREX_TEST_DYNAMODB_ENDPOINT_URL=http://127.0.0.1:58000 \
uv run --directory src/server pytest \
  tests/integration/test_persistence_contract.py \
  tests/e2e/test_backend_restart.py
```

Tests skip an external backend only when its required environment variable is
absent. The dedicated CI job sets every required variable, so those scenarios
must execute there.
