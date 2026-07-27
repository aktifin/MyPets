"""Compatibility adapter for aggregated proactive-care notices.

The existing public response contract intentionally keeps the original three notice kinds.
A multi-pet summary is still a gentle low-state notice at that boundary, while its stable
``multi-pet:`` key, title and action make the aggregation explicit to clients.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from . import proactive_care as _rules

_original_aggregate = _rules.aggregate_multi_pet_candidates


def _response_compatible_aggregate(
    candidates: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    values = _original_aggregate(candidates)
    for item in values:
        if str(item.get("notice_key") or "").startswith("multi-pet:"):
            item["kind"] = "low_state"
    return values


_rules.aggregate_multi_pet_candidates = _response_compatible_aggregate
