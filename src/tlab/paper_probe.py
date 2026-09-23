"""Read-only paper connectivity probe; never prints responses or credentials.

Standalone stdlib transport keeps this diagnostic independent of the trading
engine. Endpoints are fixed, redirects are not followed, and only GET is used.
This is a connectivity check, not an SDK/order lifecycle certification.

BAGIMLILIK ISTEMEZ - ve bu tesaduf degil, tasarimin kendisi. Bu arac tam
da baska seyler bozukken "anahtarlar ve ag saglam mi" sorusunu
cevaplayabilmek icin var; kurulum gerektirseydi, kurulumun bozuk oldugu
durumda susardi.

Bu yuzden modul `tlab` paketinin KOKUNDE duruyor, `data/` altinda degil:
`tlab.data` paketi ice aktarildiginda onbellek modulu uzerinden pandas'i
da cekiyor. Bir kez yasandi - ilk gercek kosuda
"ModuleNotFoundError: No module named 'pandas'" ile dustu.
`tests/test_architecture.py` artik bu sinirin korundugunu denetliyor.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from http.client import HTTPException, HTTPSConnection
from typing import Any
from urllib.parse import urlencode


class ProbeError(Exception):
    """Contains only a locally generated, non-sensitive diagnostic."""


def _get(host: str, path: str, headers: dict[str, str]) -> dict[str, Any]:
    connection = HTTPSConnection(host, timeout=15)
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ProbeError(f"HTTP {response.status}")
        body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise ProbeError("response too large")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ProbeError("unexpected response shape")
        return payload
    except (OSError, HTTPException, ValueError):
        raise ProbeError("network/TLS/response error") from None
    finally:
        connection.close()


def run(key: str, secret: str, now: datetime) -> int:
    key, secret = key.strip(), secret.strip()
    if not key or not secret:
        print("FAIL configuration: paper key and secret are required")
        return 1
    if any(not 33 <= ord(char) <= 126 for value in (key, secret) for char in value):
        print("FAIL configuration: key/secret contains invalid characters")
        return 1
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    if now.tzinfo is None or now.utcoffset() is None:
        print("FAIL configuration: timezone required")
        return 1
    query = urlencode(
        {
            "timeframe": "1Day",
            "feed": "iex",
            "limit": "1",
            "start": (now - timedelta(days=10)).isoformat(),
            "end": (now - timedelta(minutes=20)).isoformat(),
        }
    )
    failures = 0
    for label, host, path in (
        ("paper account", "paper-api.alpaca.markets", "/v2/account"),
        ("market clock", "paper-api.alpaca.markets", "/v2/clock"),
        ("IEX daily bars", "data.alpaca.markets", "/v2/stocks/SPY/bars?" + query),
    ):
        try:
            payload = _get(host, path, headers)
            if label == "paper account":
                if payload.get("status") != "ACTIVE":
                    raise ProbeError("account not active")
                if any(
                    payload.get(field) is not False
                    for field in ("trading_blocked", "account_blocked")
                ):
                    raise ProbeError("account blocked or flags missing")
            elif label == "market clock":
                if not isinstance(payload.get("is_open"), bool):
                    raise ProbeError("clock response incomplete")
            elif not isinstance(payload.get("bars"), list) or not payload["bars"]:
                raise ProbeError("no bar data returned")
            print(f"OK {label}")
        except ProbeError as exc:
            print(f"FAIL {label}: {exc}")
            failures += 1
    return int(failures > 0)


def main() -> int:
    return run(
        os.environ.get("ALPACA_PAPER_API_KEY", ""),
        os.environ.get("ALPACA_PAPER_SECRET_KEY", ""),
        # Duvar saati bilincli: burasi karar yolu degil, bir baglanti
        # tanisi. Clock enjekte etmek `tlab.core`'u - dolayisiyla
        # pydantic'i - zorunlu kilardi ve aracin bagimsizligini bozardi.
        datetime.now(UTC),
    )


if __name__ == "__main__":
    raise SystemExit(main())
