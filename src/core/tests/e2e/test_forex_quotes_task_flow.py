import gzip
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from autoforex.core import (
    Account,
    AccountId,
    BacktestTaskDefinition,
    Candle,
    CandleGranularity,
    CSVCandleSchema,
    CSVDataSource,
    CSVTickSchema,
    CurrencyPair,
    ExecutableTask,
    Metadata,
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEventRequest,
    StrategyParameters,
    StrategyResult,
    TaskStatus,
    TaskType,
    Tick,
    TradingTaskDefinition,
)

DATA_PATH = Path(__file__).resolve().parents[1] / "data"
QUOTE_PATH = DATA_PATH / "quotes" / "forex_quotes_examples.csv"
MINUTE_AGGS_PATH = DATA_PATH / "minute_aggs" / "forex_minute_candlesticks.csv"
EUR_USD = CurrencyPair.of("EUR_USD")
AED_AUD = CurrencyPair.of("AED_AUD")
_POLYGON_QUOTE_ROWS = [
    "ticker,ask_exchange,ask_price,bid_exchange,bid_price,participant_timestamp",
    "C:AED-AUD,48,0.395074400398535,48,0.394859306128548,1782459801000000000",
    "C:AED-AUD,48,0.394608996806469,48,0.394576768041621,1782503836000000000",
]
_POLYGON_MINUTE_AGG_ROWS = [
    "ticker,volume,open,close,high,low,window_start,transactions",
    "C:AED-AUD,1,0.394859306128548,0.394859306128548,"
    "0.394859306128548,0.394859306128548,1782459780000000000,1",
    "C:AED-AUD,2,0.394576768041621,0.394564635739964,"
    "0.394576768041621,0.394564635739964,1782503820000000000,2",
]


def _write_gzip_csv(path: Path, rows: list[str]) -> Path:
    with gzip.open(path, mode="wt", encoding="utf-8", newline="") as file:
        file.write("\n".join(rows))
    return path


def _gzip_quote_source(tmp_path: Path) -> CSVDataSource:
    return CSVDataSource(
        tick_path=_write_gzip_csv(tmp_path / "quotes.csv.gz", _POLYGON_QUOTE_ROWS),
        tick_schema=CSVTickSchema.polygon_forex_quotes(),
    )


def _gzip_minute_agg_source(tmp_path: Path) -> CSVDataSource:
    return CSVDataSource(
        candle_path=_write_gzip_csv(
            tmp_path / "minute-aggs.csv.gz",
            _POLYGON_MINUTE_AGG_ROWS,
        ),
        candle_schema=CSVCandleSchema.polygon_forex_minute_aggs(),
    )


class ForexQuotesExampleDataSource(CSVDataSource):
    """Test data source for polygon-style forex quote examples."""

    def __init__(self) -> None:
        super().__init__(
            tick_path=QUOTE_PATH,
            tick_schema=CSVTickSchema.polygon_forex_quotes(ticker_column="Ticker"),
        )


class ForexMinuteAggsExampleDataSource(CSVDataSource):
    """Test data source for polygon-style forex one-minute aggregates."""

    def __init__(self) -> None:
        super().__init__(
            candle_path=MINUTE_AGGS_PATH,
            candle_schema=CSVCandleSchema.polygon_forex_minute_aggs(),
        )


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    action=StrategyAction.HOLD,
                    instrument=tick.instrument,
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.HOLD,
                        rule_id="forex_quotes.hold",
                        evidence=Metadata.of(
                            task_type=context.task_type.value,
                            mid=str(tick.effective_mid),
                        ),
                    ),
                ),
            )
        )

    def on_candle(self, candle: Candle, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=candle.timestamp,
                    task_id=context.task_id,
                    action=StrategyAction.HOLD,
                    instrument=candle.instrument,
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.HOLD,
                        rule_id="forex_minute_aggs.hold",
                        evidence=Metadata.of(
                            task_type=context.task_type.value,
                            close=str(candle.close),
                        ),
                    ),
                ),
            )
        )


