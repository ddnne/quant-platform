"""W90 / w0816y — strong-model profit-hypothesis generation (research only).

Generates **multiple distinct economic profit hypotheses** (not window/hold/mom
tweaks) via the best available model provider, then always routes accepted
payloads through ``propose_profit_hypotheses`` (PIT + cost evaluator).

Provider preference order
-------------------------
1. Explicit ``model`` / ``provider`` override
2. Env API keys: OPENAI_API_KEY, XAI_API_KEY / GROK_API_KEY, ANTHROPIC_API_KEY,
   GLM_API_KEY (or ``~/.config/glm-coding/key.env``)
3. Cloudflare Workers AI via deployed ``research-mass-eval`` worker
   (``@cf/openai/gpt-oss-120b`` preferred; llama fallback)
4. Catalog-seeded deterministic diverse proposals (last resort — still multiple
   distinct theses; never human seed wait)

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune frozen default-path representatives.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WRANGLER = (
    _REPO_ROOT
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "node_modules"
    / ".bin"
    / "wrangler"
)
_WORKER_DIR = _REPO_ROOT / "platform" / "workers" / "research-mass-eval"
_WORKER_CONFIG = _WORKER_DIR / "wrangler.toml"
_WORKER_NAME = "quant-platform-research-mass-eval"

MASS_RESEARCH = "NO-GO"
PHASE7 = "OFF"
READY_DECLARED = False
OPERATIONAL_GO = False
CONTINUOUS_PAPER = "UNARMED"
LIVE_ORDERS = False

LLM_HYP_WAVE = "W90 / w0816y"
LLM_HYP_VERSION = "llm-hyp-generator/v1"

# Forbidden numeric-only knobs as sole differentiation.
_NUMERIC_ONLY = frozenset(
    {
        "hold_days",
        "post_hold_days",
        "momentum_n",
        "long_frac",
        "short_frac",
        "vol_n",
        "vol_threshold",
        "high_threshold",
        "low_threshold",
    }
)

_CATALOG_SEED_HYPS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "llm_flow_short_squeeze_pressure",
        "family_id": "flow_demand",
        "thesis": (
            "Elevated short interest combined with rising margin demand "
            "creates multi-day squeeze pressure that continues after initial pop"
        ),
        "signal_definition": (
            "enter long when short_ratio high AND margin_interest rising; "
            "enter short when short_ratio low AND margin falling"
        ),
        "position_rule": "min_hold sticky; require short_ratio leg (not soft tilt only)",
        "datasets": [
            "markets_margin_interest",
            "markets_short_ratio",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "short_confirm_mode": "hard",
            "require_short_confirm": True,
            "mode": "squeeze_pressure",
        },
    },
    {
        "logic_id": "llm_fund_earnings_revision_drift",
        "family_id": "event_post",
        "thesis": (
            "Post-disclosure earnings revision drift persists when surprise "
            "and value score agree; PIT entry only after available_at"
        ),
        "signal_definition": (
            "earnings surprise proxy × PIT value agreement; "
            "entry same_day_close_if_pre_close only"
        ),
        "position_rule": "post_hold fixed horizon after first non-look-ahead close",
        "datasets": ["fins_summary", "equities_bars_daily", "markets_calendar"],
        "params": {
            "post_hold_days": 10,
            "entry_mode": "same_day_close_if_pre_close",
            "mode": "surprise_value_agree",
        },
    },
    {
        "logic_id": "llm_rate_tightening_defensive_xs",
        "family_id": "rate_factor",
        "thesis": (
            "Tokyo repo tightening regime favors defensive relative-strength "
            "rotation: reverse CS mom book when rate_change high"
        ),
        "signal_definition": (
            "CS rank mom L-S inverted under high repo rate_change; "
            "kept under easing; flat mid"
        ),
        "position_rule": "sticky balanced L/S with rate-change book transform",
        "datasets": [
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
            "jsda_tokyo_repo_rates",
        ],
        "params": {
            "mode": "rate_change_xs_defensive",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
        },
    },
    {
        "logic_id": "llm_mf_value_flow_confirm",
        "family_id": "multi_factor",
        "thesis": (
            "Cheap names earn multi-day only when margin-flow confirms "
            "demand (value × flow multi-factor agreement)"
        ),
        "signal_definition": (
            "enter only when sign(value_score)==sign(margin_flow); flat otherwise"
        ),
        "position_rule": "sticky fixed_horizon of value×flow agree signs",
        "datasets": [
            "fins_summary",
            "markets_margin_interest",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "mode": "value_flow_agree",
            "hold_days": 10,
            "momentum_n": 10,
        },
    },
    {
        "logic_id": "llm_vol_compress_breakout",
        "family_id": "vol_risk_adjusted",
        "thesis": (
            "After realized-vol compression, breakout mom continues multi-day "
            "(compress → expand entry, not expand-only gate)"
        ),
        "signal_definition": (
            "sign(mom) only if prior_vol/recent_vol ≥ compress_ratio then "
            "recent expansion starts"
        ),
        "position_rule": "fixed_horizon sticky hold of compress-breakout signs",
        "datasets": ["equities_bars_daily", "markets_calendar"],
        "params": {
            "hold_days": 10,
            "momentum_n": 10,
            "vol_n": 20,
            "gate_mode": "vol_compress_breakout",
        },
    },
    {
        "logic_id": "llm_xs_low_vol_quality",
        "family_id": "cross_section_relative",
        "thesis": (
            "Cross-section long low-vol quality / short high-vol junk "
            "harvests risk-adjusted relative premium (not pure mom rank)"
        ),
        "signal_definition": (
            "rank by −realized_vol (quality proxy); balanced L/S sticky book"
        ),
        "position_rule": "sticky balanced L/S on vol-rank (book_mode=low_vol_quality)",
        "datasets": [
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 20,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "book_mode": "low_vol_quality_ls",
        },
    },
    {
        "logic_id": "llm_macro_curve_steepener_mom",
        "family_id": "macro_conditioned",
        "thesis": (
            "Equity momentum works better when funding curve is steepening "
            "(3M−ON rising); gate mom by curve_change regime"
        ),
        "signal_definition": (
            "momentum gated by Δ(curve_spread); long_only when steepening, "
            "short_only when flattening hard"
        ),
        "position_rule": "sticky multi-day under curve-change regime filter",
        "datasets": [
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
            "jsda_tokyo_repo_rates",
        ],
        "params": {
            "mode": "curve_change_gate",
            "momentum_n": 10,
            "hold_days": 10,
        },
    },
    {
        "logic_id": "llm_mf_rate_flow_price",
        "family_id": "multi_factor",
        "thesis": (
            "Three-leg agreement: easy funding + rising margin flow + price mom "
            "confirm multi-day demand; fade when any leg disagrees"
        ),
        "signal_definition": (
            "enter only when rate_level not high AND margin_flow AND price_mom agree"
        ),
        "position_rule": "sticky hold of triple-agree signs (rate×flow×price)",
        "datasets": [
            "jsda_tokyo_repo_rates",
            "markets_margin_interest",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "mode": "rate_flow_price_agree",
            "hold_days": 10,
            "momentum_n": 5,
        },
    },
)


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "continuous_paper": CONTINUOUS_PAPER,
        "live_orders": LIVE_ORDERS,
        "frozen_defaults_retuned": False,
        "window_tweaks_forbidden": True,
        "always_through_evaluator": True,
    }


def _load_dotenv_key(path: Path, names: Sequence[str]) -> str | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        if k in names and v:
            return v
    return None


def _resolve_xai_session_key() -> str | None:
    """Resolve xAI key from env or Grok CLI OIDC session (auth.json)."""
    for env_name in ("XAI_API_KEY", "XAI_KEY", "GROK_API_KEY"):
        v = (os.environ.get(env_name) or "").strip()
        if v:
            return v
    auth_path = Path.home() / ".grok" / "auth.json"
    if not auth_path.is_file():
        return None
    try:
        doc = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    for entry in doc.values():
        if not isinstance(entry, Mapping):
            continue
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            return key.strip()
        if isinstance(key, Mapping):
            for kk in ("access_token", "token", "api_key"):
                vv = key.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
    return None


def detect_api_keys() -> dict[str, str | None]:
    """Detect available provider API keys (values never logged)."""
    glm = (
        os.environ.get("GLM_API_KEY")
        or _load_dotenv_key(
            Path.home() / ".config" / "glm-coding" / "key.env",
            ("GLM_API_KEY",),
        )
    )
    return {
        "openai": os.environ.get("OPENAI_API_KEY"),
        "xai": _resolve_xai_session_key(),
        "anthropic": os.environ.get("ANTHROPIC_API_KEY"),
        "glm": glm,
        "ai_gateway": os.environ.get("AI_GATEWAY_API_KEY")
        or os.environ.get("CF_AI_GATEWAY_TOKEN"),
    }


def _is_window_tweak(proposal: Mapping[str, Any]) -> bool:
    thesis = str(proposal.get("thesis") or "").strip()
    signal = str(
        proposal.get("signal_definition") or proposal.get("signal") or ""
    ).strip()
    position = str(
        proposal.get("position_rule") or proposal.get("position") or ""
    ).strip()
    if not thesis or not signal or not position:
        return True
    params = dict(proposal.get("params") or {})
    structural = (
        proposal.get("structural_keys")
        or proposal.get("mode")
        or params.get("mode")
        or params.get("book_mode")
        or params.get("gate_mode")
        or params.get("short_confirm_mode")
        or params.get("entry_mode")
    )
    if params and set(params.keys()) <= _NUMERIC_ONLY and not structural:
        return True
    blob = f"{thesis} {signal}".lower()
    if any(
        w in blob
        for w in ("window only", "hold_days only", "mom only", "frac only")
    ):
        if not proposal.get("datasets") and not proposal.get("datasets_used"):
            return True
    return False


def _extract_json_array(text: str) -> list[Any]:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        parsed = json.loads(t)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            for k in ("hypotheses", "proposals", "accepted", "items"):
                if isinstance(parsed.get(k), list):
                    return list(parsed[k])
    except json.JSONDecodeError:
        pass
    start = t.find("[")
    end = t.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(t[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


def _normalize_proposals(
    raw_list: Sequence[Any],
    *,
    source: str,
    model: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_list):
        if not isinstance(raw, Mapping):
            rejected.append({"index": i, "reject_reason": "not_object"})
            continue
        prop = dict(raw)
        if _is_window_tweak(prop):
            rejected.append(
                {
                    "index": i,
                    "proposal": prop,
                    "reject_reason": "window_tweak_only_forbidden",
                }
            )
            continue
        family = str(prop.get("family_id") or prop.get("family") or "").strip()
        if not family:
            rejected.append(
                {
                    "index": i,
                    "proposal": prop,
                    "reject_reason": "missing_family_id",
                }
            )
            continue
        logic_id = str(prop.get("logic_id") or f"llm_hyp_{i}").strip()
        datasets = list(
            prop.get("datasets_used") or prop.get("datasets") or []
        )
        accepted.append(
            {
                "logic_id": logic_id,
                "family_id": family,
                "thesis": str(prop.get("thesis") or ""),
                "signal_definition": str(
                    prop.get("signal_definition") or prop.get("signal") or ""
                ),
                "position_rule": str(
                    prop.get("position_rule") or prop.get("position") or ""
                ),
                "datasets": datasets,
                "datasets_used": datasets,
                "params": dict(prop.get("params") or {}),
                "source": source,
                "model": model,
                "generation_index": i,
            }
        )
    return accepted, rejected


_HYP_SYSTEM = """You are a quant research hypothesizer for Japanese equities (TSE).
Propose DISTINCT economic profit hypotheses. Each MUST have:
thesis, signal_definition, position_rule, datasets, family_id, logic_id, params.
FORBIDDEN: window/hold/mom/frac-only variants; sign flip as strategy; simple_daily_sign;
inventing data; claiming READY/Mass/GO/live.
Return ONLY a JSON array of objects."""


def _http_json(
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float = 180.0,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    # Cloudflare bot fight (error 1010) rejects bare/custom UAs; use browser-like.
    hdrs = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; quant-platform-w90/1.0; "
            "+research-mass-eval)"
        ),
        "Accept": "application/json",
    }
    hdrs.update(dict(headers or {}))
    # Keep browser-like UA even if caller omitted it
    if "User-Agent" not in (headers or {}):
        hdrs["User-Agent"] = (
            "Mozilla/5.0 (compatible; quant-platform-w90/1.0; "
            "+research-mass-eval)"
        )
    req = urllib.request.Request(
        url, data=data, headers=hdrs, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {e.code} {url}: {err_body}") from e


def _call_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    n: int,
    provider: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    user = (
        f"Generate {n} distinct multi-day JP equity profit hypotheses. "
        "Diversify families (flow, fund, rate, multi-factor, event, vol, XS, macro). "
        "No hold/mom/frac window tweaks. JSON array only."
    )
    out = _http_json(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body={
            "model": model,
            "messages": [
                {"role": "system", "content": _HYP_SYSTEM},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        timeout=180.0 if provider in {"xai", "grok"} else 90.0,
    )
    choices = out.get("choices") or []
    text = ""
    if choices:
        text = str((choices[0].get("message") or {}).get("content") or "")
    raw_list = _extract_json_array(text)
    acc, rej = _normalize_proposals(
        raw_list, source=f"llm_{provider}", model=model
    )
    return acc, rej, text


def _call_anthropic(
    *,
    api_key: str,
    model: str,
    n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    user = (
        f"Generate {n} distinct multi-day JP equity profit hypotheses. "
        "Diversify families. No window tweaks. JSON array only."
    )
    out = _http_json(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        body={
            "model": model,
            "max_tokens": 4096,
            "system": _HYP_SYSTEM,
            "messages": [{"role": "user", "content": user}],
        },
    )
    parts = out.get("content") or []
    text = ""
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            text += str(p.get("text") or "")
    raw_list = _extract_json_array(text)
    acc, rej = _normalize_proposals(
        raw_list, source="llm_anthropic", model=model
    )
    return acc, rej, text


def _resolve_worker_url() -> str | None:
    env_url = os.environ.get("RESEARCH_MASS_EVAL_URL")
    if env_url:
        return env_url.rstrip("/")
    # default workers.dev pattern
    return f"https://{_WORKER_NAME}.taku-haga.workers.dev"


def _call_workers_ai_via_worker(
    *,
    n: int,
    model: str | None = None,
    worker_url: str | None = None,
    timeout: float = 120.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    url = (worker_url or _resolve_worker_url() or "").rstrip("/")
    if not url:
        raise RuntimeError("no research-mass-eval worker URL")
    body: dict[str, Any] = {"n": n}
    if model:
        body["model"] = model
    out = _http_json(
        f"{url}/v1/generate_hyps",
        headers={"Content-Type": "application/json"},
        body=body,
        timeout=timeout,
    )
    used = str(out.get("model") or model or "workers_ai")
    if out.get("status") == "model_error" and not out.get("accepted"):
        raise RuntimeError(str(out.get("error") or "workers_ai model_error"))
    acc = [dict(x) for x in (out.get("accepted") or []) if isinstance(x, dict)]
    rej = [dict(x) for x in (out.get("rejected") or []) if isinstance(x, dict)]
    # If worker returned empty accepted, try raw parse is already done server-side
    return acc, rej, json.dumps(out)[:2000], used


def catalog_seed_hypotheses(n: int = 8) -> list[dict[str, Any]]:
    """Deterministic diverse catalog-seeded proposals (no human wait)."""
    out: list[dict[str, Any]] = []
    for i, seed in enumerate(_CATALOG_SEED_HYPS):
        if i >= n:
            break
        p = dict(seed)
        p["source"] = "catalog_seed_diverse"
        p["model"] = "catalog_seed/v1"
        p["generation_index"] = i
        p["datasets_used"] = list(p.get("datasets") or [])
        out.append(p)
    return out


def generate_strong_model_hypotheses(
    *,
    n: int = 8,
    provider: str | None = None,
    model: str | None = None,
    worker_url: str | None = None,
    allow_catalog_seed: bool = True,
) -> dict[str, Any]:
    """Generate multiple distinct profit hypotheses via best available model.

    Returns dict with model, n_proposed, n_accepted, accepted, rejected, provider.
    Never waits for human seeds. Window tweaks rejected.
    """
    n = max(1, min(int(n), 16))
    keys = detect_api_keys()
    attempts: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    used_model = ""
    used_provider = ""
    raw_preview = ""

    def _try(
        name: str,
        fn: Any,
    ) -> bool:
        nonlocal accepted, rejected, used_model, used_provider, raw_preview
        t0 = time.time()
        try:
            result = fn()
            if len(result) == 4:
                acc, rej, raw, model_used = result
            else:
                acc, rej, raw = result
                model_used = model or name
            attempts.append(
                {
                    "provider": name,
                    "status": "ok" if acc else "empty",
                    "n_accepted": len(acc),
                    "n_rejected": len(rej),
                    "wall_sec": round(time.time() - t0, 3),
                    "model": model_used,
                }
            )
            if acc:
                accepted = acc
                rejected = rej
                used_model = str(model_used)
                used_provider = name
                raw_preview = (raw or "")[:500]
                return True
            if rej and not acc:
                rejected = rej
                used_model = str(model_used)
                used_provider = name
        except Exception as exc:
            attempts.append(
                {
                    "provider": name,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                    "wall_sec": round(time.time() - t0, 3),
                }
            )
        return False

    # Provider order
    order: list[tuple[str, Any]] = []

    force = (provider or "").strip().lower()
    if force in {"catalog", "catalog_seed", "seed"}:
        accepted = catalog_seed_hypotheses(n)
        used_model = "catalog_seed/v1"
        used_provider = "catalog_seed"
        attempts.append(
            {
                "provider": "catalog_seed",
                "status": "ok",
                "n_accepted": len(accepted),
                "forced": True,
            }
        )
    else:
        # Prefer strong models first: xAI grok-4.6, then OpenAI, Anthropic, GLM,
        # then Workers AI open-weight, then catalog seed.
        if force in {"", "auto", "xai", "grok"} and keys.get("xai"):
            order.append(
                (
                    "xai",
                    lambda: (
                        *_call_openai_compatible(
                            base_url=os.environ.get(
                                "XAI_BASE_URL", "https://api.x.ai/v1"
                            ),
                            api_key=str(keys["xai"]),
                            model=model or "grok-4.6",
                            n=n,
                            provider="xai",
                        ),
                        model or "grok-4.6",
                    ),
                )
            )
        if force in {"", "auto", "openai"} and keys.get("openai"):
            order.append(
                (
                    "openai",
                    lambda: _call_openai_compatible(
                        base_url=os.environ.get(
                            "OPENAI_BASE_URL", "https://api.openai.com/v1"
                        ),
                        api_key=str(keys["openai"]),
                        model=model or "gpt-4o",
                        n=n,
                        provider="openai",
                    )
                    + (model or "gpt-4o",),  # type: ignore[operator]
                )
            )
        if force in {"", "auto", "anthropic"} and keys.get("anthropic"):
            order.append(
                (
                    "anthropic",
                    lambda: (
                        *_call_anthropic(
                            api_key=str(keys["anthropic"]),
                            model=model or "claude-sonnet-4-20250514",
                            n=n,
                        ),
                        model or "claude-sonnet-4-20250514",
                    ),
                )
            )
        if force in {"", "auto", "glm"} and keys.get("glm"):
            order.append(
                (
                    "glm",
                    lambda: (
                        *_call_openai_compatible(
                            base_url=os.environ.get(
                                "GLM_BASE_URL",
                                "https://open.bigmodel.cn/api/paas/v4",
                            ),
                            api_key=str(keys["glm"]),
                            model=model or "glm-4.7",
                            n=n,
                            provider="glm",
                        ),
                        model or "glm-4.7",
                    ),
                )
            )
        if force in {"", "auto", "workers_ai", "cf", "cloudflare"}:
            order.append(
                (
                    "workers_ai",
                    lambda: _call_workers_ai_via_worker(
                        n=n,
                        model=model
                        or "@cf/openai/gpt-oss-120b",
                        worker_url=worker_url,
                    ),
                )
            )

        # Fix openai lambda to return 4-tuple cleanly
        fixed_order: list[tuple[str, Any]] = []
        for name, fn in order:
            if name == "openai" and keys.get("openai"):

                def _openai_fn(
                    _m: str = model or "gpt-4o",
                    _k: str = str(keys["openai"]),
                ) -> tuple:
                    acc, rej, raw = _call_openai_compatible(
                        base_url=os.environ.get(
                            "OPENAI_BASE_URL", "https://api.openai.com/v1"
                        ),
                        api_key=_k,
                        model=_m,
                        n=n,
                        provider="openai",
                    )
                    return acc, rej, raw, _m

                fixed_order.append((name, _openai_fn))
            elif name == "xai" and keys.get("xai"):

                def _xai_fn(
                    _m: str = model or "grok-4.6",
                    _k: str = str(keys["xai"]),
                ) -> tuple:
                    acc, rej, raw = _call_openai_compatible(
                        base_url=os.environ.get(
                            "XAI_BASE_URL", "https://api.x.ai/v1"
                        ),
                        api_key=_k,
                        model=_m,
                        n=n,
                        provider="xai",
                    )
                    return acc, rej, raw, _m

                fixed_order.append((name, _xai_fn))
            elif name == "anthropic" and keys.get("anthropic"):

                def _ant_fn(
                    _m: str = model or "claude-sonnet-4-20250514",
                    _k: str = str(keys["anthropic"]),
                ) -> tuple:
                    acc, rej, raw = _call_anthropic(
                        api_key=_k, model=_m, n=n
                    )
                    return acc, rej, raw, _m

                fixed_order.append((name, _ant_fn))
            elif name == "glm" and keys.get("glm"):

                def _glm_fn(
                    _m: str = model or "glm-4.7",
                    _k: str = str(keys["glm"]),
                ) -> tuple:
                    acc, rej, raw = _call_openai_compatible(
                        base_url=os.environ.get(
                            "GLM_BASE_URL",
                            "https://open.bigmodel.cn/api/paas/v4",
                        ),
                        api_key=_k,
                        model=_m,
                        n=n,
                        provider="glm",
                    )
                    return acc, rej, raw, _m

                fixed_order.append((name, _glm_fn))
            else:
                fixed_order.append((name, fn))

        for name, fn in fixed_order:
            if force and force not in {
                "",
                "auto",
                name,
                "cf",
                "cloudflare",
                "grok",
            }:
                if not (
                    force in {"workers_ai", "cf", "cloudflare"}
                    and name == "workers_ai"
                ):
                    if force != name and not (
                        force == "grok" and name == "xai"
                    ):
                        continue
            if _try(name, fn):
                break

    if not accepted and allow_catalog_seed:
        accepted = catalog_seed_hypotheses(n)
        used_model = used_model or "catalog_seed/v1"
        used_provider = used_provider or "catalog_seed_fallback"
        attempts.append(
            {
                "provider": "catalog_seed_fallback",
                "status": "ok",
                "n_accepted": len(accepted),
                "note": "strong model unavailable or empty; diverse seeds used",
            }
        )

    # Presence flags (never values)
    key_presence = {k: bool(v) for k, v in keys.items()}

    return {
        "version": LLM_HYP_VERSION,
        "wave": LLM_HYP_WAVE,
        "status": "ok" if accepted else "empty",
        "provider": used_provider,
        "model": used_model,
        "n_requested": n,
        "n_proposed": len(accepted) + len(rejected),
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
        "accepted": accepted,
        "rejected": rejected,
        "attempts": attempts,
        "api_key_presence": key_presence,
        "raw_preview": raw_preview,
        "representative_theses": [
            {
                "logic_id": a.get("logic_id"),
                "family_id": a.get("family_id"),
                "thesis": str(a.get("thesis") or "")[:180],
            }
            for a in accepted[:8]
        ],
        **_freeze(),
    }


def generate_and_evaluate_hypotheses(
    *,
    n: int = 8,
    provider: str | None = None,
    model: str | None = None,
    worker_url: str | None = None,
    evaluate: bool = True,
    synthetic: bool = False,
    config: Any = None,
    map_unknown_to_nearest_catalog: bool = True,
) -> dict[str, Any]:
    """Generate strong-model hyps and evaluate via propose_profit_hypotheses.

    Unknown ad-hoc logic_ids are evaluated as ad-hoc individuals when they
    carry family_id + thesis fields. Optionally map known structural cousins
    onto catalog logic_ids for executable bar evaluators.
    """
    from research.mass_strategy_factory import (
        LOGIC_TEMPLATES,
        MassFactoryConfig,
        propose_profit_hypotheses,
    )

    gen = generate_strong_model_hypotheses(
        n=n,
        provider=provider,
        model=model,
        worker_url=worker_url,
        allow_catalog_seed=True,
    )
    proposals = list(gen.get("accepted") or [])

    # Map unknown logic_ids to nearest executable catalog template when
    # family matches a known template (keeps thesis text from LLM).
    if map_unknown_to_nearest_catalog:
        family_to_logic: dict[str, str] = {}
        for lid, tpl in LOGIC_TEMPLATES.items():
            family_to_logic.setdefault(tpl.family_id, lid)
        # Prefer richer mappings
        prefer = {
            "flow_demand": "flow_margin_short_hard",
            "flow": "flow_margin_short_hard",
            "event_post": "event_post_disclosure_hold",
            "event": "event_post_disclosure_hold",
            "rate_factor": "rate_abs_level_xs",
            "rate": "rate_abs_level_xs",
            "multi_factor": "mf_value_mom_rate",
            "multi-factor": "mf_value_mom_rate",
            "multifactor": "mf_value_mom_rate",
            "vol_risk_adjusted": "vol_risk_adjusted_mom",
            "vol": "vol_risk_adjusted_mom",
            "volatility": "vol_risk_adjusted_mom",
            "cross_section_relative": "xs_rank_ls_sticky",
            "xs": "xs_rank_ls_sticky",
            "cross_section": "xs_rank_ls_sticky",
            "macro_conditioned": "macro_repo_rate_change",
            "macro": "macro_repo_rate_change",
            "fundamentals_price": "fund_value_mom_agree",
            "fund": "fund_value_mom_agree",
            "fundamentals": "fund_value_mom_agree",
            "multi_day_hold": "mdh_sticky_momentum",
            "mdh": "mdh_sticky_momentum",
        }
        mapped: list[dict[str, Any]] = []
        for p in proposals:
            pp = dict(p)
            lid = str(pp.get("logic_id") or "")
            if lid not in LOGIC_TEMPLATES:
                fam = str(pp.get("family_id") or "")
                mapped_id = (
                    prefer.get(fam)
                    or prefer.get(fam.lower())
                    or prefer.get(fam.upper())
                    or family_to_logic.get(fam)
                    or family_to_logic.get(fam.lower())
                )
                if mapped_id:
                    pp["mapped_from_logic_id"] = lid
                    pp["logic_id"] = mapped_id
                    # Keep LLM thesis; use catalog signal/position only if empty
                    tpl = LOGIC_TEMPLATES[mapped_id]
                    if not pp.get("signal_definition"):
                        pp["signal_definition"] = tpl.signal_definition
                    if not pp.get("position_rule"):
                        pp["position_rule"] = tpl.position_rule
                    if not pp.get("datasets") and not pp.get("datasets_used"):
                        pp["datasets_used"] = list(tpl.datasets_used)
                    # Merge params carefully: catalog base + LLM structural
                    base = dict(tpl.base_params)
                    base.update(dict(pp.get("params") or {}))
                    pp["params"] = base
                    pp["eval_mapped_to_catalog"] = True
            mapped.append(pp)
        proposals = mapped

    cfg = config or MassFactoryConfig(seed=870816, n=max(20, len(proposals) + 5))
    eval_out = propose_profit_hypotheses(
        proposals,
        evaluate=evaluate,
        synthetic=synthetic,
        config=cfg,
    )

    n_evaluated = int(
        (eval_out.get("eval") or {}).get("n_strategies_evaluated") or 0
    )
    survivors = []
    for s in eval_out.get("eval_screens") or []:
        if isinstance(s, dict) and s.get("survived"):
            survivors.append(s)
    ranking = list(eval_out.get("eval_ranking") or [])

    return {
        "version": LLM_HYP_VERSION,
        "wave": LLM_HYP_WAVE,
        "generation": {
            k: gen[k]
            for k in gen
            if k
            not in {
                "accepted",
                "rejected",
            }
        },
        "proposals_for_eval": proposals,
        "n_proposed": gen.get("n_proposed"),
        "n_accepted": gen.get("n_accepted"),
        "n_evaluated": n_evaluated,
        "n_survivors": len(survivors),
        "model": gen.get("model"),
        "provider": gen.get("provider"),
        "representative_theses": gen.get("representative_theses"),
        "propose_profit_hypotheses": {
            k: eval_out[k]
            for k in eval_out
            if k
            not in {
                "accepted",
                "rejected",
                "eval_results",
                "eval_screens",
                "eval_ranking",
            }
        },
        "eval_screens": eval_out.get("eval_screens"),
        "eval_ranking": ranking,
        "eval_results": eval_out.get("eval_results"),
        "accepted_proposals": eval_out.get("accepted"),
        "rejected_proposals": eval_out.get("rejected"),
        **_freeze(),
    }


def package_logics_for_cf_eval(
    results: Sequence[Mapping[str, Any]],
    *,
    source_tag: str = "local_eval",
) -> list[dict[str, Any]]:
    """Convert factory/LLM eval results (with period_rows) into CF job logics."""
    logics: list[dict[str, Any]] = []
    for r in results:
        periods_out: list[dict[str, Any]] = []
        for pr in r.get("period_rows") or []:
            if not isinstance(pr, Mapping):
                continue
            occ = pr.get("occurrence") or {}
            act = occ.get("activation_rate") if isinstance(occ, Mapping) else None
            if act is None:
                act = pr.get("activation_rate")
            periods_out.append(
                {
                    "period_id": pr.get("period_id"),
                    "year": pr.get("year"),
                    "status": pr.get("status") or "ok",
                    "gross_signed_mean_active": pr.get(
                        "gross_signed_mean_active"
                    ),
                    "net_one_way_mean_active": pr.get(
                        "net_one_way_mean_active"
                    ),
                    "amortized_one_way_cost": pr.get("amortized_one_way_cost"),
                    "activation_rate": act,
                    "hold_days": pr.get("hold_days"),
                }
            )
        logics.append(
            {
                "logic_id": r.get("logic_id"),
                "strategy_id": r.get("strategy_id"),
                "family_id": r.get("family_id"),
                "thesis": r.get("thesis"),
                "source": r.get("source") or source_tag,
                "params": r.get("params") or {},
                "periods": periods_out,
                "mean_net": r.get("mean_net"),
                "mean_gross": r.get("mean_gross"),
                "t_stat": r.get("t_stat"),
                "sharpe_period": r.get("sharpe_period"),
                "chosen_sign": r.get("chosen_sign"),
                "mean_activation": r.get("mean_activation"),
                "n_periods_ok": r.get("n_periods_ok"),
            }
        )
    return logics


def default_r2_put_research(
    key: str,
    body: bytes,
    *,
    bucket: str = "quant-structured",
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Put research artifact to R2 via wrangler."""
    from research.single_shot_job import default_r2_put

    wr = wrangler or (
        _WORKER_DIR / "node_modules" / ".bin" / "wrangler"
        if (_WORKER_DIR / "node_modules" / ".bin" / "wrangler").is_file()
        else _DEFAULT_WRANGLER
    )
    cfg = config or (
        _WORKER_CONFIG if _WORKER_CONFIG.is_file() else None
    )
    return default_r2_put(
        bucket,
        key,
        body,
        wrangler=wr,
        config=cfg,
        dry_run=dry_run,
        staging_dir=staging_dir,
    )


