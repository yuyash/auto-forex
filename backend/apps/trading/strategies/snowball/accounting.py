"""Account metric updates for the Snowball strategy."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from apps.trading.dataclasses.tick import Tick
from apps.trading.money import AccountCurrency
from apps.trading.models.state import ExecutionState
from apps.trading.strategies.snowball.cycle_state import SnowballStrategyState
from apps.trading.strategies.snowball.protection import SNOWBALL_PROTECTION
from apps.trading.utils import Instrument


class SnowballAccountMetricsUpdater:
    """Refresh NAV and margin-ratio metrics from current tick/account state."""

    def __init__(
        self,
        *,
        margin_ratio_func: Callable[..., Decimal] | None = None,
    ) -> None:
        self.margin_ratio_func = margin_ratio_func
        self._instrument_cache: dict[str, Instrument] = {}
        self._account_currency_cache: dict[str, AccountCurrency] = {}

    def update(
        self,
        *,
        state: ExecutionState,
        ss: SnowballStrategyState,
        tick: Tick,
        instrument: str,
        account_currency: str,
    ) -> Decimal:
        """Update account metrics and return the current margin ratio percentage."""
        if state.current_balance:
            ss.account_balance = Decimal(str(state.current_balance))

        instrument_obj = self._instrument(instrument)
        account_currency_obj = self._account_currency(account_currency)
        conversion_rate = instrument_obj.quote_to_account_rate(tick.mid, account_currency_obj)
        unrealized, long_units, short_units = self._account_exposure(
            ss=ss,
            tick=tick,
            conversion_rate=conversion_rate,
        )
        ss.set_entry_units_cache(long_units=long_units, short_units=short_units)
        ss.account_nav = ss.account_balance + unrealized
        if ss.account_nav <= 0:
            ss.account_nav = ss.account_balance

        ratio = (
            self._margin_ratio_func()(
                state=state,
                ss=ss,
                instrument=instrument,
                account_currency=account_currency,
            )
            if self._uses_external_margin_ratio()
            else self._margin_ratio_from_exposure(
                nav=ss.account_nav,
                mid=tick.mid,
                conversion_rate=conversion_rate,
                long_units=long_units,
                short_units=short_units,
            )
        )
        ss.set_metric("margin_ratio", ratio / Decimal("100"), defer=self._defer_metric_strings(ss))
        return ratio

    def _margin_ratio_func(self) -> Callable[..., Decimal]:
        return self.margin_ratio_func or SNOWBALL_PROTECTION.margin_ratio

    def _uses_external_margin_ratio(self) -> bool:
        return self.margin_ratio_func is not None or "margin_ratio" in SNOWBALL_PROTECTION.__dict__

    @staticmethod
    def _defer_metric_strings(ss: SnowballStrategyState) -> bool:
        return bool(getattr(ss, "_defer_metric_strings", False))

    def _instrument(self, instrument: str) -> Instrument:
        cached = self._instrument_cache.get(instrument)
        if cached is None:
            cached = Instrument(instrument)
            self._instrument_cache[instrument] = cached
        return cached

    def _account_currency(self, account_currency: str) -> AccountCurrency:
        cached = self._account_currency_cache.get(account_currency)
        if cached is None:
            cached = AccountCurrency(account_currency)
            self._account_currency_cache[account_currency] = cached
        return cached

    def _account_exposure(
        self,
        *,
        ss: SnowballStrategyState,
        tick: Tick,
        conversion_rate: Decimal,
    ) -> tuple[Decimal, int, int]:
        unrealized = Decimal("0")
        long_units = 0
        short_units = 0
        for entry in ss.iter_entries():
            entry_units = entry.units
            if entry.is_long:
                long_units += abs(entry_units)
                unrealized += (
                    (tick.bid - entry.entry_price) * Decimal(entry_units) * conversion_rate
                )
            else:
                short_units += abs(entry_units)
                unrealized += (
                    (entry.entry_price - tick.ask) * Decimal(entry_units) * conversion_rate
                )
        return unrealized, long_units, short_units

    @staticmethod
    def _margin_ratio_from_exposure(
        *,
        nav: Decimal,
        mid: Decimal,
        conversion_rate: Decimal,
        long_units: int,
        short_units: int,
    ) -> Decimal:
        if nav <= 0 or mid <= 0:
            return Decimal("0")
        total_units = max(long_units, short_units)
        if total_units == 0:
            return Decimal("0")
        required = mid * Decimal(total_units) * Decimal("0.04") * conversion_rate
        return (required / nav) * Decimal("100")
