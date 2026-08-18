from datetime import UTC, datetime
from pathlib import Path

from autoforex.core import CandleGranularity, CSVDataSource, CurrencyPair, Metadata, Money


class TestCSVMarketData:
    def test_csv_source_loads_tick_and_candle_files_together(self, tmp_path: Path) -> None:
        tick_path = tmp_path / "ticks.csv"
        candle_path = tmp_path / "candles.csv"
        tick_path.write_text(
            "\n".join(
                [
                    "timestamp,instrument,bid,ask,metadata.provider",
                    "2026-01-01T00:00:00Z,USD_JPY,150.10,150.12,csv",
                    "2026-01-01T00:00:01Z,USD_JPY,150.11,150.13,csv",
                ]
            ),
            encoding="utf-8",
        )
        candle_path.write_text(
            "\n".join(
                [
                    "timestamp,instrument,granularity,open,high,low,close,volume,complete",
                    "2026-01-01T00:00:00Z,USD_JPY,M1,150.00,150.20,149.90,150.10,120,true",
                ]
            ),
            encoding="utf-8",
        )
        source = CSVDataSource(tick_path=tick_path, candle_path=candle_path)

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("USD_JPY")))
        candles = tuple(
            source.candles(
                instrument=CurrencyPair.of("USD_JPY"),
                granularity=CandleGranularity.MINUTE_1,
            )
        )

        assert [tick.effective_mid for tick in ticks] == [
            Money.of("150.11", "JPY"),
            Money.of("150.12", "JPY"),
        ]
        assert ticks[0].metadata == Metadata.of(provider="csv")
        assert candles[0].timestamp == datetime(2026, 1, 1, tzinfo=UTC)
        assert candles[0].close == Money.of("150.10", "JPY")

    def test_csv_source_filters_market_data_by_instrument_and_time(self, tmp_path: Path) -> None:
        tick_path = tmp_path / "ticks.csv"
        tick_path.write_text(
            "\n".join(
                [
                    "timestamp,instrument,bid,ask",
                    "2026-01-01T00:00:00Z,USD_JPY,150.10,150.12",
                    "2026-01-01T00:01:00Z,EUR_USD,1.1000,1.1002",
                    "2026-01-01T00:02:00Z,USD_JPY,150.20,150.22",
                ]
            ),
            encoding="utf-8",
        )

        ticks = tuple(
            CSVDataSource(tick_path=tick_path).ticks(
                instrument=CurrencyPair.of("USD_JPY"),
                start_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            )
        )

        assert len(ticks) == 1
        assert ticks[0].bid == Money.of("150.20", "JPY")
