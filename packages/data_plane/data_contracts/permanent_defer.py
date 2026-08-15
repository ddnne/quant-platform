"""Permanent DEFER datasets — fail-closed exclude for research history loads.

W44/W47 residual lock (see ``docs/phase62_residual_status.md`` and
``docs/proof/w0815ak_w44_defer_lock_20260815.md``):

* Dataset COMPLETE was **21** at W44; residual PARTIAL set was n=5.
* Densify on remaining classes is **FORBIDDEN** unless residual SoT re-opens.
* Research **history** loads must not treat remaining DEFER as full-history COMPLETE.

**W68 supersession (tip4 only):** ``PD-MX-EARN-TIP`` / ``fins_earnings_date`` tip
months ``2026-01…04`` were FINAL permanent DEFER at W44 because vendor tip had
``NO_RAW`` / ``HAS_RAW_SEALABLE=0``. W68 live API probe returned nz window_ok
raw for all four months, sealed with signed SUCCESS receipts
(903892 / 903890 / 903889 / 903888) and remote D1 COMPLETE **104/104** →
Dataset COMPLETE **22**. Those four months only are **no longer** fail-closed
via this module. Other PD ids (bars_am, OTC, master, earn_cal) remain.

Ops / tip / SCD2 CURRENT reads are out of scope for this module — only
history-grade research loaders should call the guards below.
"""

from __future__ import annotations

from typing import Iterable, Sequence

# Canonical permanent DEFER dataset ids (n=4 after W68). Names match residual SoT.
PERMANENT_DEFER_DATASETS: frozenset[str] = frozenset(
    {
        "equities_master",  # PD-D2-MASTER (MISDATE + PRE_PLAN)
        "equities_earnings_calendar",  # PD-D4-EARN-CAL (vendor tip-only history)
        "equities_bars_daily_am",  # PD-D4-BARS-AM (tip-only AM)
        "jsda_otc_bond_reference_prices",  # PD-D5-JSDA-OTC (tip island only)
    }
)

# Stable short ids used in residual / densify ban tables (active fail-closed).
PERMANENT_DEFER_IDS: dict[str, str] = {
    "equities_master": "PD-D2-MASTER",
    "equities_earnings_calendar": "PD-D4-EARN-CAL",
    "equities_bars_daily_am": "PD-D4-BARS-AM",
    "jsda_otc_bond_reference_prices": "PD-D5-JSDA-OTC",
}

# Historical / superseded PD ids — kept for docs and residual narrative only.
# NOT fail-closed: W68 live seal closed fins tip4 (see module docstring).
SUPERSEDED_PERMANENT_DEFER_IDS: dict[str, str] = {
    "fins_earnings_date": "PD-MX-EARN-TIP",  # W44 FINAL NO_RAW → W68 LIVE SEAL tip4 COMPLETE
}


class PermanentDeferHistoryError(PermissionError):
    """Raised when a research history load targets a permanent DEFER dataset."""


def is_permanent_defer(dataset: str) -> bool:
    """True if ``dataset`` is permanently DEFER for full-history research."""
    return str(dataset).strip() in PERMANENT_DEFER_DATASETS


def filter_permanent_defer(
    datasets: Iterable[str],
) -> list[str]:
    """Return datasets with permanent DEFER ids removed (order preserved)."""
    out: list[str] = []
    seen: set[str] = set()
    for item in datasets:
        value = str(item).strip()
        if not value or value in seen:
            continue
        if value in PERMANENT_DEFER_DATASETS:
            continue
        seen.add(value)
        out.append(value)
    return out


def reject_permanent_defer_for_history(
    datasets: Sequence[str] | str,
    *,
    context: str = "research history load",
) -> None:
    """Fail-closed: raise if any permanent DEFER dataset is requested.

    Parameters
    ----------
    datasets:
        One dataset id or a sequence of ids (as accepted by research loaders).
    context:
        Short label included in the error message for logs/tests.
    """
    if isinstance(datasets, str):
        requested = (datasets,)
    else:
        requested = tuple(datasets)
    bad = sorted(
        {
            str(item).strip()
            for item in requested
            if str(item).strip() in PERMANENT_DEFER_DATASETS
        }
    )
    if not bad:
        return
    detail = ", ".join(
        f"{ds} ({PERMANENT_DEFER_IDS.get(ds, 'PD')})" for ds in bad
    )
    raise PermanentDeferHistoryError(
        f"{context}: permanent DEFER dataset(s) excluded from research "
        f"history loads: {detail}. Prefer the 22 COMPLETE datasets; see "
        "docs/proof/complete21_cf_read_paths_20260815.md"
    )


def require_history_eligible(dataset: str, *, context: str = "research history load") -> str:
    """Return ``dataset`` if history-eligible; raise if permanent DEFER."""
    value = str(dataset).strip()
    reject_permanent_defer_for_history(value, context=context)
    return value


__all__ = [
    "PERMANENT_DEFER_DATASETS",
    "PERMANENT_DEFER_IDS",
    "SUPERSEDED_PERMANENT_DEFER_IDS",
    "PermanentDeferHistoryError",
    "filter_permanent_defer",
    "is_permanent_defer",
    "reject_permanent_defer_for_history",
    "require_history_eligible",
]
