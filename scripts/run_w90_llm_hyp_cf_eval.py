#!/usr/bin/env python3
"""W90 / w0816y — strong-model hyp gen + CF multi-logic multi-period eval.

Runs end-to-end research factory evidence pack (NOT Mass/READY/GO/live):

1. Strong-model profit-hypothesis generation (xAI / Workers AI / catalog seed)
2. Local wide eval of LLM hyps + catalog survivors (real mirrors)
3. CF research-mass-eval job (multi-logic × multi-period → R2)
4. Wide table + machine-readable logs under .glm-logs/w0816y_w90_llm_cf/

Freezes held: Mass=NO-GO · READY=false · ops GO=false · continuous paper UNARMED
· 3 default-path representatives not retuned.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()
OUT_DEFAULT = ROOT / ".glm-logs" / "w0816y_w90_llm_cf"
CF_WORKER_URL = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)


def _write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _post_json(url: str, body: dict, timeout: float = 180.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "quant-platform-w90/1.0 (+research; not a bot)",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--n-hyps", type=int, default=8)
    p.add_argument("--seed", type=int, default=870816)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument(
        "--provider",
        type=str,
        default="auto",
        help="auto|xai|openai|anthropic|glm|workers_ai|catalog",
    )
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-wide", action="store_true")
    p.add_argument("--cf-url", type=str, default=CF_WORKER_URL)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    log(f"[w90] out={out}")
    log(f"[w90] freezes: Mass=NO-GO READY=false ops_GO=false continuous=UNARMED")

    # ------------------------------------------------------------------
    # 1) Strong-model hyp generation + evaluate
    # ------------------------------------------------------------------
    from research.llm_hyp_generator import (
        detect_api_keys,
        generate_and_evaluate_hypotheses,
        generate_strong_model_hypotheses,
    )
    from research.mass_strategy_factory import (
        FROZEN_DEFAULT_PATH,
        MASS_FACTORY_VERSION,
        MASS_FACTORY_WAVE,
        MASS_RESEARCH,
        CONTINUOUS_PAPER,
        try_cf_minimal_mass_batch,
        llm_logic_entry_status,
    )

    keys = detect_api_keys()
    key_presence = {k: bool(v) for k, v in keys.items()}
    log(f"[w90] api_key_presence={key_presence}")

    log(f"[w90] generating n={args.n_hyps} hyps provider={args.provider}…")
    gen_eval = generate_and_evaluate_hypotheses(
        n=int(args.n_hyps),
        provider=None if args.provider == "auto" else args.provider,
        model=args.model,
        worker_url=args.cf_url,
        evaluate=True,
        synthetic=bool(args.synthetic),
    )
    _write(out / "llm_hyp_generation.json", {
        k: gen_eval[k]
        for k in gen_eval
        if k not in {"eval_results", "eval_screens", "proposals_for_eval", "accepted_proposals"}
    })
    _write(out / "llm_hyp_eval_ranking.json", gen_eval.get("eval_ranking") or [])
    _write(out / "llm_hyp_eval_screens.json", gen_eval.get("eval_screens") or [])
    _write(out / "llm_hyp_proposals.json", gen_eval.get("proposals_for_eval") or [])

    log(
        f"[w90] hyp gen: model={gen_eval.get('model')} provider={gen_eval.get('provider')} "
        f"n_proposed={gen_eval.get('n_proposed')} n_accepted={gen_eval.get('n_accepted')} "
        f"n_evaluated={gen_eval.get('n_evaluated')} n_survivors={gen_eval.get('n_survivors')}"
    )
    for th in (gen_eval.get("representative_theses") or [])[:6]:
        log(f"  · {th.get('logic_id')}: {str(th.get('thesis') or '')[:100]}")

    # Also keep pure generation (no eval) artifact
    gen_only = generate_strong_model_hypotheses(
        n=int(args.n_hyps),
        provider=None if args.provider == "auto" else args.provider,
        model=args.model,
        worker_url=args.cf_url,
    )
    _write(out / "llm_hyp_raw_generation.json", {
        k: gen_only[k]
        for k in gen_only
        if k != "accepted" or True
    })

    # ------------------------------------------------------------------
    # 2) Wide local eval: catalog survivors + LLM hyps
    # ------------------------------------------------------------------
    wide = None
    if not args.skip_wide:
        log("[w90] wide local eval (catalog after_dedup + LLM hyps)…")
        from research.cf_mass_eval_job import run_local_wide_eval_pack

        # Merge LLM proposals under distinct logic_ids so they appear beside
        # catalog survivors (map keeps catalog eval shape but rename for table).
        llm_for_wide = []
        for i, raw in enumerate(
            gen_eval.get("accepted_proposals")
            or gen_eval.get("proposals_for_eval")
            or []
        ):
            pp = dict(raw)
            orig = str(
                pp.get("mapped_from_logic_id")
                or pp.get("logic_id")
                or f"llm_{i}"
            )
            # Unique display id for wide table while keeping executable family/params
            if not str(pp.get("logic_id") or "").startswith("llm_"):
                pp["mapped_catalog_logic_id"] = pp.get("logic_id")
                pp["logic_id"] = f"llm__{orig}" if not orig.startswith("llm") else orig
            pp["source"] = pp.get("source") or "llm_hyp"
            llm_for_wide.append(pp)

        wide = run_local_wide_eval_pack(
            llm_accepted=llm_for_wide,
            seed=int(args.seed),
            synthetic=bool(args.synthetic),
            progress=not args.quiet,
        )
        _write(out / "wide_eval.json", {
            k: wide[k]
            for k in wide
            if k not in {"screens"}
        })
        _write(out / "wide_eval_ranking.json", wide.get("ranking") or [])
        _write(out / "wide_eval_table.json", wide.get("results_compact") or [])
        n_surv = sum(
            1
            for r in (wide.get("results_compact") or [])
            if r.get("survived")
        )
        log(
            f"[w90] wide eval: n_strategies={wide.get('n_strategies')} "
            f"n_llm_merged={wide.get('n_llm_merged')} survivors≈{n_surv}"
        )

    # ------------------------------------------------------------------
    # 3) CF multi-logic multi-period eval (research-mass-eval worker)
    # ------------------------------------------------------------------
    cf_pack: dict = {"status": "skipped"}
    if not args.skip_cf:
        log(f"[w90] CF mass-eval via {args.cf_url}…")
        # Health
        try:
            hreq = urllib.request.Request(
                f"{args.cf_url.rstrip('/')}/health",
                headers={
                    "User-Agent": "quant-platform-w90/1.0 (+research; not a bot)",
                    "Accept": "application/json",
                },
                method="GET",
            )
            with urllib.request.urlopen(hreq, timeout=30) as resp:
                health = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        _write(out / "cf_health.json", health)
        log(f"[w90] CF health ok={health.get('ok')} version={health.get('version')}")

        # Build logics for CF: survivors ranking + LLM mapped catalog logics
        # Prefer bar-native + nets_only packaging from local eval period rows
        job_id = f"w90-full-{time.strftime('%Y%m%dT%H%M%S')}Z"
        logics_for_cf: list[dict] = []

        # From LLM eval results (period_rows if present)
        for r in gen_eval.get("eval_results") or []:
            if not isinstance(r, dict):
                continue
            periods = []
            for pr in r.get("period_rows") or []:
                if not isinstance(pr, dict):
                    continue
                occ = pr.get("occurrence") or {}
                periods.append(
                    {
                        "period_id": pr.get("period_id"),
                        "year": pr.get("year"),
                        "net_one_way_mean_active": pr.get(
                            "net_one_way_mean_active"
                        ),
                        "gross_signed_mean_active": pr.get(
                            "gross_signed_mean_active"
                        ),
                        "amortized_one_way_cost": pr.get(
                            "amortized_one_way_cost"
                        ),
                        "activation_rate": (
                            occ.get("activation_rate")
                            if isinstance(occ, dict)
                            else pr.get("activation_rate")
                        ),
                        "status": pr.get("status") or "ok",
                    }
                )
            nets_arr = []
            gross_arr = []
            for p in periods:
                n = p.get("net_one_way_mean_active")
                g = p.get("gross_signed_mean_active")
                if n is None:
                    continue
                try:
                    nets_arr.append(float(n))
                    gross_arr.append(
                        float(g) if g is not None else float(n)
                    )
                except (TypeError, ValueError):
                    continue
            logics_for_cf.append(
                {
                    "logic_id": r.get("logic_id"),
                    "family_id": r.get("family_id") or "multi_day_hold",
                    "thesis": r.get("thesis"),
                    "params": r.get("params") or {},
                    "source": "llm_hyp",
                    # Worker nets_only expects number[] (not objects)
                    "period_nets": nets_arr,
                    "period_grosses": gross_arr,
                    "periods": periods,
                }
            )

        # Catalog survivors from wide or prior W89 ranking
        ranking_src = []
        if wide and wide.get("ranking"):
            ranking_src = list(wide.get("ranking") or [])
        else:
            w89 = ROOT / ".glm-logs" / "w0816x_w89_rate_mf" / "ranking.json"
            if w89.is_file():
                ranking_src = json.loads(w89.read_text(encoding="utf-8"))

        seen_logic = {str(L.get("logic_id")) for L in logics_for_cf}
        for row in ranking_src[:20]:
            if not isinstance(row, dict):
                continue
            lid = str(row.get("logic_id") or "")
            if not lid or lid in seen_logic:
                continue
            # Prefer synthetic CF eval for bar-native catalog ids
            logics_for_cf.append(
                {
                    "logic_id": lid,
                    "family_id": row.get("family_id") or "multi_day_hold",
                    "thesis": row.get("thesis") or f"catalog survivor {lid}",
                    "params": row.get("params") or {},
                    "source": "catalog_survivor",
                    "strategy_id": row.get("strategy_id"),
                }
            )
            seen_logic.add(lid)

        # Ensure at least a few bar-native logics for synthetic mode
        for lid, fam in [
            ("mdh_sticky_momentum", "multi_day_hold"),
            ("xs_rank_ls_sticky", "cross_section_relative"),
            ("mdh_mean_reversion", "multi_day_hold"),
            ("cross_section_hold_10", "cross_section_relative"),
            ("cross_section_hold_10_mom3", "cross_section_relative"),
        ]:
            if lid not in seen_logic:
                logics_for_cf.append(
                    {
                        "logic_id": lid,
                        "family_id": fam,
                        "thesis": f"frozen/catalog {lid}",
                        "params": {},
                        "source": "catalog_seed",
                    }
                )
                seen_logic.add(lid)

        # Cap for CF lite
        logics_for_cf = logics_for_cf[:40]

        # Decide mode: if many have period_nets use nets_only, else synthetic
        n_with_nets = sum(
            1
            for L in logics_for_cf
            if L.get("period_nets") or L.get("periods")
        )
        mode = "nets_only" if n_with_nets >= max(2, len(logics_for_cf) // 3) else "synthetic"

        # For nets_only, worker expects period nets in logic; for synthetic runs
        # bar-native TS eval. Split if mixed: run synthetic for all bar-capable.
        if mode == "nets_only":
            body_logics = []
            for L in logics_for_cf:
                bl = {
                    "logic_id": L.get("logic_id"),
                    "family_id": L.get("family_id"),
                    "thesis": L.get("thesis"),
                    "params": L.get("params") or {},
                    "strategy_id": L.get("strategy_id"),
                }
                nets = L.get("period_nets")
                if isinstance(nets, list) and nets and isinstance(nets[0], (int, float)):
                    bl["period_nets"] = nets
                    if L.get("period_grosses"):
                        bl["period_grosses"] = L["period_grosses"]
                elif L.get("periods"):
                    narr, garr = [], []
                    for p in L["periods"]:
                        n = p.get("net_one_way_mean_active")
                        if n is None:
                            continue
                        try:
                            narr.append(float(n))
                            g = p.get("gross_signed_mean_active")
                            garr.append(float(g) if g is not None else float(n))
                        except (TypeError, ValueError):
                            continue
                    if narr:
                        bl["period_nets"] = narr
                        bl["period_grosses"] = garr
                body_logics.append(bl)
            # Drop logics without nets in nets_only mode
            body_logics = [b for b in body_logics if b.get("period_nets")]
            if len(body_logics) < 2:
                mode = "synthetic"
                body_logics = [
                    {
                        "logic_id": L.get("logic_id"),
                        "family_id": L.get("family_id"),
                        "thesis": L.get("thesis"),
                        "params": L.get("params") or {},
                        "strategy_id": L.get("strategy_id"),
                    }
                    for L in logics_for_cf
                ]
        else:
            body_logics = [
                {
                    "logic_id": L.get("logic_id"),
                    "family_id": L.get("family_id"),
                    "thesis": L.get("thesis"),
                    "params": L.get("params") or {},
                    "strategy_id": L.get("strategy_id"),
                }
                for L in logics_for_cf
            ]

        periods = [
            {"period_id": "y2020_q4", "year": 2020},
            {"period_id": "y2021_q4", "year": 2021},
            {"period_id": "y2022_q4", "year": 2022},
            {"period_id": "y2023_q4", "year": 2023},
            {"period_id": "y2024_q4", "year": 2024},
            {"period_id": "y2025_q4", "year": 2025},
        ]

        req_body = {
            "job_id": job_id,
            "seed": int(args.seed),
            "mode": mode,  # may have fallen back synthetic ↔ nets_only above
            "logics": body_logics,
            "periods": periods,
            "wave": "W90 / w0816y",
            "notes": {
                "n_llm_hyps": gen_eval.get("n_accepted"),
                "model": gen_eval.get("model"),
                "provider": gen_eval.get("provider"),
            },
        }
        # Re-stamp mode after possible fallback inside nets_only branch
        req_body["mode"] = mode
        _write(out / "cf_request.json", req_body)

        try:
            resp = _post_json(
                f"{args.cf_url.rstrip('/')}/v1/mass-eval",
                req_body,
                timeout=180.0,
            )
            cf_pack = {
                "status": "ok" if resp.get("ok") else "worker_error",
                "job_id": job_id,
                "mode": mode,
                "worker_url": args.cf_url,
                "n_logics": resp.get("n_logics"),
                "n_periods": resp.get("n_periods"),
                "n_eval_ok": resp.get("n_eval_ok"),
                "n_eval_fail": resp.get("n_eval_fail"),
                "n_survivors": resp.get("n_survivors"),
                "wall_time_ms": resp.get("wall_time_ms"),
                "r2_keys": resp.get("r2_keys") or resp.get("paths"),
                "ranking": resp.get("ranking"),
                "freezes": resp.get("freezes"),
                "worker_response_compact": {
                    k: resp.get(k)
                    for k in (
                        "ok",
                        "version",
                        "wave",
                        "job_id",
                        "n_logics",
                        "n_periods",
                        "n_eval_ok",
                        "n_eval_fail",
                        "n_survivors",
                        "wall_time_ms",
                        "note",
                    )
                },
            }
            _write(out / "cf_mass_eval_response.json", resp)
            log(
                f"[w90] CF job_id={job_id} mode={mode} "
                f"n_logics={resp.get('n_logics')} n_ok={resp.get('n_eval_ok')} "
                f"survivors={resp.get('n_survivors')} wall_ms={resp.get('wall_time_ms')}"
            )
            r2p = resp.get("r2_keys") or {}
            log(f"[w90] R2 prefix research/mass_eval/job={job_id}/ keys={list(r2p)[:8]}")
        except Exception as exc:
            cf_pack = {
                "status": "invoke_failed",
                "job_id": job_id,
                "mode": mode,
                "worker_url": args.cf_url,
                "error": f"{type(exc).__name__}: {exc}"[:600],
                "note": (
                    "deployment/config not yet complete or worker unreachable; "
                    "local wide eval still recorded"
                ),
            }
            log(f"[w90] CF invoke failed: {cf_pack['error']}")

        _write(out / "cf_job_run.json", cf_pack)

        # Also record factory CF status helper
        _write(out / "cf_status_helper.json", try_cf_minimal_mass_batch())
        _write(out / "llm_entry_status.json", llm_logic_entry_status())

    # ------------------------------------------------------------------
    # 4) Summary pack
    # ------------------------------------------------------------------
    wall = round(time.perf_counter() - t0, 3)
    summary = {
        "wave": MASS_FACTORY_WAVE,
        "version": MASS_FACTORY_VERSION,
        "status": "complete",
        "wall_time_sec": wall,
        "hyp_generation": {
            "model": gen_eval.get("model"),
            "provider": gen_eval.get("provider"),
            "n_proposed": gen_eval.get("n_proposed"),
            "n_accepted": gen_eval.get("n_accepted"),
            "n_evaluated": gen_eval.get("n_evaluated"),
            "n_survivors": gen_eval.get("n_survivors"),
            "representative_theses": gen_eval.get("representative_theses"),
            "api_key_presence": key_presence,
        },
        "wide_eval": {
            "n_strategies": (wide or {}).get("n_strategies"),
            "n_catalog_after_dedup": (wide or {}).get("n_catalog_after_dedup"),
            "n_llm_merged": (wide or {}).get("n_llm_merged"),
            "n_survivors": sum(
                1
                for r in ((wide or {}).get("results_compact") or [])
                if r.get("survived")
            )
            if wide
            else None,
            "top5": ((wide or {}).get("ranking") or [])[:5],
        }
        if wide
        else None,
        "cf_job": {
            "status": cf_pack.get("status"),
            "job_id": cf_pack.get("job_id"),
            "mode": cf_pack.get("mode"),
            "worker_url": cf_pack.get("worker_url"),
            "n_logics": cf_pack.get("n_logics"),
            "n_eval_ok": cf_pack.get("n_eval_ok"),
            "n_survivors": cf_pack.get("n_survivors"),
            "r2_prefix": (
                f"research/mass_eval/job={cf_pack.get('job_id')}/"
                if cf_pack.get("job_id")
                else None
            ),
            "error": cf_pack.get("error"),
        },
        "frozen_defaults": [
            r["representative_id"] for r in FROZEN_DEFAULT_PATH
        ],
        "frozen_defaults_retuned": False,
        "mass_research": MASS_RESEARCH,
        "ready_declared": False,
        "operational_go": False,
        "continuous_paper": CONTINUOUS_PAPER,
        "live_orders": False,
        "human_main_candidates_selected": False,
    }
    _write(out / "w90_summary.json", summary)

    # Markdown summary
    lines = [
        f"# W90 / w0816y run summary",
        "",
        f"- factory: `{MASS_FACTORY_VERSION}` · wave `{MASS_FACTORY_WAVE}`",
        f"- wall_time_sec: **{wall}**",
        f"- mass={MASS_RESEARCH} · continuous_paper={CONTINUOUS_PAPER} · READY=False · ops_GO=False",
        f"- frozen_defaults_retuned: **False**",
        "",
        "## Strong-model hyp generation",
        "",
        f"- model: `{gen_eval.get('model')}`",
        f"- provider: `{gen_eval.get('provider')}`",
        f"- n_proposed: **{gen_eval.get('n_proposed')}**",
        f"- n_accepted: **{gen_eval.get('n_accepted')}**",
        f"- n_evaluated: **{gen_eval.get('n_evaluated')}**",
        f"- n_survivors: **{gen_eval.get('n_survivors')}**",
        "",
        "### Representative theses",
        "",
    ]
    for th in gen_eval.get("representative_theses") or []:
        lines.append(
            f"- `{th.get('logic_id')}` ({th.get('family_id')}): "
            f"{str(th.get('thesis') or '')[:160]}"
        )
    lines += ["", "## CF multi-logic multi-period eval", ""]
    lines.append(f"- status: **{cf_pack.get('status')}**")
    lines.append(f"- job_id: `{cf_pack.get('job_id')}`")
    lines.append(f"- mode: `{cf_pack.get('mode')}`")
    lines.append(f"- n_logics: **{cf_pack.get('n_logics')}**")
    lines.append(f"- n_eval_ok: **{cf_pack.get('n_eval_ok')}**")
    lines.append(f"- n_survivors: **{cf_pack.get('n_survivors')}**")
    if cf_pack.get("job_id"):
        lines.append(
            f"- R2: `quant-structured/research/mass_eval/job={cf_pack.get('job_id')}/`"
        )
    if cf_pack.get("error"):
        lines.append(f"- error: {cf_pack.get('error')}")
    if wide:
        lines += [
            "",
            "## Wide local eval (LLM + catalog)",
            "",
            f"- n_strategies: **{wide.get('n_strategies')}**",
            f"- n_llm_merged: **{wide.get('n_llm_merged')}**",
            f"- n_survivors: **{summary['wide_eval']['n_survivors']}**",
            "",
            "### Top ranking",
            "",
        ]
        for row in (wide.get("ranking") or [])[:10]:
            lines.append(
                f"- #{row.get('rank')} `{row.get('logic_id')}` "
                f"t={row.get('t_stat')} mean_net={row.get('mean_net')} "
                f"sign={row.get('chosen_sign')}"
            )
    lines += [
        "",
        "## Freezes (held)",
        "",
        "- Mass **NO-GO** · READY **未宣言** · ops GO **未宣言** · Phase7 **OFF**",
        "- continuous paper **UNARMED** · live **OFF**",
        "- 3 defaults frozen (mom5 / mom3 / fund) · **not retuned**",
        "",
    ]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"[w90] done wall={wall}s → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
