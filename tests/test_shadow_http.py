"""Golge gozlemin HTTP yuzeyi (docs/designs/shadow-observation.md §3).

Kodda ad aramak yetmez: bu testler gercek alpaca-py istemcisini yerel
sahte sunucuya yonlendirir ve dongunun butun turlari boyunca sunucuya
NE geldigini kaydeder. Gosterilenler:

  * hesap, pozisyon, emir, dolum ve hesap etkinligi uclarina HIC istek
    gelmez; gelenler acik izin listesindedir (takvim, saat, bar,
    son kotasyon);
  * 401/403/429/5xx yollarinda tur dusmez, kayit "bilinmiyor" der,
    yasak uca yonelinmez ve anahtar ya da yanit govdesi loglara sizmaz.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpaca_stub import StubState, alpaca_stub, bar_payload
from conftest import make_bars
from tlab.config import Config, load_config
from tlab.core.clock import SimClock
from tlab.data.market import AlpacaMarketData
from tlab.engine.runner import SessionRunner
from tlab.errors import BrokerError
from tlab.execution.alpaca_broker import AlpacaBroker
from tlab.journal.db import apply_migrations, connect
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate
from tlab.shadow.broker import ShadowBroker
from tlab.shadow.record import RecordingMarket, SeenRecord
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
"""Sahte sunucunun takvimindeki ilk gun (09:30 New York, kis saati)."""

MARKERS = {
    "api_key": "SHADOWCANARYKEYAAAA",
    "secret": "SHADOWCANARYSECRETXX",
    "body": "SHADOW-RESPONSE-BODY-CANARY",
}

ALLOWED = {"/v2/calendar", "/v2/clock", "/v2/stocks/bars", "/v2/stocks/quotes/latest"}
FORBIDDEN = ("/v2/account", "/v2/positions", "/v2/orders")
"""`/v2/account/activities` (dolumlar) da `/v2/account` onekiyle yakalanir."""


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as server:
        yield server


@pytest.fixture
def config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text(
        "symbols:\n  - SPY\n  - QQQ\n", encoding="utf-8"
    )
    return load_config(project_root)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    apply_migrations(connection)
    yield connection
    connection.close()


def serve_bars(state: StubState) -> None:
    bars = make_bars(60, start=OPEN, spread=0.5)
    state.bars = bar_payload(
        "SPY",
        [
            {
                "t": bar.ts.isoformat().replace("+00:00", "Z"),
                "o": bar.open,
                "h": bar.high,
                "l": bar.low,
                "c": bar.close,
                "v": bar.volume,
                "n": bar.trade_count,
                "vw": bar.vwap,
            }
            for bar in bars
        ],
    )


def shadow_runner(
    base_url: str, config: Config, conn: sqlite3.Connection, clock: SimClock, record: SeenRecord
) -> SessionRunner:
    """Golge isinin kuracagi dongu: takvim salt okunur uctan, broker golge."""
    calendar = AlpacaBroker(MARKERS["api_key"], MARKERS["secret"], base_url=base_url).get_calendar(
        date(2026, 1, 5), date(2026, 1, 12)
    )
    market = AlpacaMarketData(MARKERS["api_key"], MARKERS["secret"], base_url=base_url)
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(mode="paper", data_feed="iex", params_version="orb", config={})
    return SessionRunner(
        broker=ShadowBroker(calendar, clock),
        market=RecordingMarket(market, record, clock),
        strategies=[OpeningRangeBreakout(ORBParams())],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
        dry_run=True,
    )


def forbidden(state: StubState) -> list[str]:
    return [path for path in state.paths() if path.startswith(FORBIDDEN)]


def leaked(text: str) -> list[str]:
    return [name for name, marker in MARKERS.items() if marker in text]


# --------------------------------------------------------------------------
# Normal yol
# --------------------------------------------------------------------------


def test_a_shadow_session_touches_only_allowed_endpoints(
    stub: tuple[str, StubState], config: Config, conn: sqlite3.Connection
) -> None:
    base_url, state = stub
    serve_bars(state)
    clock = SimClock(OPEN - timedelta(minutes=2))
    record = SeenRecord(sqlite3.connect(":memory:"))
    runner = shadow_runner(base_url, config, conn, clock, record)

    evaluated = 0
    for minute in (-1, 5, 16, 31, 45):
        clock.set(OPEN + timedelta(minutes=minute, seconds=7))
        evaluated += runner.run_once().evaluated

    assert evaluated > 0
    assert forbidden(state) == []
    assert set(state.paths()) <= ALLOWED
    assert "/v2/stocks/bars" in state.paths()
    # Acilis araligi asamasinda dongu sembol degerlendirmez, bar da istemez.
    assert record.moments("SPY") == [
        OPEN + timedelta(minutes=minute, seconds=7) for minute in (16, 31, 45)
    ]


# --------------------------------------------------------------------------
# Hata yollari
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_a_failing_data_endpoint_is_recorded_as_unknown_without_leaks(
    stub: tuple[str, StubState],
    config: Config,
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    base_url, state = stub
    serve_bars(state)
    body: dict[str, Any] = {
        "message": f"{MARKERS['body']} key={MARKERS['api_key']}",
        "s": MARKERS["secret"],
    }
    state.fail("/v2/stocks/bars", status, times=None, body=body)
    clock = SimClock(OPEN + timedelta(minutes=31, seconds=7))
    record = SeenRecord(sqlite3.connect(":memory:"))
    runner = shadow_runner(base_url, config, conn, clock, record)

    with caplog.at_level(logging.DEBUG):
        result = runner.run_once()

    assert result.evaluated == 0
    assert record.moments("SPY") == [clock.now()]
    assert record.view("SPY", clock.now()) is None
    assert forbidden(state) == []
    assert set(state.paths()) <= ALLOWED
    text = caplog.text + "\n".join(result.notes)
    assert not leaked(text), f"hata yolu sizdiriyor: {leaked(text)}"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_failing_calendar_stops_before_any_data_request(
    stub: tuple[str, StubState], config: Config, conn: sqlite3.Connection, status: int
) -> None:
    """Takvim yoksa dongu kurulmaz; ne veri ne hesap ucuna istek gider.

    Takvim hatasinin metni yanit govdesini tasiyabilir (adaptor boyle
    sarar). Golge isi o metni basmaz, sabit sinifa cevirir; o is
    katmaninin testidir.
    """
    base_url, state = stub
    state.fail("/v2/calendar", status, times=None)
    clock = SimClock(OPEN)
    with pytest.raises(BrokerError):
        shadow_runner(base_url, config, conn, clock, SeenRecord(sqlite3.connect(":memory:")))
    assert state.paths() == ["/v2/calendar"]
