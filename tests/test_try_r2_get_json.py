"""CLI r2 object get --remote for panel cache is not artifact authority."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import research.cf_mass_eval_job as job
from research.cf_mass_eval_job import try_r2_get_json


def test_try_r2_get_json_source_is_non_authority_cli_get() -> None:
    src = inspect.getsource(try_r2_get_json)
    doc = try_r2_get_json.__doc__ or ""
    text = f"{doc}\n{src}"
    assert "--remote" in src
    assert "wrangler" in src
    assert "r2" in src
    assert "object" in src
    assert "get" in src
    assert "not artifact authority" in text
    assert "not COMPLETE" in text
    assert "children-then-manifest" in text
    assert "FRESH" in text


def test_try_r2_get_json_cli_miss_and_garbage_return_none_not_complete(
    monkeypatch,
) -> None:
    seen: list[list[str]] = []

    def _rc_fail(cmd, **_k):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=1, stdout="", stderr="object not found")

    monkeypatch.setattr(job.subprocess, "run", _rc_fail)
    miss = try_r2_get_json("research/mass_eval/panels_cache/x/meta.json")
    assert miss is None
    assert seen and "--remote" in seen[0]
    assert miss != "COMPLETE"

    def _garbage(_cmd, **_k):
        return SimpleNamespace(returncode=0, stdout="<<<not-json>>>", stderr="")

    monkeypatch.setattr(job.subprocess, "run", _garbage)
    garbage = try_r2_get_json("research/mass_eval/panels_cache/x/meta.json")
    assert garbage is None
    assert garbage != "COMPLETE"
