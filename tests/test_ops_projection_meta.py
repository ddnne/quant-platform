from pathlib import Path

from ops.projection_meta import build_projection_metadata


def test_missing_db_is_missing(tmp_path: Path):
    meta = build_projection_metadata(tmp_path / "nope.sqlite")
    assert meta["status"] == "MISSING"


def test_failed_refresh_never_fresh(tmp_path: Path):
    # empty file is not a valid sqlite with coverage — status FAILED or similar
    db = tmp_path / "empty.sqlite"
    import sqlite3
    sqlite3.connect(db).close()
    meta = build_projection_metadata(
        db, refresh_status="failed", refresh_error="boom"
    )
    assert meta["status"] == "DEGRADED_REFRESH_FAILED"
    assert meta["last_refresh_error"] == "boom"
