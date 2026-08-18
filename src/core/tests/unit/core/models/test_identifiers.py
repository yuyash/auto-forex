from autoforex.core.models import new_uuid


class TestIdentifiers:
    def test_new_uuid_uses_uuidv7(self) -> None:
        assert new_uuid().version == 7
