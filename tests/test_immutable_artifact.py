"""Create-if-absent: local digest store and default R2 put. Not GO."""

from pathlib import Path
from types import SimpleNamespace

import research.r2_io as r2_io
from research.r2_io import default_r2_put
from storage.immutable_artifact import ImmutableArtifactStore, content_digest


def test_create_if_absent_and_verify(tmp_path: Path):
    store = ImmutableArtifactStore(tmp_path)
    identity = {"kind": "x", "payload": {"n": 1}}
    ref1 = store.create_if_absent(identity)
    ref2 = store.create_if_absent(identity)
    assert ref1.artifact_id == ref2.artifact_id == content_digest(identity)
    assert ref1.created is True
    assert ref2.created is False
    body = store.verify(ref1.path, ref1.artifact_id)
    assert body["payload"]["n"] == 1


def test_dry_run_r2_put_does_not_need_wrangler(tmp_path: Path) -> None:
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        dry_run=True,
        staging_dir=tmp_path,
    )
    assert got["status"] == "dry_run"
    assert got.get("created") is not True


def test_dry_run_r2_put_does_not_call_remote(tmp_path: Path, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("dry_run must not call remote")

    monkeypatch.setattr(r2_io.subprocess, "run", boom)
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        dry_run=True,
        staging_dir=tmp_path,
    )
    assert got["status"] == "dry_run"
    assert got.get("created") is not True
    staged = Path(got["staged_path"])
    assert staged.read_bytes() == b"{}"


def test_create_only_head_success_skips_put(tmp_path: Path, monkeypatch) -> None:
    wr = tmp_path / "wrangler"
    wr.write_text("")
    cfg = tmp_path / "wrangler.toml"
    cfg.write_text("")
    seen: list[list[str]] = []

    def fake_run(cmd, **_k):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(r2_io.subprocess, "run", fake_run)
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        wrangler=wr,
        config=cfg,
    )
    assert got["status"] == "exists"
    assert got["created"] is False
    assert len(seen) == 1
    assert "head" in seen[0]
    assert "put" not in seen[0]
