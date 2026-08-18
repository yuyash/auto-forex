from __future__ import annotations

from collections.abc import Iterator

import pytest

from autoforex.core import SqlResultStore


@pytest.fixture
def sql_result_store() -> Iterator[SqlResultStore]:
    """Provide an isolated SQL result store and dispose its engine."""
    store = SqlResultStore("sqlite:///:memory:")
    try:
        yield store
    finally:
        store.close()
