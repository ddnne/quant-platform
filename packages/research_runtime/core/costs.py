"""Transaction-cost models for the core engine.

A :class:`CostModel` charges a fixed basis-points rate on the **one-way
notional** of every fill (buys and sells both pay). Two named factories cover
the handoff requirement:

* :func:`standard_cost` — the baseline realistic cost (default 5 bps one-way).
* :func:`stress_cost` — a multiple of standard, for robustness / sensitivity.

Both are required to be deterministic so two runs with the same model produce
identical results. The model is recorded verbatim in the result metadata.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Fixed bps one-way transaction cost.

    ``one_way_cost(notional)`` returns the cash charged for a fill of the
    given signed notional (sign ignored — buyers and sellers pay symmetrically).
    """

    bps_one_way: float
    name: str = "standard"
    # Informational: how this model was derived (e.g. stress = 5x standard).
    stress_multiple: float | None = None

    def one_way_cost(self, notional: float) -> float:
        """Cash cost for a fill of ``notional`` (signed; charged on |notional|)."""
        return abs(notional) * self.bps_one_way / 1e4

    def describe(self) -> dict:
        """Stable, JSON-serializable description for reproducibility metadata."""
        return {
            "name": self.name,
            "bps_one_way": self.bps_one_way,
            "stress_multiple": self.stress_multiple,
        }


def standard_cost(bps: float = 5.0) -> CostModel:
    """Baseline cost model: ``bps`` basis points one-way (default 5 bps)."""
    return CostModel(bps_one_way=float(bps), name="standard")


def stress_cost(multiple: float = 5.0, base_bps: float = 5.0) -> CostModel:
    """Stress cost: ``multiple`` x the standard ``base_bps`` one-way."""
    return CostModel(
        bps_one_way=float(base_bps) * float(multiple),
        name="stress",
        stress_multiple=float(multiple),
    )
