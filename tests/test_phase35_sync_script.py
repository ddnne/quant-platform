"""Phase 3.5 — local sync script behavior.

The sync script must:
* exit 2 cleanly when no URL/config is available (never touch the network),
* require a real worker URL — the secrets-proxy worker has no /v1/export/d1
  endpoint, so falling back to it would silently fail.

We test the offline paths only — live network smokes are marked with
``@pytest.mark.live`` and skipped by default.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SYNC = _REPO / "scripts" / "sync_d1_to_sqlite.py"


@pytest.fixture(scope="module")
def sync_module():
    spec = importlib.util.spec_from_file_location("sync_d1_to_sqlite", _SYNC)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_sync_script_exists():
    assert _SYNC.exists()


def test_sync_exits_2_when_no_url(tmp_path, sync_module, monkeypatch):
    """Offline-safe: no URL → exit 2, no network touch."""
    db = tmp_path / "x.sqlite"
    monkeypatch.delenv("INGESTION_PREMIUM_URL", raising=False)
    monkeypatch.delenv("INGESTION_PROXY_TOKEN", raising=False)

    rc = sync_module.main([
        "--db", str(db),
        "--no-proxy-config",
        "--url", "",
    ])
    assert rc == 2
    assert not db.exists()


def test_sync_default_tables_include_pit_tables(sync_module):
    """The default table set covers every PIT fact table."""
    for t in (
        "jquants_records",
        "jquants_daily_bars",
        "jquants_listed_info",
        "jquants_market_calendar",
    ):
        assert t in sync_module.DEFAULT_TABLES


@pytest.mark.live
def test_sync_live_requires_worker_url(tmp_path, sync_module):
    """Live smoke. Skipped unless ``QP_LIVE=1`` and a worker URL is set.

    Run with:
      QP_LIVE=1 INGESTION_PREMIUM_URL=https://... INGESTION_PROXY_TOKEN=... \\
        .venv/bin/python -m pytest tests/test_phase35_sync_script.py::test_sync_live_requires_worker_url
    """
    if not os.environ.get("QP_LIVE"):
        pytest.skip("set QP_LIVE=1 to run live sync smoke")
    url = os.environ.get("INGESTION_PREMIUM_URL")
    if not url:
        pytest.skip("INGESTION_PREMIUM_URL not set")
    rc = sync_module.main([
        "--db", str(tmp_path / "live.sqlite"),
        "--url", url,
        "--table", "jquants_market_calendar",
    ])
    # Live run: only assert it terminates with one of the known exit codes.
    assert rc in (0, 1, 2)
