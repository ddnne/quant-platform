"""CLI wiring for scripts/ops/cf_premium_backfill.py --index-text.

Pins omitted ``--index-text`` → ``planner.plan(index_text=None)`` (fail-closed
empty OTC required set, not 8784 calendar replay). Supplied PATH is read
locally and forwarded. Does not hit live CF, fetch JSDA HTML, un-skip JSDA,
or invent COMPLETE.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ops.backfill_planner import BackfillPlan
from ops.range_batch_scheduler import SchedulerResult

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "ops" / "cf_premium_backfill.py"
_FIXTURE = _REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"
V2_REQUIRED = 8784


def _load_mod():
    name = "cf_premium_backfill_cli"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli_module():
    return _load_mod()


def _empty_plan() -> BackfillPlan:
    return BackfillPlan(
        plan_version="test",
        coverage_policy_version="collection-coverage/v2",
        contract_digest="sha256:test",
        cutoff="2024-01-01",
        created_at="2024-01-01T00:00:00+00:00",
        jobs=[],
    )


def _stub_planner(cli_module, monkeypatch) -> dict:
    captured: dict = {"plan_calls": []}

    class FakePlanner:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def plan(self, **kwargs):
            captured["plan"] = kwargs
            captured["plan_calls"].append(kwargs)
            return _empty_plan()

    class FakeScheduler:
        def __init__(self, plan, **kwargs):
            self.plan = plan
            captured["scheduler_init"] = kwargs

        def queue(self, **kwargs):
            return []

        def run(self, **kwargs):
            return SchedulerResult(
                mode="dry-run",
                config={},
                plan_contract_digest=self.plan.contract_digest,
                plan_cutoff=self.plan.cutoff,
            )

    monkeypatch.setattr(cli_module, "BackfillPlanner", FakePlanner)
    monkeypatch.setattr(cli_module, "RangeBatchScheduler", FakeScheduler)
    return captured


def _cli_paths(tmp_path: Path) -> list[str]:
    return [
        "--plan-out",
        str(tmp_path / "plan.json"),
        "--queue-out",
        str(tmp_path / "queue.json"),
        "--db",
        str(tmp_path / "missing.sqlite"),
    ]


def test_read_index_text_omitted_blank_is_none(cli_module) -> None:
    assert cli_module._read_index_text(None) is None
    assert cli_module._read_index_text("") is None
    assert cli_module._read_index_text("   ") is None


def test_main_omitted_index_text_calls_plan_with_none(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    captured = _stub_planner(cli_module, monkeypatch)
    rc = cli_module.main(_cli_paths(tmp_path))
    assert rc == 0
    assert captured["plan_calls"]
    assert "index_text" in captured["plan"]
    assert captured["plan"]["index_text"] is None
    assert captured["plan"]["index_text"] != V2_REQUIRED


def test_main_supplied_index_text_path_is_forwarded(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    captured = _stub_planner(cli_module, monkeypatch)
    html = _FIXTURE.read_text(encoding="utf-8")
    assert "https://" not in html
    rc = cli_module.main(_cli_paths(tmp_path) + ["--index-text", str(_FIXTURE)])
    assert rc == 0
    assert captured["plan_calls"]
    assert "index_text" in captured["plan"]
    assert captured["plan"]["index_text"] == html
    assert captured["plan"]["index_text"] is not None
    assert captured["plan"]["index_text"].strip() != ""


def test_main_missing_index_file_does_not_call_plan(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    captured = _stub_planner(cli_module, monkeypatch)
    rc = cli_module.main(
        _cli_paths(tmp_path) + ["--index-text", str(tmp_path / "missing.html")]
    )
    assert rc == 1
    assert captured["plan_calls"] == []
