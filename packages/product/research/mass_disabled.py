"""Mass remains hard-disabled. Host-local staging/factory cannot touch data."""

from __future__ import annotations

from selection.budget_ledger import MassResearchDisabledError

MASS_DISABLED_MESSAGE = (
    "Mass research remains hard-disabled and cannot request local paths or DB"
)


def refuse_mass_host_entrypoint(name: str) -> None:
    """Fail before any market path, sqlite, or staging I/O."""

    raise MassResearchDisabledError(f"{name} is disabled; {MASS_DISABLED_MESSAGE}")


__all__ = [
    "MASS_DISABLED_MESSAGE",
    "MassResearchDisabledError",
    "refuse_mass_host_entrypoint",
]
