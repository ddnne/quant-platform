#!/usr/bin/env python3
"""Automate Coverage refresh + immutable Ops projection publication.

Pipeline:
  1. Optional: refresh_coverage_ledger on local research DB
  2. export_ops_projection SQL
  3. If --apply-remote: append to dedicated quant-ops-projection D1
  4. Verify that the expected immutable generation became active

Removes the "human must remember export commands" sole path. Remote MCP still
never gains write tools; this script is an out-of-band publisher.

The publisher never deletes or updates a generation. An incomplete import may
leave only unreferenced content rows; it cannot append a sealed generation or
move the active pointer, so the Worker continues to read the prior generation.
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
import re
import sqlite3
import subprocess
import tomllib
from datetime import datetime, timezone

ROOT = ensure_repo_root()

from ingestion.jsda.official_index import read_local_index_text  # noqa: E402
from ops.projection_signing import (  # noqa: E402
    OpsProjectionSignatureError,
    load_ops_projection_signer,
)
from scripts.export_ops_projection import (  # noqa: E402
    _render_trusted_projection_bundle,
    render_projection_bundle,
)
from scripts.sync_d1_to_sqlite import (  # noqa: E402
    _authenticated_export_cursor_chain,
)

OPS_PROJECTION_DATABASE = "quant-ops-projection"
OPS_PROJECTION_DATABASE_ID = "1b497e8a-5c69-4e19-ae2e-89a8f3185272"
OPS_WRANGLER_VERSION = "4.125.0"
OPS_WRANGLER_CWD = ROOT / "platform" / "workers" / "quant-ops-mcp"
OPS_WRANGLER_CONFIG = OPS_WRANGLER_CWD / "wrangler.toml"
OPS_WRANGLER_BIN = OPS_WRANGLER_CWD / "node_modules" / ".bin" / "wrangler"
GOVERNED_LOCAL_DB = (ROOT / "data" / "structured" / "ingestion.sqlite").resolve()
GOVERNED_SNAPSHOT_DIR = (ROOT / "data" / "research_snapshots").resolve()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validated_ops_wrangler() -> tuple[str, Path]:
    """Pin production Ops commands to the reviewed binary/config/D1 id."""
    executable = OPS_WRANGLER_BIN.resolve()
    config = OPS_WRANGLER_CONFIG.resolve()
    package_json = executable.parents[1] / "package.json"
    try:
        installed = str(
            json.loads(package_json.read_text(encoding="utf-8"))["version"]
        )
        document = tomllib.loads(config.read_text(encoding="utf-8"))
        bindings = document["env"]["production"]["d1_databases"]
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("cannot verify pinned Ops Wrangler authority") from exc
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise RuntimeError("repository-pinned Ops Wrangler is unavailable")
    if installed != OPS_WRANGLER_VERSION:
        raise RuntimeError("Ops Wrangler version does not match the pinned policy")
    projection = [
        row
        for row in bindings
        if isinstance(row, dict) and row.get("binding") == "OPS_PROJECTION_DB"
    ]
    if (
        len(projection) != 1
        or projection[0].get("database_name") != OPS_PROJECTION_DATABASE
        or projection[0].get("database_id") != OPS_PROJECTION_DATABASE_ID
    ):
        raise RuntimeError("Ops Wrangler config is not bound to governed projection D1")
    return str(executable), config


def load_otc_index_text(path: Path | None) -> str | None:
    """Read official OTC index HTML. Missing path or file is None, not calendar."""
    return read_local_index_text(path, missing_ok=True)


def count_local_complete(db_path: Path) -> int:
    """Count COMPLETE coverage_segments in a local SQLite ops/research DB.

    Raises sqlite3.Error if the table is missing — callers must surface that
    rather than silently treating an unprobed DB as zero (fail-closed).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments WHERE status = 'COMPLETE'"
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def count_remote_complete(
    *,
    timeout_sec: int = 120,
) -> int | None:
    """Query remote D1 COMPLETE count via wrangler. None if unreachable.

    Returns None for any transport / parse / non-zero exit failure so that
    enforce_complete_count_guard can apply fail-closed semantics.
    """
    # Probe the same dedicated read-model D1 the Ops MCP reads.  Never query
    # quant-ingest through the Ops Worker configuration.
    try:
        wrangler, config = _validated_ops_wrangler()
    except RuntimeError:
        print("WARN: pinned remote COMPLETE probe is unavailable", file=sys.stderr)
        return None
    cmd = [
        wrangler,
        "d1",
        "execute",
        OPS_PROJECTION_DATABASE,
        "--remote",
        "--config",
        str(config),
        "--env",
        "production",
        "--yes",
        "--json",
        "--command",
        "SELECT COUNT(*) AS c FROM coverage_segments s "
        "JOIN ops_projection_active a "
        "ON a.singleton=1 AND a.generation_id=s.projection_generation_id "
        "WHERE s.status='COMPLETE'",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(OPS_WRANGLER_CWD),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print(
            "WARN: remote COMPLETE probe failed; provider output withheld",
            file=sys.stderr,
        )
        return None
    if proc.returncode != 0:
        print(
            f"WARN: remote COMPLETE probe exit={proc.returncode}; "
            "provider output withheld",
            file=sys.stderr,
        )
        return None
    text = proc.stdout or ""
    idx = text.find("[")
    if idx < 0:
        return None
    try:
        payload = json.loads(text[idx:])
        if not isinstance(payload, list) or not payload:
            return None
        results = payload[0].get("results") or []
        if not results:
            return None
        return int(results[0].get("c", results[0].get("COUNT(*)", 0)))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError):
        m = re.search(r'"c"\s*:\s*(\d+)', text)
        return int(m.group(1)) if m else None


