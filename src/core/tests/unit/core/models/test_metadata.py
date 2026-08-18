from autoforex.core.models import Metadata


class TestMetadata:
    def test_metadata_is_mapping_value_object(self) -> None:
        metadata = Metadata.of(provider="csv")

        assert metadata["provider"] == "csv"
        assert "provider" in metadata
        assert list(metadata.keys()) == ["provider"]
