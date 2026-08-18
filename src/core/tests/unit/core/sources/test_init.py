from autoforex.core.sources import (
    CSVCandleSchema,
    CSVDataSource,
    CSVTickSchema,
    FilteredDataSource,
    SpreadFilter,
    SpreadFilteredDataSource,
    TickGranularityFilter,
)


class TestInit:
    def test_sources_package_exports_csv_source(self) -> None:
        assert CSVDataSource.__name__ == "CSVDataSource"
        assert CSVTickSchema().timestamp == "timestamp"
        assert CSVCandleSchema().granularity == "granularity"
        assert FilteredDataSource.__name__ == "FilteredDataSource"
        assert SpreadFilter.__name__ == "SpreadFilter"
        assert SpreadFilteredDataSource.__name__ == "SpreadFilteredDataSource"
        assert TickGranularityFilter.__name__ == "TickGranularityFilter"
