"""AWS adapters for AutoForexV2."""

from importlib.metadata import version

from autoforex.aws.athena import AthenaDataSource, AthenaDataSourceError, AthenaSettings
from autoforex.aws.dynamodb import DynamoDbDocument, DynamoDbFenceError, DynamoDbTaskStore
from autoforex.aws.metrics import CloudWatchMetricStore

__all__ = [
    "AthenaDataSource",
    "AthenaDataSourceError",
    "AthenaSettings",
    "CloudWatchMetricStore",
    "DynamoDbDocument",
    "DynamoDbFenceError",
    "DynamoDbTaskStore",
    "__version__",
]

__version__ = version("auto-forex-aws")
