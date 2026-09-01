#!/usr/bin/env python3
"""Fetch official JSDA OTC archive CSVs via CF worker."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

WORKER = "https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev"
FULL_OK_MIN = 100_000


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "qp_paths.py").is_file() and (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("quant-platform repo root not found")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log-dir", type=Path, required=True)
    p.add_argument("--items", type=Path, default=None)
    p.add_argument("--repo", type=Path, default=None)
    args = p.parse_args()
    log = args.log_dir
    root = args.repo or _repo_root()
    raw = root / "data/raw/jsda/jsda_otc_bond_reference_prices"
    items_path = args.items or (log / "otc_items.json")
    progress = log / "otc_download_progress.jsonl"
    items = json.loads(items_path.read_text())
    done: set[str] = set()
    if progress.exists():
        for ln in progress.read_text().splitlines():
            try:
                r = json.loads(ln)
                if r.get("status") == "OK":
                    done.add(r["day"])
            except Exception:
                pass
    todo = [x for x in items if x["day"] not in done]
    print(f"total={len(items)} done={len(done)} todo={len(todo)}", flush=True)
    ok_n = 0
    with progress.open("a") as fh:
        for i, item in enumerate(todo, 1):
            day = item["day"]
            code = item["code"]
            url = item["url"]
            suffix = ".csv"
            if url.lower().endswith(".xls"):
                suffix = ".xls"
            elif url.lower().endswith(".xlsx"):
                suffix = ".xlsx"
            path = raw / day / f"{code}{suffix}"
            if path.is_file() and path.stat().st_size > FULL_OK_MIN:
                row = {
                    "code": code,
                    "day": day,
                    "status": "OK",
                    "size": path.stat().st_size,
                    "path": str(path),
                    "note": "already_local",
                    "url": url,
                }
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                ok_n += 1
                print(f"{i}/{len(todo)} {day} already_local size={row['size']}", flush=True)
                continue

            fetch_url = f"{WORKER}/fetch?url={quote(url, safe='')}"
            last = None
            for attempt in range(5):
                proc = subprocess.run(
                    ["curl", "-sS", "--max-time", "180", "-A", "Mozilla/5.0", fetch_url],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    last = {"status": "CURL_FAIL", "rc": proc.returncode, "err": proc.stderr[-200:]}
                    time.sleep(2 + attempt * 2)
                    continue
                try:
                    data = json.loads(proc.stdout)
                except json.JSONDecodeError as e:
                    last = {"status": "JSON_FAIL", "err": str(e), "head": proc.stdout[:120]}
                    time.sleep(2 + attempt * 2)
                    continue
                if data.get("error") or not data.get("ok"):
                    last = {"status": "WORKER_ERR", "data": {k: data.get(k) for k in ("error", "ok", "http", "note")}}
                    time.sleep(5 + attempt * 5)
                    continue
                if int(data.get("http") or 0) != 200:
                    last = {"status": "HTTP_NOT_200", "http": data.get("http"), "size": data.get("size")}
                    break
                size = int(data.get("size") or 0)
                if size <= FULL_OK_MIN:
                    last = {"status": "NOT_FULL_OK_SIZE", "size": size, "http": 200}
                    break
                b64 = data.get("body_b64")
                if not b64:
                    last = {"status": "NO_BODY_B64", "size": size, "note": data.get("note")}
                    break
                raw = base64.b64decode(b64)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                dig = "sha256:" + hashlib.sha256(raw).hexdigest()
                row = {
                    "code": code,
                    "day": day,
                    "status": "OK",
                    "size": len(raw),
                    "sha256": dig,
                    "path": str(path),
                    "url": url,
                    "http": 200,
                    "content_type": data.get("content_type"),
                }
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                ok_n += 1
                print(f"{i}/{len(todo)} {day} OK size={len(raw)}", flush=True)
                last = None
                break
            if last is not None:
                row = {"code": code, "day": day, "url": url, **last}
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                print(f"{i}/{len(todo)} {day} FAIL {row}", flush=True)
            time.sleep(0.8)
    summary = {"ok_n": ok_n, "todo": len(todo), "total": len(items)}
    (log / "otc_download_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("SUMMARY", summary, flush=True)
    return 0 if ok_n == len(todo) else 2


if __name__ == "__main__":
    import sys

    _scripts = Path(__file__).resolve().parent
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    from _local_market_data_guard import require_local_market_data_opt_in

    require_local_market_data_opt_in()
    raise SystemExit(main())
