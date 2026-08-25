#!/usr/bin/env python3
"""Seal official JSDA OTC archive days. No invent COMPLETE.

Coverage refresh takes local official-index HTML as index_text.
Omitted/blank text is fail-closed empty, not calendar COMPLETE.
The parser supports the early 21-column 2002-08-02/05 artifacts, but this
recovery sealer keeps them REPROOF_REQUIRED until a trusted digest/count is
approved and raw-to-structured reconciliation succeeds.
Does not fetch live JSDA HTML.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
from _bootstrap import ensure_repo_root  # noqa: E402

ROOT = ensure_repo_root()

from ingestion.jsda.normalize import normalize_otc_reference_prices  # noqa: E402
from ingestion.jsda.archive import resolve_quote_effective_dates  # noqa: E402
from ingestion.jsda.official_index import (  # noqa: E402
    read_local_index_text as _read_index_text,
)
from ingestion.jsda.parse import parse_otc_reference_csv, parse_otc_reference_xlsx  # noqa: E402
from ingestion.runtime_authority import (  # noqa: E402
    open_governed_receipt_service,
)
from storage.coverage_ledger import (  # noqa: E402
    RequiredCoverageSegment,
    record_required_segments,
    refresh_coverage_ledger,
)
from storage.sqlite_store import SqliteStore  # noqa: E402

RAW_ROOT = ROOT / "data" / "raw" / "jsda" / "jsda_otc_bond_reference_prices"
DB = ROOT / "data" / "structured" / "ingestion.sqlite"
FULL_OK_MIN = 100_000
WAVE = "jsda_otc_official_backfill"
ITEMS: list = []
LOGDIR = ROOT / "data" / "ops"
OTC_DATASET = "jsda_otc_bond_reference_prices"
OTC_GRAIN = "official_archive_index_day"
EARLY_LAYOUT_REPROOF_DAYS = frozenset({"2002-08-02", "2002-08-05"})
# This recovery path must not treat remotely observed metadata as completion
# authority.  A deliberate trusted-reconciliation release may pin a digest and
# parser count here; empty means the two parser-capable days stay PARTIAL.
EARLY_LAYOUT_RECONCILIATION_PROOF: dict[str, tuple[str, int]] = {}

TRIGGERS_DROP = [
    "invalidate_snapshot_jsda_otc_reference_i",
    "invalidate_snapshot_jsda_otc_reference_u",
    "invalidate_snapshot_jsda_otc_reference_d",
    "invalidate_snapshot_jsda_otc_reference_revisions_i",
    "invalidate_snapshot_jsda_otc_reference_revisions_u",
    "invalidate_snapshot_jsda_otc_reference_revisions_d",
]

TRIGGERS_CREATE_SQL = """
CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_otc_reference_i
AFTER INSERT ON jsda_otc_bond_reference_prices BEGIN
    UPDATE local_snapshot_policy SET snapshot_ready=0,
        active_snapshot_id=NULL,
        last_error='fact mutation invalidated research snapshot'
    WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_otc_reference_u
AFTER UPDATE ON jsda_otc_bond_reference_prices BEGIN
    UPDATE local_snapshot_policy SET snapshot_ready=0,
        active_snapshot_id=NULL,
        last_error='fact mutation invalidated research snapshot'
    WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_otc_reference_d
AFTER DELETE ON jsda_otc_bond_reference_prices BEGIN
    UPDATE local_snapshot_policy SET snapshot_ready=0,
        active_snapshot_id=NULL,
        last_error='fact mutation invalidated research snapshot'
    WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_otc_reference_revisions_i
AFTER INSERT ON jsda_otc_bond_reference_prices_revisions BEGIN
    UPDATE local_snapshot_policy SET snapshot_ready=0,
        active_snapshot_id=NULL,
        last_error='fact mutation invalidated research snapshot'
    WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_otc_reference_revisions_u
