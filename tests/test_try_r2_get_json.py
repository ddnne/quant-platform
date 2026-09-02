"""CLI r2 object get --remote for panel cache is not artifact authority."""
from __future__ import annotations

from ops.r2_io import R2IOError, try_r2_get_json


def test_try_r2_get_json_cli_miss_and_garbage_return_none_not_complete(
    monkeypatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def _miss(bucket, key, **_k):
        seen.append((bucket, key))
        raise R2IOError("object not found")

    monkeypatch.setattr(
        "ops.r2_io.default_r2_get_object", _miss
    )
    miss = try_r2_get_json(
        "quant-structured", "research/mass_eval/panels_cache/x/meta.json"
    )
    assert miss is None
    assert seen
    assert miss != "COMPLETE"

    def _garbage(_bucket, _key, **_k):
        return b"<<<not-json>>>"

    monkeypatch.setattr(
        "ops.r2_io.default_r2_get_object", _garbage
    )
    garbage = try_r2_get_json(
        "quant-structured", "research/mass_eval/panels_cache/x/meta.json"
    )
    assert garbage is None
    assert garbage != "COMPLETE"