def read_remote_active_generation(
    *,
    timeout_sec: int = 120,
) -> str | None:
    """Return the dedicated projection's active generation, or None."""
    try:
        wrangler, config = _validated_ops_wrangler()
    except RuntimeError:
        return None
    command = [
        wrangler,
        "d1",
        "execute",
        OPS_PROJECTION_DATABASE,
        "--remote",
        "--config",
        str(config),
        "--env",
        "production",
        "--yes",
        "--json",
        "--command",
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1",
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(OPS_WRANGLER_CWD),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout or ""
    start = text.find("[")
    if start < 0:
        return None
    try:
        payload = json.loads(text[start:])
        rows = payload[0].get("results") or []
        value = rows[0].get("generation_id") if rows else None
        return str(value) if value else None
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return None

def enforce_complete_count_guard(
    *,
    local_complete: int,
    remote_complete: int | None,
) -> str | None:
    """Return error message if full apply must be refused; else None.

    Fail-closed: unknown remote (None), invalid counts, and regressions refuse.
    Contract transitions require a separate governed workflow; this production
    publisher intentionally exposes no generic operator override.
    """
    if local_complete < 0 or (remote_complete is not None and remote_complete < 0):
        return "Refusing --apply-remote: COMPLETE counts must be non-negative"
    if remote_complete is None:
        return (
            "Refusing --apply-remote: could not read remote COMPLETE count "
            "(fail-closed; no generic override is available)."
        )
    if local_complete < remote_complete:
        return (
            f"Refusing --apply-remote: local COMPLETE segments ({local_complete}) "
            f"fewer than remote ({remote_complete}). "
            "Activating this generation would regress current COMPLETE evidence. "
            "Use a governed signed contract-transition workflow instead."
        )
    return None

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=GOVERNED_LOCAL_DB,
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=ROOT / "data" / "research_snapshots",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "ops" / "projection.sql",
    )
    parser.add_argument(
        "--meta-output",
        type=Path,
        default=ROOT / "data" / "ops" / "projection_meta.json",
    )
    parser.add_argument(
        "--storage-hot-cutoff",
        default=None,
        help="Optional reviewed ISO hot-window cutoff; never defaults to a date.",
    )
    parser.add_argument(
        "--refresh-coverage",
        action="store_true",
        help="Run coverage ledger refresh before export (requires evidence/receipts).",
    )
    parser.add_argument(
        "--otc-index-html",
        type=Path,
        default=None,
        help=(
            "Optional JSDA OTC official-index HTML for coverage refresh. "
            "Missing file is fail-closed empty (index_text=None), not calendar inventory."
        ),
    )
    parser.add_argument(
        "--apply-remote",
        action="store_true",
        help="Apply exported SQL to remote D1 via wrangler (requires CF auth).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render SQL only; do not write meta apply.",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"ERROR: local DB not found: {args.db}", file=sys.stderr)
        return 2

    db_path = args.db.resolve()
    trusted_cursor_chain = _authenticated_export_cursor_chain(db_path)
    has_trusted_cursor_chain = all(
        isinstance(value, int) and value > 0 for value in trusted_cursor_chain
    )
    if args.apply_remote and db_path != GOVERNED_LOCAL_DB:
        print(
            "ERROR: remote Ops publication requires the governed local mirror path",
            file=sys.stderr,
        )
        return 7
    if args.apply_remote and args.snapshot_dir.resolve() != GOVERNED_SNAPSHOT_DIR:
        print(
            "ERROR: remote Ops publication requires the governed snapshot directory",
            file=sys.stderr,
        )
        return 7
    if args.apply_remote and args.otc_index_html is not None:
        print(
            "ERROR: remote Ops publication cannot consume a caller-selected OTC index",
            file=sys.stderr,
        )
        return 7
    if args.apply_remote and args.storage_hot_cutoff is not None:
        print(
            "ERROR: remote Ops publication cannot consume a caller-selected hot cutoff",
            file=sys.stderr,
        )
        return 7
    if args.apply_remote and not has_trusted_cursor_chain:
        print(
            "ERROR: remote Ops publication requires a COMPLETE authenticated "
            "D1 sync audit with exact local cursor/content identity",
            file=sys.stderr,
        )
        return 7

    try:
        projection_signer = load_ops_projection_signer()
    except OpsProjectionSignatureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 6
    if (
        args.apply_remote
        and not args.dry_run
        and has_trusted_cursor_chain
        and projection_signer is None
    ):
        print(
            "ERROR: dedicated Ops Projection signing key is unavailable",
            file=sys.stderr,
        )
        return 6

    refresh_status = "skipped"
    refresh_error = None
    last_refresh_attempt_at = _now()
    last_success_at = None
    if args.refresh_coverage:
        from storage.sqlite_store import SqliteStore
        from storage.coverage_ledger import refresh_coverage_ledger

        last_refresh_attempt_at = _now()
        store = SqliteStore(args.db)
        index_text = load_otc_index_text(args.otc_index_html)
        try:
            refresh_coverage_ledger(
                store._conn,  # noqa: SLF001
                args.db,
                index_text=index_text,
            )
            store._conn.commit()  # noqa: SLF001
            refresh_status = "success"
            last_success_at = _now()
            print("coverage ledger refresh ok")
        except Exception as exc:  # noqa: BLE001
            refresh_status = "failed"
            refresh_error = str(exc)[:2000]
            print(f"coverage ledger refresh FAILED: {exc}", file=sys.stderr)
            # Do not apply-remote a FRESH-looking projection after a failed refresh.
        finally:
            store.close()

    if args.apply_remote and refresh_status == "failed":
        print(
            "ERROR: refusing --apply-remote after coverage refresh failed "
            "(fail-closed; projection FRESH requires refresh_success).",
            file=sys.stderr,
        )
        return 4

    # Fail-closed guard before spending time on full SQL export when apply is requested.
    # 対象: 完全 publish のみ (dry-run / targeted reeval は対象外)
    if args.apply_remote and not args.dry_run:
        local_n = count_local_complete(args.db)
        remote_n = count_remote_complete()
        guard_err = enforce_complete_count_guard(
            local_complete=local_n,
            remote_complete=remote_n,
        )
        if guard_err:
            print(f"ERROR: {guard_err}", file=sys.stderr)
            print(
                f"guard_detail local_complete={local_n} remote_complete={remote_n}",
                file=sys.stderr,
            )
            return 3
        print(f"complete_count_guard ok local={local_n} remote={remote_n}")

    render_kwargs = {
        "snapshot_dir": args.snapshot_dir,
        "refresh_status": refresh_status,
        "refresh_error": refresh_error,
        "last_refresh_attempt_at": last_refresh_attempt_at,
        "last_success_at": last_success_at,
        "storage_hot_cutoff": args.storage_hot_cutoff,
    }
    if has_trusted_cursor_chain and projection_signer is not None:
        bundle = _render_trusted_projection_bundle(
            db_path,
            source_cursor=trusted_cursor_chain[0],
            export_cursor=trusted_cursor_chain[1],
            projection_signer=projection_signer,
            **render_kwargs,
        )
    else:
        bundle = render_projection_bundle(db_path, **render_kwargs)
    sql = bundle.sql
    meta = dict(bundle.metadata)
    meta["publisher"] = "scripts/publish_ops_projection.py"
    meta["last_refresh_status"] = refresh_status
    meta["last_refresh_error"] = refresh_error
    meta["local_db"] = str(args.db)
    meta["snapshot_dir"] = str(args.snapshot_dir)
    meta["sql_bytes"] = len(sql.encode("utf-8"))
    meta["generation_id"] = bundle.generation_id
    meta["source_db_digest"] = bundle.source_db_digest
    meta["content_digest"] = bundle.content_digest
    meta["row_counts"] = dict(bundle.row_counts)
    meta["signature_status"] = "SIGNED" if bundle.signed_envelope else "UNSIGNED"
    meta["issuer_key_id"] = (
        bundle.signed_envelope.get("issuer_key_id")
        if bundle.signed_envelope
        else None
    )
    meta["signed_envelope"] = bundle.signed_envelope
    # Back-compat aliases for older readers
    meta["projection_status"] = meta["status"]
    meta["projection_generated_at"] = meta["generated_at"]
    meta["projection_source_generation"] = meta.get("source_generation")

    if args.dry_run:
        print(sql[:2000])
        print(json.dumps(meta, indent=2))
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sql, encoding="utf-8")
    args.meta_output.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({meta['sql_bytes']} bytes)")
    print(f"wrote {args.meta_output}")

    if args.apply_remote:
        if refresh_status == "failed":
            print(
                "ERROR: refusing --apply-remote after coverage refresh failed "
                "(fail-closed; projection FRESH requires refresh_success).",
                file=sys.stderr,
            )
            return 4
        # D1 remote execute rejects explicit SQL BEGIN/COMMIT and fails the
        # whole import on duplicate-column ALTER (schema is migration-owned).
        def _keep_remote_line(line: str) -> bool:
            stripped = line.strip().upper()
            if stripped in {"BEGIN TRANSACTION;", "BEGIN;", "COMMIT;", "COMMIT"}:
                return False
            if stripped.startswith("ALTER TABLE ") and " ADD COLUMN " in stripped:
                return False
            return True

        remote_sql = (
            "\n".join(line for line in sql.splitlines() if _keep_remote_line(line))
            + "\n"
        )
        remote_path = args.output.with_suffix(".d1.sql")
        remote_path.write_text(remote_sql, encoding="utf-8")
        try:
            wrangler, config = _validated_ops_wrangler()
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 8
        cmd = [
            wrangler,
            "d1",
            "execute",
            OPS_PROJECTION_DATABASE,
            "--remote",
            "--config",
            str(config),
            "--env",
            "production",
            "--yes",
            "--file",
            str(remote_path),
        ]
        print("running pinned Ops projection D1 apply")
        proc = subprocess.run(
            cmd,
            cwd=OPS_WRANGLER_CWD,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(
                "ERROR: remote apply failed; provider output withheld",
                file=sys.stderr,
            )
            return proc.returncode
        observed_generation = read_remote_active_generation()
        if observed_generation != bundle.generation_id:
            print(
                "ERROR: projection import did not activate the expected generation "
                f"expected={bundle.generation_id} observed={observed_generation}",
                file=sys.stderr,
            )
            return 5
        meta["applied_at"] = _now()
        meta["active_generation"] = observed_generation
        if meta.get("status") == "FRESH" and refresh_status != "success":
            meta["status"] = "STALE"
        meta["projection_status"] = meta["status"]
        args.meta_output.write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        print("remote projection applied")

    if refresh_status == "failed":
        return 4
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
