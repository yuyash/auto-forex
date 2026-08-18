"""Server package for AutoForexV2."""

from importlib.metadata import version

from autoforex.server.components import (
    BacktestTaskBinding,
    ComponentName,
    DataSourceReference,
    ProviderReference,
    StrategyReference,
    TradingTaskBinding,
)
from autoforex.server.composition import ServerApplication, ServerComponentCatalog
from autoforex.server.configuration import (
    ServerConfigurationError,
    load_server_settings,
    write_default_configuration,
)
from autoforex.server.discovery import (
    ServiceInstance,
    ServiceInstanceStatus,
    ServiceRegistry,
)
from autoforex.server.optional import OptionalDependencyError
from autoforex.server.providers import (
    ProviderFactory,
    ProviderName,
)
from autoforex.server.recovery import TaskExecutionDisposition
from autoforex.server.security import RpcPermission
from autoforex.server.settings import (
    PersistenceBackend,
    ServerSettings,
    ServiceDiscoveryBackend,
    TransportSecurityMode,
)
from autoforex.server.supervisor import TaskSupervisor

__all__ = [
    "BacktestTaskBinding",
    "ComponentName",
    "DataSourceReference",
    "OptionalDependencyError",
    "PersistenceBackend",
    "ProviderFactory",
    "ProviderName",
    "ProviderReference",
    "RpcPermission",
    "ServerApplication",
    "ServerComponentCatalog",
    "ServerConfigurationError",
    "ServerSettings",
    "ServiceDiscoveryBackend",
    "ServiceInstance",
    "ServiceInstanceStatus",
    "ServiceRegistry",
    "StrategyReference",
    "TaskExecutionDisposition",
    "TaskSupervisor",
    "TradingTaskBinding",
    "TransportSecurityMode",
    "__version__",
    "load_server_settings",
    "write_default_configuration",
]

__version__ = version("auto-forex-server")
