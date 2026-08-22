"""research.offline.bar_eval is the W78–W86 offline import surface (not CF SoT; no GO)."""

from __future__ import annotations

import research.offline.bar_eval as be
from research.offline import multiyear


def test_offline_bar_eval_on_bars_surface() -> None:
    assert callable(be.evaluate_multi_day_hold_on_bars)
    for name in be.__all__:
        assert name.startswith("evaluate_") and name.endswith("_on_bars")
        assert callable(getattr(be, name))
    doc = f"{be.__doc__ or ''} {__doc__ or ''}"
    assert "offline" in doc.lower()
    assert "not CF SoT" in doc
    assert "no GO" in doc


def test_multiyear_runner_is_offline() -> None:
    assert callable(multiyear.run_class_hyp_multi_year_eval)


def test_default_periods_are_eval_windows_and_cf_mass() -> None:
    import research.eval_windows as ew
    from research.cf_mass_eval_job import DEFAULT_REAL_MULTIYEAR_PERIODS as cf_periods

    assert ew.DEFAULT_PERIODS == cf_periods
