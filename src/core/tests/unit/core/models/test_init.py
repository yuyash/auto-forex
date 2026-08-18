from autoforex.core.models import Currency, CurrencyPair, Metadata, Money


class TestInit:
    def test_models_package_exports_shared_primitives(self) -> None:
        assert Currency.of("USD").code == "USD"
        assert CurrencyPair.of("EUR_USD").symbol == "EUR_USD"
        assert Metadata.of(source="unit").get("source") == "unit"
        assert Money.of("10", "USD").amount.is_finite()
