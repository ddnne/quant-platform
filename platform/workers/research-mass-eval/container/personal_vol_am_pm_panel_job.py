"""Governed N225 vol-ratio AM/PM panel writer on the existing v13 runner."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sqlite3
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Sequence

from research.eval_universe import (
    EVAL_UNIVERSE_POOL,
    UNIVERSE_MIN_BAR_DAYS,
    UNIVERSE_MIN_FINS_EQAR,
    UNIVERSE_MIN_FINS_TA,
    rank_eval_codes,
)
from research.fins_summary_keys import FINS_SUMMARY_EQAR_KEY, FINS_SUMMARY_TA_KEY

R2_ORIGIN = "http://research.r2"
PRODUCER_ID = "personal-vol-ratio-am-pm-panel-writer/v1"
COHORT_ID = "personal-vol-ratio-am-pm-v1"
RUNNER_VERSION = "personal-cloud-runner/v13"
INPUT_SCHEMA = "personal-vol-ratio-am-pm-panel-writer-input/v1"
MANIFEST_SCHEMA = "personal-vol-ratio-am-pm-panel-writer-manifest/v1"
PANEL_SCHEMA = "personal-vol-ratio-am-pm-panel/v1"
COMMON_VALID_SCHEMA = "personal-vol-ratio-am-pm-common-valid/v1"
MEMBERSHIP_SCHEMA = "personal-vol-ratio-am-pm-membership/v1"
SESSION_DATES_SCHEMA = "ordered-trading-session-dates/v1"
OPTION_DATASET = "derivatives_bars_daily_options_225"
SUPPORTED_OPTION_VERSIONS = (
    "research-options-225-vol-series/v1.2",
    "research-options-225-vol-series/v1.3",
)
INDIVIDUAL_STOCK_DATASETS = frozenset(
    {
        "derivatives_bars_daily_options_equity",
        "derivatives_bars_daily_single_stock_options",
        "equity_option_iv",
        "individual_stock_iv",
        "single_stock_option",
    }
)
INDIVIDUAL_STOCK_MAP_KEYS = frozenset({"by_code"})
REQUIRED_LOOKBACK = 61
IV_AVAILABLE_FROM = "2016-07-19"
SELECTION_START = "2019-01-01"
SELECTION_END = "2019-10-21"
EVALUATION_PERIODS = (
    {
        "period_id": "y2021_full",
        "year": 2021,
        "period_start": "2021-01-04",
        "period_end": "2021-10-15",
    },
    {
        "period_id": "y2023_full",
        "year": 2023,
        "period_start": "2023-01-04",
        "period_end": "2023-10-13",
    },
    {
        "period_id": "y2025_q4",
        "year": 2025,
        "period_start": "2025-09-01",
        "period_end": "2025-12-29",
    },
)
SESSION_CALENDAR_IDENTITY = {
    "dataset": "markets_calendar",
    "source": "jquants_premium_core",
    "upstream_locator": "/v2/markets/calendar",
    "policy_version": "source-capability/v3",
    "holiday_division": "1",
    "holiday_division_meaning": "trading_session",
    "dates_digest_schema": SESSION_DATES_SCHEMA,
    "role": "canonical_jquants_trading_session_calendar",
    "predecessor_rule": "previous_element_of_pinned_ordered_dates",
}
TEMPORAL_CONTRACT = {
    "non_price_cutoff_jst": "11:30:00+09:00",
    "am_equity_admission_jst": "12:30:00+09:00",
    "am_equity_admission_widens_non_price_cutoff": False,
    "option_observations_asof": "native_session",
    "signal_option_lag_sessions": 1,
    "equity_cross_section": "D_MAdjC_with_prior_history",
    "order_sizing_price": "D_MAdjC",
    "fill": "D_AAdjC",
    "eod_valuation": "D_AAdjC",
    "first_pnl": "D_AAdjC_to_next_AAdjC",
    "no_adjc_fallback": True,
    "no_ffill": True,
    "no_signal_date_option_values": True,
}
MAX_INPUT_BYTES = 512 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_LEGACY_PANEL_BYTES = 64 * 1024 * 1024
# Fixed <=100-code membership, three fixed evaluation windows, and index-level
# option maps: 100 codes * ~320 sessions * compact AM/PM bars stay well under
# 8 MiB. Keep the child bound there rather than the unused 64 MiB ceiling.
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
OPTION_REBUILD_ERROR = "immutable raw option evidence must be rebuilt"
COMMON_VALID_REASONS = (
    "predecessor_session_missing",
    "d_minus_1_basevol_missing",
    "d_minus_1_atm_iv_missing",
    "d_minus_1_skew_missing",
    "d_minus_1_cm_term_ratio_missing",
    "equity_universe_empty",
    "missing_MAdjC",
    "missing_AAdjC",
    "missing_next_AAdjC",
    "next_session_missing",
)

_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SNAPSHOT_RE = re.compile(
    r"^research/personal/snapshots/sha256=([0-9a-f]{64})\.sqlite\.gz$"
)


class VolPanelJobInputError(ValueError):
    """The Worker supplied a non-closed panel-writer job document."""


def _canonical_bytes(value: Mapping[str, Any] | Sequence[Any] | Any) -> bytes:
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
    return f"research/personal/vol-ratio-am-pm-v1/panel-builds/job={job_id}"


def _object_key(digest: str) -> str:
    if _DIGEST_RE.fullmatch(digest) is None:
        raise RuntimeError("content-addressed digest is invalid")
    return f"research/personal/vol-ratio-am-pm-v1/objects/{digest}.json"


@dataclass(frozen=True, slots=True)
class PersonalVolAmPmPanelJobSpec:
    cohort_id: str
    input_manifest_digest: str
    input_manifest_key: str
    job_id: str
    manifest_key: str
    producer_id: str
    request_digest: str
    runner_version: str

    @property
    def cohort_digest(self) -> str:
        return _sha256(
            _canonical_bytes(
                {
                    "cohort_id": COHORT_ID,
                    "producer_id": PRODUCER_ID,
                    "runner_version": RUNNER_VERSION,
                }
            )
        )

    @classmethod
    def from_document(cls, document: Any) -> "PersonalVolAmPmPanelJobSpec":
        fields = {
            "cohort_id",
            "input_manifest_digest",
            "input_manifest_key",
            "job_id",
            "manifest_key",
            "producer_id",
            "request_digest",
            "runner_version",
        }
        if not isinstance(document, dict) or set(document) != fields:
            raise VolPanelJobInputError("vol panel job fields are closed")
        if not all(isinstance(document[field], str) for field in fields):
            raise VolPanelJobInputError("vol panel job fields must be strings")
        spec = cls(**{field: document[field] for field in fields})
        spec.validate()
        return spec

    def validate(self) -> None:
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise VolPanelJobInputError("job_id is invalid")
        if (
            self.cohort_id != COHORT_ID
            or self.producer_id != PRODUCER_ID
            or self.runner_version != RUNNER_VERSION
        ):
            raise VolPanelJobInputError("fixed vol panel identity mismatch")
        if _DIGEST_RE.fullmatch(self.input_manifest_digest) is None:
            raise VolPanelJobInputError("input manifest digest is invalid")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise VolPanelJobInputError("request digest is invalid")
        prefix = _prefix(self.job_id)
        if self.input_manifest_key != f"{prefix}/input-manifest.json":
            raise VolPanelJobInputError("input_manifest_key mismatch")
        if self.manifest_key != f"{prefix}/manifest.json":
            raise VolPanelJobInputError("manifest_key mismatch")

    def headers(self) -> dict[str, str]:
        return {
            "x-vol-panel-job-id": self.job_id,
            "x-vol-panel-input-manifest-key": self.input_manifest_key,
            "x-vol-panel-input-manifest-digest": self.input_manifest_digest,
        }


def _request_digest_from_manifest(spec: PersonalVolAmPmPanelJobSpec, manifest: Mapping[str, Any]) -> str:
    selection = manifest["selection"]
    periods = manifest["periods"]
    period_ids = {
        row["period_id"]: periods[row["period_id"]]["job_id"]
        for row in EVALUATION_PERIODS
    }
    producer = manifest.get("sidecar_producer")
    producer_job_id = (
        producer.get("job_id") if isinstance(producer, Mapping) else None
    )
    payload: dict[str, Any] = {
        "input_manifest_digest": spec.input_manifest_digest,
        "input_manifest_key": spec.input_manifest_key,
        "job_id": spec.job_id,
        "period_snapshot_job_ids": period_ids,
        "producer_id": PRODUCER_ID,
        "runner_version": RUNNER_VERSION,
        "selection_snapshot_job_id": selection["job_id"],
        "sidecar_producer_job_id": producer_job_id,
    }
    return _sha256(_canonical_bytes(payload))


def _open_input(spec: PersonalVolAmPmPanelJobSpec, key: str, *, timeout: float = 120):
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


def _put_bytes(
    spec: PersonalVolAmPmPanelJobSpec,
    key: str,
    data: bytes,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    if not 0 < len(data) <= MAX_OUTPUT_BYTES:
        raise RuntimeError("vol panel output size out of bounds")
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
            raise RuntimeError(f"vol panel output upload returned {response.status}")
    return digest


def _safe_detail(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:800]


def _download_to_path(
    spec: PersonalVolAmPmPanelJobSpec,
    key: str,
    destination: Path,
    *,
    maximum: int,
    opener: Callable,
    expected_digest: str | None = None,
) -> str:
    response = opener(spec, key)
    with response:
        declared = response.headers.get("content-length", "")
        if not declared.isdigit() or not 0 < int(declared) <= maximum:
            raise RuntimeError("snapshot content length missing or out of bounds")
        expected = int(declared)
        digest = hashlib.sha256()
        received = 0
        with destination.open("xb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > expected:
                    raise RuntimeError("snapshot exceeded declared size")
                digest.update(chunk)
                handle.write(chunk)
        if received != expected:
            raise RuntimeError("snapshot content length mismatch")
        hex_digest = "sha256:" + digest.hexdigest()
        if expected_digest is not None and hex_digest != expected_digest:
            raise RuntimeError("snapshot gzip digest mismatch")
        return hex_digest


def _expand_gzip(transport: Path, destination: Path, raw_digest: str) -> None:
    digest = hashlib.sha256()
    expanded = 0
    with gzip.open(transport, "rb") as source, destination.open("xb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            expanded += len(chunk)
            if expanded > MAX_SNAPSHOT_BYTES:
                raise RuntimeError("expanded snapshot exceeded size bound")
            digest.update(chunk)
            output.write(chunk)
    if expanded < 1 or "sha256:" + digest.hexdigest() != raw_digest:
        raise RuntimeError("expanded snapshot raw digest mismatch")


def _open_sqlite(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    rows = connection.execute("PRAGMA quick_check").fetchall()
    if [tuple(row) for row in rows] != [("ok",)]:
        connection.close()
        raise RuntimeError("SQLite quick_check failed")
    connection.row_factory = sqlite3.Row
    return connection


def _require_v4_manifest(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute(
            "SELECT format FROM personal_history_manifest WHERE singleton=1"
        ).fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError("v4 snapshot manifest is missing") from exc
    if row is None or str(row["format"]) != "personal-draft-history/v4":
        raise RuntimeError("snapshot is not personal-draft-history/v4")


def _calendar_from_snapshot(
    connection: sqlite3.Connection,
) -> tuple[list[str], dict[str, Any]]:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(jquants_daily_bars)")
    }
    if "morning_adjustment_close" not in columns or "afternoon_adjustment_close" not in columns:
        raise RuntimeError("typed M/A columns are missing from jquants_daily_bars")
    try:
        checkpoints = [
            dict(row)
            for row in connection.execute(
                """
                SELECT dataset,segment_id,state,facts_digest,response_digest,
                       query_start,query_end
                FROM personal_history_segments
                WHERE dataset='markets_calendar'
                ORDER BY segment_id
                """
            )
        ]
    except sqlite3.Error as exc:
        raise RuntimeError("markets_calendar checkpoint evidence is missing") from exc
    if not checkpoints:
        raise RuntimeError("markets_calendar checkpoint evidence is missing")
    if any(str(row.get("state") or "") not in {"OBSERVED", "OBSERVED_EMPTY"} for row in checkpoints):
        raise RuntimeError("markets_calendar checkpoint is not observed")
    facts: list[dict[str, str]] = []
    trading: list[str] = []
    for row in connection.execute(
        """
        SELECT event_time, payload FROM jquants_records
        WHERE source='jquants' AND dataset='markets_calendar'
        ORDER BY event_time
        """
    ):
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("markets_calendar facts are invalid") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("markets_calendar facts are invalid")
        day = str(payload.get("Date") or str(row["event_time"] or "")[:10])
        holiday = str(payload.get("HolidayDivision") or payload.get("HolDiv") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise RuntimeError("markets_calendar fact date is invalid")
        facts.append({"Date": day, "HolidayDivision": holiday})
        if holiday == "1":
            trading.append(day)
    trading = sorted(set(trading))
    if not trading:
        raise RuntimeError("markets_calendar has no observed trading sessions")
    facts_digest = _sha256(_canonical_bytes({"facts": facts}))
    dates_digest = _sha256(
        json.dumps(
            {
                "ordered_session_dates": trading,
                "schema_version": SESSION_DATES_SCHEMA,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return trading, {
        "facts_digest": facts_digest,
        "dates_digest": dates_digest,
        "checkpoints": [
            {
                "segment_id": row["segment_id"],
                "state": row["state"],
                "facts_digest": row["facts_digest"],
                "response_digest": row["response_digest"],
                "query_start": row["query_start"],
                "query_end": row["query_end"],
            }
            for row in checkpoints
        ],
    }


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 0 and number == number:
        return number
    return None


def _select_2019_membership(connection: sqlite3.Connection) -> list[str]:
    pool = list(EVAL_UNIVERSE_POOL)
    scored: list[dict[str, Any]] = []
    for code in pool:
        bars = connection.execute(
            """
            SELECT date, close, volume, turnover_value
            FROM jquants_daily_bars
            WHERE source='jquants' AND code=? AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (code, SELECTION_START, SELECTION_END),
        ).fetchall()
        adv_vals: list[float] = []
        for row in bars:
            turnover = _positive(row["turnover_value"])
            if turnover is not None:
                adv_vals.append(turnover)
                continue
            volume = _positive(row["volume"])
            close = _positive(row["close"])
            if volume is not None and close is not None:
                adv_vals.append(volume * close)
        n_ta = 0
        n_eqar = 0
        for row in connection.execute(
            """
            SELECT payload FROM jquants_records
            WHERE source='jquants' AND dataset='fins_summary'
              AND json_extract(payload,'$.Code')=?
            """,
            (code,),
        ):
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            disc = str(payload.get("DiscDate") or payload.get("DisclosedDate") or "")[:10]
            if disc < SELECTION_START or disc > SELECTION_END:
                continue
            if _positive(payload.get(FINS_SUMMARY_TA_KEY)) is not None:
                n_ta += 1
            if _positive(payload.get(FINS_SUMMARY_EQAR_KEY)) is not None:
                n_eqar += 1
        scored.append(
            {
                "code": code,
                "adv": (sum(adv_vals) / len(adv_vals)) if adv_vals else 0.0,
                "n_bars": len(bars),
                "n_ta": n_ta,
                "n_eqar": n_eqar,
            }
        )
    selected = rank_eval_codes(
        scored,
        max_codes=100,
        min_bar_days=UNIVERSE_MIN_BAR_DAYS,
        min_fins_ta=UNIVERSE_MIN_FINS_TA,
        min_fins_eqar=UNIVERSE_MIN_FINS_EQAR,
    )
    if not selected:
        raise RuntimeError("frozen 2019 ADV100 membership is empty")
    return selected


