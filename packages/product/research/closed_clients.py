"""Closed typed ports for Product. No URL, header, secret, or Path capability."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ClosedJsonClient(Protocol):
    """POST a JSON body and return a JSON object. Destination is bound outside."""

    def post(self, body: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ClosedDeployResult(Protocol):
    def text(self) -> str: ...


class ClosedDeployPort(Protocol):
    def deploy(self) -> str: ...


class ClosedArtifactPut(Protocol):
    def put(self, name: str, payload: bytes) -> Mapping[str, Any]: ...


class ClosedGitIdentity(Protocol):
    def head_sha(self) -> str | None: ...