AFTER UPDATE ON jsda_otc_bond_reference_prices_revisions BEGIN
    UPDATE local_snapshot_policy SET snapshot_ready=0,
        active_snapshot_id=NULL,
        last_error='fact mutation invalidated research snapshot'
    WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_otc_reference_revisions_d
AFTER DELETE ON jsda_otc_bond_reference_prices_revisions BEGIN
    UPDATE local_snapshot_policy SET snapshot_ready=0,
        active_snapshot_id=NULL,
        last_error='fact mutation invalidated research snapshot'
    WHERE singleton=1;
END;
"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _early_layout_reproof_required(
    day: str, digest: str | None, count: int
) -> bool:
    """Keep early parser output ineligible until trusted proof is approved."""
    if day not in EARLY_LAYOUT_REPROOF_DAYS:
        return False
    proof = EARLY_LAYOUT_RECONCILIATION_PROOF.get(day)
    if proof is None:
        return True
    expected_digest, expected_count = proof
    if digest is None or not str(digest).startswith("sha256:"):
        return True
    if int(count) <= 0:
        return True
    return digest != expected_digest or int(count) != int(expected_count)


def refresh_otc_coverage(
    conn: sqlite3.Connection,
    db_path: str | Path,
    *,
    index_text: str | None,
    today: str = "2026-08-21",
):
    """Always pass index_text. Missing text is fail-closed empty, not COMPLETE."""
    return refresh_coverage_ledger(
        conn,
        db_path,
        datasets=[OTC_DATASET],
        today=today,
        index_text=index_text,
    )


def next_run_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(run_id), 900000) FROM collection_receipts"
    ).fetchone()
    return int(row[0]) + 1


def inventory_scope(conn: sqlite3.Connection, day: str):
    row = conn.execute(
        """
        SELECT expected_scope, segment_start, segment_end
        FROM coverage_segments
        WHERE dataset=? AND segment_id=?
        """,
        (OTC_DATASET, day),
    ).fetchone()
    if row is None:
        return {
            "coverage_mode": "official_archive_index_reconciled",
            "expected_frequency": "trading_day",
            "expected_item_unit": "source_query",
            "segment_end": day,
            "segment_granularity": OTC_GRAIN,
            "segment_start": day,
            "universe_rule": "all_bonds_in_official_publication_file",
        }, day, day
    scope = json.loads(row[0]) if isinstance(row[0], str) else dict(row[0])
    return scope, str(row[1]), str(row[2])


def resolve_path(day: str, code: str) -> Path | None:
    for ext in (".csv", ".xls", ".xlsx"):
        p = RAW_ROOT / day / f"{code}{ext}"
        if p.is_file() and p.stat().st_size > FULL_OK_MIN:
            return p
    return None


def _xls_cell(sh, r, c, wb):
    import xlrd

    if c >= sh.ncols:
        return ""
    cell = sh.cell(r, c)
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, wb.datemode).strftime("%Y-%m-%d")
        except Exception:
            return str(cell.value)
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        v = cell.value
        return str(int(v)) if float(v).is_integer() else str(v)
    if cell.value is None:
        return ""
    return str(cell.value)


