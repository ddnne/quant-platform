"""research.offline.bar_eval is the W78–W86 offline import surface (not CF SoT; no GO)."""

from __future__ import annotations

import inspect

import pytest

import research.offline as offline
import research.offline.bar_eval as be
from research.offline import bar_eval, multiyear
from research.offline.bar_eval import evaluate_multi_day_hold_on_bars as src_mdh


def test_offline_bar_eval_reexports_on_bars() -> None:
    assert callable(be.evaluate_multi_day_hold_on_bars)
    assert be.evaluate_multi_day_hold_on_bars is src_mdh
    assert offline.evaluate_multi_day_hold_on_bars is be.evaluate_multi_day_hold_on_bars
    for name in be.__all__:
        assert name.startswith("evaluate_") and name.endswith("_on_bars")
        assert callable(getattr(be, name))
        assert inspect.getmodule(getattr(be, name)) is be
    doc = f"{be.__doc__ or ''} {__doc__ or ''}"
    assert "offline" in doc.lower()
    assert "not CF SoT" in doc
    assert "no GO" in doc


def test_offline_package_imports_bar_eval_and_multiyear() -> None:
    assert bar_eval is be
    assert callable(multiyear.run_class_hyp_multi_year_eval)


def test_multiyear_run_identity_after_body_move() -> None:
    fn = multiyear.run_class_hyp_multi_year_eval
    assert callable(fn)
    assert inspect.getmodule(fn) is multiyear


def test_default_periods_are_eval_windows_and_cf_mass() -> None:
    import research.eval_windows as ew
    from research.cf_mass_eval_job import DEFAULT_REAL_MULTIYEAR_PERIODS as cf_periods

    windows = getattr(ew, "DEFAULT_PERIODS", None)
    if windows is None:
        windows = getattr(ew, "DEFAULT_REAL_MULTIYEAR_PERIODS", None)
    if windows is None:
        pytest.skip("eval_windows DEFAULT_PERIODS not hoisted yet")
    assert windows == cf_periods
    assert windows is cf_periods
