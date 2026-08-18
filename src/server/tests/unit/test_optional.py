from __future__ import annotations

from types import ModuleType

import pytest

import autoforex.server.optional as optional_module
from autoforex.server.optional import OptionalDependencyError, require_optional_dependency


class TestRequireOptionalDependency:
    def test_returns_an_installed_module(self) -> None:
        module = require_optional_dependency(
            "sys",
            extra="unused",
            feature="test feature",
        )

        assert isinstance(module, ModuleType)

    def test_reports_the_extra_needed_for_a_missing_package(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def missing_module(name: str) -> ModuleType:
            raise ModuleNotFoundError(name=name)

        monkeypatch.setattr(optional_module, "import_module", missing_module)

        with pytest.raises(
            OptionalDependencyError,
            match=r'pip install "auto-forex-server\[oanda\]"',
        ):
            require_optional_dependency(
                "autoforex.oanda",
                extra="oanda",
                feature="OANDA provider support",
            )

    def test_preserves_errors_from_a_broken_optional_package(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken_module(name: str) -> ModuleType:
            raise ModuleNotFoundError(name="transitive_dependency")

        monkeypatch.setattr(optional_module, "import_module", broken_module)

        with pytest.raises(ModuleNotFoundError) as error:
            require_optional_dependency(
                "autoforex.oanda",
                extra="oanda",
                feature="OANDA provider support",
            )

        assert error.value.name == "transitive_dependency"
