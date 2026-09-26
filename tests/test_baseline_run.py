"""Offline baseline olcumu: yalnizca baseline, tekrar uretilebilir, durust.

Veri, her seansta temiz bir kirilim uretecek sekilde kuruluyor ki
maliyet senaryolari gercek islemler uzerinde karsilastirilabilsin.
Seanslar Mart 2026'da ve 8 Mart'taki YAZ SAATI gecisini kapsiyor:
acilis 14:30 UTC'den 13:30 UTC'ye kayiyor. Sabit bir UTC saati
varsayan bir hata burada kirilirdi.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from fs_audit import filesystem_access, touched_under
from test_dataset import FakeBars, FakeCalendar, session, weekdays
from tlab.backtest.baseline import DEFAULT_SCENARIOS, report_bytes, run_baseline
from tlab.backtest.engine import Backtest, CarriedPositionError
from tlab.config import Config, load_config
from tlab.core.calendar import TradingSession
from tlab.core.types import Bar
from tlab.data.cached import CachedMarketData
from tlab.data.dataset import (
    DatasetIntegrityError,
    DatasetSpec,
    VerifiedBaseline,
    build_dataset,
    manifest_sha256,
    verify_baseline,
)
from tlab.journal.db import apply_migrations
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

DAYS = weekdays(date(2026, 3, 2), 10)
SESSIONS = [session(day) for day in DAYS]
DOWNLOADED_AT = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)


def breakout_session(window: Any, symbol: str = "SPY", base: float = 100.0) -> list[Bar]:
    """Aralik olusur, kirilir, hedefe dakika dakika yurur.

    `tests/test_backtest.py::breakout_day` ile ayni bicim; tek fark,
    zaman ekseni sabit bir UTC saatinden degil RESMI seans acilisindan
    kuruluyor.
    """
    minutes = int((window.close - window.open) / timedelta(minutes=1))
    bars: list[Bar] = []
    for minute in range(minutes):
        if minute < 20:
            price, volume = base, 10_000.0
        elif minute == 20:
            price, volume = base + 0.8, 40_000.0
        else:
            price = min(base + 4.0, base + 0.8 + (minute - 20) * 0.25)
            volume = 10_000.0
        bars.append(
            Bar(
                symbol=symbol,
                ts=window.open + timedelta(minutes=minute),
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


@pytest.fixture
def config() -> Config:
    return load_config(Path(__file__).resolve().parents[1])


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    bars = {"SPY": [bar for item in SESSIONS for bar in breakout_session(item)]}
    out = tmp_path / "ds"
    build_dataset(
        DatasetSpec(dataset_id="breakouts", symbols=("SPY",), start=DAYS[0], end=DAYS[-1]),
        bars_source=FakeBars(bars),
        calendar_source=FakeCalendar(SESSIONS),
        out_dir=out,
        downloaded_at=DOWNLOADED_AT,
        producer={"run_id": "test", "commit": "0" * 40},
    )
    return out


@pytest.fixture
def verified(dataset: Path) -> VerifiedBaseline:
    return verify_baseline(dataset, manifest_sha256(dataset))


def test_every_cost_scenario_runs_on_real_trades(
    verified: VerifiedBaseline, config: Config
) -> None:
    report = run_baseline(verified, config, code_commit="c0ffee")
    names = [item["name"] for item in report["scenarios"]]
    assert names == [item.name for item in DEFAULT_SCENARIOS]
    primary = next(
        item for item in report["scenarios"] if item["name"] == report["primary_scenario"]
    )
    assert primary["trades"] > 0, "veri islem uretmiyor - senaryolar bos karsilastiriliyor"
    assert primary["trading_days"] == 8


def test_harsher_costs_never_improve_expectancy(verified: VerifiedBaseline, config: Config) -> None:
    """Maliyet arttikca beklenen deger artamaz.

    Artiyorsa, maliyet modeli ya da olcum yanlis demektir - ve bu
    tur bir hata en cok "strateji maliyete dayanikli" diye
    yanlis okunur.
    """
    report = run_baseline(verified, config, code_commit="c0ffee")
    values = [item["expectancy_r"] for item in report["scenarios"]]
    assert all(later <= earlier + 1e-9 for earlier, later in pairwise(values))


def test_the_same_dataset_gives_a_byte_identical_report(
    verified: VerifiedBaseline, config: Config
) -> None:
    """Ayni veri + config + kod -> bayt bayt ayni rapor.

    Rapora duvar saati, rastgele kosu kimligi ya da yerel dosya yolu
    girseydi bu test kirilirdi.
    """
    first = report_bytes(run_baseline(verified, config, code_commit="c0ffee"))
    second = report_bytes(run_baseline(verified, config, code_commit="c0ffee"))
    assert first == second


def test_the_same_settings_in_another_checkout_give_the_same_report(
    verified: VerifiedBaseline, tmp_path: Path
) -> None:
    """Codex B4: yalnizca proje koku degisince rapor degisiyordu.

    Iki farkli klasorde ayni ayarlar -> bayt bayt ayni rapor. Rapor
    tam semantik ayarlari tasir ama hicbir yerel yolu tasimaz.
    """
    source = Path(__file__).resolve().parents[1] / "config"
    reports = []
    for name in ("ilk-checkout", "baska/bir/checkout"):
        root = tmp_path / name
        shutil.copytree(source, root / "config")
        reports.append(
            report_bytes(run_baseline(verified, load_config(root), code_commit="c0ffee"))
        )
    assert reports[0] == reports[1]
    assert str(tmp_path) not in reports[0].decode()
    assert json.loads(reports[0])["config"]["risk"], "rapor semantik ayarlari tasimali"


def test_the_report_does_not_reveal_holdout_dates(
    dataset: Path, verified: VerifiedBaseline, config: Config
) -> None:
    """Holdout hakkinda yalnizca SAYI. Tarihler bile yazilmiyor.

    Hangi gunlerin ayrildigini bilmek, o gunlere dair bir sey
    hatirlamaya davetiyedir.
    """
    report = run_baseline(verified, config, code_commit="c0ffee")
    holdout_days = json.loads((dataset / "manifest.json").read_bytes())["split"]["holdout"]
    text = report_bytes(report).decode()
    assert report["holdout"] == {"sessions": len(holdout_days), "opened": False}
    for day in holdout_days:
        assert day not in text, f"rapor holdout gununu iceriyor: {day}"


def test_running_the_baseline_never_touches_the_holdout(dataset: Path, config: Config) -> None:
    """Dogrulama + tam backtest, holdout'a tek bir erisim yapmadan."""
    with filesystem_access() as seen:
        verified = verify_baseline(dataset, manifest_sha256(dataset))
        run_baseline(verified, config, code_commit="c0ffee")

    assert seen, "denetim kancasi hicbir olay gormedi - test kendi kendini olcmuyor"
    touched = touched_under(seen, dataset / "holdout")
    assert not touched, f"holdout'a erisildi: {touched}"


