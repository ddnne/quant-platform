"""Catalog-job collection receipt evidence for the J-Quants persist path.

Collection SUCCESS is not Coverage COMPLETE. Missing index_text stays
fail-closed empty (not a calendar walk). Never fakes COMPLETE.
"""

from __future__ import annotations

from typing import Any

from .jquants.receipts import (
    emit_segment_receipt,
    require_signed_receipt_authority,
)


def _uses_official_archive_index(policy) -> bool:
    from .jsda.official_index import OFFICIAL_ARCHIVE_INDEX_DATASETS

    if getattr(policy, "dataset_id", None) in OFFICIAL_ARCHIVE_INDEX_DATASETS:
        return True
    mode = getattr(policy, "coverage_mode", "") or ""
    if "official_archive_index" in mode:
        return True
    if getattr(policy, "history_mode", None) == "official_archive_index":
        return True
    return getattr(policy, "segment_granularity", None) == "official_archive_index_day"


def _index_text_for_plan(policy, index_text: str | None = None) -> str | None:
    """Reuse already-held year-index HTML for OTC/official-archive-index.

    Missing or blank text is None (fail-closed empty plan, not a calendar
    walk). Does not fetch live HTML.
    """
    if not _uses_official_archive_index(policy):
        return None
    if index_text is None or not str(index_text).strip():
        return None
    return str(index_text)


def _plan_required_segments(
    policy,
    target_end: str,
    *,
    source: str,
    index_text: str | None = None,
    expected_items_by_segment=None,
):
    from storage.coverage_ledger import plan_required_segments

    return list(
        plan_required_segments(
            policy,
            target_end,
            source=source,
            index_text=_index_text_for_plan(policy, index_text),
            expected_items_by_segment=expected_items_by_segment,
        )
    )


def commit_governed_catalog_receipt(store) -> None:
    """Commit structured rows + receipt together. Does not mint COMPLETE."""
    store._conn.commit()


def rollback_governed_catalog_write(store) -> None:
    """Receipt failure must not leave structured rows as PASS."""
    try:
        store._conn.rollback()
    except Exception:  # noqa: BLE001
        pass


def emit_catalog_job_receipt(
    store,
    *,
    job: Any,
    when: str,
    raw_bytes: bytes,
    rows: list,
    structured_row_count: int,
    authority,
) -> None:
    """Record required segments and a signed SUCCESS receipt for one catalog job.

    Persist has no year-index HTML in hand → index_text None (empty, not calendar).
    Collection SUCCESS is not Coverage COMPLETE.
    """
    from data_contracts import coverage_contract_for
    from storage.coverage_ledger import record_required_segments

    params = dict(getattr(job, "params", None) or {})
    policy = coverage_contract_for(job.dataset_id)
    target_end = (
        params.get("to")
        or params.get("date")
        or str(when)[:10]
    )
    target_end = str(target_end)[:10]
    job_start = str(
        params.get("from") or params.get("date") or target_end
    )[:10]
    job_end = target_end
    # Official-archive-index reuses already-held year-index HTML.
    # Persist has none here → index_text None (empty, not calendar).
    index_text = _index_text_for_plan(policy, None)
    # First plan without expected counts to discover segment ids.
    segs = _plan_required_segments(
        policy,
        target_end,
        source="jquants",
        index_text=index_text,
    )
    req0 = None
    for s in segs:
        if s.segment_start <= job_end and s.segment_end >= job_start:
            req0 = s
            break
    if req0 is None and segs:
        req0 = segs[-1]
    if req0 is not None:
        unit = (req0.expected_scope or {}).get(
            "expected_item_unit", "source_query"
        )
        exp_map = None
        if (
            policy.expected_frequency != "event_driven"
            and unit == "source_query"
        ):
            exp_map = {req0.segment_id: 1}
            segs = _plan_required_segments(
                policy,
                target_end,
                source="jquants",
                index_text=index_text,
                expected_items_by_segment=exp_map,
            )
            req = next(
                s for s in segs if s.segment_id == req0.segment_id
            )
        else:
            req = req0
        record_required_segments(store._conn, [req])
        run_id_row = store._conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM ingestion_run_log"
        ).fetchone()
        run_id = int(run_id_row[0]) if run_id_row else 0
        if unit == "source_query":
            obs = 1 if len(rows) > 0 else 0
        else:
            obs = len(rows)
        emit_segment_receipt(
            store._conn,
            required=req,
            run_id=run_id,
            raw=raw_bytes,
            observed_items=obs,
            structured_row_count=structured_row_count,
            raw_row_count=len(rows),
            pagination_exhausted=True,
            status="SUCCESS",
            authority=authority,
            commit=False,
        )
        commit_governed_catalog_receipt(store)


__all__ = [
    "_index_text_for_plan",
    "_plan_required_segments",
    "commit_governed_catalog_receipt",
    "emit_catalog_job_receipt",
    "require_signed_receipt_authority",
    "rollback_governed_catalog_write",
]
