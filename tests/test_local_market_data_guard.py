"""Host-local market data opt-in: helper and executable CLI boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts._local_market_data_guard import (
    LOCAL_MARKET_DATA_DISABLED,
    LOCAL_MARKET_DATA_ENV,
    local_market_data_allowed,
    require_local_market_data_opt_in,
)
from scripts.run_ingestion_once import main as ingestion_main


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def _env(*names_to_drop: str, **updates: str) -> dict[str, str]:
    env = os.environ.copy()
    for name in (LOCAL_MARKET_DATA_ENV, "INGESTION_RUNTIME", *names_to_drop):
        env.pop(name, None)
    env.update(updates)
    return env


def _run(
    script: str,
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "value, allowed",
    [
        (None, False),
        ("", False),
        ("true", False),
        ("True", False),
        ("0", False),
        ("yes", False),
        ("1 ", False),
        ("1", True),
    ],
)
def test_allowed_requires_exact_one(monkeypatch, value, allowed) -> None:
    if value is None:
        monkeypatch.delenv(LOCAL_MARKET_DATA_ENV, raising=False)
    else:
        monkeypatch.setenv(LOCAL_MARKET_DATA_ENV, value)
    assert local_market_data_allowed() is allowed


def test_require_exits_two_with_cloudflare_path(monkeypatch, capsys) -> None:
    monkeypatch.delenv(LOCAL_MARKET_DATA_ENV, raising=False)
    with pytest.raises(SystemExit) as exc:
        require_local_market_data_opt_in(["--source", "jsda"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err.strip() == LOCAL_MARKET_DATA_DISABLED
    assert "R2" in err and "D1" in err
    assert LOCAL_MARKET_DATA_ENV in err


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_require_skips_help(monkeypatch, flag) -> None:
    monkeypatch.delenv(LOCAL_MARKET_DATA_ENV, raising=False)
    require_local_market_data_opt_in([flag])


def test_require_passes_exact_one(monkeypatch) -> None:
    monkeypatch.setenv(LOCAL_MARKET_DATA_ENV, "1")
    require_local_market_data_opt_in(["--execute"])


def test_importable_ingestion_main_is_not_guarded(monkeypatch, capsys) -> None:
    monkeypatch.delenv(LOCAL_MARKET_DATA_ENV, raising=False)
    monkeypatch.delenv("INGESTION_RUNTIME", raising=False)
    assert ingestion_main([]) == 2
    out = capsys.readouterr().out
    assert out.startswith("[cloudflare]")
    assert "local market data is disabled" not in out


def _empty_cwd(tmp_path: Path) -> Path:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    return cwd


@pytest.mark.parametrize(
    "args, env_updates",
    [
        (["--source", "jsda"], {}),
        (["--source", "jsda", "--runtime", "cloudflare"], {}),
        (["--source", "jsda", "--runtime=cloudflare"], {}),
        (["--source", "jsda", "--runtime", "cloudflare"], {"INGESTION_RUNTIME": "local"}),
        (["--source", "jsda"], {"INGESTION_RUNTIME": "cloudflare"}),
    ],
)
def test_executable_ingestion_cloudflare_allowed_without_files(
    tmp_path, args, env_updates
) -> None:
    cwd = _empty_cwd(tmp_path)
    completed = _run("run_ingestion_once.py", args, cwd=cwd, env=_env(**env_updates))
    assert completed.returncode == 2
    assert "local market data is disabled" not in completed.stderr
    assert completed.stdout.startswith("[cloudflare]")
    assert "does not fetch into host-local storage" in completed.stdout
    assert list(cwd.iterdir()) == []


@pytest.mark.parametrize(
    "args, env_updates",
    [
        (["--source", "jsda", "--runtime", "local"], {}),
        (["--source", "jsda", "--runtime=local"], {}),
        (["--source", "jsda"], {"INGESTION_RUNTIME": "local"}),
        (["--source", "jsda", "--runtime", "local"], {"INGESTION_RUNTIME": "cloudflare"}),
    ],
)
def test_executable_ingestion_local_denied_before_files(
    tmp_path, args, env_updates
) -> None:
    cwd = _empty_cwd(tmp_path)
    completed = _run("run_ingestion_once.py", args, cwd=cwd, env=_env(**env_updates))
    assert completed.returncode == 2
    assert completed.stderr.strip() == LOCAL_MARKET_DATA_DISABLED
    assert "[cloudflare]" not in completed.stdout
    assert list(cwd.iterdir()) == []


@pytest.mark.parametrize(
    "args, env_updates",
    [
        (["--runtime", "local", "--personal-draft", "--source", "jquants"], {}),
        (["--runtime=local", "--personal-draft", "--source", "jquants"], {}),
        (
            ["--personal-draft", "--source", "jquants"],
            {"INGESTION_RUNTIME": "local"},
        ),
    ],
)
def test_executable_ingestion_local_opt_in_reaches_parser_not_fetch(
    tmp_path, args, env_updates
) -> None:
    cwd = _empty_cwd(tmp_path)
    completed = _run(
        "run_ingestion_once.py",
        args,
        cwd=cwd,
        env=_env(**{LOCAL_MARKET_DATA_ENV: "1", **env_updates}),
    )
    assert completed.returncode == 2
    assert "local market data is disabled" not in completed.stderr
    assert "requires at least one --dataset" in completed.stderr
    assert list(cwd.iterdir()) == []


@pytest.mark.parametrize("value", ["true", "0", ""])
def test_executable_denies_non_exact_values(tmp_path, value) -> None:
    cwd = _empty_cwd(tmp_path)
    db = cwd / "mirror.sqlite"
    completed = _run(
        "sync_d1_to_sqlite.py",
        ["--db", str(db)],
        cwd=cwd,
        env=_env(**{LOCAL_MARKET_DATA_ENV: value}),
    )
    assert completed.returncode == 2
    assert "local market data is disabled" in completed.stderr
    assert not db.exists()
    assert list(cwd.iterdir()) == []


def test_hydrate_dry_run_does_not_need_opt_in(tmp_path) -> None:
    cwd = _empty_cwd(tmp_path)
    db = cwd / "never-created.sqlite"
    completed = _run(
        "hydrate_personal_history.py",
        [
            "--from-date",
            "2025-01-01",
            "--to-date",
            "2025-01-31",
            "--db",
            str(db),
        ],
        cwd=cwd,
        env=_env(),
    )
    assert completed.returncode == 0, completed.stderr
    assert "dry-run complete" in completed.stdout
    assert not db.exists()
    assert "local market data is disabled" not in completed.stderr


def test_hydrate_execute_refuses_without_opt_in(tmp_path) -> None:
    cwd = _empty_cwd(tmp_path)
    db = cwd / "never-created.sqlite"
    completed = _run(
        "hydrate_personal_history.py",
        [
            "--from-date",
            "2025-01-01",
            "--to-date",
            "2025-01-31",
            "--db",
            str(db),
            "--execute",
        ],
        cwd=cwd,
        env=_env(),
    )
    assert completed.returncode == 2
    assert "local market data is disabled" in completed.stderr
    assert not db.exists()
    assert "dry-run complete" not in completed.stdout
    assert list(cwd.iterdir()) == []


def test_hydrate_execute_dry_run_flag_skips_opt_in(tmp_path) -> None:
    cwd = _empty_cwd(tmp_path)
    db = cwd / "never-created.sqlite"
    completed = _run(
        "hydrate_personal_history.py",
        [
            "--from-date",
            "2025-01-01",
            "--to-date",
            "2025-01-31",
            "--db",
            str(db),
            "--execute",
            "--dry-run",
        ],
        cwd=cwd,
        env=_env(),
    )
    assert completed.returncode == 0, completed.stderr
    assert "dry-run complete" in completed.stdout
    assert not db.exists()


def test_opt_in_reaches_parser_not_market_data(tmp_path) -> None:
    cwd = _empty_cwd(tmp_path)
    completed = _run(
        "jsda_otc_fetch_official.py",
        [],
        cwd=cwd,
        env=_env(**{LOCAL_MARKET_DATA_ENV: "1"}),
    )
    assert completed.returncode == 2
    assert "local market data is disabled" not in completed.stderr
    combined = completed.stdout + completed.stderr
    assert "--log-dir" in combined
    assert list(cwd.iterdir()) == []


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["-h"],
        ["--runtime", "local", "--help"],
        ["--help", "--runtime=local"],
    ],
)
def test_ingestion_help_available_without_opt_in(tmp_path, args) -> None:
    cwd = _empty_cwd(tmp_path)
    completed = _run("run_ingestion_once.py", args, cwd=cwd, env=_env())
    assert completed.returncode == 0
    assert "local market data is disabled" not in completed.stderr
    assert "--runtime" in completed.stdout
    assert list(cwd.iterdir()) == []
