"""R2 object put and get via wrangler. Local FS is not SoT.

Python default_r2_put(create_only=True) is head-then-put TOCTOU, not
immutable create-if-absent. Worker onlyIf children-then-manifest is the
immutable authority. Python CLI put is not artifact authority.
Remote put is fail-closed unless QP_ALLOW_PYTHON_R2_PUT=1.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from qp_paths import repo_root

REPO_ROOT = repo_root()
DEFAULT_WRANGLER = (
    REPO_ROOT
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "node_modules"
    / ".bin"
    / "wrangler"
)
DEFAULT_WRANGLER_CONFIG = (
    REPO_ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml"
)

# Private aliases used by history/feature loaders.
_REPO_ROOT = REPO_ROOT
_DEFAULT_WRANGLER = DEFAULT_WRANGLER
_DEFAULT_WRANGLER_CONFIG = DEFAULT_WRANGLER_CONFIG

PYTHON_R2_PUT_ENV = "QP_ALLOW_PYTHON_R2_PUT"

# Comment-level invariant: CLI put is head-then-put TOCTOU, not create-if-absent.
# Python CLI put is not artifact authority.
python_cli_put_is_not_immutable_authority: bool = True


class R2IOError(ValueError):
    """Invalid R2 wrangler I/O input or put/get failure."""


def python_r2_put_allowed() -> bool:
    """True only when QP_ALLOW_PYTHON_R2_PUT=1. Not artifact authority."""
    return os.environ.get(PYTHON_R2_PUT_ENV, "").strip() == "1"


def default_r2_put(
    bucket: str,
    key: str,
    body: bytes,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    content_type: str = "application/json",
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
    create_only: bool = True,
    authoritative: bool = False,
) -> dict[str, Any]:
    """Put one object to R2 via wrangler (remote). dry_run stages only.

    create_only (default True): if the key already exists, do not overwrite.

    wrangler ``r2 object put`` has no create-if-absent / if-not-exists flag
    (Workers ``onlyIf.etagDoesNotMatch`` is not on the CLI). Existence is
    therefore head-then-put. That sequence is TOCTOU: a concurrent writer
    can create the key after a miss and this put will overwrite. If head
    succeeds, skip put and return status ``exists``.
    Python CLI put is not artifact authority and is not the immutable authority;
    Worker onlyIf children-then-manifest is.
    ``authoritative=True`` is refused.
    Remote (non dry_run) put is fail-closed unless QP_ALLOW_PYTHON_R2_PUT=1.
    """
    if authoritative:
        raise R2IOError("python CLI put is not artifact authority")
    meta = {
        "bucket": bucket,
        "key": key,
        "bytes": len(body),
        "content_type": content_type,
        "object_path": f"{bucket}/{key}",
    }
    # Local stage only — never wrangler/remote.
    if dry_run:
        staged: str | None = None
        if staging_dir is not None:
            out = Path(staging_dir) / key.replace("/", "__")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
            staged = str(out)
        return {**meta, "status": "dry_run", "staged_path": staged}

    if not python_r2_put_allowed():
        raise R2IOError(
            f"remote python R2 put without {PYTHON_R2_PUT_ENV}=1; "
            "Python CLI put is not artifact authority"
        )

    wr = Path(wrangler) if wrangler else DEFAULT_WRANGLER
    cfg = Path(config) if config else DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise R2IOError(
            f"wrangler binary not found for R2 put: {wr}. "
            "Use dry_run=True to stage payloads without remote write."
        )

    if create_only:
        # TOCTOU: head hit refuses overwrite; a miss still races the put.
        head = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "head",
                f"{bucket}/{key}",
                "--remote",
                f"--config={cfg}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )
        if head.returncode == 0:
            return {**meta, "status": "exists", "created": False, "wrangler_rc": 0}

    with tempfile.NamedTemporaryFile(
        prefix="r2put_", suffix=".json", delete=False
    ) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "put",
                f"{bucket}/{key}",
                f"--file={tmp_path}",
                "--remote",
                f"--config={cfg}",
                f"--content-type={content_type}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            raise R2IOError(
                f"r2 put failed for {bucket}/{key} rc={proc.returncode}: "
                f"{combined[-1200:]}"
            )
        return {**meta, "status": "put_ok", "created": True, "wrangler_rc": 0}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def default_r2_get_object(
    bucket: str,
    key: str,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    timeout: int = 300,
) -> bytes:
    """Fetch one R2 object body via ``wrangler r2 object get`` (remote)."""
    wr = Path(wrangler) if wrangler else DEFAULT_WRANGLER
    cfg = Path(config) if config else DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise R2IOError(
            f"wrangler binary not found for R2 get: {wr}. "
            "Inject r2_get= or supply local_paths / pre-parsed rows."
        )
    with tempfile.NamedTemporaryFile(
        prefix="r2fc_get_", suffix=".bin", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "get",
                f"{bucket}/{key}",
                f"--file={tmp_path}",
                "--remote",
                f"--config={cfg}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            raise R2IOError(
                f"r2 get failed for {bucket}/{key} rc={proc.returncode}: "
                f"{combined[-1200:]}"
            )
        return tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "DEFAULT_WRANGLER",
    "DEFAULT_WRANGLER_CONFIG",
    "PYTHON_R2_PUT_ENV",
    "REPO_ROOT",
    "R2IOError",
    "default_r2_get_object",
    "default_r2_put",
    "python_cli_put_is_not_immutable_authority",
    "python_r2_put_allowed",
]
