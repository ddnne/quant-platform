"""Mass-eval wrangler deploy is opt-in fail-closed. Not GO."""
from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.cf_mass_eval_job import CfMassEvalError
from research.cf_mass_eval_run import (
    MASS_EVAL_DEPLOY_ENV,
    deploy_cf_mass_eval_worker,
    mass_eval_deploy_allowed,
    run_cf_mass_eval_job,
)


def _explode(*_a, **_k):
    raise AssertionError("subprocess.run must not be called")


def test_mass_eval_deploy_allowed_is_exactly_one(monkeypatch) -> None:
    monkeypatch.delenv(MASS_EVAL_DEPLOY_ENV, raising=False)
    assert mass_eval_deploy_allowed() is False
    monkeypatch.setenv(MASS_EVAL_DEPLOY_ENV, "true")
    assert mass_eval_deploy_allowed() is False
    monkeypatch.setenv(MASS_EVAL_DEPLOY_ENV, "0")
    assert mass_eval_deploy_allowed() is False
    monkeypatch.setenv(MASS_EVAL_DEPLOY_ENV, "1")
    assert mass_eval_deploy_allowed() is True


def test_deploy_cf_mass_eval_worker_fail_closed_without_env(monkeypatch) -> None:
    monkeypatch.delenv(MASS_EVAL_DEPLOY_ENV, raising=False)
    monkeypatch.setattr(subprocess, "run", _explode)
    with pytest.raises(CfMassEvalError, match="QP_ALLOW_MASS_EVAL_DEPLOY") as ei:
        deploy_cf_mass_eval_worker()
    assert MASS_EVAL_DEPLOY_ENV in str(ei.value)


def test_deploy_cf_mass_eval_worker_invokes_wrangler_when_env_one(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(MASS_EVAL_DEPLOY_ENV, "1")
    wr = tmp_path / "wrangler"
    wr.write_text("#!/bin/sh\necho live-deploy-must-not-run\nexit 1\n")
    wr.chmod(0o755)
    calls: list[list[str]] = []

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Deployed "
                "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = deploy_cf_mass_eval_worker(wrangler=wr)
    assert calls, "wrangler subprocess must be invoked"
    cmd = calls[0]
    assert cmd[0] == str(wr)
    assert "deploy" in cmd
    assert any(part.startswith("--config=") for part in cmd)
    assert out["status"] == "deployed"
    assert out["wrangler_rc"] == 0


def test_run_cf_mass_eval_job_capability_refuse_skips_deploy(monkeypatch) -> None:
    monkeypatch.delenv(MASS_EVAL_DEPLOY_ENV, raising=False)
    monkeypatch.setattr(subprocess, "run", _explode)
    job = run_cf_mass_eval_job(
        job_id="cap-deny-deploy",
        logic_ids=["nky_vol_abs_level"],
        mode="synthetic",
        stage_panels=False,
    )
    assert job["ok"] is False
    assert job["error"] == "capability_missing"
    assert job["go"] is False
    assert "deploy" not in job or job.get("deploy") is None


def test_run_cf_mass_eval_job_records_deploy_failed_without_env(
    monkeypatch,
) -> None:
    monkeypatch.delenv(MASS_EVAL_DEPLOY_ENV, raising=False)
    monkeypatch.setattr(subprocess, "run", _explode)
    monkeypatch.setattr(
        "research.cf_mass_eval_job.require_capability",
        lambda name, caps=None: {
            "capability": name,
            "allowed": True,
            "reasons": [],
            "go": False,
            "not_a_pass": True,
        },
    )

    def _no_net(*_a, **_k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", _no_net)
    job = run_cf_mass_eval_job(
        job_id="deploy-denied",
        logic_ids=["nky_vol_abs_level"],
        mode="synthetic",
        stage_panels=False,
        dry_run_r2=True,
    )
    assert job["deploy"]["status"] == "deploy_failed"
    assert MASS_EVAL_DEPLOY_ENV in str(job["deploy"]["error"])
    assert job["status"] == "invoke_failed"
