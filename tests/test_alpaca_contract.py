"""Alpaca istemcisiyle sozlesme testleri.

Gercek alpaca-py istemcisi, Alpaca'nin yanit sekillerini taklit eden
yerel bir sunucuya karsi calistiriliyor. Ag erisimi yok; test edilen
sey Alpaca'nin davranisi DEGIL, bizim kodumuzun HTTP yuzeyi:

  * istegi dogru kuruyor muyuz (ozellikle bracket emrinin govdesi)
  * gelen yaniti dogru ayristiriyor muyuz
  * hatalari dogru sarmaliyor muyuz

Cevrimdisi birim testleri bu yuzeyi goremiyor: sahte nesneler bizim
VARSAYDIGIMIZ sekli dondurur ve gercek istemcinin serilestirmesini
atlar. Bir Timeframe cevrim hatasi tam bu bosluktan kacmisti -
`tlab fetch` hicbir zaman calismazdi ve tum testler yesildi.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from alpaca_stub import (
    NEW_ID,
    STOP_LEG_ID,
    TARGET_LEG_ID,
    StubState,
    alpaca_stub,
    bar_payload,
    quote_payload,
)
from tlab.cli import main as cli_main
from tlab.config import load_config
from tlab.core.clock import SimClock
from tlab.core.types import BracketOrder, EntryType, Side, Timeframe
from tlab.data.cache import BarCache
from tlab.data.market import _TIMEFRAME_ARGS, AlpacaMarketData
from tlab.engine.runner import SessionRunner
from tlab.errors import BrokerError, DataError
from tlab.execution.alpaca_broker import AlpacaBroker
from tlab.journal.db import apply_migrations, connect
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


@pytest.fixture
def broker(stub: tuple[str, StubState]) -> AlpacaBroker:
    return AlpacaBroker("PKTEST", "secret", paper=True, base_url=stub[0])


@pytest.fixture
def market(stub: tuple[str, StubState]) -> AlpacaMarketData:
    return AlpacaMarketData("PKTEST", "secret", feed="iex", base_url=stub[0])


# --------------------------------------------------------------------------
# Periyot cevrimi
# --------------------------------------------------------------------------


@pytest.mark.parametrize("timeframe", list(Timeframe))
def test_every_timeframe_maps_to_a_valid_sdk_value(timeframe: Timeframe) -> None:
    """Her periyot gercek SDK tipine cevrilebilmeli.

    Enum'da ADI 'Minute', DEGERI 'Min' ve enum degerle kuruluyor.
    Bu fark yuzunden bar cekme hicbir zaman calismiyordu; buradaki
    dongu ayni hatanin bir daha kacmasini engelliyor.
    """
    amount, unit = _TIMEFRAME_ARGS[timeframe]
    built = TimeFrame(amount, TimeFrameUnit(unit))
    assert built.value == timeframe.value


# --------------------------------------------------------------------------
# Hesap ve pozisyon
# --------------------------------------------------------------------------


def test_account_is_parsed_from_alpaca_shape(broker: AlpacaBroker) -> None:
    account = broker.get_account()
    assert account.equity == pytest.approx(101_234.56)
    assert account.last_equity == pytest.approx(100_000.00)
    assert account.cash == pytest.approx(98_750.25)
    assert account.buying_power == pytest.approx(197_500.50)
    assert account.daytrade_count == 2
    assert account.pattern_day_trader is False
    assert account.currency == "USD"
    assert account.is_healthy
    assert account.daily_pl_pct == pytest.approx(1.23, abs=0.01)


def test_fractional_and_short_positions_survive_parsing(broker: AlpacaBroker) -> None:
    """Kesirli miktar kaybolmamali, short pozisyon yonu dogru okunmali."""
    positions = {position.symbol: position for position in broker.get_positions()}
    assert set(positions) == {"AAPL", "TSLA"}

    apple = positions["AAPL"]
    assert apple.side is Side.BUY
    assert apple.qty == pytest.approx(10.5)
    assert apple.is_fractional

    tesla = positions["TSLA"]
    assert tesla.side is Side.SELL
    assert tesla.qty == pytest.approx(5.0), "miktar pozitif saklanir, yon ayri alanda"
    assert tesla.current_price == pytest.approx(296.00)


def test_market_clock_is_parsed(broker: AlpacaBroker) -> None:
    clock = broker.get_market_clock()
    assert clock.is_open is True
    # Alpaca yerel saat dilimiyle donduruyor; UTC'ye cevirip kontrol
    # ediyoruz. Kodun geri kalani zaten aware datetime ile calisiyor.
    assert clock.next_close.astimezone(UTC).hour == 21  # 16:00 New York = 21:00 UTC


# --------------------------------------------------------------------------
# Emir gonderimi
# --------------------------------------------------------------------------


def bracket() -> BracketOrder:
    return BracketOrder(
        symbol="SPY",
        side=Side.BUY,
        qty=100,
        entry_type=EntryType.LIMIT,
        limit_price=100.85,
        stop_loss=99.50,
        take_profit=102.88,
        client_order_id="tlab-contract-1",
    )


def test_bracket_order_body_is_correct(broker: AlpacaBroker, stub: tuple[str, StubState]) -> None:
    """Brokera giden JSON govdesi dogru olmali.

    Bu testin varlik sebebi dogrudan guvenlik: yanlis kurulmus bir
    bracket ya reddedilir ya da - daha kotusu - korumasiz bir giris
    emri olarak kabul edilir.
    """
    broker.submit_bracket(bracket())
    body = stub[1].body_for("/v2/orders")

    assert body["symbol"] == "SPY"
    assert body["side"] == "buy"
    assert body["qty"] == 100
    assert body["type"] == "limit"
    assert body["limit_price"] == pytest.approx(100.85)
    assert body["time_in_force"] == "day"
    assert body["client_order_id"] == "tlab-contract-1"

    # Koruma emirleri girisle AYNI istekte gidiyor.
    assert body["order_class"] == "bracket"
    assert body["stop_loss"]["stop_price"] == pytest.approx(99.50)
    assert body["take_profit"]["limit_price"] == pytest.approx(102.88)


def test_market_entry_body_has_no_limit_price(
    broker: AlpacaBroker, stub: tuple[str, StubState]
) -> None:
    broker.submit_bracket(
        bracket().model_copy(update={"entry_type": EntryType.MARKET, "limit_price": None})
    )
    body = stub[1].body_for("/v2/orders")
    assert body["type"] == "market"
    assert body.get("limit_price") is None
    assert body["order_class"] == "bracket"


def test_order_response_is_parsed(broker: AlpacaBroker) -> None:
    ref = broker.submit_bracket(bracket())
    assert ref.broker_order_id == NEW_ID
    assert ref.client_order_id == "tlab-contract-1"
    assert ref.symbol == "SPY"
    assert ref.status == "new"
    assert ref.submitted_at.tzinfo is not None


# --------------------------------------------------------------------------
# Emir ve gerceklesme okuma
# --------------------------------------------------------------------------


def test_open_orders_are_parsed(broker: AlpacaBroker, stub: tuple[str, StubState]) -> None:
    orders = broker.list_open_orders()
    assert [order.client_order_id for order in orders] == ["tlab-open-1"]
    assert stub[1].query_for("/v2/orders")["status"] == ["open"]


def test_bracket_legs_are_flattened_into_fills(broker: AlpacaBroker) -> None:
    """Bracket bacaklari ebeveynin ICINDE geliyor.

    Duz bir listede bacaklar kaybolur ve cikislar goremez; mutabakat
    da hicbir islemi kapatamaz.
    """
    fills = broker.list_fills(datetime(2026, 1, 1, tzinfo=UTC))
    assert len(fills) == 2, "giris ve dolan hedef bacagi"

    entry, exit_fill = fills
    assert entry.client_order_id == "tlab-abc123"
    assert entry.side is Side.BUY
    assert entry.price == pytest.approx(100.85)
    assert entry.order_type == "limit"

    assert exit_fill.broker_order_id == TARGET_LEG_ID
    assert exit_fill.side is Side.SELL
    assert exit_fill.price == pytest.approx(102.88)
    # Iptal edilmis stop bacagi dolmadigi icin listede yok.
    assert all(fill.broker_order_id != STOP_LEG_ID for fill in fills)


def test_fills_request_asks_for_nested_orders(
    broker: AlpacaBroker, stub: tuple[str, StubState]
) -> None:
    broker.list_fills(datetime(2026, 1, 1, tzinfo=UTC))
    query = stub[1].query_for("/v2/orders?")
    assert query["nested"] == ["True"]
    assert query["status"] == ["all"]


def test_close_position_and_cancel(broker: AlpacaBroker, stub: tuple[str, StubState]) -> None:
    assert broker.close_position("AAPL") is not None
    assert "/v2/positions/AAPL" in stub[1].paths()
    assert broker.cancel_open_orders() == 1


# --------------------------------------------------------------------------
# Piyasa verisi
# --------------------------------------------------------------------------


def test_bars_are_parsed_and_sorted(market: AlpacaMarketData) -> None:
    bars = market.bars(
        "SPY", Timeframe.M1, datetime(2026, 1, 5, tzinfo=UTC), datetime(2026, 1, 6, tzinfo=UTC)
    )
    assert len(bars) == 2
    assert [bar.ts for bar in bars] == sorted(bar.ts for bar in bars)

    first = bars[0]
    assert first.symbol == "SPY"
    assert first.open == pytest.approx(100.1)
    assert first.high == pytest.approx(100.6)
    assert first.low == pytest.approx(99.8)
    assert first.close == pytest.approx(100.4)
    assert first.volume == pytest.approx(12_345)
    assert first.vwap == pytest.approx(100.3)
    assert first.trade_count == 87


def test_bars_request_carries_feed_and_timeframe(
    market: AlpacaMarketData, stub: tuple[str, StubState]
) -> None:
    market.bars("SPY", Timeframe.M5, datetime(2026, 1, 5, tzinfo=UTC))
    query = stub[1].query_for("/v2/stocks/bars")
    assert query["symbols"] == ["SPY"]
    assert query["timeframe"] == ["5Min"]
    assert query["feed"] == ["iex"]


def test_latest_quote_is_parsed(market: AlpacaMarketData) -> None:
    quote = market.latest_quote("SPY")
    assert quote.bid == pytest.approx(100.79)
    assert quote.ask == pytest.approx(100.81)
    assert quote.spread_bps == pytest.approx(1.98, abs=0.05)
    assert not quote.is_crossed


def test_naive_dates_are_rejected_before_the_request(market: AlpacaMarketData) -> None:
    with pytest.raises(DataError, match="timezone"):
        market.bars("SPY", Timeframe.M1, datetime(2026, 1, 5))


# --------------------------------------------------------------------------
# Hata yollari
# --------------------------------------------------------------------------


def test_server_error_becomes_a_broker_error(
    broker: AlpacaBroker, stub: tuple[str, StubState]
) -> None:
    """Ham HTTP hatasi disari sizmamali; katman kendi tipine sarmali."""
    stub[1].fail_next = 500
    with pytest.raises(BrokerError, match="Hesap bilgisi alinamadi"):
        broker.get_account()


def test_rejected_order_becomes_a_broker_error(
    broker: AlpacaBroker, stub: tuple[str, StubState]
) -> None:
    stub[1].fail_next = 422
    with pytest.raises(BrokerError, match="emri gonderilemedi"):
        broker.submit_bracket(bracket())


def test_data_error_is_wrapped(market: AlpacaMarketData, stub: tuple[str, StubState]) -> None:
    stub[1].fail_next = 500
    with pytest.raises(DataError, match="bar verisi alinamadi"):
        market.bars("SPY", Timeframe.M1, datetime(2026, 1, 5, tzinfo=UTC))


def test_timeouts_and_retries_do_not_leak_raw_exceptions(
    broker: AlpacaBroker, stub: tuple[str, StubState]
) -> None:
    stub[1].fail_next = 503
    with pytest.raises(BrokerError):
        broker.get_positions()


def test_recovery_after_a_failure(broker: AlpacaBroker, stub: tuple[str, StubState]) -> None:
    """Gecici hata sonrasi bir sonraki cagri calismali.

    Gozetimsiz calisan bir sistemde tek bir hata kalici bir bozulmaya
    donusmemeli.
    """
    stub[1].fail_next = 500
    with pytest.raises(BrokerError):
        broker.get_account()
    assert broker.get_account().equity == pytest.approx(101_234.56)


def test_unexpected_timeframe_for_the_range(market: AlpacaMarketData) -> None:
    bars = market.bars(
        "SPY",
        Timeframe.D1,
        datetime(2026, 1, 5, tzinfo=UTC) - timedelta(days=30),
        datetime(2026, 1, 6, tzinfo=UTC),
    )
    assert len(bars) == 2


# --------------------------------------------------------------------------
# Uctan uca canli yol
# --------------------------------------------------------------------------
#
# Asagidaki test, sistemin TAMAMINI gercek Alpaca istemcisiyle
# calistiriyor: HTTP istegi, yanit ayristirmasi, grafik okuma,
# strateji karari, risk kapisi, emir kurulumu ve gonderimi, journal
# kaydi. Ag erisimi olmadan gidilebilecek en uzak nokta burasi.


def alpaca_bars(open_at: datetime, count: int) -> list[dict[str, Any]]:
    """Kirilimla biten bir bar serisini Alpaca bicimiyle uretir."""
    bars: list[dict[str, Any]] = []
    for minute in range(count):
        breakout = minute == count - 1
        close = 100.8 if breakout else 100.0
        bars.append(
            {
                "t": (open_at + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z"),
                "o": 100.0,
                "h": close + 0.5,
                "l": 99.5,
                "c": close,
                "v": 40_000 if breakout else 10_000,
                "n": 50,
                "vw": close,
            }
        )
    return bars


def test_full_live_path_places_a_bracket_order(
    stub: tuple[str, StubState], tmp_path: Path, project_root: Path
) -> None:
    """Grafik okumadan emir govdesine kadar tum zincir.

    Sahte sunucu Alpaca'nin yerinde; geri kalan her sey uretim kodu.
    Bu test gectiginde, sistemin gercek hesapta calismasi icin geriye
    yalnizca Alpaca'nin kendi davranisi kaliyor.
    """
    base, state = stub
    open_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    now = open_at + timedelta(minutes=31)

    state.positions = []
    state.open_orders = []
    state.all_orders = []
    state.bars = bar_payload("SPY", alpaca_bars(open_at, 30))
    state.quotes = quote_payload("SPY", bid=100.79, ask=100.81, ts="2026-01-05T15:01:00Z")

    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    config = load_config(project_root)

    conn = connect(tmp_path / "live.db")
    apply_migrations(conn)
    clock = SimClock(now)
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(
        mode="paper", data_feed="iex", params_version="orb-contract", config={}
    )

    runner = SessionRunner(
        broker=AlpacaBroker("PKTEST", "secret", paper=True, base_url=base),
        market=AlpacaMarketData("PKTEST", "secret", feed="iex", base_url=base),
        strategies=[OpeningRangeBreakout(ORBParams())],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
    )

    result = runner.run_once()

    assert result.market_open
    assert result.evaluated == 1
    assert result.intents == 1
    assert result.submitted == 1

    # Brokera giden govde dogru mu
    body = state.body_for("/v2/orders")
    assert body["symbol"] == "SPY"
    assert body["side"] == "buy"
    assert body["order_class"] == "bracket"
    assert body["stop_loss"]["stop_price"] == pytest.approx(99.5)
    assert body["take_profit"]["limit_price"] > body["limit_price"]
    assert body["client_order_id"].startswith("tlab-")

    # Journal'da karar ve emir var mi
    decision = conn.execute("SELECT * FROM decisions").fetchone()
    assert decision["allowed"] == 1
    assert decision["symbol"] == "SPY"

    order = conn.execute("SELECT * FROM orders").fetchone()
    assert order["client_order_id"] == body["client_order_id"]
    assert order["broker_order_id"] is not None, "broker cevabiyla kesinlesmeli"
    assert order["status"] != "submitting"
    conn.close()


def test_full_live_path_respects_the_risk_gate(
    stub: tuple[str, StubState], tmp_path: Path, project_root: Path
) -> None:
    """Spread genis oldugunda gercek zincir de emri engellemeli."""
    base, state = stub
    open_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    now = open_at + timedelta(minutes=31)

    state.positions = []
    state.open_orders = []
    state.all_orders = []
    state.bars = bar_payload("SPY", alpaca_bars(open_at, 30))
    # 100.50 / 101.10 -> ~60 bps spread, sinir 15 bps
    state.quotes = quote_payload("SPY", bid=100.5, ask=101.1, ts="2026-01-05T15:01:00Z")

    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    config = load_config(project_root)

    conn = connect(tmp_path / "veto.db")
    apply_migrations(conn)
    clock = SimClock(now)
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(
        mode="paper", data_feed="iex", params_version="orb-contract", config={}
    )
    runner = SessionRunner(
        broker=AlpacaBroker("PKTEST", "secret", paper=True, base_url=base),
        market=AlpacaMarketData("PKTEST", "secret", feed="iex", base_url=base),
        strategies=[OpeningRangeBreakout(ORBParams())],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
    )

    result = runner.run_once()
    assert result.intents == 1
    assert result.vetoed == 1
    assert result.submitted == 0
    assert "/v2/orders" not in [p for p in state.paths() if p == "/v2/orders"] or all(
        method != "POST" for method, _, _ in state.requests
    )

    row = conn.execute("SELECT veto_reasons FROM decisions").fetchone()
    assert "spread cok genis" in row["veto_reasons"]
    conn.close()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


@pytest.fixture
def cli_root(project_root: Path, stub: tuple[str, StubState]) -> Path:
    """Sahte sunucuyu hedefleyen bir .env ile proje koku."""
    (project_root / ".env").write_text(
        "ALPACA_API_KEY=PKTEST\n"
        "ALPACA_SECRET_KEY=secret\n"
        "ALPACA_PAPER=true\n"
        f"ALPACA_BASE_URL={stub[0]}\n",
        encoding="utf-8",
    )
    return project_root


def test_doctor_reports_a_healthy_system(
    cli_root: Path, stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    """doctor komutu tum katmanlari sirayla denetliyor.

    Bu testin degeri, CLI'nin kendi kablolamasini dogrulamasi:
    birim testleri modulleri ayri ayri dogrular ama komutun onlari
    dogru baglayip baglamadigini gormez.
    """
    stub[1].bars = bar_payload(
        "SPY",
        [
            {
                "t": "2026-01-05T14:30:00Z",
                "o": 100,
                "h": 101,
                "l": 99,
                "c": 100.5,
                "v": 1000,
                "n": 10,
                "vw": 100.2,
            }
        ],
    )
    assert cli_main(["--root", str(cli_root), "doctor"]) == 0

    out = capsys.readouterr().out
    assert "SONUC: sistem hazir." in out
    assert "baglanti kuruldu" in out
    assert "sema surumu 2" in out


def test_account_command_shows_fractional_and_short_positions(
    cli_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["--root", str(cli_root), "account"]) == 0
    out = capsys.readouterr().out
    assert "101,234.56" in out
    assert "AAPL" in out and "10.5 adet" in out
    assert "TSLA" in out and "sell" in out


def test_fetch_command_writes_to_the_cache(
    cli_root: Path, stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    stub[1].bars = bar_payload(
        "SPY",
        [
            {
                "t": f"2026-01-05T14:3{i}:00Z",
                "o": 100,
                "h": 101,
                "l": 99,
                "c": 100.5,
                "v": 1000,
                "n": 10,
                "vw": 100.2,
            }
            for i in range(3)
        ],
    )
    assert cli_main(["--root", str(cli_root), "fetch", "SPY", "--days", "5"]) == 0
    assert capsys.readouterr().out.count("SPY") >= 1

    cached = BarCache(cli_root / "data" / "bars").load("SPY", Timeframe.M1)
    assert len(cached) == 3


def test_doctor_reports_broker_failure_clearly(
    cli_root: Path, stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    """Sorun ciktiginda hangi katmanda oldugu tahmin edilmemeli."""
    stub[1].fail_next = 500
    assert cli_main(["--root", str(cli_root), "doctor"]) == 1

    out = capsys.readouterr().out
    assert "SONUC:" in out
    assert "broker" in out