def test_after_verification_the_measurement_opens_no_dataset_file(
    dataset: Path, config: Config
) -> None:
    """Olcum veri kumesi dizininde HICBIR dosya acmaz - baseline dahil.

    Dogrulanan baytlar bellekte cozuluyor; olcum dosya yolu almiyor.
    Yani dogrulama ile olcum arasinda "ikinci okuma" diye bir sey yok
    ve holdout'a giden bir takma ad olsa bile olcum onu okuyamaz.
    """
    verified = verify_baseline(dataset, manifest_sha256(dataset))
    with filesystem_access() as seen:
        run_baseline(verified, config, code_commit="c0ffee")
    touched = touched_under(seen, dataset)
    assert not touched, f"olcum veri kumesini yeniden okudu: {touched}"


def test_the_point_estimate_never_appears_without_its_verdict(
    verified: VerifiedBaseline, config: Config
) -> None:
    """Pozitif bir beklenen deger tek basina kanit degil.

    Her senaryoda nokta tahmininin yaninda ogrenme katmaninin hukmu
    duruyor. Bu veri kasten kazandiran bir desen iceriyor; yine de
    islem sayisi az oldugu icin hukum 'yetersiz veri' olmali -
    rakamlar ne kadar parlak gorunurse gorunsun.
    """
    report = run_baseline(verified, config, code_commit="c0ffee")
    for item in report["scenarios"]:
        assert "evidence" in item
        assert item["evidence"]["verdict"] == "insufficient_data"
        assert item["evidence"]["trades_needed"] > item["trades"]


def test_the_report_states_what_it_is_not(verified: VerifiedBaseline, config: Config) -> None:
    report = run_baseline(verified, config, code_commit="c0ffee")
    caveats = " ".join(report["caveats"])
    assert "Holdout acilmadi" in caveats
    assert "terfi karari DEGILDIR" in caveats


def test_a_tampered_dataset_never_reaches_the_backtest(dataset: Path) -> None:
    """Backtest'in girdisi dogrulanmis bir baseline; bozuk veri oraya varamaz."""
    target = dataset / "baseline" / "SPY" / "1Min.parquet"
    data = bytearray(target.read_bytes())
    data[-100] ^= 0xFF
    target.write_bytes(bytes(data))
    with pytest.raises(DatasetIntegrityError):
        verify_baseline(dataset, manifest_sha256(dataset))


# ---------------------------------------------------------------------------
# Gun sonu kapanisi (Codex B1)
#
# Asagidaki veride fiyat kirilir ve sonra YERINDE SAYAR: ne stop'a ne
# hedefe gider. Tek cikis yolu gun sonu kapatmasidir. Bu testlerden
# once o yol hic calismiyordu: SimBroker bracket bacaklarini iptal
# etmedigi icin dongu kapatma gondermiyor, pozisyon gece tasiniyor ve
# ertesi sabahin acilis boslugu "stop" diye raporlaniyordu.
# ---------------------------------------------------------------------------

NY = ZoneInfo("America/New_York")


