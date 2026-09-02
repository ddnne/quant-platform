"""Closed Controlled Pilot fill contract: morning signal, same-day afternoon fill.

The personal retrospective DRAFT contract and the engine default ``next_close``
cannot authorize Controlled execution.  This object is the user's execution
contract and is digest-bound through ExperimentPlan, PlanExecutionBinding,
exact-four aggregate binding, READY, Trader batch authorization, the
Container job, and Paper/Risk/Selection/Knowledge artifacts.
"""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_IDENTITY,
    ControlledPilotPolicyError,
    require_controlled_pilot_identity,
)


CONTROLLED_FILL_CONTRACT_ID = "controlled-pilot-am-signal-pm-close"
CONTROLLED_FILL_CONTRACT_VERSION = "1.0.0"
CONTROLLED_FILL_CONTRACT_FORMAT = "controlled-pilot-fill-contract/v1"
CONTROLLED_FILL_EXECUTION_MODE = "am_signal_pm_close"
CONTROLLED_FILL_SIGNAL_SESSION = "morning_close"
CONTROLLED_FILL_FILL_SESSION = "afternoon_close"

_CONTRACT_BODY_FIELDS = (
    "format",
    "id",
    "version",
    "identity",
    "execution_mode",
    "signal_session",
    "signal_price_field",
    "signal_price_dataset",
    "fill_session",
    "fill_valuation_field",
    "fill_valuation_session",
    "information_cutoff",
    "lifecycle",
    "retrospective_only",
    "draft",
    "live_trading_evidence",
    "ready_snapshot_declared",
    "go",
    "automatic_promotion",
    "fallback",
    "forward_fill",
)


class ControlledFillContractError(ValueError):
    """Raised when the Controlled fill contract is missing or not canonical."""


def _canonical_digest(body: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(body),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def controlled_fill_contract_body() -> dict[str, Any]:
    return {
        "format": CONTROLLED_FILL_CONTRACT_FORMAT,
        "id": CONTROLLED_FILL_CONTRACT_ID,
        "version": CONTROLLED_FILL_CONTRACT_VERSION,
        "identity": CONTROLLED_PILOT_IDENTITY,
        "execution_mode": CONTROLLED_FILL_EXECUTION_MODE,
        "signal_session": CONTROLLED_FILL_SIGNAL_SESSION,
        "signal_price_field": "MAdjC",
        "signal_price_dataset": "equities_bars_daily_am",
        "fill_session": CONTROLLED_FILL_FILL_SESSION,
        "fill_valuation_field": "AAdjC",
        "fill_valuation_session": "same_trading_date",
        "information_cutoff": "11:30:00+09:00",
        "lifecycle": "Paper",
        "retrospective_only": False,
        "draft": False,
        "live_trading_evidence": False,
        "ready_snapshot_declared": True,
        "go": False,
        "automatic_promotion": False,
        "fallback": False,
        "forward_fill": False,
    }


CONTROLLED_FILL_CONTRACT_DIGEST = _canonical_digest(controlled_fill_contract_body())


def controlled_fill_contract() -> dict[str, Any]:
    body = controlled_fill_contract_body()
    return {**body, "contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST}


CONTROLLED_FILL_CONTRACT: Mapping[str, Any] = MappingProxyType(
    controlled_fill_contract()
)


def require_controlled_fill_contract(value: object) -> dict[str, Any]:
    """Accept only the closed Controlled fill contract, including its digest."""

    if type(value) is not dict:
        raise ControlledFillContractError(
            "controlled fill contract must be an exact object"
        )
    extra = sorted(set(value) - set(_CONTRACT_BODY_FIELDS) - {"contract_digest"})
    if extra:
        raise ControlledFillContractError(
            f"controlled fill contract has unknown field(s): {extra}"
        )
    missing = [field for field in (*_CONTRACT_BODY_FIELDS, "contract_digest") if field not in value]
    if missing:
        raise ControlledFillContractError(
            f"controlled fill contract missing {missing}"
        )
    try:
        require_controlled_pilot_identity(value.get("identity"))
    except ControlledPilotPolicyError as exc:
        raise ControlledFillContractError(str(exc)) from exc
    if (
        value.get("format") != CONTROLLED_FILL_CONTRACT_FORMAT
        or value.get("id") != CONTROLLED_FILL_CONTRACT_ID
        or value.get("version") != CONTROLLED_FILL_CONTRACT_VERSION
        or value.get("execution_mode") != CONTROLLED_FILL_EXECUTION_MODE
        or value.get("signal_session") != CONTROLLED_FILL_SIGNAL_SESSION
        or value.get("fill_session") != CONTROLLED_FILL_FILL_SESSION
        or value.get("fill_valuation_session") != "same_trading_date"
        or value.get("lifecycle") != "Paper"
        or value.get("retrospective_only") is not False
        or value.get("draft") is not False
        or value.get("execution_mode") == "next_close"
    ):
        raise ControlledFillContractError(
            "retrospective DRAFT or next_close cannot authorize Controlled execution"
        )
    body = {field: value[field] for field in _CONTRACT_BODY_FIELDS}
    expected = controlled_fill_contract_body()
    if body != expected:
        raise ControlledFillContractError("controlled fill contract body is not canonical")
    digest = value.get("contract_digest")
    if digest != CONTROLLED_FILL_CONTRACT_DIGEST or _canonical_digest(body) != digest:
        raise ControlledFillContractError("controlled fill contract digest mismatch")
    return {**body, "contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST}


def require_controlled_fill_contract_digest(value: object) -> str:
    if type(value) is not str or value != CONTROLLED_FILL_CONTRACT_DIGEST:
        raise ControlledFillContractError(
            "controlled fill contract digest is not canonical"
        )
    return CONTROLLED_FILL_CONTRACT_DIGEST


__all__ = [
    "CONTROLLED_FILL_CONTRACT",
    "CONTROLLED_FILL_CONTRACT_DIGEST",
    "CONTROLLED_FILL_CONTRACT_FORMAT",
    "CONTROLLED_FILL_CONTRACT_ID",
    "CONTROLLED_FILL_CONTRACT_VERSION",
    "CONTROLLED_FILL_EXECUTION_MODE",
    "CONTROLLED_FILL_FILL_SESSION",
    "CONTROLLED_FILL_SIGNAL_SESSION",
    "ControlledFillContractError",
    "controlled_fill_contract",
    "controlled_fill_contract_body",
    "require_controlled_fill_contract",
    "require_controlled_fill_contract_digest",
]
