# auto-forex-aws

`auto-forex-aws` provides AWS adapters for AutoForex:

- Athena and S3-backed historical forex market data;
- DynamoDB task and document persistence;
- CloudWatch publication for Core profit metrics.

The distribution is installed as `auto-forex-aws` and imported as
`autoforex.aws`.

> **Project status:** Alpha. Validate schemas, IAM permissions, cost controls,
> backups, and recovery procedures before production use.

## Requirements

- Python 3.14 or newer
- AWS credentials available through the standard boto3 credential chain
- IAM permissions for the services used by the selected adapter

## Installation

Install the adapter directly:

```bash
pip install auto-forex-aws
```

Or install it as an optional server feature:

```bash
pip install "auto-forex-server[aws]"
```

## Public components

| Component | Purpose |
| --- | --- |
| `AthenaDataSource` | Core `DataSource` backed by Athena query results in S3 |
| `AthenaSettings` | Environment-backed Athena configuration |
| `AthenaDataSourceError` | Invalid query or unsupported data-source behavior |
| `DynamoDbTaskStore` | Core `TaskRegistry` and versioned document store |
| `DynamoDbDocument` | Immutable document value written by the store |
| `DynamoDbFenceError` | Rejected write from a stale task owner |
| `CloudWatchMetricStore` | Publishes Core `ProfitMetric` values |

## AWS authentication

The package delegates credential loading to boto3. Common choices include:

- `AWS_PROFILE` for a local named profile;
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional session token;
- IAM roles for EC2, ECS, EKS, or other AWS runtimes;
- injected clients for tests and custom credential management.

Do not place long-lived credentials in source control or package metadata.

## Athena market data

### Quick start

```python
from datetime import UTC, datetime

from autoforex.aws import AthenaDataSource
from autoforex.core import CurrencyPair

source = AthenaDataSource.from_env()
try:
    ticks = source.ticks(
        instrument=CurrencyPair.of("USD_JPY"),
        start_at=datetime(2026, 7, 9, tzinfo=UTC),
        end_at=datetime(2026, 7, 9, 23, 59, 59, tzinfo=UTC),
    )
    for tick in ticks:
        print(tick.timestamp, tick.bid, tick.ask)
finally:
    source.close()
```

### Configuration

`AthenaSettings` reads the current directory's `.env` file and environment
variables. Configure the result bucket explicitly for each deployment.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `AWS_PROFILE` | boto3 default | Named local AWS profile |
| `AWS_REGION` | `us-west-2` | Athena and S3 region |
| `AWS_ACCOUNT_ID` | unset | Metadata attached to returned values |
| `AWS_ATHENA_DATABASE` | `forex_hist_data_db` | Athena database |
| `AWS_ATHENA_TABLE` | `quotes` | Tick table |
| `AWS_ATHENA_MINUTE_AGGS_TABLE` | `minute_aggs` | One-minute candle table |
| `AWS_ATHENA_DAY_AGGS_TABLE` | `day_aggs` | Daily candle table |
| `AWS_ATHENA_OUTPUT_BUCKET` | package default | Athena result bucket |
| `AWS_ATHENA_OUTPUT_PREFIX` | `athena-query-results/` | Result object prefix |
| `AWS_ATHENA_WORK_GROUP` | unset | Optional Athena workgroup |
| `AWS_ATHENA_POLL_INTERVAL_SECONDS` | `1` | Query polling interval |
| `AWS_ATHENA_TIMEOUT_SECONDS` | `300` | Query timeout |
| `AWS_ATHENA_QUERY_CHUNK_DAYS` | `1` | Tick query window size |
| `AWS_ATHENA_CANDLE_QUERY_CHUNK_DAYS` | `31` | Candle query window size |
| `AWS_ATHENA_QUERY_PREFETCH_MIN_WINDOWS` | `3` | Minimum prefetch depth |
| `AWS_ATHENA_QUERY_PREFETCH_MAX_WINDOWS` | `6` | Maximum prefetch depth |
| `AWS_ATHENA_QUERY_PREFETCH_WORKERS` | `4` | Background query workers |
| `AWS_ATHENA_QUERY_PREFETCH_WAIT_TARGET_SECONDS` | `0.5` | Prefetch latency target |

