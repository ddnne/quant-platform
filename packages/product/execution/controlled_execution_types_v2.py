"""Nominal one-call and immutable Controlled artifact result types."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, NoReturn

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    _canonical_bytes,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_results import ExactFourPilotResultManifestV2


_WRITER_CONSTRUCTION_TOKEN = object()
_WRITTEN_BUNDLE_TOKEN = object()
_VERIFIED_EXECUTOR_OUTPUT_TOKEN = object()


class ControlledExecutionWriterV2Error(ExactFourAuthorityContractError):
    """A peer, handoff, signature, or immutable transaction was rejected."""


@dataclass(frozen=True, slots=True, init=False)
class _VerifiedBoundedExecutionOutputV2:
    manifest: ExactFourPilotResultManifestV2
    contents: Mapping[str, bytes]

    def __init__(
        self,
        manifest: ExactFourPilotResultManifestV2,
        contents: Mapping[str, bytes],
        *,
        _token: object,
    ) -> None:
        if _token is not _VERIFIED_EXECUTOR_OUTPUT_TOKEN:
            raise ControlledExecutionWriterV2Error(
                "bounded executor output requires canonical result revalidation"
            )
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(
            self,
            "contents",
            MappingProxyType({key: bytes(value) for key, value in contents.items()}),
        )


class WrittenExactFourControlledArtifactsV2:
    """Immutable signed Controlled result returned after the atomic commit."""

    __slots__ = ("_manifest", "_contents")

    def __setattr__(self, name: str, value: Any) -> NoReturn:
        del name, value
        raise AttributeError("written exact-four controlled artifacts are immutable")

    def __delattr__(self, name: str) -> NoReturn:
        del name
        raise AttributeError("written exact-four controlled artifacts are immutable")

    def __init__(
        self,
        manifest: bytes,
        contents: Mapping[str, bytes],
        *,
        _token: object,
    ) -> None:
        if _token is not _WRITTEN_BUNDLE_TOKEN:
            raise ControlledExecutionWriterV2Error(
                "written artifacts require a committed Controlled transaction"
            )
        copied: dict[str, bytes] = {}
        for key, value in contents.items():
            if type(key) is not str or type(value) is not bytes:
                raise ControlledExecutionWriterV2Error(
                    "written artifact content map is invalid"
                )
            copied[key] = bytes(value)
        object.__setattr__(self, "_manifest", bytes(manifest))
        object.__setattr__(self, "_contents", MappingProxyType(copied))

    @property
    def canonical_manifest(self) -> bytes:
        return self._manifest

    @property
    def contents(self) -> Mapping[str, bytes]:
        return self._contents

    def to_dict(self) -> dict[str, Any]:
        return _strict_json_loads(
            self._manifest,
            label="written exact-four Controlled manifest",
        )

    @property
    def manifest_id(self) -> str:
        return self.to_dict()["manifest_id"]

    def verify_signature(self, public_key: Ed25519PublicKey) -> bool:
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        document = self.to_dict()
        signature_text = document.pop("signature", None)
        if type(signature_text) is not str or not signature_text.startswith(
            "ed25519:"
        ):
            return False
        signed_body = dict(document)
        declared_manifest_id = signed_body.pop("manifest_id", None)
        if declared_manifest_id != canonical_authority_digest(signed_body):
            return False
        try:
            signature = base64.b64decode(
                signature_text[len("ed25519:") :], validate=True
            )
            if len(signature) != 64:
                return False
            public_key.verify(signature, _canonical_bytes(document))
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True


@dataclass(frozen=True, slots=True)
class _ControlledWriterSignerV2:
    key_id: str
    private_key: Ed25519PrivateKey

    def __post_init__(self) -> None:
        if (
            type(self.key_id) is not str
            or not self.key_id
            or self.key_id != self.key_id.strip()
            or not isinstance(self.private_key, Ed25519PrivateKey)
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled writer signer identity is invalid"
            )

    def sign(self, document: dict[str, Any]) -> str:
        return "ed25519:" + base64.b64encode(
            self.private_key.sign(_canonical_bytes(document))
        ).decode("ascii")


__all__ = [
    "ControlledExecutionWriterV2Error",
    "WrittenExactFourControlledArtifactsV2",
]
