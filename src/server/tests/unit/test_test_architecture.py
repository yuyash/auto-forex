from __future__ import annotations

from pathlib import Path


class TestUnitTestArchitecture:
    def test_every_handwritten_server_module_has_a_named_unit_test_module(self) -> None:
        package_root = Path(__file__).resolve().parents[2] / "src" / "autoforex" / "server"
        unit_root = Path(__file__).resolve().parent
        production_modules = {
            path.stem for path in package_root.glob("*.py") if path.name != "__init__.py"
        }
        tested_modules = {
            path.stem.removeprefix("test_")
            for path in unit_root.glob("test_*.py")
            if path.name != Path(__file__).name
        }

        assert production_modules <= tested_modules, (
            "server modules missing a corresponding unit test module: "
            f"{sorted(production_modules - tested_modules)}"
        )
