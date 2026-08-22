"""R2 object put via wrangler. Local FS is not SoT."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
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


class R2IOError(ValueError):
    """Invalid R2 wrangler I/O input or put failure."""


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
) -> dict[str, Any]:
    """Put one object to R2 via wrangler (remote). dry_run stages only."""
    meta = {
        "bucket": bucket,
        "key": key,
        "bytes": len(body),
        "content_type": content_type,
        "object_path": f"{bucket}/{key}",
    }
    if dry_run:
        staged: str | None = None
        if staging_dir is not None:
            out = Path(staging_dir) / key.replace("/", "__")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
            staged = str(out)
        return {**meta, "status": "dry_run", "staged_path": staged}

    wr = Path(wrangler) if wrangler else DEFAULT_WRANGLER
    cfg = Path(config) if config else DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise R2IOError(
            f"wrangler binary not found for R2 put: {wr}. "
            "Use dry_run=True to stage payloads without remote write."
        )

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
        return {**meta, "status": "put_ok", "wrangler_rc": 0}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "DEFAULT_WRANGLER",
    "DEFAULT_WRANGLER_CONFIG",
    "REPO_ROOT",
    "R2IOError",
    "default_r2_put",
]
