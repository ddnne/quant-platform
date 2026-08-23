"""Glob worker src *.ts: extracted json/token/sha256/freeze stay in named modules."""

from __future__ import annotations

from pathlib import Path

WORKERS = Path(__file__).resolve().parents[1] / "platform" / "workers"


def _worker_src_ts() -> list[Path]:
    files: list[Path] = []
    for src_dir in sorted(WORKERS.glob("*/src")):
        for path in sorted(src_dir.rglob("*.ts")):
            if path.name.endswith(".test.ts"):
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _rel(path: Path) -> str:
    return str(path.relative_to(WORKERS))


def test_timing_safe_equal_bytes_stays_in_token_modules() -> None:
    offenders: list[str] = []
    found = False
    for path in _worker_src_ts():
        src = path.read_text(encoding="utf-8")
        if "function timingSafeEqualBytes" not in src:
            continue
        found = True
        if path.name not in {"authorized.ts", "ingestion_token.ts"}:
            offenders.append(_rel(path))
    assert found
    assert not offenders, (
        "function timingSafeEqualBytes outside authorized.ts/ingestion_token.ts: "
        + ", ".join(offenders)
    )


def test_json_definition_stays_in_http_json() -> None:
    offenders: list[str] = []
    found = False
    for path in _worker_src_ts():
        src = path.read_text(encoding="utf-8")
        if "export function json(" not in src:
            continue
        found = True
        if path.name != "http_json.ts":
            offenders.append(_rel(path))
    assert found
    assert not offenders, (
        "export function json( outside http_json.ts: " + ", ".join(offenders)
    )


def test_sha256_hex_definition_stays_in_sha256() -> None:
    offenders: list[str] = []
    found = False
    for path in _worker_src_ts():
        src = path.read_text(encoding="utf-8")
        if (
            "export async function sha256Hex" not in src
            and "export async function sha256HexFrom" not in src
        ):
            continue
        found = True
        if path.name != "sha256.ts":
            offenders.append(_rel(path))
    assert found
    assert not offenders, (
        "export async function sha256Hex/sha256HexFrom outside sha256.ts: "
        + ", ".join(offenders)
    )


def test_freeze_payload_stays_in_freeze() -> None:
    offenders: list[str] = []
    found = False
    for path in _worker_src_ts():
        src = path.read_text(encoding="utf-8")
        if "export function freezePayload" not in src:
            continue
        found = True
        if path.name != "freeze.ts":
            offenders.append(_rel(path))
    assert found
    assert not offenders, (
        "export function freezePayload outside freeze.ts: " + ", ".join(offenders)
    )
