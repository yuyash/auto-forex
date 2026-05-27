"""Integration tests for backtest tick query helpers."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.market.models import TickData
from apps.market.services.backtest_ticks import iter_raw_backtest_ticks


@pytest.mark.django_db
def test_iter_raw_backtest_ticks_uses_bounded_keyset_batches() -> None:
    """Raw replay should not issue one full-period result-set query."""
    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=4)

    TickData.objects.create(
        instrument="USD_JPY",
        timestamp=start - timedelta(seconds=1),
        bid=Decimal("149.99000"),
        ask=Decimal("150.01000"),
        mid=Decimal("150.00000"),
    )
    TickData.objects.create(
        instrument="EUR_USD",
        timestamp=start,
        bid=Decimal("1.10000"),
        ask=Decimal("1.10020"),
        mid=Decimal("1.10010"),
    )
    for offset in range(5):
        bid = Decimal("150.00000") + Decimal(offset) / Decimal("100")
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=start + timedelta(seconds=offset),
            bid=bid,
            ask=bid + Decimal("0.02000"),
            mid=bid + Decimal("0.01000"),
        )

    with CaptureQueriesContext(connection) as captured:
        rows = list(
            iter_raw_backtest_ticks(
                instrument="USD_JPY",
                start_dt=start,
                end_dt=end,
                batch_size=2,
            )
        )

    assert [row.timestamp for row in rows] == [start + timedelta(seconds=i) for i in range(5)]
    select_queries = [query["sql"] for query in captured if "SELECT" in query["sql"].upper()]
    assert len(select_queries) == 3
    assert all("LIMIT 2" in query.upper() for query in select_queries)
