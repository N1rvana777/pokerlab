"""Check the local listener cannot be replaced by another app instance."""
from types import SimpleNamespace

import pytest

from pokerstudio.server import Handler, LocalServer


def test_listener_rejects_second_instance():
    first = LocalServer(("127.0.0.1", 0), SimpleNamespace())
    try:
        with pytest.raises(OSError):
            second = LocalServer(first.server_address, SimpleNamespace())
            second.server_close()
        assert first.socket.fileno() >= 0
    finally:
        first.server_close()


def test_client_disconnect_does_not_attempt_another_response():
    handler = SimpleNamespace(close_connection=False)
    Handler._handle_error(handler, ConnectionAbortedError("client left"))
    assert handler.close_connection is True
