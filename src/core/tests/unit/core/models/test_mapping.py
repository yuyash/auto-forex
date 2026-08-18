from typing import Any, cast

import pytest

from autoforex.core.models.mapping import MappingValueObject


class TestMapping:
    def test_mapping_value_object_hides_mutable_mapping(self) -> None:
        values = MappingValueObject.of(strategy_name="snowball")

        assert values.get("strategy_name") == "snowball"
        assert values.to_dict() == {"strategy_name": "snowball"}
        assert values.with_value("version", 1).to_dict() == {
            "strategy_name": "snowball",
            "version": 1,
        }

        immutable_values = cast(Any, values.values)
        with pytest.raises(TypeError):
            immutable_values["strategy_name"] = "changed"

    def test_mapping_value_object_deep_freezes_nested_values(self) -> None:
        values = MappingValueObject.model_validate(
            {"settings": {"symbols": ["USD_JPY"], "limits": {"max": 1}}}
        )

        settings = values["settings"]
        symbols = settings["symbols"]
        limits = settings["limits"]

        assert symbols == ("USD_JPY",)
        with pytest.raises(TypeError):
            settings["symbols"] = ("EUR_USD",)
        with pytest.raises(TypeError):
            limits["max"] = 2

        plain = values.to_dict()
        plain["settings"]["symbols"].append("EUR_USD")

        assert values["settings"]["symbols"] == ("USD_JPY",)

    def test_mapping_value_object_splits_plain_and_jsonable_output(self) -> None:
        values = MappingValueObject.model_validate(
            {"settings": {"symbols": ("USD_JPY",), "labels": frozenset({"primary"})}}
        )

        assert values.to_plain() == {
            "settings": {
                "symbols": ("USD_JPY",),
                "labels": frozenset({"primary"}),
            }
        }
        assert values.to_jsonable() == {
            "settings": {
                "symbols": ["USD_JPY"],
                "labels": ["primary"],
            }
        }
        assert values.to_dict() == values.to_jsonable()
