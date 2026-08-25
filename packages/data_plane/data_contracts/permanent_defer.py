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

**W71 / W72 tip-only policy lock (bars_am + OTC):**

* ``equities_bars_daily_am`` (PD-D4-BARS-AM): W71 live API re-probe returned
  ``LIVE_API_EMPTY`` for **all 31** PARTIAL history months
  (``2024-01…2026-07``); sealed_n=0. **History is DEFER.** Ops path is
  **tip continuous only** (vendor ``date_mode=today``; premium cron hourly).
  **No regular history re-probe** / no densify of residual history months.
* ``jsda_otc_bond_reference_prices`` (PD-D5-JSDA-OTC): **tip island only**
  (COMPLETE tip island held at 93). Wait for official FULL_OK tip advance;
  **no bulk densify** of archive PARTIALs.

**W98 / w0819a equities_master scope (PD-D2-MASTER):**

* ``PRE_PLAN`` months ``2000-07…2006-07`` (n=73) are **catalog OUT_OF_SCOPE**
  via the W98 subscription-floor raise to ``2006-08-13`` — not “missing”,
  not densify targets. ``2006-08-13`` remains the Premium entitlement floor
  (historical fact), not historical required start.
* Official listed-info provision start is **2008-05-07**
  (https://jpx-jquants.com/en/spec/eq-master). Planner / coverage policy
  track that official domain; ``2006-08-13`` is not a densify start.
* ``MISDATE`` months ``2006-08…2008-04`` (n=21) are
  **excluded_official_unavailable** (vendor clamp to 2008-05-07),
  not REQUIRED_PARTIAL, not missing backfill, and not COMPLETE.
* This defer record stays. Do not invent Dataset COMPLETE by floor bump.
  Remaining genuine gaps on or after 2008-05-07 stay PARTIAL.
* Honest island remains ``2008-05→latest`` (tip continuous). PIT history
  from 2008-05-07. ``FeatureContext.get_equity_master`` and
  ``get_jquants_records(dataset="equities_master")`` read that island
  through PIT with ``as_of`` required; pre-official rows are empty /
  fail-closed. Remaining genuine gaps stay PARTIAL (PD-D2-MASTER). Do not
  invent Dataset COMPLETE. Generic ``require_feature_dataset`` still
  DEFERs master; AM / earnings calendar / JSDA OTC stay tip-only DEFER.

Ops / tip / SCD2 CURRENT reads are out of scope for this module — only
history-grade research loaders should call the guards below. Tip continuous
collect + seal + ``sync_dataset_coverage_from_segments`` remain allowed
(see residual W72 tip-only ops).
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

# Canonical permanent DEFER dataset ids (n=4 after W68). Names match residual SoT.
PERMANENT_DEFER_DATASETS: frozenset[str] = frozenset(
    {
        "equities_master",  # PD-D2-MASTER (official start 2008-05-07; remaining gaps PARTIAL)
        "equities_earnings_calendar",  # PD-D4-EARN-CAL (vendor tip-only history)
        "equities_bars_daily_am",  # PD-D4-BARS-AM (tip-only AM; history LIVE_API_EMPTY)
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

# W98 / w0819a — equities_master coverage bands (PD-D2-MASTER).
# PRE_PLAN is explicit **coverage out-of-scope (de-scope)** — not "missing".
# Official provision start is 2008-05-07 (planner wired). 2006-08-13 remains
# the Premium subscription entitlement floor (historical fact), not densify.
# Do not invent Dataset COMPLETE by treating excluded MISDATE as required.
# Focus seal/ops on POST_ISLAND 2008-05→latest; remaining genuine gaps stay PARTIAL.
MASTER_JQ_SCOPE: dict[str, object] = {
    "dataset": "equities_master",
    "pd_id": "PD-D2-MASTER",
    "history_target_start": "2008-05-07",
    "not_historical_required_start": "2006-08-13",
    "wave_locked": "W98 / w0819a",
    "bands": {
        "PRE_PLAN": {
            "span": "2000-07..2006-07",
            "n_segs": 73,
            "coverage": "OUT_OF_SCOPE",
            "status": "coverage_out_of_scope",
            "de_scope": True,
            "vs_missing": "de-scoped (not missing)",
            "densify": "FORBIDDEN",
            "seal": "FORBIDDEN",
            "invent_fill": "FORBIDDEN",
            "reason": (
                "Below Premium subscription entitlement; W98 product de-scope "
                "raised the catalog floor to 2006-08-13 "
                "(not_historical_required_start). Not missing-to-invent; "
                "never densify / never raise floor to fake COMPLETE."
            ),
        },
        "MISDATE": {
            "span": "2006-08..2008-04",
            "n_segs": 21,
            "coverage": "excluded_official_unavailable",
            "status": "excluded_official_unavailable",
            "de_scope": False,
            "densify": "FORBIDDEN",
            "seal": "FORBIDDEN",
            "invent_fill": "FORBIDDEN",
            "reason": (
                "Official listed-info provision starts 2008-05-07 "
                "(https://jpx-jquants.com/en/spec/eq-master). "
                "Queries before that clamp Date to 2008-05-07 (vendor MISDATE), "
                "not a missing-backfill gap. 2006-08..2008-04 are "
                "excluded_official_unavailable, not REQUIRED_PARTIAL to densify "
                "and not COMPLETE. 2006-08-13 remains the Premium subscription "
                "entitlement floor (historical fact). PD-D2-MASTER remains; "
                "remaining genuine gaps after 2008-05-07 stay PARTIAL. "
                "Do not invent Dataset COMPLETE."
            ),
        },
        "POST_ISLAND": {
            "span": "2008-05..latest",
            "coverage": "REQUIRED_COMPLETE_TARGET",
            "status": "COMPLETE_focus",
            "de_scope": False,
            "note": (
                "honest island from official start 2008-05-07; tip continuous + "
                "gap fill via official re-fetch only. Remaining genuine gaps stay "
                "PARTIAL. Not a Dataset COMPLETE claim."
            ),
            "seal": "tip_continuous_and_gap_refetch",
        },
    },
    "subscription_floor_live": "2006-08-19",
    # Official listed-info /equities/master provision start (not the Premium
    # HTTP 400 floor). Earlier dates still return Date=2008-05-07.
    # https://jpx-jquants.com/en/spec/eq-master
    # Planner tracks this official start. 2006-08-13 is the subscription
    # floor (not_historical_required_start), not a densify target.
    "vendor_data_provision_start": "2008-05-07",
    "vendor_data_provision_citation": "https://jpx-jquants.com/en/spec/eq-master",
    "invent_complete_via_floor_to_2008_05": "FORBIDDEN",
    "dataset_complete_invent": "FORBIDDEN",
    "empty_raw_complete": "FORBIDDEN",
}

# Alias kept for callers / docs that used the interim name.
MASTER_COVERAGE_POLICY = MASTER_JQ_SCOPE

# W72 tip-only ops policy (comments + machine-readable fields).
# History densify / regular history re-probe remain FORBIDDEN for these ids.
# Tip continuous collect → seal (nz only) → sync_dataset_coverage_from_segments
# is the only COMPLETE-expand path; never invent empty-raw COMPLETE.


TIP_ONLY_POLICY: dict[str, dict[str, object]] = {
    "equities_bars_daily_am": {
        "pd_id": "PD-D4-BARS-AM",
        "mode": "tip_continuous",
        "history": "DEFER",
        "history_reason": "W71 LIVE_API_EMPTY all 31 PARTIAL months (2024-01..2026-07)",
        "history_reprobe": "FORBIDDEN",  # no regular history re-probe after W71
        "history_densify": "FORBIDDEN",
        "tip_collect": "continuous",  # premium cron hourly; date_mode=today
        "tip_cron": "platform/workers/ingestion-premium crons=['15 * * * *']",
        "empty_raw_complete": "FORBIDDEN",
        "dataset_complete_invent": "FORBIDDEN",  # needs honest 32/32; held at 1/32 tip
        "wave_locked": "W72 / w0816f",
        "prior_probe_wave": "W71 / w0816e",
    },
    "jsda_otc_bond_reference_prices": {
        "pd_id": "PD-D5-JSDA-OTC",
        "mode": "tip_island_wait_full_ok",
        "history": "DEFER",
        "history_reason": "archive long-tail PARTIAL; tip island only",
        "bulk_densify": "FORBIDDEN",  # never densify 8688 archive PARTIALs
        "tip_collect": "wait_full_ok",  # JSDA cron daily; seal only FULL_OK_NEW
        "tip_cron": "platform/workers/ingestion-jsda crons=['30 1 * * *']",
        "seal_gate": "FULL_OK",  # HTTP 200 + body > 1.5MB + nz reconcile
        "empty_raw_complete": "FORBIDDEN",
        "dataset_complete_invent": "FORBIDDEN",  # never force dataset COMPLETE
        "wave_locked": "W72 / w0816f",
        "prior_rescan_wave": "W71 / w0816e",
    },
}


class PermanentDeferHistoryError(PermissionError):
    """Raised when a research history load targets a permanent DEFER dataset."""


def is_permanent_defer(dataset: str) -> bool:
    """True if ``dataset`` is permanently DEFER for full-history research."""
    return str(dataset).strip() in PERMANENT_DEFER_DATASETS


def is_tip_only_policy(dataset: str) -> bool:
    """True if dataset is under W72 tip-only ops policy (bars_am / OTC)."""
    return str(dataset).strip() in TIP_ONLY_POLICY


def tip_only_policy_for(dataset: str) -> Mapping[str, object] | None:
    """Return tip-only policy fields for ``dataset``, or None."""
    return TIP_ONLY_POLICY.get(str(dataset).strip())


def history_reprobe_forbidden(dataset: str) -> bool:
    """True when regular history re-probe is locked FORBIDDEN (bars_am post-W71)."""
    policy = tip_only_policy_for(dataset)
    if not policy:
        return False
    return str(policy.get("history_reprobe", "")).upper() == "FORBIDDEN" or str(
        policy.get("bulk_densify", "")
    ).upper() == "FORBIDDEN"


def history_densify_forbidden(dataset: str) -> bool:
    """True when history/bulk densify is locked FORBIDDEN (tip-only residual).

    W73 regression guard: tip-only datasets must never take the densify path.
    bars_am uses ``history_densify=FORBIDDEN``; OTC uses ``bulk_densify=FORBIDDEN``.
    """
    policy = tip_only_policy_for(dataset)
    if not policy:
        return False
    return str(policy.get("history_densify", "")).upper() == "FORBIDDEN" or str(
        policy.get("bulk_densify", "")
    ).upper() == "FORBIDDEN"


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


def master_coverage_policy() -> Mapping[str, object]:
    """Return W98 equities_master band policy (PRE_PLAN de-scope)."""
    return MASTER_COVERAGE_POLICY


def master_band_for_segment(segment_id: str) -> str:
    """Classify master calendar-month segment_id into PRE_PLAN/MISDATE/POST_ISLAND."""
    sid = str(segment_id).strip()[:7]
    if sid < "2006-08":
        return "PRE_PLAN"
    if sid < "2008-05":
        return "MISDATE"
    return "POST_ISLAND"


def master_pre_plan_descope(segment_id: str) -> bool:
    """True when segment is PRE_PLAN coverage-out-of-scope (do not invent/seal)."""
    return master_band_for_segment(segment_id) == "PRE_PLAN"


__all__ = [
    "MASTER_COVERAGE_POLICY",
    "MASTER_JQ_SCOPE",
    "PERMANENT_DEFER_DATASETS",
    "PERMANENT_DEFER_IDS",
    "SUPERSEDED_PERMANENT_DEFER_IDS",
    "TIP_ONLY_POLICY",
    "PermanentDeferHistoryError",
    "filter_permanent_defer",
    "history_densify_forbidden",
    "history_reprobe_forbidden",
    "is_permanent_defer",
    "is_tip_only_policy",
    "master_band_for_segment",
    "master_coverage_policy",
    "master_pre_plan_descope",
    "reject_permanent_defer_for_history",
    "require_history_eligible",
    "tip_only_policy_for",
]