def stalling_session(
    window: TradingSession, symbol: str = "SPY", base: float = 100.0, *, cut_last: int = 0
) -> list[Bar]:
    """Kirilim, sonra yatay seyir. `cut_last`: sondan eksik dakika."""
    minutes = int((window.close - window.open) / timedelta(minutes=1)) - cut_last
    bars: list[Bar] = []
    for minute in range(minutes):
        if minute < 20:
            price, volume = base, 10_000.0
        elif minute == 20:
            price, volume = base + 0.8, 40_000.0
        else:
            price, volume = base + 0.9, 10_000.0
        bars.append(
            Bar(
                symbol=symbol,
                ts=window.open + timedelta(minutes=minute),
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


def build_stalling(
    tmp_path: Path, sessions: list[TradingSession], *, cut: dict[date, int] | None = None
) -> VerifiedBaseline:
    cut = cut or {}
    bars = [
        bar for item in sessions for bar in stalling_session(item, cut_last=cut.get(item.day, 0))
    ]
    out = tmp_path / "stall"
    build_dataset(
        DatasetSpec(
            dataset_id="stall", symbols=("SPY",), start=sessions[0].day, end=sessions[-1].day
        ),
        bars_source=FakeBars({"SPY": bars}),
        calendar_source=FakeCalendar(sessions),
        out_dir=out,
        downloaded_at=DOWNLOADED_AT,
        producer={"run_id": "test"},
    )
    return verify_baseline(out, manifest_sha256(out))


def exits_of(verified: VerifiedBaseline, config: Config) -> list[sqlite3.Row]:
    """Baseline'i resmi takvimle kosar, cikan islemleri dondurur."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    config = config.model_copy(update={"symbols": ("SPY",)})
    strategy = OpeningRangeBreakout(ORBParams())
    first, last = min(verified.days), max(verified.days)
    Backtest(
        config=config,
        strategy=strategy,
        market=CachedMarketData(verified.store()),
        conn=conn,
        opening_range_minutes=strategy.params.opening_range_minutes,
        sessions=verified.sessions,
    ).run(
        datetime.combine(first, time(), UTC),
        datetime.combine(last, time(), UTC) + timedelta(days=1),
    )
    return conn.execute("SELECT * FROM trades ORDER BY entry_ts").fetchall()


def local(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(NY)


def test_a_position_that_goes_nowhere_is_closed_before_the_bell(
    tmp_path: Path, config: Config
) -> None:
    verified = build_stalling(tmp_path, SESSIONS)
    trades = exits_of(verified, config)
    assert len(trades) == len(verified.days), "her baseline gununde bir islem bekleniyordu"
    for trade in trades:
        assert trade["exit_reason"] == "eod_flatten"
        entry, exit_ = local(trade["entry_ts"]), local(trade["exit_ts"])
        assert exit_.date() == entry.date(), f"pozisyon gece tasindi: {dict(trade)}"
        assert exit_.time() == time(15, 50), "kapanis 16:00 - 10 dk tamponda olmali"


def test_a_half_day_closes_at_the_official_one_pm_bell(tmp_path: Path, config: Config) -> None:
    """Codex B1: config'in sabit 16:00'i yarim gunde yanlis.

    13:00 kapanisli gunde gun sonu kapatmasi 12:50'de olmali.
    Eskiden baseline sonunda bir acik pozisyon kaliyordu.
    """
    half_days = {DAYS[2], DAYS[5]}
    sessions = [
        session(day, close=time(13, 0)) if day in half_days else session(day) for day in DAYS
    ]
    verified = build_stalling(tmp_path, sessions)
    trades = exits_of(verified, config)

    by_day = {local(trade["entry_ts"]).date(): trade for trade in trades}
    for day in half_days & set(verified.days):
        exit_ = local(by_day[day]["exit_ts"])
        assert exit_.date() == day
        assert exit_.time() == time(12, 50), f"{day}: {exit_}"
    assert all(local(t["exit_ts"]).date() == local(t["entry_ts"]).date() for t in trades)


def test_every_session_of_a_half_day_dataset_ends_flat(tmp_path: Path, config: Config) -> None:
    """Son baseline gunu dahil hicbir seans acik pozisyonla bitmez.

    Motor bunu kendisi denetler; burada rapor uretilebildigi, yani
    `CarriedPositionError` firlatilmadigi dogrulaniyor.
    """
    sessions = [session(day, close=time(13, 0)) for day in DAYS]
    verified = build_stalling(tmp_path, sessions)
    report = run_baseline(verified, config, code_commit="c0ffee")
    assert report["scenarios"][0]["trades"] == len(verified.days)


def test_missing_closing_bars_stop_the_measurement_instead_of_inventing_a_fill(
    tmp_path: Path, config: Config
) -> None:
    """Kapanis oncesi son 30 dakika yoksa kapatma dolamaz.

    Son bilinen fiyattan dolum uydurmak yerine olcum durur: bu gunun
    sonucu stratejiyi degil veri boslugunu olcerdi.
    """
    verified = build_stalling(tmp_path, SESSIONS, cut={DAYS[3]: 30})
    with pytest.raises(CarriedPositionError, match="acik pozisyon"):
        run_baseline(verified, config, code_commit="c0ffee")
