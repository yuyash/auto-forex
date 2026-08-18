"""FastAPI service package for AutoForexV2."""

from api._version import __version__
from api.main import app, main

__all__ = ["__version__", "app", "main"]
