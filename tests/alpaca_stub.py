"""Alpaca'yi taklit eden yerel HTTP sunucusu.

Bu sunucu, gercek alpaca-py istemcisinin konustugu adresi
degistirerek kullaniliyor. Amac Alpaca'nin davranisini dogrulamak
DEGIL - onu zaten dogrulayamayiz. Amac, bizim kodumuzun HTTP
yuzeyini dogrulamak:

  * gonderdigimiz istek dogru mu kuruluyor (ozellikle bracket emri)
  * Alpaca'nin dondurdugu sekildeki yanitlari dogru ayristiriyor muyuz
  * hata yollari dogru sarmalaniyor mu

Cevrimdisi birim testleri bu yuzeyi goremez: sahte nesneler bizim
varsaydigimiz sekli dondurur, gercek istemcinin serilestirmesini ve
model ayristirmasini atlar. Bir Timeframe cevrim hatasi tam olarak
bu bosluktan kacmisti.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

ACCOUNT: dict[str, Any] = {
    "id": "904837e3-3b76-47ec-b432-046db621571b",
    "account_number": "PA3ALPACA",
    "status": "ACTIVE",
    "currency": "USD",
    "cash": "98750.25",
    "portfolio_value": "101234.56",
    "equity": "101234.56",
    "last_equity": "100000.00",
    "buying_power": "197500.50",
    "daytrade_count": 2,
    "pattern_day_trader": False,
    "trading_blocked": False,
    "account_blocked": False,
    "transfers_blocked": False,
    "trade_suspended_by_user": False,
    "shorting_enabled": True,
    "multiplier": "2",
    "long_market_value": "2484.31",
    "short_market_value": "0",
    "initial_margin": "1242.15",
    "maintenance_margin": "745.29",
    "sma": "0",
    "created_at": "2025-01-01T00:00:00Z",
}

POSITIONS: list[dict[str, Any]] = [
    {
        "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "asset_class": "us_equity",
        "avg_entry_price": "220.50",
        # Kesirli pozisyon: int()'e dusurulurse kaybolurdu.
        "qty": "10.5",
        "qty_available": "10.5",
        "side": "long",
        "market_value": "2484.31",
        "cost_basis": "2315.25",
        "unrealized_pl": "169.06",
        "unrealized_plpc": "0.073",
        "current_price": "236.60",
        "lastday_price": "234.00",
        "change_today": "0.011",
    },
    {
        "asset_id": "c1c7ee9e-9c9c-49aa-bb57-c0e65a17f526",
        "symbol": "TSLA",
        "exchange": "NASDAQ",
        "asset_class": "us_equity",
        "avg_entry_price": "300.00",
        # Short pozisyon negatif miktarla bildirilir.
        "qty": "-5",
        "qty_available": "-5",
        "side": "short",
        "market_value": "-1480.00",
        "cost_basis": "-1500.00",
        "unrealized_pl": "20.00",
        "unrealized_plpc": "0.013",
        "current_price": "296.00",
        "lastday_price": "298.00",
        "change_today": "-0.007",
    },
]

CLOCK: dict[str, Any] = {
    "timestamp": "2026-01-05T10:30:00-05:00",
    "is_open": True,
    "next_open": "2026-01-06T09:30:00-05:00",
    "next_close": "2026-01-05T16:00:00-05:00",
}


# Alpaca emir kimlikleri UUID; istemci bunu dogruluyor. Okunabilir
# olsun diye sabit ve konusan UUID'ler kullaniliyor.
ENTRY_ID = "11111111-1111-4111-8111-111111111111"
TARGET_LEG_ID = "22222222-2222-4222-8222-222222222222"
STOP_LEG_ID = "33333333-3333-4333-8333-333333333333"
OPEN_ID = "44444444-4444-4444-8444-444444444444"
NEW_ID = "55555555-5555-4555-8555-555555555555"
CLOSE_ID = "66666666-6666-4666-8666-666666666666"


def _order(
    *,
    order_id: str,
    client_order_id: str,
    symbol: str = "SPY",
    side: str = "buy",
    status: str = "new",
    order_type: str = "limit",
    qty: str = "100",
    filled_qty: str = "0",
    filled_avg_price: str | None = None,
    filled_at: str | None = None,
    legs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": order_id,
        "client_order_id": client_order_id,
        "created_at": "2026-01-05T14:51:00Z",
        "updated_at": "2026-01-05T14:51:00Z",
        "submitted_at": "2026-01-05T14:51:00Z",
        "filled_at": filled_at,
        "expired_at": None,
        "canceled_at": None,
        "failed_at": None,
        "replaced_at": None,
        "replaced_by": None,
        "replaces": None,
        "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "symbol": symbol,
        "asset_class": "us_equity",
        "notional": None,
        "qty": qty,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "order_class": "bracket",
        "order_type": order_type,
        "type": order_type,
        "side": side,
        "time_in_force": "day",
        "limit_price": "100.85",
        "stop_price": None,
        "status": status,
        "extended_hours": False,
        "legs": legs or [],
        "trail_percent": None,
        "trail_price": None,
        "hwm": None,
    }


FILLED_BRACKET = _order(
    order_id=ENTRY_ID,
    client_order_id="tlab-abc123",
    status="filled",
    filled_qty="100",
    filled_avg_price="100.85",
    filled_at="2026-01-05T14:52:00Z",
    legs=[
        _order(
            order_id=TARGET_LEG_ID,
            client_order_id="alpaca-leg-1",
            side="sell",
            status="filled",
            order_type="limit",
            qty="100",
            filled_qty="100",
            filled_avg_price="102.88",
            filled_at="2026-01-05T15:20:00Z",
        ),
        _order(
            order_id=STOP_LEG_ID,
            client_order_id="alpaca-leg-2",
            side="sell",
            status="canceled",
            order_type="stop",
            qty="100",
        ),
    ],
)

OPEN_ORDER = _order(order_id=OPEN_ID, client_order_id="tlab-open-1")

BARS: dict[str, Any] = {
    "bars": {
        "SPY": [
            {
                "t": "2026-01-05T14:30:00Z",
                "o": 100.1,
                "h": 100.6,
                "l": 99.8,
                "c": 100.4,
                "v": 12345,
                "n": 87,
                "vw": 100.3,
            },
            {
                "t": "2026-01-05T14:31:00Z",
                "o": 100.4,
                "h": 100.9,
                "l": 100.2,
                "c": 100.8,
                "v": 23456,
                "n": 120,
                "vw": 100.6,
            },
        ]
    },
    "next_page_token": None,
}

QUOTES: dict[str, Any] = {
    "quotes": {
        "SPY": {
            "t": "2026-01-05T14:31:05.123456789Z",
            "bx": "V",
            "bp": 100.79,
            "bs": 3,
            "ax": "V",
            "ap": 100.81,
            "as": 5,
            "c": ["R"],
            "z": "C",
        }
    }
}


class StubState:
    """Sunucunun gorup kaydettikleri ve dondurecekleri.

    Yanitlar testten degistirilebiliyor: boylece ayni sahte sunucu
    hem sozlesme testlerinde hem de uctan uca senaryolarda
    kullanilabiliyor.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.fail_next: int | None = None
        self.account: dict[str, Any] = dict(ACCOUNT)
        self.positions: list[dict[str, Any]] = [dict(p) for p in POSITIONS]
        self.clock: dict[str, Any] = dict(CLOCK)
        self.open_orders: list[dict[str, Any]] = [OPEN_ORDER]
        self.all_orders: list[dict[str, Any]] = [FILLED_BRACKET]
        self.bars: dict[str, Any] = BARS
        self.quotes: dict[str, Any] = QUOTES

    def record(self, method: str, path: str, body: dict[str, Any] | None) -> None:
        self.requests.append((method, path, body))

    def paths(self) -> list[str]:
        return [urlparse(path).path for _, path, _ in self.requests]

    def body_for(self, path_fragment: str) -> dict[str, Any]:
        for _, path, body in self.requests:
            if path_fragment in path and body is not None:
                return body
        msg = f"{path_fragment} icin govde kaydedilmedi"
        raise AssertionError(msg)

    def query_for(self, path_fragment: str) -> dict[str, list[str]]:
        for _, path, _ in self.requests:
            if path_fragment in path:
                return parse_qs(urlparse(path).query)
        msg = f"{path_fragment} icin istek kaydedilmedi"
        raise AssertionError(msg)


