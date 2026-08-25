#!/usr/bin/env python3
"""Build a content-addressed, non-secret production release evidence file.

The caller supplies observed release facts as JSON.  This script validates the
minimum acceptance surface, rejects local paths and secret-shaped material,
then writes an immutable envelope whose filename is the digest of its payload.
The encrypted D1 backup itself and every decryption/signing credential remain
outside this artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = "quant-platform-release-evidence/v1"
REQUIRED_FIELDS = (
    "source_sha",
    "origin_main_sha",
    "required_check",
    "cloudflare_build",
    "merged_prs",
    "open_prs",
    "deployments",
    "migrations",
    "smoke",
    "quant_mcp",
    "backup",
    "controlled_pilot",
    "mass_research",
    "rollback_status",
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:secret|token|password|private_key|api_key|credential)(?:$|_)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:-----BEGIN (?:OPENSSH |EC |RSA |)PRIVATE KEY-----|"
    r"\b(?:sk|ghp|github_pat|glpat)-[A-Za-z0-9_-]{16,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*)",
    re.IGNORECASE,
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def payload_digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _walk(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                raise ValueError(
                    f"release evidence contains a secret-shaped key: {'.'.join(path + (key,))}"
                )
            _walk(item, path + (key,))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, path + (str(index),))
        return
    if not isinstance(value, str):
        return
    if _SENSITIVE_VALUE.search(value):
        raise ValueError(
            f"release evidence contains secret-shaped material at {'.'.join(path)}"
        )
    # Evidence must be portable.  URLs and repository-relative paths are fine;
    # host-specific absolute paths are not.
    if value.startswith(("/Users/", "/home/", "C:\\Users\\")):
        raise ValueError(
            f"release evidence contains a local absolute path at {'.'.join(path)}"
        )


def validate_payload(payload: Mapping[str, Any]) -> None:
    if tuple(payload) != REQUIRED_FIELDS:
        missing = [field for field in REQUIRED_FIELDS if field not in payload]
        extra = [field for field in payload if field not in REQUIRED_FIELDS]
        raise ValueError(
            f"release evidence field order/membership drift: missing={missing}, extra={extra}"
        )
    for field in ("source_sha", "origin_main_sha"):
        if not _SHA.fullmatch(str(payload[field])):
            raise ValueError(f"{field} must be a full lowercase Git SHA")
    if payload["source_sha"] != payload["origin_main_sha"]:
        raise ValueError("release source SHA must equal observed origin/main SHA")
    if not isinstance(payload["deployments"], Mapping) or not payload["deployments"]:
        raise ValueError("deployments must record at least one active Worker")
    if not isinstance(payload["migrations"], Mapping) or not payload["migrations"]:
        raise ValueError("migrations must record remote post-apply state")
    backup = payload["backup"]
    if not isinstance(backup, Mapping):
        raise ValueError("backup must be an object")
    if backup.get("encrypted") is not True:
        raise ValueError("release evidence may reference only an encrypted backup")
    if not _DIGEST.fullmatch(str(backup.get("ciphertext_digest") or "")):
        raise ValueError("backup ciphertext_digest must be sha256:<hex>")
    if "path" in backup or "key" in backup:
        raise ValueError("backup paths and key material are private and must be omitted")
    if payload["controlled_pilot"] not in {"GO", "NO-GO"}:
        raise ValueError("controlled_pilot must be GO or NO-GO")
    if payload["mass_research"] != "NO-GO":
        raise ValueError("Phase 6.3.1 release evidence must keep Mass Research NO-GO")
    _walk(payload)


def build_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_payload(payload)
    digest = payload_digest(payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_digest": digest,
        "payload": dict(payload),
    }


def write_envelope(payload: Mapping[str, Any], output_dir: Path) -> Path:
    envelope = build_envelope(payload)
    digest_hex = envelope["evidence_digest"].removeprefix("sha256:")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"quant-platform-release-evidence-{digest_hex}.json"
    rendered = json.dumps(envelope, ensure_ascii=False, indent=2) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"content-addressed evidence collision: {target.name}")
        return target
    target.write_text(rendered, encoding="utf-8")
    target.chmod(0o444)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="observed non-secret release facts JSON")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("release evidence input must be a JSON object")
    target = write_envelope(raw, args.output_dir)
    print(target.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
