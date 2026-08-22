"""Eval harness stub: AST/freezes ban mass / READY / orders; smoke-code pins."""

from __future__ import annotations

import pytest

from agents.mass_research import start_mass_research
from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from tests.research_eval_util import (
    HARNESS_AST_PATHS,
    assert_ast_bans_mass_ready_orders,
)
from research.complete21 import (
    COMPLETE_21_DATASET_SET,
    Complete21Error,
    DEFAULT_FEATURE_DATASETS,
    require_complete_21_only,
)
from research.eval_harness import DEFAULT_EVAL_CODES, HARNESS_SMOKE_CODES
from selection.budget_ledger import MassResearchDisabledError


def test_harness_smoke_codes_pin():
    assert DEFAULT_EVAL_CODES == HARNESS_SMOKE_CODES == ("13010", "72030", "67580")


def test_require_complete_21_only_default_feature_datasets():
    ids = require_complete_21_only(DEFAULT_FEATURE_DATASETS)
    assert ids == tuple(DEFAULT_FEATURE_DATASETS)
    assert set(ids).issubset(COMPLETE_21_DATASET_SET)
    assert set(ids).isdisjoint(PERMANENT_DEFER_DATASETS)


def test_require_complete_21_only_rejects_permanent_defer():
    for defer_id in sorted(PERMANENT_DEFER_DATASETS):
        with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
            require_complete_21_only([defer_id])
    with pytest.raises(PermanentDeferHistoryError):
        require_complete_21_only(["equities_bars_daily", "equities_master"])


def test_require_complete_21_only_rejects_unknown():
    with pytest.raises(Complete21Error, match="not in COMPLETE 21"):
        require_complete_21_only(["equities_bars_daily", "not_a_real_dataset"])


def test_mass_research_still_hard_reject():
    """Harness must not bypass mass fail-closed gate."""
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=None, readiness=None)


def test_eval_harness_ast_bans_mass_ready_orders():
    """T7: remaining research modules must not import/call mass, READY mint, or orders."""
    for path in HARNESS_AST_PATHS:
        assert_ast_bans_mass_ready_orders(path)
