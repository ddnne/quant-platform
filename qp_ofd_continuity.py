"""Portable continuity cookies for duplicated POSIX file descriptors.

The cookie is an ABA-reuse sentinel, not an authentication secret.  It is
stored only in the shared seek position of an open file description and is
deliberately capped at the largest positive signed 32-bit offset, including
the one-byte validation probe.  Some valid filesystems reject otherwise valid
64-bit ``off_t`` positions above their own maximum file size.

This neutral root module is importable from both the installed product package
and the protected ``python -I`` runtime bundle, which adds only its immutable
bundle root to ``sys.path``.
"""

from __future__ import annotations

import os


_OFD_COOKIE_MIN = 3
_OFD_COOKIE_MAX = (1 << 31) - 2
_OFD_COOKIE_SPAN = _OFD_COOKIE_MAX - _OFD_COOKIE_MIN + 1


def new_portable_ofd_continuity_cookie_v2() -> int:
    """Return a non-zero ABA sentinel whose validation probe is 32-bit safe."""

    return _OFD_COOKIE_MIN + int.from_bytes(os.urandom(8), "big") % (
        _OFD_COOKIE_SPAN
    )
