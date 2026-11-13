"""Gun ici kill-switch kaliciligi: journal kaybolursa ne olur.

Gozetimsiz paper icin on kosul (docs/designs/unattended-paper.md §4,
Codex #57/6225592912, #61/6694382019). Surec duzeyi kalicilik
`test_runner.py`'de gosteriliyor: ayni veritabaniyla yeniden baslayan
surec gunu kapali bilir. Burada ORTAM duzeyi var: her gun temiz
baslayan bir ortamda (Actions) yeniden deneme ya da elle ikinci
baslatma journal'i bulamaz. O surecin elindeki tek kanit brokerdir.

Sabitlenen davranis:
  * Zarar hesapta hala sinirin altindaysa taze surec ilk turda durur:
    bekleyen emirleri iptal eder, pozisyonu kapatir, karari yeniden
    yazar ve emir gondermez.
  * Acik 1: zarar kapanista sinirin hemen ustunde gerceklestiyse
    (ornek: -%2,1'de tetiklenip -%1,95'te kapanmak) hesap tek basina
    yetmez. Journal'da bugune ait emir yokken brokerda bugun
    gerceklesme varsa gun belirsiz sayilir ve kapatilir.
  * Acik 2: gun durumu okunamazsa yeni giris yapilmaz, ama gun sonu
    kapanisi ve emir iptali surer; tur hata firlatmaz.
  * Normal gun etkilenmez: surec kendi emrini gondermeden once
    yazdigi icin kendi gerceklesmeleri gunu belirsiz yapmaz.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import SESSION_OPEN, make_account
from test_runner import NOW, FakeBroker, FakeMarket, breakout_bars, build_runner, pending_ref
from tlab.config import Config, load_config
from tlab.core.types import Fill, Position, Side
from tlab.errors import BrokerError, JournalError
from tlab.journal.db import apply_migrations, connect
from tlab.journal.queries import halt_reason

FLATTEN_WINDOW = SESSION_OPEN + timedelta(minutes=385)
"""Kapanisa dakikalar kala: `session.must_flatten` dogru (test_runner deseni)."""


@pytest.fixture
def config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    return load_config(project_root)


def fresh_journal(tmp_path: Path, name: str) -> sqlite3.Connection:
    """Bu gune ait hicbir kaydi olmayan bos bir journal."""
    connection = connect(tmp_path / name)
    apply_migrations(connection)
    return connection


def unreadable_day_state(tmp_path: Path) -> sqlite3.Connection:
    """Gocleri uygulanmis ama gun durumu tablosu okunamayan bir journal."""
    conn = fresh_journal(tmp_path, "broken.db")
    conn.execute("DROP TABLE daily_state")
    return conn


def open_position() -> Position:
    return Position(symbol="SPY", side=Side.BUY, qty=10, avg_entry_price=100.0, current_price=97.0)


def todays_close_fill() -> Fill:
    """Onceki surecin kill-switch kapanisindan kalan bugunku gerceklesme."""
    return Fill(
        broker_order_id="onceki-kapanis",
        client_order_id="onceki-kapanis",
        symbol="SPY",
        side=Side.SELL,
        qty=10,
        price=97.0,
        filled_at=NOW - timedelta(minutes=5),
        order_type="market",
    )


class FailingFillsBroker(FakeBroker):
    def list_fills(self, since):  # type: ignore[no-untyped-def]
        msg = "gerceklesmeler alinamadi"
        raise BrokerError(msg)


def test_a_fresh_process_halts_again_while_the_loss_is_still_on_the_account(
    config: Config, tmp_path: Path
) -> None:
    """Ilk surecin journal'i yok; zarar hesapta, pozisyon ve bekleyen giris duruyor."""
    broker = FakeBroker(
        account=make_account(equity=97_000, last_equity=100_000), positions=[open_position()]
    )
    broker.open_orders.append(pending_ref("QQQ", qty=5, price=100.0))
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "fresh.db")
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    result = runner.run_once()

    assert result.halted
    assert "KILL-SWITCH" in " ".join(result.notes)
    # Once emirler iptal edilir, sonra pozisyon kapatilir.
    assert broker.cancelled == [None]
    assert broker.open_orders == []
    assert broker.closed == ["SPY"]
    assert result.flattened == 1
    assert broker.submitted == []
    # Karar yeni journal'a da yazilir: ayni surecin sonraki turlari
    # hesap toparlansa bile gunu kapali bilir.
    assert halt_reason(conn, result.now.date()) is not None


def test_a_fresh_process_halts_when_the_close_landed_just_above_the_limit(
    config: Config, tmp_path: Path
) -> None:
    """Acik 1: -%2,1'de tetiklenen gun -%1,95'te kapandi; hesap tek basina yetmez."""
    broker = FakeBroker(account=make_account(equity=98_050, last_equity=100_000))
    broker.fills.append(todays_close_fill())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "fresh.db")
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    result = runner.run_once()

    assert result.halted
    assert "gun belirsiz" in " ".join(result.notes)
    assert broker.submitted == []
    reason = halt_reason(conn, result.now.date())
    assert reason is not None
    assert reason.startswith("gun belirsiz")


def test_a_fresh_morning_without_fills_trades_normally(config: Config, tmp_path: Path) -> None:
    """Bugun hic gerceklesme yoksa bos journal normal gunun baslangicidir."""
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(
        config=config, conn=fresh_journal(tmp_path, "fresh.db"), broker=broker, market=market
    )

    result = runner.run_once()

    assert not result.halted
    assert not result.entries_blocked
    assert len(broker.submitted) == 1


