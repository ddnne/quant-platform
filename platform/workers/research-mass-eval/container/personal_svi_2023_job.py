"""One fixed 2023 SVI DRAFT screen for the existing personal Container.

All R2 reads are routed through the Container outbound capability.  The
Worker-created input manifest is the complete allowlist; option JSONL is read
one day at a time and released before the next day is opened.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, BinaryIO, Callable, Mapping, Sequence

from research.options_225_smile_features import (
    OPTIONS_225_SMILE_FEATURE_VERSION,
    build_daily_options_225_smile_features,
)
from research.personal_metrics import summarize_performance


R2_ORIGIN = "http://research.r2"
COHORT_ID = "personal-svi-term-2023-v1"
STRATEGY_ID = "svi-atm-term-ratio-momentum-switch"
RUNNER_VERSION = "personal-svi-cloud-runner/v4"
FEATURE_FIELD = "svi_atm_short_over_next_minus_one"
PANEL_KEY = (
    "research/mass_eval/panels_cache/527c1065afe14601/panels/y2023_full.json"
)
EARLIEST_DAY = "2023-01-04"
LATEST_DAY = "2023-10-13"
DECISION_CUTOFF_JST = "15:00:00+09:00"
EQUITY_UNIVERSE = {
    "scope_id": "legacy-liq-large-adv100-2019-v1",
    "selection_rule": "adv_desc_skip_missing_bars_and_fins",
    "selection_reference_start": "2019-01-01",
    "selection_reference_end": "2019-10-21",
    "maximum_codes": 100,
    "membership": "static_fixed_panel_codes",
    "daily_pit_reconstitution": False,
    "topix_scale_bound": False,
    "comparable_to_personal_topix_factor_runs": False,
}
HOLD_SESSIONS = 10
MOMENTUM_SESSIONS = 5
ONE_WAY_COST = 0.001
LONG_FRACTION = 0.30
SHORT_FRACTION = 0.30
TOPIX_PROXY_PANEL_CODE = "__NKY_PROXY__"
TOPIX_PROXY_DATASET = "indices_bars_daily_topix"
BETA_LOOKBACK_SESSIONS = 126
BETA_MIN_OBSERVATIONS = 63
MAX_ABS_TOPIX_HEDGE_WEIGHT = 1.5
MAX_INPUT_MANIFEST_BYTES = 512 * 1024
MAX_PANEL_BYTES = 64 * 1024 * 1024
MAX_OPTIONS_OBJECT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024

_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class SviJobInputError(ValueError):
    """The Worker supplied a non-closed SVI job document."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _prefix(job_id: str) -> str:
    return f"research/personal/svi-2023/job={job_id}"


@dataclass(frozen=True, slots=True)
class PersonalSvi2023JobSpec:
    cohort_id: str
    feature_key: str
    input_manifest_digest: str
    input_manifest_key: str
    job_id: str
    manifest_key: str
    report_key: str
    request_digest: str
    runner_version: str
    strategy_id: str

    @property
    def cohort_digest(self) -> str:
        """Common JobManager metadata without widening the closed wire type."""
        return _sha256(
            _canonical_bytes(
                {
                    "cohort_id": COHORT_ID,
                    "feature": FEATURE_FIELD,
                    "hold_sessions": HOLD_SESSIONS,
                    "one_way_cost": ONE_WAY_COST,
                    "runner_version": RUNNER_VERSION,
                    "signal_lag_sessions": 1,
                    "strategy_id": STRATEGY_ID,
                }
            )
        )

    @classmethod
    def from_document(cls, document: Any) -> "PersonalSvi2023JobSpec":
        fields = {
            "cohort_id",
            "feature_key",
            "input_manifest_digest",
            "input_manifest_key",
            "job_id",
            "manifest_key",
            "report_key",
            "request_digest",
            "runner_version",
            "strategy_id",
        }
        if not isinstance(document, dict) or set(document) != fields:
            raise SviJobInputError("SVI job fields are closed")
        if not all(isinstance(document[field], str) for field in fields):
            raise SviJobInputError("SVI job fields must be strings")
        spec = cls(**{field: document[field] for field in fields})
        spec.validate()
        return spec

    def validate(self) -> None:
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise SviJobInputError("job_id is invalid")
        if self.cohort_id != COHORT_ID or self.strategy_id != STRATEGY_ID:
            raise SviJobInputError("fixed SVI strategy identity mismatch")
        if self.runner_version != RUNNER_VERSION:
            raise SviJobInputError("SVI runner version mismatch")
        if _DIGEST_RE.fullmatch(self.input_manifest_digest) is None:
            raise SviJobInputError("input manifest digest is invalid")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise SviJobInputError("request digest is invalid")
        prefix = _prefix(self.job_id)
        expected = {
            "input_manifest_key": f"{prefix}/input-manifest.json",
            "feature_key": f"{prefix}/features.jsonl",
            "report_key": f"{prefix}/report.json",
            "manifest_key": f"{prefix}/manifest.json",
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise SviJobInputError(f"{field} mismatch")
        if self.request_digest != self.derived_request_digest():
            raise SviJobInputError("request digest mismatch")

    def derived_request_digest(self) -> str:
        body = {
            "cohort_id": self.cohort_id,
            "input_manifest_digest": self.input_manifest_digest,
            "input_manifest_key": self.input_manifest_key,
            "job_id": self.job_id,
            "runner_version": self.runner_version,
            "strategy_id": self.strategy_id,
        }
        return _sha256(_canonical_bytes(body))

    def headers(self) -> dict[str, str]:
        return {
            "x-svi-job-id": self.job_id,
            "x-svi-input-manifest-key": self.input_manifest_key,
            "x-svi-input-manifest-digest": self.input_manifest_digest,
        }


def _open_input(spec: PersonalSvi2023JobSpec, key: str, *, timeout: float = 120):
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        method="GET",
        headers=spec.headers(),
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _read_bounded(response: BinaryIO, maximum: int) -> bytes:
    declared = response.headers.get("content-length", "")
    if not declared.isdigit() or not 0 < int(declared) <= maximum:
        raise RuntimeError("input content length missing or out of bounds")
    expected = int(declared)
    data = response.read(expected + 1)
    if len(data) != expected:
        raise RuntimeError("input content length mismatch")
    return data


def load_input_manifest(
    spec: PersonalSvi2023JobSpec,
    *,
    opener: Callable[[PersonalSvi2023JobSpec, str], Any] = _open_input,
) -> dict[str, Any]:
    with opener(spec, spec.input_manifest_key) as response:
        raw = _read_bounded(response, MAX_INPUT_MANIFEST_BYTES)
    if _sha256(raw) != spec.input_manifest_digest:
        raise RuntimeError("input manifest digest mismatch")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("input manifest is not an object")
    authority = parsed.get("authority")
    options = parsed.get("options")
    sessions = parsed.get("sessions")
    strategy = parsed.get("strategy")
    panel = parsed.get("panel")
    equity_universe = parsed.get("equity_universe")
    temporal = parsed.get("temporal_contract")
    if (
        parsed.get("schema_version") != "personal-svi-2023-input/v2"
        or parsed.get("job_id") != spec.job_id
        or parsed.get("cohort_id") != COHORT_ID
        or parsed.get("runner_version") != RUNNER_VERSION
        or not isinstance(authority, dict)
        or authority
        != {
            "draft_only": True,
            "screening_only": True,
            "ready": False,
            "mass": False,
            "promotion": False,
            "live_orders": False,
            "go": False,
        }
        or not isinstance(options, dict)
        or options.get("dataset") != "derivatives_bars_daily_options_225"
        or options.get("natural_key") != ["Date", "Code"]
        or not isinstance(options.get("days"), list)
        or not isinstance(panel, dict)
        or panel.get("key") != PANEL_KEY
        or equity_universe != EQUITY_UNIVERSE
        or not isinstance(sessions, dict)
        or not isinstance(sessions.get("warmup_dates"), list)
        or not isinstance(sessions.get("evaluation_dates"), list)
        or not isinstance(strategy, dict)
        or strategy.get("strategy_id") != STRATEGY_ID
        or strategy.get("feature") != FEATURE_FIELD
        or strategy.get("signal_lag_sessions") != 1
        or strategy.get("hold_sessions") != HOLD_SESSIONS
        or strategy.get("one_way_cost") != ONE_WAY_COST
        or temporal
        != {
            "source_decision_cutoff_jst": DECISION_CUTOFF_JST,
            "signal_lag_sessions": 1,
            "fill_timing": "next_close",
            "first_pnl_interval": "fill_close_to_following_close",
        }
    ):
        raise RuntimeError("input manifest closed contract mismatch")
    warmup_dates = sessions["warmup_dates"]
    evaluation_dates = sessions["evaluation_dates"]
    option_dates = [
        entry.get("date") if isinstance(entry, dict) else None
        for entry in options["days"]
    ]
    invalid_option_dates = any(
        not isinstance(day, str)
        or re.fullmatch(r"2023-\d{2}-\d{2}", day) is None
        or not EARLIEST_DAY <= day <= LATEST_DAY
        for day in option_dates
    )
    if (
        sessions.get("warmup_sessions") != len(warmup_dates)
        or len(warmup_dates) > 60
        or not evaluation_dates
        or invalid_option_dates
        or option_dates != sorted(option_dates)
        or option_dates != [*warmup_dates, *evaluation_dates]
        or len(set(option_dates)) != len(option_dates)
    ):
        raise RuntimeError("input manifest session contract mismatch")
    return parsed


def load_panel(
    spec: PersonalSvi2023JobSpec,
    manifest: Mapping[str, Any],
    *,
    opener: Callable[[PersonalSvi2023JobSpec, str], Any] = _open_input,
) -> dict[str, Any]:
    reference = manifest.get("panel")
    if not isinstance(reference, dict) or reference.get("key") != PANEL_KEY:
        raise RuntimeError("fixed panel reference mismatch")
    with opener(spec, PANEL_KEY) as response:
        raw = _read_bounded(response, MAX_PANEL_BYTES)
    expected_sha = reference.get("sha256")
    if not isinstance(expected_sha, str) or _sha256(raw) != expected_sha:
        raise RuntimeError("fixed panel sha256 mismatch")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("bars"), dict):
        raise RuntimeError("fixed panel payload is invalid")
    return parsed


