from __future__ import annotations

import autoforex.oanda as oanda


class TestInit:
    def test_package_exports_public_adapter_api(self) -> None:
        for name in (
            "OandaAccountManager",
            "OandaBroker",
            "OandaDataSource",
            "OandaGateway",
            "OandaProvider",
            "OandaSettings",
        ):
            assert name in oanda.__all__
            assert getattr(oanda, name).__name__ == name
