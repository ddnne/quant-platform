"""Proxy-config pair resolution: never mix a proxy URL with a token across sources.

A proxy URL and its bearer token must come from ONE source. ``resolve_proxy_config``
tries sources in order and returns the first that yields a *complete* pair:

1. env vars ``INGESTION_PROXY_URL`` + ``INGESTION_PROXY_TOKEN`` (both);
2. single JSON file ``ingestion_proxy.json`` with ``{"url","token"}`` (both);
3. split files ``ingestion_proxy_url`` + ``ingestion_proxy_token`` (both).

These tests pin the no-mix rule — a URL from one source paired with a token
from another must resolve to ``None`` (fall back to direct fetch) rather than
a Frankenstein config that could point an authenticated token at the wrong
proxy. They also cover per-source completeness, source priority, and the
robustness/normalization paths.
"""

from __future__ import annotations

import json
from pathlib import Path

from ingestion.common.secrets import (
    JSON_FILE,
    TOKEN_FILE,
    URL_FILE,
    ProxyConfig,
    resolve_proxy_config,
)

_URL = "https://proxy.example.workers.dev"
_TOKEN = "shared-proxy-secret"


def _env(**kw: str) -> dict[str, str]:
    """Build an env dict (empty by default) — keeps tests off os.environ."""
    return dict(kw)


def _write_json_pair(config_dir: Path, *, url: str | None, token: str | None) -> None:
    data: dict[str, str] = {}
    if url is not None:
        data["url"] = url
    if token is not None:
        data["token"] = token
    (config_dir / JSON_FILE.name).write_text(json.dumps(data), encoding="utf-8")


def _write_url_file(config_dir: Path, url: str) -> None:
    (config_dir / URL_FILE.name).write_text(url + "\n", encoding="utf-8")


def _write_token_file(config_dir: Path, token: str) -> None:
    (config_dir / TOKEN_FILE.name).write_text(token + "\n", encoding="utf-8")


# --------------------------------------------------------------- complete pairs

def test_env_pair_resolves(tmp_path):
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_URL=_URL, INGESTION_PROXY_TOKEN=_TOKEN),
        config_dir=tmp_path,
    )
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


def test_json_pair_resolves(tmp_path):
    _write_json_pair(tmp_path, url=_URL, token=_TOKEN)
    cfg = resolve_proxy_config(env=_env(), config_dir=tmp_path)
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


def test_split_file_pair_resolves(tmp_path):
    _write_url_file(tmp_path, _URL)
    _write_token_file(tmp_path, _TOKEN)
    cfg = resolve_proxy_config(env=_env(), config_dir=tmp_path)
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


# ----------------------------------------------------- partial source -> None

def test_env_url_only_is_none(tmp_path):
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_URL=_URL), config_dir=tmp_path
    )
    assert cfg is None


def test_env_token_only_is_none(tmp_path):
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_TOKEN=_TOKEN), config_dir=tmp_path
    )
    assert cfg is None


def test_json_url_only_is_none(tmp_path):
    _write_json_pair(tmp_path, url=_URL, token=None)
    assert resolve_proxy_config(env=_env(), config_dir=tmp_path) is None


def test_json_token_only_is_none(tmp_path):
    _write_json_pair(tmp_path, url=None, token=_TOKEN)
    assert resolve_proxy_config(env=_env(), config_dir=tmp_path) is None


def test_split_url_file_only_is_none(tmp_path):
    _write_url_file(tmp_path, _URL)
    assert resolve_proxy_config(env=_env(), config_dir=tmp_path) is None


def test_split_token_file_only_is_none(tmp_path):
    _write_token_file(tmp_path, _TOKEN)
    assert resolve_proxy_config(env=_env(), config_dir=tmp_path) is None


# ----------------------------------------------------- THE MIX-REJECTION RULE
# A URL from one source must NEVER be paired with a token from another.

def test_env_url_with_file_token_is_none(tmp_path):
    """URL from env must NOT pair with token from a split file."""
    _write_token_file(tmp_path, _TOKEN)
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_URL=_URL), config_dir=tmp_path
    )
    assert cfg is None


def test_file_url_with_env_token_is_none(tmp_path):
    """URL from a split file must NOT pair with token from env."""
    _write_url_file(tmp_path, _URL)
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_TOKEN=_TOKEN), config_dir=tmp_path
    )
    assert cfg is None


