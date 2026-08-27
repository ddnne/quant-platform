from __future__ import annotations

from datetime import date

import pytest

from ingestion.pipeline import save_raw


def test_raw_persist_is_create_only_and_idempotent_for_identical_bytes(tmp_path):
    first = save_raw(tmp_path, "jquants", "segment.json", b"one", date(2026, 8, 25))
    second = save_raw(tmp_path, "jquants", "segment.json", b"one", date(2026, 8, 25))

    assert second == first
    assert first.read_bytes() == b"one"
    assert first.stat().st_mode & 0o222 == 0


def test_raw_persist_rejects_identity_collision(tmp_path):
    save_raw(tmp_path, "jquants", "segment.json", b"one", date(2026, 8, 25))

    with pytest.raises(FileExistsError, match="immutable raw identity"):
        save_raw(tmp_path, "jquants", "segment.json", b"two", date(2026, 8, 25))
