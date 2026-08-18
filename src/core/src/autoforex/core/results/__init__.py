"""Task result aggregation and persistence APIs."""

from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.recorder import TaskResultRecorder
from autoforex.core.results.stores import (
    CsvResultStore,
    InMemoryResultStore,
    ProfitMetricStore,
    ResultBatch,
    ResultReader,
    ResultStore,
    SqlResultStore,
)

__all__ = [
    "CsvResultStore",
    "CycleSummary",
    "InMemoryResultStore",
    "ProfitMetric",
    "ProfitMetricStore",
    "ResultBatch",
    "ResultReader",
    "ResultStore",
    "SqlResultStore",
    "StrategyEventRecord",
    "TaskResultRecorder",
    "TaskSummary",
    "TradeSummary",
]
