from datetime import UTC, datetime

from apps.trading.services.metric_watermarks import update_watermarks


def test_margin_watermark_prefers_snowball_net_percentage_when_larger() -> None:
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    watermarks = update_watermarks(
        {},
        timestamp=timestamp,
        metrics={
            "margin_ratio": "0.0105",
            "snowball_net_margin_ratio_pct": "42",
        },
    )

    assert watermarks["margin_ratio_max"] == {
        "value": "0.42",
        "timestamp": timestamp.isoformat(),
        "source_metric": "snowball_net_margin_ratio_pct",
    }


def test_watermark_fallback_sources_keep_priority_order() -> None:
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    watermarks = update_watermarks(
        {},
        timestamp=timestamp,
        metrics={
            "realized_pnl_quote": "10",
            "realized_pnl": "1500",
        },
    )

    assert watermarks["realized_pnl_max"] == {
        "value": "10",
        "timestamp": timestamp.isoformat(),
        "source_metric": "realized_pnl_quote",
    }
