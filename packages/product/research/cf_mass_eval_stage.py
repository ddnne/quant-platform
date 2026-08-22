"""COMPLETE-backed r2_panels staging. Universe is select_eval_universe — never head-N."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from data_contracts.permanent_defer import PERMANENT_DEFER_DATASETS
from research.cf_mass_eval_thicken import (
    _build_thicken_sidecars,
    attach_nky_proxy,
    attach_opt225_regime,
)
from research.eval_loaders import (
    bars_rich_to_close_panel,
    load_bars_from_sqlite_rich,
    load_bars_ndjson_rich,
    resolve_bars_path,
)
from research.eval_universe import select_eval_universe
from research.eval_windows import DEFAULT_REAL_MULTIYEAR_PERIODS
from research.complete21 import COMPLETE_21_DATASETS
from research.r2_io import default_r2_put

RESEARCH_ARTIFACT_BUCKET: str = "quant-structured"
RESEARCH_ARTIFACT_PREFIX: str = "research/mass_eval"
# liq_large default (100). Never head-N.
DEFAULT_MAX_CODES: int = 100
DEFAULT_MAX_DAYS: int = 120

# COMPLETE 22 = COMPLETE 21 + fins_earnings_date. Permanent DEFER excluded.
COMPLETE_22_DATASETS: tuple[str, ...] = tuple(
    sorted(set(COMPLETE_21_DATASETS) | {"fins_earnings_date"})
)
COMPLETE_22_DATASET_SET: frozenset[str] = frozenset(COMPLETE_22_DATASETS)
PRIMARY_BARS_DATASET: str = "equities_bars_daily"
if len(COMPLETE_22_DATASETS) != 22:
    raise RuntimeError(
        f"COMPLETE_22_DATASETS must have 22 ids, got {len(COMPLETE_22_DATASETS)}"
    )
if COMPLETE_22_DATASET_SET & PERMANENT_DEFER_DATASETS:
    raise RuntimeError(
        "COMPLETE_22_DATASETS must not intersect permanent DEFER: "
        f"{sorted(COMPLETE_22_DATASET_SET & PERMANENT_DEFER_DATASETS)}"
    )


def normalize_period_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    p = dict(raw)
    pid = str(p.get("period_id") or p.get("id") or "period")
    start = p.get("period_start") or p.get("start") or ""
    end = p.get("period_end") or p.get("end") or ""
    year = p.get("year")
    if year is None and start:
        try:
            year = int(str(start)[:4])
        except ValueError:
            year = None
    if year is None:
        for token in pid.replace("-", "_").split("_"):
            if token.startswith("y") and token[1:].isdigit() and len(token) == 5:
                year = int(token[1:])
                break
            if token.isdigit() and len(token) == 4:
                year = int(token)
                break
    out: dict[str, Any] = {"period_id": pid}
    if year is not None:
        out["year"] = int(year)
    if start:
        out["period_start"] = str(start)[:10]
    if end:
        out["period_end"] = str(end)[:10]
    return out


def build_real_period_panel(
    period: Mapping[str, Any],
    *,
    codes: Sequence[str] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    mirror_dir: str | Path | None = None,
) -> dict[str, Any]:
    p = normalize_period_row(period)
    pid = str(p["period_id"])
    pool = (
        None
        if codes is None
        else [str(c).strip() for c in codes if str(c).strip()]
    )
    selected = select_eval_universe(max_codes=int(max_codes), pool=pool)
    if mirror_dir is not None:
        bars_path = resolve_bars_path(
            pid, mirror_dir=mirror_dir, prefer_full=True
        )
    else:
        bars_path = resolve_bars_path(pid, prefer_full=True)
    if bars_path is None or not Path(bars_path).exists():
        return {
            **p,
            "status": "missing_bars",
            "bars": {},
            "dataset": PRIMARY_BARS_DATASET,
            "source": "mirror_missing",
            "n_codes": 0,
            "n_days": 0,
        }
    rich = load_bars_ndjson_rich(
        bars_path,
        codes=selected,
        max_days=int(max_days),
        period_start=p.get("period_start"),
        period_end=p.get("period_end"),
    )
    missing = [c for c in selected if c not in rich]
    if missing:
        extra = load_bars_from_sqlite_rich(
            codes=missing,
            period_start=str(p.get("period_start") or ""),
            period_end=str(p.get("period_end") or ""),
            max_days=int(max_days),
        )
        rich.update(extra)
    close = bars_rich_to_close_panel(rich)
    bars_json: dict[str, list[list[Any]]] = {
        code: [[d, float(px)] for d, px in pairs]
        for code, pairs in close.items()
        if pairs
    }
    adv_by_code: dict[str, float] = {}
    for code, pairs in (rich or {}).items():
        vals: list[float] = []
        for _d, rec in pairs:
            va = rec.get("Va") if isinstance(rec, dict) else None
            try:
                if va is not None:
                    vals.append(float(va))
                    continue
            except (TypeError, ValueError):
                pass
            try:
                vo = rec.get("Vo") if isinstance(rec, dict) else None
                px = rec.get("close") if isinstance(rec, dict) else None
                if vo is not None and px is not None:
                    vals.append(float(vo) * float(px))
            except (TypeError, ValueError):
                continue
        if vals:
            adv_by_code[str(code)] = sum(vals) / len(vals)
    nky_meta = attach_nky_proxy(bars_json, p)
    opt225_meta = attach_opt225_regime()
    thicken_meta = _build_thicken_sidecars(p, codes=selected)

    n_days = max(
        (len(v) for k, v in bars_json.items() if not str(k).startswith("__")),
        default=0,
    )
    n_eq = sum(1 for k in bars_json if not str(k).startswith("__"))
    return {
        **p,
        "status": "ok" if n_eq > 0 else "empty_bars",
        "bars": bars_json,
        "adv_by_code": adv_by_code,
        "dataset": PRIMARY_BARS_DATASET,
        "source": f"complete22_mirror:{Path(bars_path).name}",
        "n_codes": n_eq,
        "n_days": n_days,
        **nky_meta,
        **opt225_meta,
        **thicken_meta,
    }


def stage_real_panels_to_r2(
    job_id: str,
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    codes: Sequence[str] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
    r2_put: Callable[..., Mapping[str, Any]] | None = None,
    panels_prefix: str | None = None,
) -> dict[str, Any]:
    from research.cf_mass_eval_job import CF_MASS_EVAL_WAVE

    wave = CF_MASS_EVAL_WAVE
    jid = str(job_id).strip() or "unknown"
    period_list = [
        normalize_period_row(p)
        for p in (periods or DEFAULT_REAL_MULTIYEAR_PERIODS)
    ]
    prefix = panels_prefix or f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/panels"
    put_fn = r2_put or (
        lambda bucket, key, body: default_r2_put(
            bucket,
            key,
            body,
            dry_run=dry_run,
            staging_dir=staging_dir,
        )
    )
    panels: list[dict[str, Any]] = []
    puts: list[dict[str, Any]] = []
    for raw in period_list:
        panel = build_real_period_panel(
            raw,
            codes=codes,
            max_codes=max_codes,
            max_days=max_days,
        )
        key = f"{prefix}/{panel['period_id']}.json"
        body = json.dumps(panel, indent=2, default=str).encode("utf-8")
        meta = put_fn(RESEARCH_ARTIFACT_BUCKET, key, body)
        puts.append(dict(meta) if isinstance(meta, Mapping) else {"key": key})
        panels.append(
            {
                "period_id": panel.get("period_id"),
                "year": panel.get("year"),
                "period_start": panel.get("period_start"),
                "period_end": panel.get("period_end"),
                "status": panel.get("status"),
                "n_codes": panel.get("n_codes"),
                "n_days": panel.get("n_days"),
                "source": panel.get("source"),
                "dataset": panel.get("dataset"),
                "r2_key": key,
            }
        )
    n_ok = sum(1 for p in panels if p.get("status") == "ok")
    return {
        "job_id": jid,
        "panels_prefix": prefix,
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "n_periods": len(panels),
        "n_ok": n_ok,
        "n_missing": len(panels) - n_ok,
        "panels": panels,
        "puts": puts,
        "dataset": PRIMARY_BARS_DATASET,
        "wave": wave,
        "dry_run": bool(dry_run),
    }


__all__ = [
    "COMPLETE_22_DATASETS",
    "COMPLETE_22_DATASET_SET",
    "DEFAULT_MAX_CODES",
    "DEFAULT_MAX_DAYS",
    "PRIMARY_BARS_DATASET",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "build_real_period_panel",
    "normalize_period_row",
    "stage_real_panels_to_r2",
]
