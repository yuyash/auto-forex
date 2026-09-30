# API plan

The HTTP API will expose one Python Lambda function per operation through API Gateway. Route integration, authentication, authorization, AWS SDK calls, and broker calls are not implemented yet. Public paths and operation names use provider-neutral terms.

In these routes, `accountId` identifies a broker account registered with the application, not an AWS account. Administrative permissions, account ownership checks, and the scope of self-service operations must be defined before implementation.

## Planned routes

| HTTP method and proposed path | Operation | Purpose and main inputs | Data source and open decisions |
| --- | --- | --- | --- |
| `POST /users/signup` | `sign_up_user` | User self-registration | Cognito. Registration confirmation and verification flows remain to be defined. |
| `POST /users` | `create_user` | Administrative user creation | Cognito. Requires defined administrative permissions. |
| `GET /users` | `list_users` | List users with pagination | Cognito. Administrative visibility and returned attributes remain to be defined. |
| `DELETE /users/{userId}` | `delete_user` | Delete a user | Cognito. Handling of associated account registrations, settings, and credentials is unresolved. |
| `POST /broker-accounts` | `register_broker_account` | Register an existing broker account and associate its credentials with a user | Users belong in Cognito. Account metadata and credential storage are unresolved. |
| `GET /broker-accounts` | `list_broker_accounts` | List accounts registered with the application | Account registration records. Responses must exclude credential values. |
| `DELETE /broker-accounts/{accountId}` | `delete_broker_account` | Remove an account registration from the application | Account registration records and related settings. This operation does not close the external broker account. |
| `GET /broker-accounts/{accountId}/settings` | `get_broker_settings` | Retrieve stream symbols and frequency settings | AWS Config is the planned integration boundary; the storage representation and read/write mechanism are unresolved. |
| `PUT /broker-accounts/{accountId}/settings` | `update_broker_settings` | Save stream symbols and frequency settings | Same storage boundary. Sampling, aggregation, and connection cadence must be distinguished. |
| `GET /broker-accounts/{accountId}/candles` | `get_candles` | Retrieve candles using `symbol`, `from`, `to`, and `granularity` | Broker API. Supported granularities, time boundaries, and request partitioning remain to be defined. |
| `GET /broker-accounts/{accountId}/ticks` | `get_ticks` | Retrieve ticks using `symbol`, `from`, and `to` | Historical tick source is unresolved. Arbitrary historical ranges are not assumed to be available through the public v20 API. |
| `GET /broker-accounts/{accountId}` | `get_broker_account` | Retrieve account details, including balance information | Broker API. |
| `GET /broker-accounts/{accountId}/positions` | `list_positions` | Retrieve account positions | Broker API. |
| `GET /broker-accounts/{accountId}/trades` | `list_trades` | Retrieve account trades | Broker API. |
| `GET /results` | `list_results` | List persisted execution results with filtering and pagination | DynamoDB. Ownership checks, keys, and supported queries remain to be defined. |
| `GET /results/{resultId}` | `get_result` | Retrieve one persisted execution result | DynamoDB. Requires an ownership check. |

Broker account registration associates an account that already exists at a broker with an application user. Whether credentials are accepted during user signup or broker account registration, and which information belongs in Cognito, remains unresolved. See [Open application decisions](architecture.md#open-application-decisions) for storage boundaries and alternatives.

## Market-data semantics

OANDA candle requests support `from`, `to`, and `granularity`. The smallest published candle granularity is `S5` (five seconds); candles and ticks are distinct data types. Request partitioning for larger ranges remains to be designed. See the [Pricing API](https://developer.oanda.com/rest-live-v20/pricing-ep/) and [granularity definitions](https://developer.oanda.com/rest-live-v20/instrument-df/).

The tick route reserves an application interface. Its implementation depends on a confirmed historical data source or an application-owned archive of received prices. The current-price API's `since` parameter must not be treated as replay of arbitrary historical ticks.

## Asynchronous processing

Two additional Lambda modules sit outside the HTTP API:

- `handlers/stream_ingestion.py`: consume a broker price stream and publish normalized price events to SQS.
- `handlers/trade_execution.py`: consume SQS events, execute trades through the broker interface, and persist execution results in DynamoDB.

These modules currently contain responsibility descriptions only. Trading rules, order sizing, idempotency, retry behavior, and stream handover must be implemented before either workflow can run.

See the [architecture](architecture.md) for infrastructure boundaries and the [deployment guide](deployment.md) for the implemented account and pipeline setup.
