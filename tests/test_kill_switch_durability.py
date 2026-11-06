"""Gun ici kill-switch kaliciligi: journal kaybolursa ne olur.

Gozetimsiz paper icin on kosul (docs/designs/unattended-paper.md §4,
Codex #57/6225592912). Surec duzeyi kalicilik `test_runner.py`'de
gosteriliyor: ayni veritabaniyla yeniden baslayan surec gunu kapali
bilir. Burada ORTAM duzeyi var: her gun temiz baslayan bir ortamda
(Actions) yeniden deneme ya da elle ikinci baslatma journal'i
bulamaz. O surecin elindeki tek kanit brokerdaki hesaptir.

Bu dosya bugunku davranisi sabitler:
  * Zarar hesapta hala sinirin altindaysa taze surec ilk turda
    durur: bekleyen emirleri iptal eder, pozisyonu kapatir, karari
    yeniden yazar ve emir gondermez.
  * Gun durumu okunamazsa tur hata firlatir; emir gitmez.

Bilinen aciklar (duzeltmeleri `src/` altinda; kampanya dondurmasi
bitince ayri PR, Codex #61/6694382019):
  * Kapanis sinirin hemen ustunde gerceklesirse (ornek: -%2,1'de
    tetiklenip -%1,95'te kapanmak) taze surec zarari sinirin ustunde
    gorur ve ayni gun yeniden islem acar.
  * Gun durumu okunamazsa hata gun sonu kapanisinin da onune gecer:
    kill-switch kontrolu kapanis kontrolunden once gelir. `run_forever`
    hatayi yakalayip donguye devam eder; is kirmizi bitmez, her tur
    ayni hatayla biter ve acik pozisyon kapanmaz. Asagidaki son test
    bu davranisi karakterize eder.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import SESSION_OPEN, make_account
from test_runner import FakeBroker, FakeMarket, breakout_bars, build_runner, pending_ref
from tlab.config import Config, load_config
from tlab.core.types import Position, Side
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


def test_an_unreadable_day_state_raises_before_any_order(config: Config, tmp_path: Path) -> None:
    """Gun durumunu okuyamayan tur karar veremez ve hata firlatir.

    Bu, isin kirmizi bittigi anlamina gelmez: `run_forever` hatayi
    yakalar ve sonraki turu dener.
    """
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(
        config=config, conn=unreadable_day_state(tmp_path), broker=broker, market=market
    )

    with pytest.raises(sqlite3.Error):
        runner.run_once()

    assert broker.submitted == []


def test_an_unreadable_day_state_also_blocks_the_end_of_day_flatten(
    config: Config, tmp_path: Path
) -> None:
    """KARAKTERIZASYON, bilinen acik: gun sonu kapanisi da yapilmaz.

    Kill-switch kontrolu kapanis kontrolunden once gelir; okuma hatasi
    turu orada bitirir. Acik pozisyon kapanmaz, emir iptal edilmez.
    Duzeltme kampanya sonrasi gelince bu test yeni beklentiyle
    (okuma hatasinda yeni giris yok ama koruma ve kapanis surer)
    degistirilir.
    """
    broker = FakeBroker(positions=[open_position()])
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(
        config=config,
        conn=unreadable_day_state(tmp_path),
        broker=broker,
        market=market,
        now=FLATTEN_WINDOW,
    )

    with pytest.raises(sqlite3.Error):
        runner.run_once()

    assert broker.closed == []
    assert broker.cancelled == []
    assert broker.submitted == []
