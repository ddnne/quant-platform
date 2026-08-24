"""Phase 3.5 — validation rules for the Premium core closed loop.

The CF Worker records one `DatasetResult` per (run, dataset). The run as a
whole is `pass` iff every dataset `pass`ed. This module is the single source
of truth for what `pass` / `fail` means; both the worker and the local
sync/ops tooling should agree with it.

A dataset **fails** when:

* the upstream fetch returned an error string, OR
* `rows_seen > 0` but `rows_inserted == 0` AND `rows_revisions == 0`
  (silent schema miss), OR
* `available_at_min` is null/empty after the run (PIT column missing).

A dataset **passes** when:

* `rows_seen >= 0` AND `rows_inserted > 0` OR `rows_seen == 0` (genuinely
  empty — many Premium endpoints return zero rows on non-trading days).

Failures are never reported as success: a run with any failed dataset has
overall status `partial` (if some passed) or `fail` (if all failed).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Explicit re-export here so this module is the canonical Python entry point.
from ingestion.jquants.catalog import (  # noqa: F401
    PREMIUM_CORE_DATASETS,
    is_premium_core,
    list_datasets,
)


@dataclass(frozen=True)
class DatasetResult:
    """One dataset's outcome in a run. Mirrors the Worker's DatasetResult."""

    dataset: str
    status: str  # "pass" | "fail"
    started_at: str
    finished_at: str
    rows_seen: int = 0
    rows_inserted: int = 0
    rows_revisions: int = 0
    available_at_min: str | None = None
    available_at_max: str | None = None
    detail: str = ""
    raw_key: str | None = None

    def as_log_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunSummary:
    """Run-level roll-up. Mirrors the Worker's RunSummary."""

    started_at: str
    finished_at: str
    status: str  # "pass" | "fail" | "partial"
    dataset_count: int
    passed: int
    failed: int
    rows_inserted: int
    triggered_by: str  # "cron" | "manual"
    failures: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def as_log_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["failures"] = [{"dataset": ds, "detail": det} for ds, det in self.failures]
        return d


def classify_dataset(
    *,
    dataset: str,
    error: str = "",
    rows_seen: int = 0,
    rows_inserted: int = 0,
    rows_revisions: int = 0,
    available_at_min: str | None = None,
) -> str:
    """Apply the closed-loop pass/fail rule to one dataset's outcome.

    Returns ``"pass"`` or ``"fail"``. The rule is documented at the top of
    this module. Used both by the local sync script's own validation log and
    by tests; the CF Worker's TypeScript re-implements the same rule.
    """
    if error:
        return "fail"
    if rows_seen > 0 and rows_inserted == 0 and rows_revisions == 0:
        # Silent schema miss — normalize produced nothing for non-empty input.
        return "fail"
    if available_at_min is None and rows_inserted > 0:
        # PIT column missing — would be unreadable downstream.
        return "fail"
    return "pass"


def classify_run(results: list[DatasetResult]) -> str:
    """Roll up per-dataset statuses into a run status."""
    if not results:
        return "fail"
    if all(r.status == "pass" for r in results):
        return "pass"
    if all(r.status == "fail" for r in results):
        return "fail"
    return "partial"


def required_dataset_coverage(
    implemented: list[str],
    *,
    required: tuple[str, ...] = PREMIUM_CORE_DATASETS,
) -> dict[str, bool]:
    """Map each required dataset to whether it has an implementation.

    Used by tests to fail loudly when a required Premium core id has no job.
    A dataset with an explicit failure reason is still "implemented" — the
    contract is "every required id has a job, no silent skip".
    """
    have = set(implemented)
    return {did: did in have for did in required}


def assert_no_addon_in_required(
    scheduled: list[str], *,
    addon_ids: tuple[str, ...] = tuple(list_datasets("addon")),
) -> None:
    """Fail if any addon id appears in the scheduled (required) set."""
    leaked = sorted(set(scheduled) & set(addon_ids))
    if leaked:
        raise AssertionError(
            f"addon datasets must not be in the required schedule: {leaked}"
        )
