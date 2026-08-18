# Core LLD Sequence Diagrams

The diagrams are grouped by workflow and split into focused execution cases.

## Task Creation

1. [Manager initialization](task_creation/manager_initialization.mmd)
2. [Start a backtest](task_creation/backtest.mmd)
3. [Start live trading](task_creation/trading.mmd)
4. [Launch a runner](task_creation/runner_launch.mmd)

## Task Execution

1. [Wait without progress reporting](task_execution/wait_without_progress.mmd)
2. [Wait with progress reporting](task_execution/wait_with_progress.mmd)
3. [Task context ownership hierarchy](task_execution/context_hierarchy.mmd)
4. [Start a runner](task_execution/runner_start.mmd)
5. [Manage strategy subscriber lifecycle](task_execution/strategy_subscriptions.mmd)
6. [Continue tick processing](task_execution/tick_continues.mmd)
7. [Pause requested](task_execution/pause_requested.mmd)
8. [Stop requested](task_execution/stop_requested.mmd)
9. [Complete a tick stream](task_execution/stream_completion.mmd)
10. [Handle a runner failure](task_execution/failure.mmd)
11. [Finalize profiling](task_execution/profiling.mmd)
12. [Monitor strategy request timeouts](task_execution/timeout_monitor.mmd)

## Tick Processing

1. [Pause requested](tick_processing/pause_requested.mmd)
2. [Stop requested](tick_processing/stop_requested.mmd)
3. [Strategy returns no events](tick_processing/no_events.mmd)
4. [Strategy returns events](tick_processing/strategy_events.mmd)
5. [Publish event requests](tick_processing/request_publication.mmd)
6. [Execute HOLD](tick_processing/execute_hold.mmd)
7. [Execute OPEN_TRADE](tick_processing/execute_open_trade.mmd)
8. [Execute CLOSE_TRADE by logical trade ID](tick_processing/execute_close_trade.mmd)
9. [Execute CLOSE_TRADE by position](tick_processing/execute_close_position.mmd)
10. [Handle execution errors](tick_processing/execution_error.mmd)
11. [Process execution responses](tick_processing/response_processing.mmd)

## Result Persistence

1. [Record a strategy event](result_persistence/event_recording.mmd)
2. [Record a filled OPEN_TRADE](result_persistence/open_trade.mmd)
3. [Record a filled CLOSE_TRADE](result_persistence/close_trade.mmd)
4. [Flush buffered results](result_persistence/batch_flush.mmd)
5. [Finalize a terminal task](result_persistence/task_completion.mmd)
6. [Store backend semantics](result_persistence/store_backends.mmd)

## Profit Metrics

1. [Check whether a metric is due](metrics/due_check.mmd)
2. [Calculate a metric](metrics/calculation.mmd)
3. [Persist a metric](metrics/persistence.mmd)
4. [Clean up a finished task](metrics/cleanup.mmd)