def run_cf_multi_logic_eval_job(
    logics: Sequence[Mapping[str, Any]],
    *,
    job_id: str | None = None,
    worker_url: str | None = None,
    near_zero_abs: float = 0.0005,
    min_activation: float = 0.01,
    one_way_cost: float = 0.001,
    seed: int = 870816,
    mode: str = "synthetic",
    periods: Sequence[Mapping[str, Any]] | None = None,
    write_r2_input: bool = True,
    dry_run: bool = False,
    notes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute CF multi-logic multi-period eval via research-mass-eval Worker.

    Primary path: ``POST /v1/mass-eval`` on
    ``quant-platform-research-mass-eval`` (writes R2 under
    ``research/mass_eval/job={id}/``). Optional input.json stage for audit.

    Local aggregate is used only when the worker is unreachable — documented
    as incomplete CF path (not claimed as done).
    """
    jid = job_id or f"w90_{time.strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
    period_rows = [dict(p) for p in (periods or [])]
    if not period_rows:
        period_rows = [
            {"period_id": "y2019_q4_lite", "year": 2019},
            {"period_id": "y2020_q4_lite", "year": 2020},
            {"period_id": "y2021_q4_lite", "year": 2021},
            {"period_id": "y2022_q4_lite", "year": 2022},
            {"period_id": "y2023_q4_lite", "year": 2023},
            {"period_id": "y2024_q4_lite", "year": 2024},
        ]
    # Normalize logics for worker shape
    logic_rows: list[dict[str, Any]] = []
    for i, raw in enumerate(logics):
        if not isinstance(raw, Mapping):
            continue
        row = {
            "logic_id": raw.get("logic_id") or f"logic_{i}",
            "strategy_id": raw.get("strategy_id"),
            "family_id": raw.get("family_id") or "multi_day_hold",
            "params": dict(raw.get("params") or {}),
            "thesis": raw.get("thesis") or "",
            "signal_definition": raw.get("signal_definition")
            or raw.get("signal")
            or "",
            "position_rule": raw.get("position_rule") or raw.get("position") or "",
            "periods": list(raw.get("periods") or []),
            "period_nets": raw.get("period_nets"),
            "period_grosses": raw.get("period_grosses"),
            "mean_net": raw.get("mean_net"),
            "mean_gross": raw.get("mean_gross"),
            "t_stat": raw.get("t_stat"),
            "sharpe_period": raw.get("sharpe_period"),
            "chosen_sign": raw.get("chosen_sign"),
            "mean_activation": raw.get("mean_activation"),
            "source": raw.get("source"),
        }
        logic_rows.append(row)

    input_doc = {
        "job_id": jid,
        "seed": int(seed),
        "wave": LLM_HYP_WAVE,
        "version": "research-mass-eval/v1",
        "mode": mode,
        "one_way_cost": one_way_cost,
        "near_zero_abs": near_zero_abs,
        "min_activation": min_activation,
        "logics": logic_rows,
        "periods": period_rows,
        "notes": dict(notes or {}),
    }
    input_key = f"research/mass_eval/job={jid}/input.json"
    r2_input_meta: dict[str, Any] | None = None
    if write_r2_input and not dry_run:
        try:
            r2_input_meta = default_r2_put_research(
                input_key,
                json.dumps(input_doc, indent=2).encode("utf-8"),
            )
        except Exception as exc:
            r2_input_meta = {
                "status": "put_failed",
                "error": f"{type(exc).__name__}: {exc}"[:400],
                "key": input_key,
            }

    url = (
        worker_url
        or _resolve_worker_url()
        or "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
    ).rstrip("/")
    path_used = "none"
    summary: dict[str, Any] = {}
    http_error: str | None = None

    if dry_run:
        path_used = "dry_run_local_aggregate"
        summary = _local_aggregate_fallback(input_doc)
        summary["status"] = "dry_run"
    else:
        # Primary: deployed worker POST /v1/mass-eval
        try:
            summary = _http_json(
                f"{url}/v1/mass-eval",
                headers={"Content-Type": "application/json"},
                body=input_doc,
                timeout=240.0,
            )
            # Worker returns {ok:true, ...} or {status:"ok", ...}
            if summary and (
                summary.get("ok") is True
                or summary.get("status") in {"ok", "available", None}
                or summary.get("n_eval_ok") is not None
                or summary.get("n_logics_evaluated") is not None
            ):
                path_used = "cf_worker_mass_eval"
            else:
                raise RuntimeError(
                    f"unexpected mass-eval response keys={list(summary)[:12]}"
                )
        except Exception as exc:
            http_error = f"mass_eval: {type(exc).__name__}: {exc}"[:400]

        if not summary:
            # Last resort: local aggregate (document as incomplete CF path)
            summary = _local_aggregate_fallback(input_doc)
            path_used = "local_aggregate_fallback"
            summary["cf_path_note"] = (
                "worker unreachable; local aggregate used — not CF done. "
                + (http_error or "")
            )

    n_eval = int(
        summary.get("n_eval_ok")
        or summary.get("n_logics_evaluated")
        or summary.get("n_evaluated")
        or 0
    )
    n_surv = int(summary.get("n_survivors") or 0)
    r2_keys = dict(summary.get("r2_keys") or {})
    if not r2_keys:
        prefix = f"research/mass_eval/job={jid}"
        r2_keys = {
            "summary": f"{prefix}/summary.json",
            "results": f"{prefix}/results.json",
            "ranking": f"{prefix}/ranking.json",
            "manifest": f"{prefix}/manifest.json",
            "input": input_key,
        }

    return {
        "job_id": jid,
        "path_used": path_used,
        "status": "ok" if path_used.startswith("cf_worker") else path_used,
        "worker_url": url,
        "input_key": input_key,
        "r2_input": r2_input_meta,
        "summary": summary,
        "n_logics": len(logic_rows),
        "n_periods": len(period_rows),
        "n_logics_evaluated": n_eval,
        "n_survivors": n_surv,
        "r2_paths": r2_keys,
        "r2_prefix": f"research/mass_eval/job={jid}/",
        "http_error": http_error,
        "mode": mode,
        "seed": seed,
        "wave": LLM_HYP_WAVE,
        **_freeze(),
    }


def _local_aggregate_fallback(input_doc: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror CF worker multi-period aggregation locally (fallback only)."""
    near = float(input_doc.get("near_zero_abs") or 0.0005)
    min_act = float(input_doc.get("min_activation") or 0.01)
    results = []
    for logic in input_doc.get("logics") or []:
        if not isinstance(logic, Mapping):
            continue
        periods = list(logic.get("periods") or [])
        nets: list[float] = []
        grosses: list[float] = []
        costs: list[float | None] = []
        acts: list[float] = []
        for p in periods:
            if not isinstance(p, Mapping):
                continue
            if p.get("status") not in {None, "ok"}:
                continue
            n = p.get("net_one_way_mean_active")
            if n is None:
                continue
            try:
                nf = float(n)
            except (TypeError, ValueError):
                continue
            nets.append(nf)
            g = p.get("gross_signed_mean_active")
            try:
                grosses.append(float(g) if g is not None else nf)
            except (TypeError, ValueError):
                grosses.append(nf)
            c = p.get("amortized_one_way_cost")
            try:
                costs.append(float(c) if c is not None else None)
            except (TypeError, ValueError):
                costs.append(None)
            ar = p.get("activation_rate")
            if ar is not None:
                try:
                    acts.append(float(ar))
                except (TypeError, ValueError):
                    pass
        if not nets and logic.get("mean_net") is not None:
            try:
                nets = [float(logic["mean_net"])]
                grosses = [
                    float(logic["mean_gross"])
                    if logic.get("mean_gross") is not None
                    else nets[0]
                ]
                costs = [None]
            except (TypeError, ValueError):
                nets = []

        def _mean(xs: list[float]) -> float | None:
            return sum(xs) / len(xs) if xs else None

        def _t(xs: list[float]) -> float | None:
            if len(xs) < 2:
                return None
            m = _mean(xs) or 0.0
            var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
            s = var ** 0.5
            if s == 0:
                return None
            return m / (s / (len(xs) ** 0.5))

        def _sharpe(xs: list[float]) -> float | None:
            if len(xs) < 2:
                return None
            m = _mean(xs) or 0.0
            var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
            s = var ** 0.5
            return None if s == 0 else m / s

        inv: list[float] = []
        for i, n in enumerate(nets):
            c = costs[i] if i < len(costs) else None
            if c is not None:
                inv.append(-n - 2 * c)
            else:
                inv.append(-n)
        mean_o = _mean(nets)
        mean_i = _mean(inv)
        chosen = None
        if mean_o is not None and mean_o > near:
            chosen = 1
        if mean_i is not None and mean_i > near:
            if chosen is None or (mean_i > (mean_o or -1e9)):
                chosen = -1
        side = inv if chosen == -1 else nets
        mean_net = mean_i if chosen == -1 else mean_o
        reject = []
        if not nets:
            reject.append("no_ok_periods")
        if mean_net is not None and abs(mean_net) < near:
            reject.append("near_zero_after_cost")
        if chosen is None and nets:
            reject.append("both_signs_near_zero_or_nonpositive")
        mean_act = _mean(acts)
        if mean_act is not None and mean_act < min_act and nets:
            reject.append("low_activation")
        survived = len(reject) == 0 and bool(nets) and chosen is not None
        results.append(
            {
                "logic_id": logic.get("logic_id"),
                "strategy_id": logic.get("strategy_id") or logic.get("logic_id"),
                "family_id": logic.get("family_id"),
                "thesis": logic.get("thesis"),
                "source": logic.get("source"),
                "n_periods_ok": len(nets),
                "mean_gross": _mean(grosses),
                "mean_net": mean_net,
                "t_stat": _t(side),
                "sharpe_period": _sharpe(side),
                "mean_activation": mean_act,
                "chosen_sign": chosen,
                "survived": survived,
                "reject_reasons": reject,
            }
        )
    survivors = [r for r in results if r.get("survived")]
    ranking = sorted(
        results,
        key=lambda r: (
            0 if r.get("survived") else 1,
            -(r.get("t_stat") or -1e9),
            -(r.get("mean_net") or -1e9),
        ),
    )
    for i, r in enumerate(ranking):
        r["rank"] = i + 1
    return {
        "job_id": input_doc.get("job_id"),
        "version": "research-mass-eval/v1",
        "wave": LLM_HYP_WAVE,
        "status": "ok",
        "n_logics_input": len(list(input_doc.get("logics") or [])),
        "n_logics_evaluated": len(results),
        "n_survivors": len(survivors),
        "n_screen_rejected": len(results) - len(survivors),
        "fail_rate": 0,
        "ranking": ranking,
        "results": results,
        "wide_table": ranking,
        **_freeze(),
    }


def generate_profit_hypotheses_via_llm(
    *,
    n: int = 8,
    provider: str | None = None,
    model: str | None = None,
    worker_url: str | None = None,
    evaluate: bool = True,
    synthetic: bool = False,
    config: Any = None,
) -> dict[str, Any]:
    """Alias used by factory docs: strong-model gen → always through evaluator."""
    return generate_and_evaluate_hypotheses(
        n=n,
        provider=provider,
        model=model,
        worker_url=worker_url,
        evaluate=evaluate,
        synthetic=synthetic,
        config=config,
        map_unknown_to_nearest_catalog=True,
    )


__all__ = [
    "LLM_HYP_WAVE",
    "LLM_HYP_VERSION",
    "detect_api_keys",
    "catalog_seed_hypotheses",
    "generate_strong_model_hypotheses",
    "generate_and_evaluate_hypotheses",
    "generate_profit_hypotheses_via_llm",
    "package_logics_for_cf_eval",
    "run_cf_multi_logic_eval_job",
    "default_r2_put_research",
]
