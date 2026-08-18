import gzip
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from autoforex.core import CandleGranularity, CurrencyPair, Metadata, Money, TickGranularity
from autoforex.core.clock import local_timezone
from autoforex.core.sources import CSVCandleSchema, CSVDataSource, CSVDataSourceError, CSVTickSchema

_POLYGON_HEADER = "ticker,ask_exchange,ask_price,bid_exchange,bid_price,participant_timestamp"
_POLYGON_MINUTE_AGGS_HEADER = "ticker,volume,open,close,high,low,window_start,transactions"


def _polygon_row(ticker: str, ask: str, bid: str, epoch_ns: int) -> str:
    return f"{ticker},48,{ask},48,{bid},{epoch_ns}"


def _write_polygon_quotes(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join([_POLYGON_HEADER, *rows]), encoding="utf-8")
    return path


def _write_gzip_csv(path: Path, rows: list[str]) -> Path:
    with gzip.open(path, mode="wt", encoding="utf-8", newline="") as file:
        file.write("\n".join(rows))
    return path


DATA_PATH = Path(__file__).resolve().parents[3] / "data"
QUOTE_PATH = DATA_PATH / "quotes" / "forex_quotes_examples.csv"
MINUTE_AGGS_PATH = DATA_PATH / "minute_aggs" / "forex_minute_candlesticks.csv"