def test_env_url_with_json_token_is_none(tmp_path):
    """URL from env must NOT pair with token from the JSON file."""
    _write_json_pair(tmp_path, url=None, token=_TOKEN)
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_URL=_URL), config_dir=tmp_path
    )
    assert cfg is None


def test_env_token_with_json_url_is_none(tmp_path):
    """Token from env must NOT pair with URL from the JSON file."""
    _write_json_pair(tmp_path, url=_URL, token=None)
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_TOKEN=_TOKEN), config_dir=tmp_path
    )
    assert cfg is None


def test_json_url_with_file_token_is_none(tmp_path):
    """URL from JSON must NOT pair with token from a split file."""
    _write_json_pair(tmp_path, url=_URL, token=None)
    _write_token_file(tmp_path, _TOKEN)
    assert resolve_proxy_config(env=_env(), config_dir=tmp_path) is None


def test_file_url_with_json_token_is_none(tmp_path):
    """URL from a split file must NOT pair with token from JSON."""
    _write_json_pair(tmp_path, url=None, token=_TOKEN)
    _write_url_file(tmp_path, _URL)
    assert resolve_proxy_config(env=_env(), config_dir=tmp_path) is None


# ------------------------------------------------------------ source priority

def test_env_pair_takes_precedence_over_json(tmp_path):
    _write_json_pair(tmp_path, url="https://from-json", token="json-tok")
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_URL=_URL, INGESTION_PROXY_TOKEN=_TOKEN),
        config_dir=tmp_path,
    )
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


def test_json_pair_takes_precedence_over_split_files(tmp_path):
    _write_json_pair(tmp_path, url=_URL, token=_TOKEN)
    _write_url_file(tmp_path, "https://from-split")
    _write_token_file(tmp_path, "split-tok")
    cfg = resolve_proxy_config(env=_env(), config_dir=tmp_path)
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


def test_env_pair_takes_precedence_over_split_files(tmp_path):
    _write_url_file(tmp_path, "https://from-split")
    _write_token_file(tmp_path, "split-tok")
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_URL=_URL, INGESTION_PROXY_TOKEN=_TOKEN),
        config_dir=tmp_path,
    )
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


# -------------------------------------------------------- normalization/robust

def test_trailing_slash_stripped_per_source(tmp_path):
    # env
    cfg = resolve_proxy_config(
        env=_env(INGESTION_PROXY_URL=_URL + "/", INGESTION_PROXY_TOKEN=_TOKEN),
        config_dir=tmp_path,
    )
    assert cfg is not None and cfg.url == _URL
    # json
    _write_json_pair(tmp_path, url=_URL + "/", token=_TOKEN)
    cfg = resolve_proxy_config(env=_env(), config_dir=tmp_path)
    assert cfg is not None and cfg.url == _URL
    # split files (remove the json file so source 3 is reached)
    (tmp_path / JSON_FILE.name).unlink()
    _write_url_file(tmp_path, _URL + "/")
    _write_token_file(tmp_path, _TOKEN)
    cfg = resolve_proxy_config(env=_env(), config_dir=tmp_path)
    assert cfg is not None and cfg.url == _URL


def test_whitespace_stripped(tmp_path):
    cfg = resolve_proxy_config(
        env=_env(
            INGESTION_PROXY_URL="  " + _URL + "  ",
            INGESTION_PROXY_TOKEN="\t" + _TOKEN + " ",
        ),
        config_dir=tmp_path,
    )
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


def test_malformed_json_falls_through_to_split_files(tmp_path):
    (tmp_path / JSON_FILE.name).write_text("{not valid json", encoding="utf-8")
    _write_url_file(tmp_path, _URL)
    _write_token_file(tmp_path, _TOKEN)
    cfg = resolve_proxy_config(env=_env(), config_dir=tmp_path)
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


def test_non_object_json_is_ignored(tmp_path):
    (tmp_path / JSON_FILE.name).write_text('["url", "token"]', encoding="utf-8")
    _write_url_file(tmp_path, _URL)
    _write_token_file(tmp_path, _TOKEN)
    cfg = resolve_proxy_config(env=_env(), config_dir=tmp_path)
    assert cfg == ProxyConfig(url=_URL, token=_TOKEN)


def test_nothing_configured_is_none(tmp_path):
    assert resolve_proxy_config(env=_env(), config_dir=tmp_path) is None
