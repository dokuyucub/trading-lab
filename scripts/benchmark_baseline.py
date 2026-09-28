"""Ana baseline olcumunun hedef olcekte sentetik benchmark'i (#17, PR b).

Soru: 11 sembol x ~63 seans dakikalik veriyle indirme sonrasi zincir
(`build_dataset` -> `verify_baseline` -> dort senaryolu `run_baseline`)
ne kadar surer ve ne kadar bellek ister? Cevap workflow'un
`timeout-minutes` butcesinin dayanagidir.

Veri SENTETIK ve deterministik. Uc gun deseni donusumlu kullanilir ki
emir, pozisyon ve journal yolu gercekten calissin:

  * kirilim -> hedef  (islem kazanir)
  * kirilim -> stop   (islem kaybeder)
  * yatay             (sinyal yok)

Bu bir BENCHMARK'tir; strateji basarisinin kaniti DEGILDIR ve
performans sayisi basmaz. Yerel sure, hosted runner icin ust sinir
degildir. Ag kullanmaz; indirme suresi dahil degildir.

Kullanim:  PYTHONPATH=src python scripts/benchmark_baseline.py
"""

from __future__ import annotations

import os
import platform
import resource
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from tlab.backtest.baseline import run_baseline
from tlab.config import load_config
from tlab.core.calendar import TradingSession
from tlab.core.types import Bar, Timeframe
from tlab.data.dataset import DatasetSpec, build_dataset, manifest_sha256, verify_baseline

REPO = Path(__file__).resolve().parents[1]
SESSIONS = 63
START = date(2026, 6, 22)
NEW_YORK_OPEN_UTC = 13  # yaz saati: 09:30 ET = 13:30 UTC


def weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def session(day: date) -> TradingSession:
    opened = datetime(day.year, day.month, day.day, NEW_YORK_OPEN_UTC, 30, tzinfo=UTC)
    return TradingSession(day=day, open=opened, close=opened + timedelta(minutes=390))


def day_bars(symbol: str, window: TradingSession, pattern: int, base: float) -> list[Bar]:
    """0: kirilim->hedef, 1: kirilim->stop, 2: yatay (sinyal yok)."""
    bars: list[Bar] = []
    for minute in range(390):
        if minute < 20 or pattern == 2:
            price, volume = base + (0.2 if minute % 2 else -0.2), 10_000.0
        elif minute == 20:
            price, volume = base + 0.8, 40_000.0
        elif pattern == 0:
            price, volume = min(base + 4.0, base + 0.8 + (minute - 20) * 0.25), 10_000.0
        else:
            price, volume = max(base - 3.0, base + 0.8 - (minute - 20) * 0.25), 10_000.0
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


class Bars:
    def __init__(self, by_symbol: dict[str, list[Bar]]) -> None:
        self.by_symbol = by_symbol

    def bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None
    ) -> list[Bar]:
        del timeframe  # sentetik veri tek zaman diliminde
        return [
            bar
            for bar in self.by_symbol[symbol]
            if start <= bar.ts and (end is None or bar.ts < end)
        ]


class Calendar:
    def __init__(self, sessions: list[TradingSession]) -> None:
        self.sessions = sessions

    def get_calendar(self, start: date, end: date) -> list[TradingSession]:
        return [item for item in self.sessions if start <= item.day <= end]


def peak_rss_mb() -> float:
    # Linux'ta ru_maxrss kilobayt.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> int:
    config = load_config(REPO)
    symbols = tuple(config.symbols)
    days = weekdays(START, SESSIONS)
    sessions = [session(day) for day in days]
    by_symbol = {
        symbol: [
            bar
            for index, window in enumerate(sessions)
            for bar in day_bars(symbol, window, (index + offset) % 3, 100.0 + 10 * offset)
        ]
        for offset, symbol in enumerate(symbols)
    }
    spec = DatasetSpec.model_validate(
        {
            "dataset_id": "benchmark",
            "status": "approved",
            "symbols": symbols,
            "start": days[0],
            "end": days[-1],
        }
    )

    timings: dict[str, float] = {}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "dataset"
        started = time.perf_counter()
        manifest = build_dataset(
            spec,
            bars_source=Bars(by_symbol),
            calendar_source=Calendar(sessions),
            out_dir=out,
            downloaded_at=datetime.combine(days[-1] + timedelta(days=7), datetime.min.time(), UTC),
            producer={"run_id": "benchmark", "commit": "local"},
        )
        timings["build_dataset"] = time.perf_counter() - started

        started = time.perf_counter()
        verified = verify_baseline(out, manifest_sha256(out))
        timings["verify_baseline"] = time.perf_counter() - started

        started = time.perf_counter()
        report = run_baseline(verified, config, code_commit="benchmark")
        timings["run_baseline"] = time.perf_counter() - started

    bars = sum(len(items) for items in by_symbol.values())
    print(f"ortam: Python {platform.python_version()}, {platform.machine()}, cpu {os.cpu_count()}")
    split = manifest["split"]
    print(
        f"veri: {len(symbols)} sembol, {len(days)} seans, {bars} bar; "
        f"baseline {len(split['baseline'])} / holdout {len(split['holdout'])}"
    )
    for name, seconds in timings.items():
        print(f"sure {name:<16}: {seconds:8.1f} sn")
    print(f"sure toplam           : {sum(timings.values()):8.1f} sn")
    print(f"tepe bellek (RSS)     : {peak_rss_mb():8.0f} MB")
    for scenario in report["scenarios"]:
        # Yalnizca SAYIM: sentetik veride performans anlamsiz.
        print(f"senaryo {scenario['name']:<9}: {scenario['trades']} islem")
    return 0


if __name__ == "__main__":
    sys.exit(main())
