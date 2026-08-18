"""Reusable chart renderers for backtest notebooks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from itertools import pairwise
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from autoforex.core import CandleGranularity, CurrencyPair
from autoforex.core.sources.base import DataSource
from autoforex.core.sources.models import Candle
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from notebooks.backtests.results import TaskResultFrames


@dataclass(frozen=True, slots=True)
class BacktestChartConfig:
    """Configuration for the standard price and P/L backtest chart."""

    instrument: CurrencyPair
    start_at: datetime
    end_at: datetime
    local_timezone: tzinfo
    day_aggs_threshold_days: int = 31
    width: float = 16
    height: float = 10

    @property
    def granularity(self) -> CandleGranularity:
        """Return the candle granularity suitable for the configured period."""
        if self.end_at - self.start_at > timedelta(days=self.day_aggs_threshold_days):
            return CandleGranularity.DAY
        return CandleGranularity.MINUTE_1


@dataclass(frozen=True, slots=True)
class CandleFrameBuilder:
    """Build chart-oriented DataFrames from Core candle models."""

    timezone: tzinfo

    def frame(self, candles: Iterable[Candle]) -> pd.DataFrame:
        """Return an OHLC DataFrame suitable for matplotlib rendering."""
        return pd.DataFrame(self._row(candle) for candle in candles)

    def _row(self, candle: Candle) -> dict[str, Any]:
        return {
            "timestamp": candle.timestamp.astimezone(self.timezone),
            "open": float(candle.open.amount),
            "high": float(candle.high.amount),
            "low": float(candle.low.amount),
            "close": float(candle.close.amount),
            "volume": candle.volume,
        }


@dataclass(frozen=True, slots=True)
class CandleWidthCalculator:
    """Calculate readable candle body widths for matplotlib date axes."""

    granularity: CandleGranularity

    def width(self, x_values: Iterable[float]) -> float:
        """Return a candle body width in matplotlib date units."""
        values = tuple(x_values)
        positive_deltas = [right - left for left, right in pairwise(values) if right > left]
        width = min(positive_deltas) * 0.8 if positive_deltas else 0.7
        if self.granularity == CandleGranularity.MINUTE_1:
            return min(width, 1 / 24 / 60 * 0.8)
        return width


@dataclass(frozen=True, slots=True)
class CandleChartRenderer:
    """Render OHLC candle bodies and wicks."""

    granularity: CandleGranularity

    def render(self, ax: Axes, frame: pd.DataFrame) -> None:
        """Draw candle data on the provided axes."""
        if frame.empty:
            return
        x_values = mdates.date2num(frame["timestamp"])
        width = CandleWidthCalculator(self.granularity).width(x_values)
        rows = zip(
            x_values,
            frame["open"],
            frame["high"],
            frame["low"],
            frame["close"],
            strict=False,
        )
        for x, open_price, high, low, close_price in rows:
            color = "#16833a" if close_price >= open_price else "#b42318"
            ax.vlines(x, low, high, color=color, linewidth=0.8, alpha=0.9)
            self._body(
                ax,
                x=x,
                open_price=open_price,
                close_price=close_price,
                color=color,
                width=width,
            )

    @staticmethod
    def _body(
        ax: Axes,
        *,
        x: float,
        open_price: float,
        close_price: float,
        color: str,
        width: float,
    ) -> None:
        lower = min(open_price, close_price)
        height = abs(close_price - open_price)
        if height == 0:
            ax.hlines(open_price, x - width / 2, x + width / 2, color=color, linewidth=1.2)
            return
        ax.add_patch(
            Rectangle(
                (x - width / 2, lower),
                width,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.6,
                alpha=0.75,
            )
        )


@dataclass(frozen=True, slots=True)
class EventMarkerRenderer:
    """Render strategy event markers on a price chart."""

    def render(self, ax: Axes, events: pd.DataFrame) -> None:
        """Draw open, close, rebuild, and stop-loss markers."""
        if events.empty or "price" not in events.columns:
            return
        self._scatter(
            ax,
            self._points(events, action="open_trade", is_rebuild=False),
            label="open",
            marker="^",
            color="#2563eb",
        )
        self._scatter(
            ax,
            self._points(events, action="close_trade", close_reason_not="stop_loss"),
            label="close",
            marker="v",
            color="#0f766e",
        )
        self._scatter(
            ax,
            self._points(events, action="open_trade", is_rebuild=True),
            label="rebuild",
            marker="D",
            color="#9333ea",
        )
        self._scatter(
            ax,
            self._points(events, close_reason="stop_loss"),
            label="stop_loss",
            marker="x",
            color="#dc2626",
        )

    def _points(
        self,
        events: pd.DataFrame,
        *,
        action: str | None = None,
        is_rebuild: bool | None = None,
        close_reason: str | None = None,
        close_reason_not: str | None = None,
    ) -> list[tuple[Any, float]]:
        filtered = events
        if action is not None:
            filtered = filtered[filtered["action"] == action]
        if is_rebuild is not None and "is_rebuild" in filtered.columns:
            filtered = filtered[filtered["is_rebuild"] == is_rebuild]
        if close_reason is not None and "close_reason" in filtered.columns:
            filtered = filtered[filtered["close_reason"] == close_reason]
        if close_reason_not is not None and "close_reason" in filtered.columns:
            filtered = filtered[filtered["close_reason"] != close_reason_not]
        return [
            (timestamp, self._price(price))
            for timestamp, price in zip(
                filtered["timestamp"],
                filtered["price"],
                strict=False,
            )
            if pd.notna(price)
        ]

    @staticmethod
    def _price(value: Any) -> float:
        amount = str(value).split()[0]
        return float(amount)

    @staticmethod
    def _scatter(
        ax: Axes,
        points: list[tuple[Any, float]],
        *,
        label: str,
        marker: str,
        color: str,
    ) -> None:
        if not points:
            return
        timestamps, prices = zip(*points, strict=False)
        ax.scatter(timestamps, prices, label=label, marker=marker, color=color, s=48, zorder=5)


@dataclass(frozen=True, slots=True)
class MetricChartRenderer:
    """Render realized, unrealized, and total P/L metrics."""

    def render(self, ax: Axes, metrics: pd.DataFrame) -> None:
        """Draw metric lines on the provided axes."""
        if metrics.empty:
            ax.text(0.5, 0.5, "No metrics", ha="center", va="center", transform=ax.transAxes)
            return
        ax.plot(
            metrics["timestamp"],
            metrics["realized_pl"],
            label="realized_pl",
            color="#2563eb",
            linewidth=1.4,
        )
        ax.plot(
            metrics["timestamp"],
            metrics["unrealized_pl"],
            label="unrealized_pl",
            color="#f97316",
            linewidth=1.4,
        )
        ax.plot(
            metrics["timestamp"],
            metrics["total_pl"],
            label="total_pl",
            color="#111827",
            linewidth=1.6,
        )
        currency = self._currency(metrics)
        ax.set_ylabel(f"P/L {currency}".strip())
        ax.legend(loc="best", ncols=3)

    @staticmethod
    def _currency(metrics: pd.DataFrame) -> str:
        if "currency" not in metrics.columns or not metrics["currency"].notna().any():
            return ""
        return str(metrics["currency"].dropna().iloc[0])


@dataclass(frozen=True, slots=True)
class BacktestChartRenderer:
    """Render the combined price and metric chart."""

    config: BacktestChartConfig

    def render(self, *, candles: pd.DataFrame, frames: TaskResultFrames) -> Figure:
        """Render the complete chart and return the matplotlib figure."""
        fig, (price_ax, metric_ax) = plt.subplots(
            2,
            1,
            figsize=(self.config.width, self.config.height),
            sharex=True,
            gridspec_kw={"height_ratios": (1, 1), "hspace": 0.08},
        )
        CandleChartRenderer(self.config.granularity).render(price_ax, candles)
        EventMarkerRenderer().render(price_ax, frames.events)
        self._format_price_axis(price_ax)
        MetricChartRenderer().render(metric_ax, frames.metrics)
        self._format_metric_axis(metric_ax)
        fig.autofmt_xdate()
        return fig

    def _format_price_axis(self, ax: Axes) -> None:
        ax.set_title(f"{self.config.instrument} {self.config.granularity.value} Snowball")
        ax.set_ylabel(str(self.config.instrument.quote))
        ax.grid(True, axis="y", alpha=0.25)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc="best")

    def _format_metric_axis(self, ax: Axes) -> None:
        ax.grid(True, axis="y", alpha=0.25)
        ax.xaxis_date()
        ax.xaxis.set_major_formatter(
            mdates.DateFormatter("%Y-%m-%d %H:%M", tz=self.config.local_timezone)
        )


@dataclass(frozen=True, slots=True)
class BacktestResultChart:
    """Load candle data and display the standard backtest chart."""

    data_source: DataSource
    config: BacktestChartConfig

    @property
    def granularity(self) -> CandleGranularity:
        """Return the candle granularity selected by the chart config."""
        return self.config.granularity

    def candles(self) -> tuple[Candle, ...]:
        """Load chart candles from the configured data source."""
        return tuple(
            self.data_source.candles(
                instrument=self.config.instrument,
                granularity=self.config.granularity,
                start_at=self.config.start_at,
                end_at=self.config.end_at,
            )
        )

    def candle_frame(self, candles: Iterable[Candle]) -> pd.DataFrame:
        """Build the chart candle DataFrame."""
        return CandleFrameBuilder(self.config.local_timezone).frame(candles)

    def display(
        self,
        *,
        frames: TaskResultFrames,
        candles: pd.DataFrame | None = None,
    ) -> Figure:
        """Render and display the chart."""
        candle_frame = self.candle_frame(self.candles()) if candles is None else candles
        fig = BacktestChartRenderer(self.config).render(candles=candle_frame, frames=frames)
        plt.show()
        return fig
