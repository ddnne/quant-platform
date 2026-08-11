"""Phase 7 agent runtime capability authority.

Every role runs **deny-by-default**: no network, no secrets, no raw database,
no arbitrary filesystem, and no shell. The runtime injects *only* the positive
capabilities a role is granted by :data:`agents.roles.ROLE_MATRIX`.

The single positive capability that can reach the trusted paper runtime is
:data:`Capability.REQUEST_PAPER_EXECUTION`, held by the trader role. Even that
does not hand back a callable or handle — the trader only mints an
:class:`~agents.types.AuthorizedPaperExecutionRequest`, which the orchestrator
forwards to :class:`execution.paper_service.PaperExecutionService`. No role
ever receives ``run_paper``, a SQLite path, a PIT handle, or a transport.

This module is the declarative authority; the static import boundary in
``tests/test_paper_boundaries.py`` is its enforcement complement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .roles import AgentRole, Capability, ROLE_MATRIX


#: Non-circumventable denied baseline. Every role starts here; no positive
#: tool injection may touch any of these surfaces. Values are deliberately
#: ``False`` (i.e. *off*) so a sandboxed policy is one whose every boundary
#: is falsy.
NEGATIVE_BOUNDARIES: dict[str, bool] = {
    "network": False,
    "secrets": False,
    "raw_db": False,
    "arbitrary_fs": False,
    "shell": False,
}


@dataclass(frozen=True)
class AgentRuntimePolicy:
    """The resolved runtime policy for one role.

    ``boundaries`` is the denied baseline (identical for every role).
    ``positive_tools`` is the closed set of capabilities the runtime injects
    for this role and nothing more.
    """

    role: str
    boundaries: Mapping[str, bool]
    positive_tools: frozenset[str]

    @property
    def is_sandboxed(self) -> bool:
        """True when no negative boundary has been relaxed."""
        return all(not value for value in self.boundaries.values())


def positive_tools_for_role(role: AgentRole) -> frozenset[str]:
    """The closed set of positive capability names injected for ``role``."""
    contract = ROLE_MATRIX[role]
    return frozenset(capability.value for capability in contract.capabilities)


def runtime_policy_for_role(role: AgentRole) -> AgentRuntimePolicy:
    """Resolve the deny-by-default policy plus injected tools for ``role``."""
    return AgentRuntimePolicy(
        role=role.value,
        boundaries=NEGATIVE_BOUNDARIES,
        positive_tools=positive_tools_for_role(role),
    )


def all_runtime_policies() -> dict[str, AgentRuntimePolicy]:
    """Every role's runtime policy, keyed by role name."""
    return {role.value: runtime_policy_for_role(role) for role in AgentRole}


def assert_no_capability_leak(role: AgentRole) -> None:
    """Fail closed if a role's injected tools touch a denied surface."""
    policy = runtime_policy_for_role(role)
    if not policy.is_sandboxed:
        raise RuntimeError(
            f"role {role.value!r} relaxed a negative boundary"
        )
    leaked = sorted(set(policy.positive_tools).intersection(NEGATIVE_BOUNDARIES))
    if leaked:
        raise RuntimeError(
            f"role {role.value!r} injects a denied tool: {leaked}"
        )


__all__ = [
    "NEGATIVE_BOUNDARIES",
    "AgentRuntimePolicy",
    "positive_tools_for_role",
    "runtime_policy_for_role",
    "all_runtime_policies",
    "assert_no_capability_leak",
]
