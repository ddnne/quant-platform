"""Root pytest config.

1. Puts the repo root and ``packages/*`` plane roots on ``sys.path`` so top-level
   import names (``ingestion``, ``storage``, …) resolve whether or not the
   project is installed editable. Primary path remains ``pip install -e ".[dev]"``.
2. Provides offline test doubles (FakeHttpClient) so unit tests never touch
   the network.
"""

from __future__ import annotations

import json
import os
import sys

# Repo root on sys.path (parent of this file's directory == repo root).
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Multi-root layout: packages live under packages/{edge,data_plane,...}/<name>.
# Editable install is preferred; these entries keep uninstalled checkouts importable.
_PACKAGES_ROOT = os.path.join(_REPO_ROOT, "packages")
for _plane in ("edge", "data_plane", "research_runtime", "product"):
    _plane_path = os.path.join(_PACKAGES_ROOT, _plane)
    if os.path.isdir(_plane_path) and _plane_path not in sys.path:
        sys.path.insert(0, _plane_path)

import pytest

from ingestion.common.http import HttpResponse


class FakeHttpClient:
    """In-memory ``HttpClient`` for offline tests.

    Register routes with :meth:`route`; unmatched URLs return HTTP 404.
    Records every call in ``self.calls`` for assertions.
    """

    name = "local"

    def __init__(self) -> None:
        self._routes: dict[str, HttpResponse] = {}
        self.calls: list[dict] = []

    def route(self, url, *, status=200, body=b"", text=None, json_data=None,
              headers=None) -> "FakeHttpClient":
        if json_data is not None:
            body = json.dumps(json_data).encode("utf-8")
        elif text is not None:
            body = text.encode("utf-8")
        self._routes[url] = HttpResponse(
            status=status,
            headers=headers or {"content-type": "application/octet-stream"},
            body=body,
            url=url,
        )
        return self

    def get(self, url, *, headers=None, params=None, timeout=30.0) -> HttpResponse:
        self.calls.append({"url": url, "params": params, "headers": headers})
        if url in self._routes:
            return self._routes[url]
        for key, resp in self._routes.items():
            if url.startswith(key):
                return resp
        return HttpResponse(404, {}, b"", url)


@pytest.fixture
def fake_http() -> FakeHttpClient:
    return FakeHttpClient()


@pytest.fixture
def jsda_sample_text() -> str:
    with open(os.path.join(_REPO_ROOT, "tests", "fixtures", "jsda_sample.csv"),
              encoding="utf-8") as fh:
        return fh.read()
