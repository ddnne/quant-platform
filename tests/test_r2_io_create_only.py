"""R2 put is create-only by default. Not GO."""
from __future__ import annotations

from research.r2_io import default_r2_put


def test_dry_run_does_not_need_wrangler(tmp_path) -> None:
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        dry_run=True,
        staging_dir=tmp_path,
    )
    assert got["status"] == "dry_run"
    assert got.get("created") is not True
