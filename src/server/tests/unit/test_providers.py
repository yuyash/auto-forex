from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

import autoforex.server.providers as providers_module
from autoforex.server.providers import ProviderFactory, ProviderName


class FakeOandaProvider:
    settings: Any = None

    @classmethod
    def from_settings(cls, settings: Any) -> FakeOandaProvider:
        cls.settings = settings
        return cls()


class TestProviders:
    def test_loads_oanda_only_when_the_provider_is_requested(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = object()
        fake_module = SimpleNamespace(OandaProvider=FakeOandaProvider)
        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def load_optional(*args: Any, **kwargs: Any) -> SimpleNamespace:
            calls.append((args, kwargs))
            return fake_module

        monkeypatch.setattr(providers_module, "require_optional_dependency", load_optional)

        provider = ProviderFactory().create(
            ProviderName.OANDA,
            settings=cast(Any, settings),
        )

        assert isinstance(provider, FakeOandaProvider)
        assert FakeOandaProvider.settings is settings
        assert calls == [
            (
                ("autoforex.oanda",),
                {
                    "extra": "oanda",
                    "feature": "OANDA provider support",
                },
            )
        ]

    def test_rejects_an_unsupported_provider_value(self) -> None:
        unsupported = cast(ProviderName, SimpleNamespace(value="unsupported"))

        with pytest.raises(ValueError, match="unsupported account provider"):
            ProviderFactory().create(
                unsupported,
                settings=cast(Any, object()),
            )
