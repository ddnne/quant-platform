#!/usr/bin/env python3
"""Seal official JSDA OTC archive days (not a wave runner).

Historical gate: HTTP200 + size>100KB + non-HTML + parse rows>0.
No invent / empty COMPLETE / fake densify.
"""
from __future__ import annotations

import hashlib
import json
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
sys.path.insert(0, str(ROOT / "packages" / "data_plane"))
sys.path.insert(0, str(ROOT / "packages" / "edge"))

from ingestion.jsda.normalize import normalize_otc_reference_prices  # noqa: E402
from ingestion.jsda.parse import parse_otc_reference_csv, parse_otc_reference_xlsx  # noqa: E402
from storage.coverage_ledger import (  # noqa: E402
    RequiredCoverageSegment,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
)
from storage.trusted_receipt import open_signed_receipt_authority  # noqa: E402

RAW_ROOT = ROOT / "data" / "raw" / "jsda" / "jsda_otc_bond_reference_prices"
DB = ROOT / "data" / "structured" / "ingestion.sqlite"
FULL_OK_MIN = 100_000
WAVE = "jsda_otc_official_backfill"
W_LABEL = "OTC"
ITEMS: list = []
LOGDIR = ROOT / "data" / "ops"

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
        WHERE dataset='jsda_otc_bond_reference_prices' AND segment_id=?
        """,
        (day,),
    ).fetchone()
    if row is None:
        return {
            "coverage_mode": "official_archive_index_reconciled",
            "expected_frequency": "trading_day",
            "expected_item_unit": "source_query",
            "segment_end": day,
            "segment_granularity": "official_archive_day",
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


def _parse_otc_xls(raw: bytes, day: str):
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
                "publication_label_date": day,
                "quote_effective_date": day,
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


def parse_raw(path: Path, day: str):
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return (
            raw,
            parse_otc_reference_csv(
                raw, publication_label_date=day, quote_effective_date=day
            ),
            "csv",
        )
    if suffix == ".xlsx":
        return (
            raw,
            parse_otc_reference_xlsx(
                raw, publication_label_date=day, quote_effective_date=day
            ),
            "xlsx",
        )
    if suffix == ".xls":
        return raw, _parse_otc_xls(raw, day), "xls"
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
    """Replace any partial day facts, then bulk INSERT. Triggers must be off.

    Always filter with source='jsda' so the composite PRIMARY KEY prefix is used.
    Date-only predicates force a full-table scan on ~187GB facts.
    """
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
    conn.commit()
    return len(rows)


def seal_day(conn, day, path, source_url, issuer):
    t0 = time.time()
    raw, parsed, fmt = parse_raw(path, day)
    if len(raw) <= FULL_OK_MIN:
        return {"segment_id": day, "status": "NOT_FULL_OK_SIZE", "size": len(raw)}
    head = raw[:200].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return {"segment_id": day, "status": "HTML_BODY", "size": len(raw)}
    if not parsed:
        return {"segment_id": day, "status": "PARSE_ZERO", "path": str(path), "fmt": fmt}
    digest = sha256_file(path)
    now = datetime.now(timezone.utc).isoformat()
    rows = normalize_otc_reference_prices(
        parsed,
        ingested_at=now,
        publication_label_date=day,
        quote_effective_date=day,
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
    scope.setdefault("expected_item_unit", "source_query")
    scope.setdefault("segment_granularity", "official_archive_day")
    scope.setdefault("universe_rule", "all_bonds_in_official_publication_file")
    scope["segment_start"] = seg_start
    scope["segment_end"] = seg_end
    scope["source_url"] = source_url
    scope["source_format"] = fmt
    run_id = next_run_id(conn)
    required = RequiredCoverageSegment(
        source="jsda",
        dataset="jsda_otc_bond_reference_prices",
        segment_id=day,
        segment_start=seg_start,
        segment_end=seg_end,
        expected_scope=scope,
        expected_items=raw_count,
    )
    record_required_segments(conn, [required])
    receipt = issuer.issue(
        required=required,
        run_id=run_id,
        raw=raw,
        observed_items=raw_count,
        structured_row_count=structured,
        raw_row_count=raw_count,
        pagination_exhausted=True,
        raw_manifest_digest=digest,
        extra_digests={
            "eligibility": "TRUSTED_COLLECTION",
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
    record_collection_receipt(conn, receipt)
    conn.commit()
    return {
        "dataset": "jsda_otc_bond_reference_prices",
        "segment_id": day,
        "status": "SEALED",
        "raw": raw_count,
        "struct": structured,
        "run_id": run_id,
        "digest": digest,
        "path": str(path),
        "size": len(raw),
        "fmt": fmt,
        "secs": round(time.time() - t0, 2),
    }


def main() -> int:
    import argparse

    global ITEMS, LOGDIR, WAVE, W_LABEL
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log-dir", type=Path, required=True)
    p.add_argument("--items", type=Path, default=None, help="full_ok json; default <log-dir>/otc_full_ok.json")
    p.add_argument("--wave", type=str, default="jsda_otc_official_backfill")
    args = p.parse_args()
    LOGDIR = args.log_dir
    WAVE = str(args.wave)
    W_LABEL = WAVE
    items_path = args.items or (LOGDIR / "otc_full_ok.json")
    ITEMS = json.loads(items_path.read_text())
    print(
        f"official PARTIAL seal n={len(ITEMS)} wave={WAVE} "
        f"span={ITEMS[0]['day'] if ITEMS else None}..{ITEMS[-1]['day'] if ITEMS else None}",
        flush=True,
    )
    conn = sqlite3.connect(DB, timeout=600)
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
    print("PRE OTC COMPLETE", pre, flush=True)

    print("drop snapshot triggers...", flush=True)
    drop_triggers(conn)

    issuer = open_signed_receipt_authority()
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
            r = seal_day(conn, day, path, url, issuer)
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

    if __import__("os").environ.get("SKIP_REFRESH"):
        print("SKIP_REFRESH set — defer ledger refresh", flush=True)
        Path(LOGDIR / "otc_seal_result_partial.json").write_text(
            json.dumps({"results": results, "sealed_n": sealed_n}, indent=2, default=str)
        )
        print("PARTIAL_SEAL_DONE", sealed_n, flush=True)
        return 0
    print("refresh_coverage_ledger (OTC)...", flush=True)
    t_ref = time.time()
    refresh_coverage_ledger(
        conn,
        DB,
        datasets=["jsda_otc_bond_reference_prices"],
        today="2026-08-21",
    )
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
        "W": W_LABEL,
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
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
