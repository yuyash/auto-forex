import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "autoforex" / "snowball"

ADAPTER_SYMBOLS = {
    "StrategyAction",
    "StrategyContext",
    "StrategyDecisionCode",
    "StrategyDecisionReason",
    "StrategyEvent",
    "StrategyState",
    "TaskType",
    "TradeSide",
}

OLD_SERVICE_REFERENCES = {
    "autoforex.snowball.services.close_service",
    "autoforex.snowball.services.counter_service",
    "autoforex.snowball.services.cycle_service",
    "autoforex.snowball.services.entry_service",
    "autoforex.snowball.services.event_factory",
    "autoforex.snowball.services.grid_policy",
    "autoforex.snowball.services.grid_selectors",
    "autoforex.snowball.services.position_sizing",
    "autoforex.snowball.services.pricing",
    "autoforex.snowball.services.protection_service",
    "autoforex.snowball.services.rebuild_service",
    "autoforex.snowball.services.stop_loss_close_service",
    "autoforex.snowball.services.stop_loss_policy",
    "autoforex.snowball.services.take_profit_close_service",
    "autoforex.snowball.services.take_profit_policy",
    "autoforex.snowball.services.tick_stages",
    "SnowballCloseService",
    "SnowballPricing",
}


def imported_core_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "autoforex.core":
            symbols.update(alias.name for alias in node.names)
    return symbols


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def python_paths() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


class TestSnowballArchitectureBoundaries:
    def test_domain_models_and_events_do_not_import_core_adapter_types(self) -> None:
        domain_paths = [*sorted((PACKAGE / "models").glob("*.py")), PACKAGE / "events.py"]

        violations = {
            path.relative_to(ROOT).as_posix(): sorted(imported_core_symbols(path) & ADAPTER_SYMBOLS)
            for path in domain_paths
            if imported_core_symbols(path) & ADAPTER_SYMBOLS
        }

        assert violations == {}

    def test_market_pricing_has_no_config_or_policy_dependencies(self) -> None:
        modules = imported_modules(PACKAGE / "services" / "market_pricing.py")

        assert "autoforex.snowball.config" not in modules
        assert "autoforex.snowball.enums" not in modules
        assert not any(
            module.startswith("autoforex.snowball.services.policies") for module in modules
        )

    def test_old_service_paths_are_not_used(self) -> None:
        violations: dict[str, list[str]] = {}
        for path in python_paths():
            text = path.read_text()
            matches = sorted(reference for reference in OLD_SERVICE_REFERENCES if reference in text)
            if matches:
                violations[path.relative_to(ROOT).as_posix()] = matches

        assert violations == {}
