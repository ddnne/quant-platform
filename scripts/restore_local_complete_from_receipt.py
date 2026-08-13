#!/usr/bin/env python3
"""Phase 6.3 — restore ONE local COMPLETE from SUCCESS receipt (remote untouched).

Design intent: GLM Phase 6.3 Worker4. Wired to real storage.coverage_ledger APIs
(_receipt_from_row, evaluate_segment, record_required_segments).

Mass / READY: NO-GO. Never invents segments. Never writes remote D1.
"""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root  # noqa: E402

import argparse
import json
import sqlite3
from datetime import datetime, timezone

ROOT = ensure_repo_root()

from data_contracts.coverage import coverage_contract_for  # noqa: E402
from storage.coverage_ledger import (  # noqa: E402
    RequiredCoverageSegment,
    _receipt_from_row,
    evaluate_segment,
    is_complete_eligible_receipt,
    record_required_segments,
)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "structured" / "ingestion.sqlite",
    )
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--segment-id", required=True)
    ap.add_argument("--policy-version", default="collection-coverage/v2")
    args = ap.parse_args(argv)

    if not args.db.is_file():
        print(f"ERROR: db not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    try:
        before = conn.execute(
            "SELECT status, receipt_run_id FROM coverage_segments "
            "WHERE dataset=? AND segment_id=? AND policy_version=?",
            (args.dataset, args.segment_id, args.policy_version),
        ).fetchone()
        print(
            "before:",
            None
            if before is None
            else {"status": before["status"], "receipt_run_id": before["receipt_run_id"]},
        )

        rec_row = conn.execute(
            "SELECT * FROM collection_receipts "
            "WHERE dataset=? AND segment_id=? AND status='SUCCESS' "
            "ORDER BY checked_at DESC, run_id DESC LIMIT 1",
            (args.dataset, args.segment_id),
        ).fetchone()
        if rec_row is None:
            print(
                f"ERROR: no SUCCESS receipt for {args.dataset}/{args.segment_id}",
                file=sys.stderr,
            )
            return 1

        receipt = _receipt_from_row(dict(rec_row))
        if not is_complete_eligible_receipt(receipt):
            print(
                "ERROR: receipt not COMPLETE-eligible (need TRUSTED Ed25519)",
                file=sys.stderr,
            )
            return 1

        scope = dict(receipt.expected_scope) if receipt.expected_scope else {}
        required = RequiredCoverageSegment(
            source=receipt.source,
            dataset=receipt.dataset,
            segment_id=receipt.segment_id,
            segment_start=receipt.segment_start,
            segment_end=receipt.segment_end,
            expected_scope=scope,
            expected_items=receipt.expected_items,
        )
        record_required_segments(
            conn, [required], policy_version=args.policy_version
        )
        conn.commit()

        policy = coverage_contract_for(args.dataset)
        status, detail = evaluate_segment(policy, required, receipt)
        print("evaluate:", status, detail)
        if status != "COMPLETE":
            print(f"ERROR: evaluate_segment={status}", file=sys.stderr)
            return 1

        now = _now()
        conn.execute(
            "UPDATE coverage_segments SET status=?, receipt_run_id=?, "
            "evaluated_at=?, detail_json=? "
            "WHERE dataset=? AND segment_id=? AND policy_version=?",
            (
                "COMPLETE",
                receipt.run_id,
                now,
                json.dumps(detail, ensure_ascii=False, sort_keys=True),
                args.dataset,
                args.segment_id,
                args.policy_version,
            ),
        )
        conn.commit()
        after = conn.execute(
            "SELECT status, receipt_run_id, evaluated_at FROM coverage_segments "
            "WHERE dataset=? AND segment_id=? AND policy_version=?",
            (args.dataset, args.segment_id, args.policy_version),
        ).fetchone()
        print(
            "after:",
            {
                "status": after["status"],
                "receipt_run_id": after["receipt_run_id"],
                "evaluated_at": after["evaluated_at"],
            },
        )
        total = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
        ).fetchone()[0]
        print(f"local COMPLETE total: {total}")
        print("OK remote_untouched=1")
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    raise SystemExit(main())