class TestForexQuotesTaskFlow:
    def test_forex_quotes_data_source_generates_ticks(self) -> None:
        source = ForexQuotesExampleDataSource()

        ticks = tuple(source.ticks(instrument=EUR_USD))

        assert len(ticks) == 99
        assert ticks[0].timestamp == datetime(2023, 3, 28, tzinfo=UTC)
        assert ticks[0].metadata == Metadata.of(ask_exchange="48", bid_exchange="48")

    def test_forex_minute_aggs_data_source_generates_candles(self) -> None:
        source = ForexMinuteAggsExampleDataSource()

        candles = tuple(source.candles(instrument=EUR_USD, granularity=CandleGranularity.MINUTE_1))

        assert len(candles) == 99
        assert candles[0].timestamp == datetime(2023, 3, 28, tzinfo=UTC)
        assert candles[0].volume == 120
        assert candles[0].metadata == Metadata.of(transactions="120")

    def test_backtest_task_processes_forex_quote_ticks_end_to_end(self) -> None:
        definition = BacktestTaskDefinition(
            name="Backtest EUR_USD sample quotes",
            instrument=EUR_USD,
            parameters=StrategyParameters.of(risk_percent=Decimal("1.0")),
            start_at=datetime(2023, 3, 28, tzinfo=UTC),
            end_at=datetime(2023, 3, 29, tzinfo=UTC),
        )

        completed, events = _run_ticks_through_task(definition.task_type, definition)

        assert completed.status == TaskStatus.COMPLETED
        assert len(events) == 99
        assert all(event.task_id == completed.id for event in events)
        assert {event.action for event in events} == {StrategyAction.HOLD}

    def test_trading_task_processes_forex_quote_ticks_end_to_end(self) -> None:
        definition = TradingTaskDefinition(
            name="Trading EUR_USD sample quotes",
            instrument=EUR_USD,
            account=Account(id=AccountId.of("test-account")),
            dry_run=True,
            parameters=StrategyParameters.of(risk_percent=Decimal("1.0")),
        )

        stopped, events = _run_ticks_through_task(definition.task_type, definition, limit=10)

        assert stopped.status == TaskStatus.STOPPED
        assert len(events) == 10
        assert all(event.task_id == stopped.id for event in events)
        assert all(event.reason.rule_id == "forex_quotes.hold" for event in events)

    def test_backtest_task_processes_gzip_forex_quote_ticks_end_to_end(
        self, tmp_path: Path
    ) -> None:
        definition = BacktestTaskDefinition(
            name="Backtest AED_AUD compressed sample quotes",
            instrument=AED_AUD,
            parameters=StrategyParameters.of(risk_percent=Decimal("1.0")),
            start_at=datetime(2026, 6, 26, tzinfo=UTC),
            end_at=datetime(2026, 6, 27, tzinfo=UTC),
        )

        completed, events = _run_ticks_through_task(
            definition.task_type,
            definition,
            source=_gzip_quote_source(tmp_path),
            limit=2,
        )

        assert completed.status == TaskStatus.COMPLETED
        assert len(events) == 2
        assert all(event.instrument == AED_AUD for event in events)

    def test_trading_task_processes_gzip_forex_quote_ticks_end_to_end(self, tmp_path: Path) -> None:
        definition = TradingTaskDefinition(
            name="Trading AED_AUD compressed sample quotes",
            instrument=AED_AUD,
            account=Account(id=AccountId.of("test-account")),
            dry_run=True,
            parameters=StrategyParameters.of(risk_percent=Decimal("1.0")),
        )

        stopped, events = _run_ticks_through_task(
            definition.task_type,
            definition,
            source=_gzip_quote_source(tmp_path),
            limit=2,
        )

        assert stopped.status == TaskStatus.STOPPED
        assert len(events) == 2
        assert all(event.task_id == stopped.id for event in events)

    def test_backtest_task_processes_forex_minute_aggs_candles_end_to_end(self) -> None:
        definition = BacktestTaskDefinition(
            name="Backtest EUR_USD sample minute aggs",
            instrument=EUR_USD,
            parameters=StrategyParameters.of(risk_percent=Decimal("1.0")),
            start_at=datetime(2023, 3, 28, tzinfo=UTC),
            end_at=datetime(2023, 3, 29, tzinfo=UTC),
        )

        completed, events = _run_candles_through_task(
            definition.task_type,
            definition,
            source=ForexMinuteAggsExampleDataSource(),
        )

        assert completed.status == TaskStatus.COMPLETED
        assert len(events) == 99
        assert all(event.reason.rule_id == "forex_minute_aggs.hold" for event in events)

    def test_trading_task_processes_gzip_forex_minute_aggs_candles_end_to_end(
        self, tmp_path: Path
    ) -> None:
        definition = TradingTaskDefinition(
            name="Trading AED_AUD compressed minute aggs",
            instrument=AED_AUD,
            account=Account(id=AccountId.of("test-account")),
            dry_run=True,
            parameters=StrategyParameters.of(risk_percent=Decimal("1.0")),
        )

        stopped, events = _run_candles_through_task(
            definition.task_type,
            definition,
            source=_gzip_minute_agg_source(tmp_path),
            limit=2,
        )

        assert stopped.status == TaskStatus.STOPPED
        assert len(events) == 2
        assert all(event.instrument == AED_AUD for event in events)


