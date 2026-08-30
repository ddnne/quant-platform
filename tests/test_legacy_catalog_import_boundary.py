"""Normal research control-plane imports must not read the replay catalog."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_normal_research_and_scheduler_imports_do_not_load_legacy_catalog() -> None:
    repo = Path(__file__).resolve().parents[1]
    python_paths = [
        repo / "packages" / "edge",
        repo / "packages" / "data_plane",
        repo / "packages" / "research_runtime",
        repo / "packages" / "product",
        repo / "platform" / "workers" / "research-mass-eval" / "container",
    ]
    code = r'''
import importlib
import pathlib
import sys

sys.path[:0] = sys.argv[1:]

replay_name = "legacy_strategy_catalog"
original_open = pathlib.Path.open
original_read_text = pathlib.Path.read_text

def reject_open(self, *args, **kwargs):
    if replay_name in self.parts:
        raise AssertionError(f"normal import opened replay artifact: {self}")
    return original_open(self, *args, **kwargs)

def reject_read_text(self, *args, **kwargs):
    if replay_name in self.parts:
        raise AssertionError(f"normal import read replay artifact: {self}")
    return original_read_text(self, *args, **kwargs)

pathlib.Path.open = reject_open
pathlib.Path.read_text = reject_read_text
for name in (
    "research",
    "research.experiment_plans",
    "research.phase7_pilot",
    "research.scheduler",
    "agents.mass_research",
    "personal_vol_am_pm_panel_job",
    "personal_research_service",
):
    importlib.import_module(name)

blocked = sorted(
    name
    for name in sys.modules
    if name == "research.unique_logic.catalog"
    or name == "research.catalog_compiler"
    or name == "research.catalog_active"
)
if blocked:
    raise AssertionError(f"legacy catalog modules loaded: {blocked}")
'''
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, *(str(path) for path in python_paths)],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
