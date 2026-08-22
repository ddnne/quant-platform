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
from research.complete21 import COMPLETE_21_DATASET_SET
from research.unique_logic.constants import PROPOSE_ALLOWED_GATES

# Copied from factory_propose._is_window_tweak_only (do not import factory).
_TWEAK_WORDS = ("window", "hold_days only", "mom only", "frac only")

PROPOSE_ALLOWED_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_daily",
        "fins_summary",
        "markets_calendar",
        "markets_margin_interest",
        "markets_short_ratio",
        "jsda_tokyo_repo_rates",
    }
)
if not PROPOSE_ALLOWED_DATASETS <= COMPLETE_21_DATASET_SET:
    raise RuntimeError("propose datasets must be a subset of COMPLETE 21")

_PROMPT_DIRECTION_ECHO: tuple[str, ...] = (
    "liquidity × fundamentals",
    "liquidity x fundamentals",
    "margin × price",
    "margin x price",
    "disclosure × funding",
    "disclosure x funding",
)

PROPOSE_CONTRADICTORY_GATE_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({"easy_funding", "tight_funding"}),
    frozenset({"crowded_margin", "uncrowded_margin"}),
    frozenset({"eq_ar_high", "eq_ar_low"}),
    frozenset({"eq_ar_rising", "eq_ar_falling"}),
    frozenset({"cheap_iv", "rich_iv"}),
    frozenset({"ta_up", "ta_down"}),
    frozenset({"overnight_easing", "overnight_tightening"}),
    frozenset({"margin_up", "margin_down"}),
    frozenset({"eps_up", "eps_down"}),
)

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
        "gates": ["liq_high", "eq_ar_high"],
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
        "datasets": [
            "equities_bars_daily",
            "markets_margin_interest",
            "markets_calendar",
        ],
        "gates": ["crowded_margin"],
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
        "gates": ["afterclose", "overnight_easing"],
        "why_different_from": ["ungated PEAD", "overnight-level CS sticky"],
    },
)


def review_proposal_row(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Local review of an LLM row. Never injects. Never GO."""
    reasons: list[str] = []
    if "logic_id" in proposal:
        reasons.append("logic_id_forbidden")
    if reject_window_tweak(proposal):
        reasons.append("window_tweak_only_forbidden")
    datasets = [
        str(x)
        for x in (proposal.get("datasets") or proposal.get("datasets_used") or [])
        if str(x).strip()
    ]
    kept_ds = [d for d in datasets if d in PROPOSE_ALLOWED_DATASETS]
    if not kept_ds:
        reasons.append("datasets_not_complete21_sidecars")
    invented_ds = [d for d in datasets if d not in PROPOSE_ALLOWED_DATASETS]
    if invented_ds:
        reasons.append("invented_datasets")
    gates = [str(x) for x in (proposal.get("gates") or []) if str(x).strip()]
    kept_g = [g for g in gates if g in PROPOSE_ALLOWED_GATES]
    if not kept_g:
        reasons.append("gates_empty_or_not_economic")
    invented_g = [g for g in gates if g not in PROPOSE_ALLOWED_GATES]
    if invented_g:
        reasons.append("invented_or_calendar_gates")
    thesis = str(proposal.get("thesis") or "")
    if kept_g and not thesis.startswith("STUB"):
        from research.unique_logic.catalog import yaml_combo_rows

        catalog_sets = {
            frozenset(
                str(x)
                for x in ((row.get("params") or {}).get("gates") or [])
                if str(x).strip()
            )
            for row in yaml_combo_rows()
        }
        if frozenset(kept_g) in catalog_sets:
            reasons.append("gate_set_already_catalog")
        kept_set = frozenset(kept_g)
        if any(pair <= kept_set for pair in PROPOSE_CONTRADICTORY_GATE_PAIRS):
            reasons.append("contradictory_gates")
        if len(kept_g) < 2:
            reasons.append("gates_not_a_cross")
        blob = thesis.lower().replace("×", "x")
        if any(echo.replace("×", "x") in blob for echo in _PROMPT_DIRECTION_ECHO):
            reasons.append("prompt_direction_echo")
    ok = not reasons
    return {
        "ok": ok,
        "reasons": reasons,
        "datasets": kept_ds,
        "gates": kept_g,
        "auto_inject": False,
        "go": False,
        "not_injected": True,
        "not_a_pass": True,
    }


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
                "gates": list(tpl["gates"]),
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


def _attach_reviews(
    out: dict[str, Any],
    *,
    write_sidecar: bool = False,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Stamp review_proposal_row onto a Worker payload. Never injects."""
    rows = [p for p in (out.get("proposals") or []) if isinstance(p, Mapping)]
    reviews: list[dict[str, Any]] = []
    n_ok = 0
    for p in rows:
        rev = review_proposal_row(p)
        reviews.append(rev)
        stub = str(p.get("status") or "").startswith("stub") or str(
            p.get("thesis") or ""
        ).startswith("STUB")
        if rev["ok"] and not stub:
            n_ok += 1
    out["reviews"] = reviews
    out["n_adoptable"] = n_ok
    out["auto_inject"] = False
    out["catalog_written"] = False
    out["ids_injected"] = False
    out["go"] = False
    out["not_a_pass"] = True
    if write_sidecar and job_id:
        from research.cf_mass_eval_stage import RESEARCH_ARTIFACT_BUCKET
        from research.r2_io import default_r2_put

        key = f"research/eval/job={job_id}/review.json"
        default_r2_put(
            RESEARCH_ARTIFACT_BUCKET,
            key,
            json.dumps(
                {
                    "job_id": job_id,
                    "n_adoptable": n_ok,
                    "adopted": [],
                    "reviews": reviews,
                    "auto_inject": False,
                    "go": False,
                    "catalog_written": False,
                    "not_a_pass": True,
                },
                default=str,
            ).encode("utf-8"),
        )
        out["review_r2_key"] = key
    return out


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
            return _attach_reviews(dict(raw_resp))
        text = raw_resp if isinstance(raw_resp, str) else raw_resp.decode("utf-8")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise CfMassEvalError("propose-thesis response not an object")
        return _attach_reviews(parsed)

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
    return _attach_reviews(
        out,
        write_sidecar=bool(write_artifacts),
        job_id=str(body.get("job_id") or "") or None,
    )


__all__ = [
    "PROPOSE_ALLOWED_DATASETS",
    "STUB_PROPOSAL_TEMPLATES",
    "invoke_cf_propose_thesis",
    "reject_window_tweak",
    "review_proposal_row",
    "stub_propose_thesis_result",
]
