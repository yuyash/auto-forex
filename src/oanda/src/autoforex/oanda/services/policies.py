"""Broker service response policies."""

from __future__ import annotations

from autoforex.oanda.errors import OandaResponsePolicy


class OandaMutationResponsePolicy:
    """Classify OANDA mutation responses accepted by broker services."""

    expected_statuses = frozenset({200, 201, 400, 404})

    @classmethod
    def raise_for_unexpected(cls, response: object) -> None:
        """Raise for mutation response statuses outside the broker contract."""
        status = int(getattr(response, "status", 0) or 0)
        if status in cls.expected_statuses:
            return
        raise OandaResponsePolicy.error_from_response(response)