def _parse_otc_xls(
    raw: bytes,
    publication_label_date: str,
    quote_effective_date: str,
):
    import xlrd
    from ingestion.jsda.parse import _date, _num  # type: ignore

    wb = xlrd.open_workbook(file_contents=raw, on_demand=True)
    sh = wb.sheet_by_index(0)
    out = []
    for r in range(sh.nrows):
        code = _xls_cell(sh, r, 1, wb).strip()
        name = _xls_cell(sh, r, 2, wb).strip()
        if not code or not name:
            continue
        if not re.match(r"^[0-9A-Za-z]{6,}", code):
            continue
        if code in {"Code", "銘柄コード"} or "Issue" in code:
            continue
        mat = _xls_cell(sh, r, 3, wb)
        mat = mat.replace("/", "-") if mat else ""
        coupon_s = _xls_cell(sh, r, 4, wb)
        avg_px = _xls_cell(sh, r, 5, wb)
        avg_y_c = _xls_cell(sh, r, 7, wb)
        avg_y_s = _xls_cell(sh, r, 8, wb)
        med_px = _xls_cell(sh, r, 9, wb)
        med_y_c = _xls_cell(sh, r, 11, wb)
        high_px = _xls_cell(sh, r, 13, wb)
        high_y_c = _xls_cell(sh, r, 15, wb)
        low_px = _xls_cell(sh, r, 17, wb)
        low_y_c = _xls_cell(sh, r, 19, wb)
        avg_y = avg_y_c if avg_y_c and avg_y_c not in {"―――", "-----", "--"} else avg_y_s
        out.append(
            {
                "publication_label_date": publication_label_date,
                "quote_effective_date": quote_effective_date,
                "security_code": code,
                "bond_name": name,
                "coupon_rate": _num(coupon_s),
                "maturity_date": _date(mat),
                "average_price": _num(avg_px),
                "average_yield": _num(avg_y),
                "median_price": _num(med_px),
                "median_yield": _num(med_y_c),
                "high_price": _num(high_px),
                "high_yield": _num(high_y_c),
                "low_price": _num(low_px),
                "low_yield": _num(low_y_c),
                "individual_investor_flag": None,
                "source_row_number": r + 1,
            }
        )
    return out


def parse_raw(
    path: Path,
    publication_label_date: str,
    quote_effective_date: str,
):
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return (
            raw,
            parse_otc_reference_csv(
                raw,
                publication_label_date=publication_label_date,
                quote_effective_date=quote_effective_date,
            ),
            "csv",
        )
    if suffix == ".xlsx":
        return (
            raw,
            parse_otc_reference_xlsx(
                raw,
                publication_label_date=publication_label_date,
                quote_effective_date=quote_effective_date,
            ),
            "xlsx",
        )
    if suffix == ".xls":
        return (
            raw,
            _parse_otc_xls(raw, publication_label_date, quote_effective_date),
            "xls",
        )
    return raw, [], suffix.lstrip(".")


def drop_triggers(conn: sqlite3.Connection) -> None:
    for name in TRIGGERS_DROP:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    conn.commit()


def restore_triggers(conn: sqlite3.Connection) -> None:
    conn.executescript(TRIGGERS_CREATE_SQL)
    try:
        conn.execute(
            """
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='W107 OTC batch11 official PARTIAL seal invalidated research snapshot'
            WHERE singleton=1
            """
        )
    except sqlite3.Error:
        pass
    conn.commit()


def bulk_insert_day(conn: sqlite3.Connection, day: str, rows: list[dict]) -> int:
    """Replace one day inside the governed transaction. Triggers must be off."""
    exists = conn.execute(
        "SELECT 1 FROM jsda_otc_bond_reference_prices "
        "WHERE source='jsda' AND publication_label_date=? LIMIT 1",
        (day,),
    ).fetchone()
    if exists:
        conn.execute(
            "DELETE FROM jsda_otc_bond_reference_prices "
            "WHERE source='jsda' AND publication_label_date=?",
            (day,),
        )
    cols = list(rows[0].keys())
    placeholders = ",".join("?" for _ in cols)
    colsql = ",".join(cols)
    conn.executemany(
        f"INSERT INTO jsda_otc_bond_reference_prices ({colsql}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in cols) for r in rows],
    )
    return len(rows)


