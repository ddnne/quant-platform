"""Wrangler R2 object get. Not a signing or READY authority."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


class R2CliError(ValueError):
    """Remote R2 CLI get failed closed."""


def get_r2_object(
    bucket: str,
    key: str,
    *,
    wrangler: str | Path,
    config: str | Path,
    cwd: str | Path,
    timeout: int = 300,
) -> bytes:
    wr = Path(wrangler)
    cfg = Path(config)
    if not wr.is_file():
        raise R2CliError(f"wrangler binary not found for R2 get: {wr}")
    with tempfile.TemporaryDirectory(prefix="r2fc_get_") as tmp_dir:
        tmp_path = Path(tmp_dir) / "object.bin"
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
            cwd=str(cwd),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            raise R2CliError(
                f"r2 get failed for {bucket}/{key} rc={proc.returncode}: "
                f"{combined[-1200:]}"
            )
        return tmp_path.read_bytes()
