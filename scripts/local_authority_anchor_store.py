"""Pinned HTTPS transport and append-only local anchor audit store.

The transport and local persistence layers consume the canonical contract but
do not define wire semantics or remote authority state.
"""

from __future__ import annotations

import errno
import fcntl
import os
import ssl
import stat
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.local_authority_activation import canonical_json_bytes
from scripts.local_authority_anchor_contract import (
    ABANDONMENT_RECORD_FORMAT,
    AUDIT_RECORD_FORMAT,
    MAX_DOCUMENT_BYTES,
    SUBMISSION_RECORD_FORMAT,
    AnchorKeyRegistry,
    AnchorProtocolError,
    _digest,
    _parse_time,
    _strict_json,
    _validate_challenge,
    _validate_challenge_request,
    _validate_commit_request,
    _validate_receipt,
    _validate_resolution_request,
    _validate_resolution_response,
    _verify_lineage_proof,
)
from scripts.manage_local_authority_staged_canary import _validate_anchor_candidate

class AnchorTransport(Protocol):
    def post(self, path: str, raw: bytes) -> bytes: ...


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise AnchorProtocolError("anchor transport redirect rejected")


class PinnedHTTPSAnchorTransport:
    """HTTPS-only POST transport with no ambient proxy, cookies or credentials."""

    def __init__(
        self, *, endpoint: str, per_io_timeout_seconds: int,
        maximum_document_bytes: int,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        parsed = urllib.parse.urlsplit(endpoint)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}
        ):
            raise AnchorProtocolError("anchor transport endpoint is not pinned HTTPS")
        if (
            type(per_io_timeout_seconds) is not int
            or per_io_timeout_seconds < 1
            or per_io_timeout_seconds > 10
            or maximum_document_bytes != MAX_DOCUMENT_BYTES
        ):
            raise AnchorProtocolError("anchor transport bounds are invalid")
        self._endpoint = endpoint.rstrip("/")
        self._per_io_timeout = per_io_timeout_seconds
        self._maximum = maximum_document_bytes
        context = ssl_context or ssl.create_default_context()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context),
            _RejectRedirect(),
        )

    def post(self, path: str, raw: bytes) -> bytes:
        if path not in {
            "/v1/local-authority-anchor/challenge",
            "/v1/local-authority-anchor/commit",
            "/v1/local-authority-anchor/resolve",
        } or type(raw) is not bytes or not raw or len(raw) > self._maximum:
            raise AnchorProtocolError("anchor transport request is outside policy")
        request = urllib.request.Request(
            self._endpoint + path,
            data=raw,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._per_io_timeout) as response:
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise AnchorProtocolError("anchor transport response metadata rejected")
                body = response.read(self._maximum + 1)
                final_url = urllib.parse.urlsplit(response.geturl())
        except AnchorProtocolError:
            raise
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise AnchorProtocolError("anchor HTTPS request failed closed") from exc
        if (
            len(body) > self._maximum
            or final_url.geturl() != urllib.parse.urlsplit(self._endpoint + path).geturl()
        ):
            raise AnchorProtocolError("anchor transport response exceeded its boundary")
        return body


