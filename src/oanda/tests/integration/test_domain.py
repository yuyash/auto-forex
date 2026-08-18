from __future__ import annotations

from autoforex.core import Account, Order, Position, Trade, Transaction

from autoforex.oanda.snapshots import (
    OandaAccount,
    OandaOrder,
    OandaPosition,
    OandaTrade,
    OandaTransaction,
)


class TestDomain:
    def test_domain_models_compose_core_models_without_inheriting_them(self) -> None:
        assert not issubclass(OandaAccount, Account)
        assert not issubclass(OandaOrder, Order)
        assert not issubclass(OandaPosition, Position)
        assert not issubclass(OandaTrade, Trade)
        assert not issubclass(OandaTransaction, Transaction)