def test_own_fills_do_not_make_the_day_unexplained(config: Config, tmp_path: Path) -> None:
    """Surec emrini gondermeden once yazar; kendi gerceklesmesi gunu bozmaz."""
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "own.db")
    first = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()
    assert first.submitted == 1
    order = broker.submitted[0]
    broker.fills.append(
        Fill(
            broker_order_id="kendi-giris",
            client_order_id=order.client_order_id,
            symbol="SPY",
            side=order.side,
            qty=order.qty,
            price=order.limit_price or 100.8,
            filled_at=NOW,
            order_type="limit",
        )
    )

    second = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert not second.halted
    assert halt_reason(conn, second.now.date()) is None


def test_unreadable_fills_block_entries_without_halting(config: Config, tmp_path: Path) -> None:
    """Bugunku gerceklesmeler okunamazsa gun bilinmiyor: giris yok, karar yazilmaz."""
    broker = FailingFillsBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "fresh.db")
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    result = runner.run_once()

    assert result.entries_blocked
    assert not result.halted
    assert broker.submitted == []
    assert halt_reason(conn, result.now.date()) is None


def test_an_unreadable_day_state_blocks_entries_without_raising(
    config: Config, tmp_path: Path
) -> None:
    """Acik 2: gun durumunu okuyamayan tur yeni giris yapmaz ama hata firlatmaz."""
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(
        config=config, conn=unreadable_day_state(tmp_path), broker=broker, market=market
    )

    result = runner.run_once()

    assert result.entries_blocked
    assert "gun durumu okunamadi" in " ".join(result.notes)
    assert broker.submitted == []


def test_an_unreadable_day_state_still_flattens_at_the_end_of_day(
    config: Config, tmp_path: Path
) -> None:
    """Acik 2: okuma hatasi gun sonu kapanisinin onune gecmez."""
    broker = FakeBroker(positions=[open_position()])
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(
        config=config,
        conn=unreadable_day_state(tmp_path),
        broker=broker,
        market=market,
        now=FLATTEN_WINDOW,
    )

    result = runner.run_once()

    assert result.flattened == 1
    assert broker.cancelled == [None]
    assert broker.closed == ["SPY"]
    assert broker.submitted == []


def test_an_unreadable_day_state_still_honours_a_breached_loss(
    config: Config, tmp_path: Path
) -> None:
    """Karar yazilamasa da zarar siniri asildiysa pozisyonlar kapatilir."""
    broker = FakeBroker(
        account=make_account(equity=97_000, last_equity=100_000), positions=[open_position()]
    )
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(
        config=config, conn=unreadable_day_state(tmp_path), broker=broker, market=market
    )

    result = runner.run_once()

    assert result.halted
    assert broker.closed == ["SPY"]
    assert broker.submitted == []
    assert "kill-switch karari journal'a yazilamadi" in " ".join(result.notes)


def test_a_halt_that_failed_to_persist_still_holds_for_the_process(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex #63/6772282247: tek seferlik yazma hatasi karari unutturmaz.

    Bu seansta journal'da giris emri var (belirsiz gun kurali devre
    disi). Zarar -%2,1'de tetiklenir, karar bir kez yazilamaz. Kapanis
    -%1,95'te kalir; sonraki turda gecerli kirilim sinyali olsa da emir
    gitmez ve karar bu kez kalici yazilir.
    """
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "journal.db")
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)
    assert runner.run_once().submitted == 1

    real = runner.writer.record_halt
    calls: list[str] = []

    def flaky(trade_date, reason, run_id):  # type: ignore[no-untyped-def]
        calls.append(reason)
        if len(calls) == 1:
            msg = "disk dolu"
            raise JournalError(msg)
        real(trade_date, reason, run_id)

    monkeypatch.setattr(runner.writer, "record_halt", flaky)

    broker.account = make_account(equity=97_900, last_equity=100_000)
    first = runner.run_once()
    assert first.halted
    assert broker.cancelled == [None]
    assert "kill-switch karari journal'a yazilamadi" in " ".join(first.notes)
    assert halt_reason(conn, first.now.date()) is None

    broker.account = make_account(equity=98_050, last_equity=100_000)
    submitted_before = len(broker.submitted)
    second = runner.run_once()

    assert second.halted
    assert len(broker.submitted) == submitted_before
    assert len(calls) == 2
    assert halt_reason(conn, second.now.date()) is not None


def test_blocked_entries_cancel_fresh_entry_orders(config: Config, tmp_path: Path) -> None:
    """Gun durumu bilinmiyorken yeni verilmis bekleyen giris de iptal edilir."""
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "journal.db")
    assert build_runner(config=config, conn=conn, broker=broker, market=market).run_once().submitted
    [entry] = broker.open_orders
    conn.execute("DROP TABLE daily_state")

    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert result.entries_blocked
    # Iptal girisin kimligine gider; sembol bazli iptal yok.
    assert broker.cancelled_ids == [entry.broker_order_id]
    assert broker.cancelled == []
    assert broker.open_orders == []
    assert result.cancelled == 1
    assert len(broker.submitted) == 1


def test_blocked_entries_keep_the_protective_legs_of_an_open_position(
    config: Config, tmp_path: Path
) -> None:
    """Pozisyonu olan sembolde iptal yok: kalan giris bekler, bacaklara dokunulmaz."""
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "journal.db")
    assert build_runner(config=config, conn=conn, broker=broker, market=market).run_once().submitted
    # Giris kismen doldu: pozisyon var, kalan giris ve koruma bacaklari bekliyor.
    broker.positions = [
        Position(symbol="SPY", side=Side.BUY, qty=5, avg_entry_price=100.8, current_price=100.9)
    ]
    conn.execute("DROP TABLE daily_state")

    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert result.entries_blocked
    assert broker.cancelled == []
    assert broker.cancelled_ids == []
    assert [o.symbol for o in broker.open_orders] == ["SPY"]
    assert broker.closed == []
    assert len(broker.submitted) == 1
