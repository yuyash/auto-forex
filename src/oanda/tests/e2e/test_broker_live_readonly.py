from __future__ import annotations

from autoforex.oanda import OandaProvider, OandaSettings
from autoforex.oanda.models import OandaStreamResponse
from tests.e2e.coverage import covers_endpoints


class TestBrokerLiveReadonly:
    @covers_endpoints("orders.list_orders")
    def test_live_list_orders(self, oanda_provider: OandaProvider) -> None:
        orders = oanda_provider.broker.list_orders(count=10)

        assert isinstance(orders, tuple)

    @covers_endpoints("orders.list_pending_orders")
    def test_live_list_pending_orders(self, oanda_provider: OandaProvider) -> None:
        pending_orders = oanda_provider.broker.list_pending_orders()

        assert isinstance(pending_orders, tuple)

    @covers_endpoints("positions.list_positions")
    def test_live_list_positions(self, oanda_provider: OandaProvider) -> None:
        positions = oanda_provider.broker.list_positions()

        assert isinstance(positions, tuple)

    @covers_endpoints("positions.list_open_positions")
    def test_live_list_open_positions(self, oanda_provider: OandaProvider) -> None:
        open_positions = oanda_provider.broker.list_open_positions()

        assert isinstance(open_positions, tuple)

    @covers_endpoints("trades.list_trades")
    def test_live_list_trades(self, oanda_provider: OandaProvider) -> None:
        trades = oanda_provider.broker.list_trades(count=10)

        assert isinstance(trades, tuple)

    @covers_endpoints("trades.list_open_trades")
    def test_live_list_open_trades(self, oanda_provider: OandaProvider) -> None:
        open_trades = oanda_provider.broker.list_open_trades()

        assert isinstance(open_trades, tuple)

    @covers_endpoints("transactions.list_transactions")
    def test_live_list_transactions(self, oanda_provider: OandaProvider) -> None:
        transaction_page = oanda_provider.broker.list_transactions(page_size=100)

        assert transaction_page["lastTransactionID"]

    @covers_endpoints("transactions.get_transaction")
    def test_live_get_transaction(self, oanda_provider: OandaProvider) -> None:
        last_transaction_id = _last_transaction_id(oanda_provider)
        transaction = oanda_provider.broker.get_transaction(last_transaction_id)

        assert transaction.id.value == last_transaction_id

    @covers_endpoints("transactions.get_transaction_range")
    def test_live_get_transaction_range(self, oanda_provider: OandaProvider) -> None:
        last_transaction_id = _last_transaction_id(oanda_provider)
        transactions = oanda_provider.broker.get_transaction_range(
            from_id=last_transaction_id,
            to_id=last_transaction_id,
        )

        assert transactions

    @covers_endpoints("transactions.get_transactions_since")
    def test_live_get_transactions_since(self, oanda_provider: OandaProvider) -> None:
        last_transaction_id = _last_transaction_id(oanda_provider)
        transactions = oanda_provider.broker.get_transactions_since(last_transaction_id)

        assert isinstance(transactions, tuple)

    @covers_endpoints("transactions.stream_transactions")
    def test_live_transaction_stream_endpoint_connects(
        self,
        oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        broker = oanda_provider.broker
        response = broker.gateway.transactions.stream_transactions(oanda_settings.account_id)
        try:
            assert response.status == 200
            assert isinstance(response.raw, OandaStreamResponse)
            assert response.raw.stream_kind == "transactions"
        finally:
            close = getattr(response.raw.stream, "close", None)
            if close is not None:
                close()


def _last_transaction_id(provider: OandaProvider) -> str:
    page = provider.broker.list_transactions(page_size=100)
    return str(page["lastTransactionID"])
