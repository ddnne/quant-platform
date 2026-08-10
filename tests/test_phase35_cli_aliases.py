"""Phase 3.5 — CLI dataset aliases (premiums / addons / all).

The existing ``run_ingestion_once.py`` CLI now accepts three alias tokens
in ``--dataset`` to target dataset groups: ``premiums`` (Premium core
closed-loop), ``addons`` (minute/trades/TDnet), ``all`` (every catalog id).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "run_ingestion_once.py"


@pytest.fixture(scope="module")
def cli_module():
    spec = importlib.util.spec_from_file_location("run_ingestion_once", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_premiums_alias_expands_to_premium_core(cli_module):
    from ingestion.jquants.catalog import PREMIUM_CORE_DATASETS
    expanded = cli_module._parse_datasets(["premiums"])
    # All 23 premium core ids are present, in catalog order.
    assert tuple(expanded) == PREMIUM_CORE_DATASETS


def test_addons_alias_expands_to_addon_group(cli_module):
    from ingestion.jquants.catalog import list_datasets
    expanded = cli_module._parse_datasets(["addons"])
    assert set(expanded) == set(list_datasets("addon"))
    # Sanity check: the well-known addon ids are there.
    assert {"equities_bars_minute", "equities_trades", "td_list",
            "td_files", "td_bulk"}.issubset(set(expanded))


def test_all_alias_expands_to_entire_catalog(cli_module):
    from ingestion.jquants.catalog import DATASETS
    expanded = cli_module._parse_datasets(["all"])
    assert set(expanded) == set(DATASETS.keys())


def test_literal_dataset_id_passes_through(cli_module):
    assert cli_module._parse_datasets(["fins_dividend"]) == ["fins_dividend"]


def test_mixed_aliases_and_literals(cli_module):
    expanded = cli_module._parse_datasets(["premiums,fins_dividend"])
    # fins_dividend is already in premiums, so de-dup is the caller's job —
    # the parser just expands. The result must include fins_dividend and
    # every premium core id.
    from ingestion.jquants.catalog import PREMIUM_CORE_DATASETS
    assert set(PREMIUM_CORE_DATASETS).issubset(set(expanded))
    assert "fins_dividend" in expanded


def test_no_dataset_returns_empty(cli_module):
    assert cli_module._parse_datasets(None) == []
    assert cli_module._parse_datasets([]) == []