def _handler(state: StubState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, payload: Any, status: int = 200) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _route(self, method: str, body: dict[str, Any] | None) -> None:
            state.record(method, self.path, body)
            if state.fail_next is not None:
                status, state.fail_next = state.fail_next, None
                self._send({"message": "simulated failure"}, status)
                return

            path = urlparse(self.path).path
            query = parse_qs(urlparse(self.path).query)

            if path == "/v2/account":
                self._send(state.account)
            elif path == "/v2/positions":
                self._send(state.positions)
            elif path.startswith("/v2/positions/"):
                self._send(_order(order_id=CLOSE_ID, client_order_id="close-1", side="sell"))
            elif path == "/v2/clock":
                self._send(state.clock)
            elif path == "/v2/orders":
                if method == "POST":
                    self._send(
                        _order(
                            order_id=NEW_ID,
                            client_order_id=str((body or {}).get("client_order_id", "unknown")),
                        )
                    )
                elif method == "DELETE":
                    self._send([{"id": OPEN_ID, "status": 200}])
                elif query.get("status") == ["all"]:
                    self._send(state.all_orders)
                else:
                    self._send(state.open_orders)
            elif path.startswith("/v2/orders/"):
                self._send({}, 204)
            elif path == "/v2/stocks/bars":
                self._send(state.bars)
            elif path == "/v2/stocks/quotes/latest":
                self._send(state.quotes)
            else:
                self._send({"message": f"bilinmeyen yol: {path}"}, 404)

        def do_GET(self) -> None:
            self._route("GET", None)

        def do_DELETE(self) -> None:
            self._route("DELETE", None)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            self._route("POST", json.loads(raw or b"{}"))

        def log_message(self, *args: Any) -> None:
            """Test ciktisini bogmamak icin sessiz."""

    return Handler


@contextmanager
def alpaca_stub() -> Iterator[tuple[str, StubState]]:
    """Sahte Alpaca sunucusunu baslatir, (adres, durum) dondurur."""
    state = StubState()
    # Coklu is parcacigi sart: istemci HTTP/1.1 keep-alive kullaniyor
    # ve baglantiyi acik tutuyor. Tek is parcacikli bir sunucu, ikinci
    # baglantiyi beklerken kilitlenir.
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def bar_payload(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Alpaca bar yaniti bicimine sarar."""
    return {"bars": {symbol: bars}, "next_page_token": None}


def quote_payload(symbol: str, *, bid: float, ask: float, ts: str) -> dict[str, Any]:
    return {
        "quotes": {
            symbol: {
                "t": ts,
                "bx": "V",
                "bp": bid,
                "bs": 3,
                "ax": "V",
                "ap": ask,
                "as": 5,
                "c": ["R"],
                "z": "C",
            }
        }
    }
