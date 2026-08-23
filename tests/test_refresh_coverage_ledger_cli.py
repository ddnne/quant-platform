"""CLI wiring for scripts/refresh_coverage_ledger.py.

Pins argparse ``--index-text PATH`` and the ``index_text=`` kwarg forwarded
to ``storage.coverage_ledger.refresh_coverage_ledger``. Missing flag →
``index_text is None`` (fail-closed empty OTC required set, not 8784
calendar replay). Does not run a live ledger, fetch JSDA HTML, or apply
remotely. Does not invent COMPLETE.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "refresh_coverage_ledger.py"
_FIXTURE = _REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"
V2_REQUIRED = 8784


def _load_mod():
    name = "refresh_coverage_ledger_cli"
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


def _stub_db(tmp_path: Path) -> Path:
    db = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(db)
    conn.close()
    return db


def _stub_refresh(cli_module, monkeypatch) -> dict:
    captured: dict = {}

    def fake_refresh(conn, db_path, **kw):
        captured["kwargs"] = kw
        captured["index_text"] = kw.get("index_text", "MISSING_KEY")
        return [
            {
                "dataset": "jsda_otc_bond_reference_prices",
                "status": "PARTIAL",
                "detail_json": "{}",
            }
        ]

    def fake_summary(db_path):
        return {
            "policy_version": "collection-coverage/v2",
            "dataset_count": 1,
            "status_counts": {"PARTIAL": 1},
            "governed_ready": False,
        }

    monkeypatch.setattr(cli_module, "refresh_coverage_ledger", fake_refresh)
    monkeypatch.setattr(cli_module, "coverage_summary", fake_summary)
    return captured


def test_argparse_index_text_is_optional_path(cli_module) -> None:
    parser = cli_module._build_parser()
    omitted = parser.parse_args(["--db", "x.sqlite"])
    assert omitted.index_text is None
    supplied = parser.parse_args(
        ["--db", "x.sqlite", "--index-text", "tests/fixtures/jsda_otc_official_index_tiny.html"]
    )
    assert supplied.index_text == (
        "tests/fixtures/jsda_otc_official_index_tiny.html"
    )
    action = next(
        item for item in parser._actions if "--index-text" in item.option_strings
    )
    assert action.required is False
    assert action.default is None


def test_read_index_text_missing_path_is_none(cli_module) -> None:
    assert cli_module._read_index_text(None) is None


def test_main_passes_local_index_text_through(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    db = _stub_db(tmp_path)
    captured = _stub_refresh(cli_module, monkeypatch)
    html = _FIXTURE.read_text(encoding="utf-8")
    assert "https://" not in html
    rc = cli_module.main(
        [
            "--db",
            str(db),
            "--datasets",
            "jsda_otc_bond_reference_prices",
            "--index-text",
            str(_FIXTURE),
        ]
    )
    assert rc == 0
    assert "index_text" in captured["kwargs"]
    assert captured["index_text"] == html
    assert captured["index_text"] is not None
    assert captured["index_text"].strip() != ""


def test_main_omitted_index_text_is_none_not_calendar_replay(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    db = _stub_db(tmp_path)
    captured = _stub_refresh(cli_module, monkeypatch)
    rc = cli_module.main(
        ["--db", str(db), "--datasets", "jsda_otc_bond_reference_prices"]
    )
    assert rc == 0
    assert "index_text" in captured["kwargs"]
    assert captured["index_text"] is None
    assert captured["index_text"] != V2_REQUIRED


def test_main_missing_index_file_does_not_call_refresh(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    db = _stub_db(tmp_path)
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("refresh must not run when index HTML is missing")

    monkeypatch.setattr(cli_module, "refresh_coverage_ledger", boom)
    rc = cli_module.main(
        ["--db", str(db), "--index-text", str(tmp_path / "missing.html")]
    )
    assert rc == 1
    assert called["n"] == 0