def _bars_for_codes(
    connection: sqlite3.Connection,
    codes: Sequence[str],
    dates: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    wanted = set(dates)
    out: dict[str, list[dict[str, Any]]] = {code: [] for code in codes}
    placeholders = ",".join("?" for _ in codes)
    rows = connection.execute(
        f"""
        SELECT code, date, morning_adjustment_close, afternoon_adjustment_close
        FROM jquants_daily_bars
        WHERE source='jquants' AND code IN ({placeholders})
        ORDER BY code, date
        """,
        tuple(codes),
    )
    for row in rows:
        day = str(row["date"])
        if day not in wanted:
            continue
        morning = _positive(row["morning_adjustment_close"])
        afternoon = _positive(row["afternoon_adjustment_close"])
        if morning is None and afternoon is None:
            continue
        out[str(row["code"])].append(
            {"date": day, "MAdjC": morning, "AAdjC": afternoon}
        )
    for code in out:
        out[code].sort(key=lambda item: item["date"])
    return out


def _finite_map(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed == parsed:
            out[str(key)[:10]] = parsed
    return out


def _contains_individual_stock_maps(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if key in INDIVIDUAL_STOCK_MAP_KEYS and isinstance(item, dict):
            return True
        if isinstance(item, dict) and _contains_individual_stock_maps(item):
            return True
    return False


def _extract_opt225_regime(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or "opt225_regime" not in raw:
        raise RuntimeError(OPTION_REBUILD_ERROR)
    bundle = raw["opt225_regime"]
    if not isinstance(bundle, dict):
        raise RuntimeError(OPTION_REBUILD_ERROR)
    nested_source = bundle.get("source")
    if isinstance(nested_source, dict):
        dataset = nested_source.get("dataset")
        version = nested_source.get("version")
    else:
        dataset = bundle.get("dataset")
        version = bundle.get("version")
    if dataset in INDIVIDUAL_STOCK_DATASETS:
        raise RuntimeError(OPTION_REBUILD_ERROR)
    if dataset != OPTION_DATASET or version not in SUPPORTED_OPTION_VERSIONS:
        raise RuntimeError(OPTION_REBUILD_ERROR)
    if _contains_individual_stock_maps(bundle):
        raise RuntimeError(OPTION_REBUILD_ERROR)
    extracted: dict[str, Any] = {"source": {"dataset": dataset, "version": version}}
    for field in ("basevol", "atm_iv", "skew"):
        series = bundle.get(field)
        if not isinstance(series, dict):
            raise RuntimeError(OPTION_REBUILD_ERROR)
        short = _finite_map(series.get("rv_short_by_date"))
        long = _finite_map(series.get("rv_long_by_date"))
        if not short or not long:
            raise RuntimeError(OPTION_REBUILD_ERROR)
        extracted[field] = {
            "rv_short_by_date": short,
            "rv_long_by_date": long,
        }
    cm = bundle.get("cm_term_ratio")
    if not isinstance(cm, dict):
        raise RuntimeError(OPTION_REBUILD_ERROR)
    absolute = _finite_map(cm.get("rv_abs_by_date"))
    if not absolute:
        raise RuntimeError(OPTION_REBUILD_ERROR)
    extracted["cm_term_ratio"] = {"rv_abs_by_date": absolute}
    return extracted


def _lookup(series: Mapping[str, Any] | None, date_value: str, field: str) -> float | None:
    if not isinstance(series, dict):
        return None
    raw = series.get(field)
    if not isinstance(raw, dict):
        return None
    value = raw.get(date_value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _rolling_ok(series: Mapping[str, Any] | None, date_value: str) -> bool:
    short = _lookup(series, date_value, "rv_short_by_date")
    long = _lookup(series, date_value, "rv_long_by_date")
    return short is not None and long is not None and long > 1e-12


def _common_valid_rows(
    dates: Sequence[str],
    codes: Sequence[str],
    bars: Mapping[str, Sequence[Mapping[str, Any]]],
    opt225: Mapping[str, Any],
) -> list[dict[str, Any]]:
    morning: dict[str, dict[str, float]] = {code: {} for code in codes}
    afternoon: dict[str, dict[str, float]] = {code: {} for code in codes}
    for code in codes:
        for point in bars.get(code) or []:
            day = str(point.get("date") or "")
            m_value = _positive(point.get("MAdjC"))
            a_value = _positive(point.get("AAdjC"))
            if m_value is not None:
                morning[code][day] = m_value
            if a_value is not None:
                afternoon[code][day] = a_value
    rows: list[dict[str, Any]] = []
    for index, day in enumerate(dates):
        predecessor = dates[index - 1] if index > 0 else None
        nxt = dates[index + 1] if index + 1 < len(dates) else None
        reasons: list[str] = []
        predecessor_available = predecessor is not None
        if not predecessor_available:
            reasons.append("predecessor_session_missing")
        basevol = _rolling_ok(opt225.get("basevol"), predecessor or "")
        atm = _rolling_ok(opt225.get("atm_iv"), predecessor or "")
        skew = _rolling_ok(opt225.get("skew"), predecessor or "")
        cm_value = _lookup(opt225.get("cm_term_ratio"), predecessor or "", "rv_abs_by_date")
        cm_ok = predecessor is not None and predecessor >= IV_AVAILABLE_FROM and cm_value is not None
        if predecessor_available and not basevol:
            reasons.append("d_minus_1_basevol_missing")
        if predecessor_available and not atm:
            reasons.append("d_minus_1_atm_iv_missing")
        if predecessor_available and not skew:
            reasons.append("d_minus_1_skew_missing")
        if predecessor_available and not cm_ok:
            reasons.append("d_minus_1_cm_term_ratio_missing")
        if not codes:
            reasons.append("equity_universe_empty")
        d_m = bool(codes) and all(day in morning[code] for code in codes)
        d_a = bool(codes) and all(day in afternoon[code] for code in codes)
        next_a = bool(codes) and nxt is not None and all(nxt in afternoon[code] for code in codes)
        if not d_m:
            reasons.append("missing_MAdjC")
        if not d_a:
            reasons.append("missing_AAdjC")
        if nxt is None:
            reasons.append("next_session_missing")
            next_a = False
        elif not next_a:
            reasons.append("missing_next_AAdjC")
        unique = [code for code in COMMON_VALID_REASONS if code in reasons]
        common_valid = (
            predecessor_available
            and basevol
            and atm
            and skew
            and cm_ok
            and d_m
            and d_a
            and next_a
        )
        rows.append(
            {
                "common_valid": common_valid,
                "d_a_fill_valid": d_a,
                "d_m_decision_valid": d_m,
                "d_minus_1_atm_iv": atm,
                "d_minus_1_basevol": basevol,
                "d_minus_1_cm_term_ratio": cm_ok,
                "d_minus_1_skew": skew,
                "date": day,
                "next_a_valuation_valid": next_a,
                "predecessor": predecessor,
                "predecessor_available": predecessor_available,
                "reasons": unique,
            }
        )
    return rows


def load_input_manifest(
    spec: PersonalVolAmPmPanelJobSpec,
    *,
    opener: Callable = _open_input,
) -> dict[str, Any]:
    with opener(spec, spec.input_manifest_key) as response:
        data = _read_bounded(response, MAX_INPUT_BYTES)
    if _sha256(data) != spec.input_manifest_digest:
        raise RuntimeError("input manifest digest mismatch")
    parsed = json.loads(data)
    if (
        not isinstance(parsed, dict)
        or parsed.get("schema_version") != INPUT_SCHEMA
        or parsed.get("job_id") != spec.job_id
        or parsed.get("producer_id") != PRODUCER_ID
        or parsed.get("cohort_id") != COHORT_ID
        or parsed.get("runner_version") != RUNNER_VERSION
        or parsed.get("panel_schema") != PANEL_SCHEMA
        or not isinstance(parsed.get("selection"), dict)
        or not isinstance(parsed.get("periods"), dict)
        or not isinstance(parsed.get("option_sidecars"), dict)
        or not isinstance(parsed.get("sidecar_producer"), dict)
        or not parsed["sidecar_producer"].get("job_id")
    ):
        raise RuntimeError("input manifest identity mismatch")
    if spec.request_digest != _request_digest_from_manifest(spec, parsed):
        raise RuntimeError("request digest does not match locked snapshot job ids")
    return parsed


def with_locked_snapshot(
    spec: PersonalVolAmPmPanelJobSpec,
    lock: Mapping[str, Any],
    work: Path,
    *,
    opener: Callable,
    extract: Callable[[sqlite3.Connection], Any],
) -> Any:
    snapshot = lock["snapshot"]
    key = str(snapshot["key"])
    match = _SNAPSHOT_RE.fullmatch(key)
    if match is None:
        raise RuntimeError("snapshot key is not a v4 gzip object")
    gzip_path = work / f"{lock['period_id']}.sqlite.gz"
    raw_path = work / f"{lock['period_id']}.sqlite"
    try:
        gzip_digest = _download_to_path(
            spec,
            key,
            gzip_path,
            maximum=MAX_SNAPSHOT_BYTES,
            opener=opener,
            expected_digest=str(snapshot["gzip_sha256"]),
        )
        if gzip_digest != snapshot.get("sha256", snapshot["gzip_sha256"]):
            raise RuntimeError("snapshot content digest mismatch")
        _expand_gzip(gzip_path, raw_path, str(snapshot["raw_sha256"]))
        gzip_path.unlink(missing_ok=True)
        connection = _open_sqlite(raw_path)
        try:
            _require_v4_manifest(connection)
            return extract(connection)
        finally:
            connection.close()
    finally:
        gzip_path.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)


def execute_vol_am_pm_panel_job(
    spec: PersonalVolAmPmPanelJobSpec,
    *,
    opener: Callable = _open_input,
    uploader: Callable = _put_bytes,
) -> dict[str, Any]:
    try:
        manifest = load_input_manifest(spec, opener=opener)
        with tempfile.TemporaryDirectory(prefix=f"vol-panel-{spec.job_id}-") as raw_root:
            work = Path(raw_root)
            membership = sorted(
                with_locked_snapshot(
                    spec,
                    manifest["selection"],
                    work,
                    opener=opener,
                    extract=_select_2019_membership,
                )
            )
            membership_digest = _sha256(
                _canonical_bytes({"codes": membership, "schema_version": MEMBERSHIP_SCHEMA})
            )
            period_out: dict[str, Any] = {}
            for period in EVALUATION_PERIODS:
                period_id = period["period_id"]
                lock = manifest["periods"][period_id]
                sidecar_lock = manifest["option_sidecars"][period_id]

                def _period_extract(connection: sqlite3.Connection, locked=lock) -> tuple:
                    dates, calendar_meta = _calendar_from_snapshot(connection)
                    if locked["lookback_sessions"] < REQUIRED_LOOKBACK:
                        raise RuntimeError("period snapshot lookback is below 61 sessions")
                    return dates, calendar_meta, _bars_for_codes(connection, membership, dates)

                dates, calendar_meta, bars = with_locked_snapshot(
                    spec, lock, work, opener=opener, extract=_period_extract
                )
                with opener(spec, sidecar_lock["source_key"]) as response:
                    sidecar_bytes = _read_bounded(response, MAX_LEGACY_PANEL_BYTES)
                if _sha256(sidecar_bytes) != sidecar_lock["sha256"]:
                    raise RuntimeError("option sidecar digest mismatch")
                sidecar_json = json.loads(sidecar_bytes)
                if not isinstance(sidecar_json, dict):
                    raise RuntimeError(OPTION_REBUILD_ERROR)
                opt225 = _extract_opt225_regime(sidecar_json)
                panel = {
                    "schema_version": PANEL_SCHEMA,
                    "period_id": period_id,
                    "year": period["year"],
                    "period_start": period["period_start"],
                    "period_end": period["period_end"],
                    "status": "ok",
                    "source": PRODUCER_ID,
                    "temporal_contract": TEMPORAL_CONTRACT,
                    "session_calendar": {
                        **SESSION_CALENDAR_IDENTITY,
                        "dates": dates,
                        "dates_digest": calendar_meta["dates_digest"],
                    },
                    "codes": membership,
                    "bars": bars,
                    "opt225_regime": opt225,
                    "tradable_hedge": None,
                }
                mask_rows = _common_valid_rows(dates, membership, bars, opt225)
                panel_bytes = _canonical_bytes(panel)
                panel_digest = uploader(spec, _object_key(_sha256(panel_bytes)), panel_bytes)
                if panel_digest != _sha256(panel_bytes):
                    raise RuntimeError("panel digest mismatch")
                mask_digest = _sha256(
                    _canonical_bytes({"rows": mask_rows, "schema_version": COMMON_VALID_SCHEMA})
                )
                period_out[period_id] = {
                    "panel_key": _object_key(panel_digest),
                    "panel_sha256": panel_digest,
                    "panel_size": len(panel_bytes),
                    "common_valid_sha256": mask_digest,
                    "common_valid_count": sum(1 for row in mask_rows if row["common_valid"]),
                    "session_count": len(dates),
                    "session_dates_digest": calendar_meta["dates_digest"],
                    "option_sidecar": {
                        "source_key": sidecar_lock["source_key"],
                        "etag": sidecar_lock["etag"],
                        "sha256": sidecar_lock["sha256"],
                        "dataset": opt225["source"]["dataset"],
                        "version": opt225["source"]["version"],
                    },
                    "snapshot": {
                        "job_id": lock["job_id"],
                        "raw_sha256": lock["snapshot"]["raw_sha256"],
                        "gzip_sha256": lock["snapshot"]["gzip_sha256"],
                    },
                }
            terminal = {
                "schema_version": MANIFEST_SCHEMA,
                "status": "COMPLETED",
                "kind": "vol-panel",
                "producer_id": PRODUCER_ID,
                "job_id": spec.job_id,
                "cohort_id": COHORT_ID,
                "runner_version": RUNNER_VERSION,
                "request_digest": spec.request_digest,
                "input_manifest_key": spec.input_manifest_key,
                "input_manifest_digest": spec.input_manifest_digest,
                "membership": {
                    "codes": membership,
                    "digest": membership_digest,
                    "count": len(membership),
                },
                "periods": period_out,
                "draft_only": True,
                "screening_only": True,
                "go": False,
                "not_a_pass": True,
            }
    except Exception as error:
        terminal = {
            "schema_version": MANIFEST_SCHEMA,
            "status": "FAILED",
            "kind": "vol-panel",
            "producer_id": PRODUCER_ID,
            "job_id": spec.job_id,
            "cohort_id": COHORT_ID,
            "runner_version": RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "input_manifest_key": spec.input_manifest_key,
            "input_manifest_digest": spec.input_manifest_digest,
            "error": _safe_detail(error),
            "draft_only": True,
            "screening_only": True,
            "go": False,
            "not_a_pass": True,
        }
    terminal_bytes = _canonical_bytes(terminal)
    uploader(spec, spec.manifest_key, terminal_bytes)
    return terminal


__all__ = [
    "PersonalVolAmPmPanelJobSpec",
    "VolPanelJobInputError",
    "execute_vol_am_pm_panel_job",
    "with_locked_snapshot",
]
