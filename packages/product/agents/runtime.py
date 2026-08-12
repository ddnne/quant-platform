"""Phase 7 agent runtime capability authority.

Every role runs **deny-by-default**: no network, no secrets, no raw database,
no arbitrary filesystem, and no shell. The runtime injects *only* the positive
capabilities a role is granted by :data:`agents.roles.ROLE_MATRIX`.

Phase 6.2.3: :class:`AgentCapabilityRouter` is an **in-process** policy router,
not a real OS sandbox. Do not document it as non-circumventable isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .roles import AgentRole, ROLE_MATRIX

NEGATIVE_BOUNDARIES: dict[str, bool] = {
    "network": False,
    "secrets": False,
    "raw_db": False,
    "arbitrary_fs": False,
    "shell": False,
}


@dataclass(frozen=True)
class AgentRuntimePolicy:
    role: str
    boundaries: Mapping[str, bool]
    positive_tools: frozenset[str]

    @property
    def is_sandboxed(self) -> bool:
        """True when no negative boundary has been relaxed (policy only)."""
        return all(not value for value in self.boundaries.values())


def positive_tools_for_role(role: AgentRole) -> frozenset[str]:
    contract = ROLE_MATRIX[role]
    return frozenset(capability.value for capability in contract.capabilities)


def runtime_policy_for_role(role: AgentRole) -> AgentRuntimePolicy:
    return AgentRuntimePolicy(
        role=role.value,
        boundaries=NEGATIVE_BOUNDARIES,
        positive_tools=positive_tools_for_role(role),
    )


def all_runtime_policies() -> dict[str, AgentRuntimePolicy]:
    return {role.value: runtime_policy_for_role(role) for role in AgentRole}


def assert_no_capability_leak(role: AgentRole) -> None:
    policy = runtime_policy_for_role(role)
    if not policy.is_sandboxed:
        raise RuntimeError(f"role {role.value!r} relaxed a negative boundary")
    leaked = sorted(set(policy.positive_tools).intersection(NEGATIVE_BOUNDARIES))
    if leaked:
        raise RuntimeError(f"role {role.value!r} injects a denied tool: {leaked}")


@dataclass(frozen=True)
class DomainTool:
    """Domain RPC handle — READY/PIT/Feature only; never raw DB."""

    name: str
    invoke: object


class AgentCapabilityRouter:
    """In-process capability router (not OS isolation).

    Allows only explicitly injected domain tools. Does not enforce
    network/FS/CPU isolation — that requires a future container/isolate runner.
    """

    def __init__(
        self,
        policy: AgentRuntimePolicy,
        *,
        domain_tools: Mapping[str, DomainTool] | None = None,
    ) -> None:
        if not policy.is_sandboxed:
            raise RuntimeError("AgentCapabilityRouter requires sandboxed policy")
        try:
            assert_no_capability_leak(AgentRole(policy.role))
        except ValueError as exc:
            raise RuntimeError(f"unknown role in policy: {policy.role}") from exc
        self.policy = policy
        # Only exact allowlisted domain tools — no domain:* wildcard.
        allowed_domain = frozenset(
            {"ready_snapshot", "pit_read", "feature_compute"}
        )
        tools = dict(domain_tools or {})
        for name in tools:
            if name not in allowed_domain:
                raise RuntimeError(
                    f"tool {name!r} not in closed domain allowlist {sorted(allowed_domain)}"
                )
        self._tools = tools

    def call_tool(self, name: str, **kwargs: object) -> object:
        if name not in self._tools:
            raise RuntimeError(f"tool {name!r} not injected")
        fn = self._tools[name].invoke
        if not callable(fn):
            raise RuntimeError(f"tool {name!r} is not callable")
        return fn(**kwargs)

    def deny_network(self) -> None:
        if self.policy.boundaries.get("network"):
            raise RuntimeError("network boundary relaxed")

    def deny_secrets(self) -> None:
        if self.policy.boundaries.get("secrets"):
            raise RuntimeError("secrets boundary relaxed")

    def deny_shell(self) -> None:
        raise RuntimeError(
            "shell/subprocess execution is forbidden in AgentCapabilityRouter"
        )

    def deny_dynamic_code(self, source: str) -> None:
        raise RuntimeError(
            "dynamic code execution (eval/exec/compile) is forbidden; "
            f"refused payload_chars={len(source)}"
        )


# Deprecated alias — do not imply real sandbox isolation.
SandboxedAgentRunner = AgentCapabilityRouter


__all__ = [
    "NEGATIVE_BOUNDARIES",
    "AgentCapabilityRouter",
    "AgentRuntimePolicy",
    "DomainTool",
    "SandboxedAgentRunner",
    "positive_tools_for_role",
    "runtime_policy_for_role",
    "all_runtime_policies",
    "assert_no_capability_leak",
]
