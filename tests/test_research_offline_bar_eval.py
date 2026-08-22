"""research.offline.bar_eval is the W78–W86 offline import surface (not CF SoT; no GO)."""

from __future__ import annotations

import research.offline as offline
import research.offline.bar_eval as be
from research.class_hyp_eval import evaluate_multi_day_hold_on_bars as che_mdh
from research.offline import bar_eval, multiyear
from research.offline.bar_eval import evaluate_multi_day_hold_on_bars as src_mdh


def test_offline_bar_eval_reexports_on_bars() -> None:
    assert callable(be.evaluate_multi_day_hold_on_bars)
    assert be.evaluate_multi_day_hold_on_bars is src_mdh
    assert offline.evaluate_multi_day_hold_on_bars is be.evaluate_multi_day_hold_on_bars
    assert be.evaluate_multi_day_hold_on_bars is che_mdh
    for name in be.__all__:
        assert name.startswith("evaluate_") and name.endswith("_on_bars")
        assert callable(getattr(be, name))
    doc = f"{be.__doc__ or ''} {__doc__ or ''}"
    assert "offline" in doc.lower()
    assert "not CF SoT" in doc
    assert "no GO" in doc


def test_offline_package_imports_bar_eval_and_multiyear() -> None:
    assert bar_eval is be
    assert callable(multiyear.run_class_hyp_multi_year_eval)
