"""Eval harness stub: AST/freezes ban mass / READY / orders."""

from __future__ import annotations

import pytest

from agents.mass_research import start_mass_research
from data_contracts.permanent_defer import PERMANENT_DEFER_DATASETS
from tests.research_eval_util import (
    HARNESS_AST_PATHS,
    assert_ast_bans_mass_ready_orders,
)
from research.complete21 import (
    COMPLETE_21_DATASET_SET,
    DEFAULT_FEATURE_DATASETS,
    require_complete_21_only,
)
from selection.budget_ledger import MassResearchDisabledError


def test_require_complete_21_only_default_feature_datasets():
    ids = require_complete_21_only(DEFAULT_FEATURE_DATASETS)
    assert ids == tuple(DEFAULT_FEATURE_DATASETS)
    assert set(ids).issubset(COMPLETE_21_DATASET_SET)
    assert set(ids).isdisjoint(PERMANENT_DEFER_DATASETS)


def test_mass_research_still_hard_reject():
    """Harness must not bypass mass fail-closed gate."""
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=None, readiness=None)


def test_eval_harness_ast_bans_mass_ready_orders():
    """T7: remaining research modules must not import/call mass, READY mint, or orders."""
    assert HARNESS_AST_PATHS
    for path in HARNESS_AST_PATHS:
        assert path.is_file(), path
        assert_ast_bans_mass_ready_orders(path)