def _payload(line: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = line.get("payload")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, Mapping) else None


def _natural_key(line: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = line.get("natural_key")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, Mapping) else None


def _valid_iso_day(value: Any) -> str | None:
    day = str(value or "")[:10]
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        return None


def _valid_iso_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _line_identity(line: Mapping[str, Any], day: str) -> tuple[str, str] | None:
    if line.get("dataset") != "derivatives_bars_daily_options_225":
        return None
    payload = _payload(line)
    natural_key = _natural_key(line)
    if payload is None or natural_key is None:
        return None
    payload_day = _valid_iso_day(payload.get("Date") or payload.get("date"))
    payload_code = str(payload.get("Code") or payload.get("code") or "")
    key_day = _valid_iso_day(natural_key.get("Date") or natural_key.get("date"))
    key_code = str(natural_key.get("Code") or natural_key.get("code") or "")
    event_at = _valid_iso_instant(line.get("event_time"))
    available_at = _valid_iso_instant(line.get("available_at"))
    cutoff = datetime.fromisoformat(f"{day}T{DECISION_CUTOFF_JST}")
    if (
        payload_day != day
        or key_day != day
        or not payload_code
        or key_code != payload_code
        or event_at is None
        or event_at.date().isoformat() != day
        or available_at is None
        or available_at > event_at
        or event_at > cutoff
        or available_at > cutoff
    ):
        return None
    return day, payload_code


OpenInput = Callable[[PersonalSvi2023JobSpec, str], Any]


