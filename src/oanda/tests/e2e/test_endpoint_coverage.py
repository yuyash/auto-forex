from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from autoforex.oanda.gateways.clients import (
    OandaAccountsApi,
    OandaOrdersApi,
    OandaPositionsApi,
    OandaPricingApi,
    OandaTradesApi,
    OandaTransactionsApi,
)
from tests.e2e.coverage import covered_endpoints

_ENDPOINT_CLIENTS: Mapping[str, type[object]] = {
    "accounts": OandaAccountsApi,
    "orders": OandaOrdersApi,
    "positions": OandaPositionsApi,
    "pricing": OandaPricingApi,
    "trades": OandaTradesApi,
    "transactions": OandaTransactionsApi,
}


class TestGatewayEndpointCoverage:
    def test_every_gateway_endpoint_has_an_e2e_scenario(self, request: Any) -> None:
        expected = {
            f"{namespace}.{method_name}"
            for namespace, client in _ENDPOINT_CLIENTS.items()
            for method_name, method in vars(client).items()
            if not method_name.startswith("_") and callable(method)
        }
        covered = {
            endpoint for item in request.session.items for endpoint in covered_endpoints(item.obj)
        }

        missing = sorted(expected - covered)
        unknown = sorted(covered - expected)

        assert not missing, f"OANDA endpoints missing E2E coverage: {', '.join(missing)}"
        assert not unknown, f"E2E coverage declares unknown OANDA endpoints: {', '.join(unknown)}"
