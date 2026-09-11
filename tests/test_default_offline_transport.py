"""Project wiring for default pytest-socket (test execution only)."""

import pytest
import pytest_socket

from ingestion.common.http import LocalHttpClient


def test_local_http_client_without_transport_raises_socket_blocked(pytestconfig):
    assert pytestconfig.getoption("disable_socket"), (
        "expected --disable-socket in default addopts before any request"
    )
    assert pytestconfig.getoption("force_enable_socket") is False
    assert not pytestconfig.getoption("allow_hosts")
    with pytest.warns(UserWarning, match="A test tried to use socket."):
        with pytest.raises(pytest_socket.SocketBlockedError):
            with LocalHttpClient(transport=None, trust_env=False, timeout=0.1) as client:
                client.get("http://192.0.2.1/")
