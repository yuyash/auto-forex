"""Enums for market models.

This module contains enum definitions for:
- ApiType: OANDA API endpoint type (practice/live)
- Jurisdiction: Regulatory jurisdiction for an OANDA account
"""

from django.db import models


class ApiType(models.TextChoices):
    """OANDA API endpoint type."""

    PRACTICE = "practice", "Practice"
    LIVE = "live", "Live"


class Jurisdiction(models.TextChoices):
    """Regulatory jurisdiction for an OANDA account."""

    US = "US", "United States"
    JP = "JP", "Japan"
    OTHER = "OTHER", "Other/International"


class MarketEventSeverity(models.TextChoices):
    """Severity levels for MarketEvent records."""

    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"


class MarketEventCategory(models.TextChoices):
    """Categories for MarketEvent records."""

    MARKET = "market", "Market"
    TRADING = "trading", "Trading"
    SECURITY = "security", "Security"


class MarketEventType(models.TextChoices):
    """Known event types emitted by the market app."""

    COMPLIANCE_VIOLATION = "compliance_violation", "Compliance Violation"
    TICK_STREAM_STARTED = "tick_stream_started", "Tick Stream Started"
    TICK_STREAM_RETRY = "tick_stream_retry", "Tick Stream Retry"
    TICK_STREAM_STOPPED = "tick_stream_stopped", "Tick Stream Stopped"
    ORDER_FAILED = "order_failed", "Order Failed"
    ORDER_SUBMITTED = "order_submitted", "Order Submitted"
    ORDER_REJECTED = "order_rejected", "Order Rejected"
    ORDER_CANCELLED = "order_cancelled", "Order Cancelled"
