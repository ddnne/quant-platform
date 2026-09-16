"""Build the idle exact-five Cron control from compiled selector output.

Worker admission checks profile/closure identity and catalog month bounds.
Selector membership is this producer: in-period
``compiled_period_collection_segments`` (same function as
``compiled_candidate_selectors``) plus ``declared_coverage_segments`` and
candidate-loop ``_missing_compiled_segments`` extras. Does not PUT R2.
The 24-job parse bound is a source control ceiling, not an authorized
cloud execution plan.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from data_contracts.coverage import coverage_contract_for
from research.ready_manifest import load_exact_four_pilot_ready_binding
from storage.coverage_ledger import (
    compiled_period_collection_segments,
    declared_coverage_segments,
)

EXACT_FIVE_ACQUISITION_KEY = "control/exact_five_compiled_acquisition.json"
EXACT_FIVE_ACQUISITION_SCHEMA = "exact-five-compiled-acquisition/v1"
# Source parse bound matching the Worker control. Not an authorized 24-job
# or 64-job cloud plan; putting the object remains a later mutation.
MAX_JOBS = 24
_MONTH_ID = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_JST = timezone(timedelta(hours=9))


class ExactFiveAcquisitionControlError(ValueError):
    """Selector or pin is outside catalog/profile bounds."""


def _pins() -> dict[str, Any]:
    binding = load_exact_four_pilot_ready_binding()
    periods = {
        (str(profile.period_start), str(profile.period_end))
        for profile in binding.profiles
        if getattr(profile, "period_start", None)
        and getattr(profile, "period_end", None)
    }
    if len(periods) != 1:
        raise ExactFiveAcquisitionControlError("profile period is missing")
    period_start, period_end = next(iter(periods))
    datasets = tuple(str(item) for item in binding.required_datasets)
    if not datasets:
        raise ExactFiveAcquisitionControlError("profile datasets are missing")
    return {
        "profile_id": binding.profile_id,
        "profile_digest": binding.profile_digest,
        "dependency_closure_digest": binding.closure_set_digest,
        "period_start": period_start,
        "period_end": period_end,
        "datasets": frozenset(datasets),
    }


def compiled_bootstrap_selectors() -> tuple[dict[str, str], ...]:
    """In-period months. Same producer as ``compiled_candidate_selectors``."""

    pins = _pins()
    planned = compiled_period_collection_segments(
        tuple(sorted(pins["datasets"])),
        period_start=pins["period_start"],
        period_end=pins["period_end"],
    )
    return tuple(
        {"dataset": item.dataset, "segment_id": item.segment_id} for item in planned
    )


def compiled_fill_selectors(
    *,
    selected_event_dates: Mapping[str, frozenset[str]],
    bar_split_interval_start: str | None = None,
    lookback_start: str | None = None,
    datasets: Sequence[str] | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> tuple[dict[str, str], ...]:
    """Pre-period and in-period months from ``declared_coverage_segments``.

    Same fill used by ``_missing_compiled_segments`` after evaluate.
    """

    pins = _pins()
    start = period_start or pins["period_start"]
    end = period_end or pins["period_end"]
    wanted = tuple(datasets) if datasets is not None else tuple(sorted(pins["datasets"]))
    planned = declared_coverage_segments(
        wanted,
        lookback_start=lookback_start or start,
        period_start=start,
        period_end=end,
        selected_event_dates=selected_event_dates,
        bar_split_interval_start=bar_split_interval_start,
    )
    return tuple(
        {"dataset": item.dataset, "segment_id": item.segment_id} for item in planned
    )


def _today_jst() -> date:
    return datetime.now(_JST).date()


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def catalog_collection_window(dataset: str, segment_id: str) -> tuple[str, str]:
    """Canonical full-month window. Mirrors Worker catalog admission."""

    pins = _pins()
    if dataset not in pins["datasets"] or _MONTH_ID.fullmatch(segment_id) is None:
        raise ExactFiveAcquisitionControlError("selector is not a compiled catalog month")
    policy = coverage_contract_for(dataset)
    if policy.segment_granularity != "calendar_month":
        raise ExactFiveAcquisitionControlError("selector grain is not calendar_month")
    history_start = date.fromisoformat(str(policy.history_target_start))
    period_end = date.fromisoformat(pins["period_end"])
    today = _today_jst()
    year = int(segment_id[:4])
    month = int(segment_id[5:7])
    if not 1 <= month <= 12:
        raise ExactFiveAcquisitionControlError("selector is not a compiled catalog month")
    if (
        segment_id < history_start.isoformat()[:7]
        or segment_id > period_end.isoformat()[:7]
        or segment_id > today.isoformat()[:7]
    ):
        raise ExactFiveAcquisitionControlError("selector is outside catalog bounds")
    start = history_start if history_start.isoformat()[:7] == segment_id else date(year, month, 1)
    end = today if today.isoformat()[:7] == segment_id else _month_end(year, month)
    if start > end:
        raise ExactFiveAcquisitionControlError("selector is outside catalog bounds")
    return start.isoformat(), end.isoformat()


def build_exact_five_compiled_acquisition_control(
    selectors: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """Pin current profile/closure and emit the Cron control document."""

    pins = _pins()
    if not 1 <= len(selectors) <= MAX_JOBS:
        raise ExactFiveAcquisitionControlError("jobs out of range")
    jobs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in selectors:
        if set(row) != {"dataset", "segment_id"}:
            raise ExactFiveAcquisitionControlError("selector fields are closed")
        dataset = row["dataset"]
        segment_id = row["segment_id"]
        if type(dataset) is not str or type(segment_id) is not str:
            raise ExactFiveAcquisitionControlError("selector fields are closed")
        catalog_collection_window(dataset, segment_id)
        key = (dataset, segment_id)
        if key in seen:
            raise ExactFiveAcquisitionControlError("duplicate selector")
        seen.add(key)
        jobs.append({"dataset": dataset, "segment_id": segment_id})
    return {
        "schema": EXACT_FIVE_ACQUISITION_SCHEMA,
        "profile_id": pins["profile_id"],
        "profile_digest": pins["profile_digest"],
        "dependency_closure_digest": pins["dependency_closure_digest"],
        "jobs": jobs,
        "cursor": 0,
        "attempts": 0,
        "lease": None,
        "last": None,
    }
