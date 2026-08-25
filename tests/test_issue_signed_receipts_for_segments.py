"""CLI wiring for scripts/issue_signed_receipts_for_segments.py.

Pins argparse ``--index-text PATH`` and the ``index_text=`` kwarg forwarded
to ``storage.coverage_ledger.refresh_coverage_ledger``. Missing flag →
``index_text is None`` (fail-closed empty OTC required set, not 8784
calendar replay). Does not run a live ledger, fetch JSDA HTML, or invent
COMPLETE.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "issue_signed_receipts_for_segments.py"
_FIXTURE = _REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"
V2_REQUIRED = 8784
WEEKEND_IN_TINY_SPAN = "2002-08-03"


def _load_mod():
    name = "issue_signed_receipts_for_segments_cli"
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


def test_argparse_index_text_is_optional_path(cli_module) -> None:
    parser = cli_module._build_parser()
    omitted = parser.parse_args([])
    assert omitted.index_text is None
    supplied = parser.parse_args(
        ["--index-text", "tests/fixtures/jsda_otc_official_index_tiny.html"]
    )
    assert supplied.index_text == (
        "tests/fixtures/jsda_otc_official_index_tiny.html"
    )
    action = next(
        item for item in parser._actions if "--index-text" in item.option_strings
    )
    assert action.required is False
    assert action.default is None


def test_read_index_text_omitted_blank_fixture(cli_module, tmp_path: Path) -> None:
    assert cli_module._read_index_text(None) is None
    assert cli_module._read_index_text("") is None
    assert cli_module._read_index_text("   ") is None
    blank = tmp_path / "blank.html"
    blank.write_text("   \n", encoding="utf-8")
    assert cli_module._read_index_text(blank) is None
    html = cli_module._read_index_text(_FIXTURE)
    assert html is not None
    assert html.strip() != ""
    assert "https://" not in html
    assert "2002.8.2" in html
    assert WEEKEND_IN_TINY_SPAN not in html.replace(".", "-")


def test_read_index_text_missing_path_raises(cli_module, tmp_path: Path) -> None:
    missing = tmp_path / "no_such_official_index.html"
    assert not missing.exists()
    with pytest.raises(FileNotFoundError):
        cli_module._read_index_text(missing)


def test_refresh_issued_coverage_always_passes_index_text(
    cli_module, monkeypatch,
) -> None:
    captured: dict = {}

    def fake_refresh(conn, db_path, **kw):
        captured["kwargs"] = kw
        captured["index_text"] = kw.get("index_text", "MISSING_KEY")
        return [
            {
                "dataset": "jsda_otc_bond_reference_prices",
                "status": "PARTIAL",
                "detail": {},
            }
        ]

    monkeypatch.setattr(cli_module, "refresh_coverage_ledger", fake_refresh)
    cli_module._refresh_issued_coverage(
        object(), "db.sqlite", ["jsda_otc_bond_reference_prices"], index_text=None
    )
    assert "index_text" in captured["kwargs"]
    assert captured["index_text"] is None
    assert captured["index_text"] != V2_REQUIRED
    html = _FIXTURE.read_text(encoding="utf-8")
    cli_module._refresh_issued_coverage(
        object(), "db.sqlite", ["jsda_otc_bond_reference_prices"], index_text=html
    )
    assert captured["index_text"] == html
    assert captured["kwargs"]["datasets"] == ["jsda_otc_bond_reference_prices"]
    assert captured["index_text"] is not None
    assert captured["index_text"].strip() != ""


def test_main_omitted_index_text_is_none_not_calendar_replay(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    captured: dict = {}

    def fake_read(path):
        captured["path"] = path
        return None

    monkeypatch.setattr(cli_module, "_read_index_text", fake_read)
    rc = cli_module.main(["--db", str(tmp_path / "missing.sqlite")])
    assert rc == 2
    assert captured["path"] is None
    assert captured["path"] != V2_REQUIRED


def test_main_supplied_index_text_path_is_forwarded(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    captured: dict = {}

    def fake_read(path):
        captured["path"] = path
        return None

    monkeypatch.setattr(cli_module, "_read_index_text", fake_read)
    html_path = str(tmp_path / "tiny.html")
    rc = cli_module.main(
        ["--db", str(tmp_path / "missing.sqlite"), "--index-text", html_path]
    )
    assert rc == 2
    assert captured["path"] == html_path


def test_main_missing_index_file_does_not_call_refresh(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("refresh must not run when index HTML is missing")

    monkeypatch.setattr(cli_module, "refresh_coverage_ledger", boom)
    monkeypatch.setattr(cli_module, "_refresh_issued_coverage", boom)
    rc = cli_module.main(
        ["--db", str(tmp_path / "ledger.sqlite"), "--index-text", str(tmp_path / "missing.html")]
    )
    assert rc == 1
    assert called["n"] == 0


def test_main_refresh_site_passes_index_text(cli_module) -> None:
    src = inspect.getsource(cli_module.main)
    assert "_read_index_text" in src
    assert "index_text=index_text" in src
    assert "_refresh_issued_coverage" in src
    assert "urllib" not in src
    assert "requests." not in inspect.getsource(cli_module)
    assert "urlopen" not in inspect.getsource(cli_module)
    assert "open_governed_receipt_service" not in inspect.getsource(cli_module)
    assert "record_persisted_success" not in inspect.getsource(cli_module)
    assert "RECOVERED_RAW_ONLY" in inspect.getsource(cli_module)
