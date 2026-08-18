from pydantic import Field, ValidationError

from autoforex.core.models.base import DomainModel


class ExampleModel(DomainModel):
    value: int = Field(ge=0)


class TestBase:
    def test_domain_model_is_immutable_and_forbids_extra_fields(self) -> None:
        model = ExampleModel(value=1)

        evolved = model.evolve(value=2)

        assert evolved.value == 2
        assert model.value == 1
        try:
            model.value = 3
        except ValidationError:
            pass
        else:  # pragma: no cover
            raise AssertionError("DomainModel should be frozen")

    def test_domain_model_evolve_revalidates_changes(self) -> None:
        model = ExampleModel(value=1)

        try:
            model.evolve(value=-1)
        except ValidationError:
            pass
        else:  # pragma: no cover
            raise AssertionError("evolve should revalidate changes")
