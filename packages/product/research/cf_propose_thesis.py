"""CF Worker POST /v1/propose-thesis. Does not write YAML. Does not GO.

Remote proposals SoT is the Worker route. Local
``research.offline.factory_propose.propose_profit_hypotheses`` stays
offline-only. Does not import factory / class_hyp_eval / bar_eval.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from research.cf_mass_eval_job import (
    DEFAULT_WORKER_URL,
    CfMassEvalError,
    resolve_research_run_token,
)

# Copied from factory_propose._is_window_tweak_only (do not import factory).
_TWEAK_WORDS = ("window", "hold_days only", "mom only", "frac only")

STUB_PROPOSAL_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "thesis": (
            "STUB (not catalog): liquidity × fundamentals — high-ADV names "
            "with conservative EqAR/TA change after disclosure."
        ),
        "signal_definition": (
            "AND(liq_high, EqAR-or-TA-change) on the event window; skip "
            "missing ADV/EqAR/TA (no invent)."
        ),
        "position_rule": (
            "Event-hold original surprise sign when both gates are PIT-true; "
            "otherwise flat."
        ),
        "datasets": ["equities_bars_daily", "fins_summary", "markets_calendar"],
        "why_different_from": ["ungated PEAD", "always-on CS EqAR sticky"],
    },
    {
        "thesis": (
            "STUB (not catalog): margin × price disagreement — fade names "
            "where margin is crowded while price still rises."
        ),
        "signal_definition": (
            "AND(crowded_margin, price_up) occupancy; skip missing margin "
            "PIT prints (no ffill)."
        ),
        "position_rule": "CS fade (invert mom) while both gates hold; otherwise flat.",
        "datasets": ["equities_bars_daily", "margin_interest", "markets_calendar"],
        "why_different_from": ["ungated CS mom", "margin-only crowd fade"],
    },
    {
        "thesis": (
            "STUB (not catalog): disclosure × funding — PEAD only when "
            "overnight repo eased into the print cluster."
        ),
        "signal_definition": (
            "AND(afterclose-or-cluster, overnight_easing) on disclosure; "
            "skip missing repo (no invent)."
        ),
        "position_rule": (
            "Event-hold original surprise sign when funding eased; otherwise flat."
        ),
        "datasets": [
            "equities_bars_daily",
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "markets_calendar",
        ],
        "why_different_from": ["ungated PEAD", "overnight-level CS sticky"],
    },
)


def reject_window_tweak(proposal: Mapping[str, Any]) -> bool:
    """True when proposal only mutates hold/mom/window without a new thesis."""
    thesis = str(proposal.get("thesis") or "").strip()
    signal = str(
        proposal.get("signal_definition") or proposal.get("signal") or ""
    ).strip()
    position = str(
        proposal.get("position_rule") or proposal.get("position") or ""
    ).strip()
    if not thesis or not signal or not position:
        return True
    blob = f"{thesis} {signal}".lower()
    if any(w in blob for w in _TWEAK_WORDS) and "factor" not in blob:
        if not proposal.get("datasets") and not proposal.get("datasets_used"):
            return True
    return False


def stub_propose_thesis_result(
    *,
    n: int = 3,
    why_avoid: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Expected Worker stub payload when Workers AI is unbound. Not catalog."""
    want = max(1, min(3, int(n)))
    avoid = {str(x) for x in (why_avoid or ())}
    proposals: list[dict[str, Any]] = []
    for tpl in STUB_PROPOSAL_TEMPLATES:
        if len(proposals) >= want:
            break
        proposals.append(
            {
                "thesis": tpl["thesis"],
                "signal_definition": tpl["signal_definition"],
                "position_rule": tpl["position_rule"],
                "datasets": list(tpl["datasets"]),
                "why_different_from": [
                    x for x in tpl["why_different_from"] if x not in avoid
                ],
                "not_injected": True,
                "status": "stub_not_catalog",
            }
        )
    return {
        "ok": True,
        "proposals": proposals,
        "auto_inject": False,
        "go": False,
        "not_a_pass": True,
        "catalog_written": False,
        "ids_injected": False,
    }


def invoke_cf_propose_thesis(
    *,
    n: int = 3,
    why_avoid: Sequence[str] | None = None,
    write_artifacts: bool = False,
    job_id: str | None = None,
    worker_url: str = DEFAULT_WORKER_URL,
    timeout: int = 60,
    http_post: Callable[..., Any] | None = None,
    proposal: Mapping[str, Any] | None = None,
    proposals: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """POST /v1/propose-thesis. Does not write catalog YAML or inject IDs."""
    if proposal is not None and reject_window_tweak(proposal):
        return {
            "ok": False,
            "error": "window_tweak_only_forbidden",
            "auto_inject": False,
            "go": False,
            "not_a_pass": True,
        }
    for raw in proposals or ():
        if reject_window_tweak(raw):
            return {
                "ok": False,
                "error": "window_tweak_only_forbidden",
                "auto_inject": False,
                "go": False,
                "not_a_pass": True,
            }

    url = worker_url.rstrip("/") + "/v1/propose-thesis"
    tok = resolve_research_run_token() or ""
    body: dict[str, Any] = {
        "n": max(1, min(3, int(n))),
        "why_avoid": [str(x) for x in (why_avoid or ())],
        "write_artifacts": bool(write_artifacts),
        "auto_inject": False,
        "go": False,
    }
    if job_id:
        body["job_id"] = str(job_id)
    elif write_artifacts:
        body["job_id"] = f"propose-{uuid4().hex[:10]}"
    if proposal is not None:
        body["thesis"] = proposal.get("thesis")
        body["signal_definition"] = proposal.get("signal_definition") or proposal.get(
            "signal"
        )
        body["position_rule"] = proposal.get("position_rule") or proposal.get(
            "position"
        )
        if proposal.get("datasets") or proposal.get("datasets_used"):
            body["datasets"] = list(
                proposal.get("datasets") or proposal.get("datasets_used") or []
            )
    if proposals is not None:
        body["proposals"] = [dict(p) for p in proposals]
    payload = json.dumps(body, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "quant-platform-cf-propose-thesis/1.0",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-Research-Run-Token"] = tok
        headers["X-Mass-Eval-Token"] = tok
        headers["X-Ingestion-Token"] = tok

    if http_post is not None:
        raw_resp = http_post(url=url, body=payload, headers=headers)
        if isinstance(raw_resp, Mapping):
            return dict(raw_resp)
        text = raw_resp if isinstance(raw_resp, str) else raw_resp.decode("utf-8")
        return json.loads(text)

    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:2000]
        except Exception:
            detail = str(exc)
        raise CfMassEvalError(
            f"propose-thesis HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CfMassEvalError(f"propose-thesis network error: {exc}") from exc
    try:
        out = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CfMassEvalError(f"propose-thesis non-json: {raw[:500]}") from exc
    if not isinstance(out, dict):
        raise CfMassEvalError("propose-thesis response not an object")
    return out


__all__ = [
    "STUB_PROPOSAL_TEMPLATES",
    "invoke_cf_propose_thesis",
    "reject_window_tweak",
    "stub_propose_thesis_result",
]