def load_one_options_day(
    spec: PersonalSvi2023JobSpec,
    day_entry: Mapping[str, Any],
    *,
    opener: OpenInput = _open_input,
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    day = str(day_entry.get("date") or "")
    objects = day_entry.get("objects")
    if (
        not re.fullmatch(r"2023-\d{2}-\d{2}", day)
        or not EARLIEST_DAY <= day <= LATEST_DAY
        or not isinstance(objects, list)
        or not objects
    ):
        raise RuntimeError("options day manifest entry is invalid")
    selected: dict[tuple[str, str], tuple[tuple[str, str, int], Mapping[str, Any]]] = {}
    parsed_rows = 0
    rejected_rows = 0
    for object_index, reference in enumerate(objects):
        if not isinstance(reference, dict):
            raise RuntimeError("options object reference is invalid")
        key = str(reference.get("key") or "")
        expected_size = reference.get("size")
        expected_sha = reference.get("sha256")
        if (
            not isinstance(expected_size, int)
            or not 0 < expected_size <= MAX_OPTIONS_OBJECT_BYTES
            or f"/dt={day}/" not in key
        ):
            raise RuntimeError("options object bound mismatch")
        digest = hashlib.sha256()
        received = 0
        with opener(spec, key) as response:
            declared = response.headers.get("content-length", "")
            if not declared.isdigit() or int(declared) != expected_size:
                raise RuntimeError("options object content length mismatch")
            for line_index, raw_line in enumerate(response):
                received += len(raw_line)
                if received > expected_size:
                    raise RuntimeError("options object exceeded its manifest size")
                digest.update(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    parsed = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    rejected_rows += 1
                    continue
                if not isinstance(parsed, dict):
                    rejected_rows += 1
                    continue
                identity = _line_identity(parsed, day)
                payload = _payload(parsed)
                if identity is None or payload is None:
                    rejected_rows += 1
                    continue
                parsed_rows += 1
                rank = (
                    str(parsed.get("ingested_at") or ""),
                    key,
                    line_index + object_index * 10_000_000,
                )
                current = selected.get(identity)
                if current is None or rank > current[0]:
                    selected[identity] = (rank, payload)
        if received != expected_size:
            raise RuntimeError("options object content length mismatch")
        actual_sha = "sha256:" + digest.hexdigest()
        if isinstance(expected_sha, str) and expected_sha and actual_sha != expected_sha:
            raise RuntimeError("options object sha256 mismatch")
    rows = [selected[key][1] for key in sorted(selected)]
    return rows, {
        "source_rows": parsed_rows,
        "rejected_rows": rejected_rows,
        "deduplicated_rows": parsed_rows - len(rows),
        "natural_keys": len(rows),
    }


def build_feature_sidecar(
    spec: PersonalSvi2023JobSpec,
    manifest: Mapping[str, Any],
    *,
    opener: OpenInput = _open_input,
) -> list[dict[str, Any]]:
    options = manifest["options"]
    rows: list[dict[str, Any]] = []
    for day_entry in options["days"]:
        day = str(day_entry["date"])
        day_rows, audit = load_one_options_day(spec, day_entry, opener=opener)
        built = build_daily_options_225_smile_features(day_rows)
        matching = [row for row in built if row.get("date") == day]
        if len(matching) == 1:
            feature = dict(matching[0])
        else:
            feature = {
                "date": day,
                "fit_success": False,
                "fit_reason": (
                    "no_valid_structured_rows" if not matching else "multiple_daily_rows"
                ),
                "version": OPTIONS_225_SMILE_FEATURE_VERSION,
            }
        feature["input_audit"] = audit
        feature["source_object_keys"] = [
            str(reference["key"]) for reference in day_entry["objects"]
        ]
        rows.append(feature)
        # day_rows and the raw JSONL object graph become unreachable here;
        # the next R2 day is not opened until the builder has returned.
    return rows


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_bars(panel: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    raw = panel.get("bars")
    if not isinstance(raw, Mapping):
        raise RuntimeError("panel bars missing")
    bars: dict[str, dict[str, float]] = {}
    for code, pairs in raw.items():
        if str(code).startswith("__") or not isinstance(pairs, Sequence):
            continue
        by_day: dict[str, float] = {}
        for pair in pairs:
            if not isinstance(pair, Sequence) or len(pair) < 2:
                continue
            day = str(pair[0])[:10]
            close = _number(pair[1])
            if close is not None and close > 0 and EARLIEST_DAY <= day <= LATEST_DAY:
                by_day[day] = close
        if by_day:
            bars[str(code)] = by_day
    if len(bars) < 4:
        raise RuntimeError("fixed panel has too few equities")
    return bars


_BetaEstimate = tuple[float, int, str]


def _normalize_topix_proxy(panel: Mapping[str, Any]) -> dict[str, float]:
    """Open the legacy alias only when the panel proves it contains TOPIX."""

    identity = panel.get("index_proxy")
    if (
        not isinstance(identity, Mapping)
        or identity.get("dataset") != TOPIX_PROXY_DATASET
        or identity.get("label") != "TOPIX"
    ):
        raise RuntimeError("TOPIX index proxy identity is unavailable")
    raw = panel.get("bars")
    pairs = raw.get(TOPIX_PROXY_PANEL_CODE) if isinstance(raw, Mapping) else None
    if not isinstance(pairs, Sequence):
        raise RuntimeError("TOPIX index proxy series is unavailable")
    values: dict[str, float] = {}
    for pair in pairs:
        if not isinstance(pair, Sequence) or len(pair) < 2:
            continue
        day = _valid_iso_day(pair[0])
        close = _number(pair[1])
        if day is not None and close is not None and close > 0:
            values[day] = close
    if len(values) < BETA_MIN_OBSERVATIONS + 1:
        raise RuntimeError("TOPIX index proxy has insufficient history")
    return values


def _estimate_beta_through(
    stock: Mapping[str, float],
    topix: Mapping[str, float],
    signal_day: str,
) -> _BetaEstimate | None:
    """Estimate beta from at most 126 paired returns ending no later than d."""

    common_days = sorted(day for day in stock if day <= signal_day and day in topix)
    observations: list[tuple[str, float, float]] = []
    for previous_day, current_day in zip(common_days, common_days[1:]):
        stock_before = stock[previous_day]
        topix_before = topix[previous_day]
        if stock_before <= 0 or topix_before <= 0:
            continue
        observations.append(
            (
                current_day,
                stock[current_day] / stock_before - 1.0,
                topix[current_day] / topix_before - 1.0,
            )
        )
    observations = observations[-BETA_LOOKBACK_SESSIONS:]
    if len(observations) < BETA_MIN_OBSERVATIONS:
        return None
    stock_returns = [row[1] for row in observations]
    topix_returns = [row[2] for row in observations]
    stock_mean = sum(stock_returns) / len(stock_returns)
    topix_mean = sum(topix_returns) / len(topix_returns)
    covariance_sum = sum(
        (stock_return - stock_mean) * (topix_return - topix_mean)
        for stock_return, topix_return in zip(stock_returns, topix_returns)
    )
    topix_variance_sum = sum(
        (topix_return - topix_mean) ** 2 for topix_return in topix_returns
    )
    if topix_variance_sum <= 1e-18:
        return None
    beta = covariance_sum / topix_variance_sum
    if not math.isfinite(beta):
        return None
    return beta, len(observations), observations[-1][0]


def _realized_beta(
    returns: Sequence[float],
    topix_returns: Sequence[float],
) -> float | None:
    if len(returns) != len(topix_returns) or len(returns) < 2:
        return None
    return_mean = sum(returns) / len(returns)
    topix_mean = sum(topix_returns) / len(topix_returns)
    covariance_sum = sum(
        (value - return_mean) * (proxy - topix_mean)
        for value, proxy in zip(returns, topix_returns)
    )
    variance_sum = sum((value - topix_mean) ** 2 for value in topix_returns)
    if variance_sum <= 1e-18:
        return None
    beta = covariance_sum / variance_sum
    return beta if math.isfinite(beta) else None


def _annualized_volatility(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    average = sum(returns) / len(returns)
    variance = sum((value - average) ** 2 for value in returns) / (
        len(returns) - 1
    )
    volatility = math.sqrt(max(0.0, variance)) * math.sqrt(252.0)
    return volatility if math.isfinite(volatility) else None


def _rank_book(
    bars: Mapping[str, Mapping[str, float]],
    dates: Sequence[str],
    index: int,
    feature: float | None,
) -> dict[str, float]:
    if feature is None or feature == 0.0 or index < MOMENTUM_SESSIONS:
        return {}
    today = dates[index]
    base_day = dates[index - MOMENTUM_SESSIONS]
    scores: list[tuple[str, float]] = []
    for code, values in bars.items():
        current = values.get(today)
        base = values.get(base_day)
        if current is not None and base is not None and base > 0:
            scores.append((code, current / base - 1.0))
    scores.sort(key=lambda row: (-row[1], row[0]))
    if len(scores) < 4:
        return {}
    n_long = max(1, math.floor(len(scores) * LONG_FRACTION))
    n_short = max(1, math.floor(len(scores) * SHORT_FRACTION))
    if n_long + n_short > len(scores):
        return {}
    # contango (front/next - 1 < 0) keeps momentum; front inversion reverses.
    direction = -1.0 if feature > 0.0 else 1.0
    book: dict[str, float] = {}
    for code, _score in scores[:n_long]:
        book[code] = direction * 0.5 / n_long
    for code, _score in scores[-n_short:]:
        book[code] = -direction * 0.5 / n_short
    return book


def _held_books_by_signal(
    bars: Mapping[str, Mapping[str, float]],
    dates: Sequence[str],
    features: Mapping[str, float | None],
) -> dict[str, dict[str, float]]:
    held_by_signal: dict[str, dict[str, float]] = {}
    held: dict[str, float] = {}
    remaining = 0
    for index, day in enumerate(dates):
        if remaining <= 0:
            held = _rank_book(bars, dates, index, features.get(day))
            remaining = HOLD_SESSIONS
        held_by_signal[day] = dict(held)
        remaining -= 1
    return held_by_signal


def _stock_interval_trace(
    bars: Mapping[str, Mapping[str, float]],
    dates: Sequence[str],
    features: Mapping[str, float | None],
    evaluation_dates: Sequence[str],
) -> list[dict[str, Any]]:
    allowed_evaluation = set(map(str, evaluation_dates))
    held_by_signal = _held_books_by_signal(bars, dates, features)
    trace: list[dict[str, Any]] = []
    for index in range(2, len(dates)):
        previous_day = dates[index - 1]
        current_day = dates[index]
        if current_day not in allowed_evaluation:
            continue
        signal_day = dates[index - 2]
        target_book = held_by_signal.get(signal_day, {})
        missing_target_codes = sorted(
            code
            for code in target_book
            if bars[code].get(previous_day) is None
            or bars[code].get(current_day) is None
        )
        stock_gross = (
            0.0
            if missing_target_codes
            else sum(
                weight
                * (bars[code][current_day] / bars[code][previous_day] - 1.0)
                for code, weight in target_book.items()
            )
        )
        trace.append(
            {
                "date": current_day,
                "previous_day": previous_day,
                "signal_date": signal_day,
                "target_book": target_book,
                "active_target": bool(target_book),
                "interval_status": (
                    "INCOMPLETE_TARGET_BOOK"
                    if missing_target_codes
                    else "COMPLETE"
                ),
                "missing_target_codes": missing_target_codes,
                "stock_gross_return": stock_gross,
            }
        )
    eligible_evaluation = allowed_evaluation.intersection(dates[2:])
    if len(trace) != len(eligible_evaluation):
        raise RuntimeError("evaluation calendar is not represented by the stock trace")
    return trace


def evaluate_fixed_strategy(
    panel: Mapping[str, Any],
    feature_rows: Sequence[Mapping[str, Any]],
    evaluation_dates: Sequence[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    bars = _normalize_bars(panel)
    dates = sorted({day for values in bars.values() for day in values})
    features = {
        str(row.get("date") or ""): _number(row.get(FEATURE_FIELD))
        if row.get("fit_success") is True
        else None
        for row in feature_rows
    }
    trace = _stock_interval_trace(bars, dates, features, evaluation_dates)

    equity = 1.0
    applied: dict[str, float] = {}
    curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    active_sessions = 0
    incomplete_active_intervals: list[str] = []
    missing_target_codes: set[str] = set()
    missing_target_leg_observations = 0
    for interval in trace:
        current_day = str(interval["date"])
        previous_day = str(interval["previous_day"])
        signal_day = str(interval["signal_date"])
        target = dict(interval["target_book"])
        missing = list(interval["missing_target_codes"])
        if missing:
            incomplete_active_intervals.append(current_day)
            missing_target_codes.update(map(str, missing))
            missing_target_leg_observations += len(missing)
            curve.append(
                {
                    "date": current_day,
                    "signal_date": signal_day,
                    "interval_status": "INCOMPLETE_TARGET_BOOK",
                    "missing_target_codes": missing,
                    "gross_return": 0.0,
                    "cost_return": 0.0,
                    "net_return": 0.0,
                    "turnover_one_way": 0.0,
                    "equity": equity,
                }
            )
            continue
        all_codes = sorted(set(applied) | set(target))
        turnover = 0.0
        equity_before = equity
        for code in all_codes:
            delta = target.get(code, 0.0) - applied.get(code, 0.0)
            if delta == 0.0:
                continue
            turnover_weight = abs(delta)
            turnover += turnover_weight
            notional = turnover_weight * equity_before
            trades.append(
                {
                    "date": previous_day,
                    "fill_date": previous_day,
                    "pnl_date": current_day,
                    "signal_date": signal_day,
                    "code": code,
                    "side": "buy" if delta > 0 else "sell",
                    "notional": notional,
                    "cost": notional * ONE_WAY_COST,
                }
            )
        gross = float(interval["stock_gross_return"])
        cost = turnover * ONE_WAY_COST
        net = gross - cost
        equity *= 1.0 + net
        if target:
            active_sessions += 1
        curve.append(
            {
                "date": current_day,
                "signal_date": signal_day,
                "interval_status": "COMPLETE",
                "missing_target_codes": [],
                "gross_return": gross,
                "cost_return": cost,
                "net_return": net,
                "turnover_one_way": turnover,
                "equity": equity,
            }
        )
        applied = dict(target)

    # Close the screening book at the final observed close so reported cost is
    # a full round trip rather than an uncharged open terminal position.
    terminal_liquidation_costed = bool(
        curve
        and applied
        and trace[-1]["interval_status"] == "COMPLETE"
    )
    if terminal_liquidation_costed:
        final_day = str(curve[-1]["date"])
        liquidation = sum(abs(weight) for weight in applied.values())
        liquidation_cost = liquidation * ONE_WAY_COST
        equity_before_last = (
            float(curve[-2]["equity"]) if len(curve) > 1 else 1.0
        )
        curve[-1]["cost_return"] = float(curve[-1]["cost_return"]) + liquidation_cost
        curve[-1]["net_return"] = float(curve[-1]["gross_return"]) - float(
            curve[-1]["cost_return"]
        )
        equity = equity_before_last * (1.0 + float(curve[-1]["net_return"]))
        curve[-1]["turnover_one_way"] = (
            float(curve[-1]["turnover_one_way"]) + liquidation
        )
        curve[-1]["equity"] = equity
        for code, weight in sorted(applied.items()):
            trades.append(
                {
                    "date": final_day,
                    "signal_date": None,
                    "code": code,
                    "side": "sell" if weight > 0 else "buy",
                    "notional": abs(weight) * equity_before_last,
                    "cost": abs(weight) * equity_before_last * ONE_WAY_COST,
                }
            )

    primary_status = (
        "INCOMPLETE"
        if incomplete_active_intervals
        else "EVALUATED"
        if active_sessions > 0
        else "NOT_EVALUATED"
    )
    performance = (
        summarize_performance(
            equity_curve=curve,
            trades=trades,
            starting_capital=1.0,
        )
        if primary_status == "EVALUATED"
        else None
    )
    performance_unavailable_reason = (
        "incomplete_active_target_intervals"
        if primary_status == "INCOMPLETE"
        else "no_active_stock_book_sessions"
        if primary_status == "NOT_EVALUATED"
        else None
    )
    diagnostics = {
        "status": primary_status,
        "performance_status": (
            "UNAVAILABLE" if performance is None else "AVAILABLE"
        ),
        "performance_unavailable_reason": performance_unavailable_reason,
        "panel_sessions": len(dates),
        "evaluation_sessions": len(curve),
        "calendar_sessions_dropped": len(trace) - len(curve),
        "active_target_sessions": sum(
            bool(interval["active_target"]) for interval in trace
        ),
        "active_sessions": active_sessions,
        "incomplete_active_interval_count": len(incomplete_active_intervals),
        "incomplete_active_intervals": incomplete_active_intervals,
        "missing_target_leg_observations": missing_target_leg_observations,
        "missing_target_codes_sample": sorted(missing_target_codes)[:20],
        "terminal_liquidation_costed": terminal_liquidation_costed,
        "feature_sessions": sum(features.get(day) is not None for day in dates),
        "fit_success_sessions": sum(
            row.get("fit_success") is True for row in feature_rows
        ),
        "fit_failure_sessions": sum(
            row.get("fit_success") is not True for row in feature_rows
        ),
    }
    return curve, trades, {"performance": performance, **diagnostics}, trace


def evaluate_topix_beta_hedged_comparison(
    panel: Mapping[str, Any],
    feature_rows: Sequence[Mapping[str, Any]],
    stock_interval_trace: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Add a non-executable TOPIX-index hedge comparison to the fixed result."""

    bars = _normalize_bars(panel)
    topix = _normalize_topix_proxy(panel)
    plans: list[dict[str, Any]] = []
    active_sessions = 0
    incomplete_active_intervals: list[str] = []
    beta_available_sessions = 0
    beta_unavailable_sessions = 0
    hedge_capped_sessions = 0

    for stock_interval in stock_interval_trace:
        current_day = str(stock_interval.get("date") or "")
        previous_day = str(stock_interval.get("previous_day") or "")
        signal_day = str(stock_interval.get("signal_date") or "")
        target_raw = stock_interval.get("target_book")
        missing_raw = stock_interval.get("missing_target_codes")
        if not isinstance(target_raw, Mapping) or not isinstance(missing_raw, list):
            raise RuntimeError("stock interval trace is invalid")
        target_book = {str(code): float(weight) for code, weight in target_raw.items()}
        missing_target_codes = sorted(map(str, missing_raw))
        expected_interval_status = (
            "INCOMPLETE_TARGET_BOOK"
            if missing_target_codes
            else "COMPLETE"
        )
        if stock_interval.get("interval_status") != expected_interval_status:
            raise RuntimeError("stock interval trace completeness mismatch")
        active = bool(target_book)
        if active:
            active_sessions += 1
        topix_before = topix.get(previous_day)
        topix_after = topix.get(current_day)
        if topix_before is None or topix_after is None or topix_before <= 0:
            raise RuntimeError("TOPIX index proxy return is unavailable")
        topix_return = topix_after / topix_before - 1.0
        missing_estimates = 0
        estimates: list[tuple[str, float, _BetaEstimate]] = []
        for code, weight in target_book.items():
            estimate = _estimate_beta_through(bars[code], topix, signal_day)
            if estimate is None:
                missing_estimates += 1
            else:
                estimates.append((code, weight, estimate))

        book_beta: float | None = None
        residual_beta: float | None = None
        estimate_end: str | None = None
        if missing_target_codes:
            beta_status = "INCOMPLETE_TARGET_BOOK"
            target_hedge = 0.0
            incomplete_active_intervals.append(current_day)
        elif not target_book:
            beta_status = "NO_ACTIVE_BOOK"
            target_hedge = 0.0
        elif missing_estimates:
            # Do not partially hedge a book whose beta is not fully observed.
            beta_status = "INSUFFICIENT_HISTORY"
            target_hedge = 0.0
            beta_unavailable_sessions += 1
        else:
            beta_status = "ESTIMATED"
            book_beta = sum(weight * estimate[0] for _, weight, estimate in estimates)
            unclipped_hedge = -book_beta
            target_hedge = max(
                -MAX_ABS_TOPIX_HEDGE_WEIGHT,
                min(MAX_ABS_TOPIX_HEDGE_WEIGHT, unclipped_hedge),
            )
            residual_beta = book_beta + target_hedge
            estimate_end = max(estimate[2] for _, _, estimate in estimates)
            if estimate_end > signal_day:
                raise RuntimeError("TOPIX beta estimate crossed the signal wall")
            beta_available_sessions += 1
            if target_hedge != unclipped_hedge:
                hedge_capped_sessions += 1

        plans.append(
            {
                "date": current_day,
                "signal_date": signal_day,
                "assumed_proxy_fill_date": previous_day,
                "target_book": target_book,
                "missing_target_codes": missing_target_codes,
                "stock_gross_return": float(stock_interval["stock_gross_return"]),
                "topix_proxy_return": topix_return,
                "estimated_stock_book_beta": book_beta,
                "target_topix_proxy_hedge_weight": target_hedge,
                "residual_beta_after_hedge": residual_beta,
                "beta_status": beta_status,
                "beta_window_last_return_date": estimate_end,
            }
        )

    beta_coverage_ratio = (
        None
        if active_sessions == 0
        else beta_available_sessions / active_sessions
    )
    beta_coverage_complete = (
        active_sessions > 0
        and not incomplete_active_intervals
        and beta_available_sessions == active_sessions
    )
    if incomplete_active_intervals:
        comparison_status = "INCOMPLETE"
        performance_unavailable_reason = "incomplete_active_target_intervals"
    elif active_sessions == 0:
        comparison_status = "NOT_EVALUATED"
        performance_unavailable_reason = "no_active_stock_book_sessions"
    elif beta_coverage_complete:
        comparison_status = "EVALUATED"
        performance_unavailable_reason = None
    elif beta_available_sessions:
        comparison_status = "PARTIAL"
        performance_unavailable_reason = "beta_did_not_cover_every_active_session"
    else:
        comparison_status = "UNAVAILABLE"
        performance_unavailable_reason = "beta_unavailable_for_all_active_sessions"

    path: list[dict[str, Any]] = []
    unhedged_gross_returns: list[float] = []
    hedged_gross_returns: list[float] = []
    topix_returns: list[float] = []
    stock_adjustment_count = 0
    stock_notional_amount = 0.0
    stock_cost_amount = 0.0
    proxy_adjustment_count = 0
    proxy_notional_amount = 0.0
    proxy_cost_amount = 0.0
    hedge_applied_sessions = 0
    terminal_stock_liquidation_cost = 0.0
    terminal_proxy_liquidation_cost = 0.0

    if incomplete_active_intervals:
        # A missing active leg makes the cumulative equity unknowable. Preserve
        # every source date for audit, but do not invent returns across the gap.
        path = [
            {
                **{key: value for key, value in plan.items() if key != "target_book"},
                "interval_status": (
                    "INCOMPLETE_TARGET_BOOK"
                    if plan["missing_target_codes"]
                    else "NOT_SIMULATED_INCOMPLETE_COMPARISON"
                ),
                "stock_book_gross_return": None,
                "topix_hedge_gross_return": None,
                "gross_return": None,
                "stock_cost_return": None,
                "topix_hedge_cost_return": None,
                "cost_return": None,
                "net_return": None,
                "stock_turnover_one_way": None,
                "topix_proxy_turnover_one_way": None,
                "turnover_one_way": None,
                "stock_adjustment_notional_amount": None,
                "topix_proxy_adjustment_notional_amount": None,
                "equity": None,
            }
            for plan in plans
        ]
    else:
        equity = 1.0
        applied_stock: dict[str, float] = {}
        applied_hedge = 0.0
        for plan in plans:
            current_day = str(plan["date"])
            previous_day = str(plan["assumed_proxy_fill_date"])
            target_book = dict(plan["target_book"])
            equity_before = equity

            stock_turnover = 0.0
            stock_interval_notional = 0.0
            for code in sorted(set(applied_stock) | set(target_book)):
                delta = target_book.get(code, 0.0) - applied_stock.get(code, 0.0)
                if delta == 0.0:
                    continue
                turnover_weight = abs(delta)
                stock_turnover += turnover_weight
                notional = turnover_weight * equity_before
                stock_interval_notional += notional
                stock_adjustment_count += 1
                stock_notional_amount += notional
                stock_cost_amount += notional * ONE_WAY_COST

            target_hedge = float(plan["target_topix_proxy_hedge_weight"])
            hedge_delta = target_hedge - applied_hedge
            hedge_turnover = abs(hedge_delta)
            proxy_interval_notional = hedge_turnover * equity_before
            if hedge_delta != 0.0:
                proxy_adjustment_count += 1
                proxy_notional_amount += proxy_interval_notional
                proxy_cost_amount += proxy_interval_notional * ONE_WAY_COST

            stock_gross = float(plan["stock_gross_return"])
            hedge_gross = target_hedge * float(plan["topix_proxy_return"])
            stock_cost = stock_turnover * ONE_WAY_COST
            hedge_cost = hedge_turnover * ONE_WAY_COST
            gross = stock_gross + hedge_gross
            cost = stock_cost + hedge_cost
            net = gross - cost
            if 1.0 + net <= 0.0:
                raise RuntimeError("TOPIX comparison exhausted screening capital")
            equity *= 1.0 + net
            unhedged_gross_returns.append(stock_gross)
            hedged_gross_returns.append(gross)
            topix_returns.append(float(plan["topix_proxy_return"]))
            if target_hedge != 0.0:
                hedge_applied_sessions += 1
            path.append(
                {
                    **{key: value for key, value in plan.items() if key != "target_book"},
                    "interval_status": "COMPLETE",
                    "stock_book_gross_return": stock_gross,
                    "topix_hedge_gross_return": hedge_gross,
                    "gross_return": gross,
                    "stock_cost_return": stock_cost,
                    "topix_hedge_cost_return": hedge_cost,
                    "cost_return": cost,
                    "net_return": net,
                    "stock_turnover_one_way": stock_turnover,
                    "topix_proxy_turnover_one_way": hedge_turnover,
                    "turnover_one_way": stock_turnover + hedge_turnover,
                    "stock_adjustment_notional_amount": stock_interval_notional,
                    "topix_proxy_adjustment_notional_amount": (
                        proxy_interval_notional
                    ),
                    "equity": equity,
                }
            )
            applied_stock = target_book
            applied_hedge = target_hedge

        if path and (applied_stock or applied_hedge != 0.0):
            equity_before_last = (
                float(path[-2]["equity"]) if len(path) > 1 else 1.0
            )
            stock_liquidation = sum(abs(weight) for weight in applied_stock.values())
            proxy_liquidation = abs(applied_hedge)
            terminal_stock_liquidation_cost = stock_liquidation * ONE_WAY_COST
            terminal_proxy_liquidation_cost = proxy_liquidation * ONE_WAY_COST
            stock_terminal_notional = stock_liquidation * equity_before_last
            proxy_terminal_notional = proxy_liquidation * equity_before_last
            stock_adjustment_count += len(applied_stock)
            stock_notional_amount += stock_terminal_notional
            stock_cost_amount += stock_terminal_notional * ONE_WAY_COST
            if applied_hedge != 0.0:
                proxy_adjustment_count += 1
                proxy_notional_amount += proxy_terminal_notional
                proxy_cost_amount += proxy_terminal_notional * ONE_WAY_COST
            path[-1]["stock_cost_return"] = (
                float(path[-1]["stock_cost_return"])
                + terminal_stock_liquidation_cost
            )
            path[-1]["topix_hedge_cost_return"] = (
                float(path[-1]["topix_hedge_cost_return"])
                + terminal_proxy_liquidation_cost
            )
            path[-1]["cost_return"] = (
                float(path[-1]["cost_return"])
                + terminal_stock_liquidation_cost
                + terminal_proxy_liquidation_cost
            )
            path[-1]["net_return"] = float(path[-1]["gross_return"]) - float(
                path[-1]["cost_return"]
            )
            path[-1]["stock_turnover_one_way"] = (
                float(path[-1]["stock_turnover_one_way"]) + stock_liquidation
            )
            path[-1]["topix_proxy_turnover_one_way"] = (
                float(path[-1]["topix_proxy_turnover_one_way"])
                + proxy_liquidation
            )
            path[-1]["turnover_one_way"] = (
                float(path[-1]["turnover_one_way"])
                + stock_liquidation
                + proxy_liquidation
            )
            path[-1]["stock_adjustment_notional_amount"] = (
                float(path[-1]["stock_adjustment_notional_amount"])
                + stock_terminal_notional
            )
            path[-1]["topix_proxy_adjustment_notional_amount"] = (
                float(path[-1]["topix_proxy_adjustment_notional_amount"])
                + proxy_terminal_notional
            )
            path[-1]["equity"] = equity_before_last * (
                1.0 + float(path[-1]["net_return"])
            )

    performance: dict[str, Any] | None = None
    if comparison_status == "EVALUATED":
        combined_notional = stock_notional_amount + proxy_notional_amount
        combined_cost = stock_cost_amount + proxy_cost_amount
        performance = summarize_performance(
            equity_curve=path,
            trades=[
                {
                    "side": "buy",
                    "notional": combined_notional,
                    "cost": combined_cost,
                }
            ]
            if combined_notional
            else [],
            starting_capital=1.0,
        )
        # Proxy adjustments affect the hypothetical cost path but are not fills.
        performance["fill_count"] = stock_adjustment_count
        performance["fill_count_basis"] = (
            "comparison_stock_fills_only; TOPIX proxy adjustments excluded"
        )
        performance["turnover_one_way_basis"] = (
            "comparison stock plus hypothetical TOPIX proxy adjustments"
        )

    stock_accounting = {
        "adjustment_count": stock_adjustment_count,
        "notional_amount": stock_notional_amount,
        "cost_amount": stock_cost_amount,
    }
    proxy_accounting = {
        "adjustment_count": proxy_adjustment_count,
        "notional_amount": proxy_notional_amount,
        "cost_amount": proxy_cost_amount,
    }
    combined_accounting = {
        "adjustment_count": (
            stock_accounting["adjustment_count"]
            + proxy_accounting["adjustment_count"]
        ),
        "notional_amount": (
            stock_accounting["notional_amount"]
            + proxy_accounting["notional_amount"]
        ),
        "cost_amount": (
            stock_accounting["cost_amount"] + proxy_accounting["cost_amount"]
        ),
    }
    comparison_metrics_available = comparison_status == "EVALUATED"
    unhedged_volatility = (
        _annualized_volatility(unhedged_gross_returns)
        if comparison_metrics_available
        else None
    )
    residual_volatility = (
        _annualized_volatility(hedged_gross_returns)
        if comparison_metrics_available
        else None
    )
    observed_features = [
        value
        for row in feature_rows
        if row.get("fit_success") is True
        and (value := _number(row.get(FEATURE_FIELD))) is not None
    ]
    return {
        "status": comparison_status,
        "comparison_only": True,
        "instrument": {
            "panel_storage_alias": TOPIX_PROXY_PANEL_CODE,
            "identity": "TOPIX_cash_index_close",
            "dataset": TOPIX_PROXY_DATASET,
            "etf_approximation": "1306_TOPIX_ETF_only",
            "etf_price_or_fill_used": False,
            "execution_claim": False,
        },
        "beta_model": {
            "estimator": "cov(stock_return,TOPIX_return)/var(TOPIX_return)",
            "lookback_return_observations": BETA_LOOKBACK_SESSIONS,
            "minimum_return_observations": BETA_MIN_OBSERVATIONS,
            "information_wall": "all_returns_end_on_or_before_signal_close_d",
            "decision_timing": "close_d",
            "proxy_assumed_fill_timing": "close_d_plus_1",
            "first_proxy_pnl_interval": "close_d_plus_1_to_close_d_plus_2",
            "maximum_absolute_hedge_weight": MAX_ABS_TOPIX_HEDGE_WEIGHT,
            "incomplete_book_policy": (
                "performance_unavailable_preserve_calendar_no_partial_beta_"
                "extrapolation"
            ),
            "coverage_policy": "every_active_session_must_have_complete_beta",
        },
        "performance": performance,
        "performance_status": (
            "AVAILABLE" if performance is not None else "UNAVAILABLE"
        ),
        "performance_unavailable_reason": performance_unavailable_reason,
        "beta_and_residual_volatility": {
            "status": (
                "AVAILABLE" if comparison_metrics_available else "UNAVAILABLE"
            ),
            "realized_unhedged_beta_to_topix": (
                _realized_beta(unhedged_gross_returns, topix_returns)
                if comparison_metrics_available
                else None
            ),
            "realized_hedged_beta_to_topix": (
                _realized_beta(hedged_gross_returns, topix_returns)
                if comparison_metrics_available
                else None
            ),
            "unhedged_gross_annualized_volatility": unhedged_volatility,
            "topix_hedged_gross_residual_annualized_volatility": residual_volatility,
        },
        "hedge_tracking": {
            "source_path_sessions": len(stock_interval_trace),
            "comparison_calendar_sessions": len(path),
            "calendar_sessions_dropped": len(stock_interval_trace) - len(path),
            "return_path_sessions": (
                len(path) if not incomplete_active_intervals else 0
            ),
            "active_sessions": active_sessions,
            "incomplete_active_interval_count": len(incomplete_active_intervals),
            "incomplete_active_intervals": incomplete_active_intervals,
            "beta_available_sessions": beta_available_sessions,
            "beta_unavailable_active_sessions": beta_unavailable_sessions,
            "beta_coverage_ratio_of_active_sessions": beta_coverage_ratio,
            "beta_coverage_complete": beta_coverage_complete,
            "hedge_applied_sessions": hedge_applied_sessions,
            "hedge_capped_sessions": hedge_capped_sessions,
            "maximum_absolute_hedge_weight_observed": max(
                (
                    abs(float(row["target_topix_proxy_hedge_weight"]))
                    for row in plans
                ),
                default=0.0,
            ),
            "terminal_stock_liquidation_costed": (
                terminal_stock_liquidation_cost > 0.0
            ),
            "terminal_proxy_liquidation_costed": (
                terminal_proxy_liquidation_cost > 0.0
            ),
        },
        "comparison_stock_accounting": stock_accounting,
        "hypothetical_topix_proxy_accounting": {
            **proxy_accounting,
            "execution_claim": False,
            "included_in_performance_fill_count": False,
        },
        "combined_comparison_accounting": combined_accounting,
        "signal_branch_coverage": {
            "contango_sessions": sum(value < 0.0 for value in observed_features),
            "front_inversion_sessions": sum(value > 0.0 for value in observed_features),
            "single_branch_limitation": not (
                any(value < 0.0 for value in observed_features)
                and any(value > 0.0 for value in observed_features)
            ),
        },
        "daily_path": path,
        "individual_stock_option_volatility_used": False,
        "volatility_signal_scope": "nikkei_225_index_options",
        "draft_only": True,
        "screening_only": True,
        "ready": False,
        "mass": False,
        "promotion": False,
        "live_orders": False,
        "go": False,
        "not_a_pass": True,
    }


def _put_bytes(
    spec: PersonalSvi2023JobSpec,
    key: str,
    data: bytes,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    if not 0 < len(data) <= MAX_OUTPUT_BYTES:
        raise RuntimeError("SVI output size out of bounds")
    digest = _sha256(data)
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        data=data,
        method="PUT",
        headers={
            **spec.headers(),
            "content-length": str(len(data)),
            "x-content-sha256": digest,
        },
    )
    with opener(request, timeout=300) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"SVI output upload returned {response.status}")
    return digest


def _safe_detail(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


def execute_svi_job(
    spec: PersonalSvi2023JobSpec,
    *,
    input_opener: OpenInput = _open_input,
    uploader: Callable[[PersonalSvi2023JobSpec, str, bytes], str] = _put_bytes,
) -> dict[str, Any]:
    try:
        manifest = load_input_manifest(spec, opener=input_opener)
        panel = load_panel(spec, manifest, opener=input_opener)
        feature_rows = build_feature_sidecar(
            spec,
            manifest,
            opener=input_opener,
        )
        evaluation_dates = manifest["sessions"]["evaluation_dates"]
        curve, trades, evaluation, stock_interval_trace = evaluate_fixed_strategy(
            panel,
            feature_rows,
            evaluation_dates,
        )
        topix_beta_hedged_comparison = evaluate_topix_beta_hedged_comparison(
            panel,
            feature_rows,
            stock_interval_trace,
        )
        feature_bytes = b"".join(
            _canonical_bytes(row) + b"\n" for row in feature_rows
        )
        feature_digest = uploader(spec, spec.feature_key, feature_bytes)
        report = {
            "schema_version": "personal-svi-2023-report/v4",
            "job_id": spec.job_id,
            "cohort_id": COHORT_ID,
            "strategy_id": STRATEGY_ID,
            "runner_version": RUNNER_VERSION,
            "input_manifest_key": spec.input_manifest_key,
            "input_manifest_digest": spec.input_manifest_digest,
            "feature_key": spec.feature_key,
            "feature_sha256": feature_digest,
            "feature_definition": {
                "field": FEATURE_FIELD,
                "normalization": "front_SVI_ATM_IV/next_SVI_ATM_IV-1",
                "moneyness_proxy": "ln(strike/UnderPx); UnderPx is not a forward",
                "thesis": (
                    "Maintain cross-sectional momentum when the fitted ATM term "
                    "ratio is below zero; reverse it during front inversion, where "
                    "near-term stress is expected to disrupt leadership."
                ),
                "return_source": (
                    "Equity cross-sectional trend/reversal conditional on a normalized "
                    "Nikkei 225 option-smile term signal, not option-premium P&L."
                ),
                "works_when": (
                    "SVI fits are stable and front-end inversion precedes equity factor "
                    "reversal while contango accompanies persistent leadership."
                ),
                "fails_when": (
                    "Sparse/noisy strikes reject the fit, expiry effects dominate the "
                    "term ratio, or index-option stress does not transmit to the panel."
                ),
            },
            "equity_universe": EQUITY_UNIVERSE,
            "temporal_contract": manifest["temporal_contract"],
            "input_summary": {
                "panel_key": PANEL_KEY,
                "option_object_count": manifest["options"].get("object_count"),
                "option_total_bytes": manifest["options"].get("total_bytes"),
                "option_day_count": len(manifest["options"]["days"]),
            },
            "execution": {
                "signal_lag_sessions": 1,
                "execution_timing": "signal_close_d_fill_close_d_plus_1",
                "first_return_timing": "close_d_plus_1_to_close_d_plus_2",
                "hold_sessions": HOLD_SESSIONS,
                "one_way_cost": ONE_WAY_COST,
                "terminal_liquidation_costed": evaluation[
                    "terminal_liquidation_costed"
                ],
                "short_borrow_and_financing": "not_modelled_screening_limitation",
                "market_neutrality": (
                    "dollar_balanced_rank_long_short_not_beta_neutral"
                ),
                "index_etf_hedge": (
                    "not_applied_to_primary_result; paired_TOPIX_index_proxy_"
                    "comparison_is_1306_approximation_only"
                ),
                "individual_stock_option_volatility_used": False,
                "volatility_signal_scope": "nikkei_225_index_options",
                "momentum_sessions": MOMENTUM_SESSIONS,
                "long_fraction": LONG_FRACTION,
                "short_fraction": SHORT_FRACTION,
            },
            "period": {
                "fixed_panel_key": PANEL_KEY,
                "warmup_dates": manifest["sessions"]["warmup_dates"],
                "evaluation_dates": evaluation_dates,
            },
            "evaluation": evaluation,
            "topix_beta_hedged_comparison": topix_beta_hedged_comparison,
            "daily_path": curve,
            "fills": trades,
            "candidate_status": evaluation["status"],
            "draft_only": True,
            "screening_only": True,
            "ready": False,
            "mass": False,
            "promotion": False,
            "live_orders": False,
            "go": False,
            "not_a_pass": True,
        }
        report_bytes = _canonical_bytes(report)
        report_digest = uploader(spec, spec.report_key, report_bytes)
        terminal = {
            "schema_version": "personal-svi-2023-manifest/v2",
            "status": "COMPLETED",
            "job_id": spec.job_id,
            "cohort_id": COHORT_ID,
            "strategy_id": STRATEGY_ID,
            "runner_version": RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "input_manifest_key": spec.input_manifest_key,
            "input_manifest_digest": spec.input_manifest_digest,
            "feature_key": spec.feature_key,
            "feature_sha256": feature_digest,
            "report_key": spec.report_key,
            "report_sha256": report_digest,
            "candidate_status": report["candidate_status"],
            "draft_only": True,
            "screening_only": True,
            "ready": False,
            "mass": False,
            "promotion": False,
            "live_orders": False,
            "go": False,
            "not_a_pass": True,
        }
    except Exception as error:
        terminal = {
            "schema_version": "personal-svi-2023-manifest/v2",
            "status": "FAILED",
            "job_id": spec.job_id,
            "cohort_id": COHORT_ID,
            "strategy_id": STRATEGY_ID,
            "runner_version": RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "input_manifest_key": spec.input_manifest_key,
            "input_manifest_digest": spec.input_manifest_digest,
            "error": _safe_detail(error),
            "draft_only": True,
            "screening_only": True,
            "ready": False,
            "mass": False,
            "promotion": False,
            "live_orders": False,
            "go": False,
            "not_a_pass": True,
        }
    terminal_bytes = _canonical_bytes(terminal)
    uploader(spec, spec.manifest_key, terminal_bytes)
    return terminal


__all__ = [
    "PersonalSvi2023JobSpec",
    "SviJobInputError",
    "build_feature_sidecar",
    "evaluate_fixed_strategy",
    "evaluate_topix_beta_hedged_comparison",
    "execute_svi_job",
    "load_one_options_day",
]
