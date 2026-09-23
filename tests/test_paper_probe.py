"""Real HTTP transport against a local server; no real credentials or orders."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from tlab.data import paper_probe

NOW = datetime(2026, 9, 21, 14, tzinfo=UTC)


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {"status": 200, "requests": [], "hosts": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

        def do_GET(self) -> None:
            state["requests"].append((self.command, self.path, dict(self.headers)))
            self.send_response(state["status"])
            self.send_header("Location", "https://example.invalid/never-follow")
            self.end_headers()
            data = {
                "status": "ACTIVE",
                "trading_blocked": False,
                "account_blocked": False,
                "is_open": False,
                "bars": [{"c": 1}],
                "sensitive": "DO-NOT-PRINT",
            }
            self.wfile.write(state.get("body", json.dumps(data).encode()))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def local_connection(host: str, timeout: int) -> HTTPConnection:
        state["hosts"].append(host)
        return HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)

    monkeypatch.setattr(paper_probe, "HTTPSConnection", local_connection)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_only_fixed_gets_and_no_sensitive_output(
    endpoint: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert paper_probe.run("dummy-key", "dummy-secret", NOW) == 0
    assert endpoint["hosts"] == [
        "paper-api.alpaca.markets",
        "paper-api.alpaca.markets",
        "data.alpaca.markets",
    ]
    assert [request[0] for request in endpoint["requests"]] == ["GET"] * 3
    assert endpoint["requests"][0][1] == "/v2/account"
    assert endpoint["requests"][1][1] == "/v2/clock"
    assert endpoint["requests"][2][1].startswith("/v2/stocks/SPY/bars?")
    assert endpoint["requests"][0][2]["APCA-API-SECRET-KEY"] == "dummy-secret"
    output = capsys.readouterr().out
    assert "OK paper account" in output
    assert all(value not in output for value in ("dummy-key", "dummy-secret", "DO-NOT-PRINT"))


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_http_failure_and_redirect_do_not_leak_or_follow(
    endpoint: dict[str, Any], capsys: pytest.CaptureFixture[str], status: int
) -> None:
    endpoint["status"] = status
    assert paper_probe.run("dummy-key", "dummy-secret", NOW) == 1
    assert len(endpoint["requests"]) == 3
    assert "DO-NOT-PRINT" not in capsys.readouterr().out


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"{}", b"x" * 1_000_001])
def test_bad_response_fails_safely(endpoint: dict[str, Any], body: bytes) -> None:
    endpoint["body"] = body
    assert paper_probe.run("dummy-key", "dummy-secret", NOW) == 1


def test_missing_credentials_make_no_requests(endpoint: dict[str, Any]) -> None:
    assert paper_probe.run("", "", NOW) == 1
    assert not endpoint["requests"]


def test_network_error_hides_exception_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(self: HTTPConnection, *args: Any, **kwargs: Any) -> None:
        raise TimeoutError("DO-NOT-PRINT")

    monkeypatch.setattr(HTTPConnection, "request", fail)
    assert paper_probe.run("dummy-key", "dummy-secret", NOW) == 1
    assert "DO-NOT-PRINT" not in capsys.readouterr().out


def test_pasted_credentials_are_trimmed(endpoint: dict[str, Any]) -> None:
    assert paper_probe.run(" dummy-key\n", "\tdummy-secret\r\n", NOW) == 0
    for _, _, headers in endpoint["requests"]:
        assert headers["APCA-API-KEY-ID"] == "dummy-key"
        assert headers["APCA-API-SECRET-KEY"] == "dummy-secret"


@pytest.mark.parametrize("invalid", ["dummy\nkey", "dummy\x00key", "dummy key", "dummy\u0131key"])
@pytest.mark.parametrize("field", ["key", "secret"])
def test_invalid_credentials_fail_before_network(
    endpoint: dict[str, Any], capsys: pytest.CaptureFixture[str], invalid: str, field: str
) -> None:
    key, secret = (invalid, "dummy-secret") if field == "key" else ("dummy-key", invalid)
    assert paper_probe.run(key, secret, NOW) == 1
    assert not endpoint["requests"]
    output = capsys.readouterr().out
    assert "FAIL configuration:" in output
    assert invalid not in output
