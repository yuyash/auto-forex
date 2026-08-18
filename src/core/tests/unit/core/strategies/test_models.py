from decimal import Decimal
from typing import Any, cast

import pytest

from autoforex.core import StrategyParameters, StrategyState


class TestModels:
    def test_strategy_parameters_and_state_are_modeled_value_objects(self) -> None:
        parameters = StrategyParameters.of(risk_percent=Decimal("1.5"))
        state = StrategyState.of(seen_ticks=1)

        assert parameters.require("risk_percent") == Decimal("1.5")
        assert parameters.with_value("max_positions", 2).to_dict() == {
            "risk_percent": Decimal("1.5"),
            "max_positions": 2,
        }
        assert state.get("seen_ticks") == 1

        immutable_parameters = cast(Any, parameters.values)
        immutable_state = cast(Any, state.values)
        with pytest.raises(TypeError):
            immutable_parameters["risk_percent"] = Decimal("2.0")
        with pytest.raises(TypeError):
            immutable_state["seen_ticks"] = 2
