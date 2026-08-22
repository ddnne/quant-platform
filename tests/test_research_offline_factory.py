"""research.offline.factory is the factory import surface; old path is a shim."""

from __future__ import annotations

import research.mass_strategy_factory
import research.offline.factory as fac


def test_offline_factory_import_and_shim_identity() -> None:
    assert research.mass_strategy_factory.LOGIC_TEMPLATES is fac.LOGIC_TEMPLATES
