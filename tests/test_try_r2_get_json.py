"""CLI r2 object get --remote for panel cache is not artifact authority."""
from __future__ import annotations

from types import SimpleNamespace

import research.cf_mass_eval_job as job
from research.cf_mass_eval_job import try_r2_get_json


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