Settings may also be supplied directly:

```python
from autoforex.aws import AthenaDataSource, AthenaSettings

settings = AthenaSettings(
    region_name="us-west-2",
    database="forex",
    table="quotes",
    output_bucket="my-athena-results",
    work_group="primary",
)
source = AthenaDataSource(settings=settings)
```

### Expected Athena schema

The tick table must expose:

- `ticker`
- `bid_price`
- `ask_price`
- `participant_timestamp`
- string partitions `year`, `month`, and `day`

Ticker values use Polygon-style forex symbols such as `C:USD-JPY`.
`participant_timestamp` may be an epoch-nanosecond value or an ISO timestamp.

The minute and day aggregate tables must expose:

- `ticker`, `open`, `high`, `low`, `close`
- `window_start`
- optional `volume` and `transactions`
- string partitions `year`, `month`, and `day`

Only `CandleGranularity.MINUTE_1` and `CandleGranularity.DAY` are supported by
the Athena adapter.

### Query behavior

Bounded requests are split at UTC day boundaries. Results are streamed from
the Athena S3 output object and mapped into Core models. Future query windows
are prefetched in the background; the depth adapts to observed query and
consumer latency.

Use an Athena workgroup with query limits and lifecycle-expire result objects
in the configured S3 bucket to control cost.

## DynamoDB persistence

`DynamoDbTaskStore` implements Core's `TaskRegistry` and a generic versioned
JSON document store:

```python
from autoforex.aws import DynamoDbTaskStore

store = DynamoDbTaskStore.from_table_name(
    "auto-forex-server",
    region_name="us-west-2",
)
store.create_schema()
try:
    # Pass the store to Core or auto-forex-server persistence components.
    ...
finally:
    store.close()
```

The shared table uses:

- partition key: `namespace` (`S`);
- sort key: `key` (`S`);
- on-demand billing;
- server-side encryption;
- point-in-time recovery by default.

Provide `kms_key_arn` to use a customer-managed KMS key. Set
`consistent_reads=False` only when the deployment can tolerate eventually
consistent reads.

For DynamoDB Local:

```python
store = DynamoDbTaskStore.from_table_name(
    "auto-forex-test",
    region_name="us-west-2",
    endpoint_url="http://127.0.0.1:8000",
    enable_point_in_time_recovery=False,
)
```

Task writes can be fenced against server ownership metadata. A stale lease or
fencing token raises `DynamoDbFenceError` instead of committing an outdated
checkpoint.

## CloudWatch metrics

`CloudWatchMetricStore.save_metric()` publishes:

- realized, unrealized, and total profit/loss;
- open and closed trade counts;
- task ID, instrument, currency, configured dimensions, and approved metadata
  dimensions.

```python
from autoforex.aws import CloudWatchMetricStore

metrics = CloudWatchMetricStore(
    namespace="AutoForex/Production",
    dimensions={"Environment": "prod"},
)
```

The caller owns retry, buffering, and failure policy around CloudWatch
publication.

## IAM and operational guidance

Grant only the actions required by the selected component:

- Athena query execution and status APIs;
- read/write access to the configured Athena result prefix;
- S3 result object reads;
- DynamoDB table and backup APIs;
- CloudWatch `PutMetricData`.

Use separate roles and resources for development, backtesting, and production.
Review generated queries, table partitioning, encryption, retention, alarms,
and AWS charges before enabling continuous workloads.

## Development

From `src/aws` in the repository:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Live DynamoDB integration tests require the repository's documented test
environment variables and are skipped when no endpoint is configured.
