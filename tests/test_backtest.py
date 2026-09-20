"""Backtest motoru testleri.

Bir backtest motorunun en tehlikeli hatasi yanlis sonuc uretmek
degil, FAZLA IYI sonuc uretmektir: yanlis rakam supheyle
karsilanir, guzel rakam ise inanilir ve uzerine para konur.

Bu yuzden testlerin cogu "motor kendine avantaj sagliyor mu" diye
soruyor: gelecege bakiyor mu, ayni girdiyle ayni sonucu veriyor mu,
edge olmayan veride edge uretiyor mu.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tlab.backtest.engine import Backtest
from tlab.backtest.metrics import compute_metrics, max_drawdown
from tlab.backtest.sim_broker import SimFillModel
from tlab.config import Config, load_config
from tlab.core.types import Bar, Timeframe
from tlab.data.cache import BarCache
from tlab.data.cached import CachedMarketData
from tlab.errors import DataError
from tlab.journal.db import apply_migrations, connect
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

SESSION_MINUTES = 390


def session_open(day_offset: int = 0) -> datetime:
    """2026-01-05 09:30 New York (kis saati) + gun."""
    return datetime(2026, 1, 5, 14, 30, tzinfo=UTC) + timedelta(days=day_offset)


def breakout_day(day_offset: int, symbol: str = "SPY", base: float = 100.0) -> list[Bar]:
    """Temiz bir kirilim gunu: aralik olusur, kirilir, hedefe YURUR.

    Kirilimdan sonra fiyat dakikada bir adim ilerliyor. Bu ayrinti
    onemli: bir dakikada iki dolar siçrayan veri gercekci degil ve
    limit emirlerinin dolum davranisini yanlis test eder.
    """
    open_at = session_open(day_offset)
    bars: list[Bar] = []
    for minute in range(SESSION_MINUTES):
        if minute < 20:
            price, volume = base, 10_000.0
        elif minute == 20:
            price, volume = base + 0.8, 40_000.0
        else:
            # Kademeli yukselis: hedefe birkac dakikada ulasiliyor.
            price = min(base + 4.0, base + 0.8 + (minute - 20) * 0.25)
            volume = 10_000.0
        bars.append(
            Bar(
                symbol=symbol,
                ts=open_at + timedelta(minutes=minute),
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=volume,
                vwap=price,
                trade_count=50,
            )
        )
    return bars


def random_walk_day(
    day_offset: int, rng: random.Random, symbol: str = "SPY", start_price: float = 100.0
) -> tuple[list[Bar], float]:
    """Edge icermeyen gun: fiyat rastgele yuruyor."""
    open_at = session_open(day_offset)
    bars: list[Bar] = []
    price = start_price
    for minute in range(SESSION_MINUTES):
        price = max(1.0, price * (1 + rng.gauss(0, 0.0012)))
        spread = price * 0.0006
        volume = rng.uniform(5_000, 15_000) * (4 if minute in (25, 90) else 1)
        bars.append(
            Bar(
                symbol=symbol,
                ts=open_at + timedelta(minutes=minute),
                open=price,
                high=price + spread,
                low=price - spread,
                close=price,
                volume=volume,
                vwap=price,
                trade_count=50,
            )
        )
    return bars, price


@pytest.fixture
def bt_config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    return load_config(project_root)


@pytest.fixture
def cache(tmp_path: Path) -> BarCache:
    return BarCache(tmp_path / "bars")


@pytest.fixture
def bt_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "bt.db")
    apply_migrations(connection)
    yield connection
    connection.close()


def make_backtest(
    config: Config, cache: BarCache, conn: sqlite3.Connection, *, slippage_bps: float = 0.0
) -> Backtest:
    return Backtest(
        config=config,
        strategy=OpeningRangeBreakout(ORBParams()),
        market=CachedMarketData(cache, timeframe=Timeframe.M1),
        conn=conn,
        starting_equity=100_000.0,
        fill_model=SimFillModel(slippage_bps=slippage_bps),
    )


def trade_fingerprints(
    conn: sqlite3.Connection, run_id: str
) -> list[tuple[str, str, float, float]]:
    rows = conn.execute(
        "SELECT symbol, entry_ts, entry_price, exit_price FROM trades"
        " WHERE run_id = ? ORDER BY entry_ts",
        (run_id,),
    ).fetchall()
    return [
        (str(r["symbol"]), str(r["entry_ts"]), float(r["entry_price"]), float(r["exit_price"]))
        for r in rows
    ]


# --------------------------------------------------------------------------
# Uctan uca
# --------------------------------------------------------------------------


def test_clean_breakout_produces_a_winning_trade(
    bt_config: Config, cache: BarCache, bt_conn: sqlite3.Connection
) -> None:
    """Tasarlanmis bir kirilim gununde zincirin tamami calismali."""
    cache.save("SPY", Timeframe.M1, breakout_day(0))
    result = make_backtest(bt_config, cache, bt_conn).run(
        session_open(0) - timedelta(days=1), session_open(1)
    )

    assert result.metrics is not None
    assert result.metrics.trades == 1
    assert result.metrics.expectancy_r > 0
    assert result.ending_equity > result.starting_equity
    assert result.steps == SESSION_MINUTES


def test_backtest_uses_the_same_runner_as_live(
    bt_config: Config, cache: BarCache, bt_conn: sqlite3.Connection
) -> None:
    """Kararlar canlidakiyle ayni yoldan gecmeli: journal bunu gosterir.

    Karar kaydi, emir kaydi ve islem kaydi ayni semaya dusuyorsa
    backtest gercekten ayni beyni kullaniyor demektir.
    """
    cache.save("SPY", Timeframe.M1, breakout_day(0))
    result = make_backtest(bt_config, cache, bt_conn).run(
        session_open(0) - timedelta(days=1), session_open(1)
    )

    run = bt_conn.execute("SELECT * FROM runs WHERE run_id = ?", (result.run_id,)).fetchone()
    assert run["mode"] == "backtest"
    assert bt_conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] >= 1
    assert bt_conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"] == 1
    assert bt_conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"] == 2


def test_journal_timestamps_follow_the_simulated_clock(
    bt_config: Config, cache: BarCache, bt_conn: sqlite3.Connection
) -> None:
    """Kayitlar bugunun degil, simule edilen gunun tarihini tasimali.

    Aksi halde backtest'ten uretilen istatistikler zaman ekseninde
    yerinden oynar ve donemler karsilastirilamaz hale gelir.
    """
    cache.save("SPY", Timeframe.M1, breakout_day(0))
    result = make_backtest(bt_config, cache, bt_conn).run(
        session_open(0) - timedelta(days=1), session_open(1)
    )
    row = bt_conn.execute(
        "SELECT started_at FROM runs WHERE run_id = ?", (result.run_id,)
    ).fetchone()
    assert datetime.fromisoformat(str(row["started_at"])).date() == session_open(0).date()


# --------------------------------------------------------------------------
# Motor kendine avantaj sagliyor mu
# --------------------------------------------------------------------------


def test_no_edge_data_produces_no_edge(
    bt_config: Config, cache: BarCache, bt_conn: sqlite3.Connection
) -> None:
    """Rastgele yuruyuste beklenen deger pozitif CIKMAMALI.

    Rastgele veride kazanc uretebilen bir motor, kendine bir yerden
    avantaj sagliyor demektir. Bu test o avantajin sizmasini
    engelleyen en genel korumadir.
    """
    rng = random.Random(7)
    price = 100.0
    bars: list[Bar] = []
    for day in range(12):
        day_bars, price = random_walk_day(day, rng, start_price=price)
        bars.extend(day_bars)
    cache.save("SPY", Timeframe.M1, bars)

    result = make_backtest(bt_config, cache, bt_conn, slippage_bps=1.0).run(
        session_open(0) - timedelta(days=1), session_open(13)
    )
    assert result.metrics is not None
    if result.metrics.trades:
        assert result.metrics.expectancy_r <= 0.25, (
            f"edge olmayan veride {result.metrics.expectancy_r:+.3f} R uretildi"
        )


def test_future_data_does_not_change_past_decisions(
    bt_config: Config, cache: BarCache, tmp_path: Path
) -> None:
    """Ileriye bakma testi.

    Ayni gecmis, iki farkli gelecekle birlikte isletiliyor. Gecmisteki
    kararlar birebir ayni cikmali; farkliysa motor gelecege bakiyor
    demektir.
    """
    early = breakout_day(0)
    later = breakout_day(1, base=120.0)

    cache.save("SPY", Timeframe.M1, early)
    short_conn = connect(tmp_path / "short.db")
    apply_migrations(short_conn)
    short = make_backtest(bt_config, cache, short_conn).run(
        session_open(0) - timedelta(days=1), session_open(1)
    )
    short_trades = trade_fingerprints(short_conn, short.run_id)
    short_conn.close()

    # Ayni gecmisin uzerine gelecek ekleniyor.
    cache.save("SPY", Timeframe.M1, later)
    long_conn = connect(tmp_path / "long.db")
    apply_migrations(long_conn)
    full = make_backtest(bt_config, cache, long_conn).run(
        session_open(0) - timedelta(days=1), session_open(2)
    )
    full_trades = trade_fingerprints(long_conn, full.run_id)
    long_conn.close()

    assert short_trades, "ilk gunde islem olmali ki karsilastirma anlamli olsun"
    assert full_trades[: len(short_trades)] == short_trades


def test_backtest_is_deterministic(bt_config: Config, cache: BarCache, tmp_path: Path) -> None:
    """Ayni veri, ayni parametre, ayni sonuc.

    Tekrarlanabilirlik olmadan 'bu degisiklik iyilestirdi mi'
    sorusu cevaplanamaz.
    """
    cache.save("SPY", Timeframe.M1, breakout_day(0) + breakout_day(1, base=105.0))
    fingerprints = []
    for index in range(2):
        conn = connect(tmp_path / f"run{index}.db")
        apply_migrations(conn)
        result = make_backtest(bt_config, cache, conn).run(
            session_open(0) - timedelta(days=1), session_open(2)
        )
        fingerprints.append(trade_fingerprints(conn, result.run_id))
        conn.close()
    assert fingerprints[0] == fingerprints[1]


def test_slippage_makes_results_worse(bt_config: Config, cache: BarCache, tmp_path: Path) -> None:
    """Maliyet arttikca sonuc kotulesmeli - aksi bir isaret hatadir."""
    cache.save("SPY", Timeframe.M1, breakout_day(0))
    results = []
    for index, slippage in enumerate([0.0, 20.0]):
        conn = connect(tmp_path / f"slip{index}.db")
        apply_migrations(conn)
        result = make_backtest(bt_config, cache, conn, slippage_bps=slippage).run(
            session_open(0) - timedelta(days=1), session_open(1)
        )
        assert result.metrics is not None
        results.append(result.metrics.total_r)
        conn.close()
    assert results[1] < results[0]


# --------------------------------------------------------------------------
# Veri kaynagi
# --------------------------------------------------------------------------


def test_cached_market_data_never_returns_future_bars(cache: BarCache) -> None:
    cache.save("SPY", Timeframe.M1, breakout_day(0))
    market = CachedMarketData(cache, timeframe=Timeframe.M1)
    cutoff = session_open(0) + timedelta(minutes=10)
    bars = market.bars("SPY", Timeframe.M1, session_open(0), cutoff)
    assert bars[-1].ts <= cutoff
    assert len(bars) == 11


def test_quote_is_taken_from_the_simulated_moment(cache: BarCache) -> None:
    """Saat verilmisse kotasyon o ana ait olmali.

    Bu atlanirsa backtest dogrudan gelecege bakar: 'son' kotasyon,
    veri setinin en sonundaki fiyat olur.
    """
    from tlab.core.clock import SimClock

    cache.save("SPY", Timeframe.M1, breakout_day(0))
    moment = session_open(0) + timedelta(minutes=5)
    clock = SimClock(moment)
    market = CachedMarketData(cache, timeframe=Timeframe.M1, clock=clock)

    quote = market.latest_quote("SPY")
    assert quote.ts <= moment
    # Kirilim 20. dakikada; 5. dakikadaki kotasyon onu bilmemeli.
    assert quote.mid == pytest.approx(100.0, abs=0.1)


def test_wrong_timeframe_is_rejected(cache: BarCache) -> None:
    cache.save("SPY", Timeframe.M1, breakout_day(0))
    market = CachedMarketData(cache, timeframe=Timeframe.M1)
    with pytest.raises(DataError, match="hazirlandi"):
        market.bars("SPY", Timeframe.M5, session_open(0))


def test_missing_data_gives_an_actionable_error(
    bt_config: Config, cache: BarCache, bt_conn: sqlite3.Connection
) -> None:
    with pytest.raises(DataError, match="tlab fetch"):
        make_backtest(bt_config, cache, bt_conn).run(session_open(0), session_open(1))


# --------------------------------------------------------------------------
# Metrikler
# --------------------------------------------------------------------------


def test_max_drawdown_measures_peak_to_trough() -> None:
    curve = [
        (session_open(0), 100_000.0),
        (session_open(1), 110_000.0),
        (session_open(2), 95_000.0),
        (session_open(3), 105_000.0),
    ]
    drop, pct = max_drawdown(curve)
    assert drop == pytest.approx(15_000.0)
    assert pct == pytest.approx(13.636, abs=0.01)


def test_metrics_of_an_empty_run_are_zero(bt_conn: sqlite3.Connection) -> None:
    metrics = compute_metrics(bt_conn, "olmayan-kosu")
    assert metrics.trades == 0
    assert metrics.expectancy_r == 0.0
    assert not metrics.is_profitable


def test_metrics_report_is_readable(
    bt_config: Config, cache: BarCache, bt_conn: sqlite3.Connection
) -> None:
    cache.save("SPY", Timeframe.M1, breakout_day(0))
    result = make_backtest(bt_config, cache, bt_conn).run(
        session_open(0) - timedelta(days=1), session_open(1)
    )
    assert result.metrics is not None
    text = result.report()
    assert "BEKLENEN DEGER" in text
    assert "islem sayisi" in text
