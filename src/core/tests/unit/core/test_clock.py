from datetime import UTC, datetime

import pytest

from autoforex.core import ManualClock, local_timezone, now


class TestClock:
    def test_now_returns_aware_local_datetime(self) -> None:
        current = now()

        assert current.tzinfo is not None
        # Matches the system local zone used by astimezone().
        assert current.utcoffset() == datetime.now().astimezone().utcoffset()

    def test_local_timezone_matches_system_zone(self) -> None:
        zone = local_timezone()

        assert zone is not None
        assert datetime.now().astimezone().utcoffset() == datetime.now(zone).utcoffset()

    def test_manual_clock_controls_now(self) -> None:
        clock = ManualClock(datetime(2020, 1, 1, tzinfo=UTC))

        assert now(clock) == datetime(2020, 1, 1, tzinfo=UTC)

        clock.set(datetime(2020, 1, 2, tzinfo=UTC))

        assert now(clock) == datetime(2020, 1, 2, tzinfo=UTC)

    def test_manual_clock_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            ManualClock(datetime(2020, 1, 1))
