"""R2 available_at repair policy authority.

Public import remains ``research.r2_feature_context``. Research-only PIT
repairs. Never invent visibility. Never look-ahead. Never rewrite R2 SoT.
Parse stays in r2_feature_parse; normalize stays in r2_feature_normalize.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# Research-only PIT repairs. Never invent visibility. Never rewrite R2 SoT.
AVAILABLE_AT_REPAIR_POLICY: dict[str, Any] = {
    "version": "r2-available-at-repair/v1",
    "research_only": True,
    "r2_sot_rewrite": False,
    "repairs": {
        "calendar_ingest_pollution": {},
        "archive_ingest_pollution": {},
        "missing_available_at_drop": {},
        "post_date_preserve": {},
    },
}

_ARCHIVE_INGEST_POLLUTION_DATASETS: frozenset[str] = frozenset(
    {
        "markets_margin_interest",
        "markets_short_ratio",
        "markets_margin_alert",
    }
)


def repair_available_at_research(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    policy: str = "auto",
) -> dict[str, Any]:
    """Research-only available_at repairs. Never invent; never look-ahead."""
    ds = str(dataset).strip()
    apply_cal = policy in ("auto", "calendar_ingest_pollution") and (
        ds == "markets_calendar" or policy == "calendar_ingest_pollution"
    )
    apply_archive = policy in ("auto", "archive_ingest_pollution") and (
        ds in _ARCHIVE_INGEST_POLLUTION_DATASETS
        or policy == "archive_ingest_pollution"
    )
    n_fixed = 0
    n_dropped = 0
    repair_tags: list[str] = []
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        aa = row.get("available_at")
        et = row.get("event_time")
        if aa is None or aa == "":
            n_dropped += 1
            continue
        if et is not None and str(et).strip():
            aa_day = str(aa).strip()[:10]
            et_day = str(et).strip()[:10]
            aa_year = aa_day[:4] if len(aa_day) >= 4 else ""
            et_year = et_day[:4] if len(et_day) >= 4 else ""
            if apply_cal and aa_day and et_day and aa_day > et_day:
                row["available_at"] = et
                row["_aa_repair"] = "calendar_ingest_pollution"
                n_fixed += 1
                repair_tags.append("calendar_ingest_pollution")
            elif (
                apply_archive
                and aa_day
                and et_day
                and aa_day > et_day
                and aa_year >= "2026"
                and et_year
                and et_year < "2026"
            ):
                row["available_at"] = et
                row["_aa_repair"] = "archive_ingest_pollution"
                n_fixed += 1
                repair_tags.append("archive_ingest_pollution")
        out.append(row)
    applied = "none"
    if n_fixed:
        if "archive_ingest_pollution" in repair_tags:
            applied = "archive_ingest_pollution"
        elif "calendar_ingest_pollution" in repair_tags:
            applied = "calendar_ingest_pollution"
    return {
        "rows": out,
        "n_in": len(list(rows)),
        "n_out": len(out),
        "n_fixed": n_fixed,
        "n_dropped_null_aa": n_dropped,
        "dataset": ds,
        "policy": policy,
        "repair_applied": applied,
        "research_only": True,
        "look_ahead": False,
    }


def available_at_policy_document() -> dict[str, Any]:
    """Public document for available_at repair."""
    return dict(AVAILABLE_AT_REPAIR_POLICY)


__all__ = [
    "AVAILABLE_AT_REPAIR_POLICY",
    "available_at_policy_document",
    "repair_available_at_research",
]