def seal_day(
    store,
    day,
    path,
    source_url,
    receipt_service,
    *,
    quote_effective_date,
):
    t0 = time.time()
    conn = None if store is None else store._conn  # noqa: SLF001
    if (
        not isinstance(quote_effective_date, str)
        or not quote_effective_date
        or quote_effective_date >= day
    ):
        return {
            "segment_id": day,
            "status": "QUOTE_EFFECTIVE_DATE_UNRESOLVED",
        }
    raw, parsed, fmt = parse_raw(path, day, quote_effective_date)
    if len(raw) <= FULL_OK_MIN:
        return {"segment_id": day, "status": "NOT_FULL_OK_SIZE", "size": len(raw)}
    head = raw[:200].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return {"segment_id": day, "status": "HTML_BODY", "size": len(raw)}
    if not parsed:
        # Raw may still be a real official file (2002-08-02/05 are ~560KB /
        # ~4200 rows). Zero parse ≠ empty source and must not become COMPLETE.
        return {"segment_id": day, "status": "PARSE_ZERO", "path": str(path), "fmt": fmt}
    digest = sha256_file(path)
    if _early_layout_reproof_required(day, digest, len(parsed)):
        # Parser capability is not a receipt.  The recovery path stays PARTIAL
        # until the approved artifact is persisted and independently reconciled.
        return {
            "segment_id": day,
            "status": "REPROOF_REQUIRED",
            "reason": "TRUSTED_RAW_RECONCILIATION_REQUIRED",
            "path": str(path),
            "fmt": fmt,
            "raw": len(parsed),
            "digest": digest,
        }
    if path.is_symlink():
        return {"segment_id": day, "status": "RAW_SYMLINK_REJECTED"}
    path.chmod(0o444)
    now = datetime.now(timezone.utc).isoformat()
    rows = normalize_otc_reference_prices(
        parsed,
        ingested_at=now,
        publication_label_date=day,
        quote_effective_date=quote_effective_date,
        source_url=source_url,
        raw_digest=digest,
        segment_id=day,
        source_format=fmt,
    )
    structured = bulk_insert_day(conn, day, rows)
    raw_count = len(parsed)
    if structured <= 0 or raw_count <= 0:
        return {
            "segment_id": day,
            "status": "EMPTY_COMPLETE_BAN",
            "raw": raw_count,
            "struct": structured,
        }
    if int(structured) != int(raw_count):
        return {
            "segment_id": day,
            "status": "RECONCILE_FAIL",
            "raw": raw_count,
            "struct": structured,
            "path": str(path),
        }
    scope, seg_start, seg_end = inventory_scope(conn, day)
    scope = dict(scope)
    scope.setdefault("coverage_mode", "official_archive_index_reconciled")
    scope.setdefault("expected_frequency", "trading_day")
    scope["expected_item_unit"] = "official_archive_file"
    scope.setdefault("segment_granularity", OTC_GRAIN)
    scope.setdefault("universe_rule", "all_bonds_in_official_publication_file")
    scope["segment_start"] = seg_start
    scope["segment_end"] = seg_end
    scope["source_url"] = source_url
    scope["source_format"] = fmt
    run_id = next_run_id(conn)
    required = RequiredCoverageSegment(
        source="jsda",
        dataset=OTC_DATASET,
        segment_id=day,
        segment_start=seg_start,
        segment_end=seg_end,
        expected_scope=scope,
        expected_items=1,
    )
    record_required_segments(conn, [required])
    receipt_service.record_persisted_success(
        store,
        required=required,
        run_id=run_id,
        raw_artifact_paths=(path,),
        raw_records=parsed,
        structured_table="jsda_otc_bond_reference_prices",
        normalized_records=rows,
        pagination_exhausted=True,
        discovery_exhausted=True,
        checked_at=now,
        source_request={"source_url": source_url, "segment_id": day},
        extra_evidence={
            "fetched_via": "cf_workers_fetch+local_raw",
            "local_raw_path": str(path),
            "r2_key_hint": f"raw/jsda/jsda_otc_bond_reference_prices/file_{path.name}/",
            "source_url": source_url,
            "parser_note": f"parse_otc_reference ({fmt}) + normalize_otc_reference_prices",
            "wave": WAVE,
            "full_ok": "http200_size_gt_100kb",
            "policy": "W107_planned_official_historical_partial_backfill",
            "gate": "historical_gt_100kb_or_tip_1_5mb",
            "path_style": path.suffix,
            "opt": "triggers_off_bulk",
        },
    )
    return {
        "dataset": OTC_DATASET,
        "segment_id": day,
        "status": "SEALED",
        "raw": raw_count,
        "struct": structured,
        "run_id": run_id,
        "digest": digest,
        "path": str(path),
        "size": len(raw),
        "fmt": fmt,
        "quote_effective_date": quote_effective_date,
        "secs": round(time.time() - t0, 2),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log-dir", type=Path, required=True)
    p.add_argument("--items", type=Path, default=None, help="full_ok json; default <log-dir>/otc_full_ok.json")
    p.add_argument("--wave", type=str, default="jsda_otc_official_backfill")
    p.add_argument(
        "--index-text",
        default=None,
        metavar="PATH",
        help=(
            "local official-archive index HTML. Omitted: index_text is None "
            "so OTC required set is fail-closed empty, not a calendar replay. "
            "Does not fetch live JSDA HTML."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    global ITEMS, LOGDIR, WAVE
    p = _build_parser()
    args = p.parse_args(argv)
    LOGDIR = args.log_dir
    WAVE = str(args.wave)
    items_path = args.items or (LOGDIR / "otc_full_ok.json")
    ITEMS = json.loads(items_path.read_text())
    try:
        index_text = _read_index_text(args.index_text)
    except FileNotFoundError as e:
        print(f"Error: {e}", flush=True)
        return 1
    print(
        f"official PARTIAL seal n={len(ITEMS)} wave={WAVE} "
        f"span={ITEMS[0]['day'] if ITEMS else None}..{ITEMS[-1]['day'] if ITEMS else None}",
        flush=True,
    )
    store = SqliteStore(DB)
    conn = store._conn  # noqa: SLF001
    conn.execute("PRAGMA busy_timeout=600000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2097152")  # 2GiB
    conn.execute("PRAGMA mmap_size=1073741824")
    pre = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments "
        "WHERE dataset='jsda_otc_bond_reference_prices' AND status='COMPLETE'"
    ).fetchone()[0]
    stored_labels = [
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT publication_label_date "
            "FROM jsda_otc_bond_reference_prices"
        ).fetchall()
    ]
    effective_dates = resolve_quote_effective_dates(
        (),
        stored_labels=tuple(stored_labels)
        + tuple(str(item["day"]) for item in ITEMS),
    )
    print("PRE OTC COMPLETE", pre, flush=True)

    print("drop snapshot triggers...", flush=True)
    drop_triggers(conn)

    receipt_service = open_governed_receipt_service()
    results = []
    sealed_n = 0
    t_all = time.time()
    try:
        for i, item in enumerate(ITEMS, 1):
            day = item["day"]
            code = item["code"]
            url = item.get("url") or item.get("winning_url") or ""
            has_success = conn.execute(
                "SELECT 1 FROM collection_receipts "
                "WHERE dataset='jsda_otc_bond_reference_prices' "
                "AND segment_id=? AND status='SUCCESS' LIMIT 1",
                (day,),
            ).fetchone()
            if has_success:
                results.append({"segment_id": day, "status": "ALREADY_RECEIPT_SUCCESS"})
                continue
            path = resolve_path(day, code)
            if path is None:
                results.append({"segment_id": day, "status": "RAW_MISS", "code": code})
                print(results[-1], flush=True)
                continue
            r = seal_day(
                store,
                day,
                path,
                url,
                receipt_service,
                quote_effective_date=effective_dates.get(day),
            )
            results.append(r)
            if r.get("status") == "SEALED":
                sealed_n += 1
            else:
                print("NON_SEAL", r, flush=True)
            if i % 5 == 0 or r.get("status") != "SEALED":
                rate = sealed_n / max(time.time() - t_all, 1e-6)
                print(
                    f"seal {i}/{len(ITEMS)} day={day} status={r.get('status')} "
                    f"sealed={sealed_n} secs={r.get('secs')} rate={rate:.2f}/s "
                    f"run={r.get('run_id')}",
                    flush=True,
                )
            if i % 100 == 0:
                try:
                    ck = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                    print(f"wal_checkpoint_passive {ck}", flush=True)
                except sqlite3.Error as e:
                    print(f"wal_checkpoint err {e}", flush=True)
    finally:
        print("restore snapshot triggers...", flush=True)
        restore_triggers(conn)

    if os.environ.get("SKIP_REFRESH"):
        print("SKIP_REFRESH set — defer ledger refresh", flush=True)
        Path(LOGDIR / "otc_seal_result_partial.json").write_text(
            json.dumps({"results": results, "sealed_n": sealed_n}, indent=2, default=str)
        )
        print("PARTIAL_SEAL_DONE", sealed_n, flush=True)
        store.close()
        return 0
    print("refresh_coverage_ledger (OTC)...", flush=True)
    t_ref = time.time()
    refresh_otc_coverage(conn, DB, index_text=index_text, today="2026-08-21")
    conn.commit()
    print(f"refresh done in {time.time()-t_ref:.1f}s", flush=True)

    post_ids = [
        r[0]
        for r in conn.execute(
            "SELECT segment_id FROM coverage_segments "
            "WHERE dataset='jsda_otc_bond_reference_prices' AND status='COMPLETE' "
            "ORDER BY segment_id"
        )
    ]
    status_counts = list(
        conn.execute(
            "SELECT status, COUNT(*) n, MIN(segment_id), MAX(segment_id) "
            "FROM coverage_segments WHERE dataset='jsda_otc_bond_reference_prices' "
            "GROUP BY status"
        )
    )
    by_year = list(
        conn.execute(
            "SELECT substr(segment_start,1,4) y, COUNT(*) "
            "FROM coverage_segments WHERE dataset='jsda_otc_bond_reference_prices' "
            "AND status='COMPLETE' GROUP BY y ORDER BY y"
        )
    )
    platform = conn.execute(
        "SELECT count(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]
    empty_otc = conn.execute(
        """
        SELECT count(*) FROM coverage_segments
        WHERE dataset='jsda_otc_bond_reference_prices' AND status='COMPLETE'
          AND (expected_items IS NULL OR expected_items=0)
        """
    ).fetchone()[0]
    sealed = [r for r in results if r.get("status") == "SEALED"]
    summary = {
        "wave": WAVE,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "pre_complete": pre,
        "post_complete": len(post_ids),
        "delta": len(post_ids) - pre,
        "tip_input_n": len(ITEMS),
        "sealed_n": len(sealed),
        "sealed_days": [r["segment_id"] for r in sealed],
        "status_counts": [
            {"status": s[0], "n": s[1], "min": s[2], "max": s[3]} for s in status_counts
        ],
        "complete_by_year": {y: n for y, n in by_year},
        "complete_span": [post_ids[0], post_ids[-1]] if post_ids else None,
        "platform_complete": platform,
        "empty_otc_complete": empty_otc,
        "elapsed_s": round(time.time() - t_all, 1),
        "results": results,
    }
    (LOGDIR / "otc_seal_result.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    (LOGDIR / "otc_seal.json").write_text(
        json.dumps({k: summary[k] for k in summary if k not in ("results", "sealed_days")}, indent=2)
        + "\n"
    )
    print(
        json.dumps(
            {k: summary[k] for k in summary if k not in ("results", "sealed_days")},
            indent=2,
        )
    )
    print("sealed_n", len(sealed), "COMPLETE", pre, "->", len(post_ids), "span", summary["complete_span"])
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
