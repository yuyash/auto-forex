from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from autoforex.core.models import Currency, CurrencyPair, Money, Pips, Units


class TestMoney:
    def test_currency_pair_and_money_normalize_values(self) -> None:
        pair = CurrencyPair.of("usd/jpy")
        money = Money.of("150.10", pair.quote)

        assert pair.symbol == "USD_JPY"
        assert str(pair.base) == "USD"
        assert pair.pip_size == Decimal("0.01")
        assert CurrencyPair.of("EUR_USD").pip_size == Decimal("0.0001")
        assert money.currency == Currency(code="JPY")

    def test_currency_rejects_unknown_iso_4217_code(self) -> None:
        with pytest.raises(ValidationError, match="unknown ISO 4217 currency code"):
            Currency.of("ZZZ")

    def test_money_requires_matching_currency_and_positive_amount(self) -> None:
        money = Money.of("10", "USD")

        assert money.require_currency(Currency.of("USD")) == money
        assert money.require_positive() == money
        with pytest.raises(ValueError, match="currency mismatch"):
            money.require_currency(Currency.of("JPY"))
        with pytest.raises(ValueError, match="greater than 0"):
            Money.of("0", "USD").require_positive()

    def test_money_coerce_accepts_raw_amount_and_existing_money(self) -> None:
        money = Money.model_validate({"amount": "12.50", "currency": "USD"})

        assert money == Money.of("12.50", "USD")
        assert Money.coerce("12.50", "USD") == money
        assert Money.coerce_positive("12.50", "USD") == money
        assert Money.coerce(money, "USD") == money
        with pytest.raises(ValueError, match="currency mismatch"):
            Money.coerce(money, "JPY")
        with pytest.raises(ValueError, match="greater than 0"):
            Money.coerce_positive("0", "USD")

    def test_decimal_value_tuple_of_coerces_sequences(self) -> None:
        assert Pips.tuple_of(("1", Decimal("2"))) == (Pips("1"), Pips("2"))
        with pytest.raises(TypeError, match="sequence"):
            Pips.tuple_of("1,2")

    def test_money_string_displays_amount_rounded_to_two_decimal_places(self) -> None:
        assert str(Money.of("150.124", "JPY")) == "150.12 JPY"
        assert str(Money.of("150.125", "JPY")) == "150.13 JPY"
        assert str(Money.of("10", "USD")) == "10.00 USD"

    def test_money_and_quantity_values_reject_primitive_numbers(self) -> None:
        primitive_amount: Any = 10
        primitive_units: Any = 1000
        with pytest.raises(TypeError, match="money amount"):
            Money.of(primitive_amount, "USD")
        with pytest.raises(TypeError, match="money amount"):
            Money.model_validate({"amount": primitive_amount, "currency": "USD"})
        with pytest.raises(TypeError, match="units"):
            Units(primitive_units)
