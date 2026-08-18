"""Snowball trading strategy package for AutoForexV2."""

from importlib.metadata import version

from autoforex.snowball.config import SnowballConfig
from autoforex.snowball.strategy import SnowballStrategy

__all__ = ["SnowballConfig", "SnowballStrategy", "__version__"]

__version__ = version("auto-forex-snowball")