class TestCSV:
    def test_csv_data_source_yields_ticks_from_csv(self, tmp_path: Path) -> None:
        tick_path = tmp_path / "ticks.csv"
        tick_path.write_text(
            "\n".join(
                [
                    "timestamp,instrument,bid,ask,metadata.provider",
                    "2026-01-01T00:00:00Z,USD_JPY,150.10,150.12,fixture",
                    "2026-01-01T00:01:00Z,EUR_USD,1.1000,1.1002,fixture",
                ]
            ),
            encoding="utf-8",
        )
        source = CSVDataSource(tick_path=tick_path)

        ticks = tuple(
            source.ticks(
                instrument=CurrencyPair.of("USD_JPY"),
                start_at=datetime(2026, 1, 1, tzinfo=UTC),
                end_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            )
        )

        assert len(ticks) == 1
        assert ticks[0].effective_mid == Money.of("150.11", "JPY")
        assert ticks[0].metadata == Metadata.of(provider="fixture")

    def test_csv_data_source_yields_candles_from_csv(self, tmp_path: Path) -> None:
        candle_path = tmp_path / "candles.csv"
        candle_path.write_text(
            "\n".join(
                [
                    "timestamp,open,high,low,close,volume,complete,metadata.provider",
                    "2026-01-01T00:00:00,1.1000,1.1010,1.0990,1.1005,120,false,fixture",
                ]
            ),
            encoding="utf-8",
        )
        source = CSVDataSource(candle_path=candle_path)

        candles = tuple(
            source.candles(
                instrument=CurrencyPair.of("EUR_USD"),
                granularity=CandleGranularity.MINUTE_1,
            )
        )

        assert len(candles) == 1
        # Naive timestamps are interpreted in the local zone by default.
        assert candles[0].timestamp == datetime(2026, 1, 1, tzinfo=local_timezone())
        assert candles[0].close == Money.of("1.1005", "USD")
        assert candles[0].complete is False
        assert candles[0].metadata == Metadata.of(provider="fixture")

    def test_csv_data_source_assume_timezone_overrides_naive_timestamps(
        self, tmp_path: Path
    ) -> None:
        candle_path = tmp_path / "candles.csv"
        candle_path.write_text(
            "\n".join(
                [
                    "timestamp,open,high,low,close,volume,complete",
                    "2026-01-01T00:00:00,1.1000,1.1010,1.0990,1.1005,120,false",
                ]
            ),
            encoding="utf-8",
        )
        source = CSVDataSource(candle_path=candle_path, assume_timezone=ZoneInfo("Asia/Tokyo"))

        candles = tuple(
            source.candles(
                instrument=CurrencyPair.of("EUR_USD"),
                granularity=CandleGranularity.MINUTE_1,
            )
        )

        assert candles[0].timestamp == datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Tokyo"))

    def test_csv_data_source_reports_invalid_rows(self, tmp_path: Path) -> None:
        tick_path = tmp_path / "ticks.csv"
        tick_path.write_text(
            "\n".join(
                [
                    "timestamp,instrument,bid",
                    "2026-01-01T00:00:00Z,USD_JPY,150.10",
                ]
            ),
            encoding="utf-8",
        )
        source = CSVDataSource(tick_path=tick_path)

        with pytest.raises(CSVDataSourceError, match="missing required column value: ask"):
            tuple(source.ticks(instrument=CurrencyPair.of("USD_JPY")))

    def test_csv_data_source_reads_forex_quote_example_file(self) -> None:
        source = CSVDataSource(
            tick_path=QUOTE_PATH,
            tick_schema=CSVTickSchema.polygon_forex_quotes(ticker_column="Ticker"),
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("EUR_USD")))

        assert len(ticks) == 99
        assert ticks[0].instrument == CurrencyPair.of("EUR_USD")
        assert ticks[0].timestamp == datetime(2023, 3, 28, tzinfo=UTC)
        assert ticks[0].bid == Money.of("1.08063", "USD")
        assert ticks[0].ask == Money.of("1.08066", "USD")
        assert ticks[0].metadata == Metadata.of(ask_exchange="48", bid_exchange="48")

    def test_csv_data_source_reads_gzip_compressed_forex_quote_file(self, tmp_path: Path) -> None:
        quote_path = _write_gzip_csv(
            tmp_path / "quotes.csv.gz",
            [
                _POLYGON_HEADER,
                "C:AED-AUD,48,0.395074400398535,48,0.394859306128548,1782459801000000000",
                "C:AED-AUD,48,0.394608996806469,48,0.394576768041621,1782503836000000000",
            ],
        )
        source = CSVDataSource(
            tick_path=quote_path,
            tick_schema=CSVTickSchema.polygon_forex_quotes(),
        )

        ticks = tuple(islice(source.ticks(instrument=CurrencyPair.of("AED_AUD")), 2))

        assert len(ticks) == 2
        assert ticks[0].instrument == CurrencyPair.of("AED_AUD")
        assert ticks[0].timestamp == datetime(2026, 6, 26, 7, 43, 21, tzinfo=UTC)
        assert ticks[0].bid == Money.of("0.394859306128548", "AUD")
        assert ticks[0].ask == Money.of("0.395074400398535", "AUD")
        assert ticks[0].metadata == Metadata.of(ask_exchange="48", bid_exchange="48")

    def test_csv_data_source_reads_forex_minute_aggregate_file(self) -> None:
        source = CSVDataSource(
            candle_path=MINUTE_AGGS_PATH,
            candle_schema=CSVCandleSchema.polygon_forex_minute_aggs(),
        )

        candles = tuple(
            source.candles(
                instrument=CurrencyPair.of("EUR_USD"),
                granularity=CandleGranularity.MINUTE_1,
            )
        )

        assert len(candles) == 99
        assert candles[0].instrument == CurrencyPair.of("EUR_USD")
        assert candles[0].timestamp == datetime(2023, 3, 28, tzinfo=UTC)
        assert candles[0].open == Money.of("1.08063", "USD")
        assert candles[0].close == Money.of("1.08033", "USD")
        assert candles[0].volume == 120
        assert candles[0].metadata == Metadata.of(transactions="120")

    def test_csv_data_source_reads_gzip_compressed_forex_minute_aggregate_file(
        self, tmp_path: Path
    ) -> None:
        candle_path = _write_gzip_csv(
            tmp_path / "minute-aggs.csv.gz",
            [
                _POLYGON_MINUTE_AGGS_HEADER,
                "C:AED-AUD,1,0.394859306128548,0.394859306128548,"
                "0.394859306128548,0.394859306128548,1782459780000000000,1",
                "C:AED-AUD,2,0.394576768041621,0.394564635739964,"
                "0.394576768041621,0.394564635739964,1782503820000000000,2",
            ],
        )
        source = CSVDataSource(
            candle_path=candle_path,
            candle_schema=CSVCandleSchema.polygon_forex_minute_aggs(),
        )

        candles = tuple(
            islice(
                source.candles(
                    instrument=CurrencyPair.of("AED_AUD"),
                    granularity=CandleGranularity.MINUTE_1,
                ),
                2,
            )
        )

        assert len(candles) == 2
        assert candles[0].instrument == CurrencyPair.of("AED_AUD")
        assert candles[0].timestamp == datetime(2026, 6, 26, 7, 43, tzinfo=UTC)
        assert candles[0].open == Money.of("0.394859306128548", "AUD")
        assert candles[0].close == Money.of("0.394859306128548", "AUD")
        assert candles[0].volume == 1
        assert candles[0].metadata == Metadata.of(transactions="1")

    def test_csv_data_source_default_granularity_yields_every_tick(self) -> None:
        source = CSVDataSource(
            tick_path=QUOTE_PATH,
            tick_schema=CSVTickSchema.polygon_forex_quotes(ticker_column="Ticker"),
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("EUR_USD")))

        assert len(ticks) == 99

    def test_csv_data_source_samples_ticks_by_granularity(self) -> None:
        source = CSVDataSource(
            tick_path=QUOTE_PATH,
            tick_schema=CSVTickSchema.polygon_forex_quotes(ticker_column="Ticker"),
        )

        per_second = tuple(
            source.ticks(
                instrument=CurrencyPair.of("EUR_USD"), granularity=TickGranularity.SECOND_1
            )
        )
        per_minute = tuple(
            source.ticks(
                instrument=CurrencyPair.of("EUR_USD"), granularity=TickGranularity.MINUTE_1
            )
        )

        # The fixture holds 99 quotes spread across 45 distinct seconds in one minute.
        assert len(per_second) == 45
        assert len(per_minute) == 1

    def test_csv_data_source_filters_instrument_before_parsing(self, tmp_path: Path) -> None:
        quote_path = _write_polygon_quotes(
            tmp_path / "quotes.csv",
            [
                _polygon_row("C:EUR-USD", "1.10020", "1.10010", 1_679_961_600_000_000_000),
                _polygon_row("C:USD-JPY", "150.120", "150.100", 1_679_961_601_000_000_000),
                # Unparseable prices for another instrument: if every row were parsed
                # before filtering, this would raise. It must be skipped by ticker.
                _polygon_row("C:GBP-USD", "not-a-number", "also-bad", 1_679_961_602_000_000_000),
                _polygon_row("C:EUR-USD", "1.10040", "1.10030", 1_679_961_603_000_000_000),
            ],
        )
        source = CSVDataSource(
            tick_path=quote_path,
            tick_schema=CSVTickSchema.polygon_forex_quotes(),
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("EUR_USD")))

        assert len(ticks) == 2
        assert all(tick.instrument == CurrencyPair.of("EUR_USD") for tick in ticks)
        assert ticks[0].bid == Money.of("1.10010", "USD")

    def test_csv_data_source_streams_multiple_files_in_order(self, tmp_path: Path) -> None:
        first = _write_polygon_quotes(
            tmp_path / "2026-01-01.csv",
            [
                _polygon_row("C:EUR-USD", "1.10020", "1.10010", 1_679_961_600_000_000_000),
                _polygon_row("C:USD-JPY", "150.120", "150.100", 1_679_961_600_000_000_000),
            ],
        )
        second = _write_polygon_quotes(
            tmp_path / "2026-01-02.csv",
            [_polygon_row("C:EUR-USD", "1.10120", "1.10110", 1_680_048_000_000_000_000)],
        )
        source = CSVDataSource(
            tick_paths=[first, second],
            tick_schema=CSVTickSchema.polygon_forex_quotes(),
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("EUR_USD")))

        assert [tick.bid for tick in ticks] == [
            Money.of("1.10010", "USD"),
            Money.of("1.10110", "USD"),
        ]
        assert ticks[0].timestamp < ticks[1].timestamp

    def test_csv_data_source_matches_ticker_prefix_variants(self, tmp_path: Path) -> None:
        quote_path = _write_polygon_quotes(
            tmp_path / "quotes.csv",
            [
                _polygon_row("X:EUR-USD", "1.10020", "1.10010", 1_679_961_600_000_000_000),
                _polygon_row("C:EUR-USD", "1.10040", "1.10030", 1_679_961_660_000_000_000),
            ],
        )
        source = CSVDataSource(
            tick_path=quote_path,
            tick_schema=CSVTickSchema.polygon_forex_quotes(),
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("EUR_USD")))

        assert len(ticks) == 2

    def test_csv_data_source_from_directory_globs_sorted(self, tmp_path: Path) -> None:
        _write_polygon_quotes(
            tmp_path / "2026-01-02.csv",
            [_polygon_row("C:EUR-USD", "1.10120", "1.10110", 1_680_048_000_000_000_000)],
        )
        _write_polygon_quotes(
            tmp_path / "2026-01-01.csv",
            [_polygon_row("C:EUR-USD", "1.10020", "1.10010", 1_679_961_600_000_000_000)],
        )
        source = CSVDataSource.from_directory(
            tmp_path,
            tick_pattern="*.csv",
            tick_schema=CSVTickSchema.polygon_forex_quotes(),
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("EUR_USD")))

        assert [tick.bid for tick in ticks] == [
            Money.of("1.10010", "USD"),
            Money.of("1.10110", "USD"),
        ]

    def test_csv_data_source_from_directory_requires_pattern(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="tick_pattern and/or candle_pattern"):
            CSVDataSource.from_directory(tmp_path)

    def test_csv_data_source_from_directory_raises_when_empty(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="no files matching"):
            CSVDataSource.from_directory(tmp_path, tick_pattern="*.csv.gz")

    def test_csv_data_source_rejects_path_and_paths(self, tmp_path: Path) -> None:
        quote_path = _write_polygon_quotes(
            tmp_path / "quotes.csv",
            [_polygon_row("C:EUR-USD", "1.10020", "1.10010", 1_679_961_600_000_000_000)],
        )
        with pytest.raises(ValueError, match="not both"):
            CSVDataSource(tick_path=quote_path, tick_paths=[quote_path])