class AnchorReceiptAudit:
    """Create-only root-owned receipt records; corruption is never repaired."""

    def __init__(
        self, path: Path, *, expected_owner_uid: int = 0,
        expected_owner_gid: int = 0,
    ) -> None:
        self.path = path
        self.expected_owner_uid = expected_owner_uid
        self.expected_owner_gid = expected_owner_gid
        self._collector_lock_fd: int | None = None
        self._collector_lock_guard_fd: int | None = None
        self._collector_directory_fd: int | None = None
        self._collector_lock_owner_pid: int | None = None
        self._collector_lock_ofd_cookie: int | None = None
        self._collector_lock_validation = threading.Lock()

    @contextmanager
    def collector_lock(self) -> Any:
        """Hold the one pinned process lock for a complete collector decision."""

        if self._collector_lock_fd is not None:
            raise AnchorProtocolError("anchor collector lock is already held")
        self._require_directory(create=True)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_fd = os.open(self.path, directory_flags)
        lock_fd: int | None = None
        guard_fd: int | None = None
        owner_pid = os.getpid()
        try:
            directory_info = os.fstat(directory_fd)
            path_info = self.path.lstat()
            if (
                not stat.S_ISDIR(directory_info.st_mode)
                or directory_info.st_uid != self.expected_owner_uid
                or directory_info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(directory_info.st_mode) != 0o700
                or directory_info.st_nlink < 2
                or (directory_info.st_dev, directory_info.st_ino)
                != (path_info.st_dev, path_info.st_ino)
            ):
                raise AnchorProtocolError("anchor collector lock parent drifted")
            lock_flags = (
                os.O_RDWR
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            created = False
            try:
                lock_fd = os.open(
                    ".collector.lock",
                    lock_flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                created = True
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise AnchorProtocolError(
                        "anchor collector lock creation failed"
                    ) from exc
                lock_fd = os.open(
                    ".collector.lock", lock_flags, dir_fd=directory_fd
                )
            if created:
                os.fchmod(lock_fd, 0o600)
                os.fchown(
                    lock_fd, self.expected_owner_uid, self.expected_owner_gid
                )
                os.fsync(lock_fd)
                os.fsync(directory_fd)
            lock_info = os.fstat(lock_fd)
            named_info = os.stat(
                ".collector.lock", dir_fd=directory_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(lock_info.st_mode)
                or lock_info.st_uid != self.expected_owner_uid
                or lock_info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(lock_info.st_mode) != 0o600
                or lock_info.st_nlink != 1
                or (lock_info.st_dev, lock_info.st_ino)
                != (named_info.st_dev, named_info.st_ino)
            ):
                raise AnchorProtocolError("anchor collector lock file is unsafe")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                raise AnchorProtocolError("anchor collector is already running") from exc
            try:
                guard_fd = os.dup(lock_fd)
                # A duplicate proves the descriptors initially name one open
                # file description.  The unpredictable shared offset also
                # prevents a stale Audit object from reviving if both integer
                # descriptor numbers are later closed and reused by open+dup.
                ofd_cookie = 3 + int.from_bytes(os.urandom(8), "big") % (
                    (1 << 62) - 4
                )
                os.lseek(lock_fd, ofd_cookie, os.SEEK_SET)
                if os.lseek(guard_fd, 0, os.SEEK_CUR) != ofd_cookie:
                    raise OSError("collector lock descriptors do not share an OFD")
            except OSError as exc:
                raise AnchorProtocolError(
                    "anchor collector lock descriptor cannot be guarded"
                ) from exc
            lock_info_after = os.fstat(lock_fd)
            named_after = os.stat(
                ".collector.lock", dir_fd=directory_fd, follow_symlinks=False
            )
            if (
                (lock_info_after.st_dev, lock_info_after.st_ino)
                != (lock_info.st_dev, lock_info.st_ino)
                or (named_after.st_dev, named_after.st_ino)
                != (lock_info.st_dev, lock_info.st_ino)
            ):
                raise AnchorProtocolError("anchor collector lock inode changed")
            self._collector_lock_fd = lock_fd
            self._collector_lock_guard_fd = guard_fd
            self._collector_directory_fd = directory_fd
            self._collector_lock_owner_pid = owner_pid
            self._collector_lock_ofd_cookie = ofd_cookie
            self._require_collector_lock()
            yield
            self._require_collector_lock()
        finally:
            if lock_fd is not None:
                if (
                    os.getpid() == owner_pid
                    and self._collector_descriptors_share_open_file_description()
                ):
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                try:
                    os.close(lock_fd)
                except OSError:
                    pass
            if guard_fd is not None:
                try:
                    os.close(guard_fd)
                except OSError:
                    pass
            if os.getpid() == owner_pid:
                self._collector_lock_fd = None
                self._collector_lock_guard_fd = None
                self._collector_directory_fd = None
                self._collector_lock_owner_pid = None
                self._collector_lock_ofd_cookie = None
            try:
                os.close(directory_fd)
            except OSError:
                pass

    def _require_collector_lock(self) -> None:
        if (
            self._collector_lock_fd is None
            or self._collector_lock_guard_fd is None
            or self._collector_directory_fd is None
            or self._collector_lock_owner_pid != os.getpid()
            or self._collector_lock_ofd_cookie is None
        ):
            raise AnchorProtocolError("anchor collector lock ownership is absent")
        with self._collector_lock_validation:
            try:
                info = os.fstat(self._collector_lock_fd)
                guard_info = os.fstat(self._collector_lock_guard_fd)
                directory_info = os.fstat(self._collector_directory_fd)
                path_info = self.path.lstat()
                named_info = os.stat(
                    ".collector.lock",
                    dir_fd=self._collector_directory_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise AnchorProtocolError(
                    "anchor collector lock descriptor is invalid"
                ) from exc
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.expected_owner_uid
                or info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or (guard_info.st_dev, guard_info.st_ino)
                != (info.st_dev, info.st_ino)
                or guard_info.st_uid != self.expected_owner_uid
                or guard_info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(guard_info.st_mode) != 0o600
                or guard_info.st_nlink != 1
                or not stat.S_ISDIR(directory_info.st_mode)
                or directory_info.st_uid != self.expected_owner_uid
                or directory_info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(directory_info.st_mode) != 0o700
                or directory_info.st_nlink < 2
                or (directory_info.st_dev, directory_info.st_ino)
                != (path_info.st_dev, path_info.st_ino)
                or (info.st_dev, info.st_ino)
                != (named_info.st_dev, named_info.st_ino)
                or not self._collector_descriptors_share_open_file_description()
            ):
                raise AnchorProtocolError("anchor collector lock descriptor drifted")
            try:
                # flock is idempotent for the held OFD.  A descriptor opened
                # independently, even by this process/UID, conflicts with the
                # live holder and therefore cannot masquerade as the lease.
                fcntl.flock(
                    self._collector_lock_fd,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except (BlockingIOError, OSError) as exc:
                raise AnchorProtocolError(
                    "anchor collector lock descriptor does not own the lock"
                ) from exc

    def _collector_descriptors_share_open_file_description(self) -> bool:
        """Reject stale lock state after either descriptor number is reused."""

        descriptor = self._collector_lock_fd
        guard = self._collector_lock_guard_fd
        cookie = self._collector_lock_ofd_cookie
        if descriptor is None or guard is None or cookie is None:
            return False
        descriptor_offset: int | None = None
        guard_offset: int | None = None
        try:
            descriptor_offset = os.lseek(descriptor, 0, os.SEEK_CUR)
            guard_offset = os.lseek(guard, 0, os.SEEK_CUR)
            if descriptor_offset != cookie or guard_offset != cookie:
                return False
            probe_offset = cookie + 1
            os.lseek(descriptor, probe_offset, os.SEEK_SET)
            return os.lseek(guard, 0, os.SEEK_CUR) == probe_offset
        except OSError:
            return False
        finally:
            if descriptor_offset is not None:
                try:
                    os.lseek(descriptor, descriptor_offset, os.SEEK_SET)
                except OSError:
                    pass
            if guard_offset is not None:
                try:
                    os.lseek(guard, guard_offset, os.SEEK_SET)
                except OSError:
                    pass

    def _require_directory(self, *, create: bool) -> None:
        if not self.path.exists() and create:
            os.mkdir(self.path, 0o700)
            os.chown(self.path, self.expected_owner_uid, self.expected_owner_gid)
            parent_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        try:
            info = self.path.lstat()
        except OSError as exc:
            raise AnchorProtocolError("anchor receipt audit directory is absent") from exc
        if (
            not stat.S_ISDIR(info.st_mode) or info.st_uid != self.expected_owner_uid
            or info.st_gid != self.expected_owner_gid
            or stat.S_IMODE(info.st_mode) != 0o700 or info.st_nlink < 2
        ):
            raise AnchorProtocolError("anchor receipt audit directory is unsafe")

    def records(self) -> list[dict[str, Any]]:
        self._require_directory(create=False)
        result: list[dict[str, Any]] = []
        accepted_paths = sorted(
            path for path in self.path.iterdir() if path.name[:1].isdigit()
        )
        for expected_generation, path in enumerate(accepted_paths, start=1):
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode) or info.st_uid != self.expected_owner_uid
                or info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or not path.name.startswith(f"{expected_generation:020d}-")
                or not path.name.endswith(".json")
            ):
                raise AnchorProtocolError("anchor receipt audit record is unsafe")
            raw = path.read_bytes()
            value = _strict_json(raw, label="stored anchor audit record")
            if set(value) != {
                "format", "challenge_request", "challenge", "commit_request",
                "receipt", "record_digest"
            } or value["format"] != AUDIT_RECORD_FORMAT:
                raise AnchorProtocolError("stored anchor audit record fields drifted")
            if value["record_digest"] != _digest(
                {name: value[name] for name in value if name != "record_digest"}
            ) or path.name != f"{expected_generation:020d}-{value['record_digest'].removeprefix('sha256:')}.json":
                raise AnchorProtocolError("stored anchor audit record digest drifted")
            result.append(value)
        submissions = self.submissions()
        abandonments = self.abandonments()
        accepted_by_commit = {
            row["commit_request"]["commit_request_digest"]: row for row in result
        }
        abandoned_by_submission = {
            row["submission_record_digest"]: row for row in abandonments
        }
        expected_generation = 1
        pending = 0
        for index, submission in enumerate(submissions):
            accepted = accepted_by_commit.get(
                submission["commit_request"]["commit_request_digest"]
            )
            abandoned = abandoned_by_submission.get(submission["record_digest"])
            if submission["generation"] != expected_generation:
                raise AnchorProtocolError("anchor submission generation is not contiguous")
            if accepted is not None and abandoned is not None:
                raise AnchorProtocolError("anchor submission has conflicting resolutions")
            if accepted is not None:
                if accepted["commit_request"] != submission["commit_request"]:
                    raise AnchorProtocolError(
                        "anchor accepted record changed its submission"
                    )
                expected_generation += 1
            elif abandoned is None:
                pending += 1
                if index != len(submissions) - 1:
                    raise AnchorProtocolError("anchor pending submission is not last")
        if pending > 1 or expected_generation != len(result) + 1:
            raise AnchorProtocolError("anchor submission audit is not contiguous")
        if set(accepted_by_commit) != {
            row["commit_request"]["commit_request_digest"]
            for row in submissions
            if row["commit_request"]["commit_request_digest"] in accepted_by_commit
        } or set(abandoned_by_submission) - {
            row["record_digest"] for row in submissions
        }:
            raise AnchorProtocolError("anchor resolution has no submitted request")
        known = {
            path
            for path in self.path.iterdir()
            if path.name[:1].isdigit()
            or path.name.startswith("submission-")
            or path.name.startswith("abandonment-")
            or path.name == ".collector.lock"
        }
        if any(path not in known for path in self.path.iterdir()):
            raise AnchorProtocolError("anchor receipt audit contains an unknown file")
        return result

    def submissions(self) -> list[dict[str, Any]]:
        self._require_directory(create=False)
        result: list[dict[str, Any]] = []
        paths = sorted(
            path for path in self.path.iterdir() if path.name.startswith("submission-")
        )
        for expected_ordinal, path in enumerate(paths, start=1):
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.expected_owner_uid
                or info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise AnchorProtocolError("anchor submission record is unsafe")
            value = _strict_json(path.read_bytes(), label="stored anchor submission")
            if (
                set(value)
                != {
                    "format",
                    "attempt_ordinal",
                    "generation",
                    "challenge_request",
                    "challenge",
                    "commit_request",
                    "record_digest",
                }
                or value["format"] != SUBMISSION_RECORD_FORMAT
                or value["attempt_ordinal"] != expected_ordinal
                or type(value["generation"]) is not int
                or value["generation"] < 1
                or value["record_digest"]
                != _digest({name: value[name] for name in value if name != "record_digest"})
                or path.name
                != f"submission-{expected_ordinal:020d}-{value['record_digest'].removeprefix('sha256:')}.json"
            ):
                raise AnchorProtocolError("stored anchor submission digest drifted")
            result.append(value)
        return result

    def abandonments(self) -> list[dict[str, Any]]:
        self._require_directory(create=False)
        result: list[dict[str, Any]] = []
        paths = sorted(
            path for path in self.path.iterdir() if path.name.startswith("abandonment-")
        )
        observed_ordinals: set[int] = set()
        for path in paths:
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.expected_owner_uid
                or info.st_gid != self.expected_owner_gid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise AnchorProtocolError("anchor abandonment record is unsafe")
            value = _strict_json(path.read_bytes(), label="stored anchor abandonment")
            if set(value) != {
                "format",
                "attempt_ordinal",
                "generation",
                "submission_record_digest",
                "resolution_request",
                "resolution_response",
                "record_digest",
            } or value["format"] != ABANDONMENT_RECORD_FORMAT:
                raise AnchorProtocolError("stored anchor abandonment fields drifted")
            ordinal = value["attempt_ordinal"]
            if (
                type(ordinal) is not int
                or ordinal < 1
                or ordinal in observed_ordinals
                or type(value["generation"]) is not int
                or value["generation"] < 1
                or value["record_digest"]
                != _digest({name: value[name] for name in value if name != "record_digest"})
                or path.name
                != f"abandonment-{ordinal:020d}-{value['record_digest'].removeprefix('sha256:')}.json"
            ):
                raise AnchorProtocolError("stored anchor abandonment digest drifted")
            observed_ordinals.add(ordinal)
            result.append(value)
        return result

    def pending_submission(self) -> dict[str, Any] | None:
        submissions = self.submissions()
        records = self.records()
        accepted = {
            row["commit_request"]["commit_request_digest"] for row in records
        }
        abandoned = {
            row["submission_record_digest"] for row in self.abandonments()
        }
        pending = [
            row for row in submissions
            if row["commit_request"]["commit_request_digest"] not in accepted
            and row["record_digest"] not in abandoned
        ]
        if len(pending) > 1:
            raise AnchorProtocolError("multiple anchor submissions are pending")
        return pending[0] if pending else None

    def _write_create_only(self, path: Path, raw: bytes, *, collision: str) -> None:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise AnchorProtocolError(collision) from exc
        try:
            os.fchmod(descriptor, 0o600)
            os.fchown(descriptor, self.expected_owner_uid, self.expected_owner_gid)
            written = 0
            while written < len(raw):
                count = os.write(descriptor, raw[written:])
                if count <= 0:
                    raise AnchorProtocolError("anchor local audit write stalled")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(self.path, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def append_submission(
        self, *, challenge_request: Mapping[str, Any], challenge: Mapping[str, Any],
        commit_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Durably retain the exact idempotent request before remote commit."""

        self._require_collector_lock()
        self._require_directory(create=True)
        generation = commit_request["generation"]
        existing = self.submissions()
        if self.pending_submission() is not None:
            raise AnchorProtocolError("an anchor submission is already pending")
        if type(generation) is not int or generation != len(self.records()) + 1:
            raise AnchorProtocolError("anchor submission generation is not contiguous")
        attempt_ordinal = len(existing) + 1
        body = {
            "format": SUBMISSION_RECORD_FORMAT,
            "attempt_ordinal": attempt_ordinal,
            "generation": generation,
            "challenge_request": dict(challenge_request),
            "challenge": dict(challenge),
            "commit_request": dict(commit_request),
        }
        record = {**body, "record_digest": _digest(body)}
        path = self.path / (
            f"submission-{attempt_ordinal:020d}-"
            f"{record['record_digest'].removeprefix('sha256:')}.json"
        )
        self._write_create_only(
            path,
            canonical_json_bytes(record),
            collision="anchor submission audit append collided",
        )
        reread = self.submissions()[-1]
        if reread != record:
            raise AnchorProtocolError("anchor submission audit readback mismatch")
        return reread

    def append_abandonment(
        self, *, submission: Mapping[str, Any],
        resolution_request: Mapping[str, Any],
        resolution_response: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._require_collector_lock()
        self._require_directory(create=True)
        pending = self.pending_submission()
        if pending != submission or resolution_response.get("status") != "NOT_ACCEPTED":
            raise AnchorProtocolError("anchor abandonment is not the exact pending request")
        body = {
            "format": ABANDONMENT_RECORD_FORMAT,
            "attempt_ordinal": submission["attempt_ordinal"],
            "generation": submission["generation"],
            "submission_record_digest": submission["record_digest"],
            "resolution_request": dict(resolution_request),
            "resolution_response": dict(resolution_response),
        }
        record = {**body, "record_digest": _digest(body)}
        path = self.path / (
            f"abandonment-{submission['attempt_ordinal']:020d}-"
            f"{record['record_digest'].removeprefix('sha256:')}.json"
        )
        self._write_create_only(
            path,
            canonical_json_bytes(record),
            collision="anchor abandonment audit append collided",
        )
        reread = next(
            row for row in self.abandonments()
            if row["attempt_ordinal"] == submission["attempt_ordinal"]
        )
        if reread != record:
            raise AnchorProtocolError("anchor abandonment audit readback mismatch")
        self.records()
        return reread

    def append(
        self, *, challenge_request: Mapping[str, Any], challenge: Mapping[str, Any],
        commit_request: Mapping[str, Any], receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._require_collector_lock()
        self._require_directory(create=True)
        generation = receipt["generation"]
        pending = self.pending_submission()
        if (
            type(generation) is not int
            or generation != len(self.records()) + 1
            or pending is None
            or pending["commit_request"] != commit_request
        ):
            raise AnchorProtocolError("anchor local audit generation is not contiguous")
        body = {
            "format": AUDIT_RECORD_FORMAT,
            "challenge_request": dict(challenge_request),
            "challenge": dict(challenge),
            "commit_request": dict(commit_request),
            "receipt": dict(receipt),
        }
        record = {**body, "record_digest": _digest(body)}
        raw = canonical_json_bytes(record)
        name = f"{generation:020d}-{record['record_digest'].removeprefix('sha256:')}.json"
        path = self.path / name
        self._write_create_only(
            path, raw, collision="anchor receipt audit append collided"
        )
        reread = self.records()[-1]
        if reread != record:
            raise AnchorProtocolError("anchor receipt audit readback mismatch")
        return reread


def _reverify_audit_record(
    record: Mapping[str, Any], *, registry: AnchorKeyRegistry,
    client_public_key: Ed25519PublicKey, client_key_id: str,
    expected_generation: int, expected_prior_anchor_digest: str | None,
    previous_candidate: Mapping[str, Any] | None,
    previous_attempts: list[dict[str, Any]],
    previous_runs: list[dict[str, Any]],
    previous_events: list[dict[str, Any]],
) -> tuple[
    dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]],
    list[dict[str, Any]],
]:
    request = _validate_challenge_request(
        canonical_json_bytes(record["challenge_request"]),
        client_keys={client_key_id: client_public_key},
    )
    candidate = _validate_anchor_candidate(record["commit_request"]["anchor_candidate"])
    receipt_time = _parse_time(
        record["receipt"]["accepted_at"], label="stored receipt accepted_at"
    )
    challenge = _validate_challenge(
        canonical_json_bytes(record["challenge"]), registry=registry,
        challenge_request=request, candidate=candidate,
        expected_generation=expected_generation,
        expected_prior_anchor_digest=expected_prior_anchor_digest,
        now=receipt_time,
    )
    commit = _validate_commit_request(
        canonical_json_bytes(record["commit_request"]),
        client_keys={client_key_id: client_public_key},
    )
    if (
        commit["challenge_digest"] != challenge["challenge_digest"]
        or commit["challenge_nonce"] != challenge["nonce"]
        or commit["generation"] != challenge["generation"]
        or commit["prior_anchor_digest"] != challenge["prior_anchor_digest"]
        or commit["anchor_candidate_digest"] != challenge["anchor_candidate_digest"]
    ):
        raise AnchorProtocolError("stored anchor commit lineage drifted")
    attempts, runs, events = _verify_lineage_proof(
        commit["lineage_proof"],
        candidate=candidate,
        previous_candidate=previous_candidate,
        previous_attempts=previous_attempts,
        previous_runs=previous_runs,
        previous_events=previous_events,
        prior_anchor_digest=expected_prior_anchor_digest,
    )
    receipt = _validate_receipt(
        canonical_json_bytes(record["receipt"]), registry=registry,
        challenge=challenge, commit_request=commit, candidate=candidate,
        now=receipt_time,
    )
    return receipt, candidate, attempts, runs, events


def _reverify_abandonment(
    abandonment: Mapping[str, Any], *, submission: Mapping[str, Any],
    registry: AnchorKeyRegistry, client_public_key: Ed25519PublicKey,
    client_key_id: str, expected_generation: int,
    expected_prior_anchor_digest: str | None,
    previous_candidate: Mapping[str, Any] | None,
    previous_attempts: list[dict[str, Any]], previous_runs: list[dict[str, Any]],
    previous_events: list[dict[str, Any]],
) -> None:
    if (
        abandonment["attempt_ordinal"] != submission["attempt_ordinal"]
        or abandonment["generation"] != submission["generation"]
        or abandonment["submission_record_digest"] != submission["record_digest"]
    ):
        raise AnchorProtocolError("stored anchor abandonment changed its submission")
    challenge_request = _validate_challenge_request(
        canonical_json_bytes(submission["challenge_request"]),
        client_keys={client_key_id: client_public_key},
    )
    candidate = _validate_anchor_candidate(
        submission["commit_request"]["anchor_candidate"]
    )
    challenge = _validate_challenge(
        canonical_json_bytes(submission["challenge"]),
        registry=registry,
        challenge_request=challenge_request,
        candidate=candidate,
        expected_generation=expected_generation,
        expected_prior_anchor_digest=expected_prior_anchor_digest,
        now=_parse_time(submission["challenge"]["issued_at"], label="issued_at"),
    )
    commit_request = _validate_commit_request(
        canonical_json_bytes(submission["commit_request"]),
        client_keys={client_key_id: client_public_key},
    )
    if (
        commit_request["challenge_digest"] != challenge["challenge_digest"]
        or commit_request["challenge_nonce"] != challenge["nonce"]
    ):
        raise AnchorProtocolError("abandoned anchor commit lineage drifted")
    _verify_lineage_proof(
        commit_request["lineage_proof"],
        candidate=candidate,
        previous_candidate=previous_candidate,
        previous_attempts=previous_attempts,
        previous_runs=previous_runs,
        previous_events=previous_events,
        prior_anchor_digest=expected_prior_anchor_digest,
    )
    resolution_request = _validate_resolution_request(
        canonical_json_bytes(abandonment["resolution_request"]),
        client_keys={client_key_id: client_public_key},
    )
    if any(
        resolution_request[name] != commit_request[name]
        for name in (
            "journal_instance_id",
            "generation",
            "prior_anchor_digest",
            "challenge_digest",
            "commit_request_digest",
        )
    ):
        raise AnchorProtocolError("anchor abandonment request lineage drifted")
    response_time = _parse_time(
        abandonment["resolution_response"]["resolved_at"],
        label="abandonment resolved_at",
    )
    response = _validate_resolution_response(
        canonical_json_bytes(abandonment["resolution_response"]),
        registry=registry,
        resolution_request=resolution_request,
        challenge=challenge,
        commit_request=commit_request,
        candidate=candidate,
        now=response_time,
    )
    if response["status"] != "NOT_ACCEPTED":
        raise AnchorProtocolError("anchor abandonment contains an accepted response")
