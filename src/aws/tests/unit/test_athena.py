from __future__ import annotations

from threading import Lock
from typing import Any

import pytest
from autoforex.core.models import CurrencyPair
from autoforex.core.sources import CandleGranularity

from autoforex.aws import AthenaDataSource, AthenaDataSourceError, AthenaSettings


class FakeAthenaClient:
    def __init__(self) -> None:
        self.started: dict[str, Any] | None = None
        self.started_queries: list[dict[str, Any]] = []
        self._lock = Lock()

    def start_query_execution(self, **kwargs: Any) -> dict[str, str]:
        with self._lock:
            self.started = kwargs
            self.started_queries.append(kwargs)
            execution_id = f"query-{len(self.started_queries)}"
        return {"QueryExecutionId": execution_id}

    def get_query_execution(self, *, QueryExecutionId: str) -> dict[str, Any]:
        assert QueryExecutionId in {f"query-{index}" for index in range(1, 10)}
        return {
            "QueryExecution": {
                "Status": {"State": "SUCCEEDED"},
                "ResultConfiguration": {
                    "OutputLocation": (
                        "s3://aws-athena-query-results-789121567207-us-west-2/"
                        f"athena-query-results/{QueryExecutionId}.csv"
                    )
                },
            }
        }


class FakeStreamingBody:
    def __init__(self, content: str) -> None:
        self.content = content

    def iter_lines(self) -> list[bytes]:
        return [line.encode("utf-8") for line in self.content.splitlines()]


class FakeS3Client:
    def __init__(self, *, result_kind: str = "tick") -> None:
        self.objects_requested: list[dict[str, str]] = []
        self.result_kind = result_kind

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, FakeStreamingBody]:
        self.objects_requested.append({"Bucket": Bucket, "Key": Key})
        execution_id = Key.rsplit("/", maxsplit=1)[-1].removesuffix(".csv")
        execution_index = int(execution_id.rsplit("-", maxsplit=1)[-1])
        participant_timestamp = str(1783555200000000000 + execution_index)
        if self.result_kind == "candle":
            return {
                "Body": FakeStreamingBody(
                    "\n".join(
                        (
                            "ticker,volume,open,close,high,low,window_start,transactions",
                            (
                                "C:USD-JPY,120,150.100,150.200,150.300,150.000,"
                                f"{participant_timestamp},42"
                            ),
                        )
                    )
                )
            }
        return {
            "Body": FakeStreamingBody(
                "\n".join(
                    (
                        "ticker,bid_price,ask_price,participant_timestamp",
                        f"C:USD-JPY,150.100,150.120,{participant_timestamp}",
                    )
                )
            )
        }


class TestAthenaDataSourceValidation:
    def test_candles_reject_unsupported_granularity(self) -> None:
        source = AthenaDataSource(settings=AthenaSettings())

        with pytest.raises(AthenaDataSourceError, match="unsupported Athena candle granularity"):
            source.query_for_candles(
                instrument=CurrencyPair.of("USD_JPY"),
                granularity=CandleGranularity.MINUTE_5,
            )


class TestAthenaPrefetchPolicy:
    def test_tracks_query_and_consumption_speed(self) -> None:
        source = AthenaDataSource(
            settings=AthenaSettings(
                query_prefetch_min_windows=1,
                query_prefetch_max_windows=6,
                query_prefetch_workers=6,
                query_prefetch_wait_target_seconds=0.5,
            )
        )

        assert (
            source.prefetch_policy.target(
                current_target=2,
                query_elapsed=3.0,
                consumption_elapsed=0.5,
                wait_elapsed=0.0,
            )
            == 6
        )
        assert (
            source.prefetch_policy.target(
                current_target=2,
                query_elapsed=0.2,
                consumption_elapsed=3.0,
                wait_elapsed=0.8,
            )
            == 3
        )
        assert (
            source.prefetch_policy.target(
                current_target=4,
                query_elapsed=0.5,
                consumption_elapsed=5.0,
                wait_elapsed=0.0,
            )
            == 3
        )