def _run_ticks_through_task(
    task_type: TaskType,
    definition: BacktestTaskDefinition | TradingTaskDefinition,
    *,
    source: CSVDataSource | None = None,
    limit: int | None = None,
) -> tuple[ExecutableTask, tuple[StrategyEventRequest, ...]]:
    task = ExecutableTask.from_definition(definition).start()
    strategy = HoldStrategy(
        name="hold",
        parameters=definition.parameters,
    )
    context = StrategyContext(
        task_id=task.id,
        task_type=task_type,
        instrument=definition.instrument,
        metadata=Metadata.of(strategy_name=strategy.name),
    )
    data_source = source or ForexQuotesExampleDataSource()
    ticks = data_source.ticks(instrument=definition.instrument)
    selected_ticks = _take(ticks, limit=limit)
    events = tuple(
        event for tick in selected_ticks for event in strategy.on_tick(tick, context).events
    )
    if task_type == TaskType.TRADING:
        return task.stop(), events
    return task.complete(), events


def _run_candles_through_task(
    task_type: TaskType,
    definition: BacktestTaskDefinition | TradingTaskDefinition,
    *,
    source: CSVDataSource,
    limit: int | None = None,
) -> tuple[ExecutableTask, tuple[StrategyEventRequest, ...]]:
    task = ExecutableTask.from_definition(definition).start()
    strategy = HoldStrategy(
        name="hold",
        parameters=definition.parameters,
    )
    context = StrategyContext(
        task_id=task.id,
        task_type=task_type,
        instrument=definition.instrument,
        metadata=Metadata.of(strategy_name=strategy.name),
    )
    candles = source.candles(
        instrument=definition.instrument,
        granularity=CandleGranularity.MINUTE_1,
    )
    selected_candles = _take(candles, limit=limit)
    events = tuple(
        event for candle in selected_candles for event in strategy.on_candle(candle, context).events
    )
    if task_type == TaskType.TRADING:
        return task.stop(), events
    return task.complete(), events


def _take[T](items: Iterable[T], *, limit: int | None) -> tuple[T, ...]:
    if limit is None:
        return tuple(items)
    selected: list[T] = []
    for item in items:
        selected.append(item)
        if len(selected) >= limit:
            break
    return tuple(selected)
