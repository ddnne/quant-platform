"""CF Worker POST /v1/propose-thesis. Does not write YAML. Does not GO.

Remote proposals SoT is the Worker route. Review / write-block policy
lives in ``research.cf_propose_policy``. Local
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
    refuse_missing_capability,
    resolve_research_run_token,
)
from research.cf_propose_policy import (
    CATALOG_GATE_SET_AVOID_LIMIT,
    PROPOSE_ALLOWED_DATASETS,
    PROPOSE_BLOCKED_GATE_SETS,
    PROPOSE_MAX_AND_GATES,
    PROPOSE_PARENT_LO_MIN,
    PROPOSE_WHY_AVOID_LIMIT,
    assemble_why_avoid,
    catalog_gate_set_avoid,
    catalog_prefer_and_avoid,
    catalog_prefer_pair_avoid,
    catalog_prefer_triple_avoid,
    local_catalog_write_block_reasons,
    propose_eval_pack,
    reject_window_tweak,
    review_proposal_row,
    sparse_gate_set_avoid,
    sparse_prefer_subset_avoid,
)


def _attach_reviews(
    out: dict[str, Any],
    *,
    write_sidecar: bool = False,
    job_id: str | None = None,
    artifact_put: Any | None = None,
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
        if artifact_put is None:
            raise RuntimeError("closed artifact put port is required")
        from research.cf_mass_eval_stage import RESEARCH_ARTIFACT_BUCKET

        key = f"research/eval/job={job_id}/review.json"
        artifact_put(
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
    timeout: int = 300,
    http_post: Callable[..., Any] | None = None,
    proposal: Mapping[str, Any] | None = None,
    proposals: Sequence[Mapping[str, Any]] | None = None,
    retry_on_clone: bool = True,
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

    refused = refuse_missing_capability("generation")
    if refused is not None:
        return refused

    url = worker_url.rstrip("/") + "/v1/propose-thesis"
    auth_tok = resolve_research_run_token() or ""
    avoid = assemble_why_avoid(why_avoid)
    body: dict[str, Any] = {
        "n": max(1, min(3, int(n))),
        "why_avoid": avoid,
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
    if auth_tok:
        headers["Authorization"] = f"Bearer {auth_tok}"
        headers["X-Research-Run-Token"] = auth_tok
        headers["X-Mass-Eval-Token"] = auth_tok
        headers["X-Ingestion-Token"] = auth_tok

    if http_post is not None:
        raw_resp = http_post(url=url, body=payload, headers=headers)
        if isinstance(raw_resp, Mapping):
            parsed: dict[str, Any] = dict(raw_resp)
        else:
            text = raw_resp if isinstance(raw_resp, str) else raw_resp.decode("utf-8")
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                raise CfMassEvalError("propose-thesis response not an object")
            parsed = loaded
        reviewed = _attach_reviews(
            parsed,
            write_sidecar=False,
            job_id=str(body.get("job_id") or "") or None,
        )
    else:
        raise CfMassEvalError("closed JSON client is required")
    if (
        retry_on_clone
        and reviewed.get("workers_ai_used")
        and int(reviewed.get("n_adoptable") or 0) == 0
    ):
        extra = []
        seen_extra: set[str] = set()
        # Clone/sparse: avoid those gate sets. Polarity/occupancy-label:
        # retry once without avoiding the (possibly unique) AND.
        avoid_reasons = {
            "gate_set_already_catalog",
            "sparse_gate_combo",
        }
        for prop, rev in zip(
            reviewed.get("proposals") or [],
            reviewed.get("reviews") or [],
        ):
            if not isinstance(prop, Mapping) or not isinstance(rev, Mapping):
                continue
            reasons = set(str(x) for x in (rev.get("reasons") or []))
            if not (reasons & avoid_reasons):
                continue
            gates = [str(x) for x in (prop.get("gates") or []) if str(x).strip()]
            if not gates:
                continue
            token = "+".join(sorted(gates))
            if token in seen_extra:
                continue
            seen_extra.add(token)
            extra.append(token)
        jid = str(body.get("job_id") or "")
        return invoke_cf_propose_thesis(
            n=n,
            why_avoid=extra + list(avoid),
            write_artifacts=write_artifacts,
            job_id=f"{jid}-retry" if jid else None,
            worker_url=worker_url,
            timeout=timeout,
            http_post=http_post,
            retry_on_clone=False,
        )
    return reviewed


__all__ = [
    "CATALOG_GATE_SET_AVOID_LIMIT",
    "PROPOSE_ALLOWED_DATASETS",
    "PROPOSE_BLOCKED_GATE_SETS",
    "PROPOSE_MAX_AND_GATES",
    "PROPOSE_WHY_AVOID_LIMIT",
    "assemble_why_avoid",
    "catalog_gate_set_avoid",
    "catalog_prefer_and_avoid",
    "catalog_prefer_pair_avoid",
    "catalog_prefer_triple_avoid",
    "sparse_gate_set_avoid",
    "sparse_prefer_subset_avoid",
    "invoke_cf_propose_thesis",
    "local_catalog_write_block_reasons",
    "propose_eval_pack",
    "PROPOSE_PARENT_LO_MIN",
    "reject_window_tweak",
    "review_proposal_row",
]
