"""Ortak kalite ozeti: pilot ve baseline teshisi ayni toplamayi kullanir (#17).

Birinci amac bir DEGISMEZLIK kaniti: sembol bazli toplama
`pilot_quality`'den `tlab.data.quality_summary`'ye cikarildi. Pilotun
schema 1 ciktisi ve sayim anlami degismemeli. Asagidaki beklenen sozluk,
cikarmadan ONCE ayni sentetik manifest uzerinde uretilip buraya
yazildi; cikarmadan sonra birebir ayni kalmali.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from test_dataset import FakeBars, FakeCalendar, minute_bars, session, weekdays
from tlab.core.types import Bar
from tlab.data.dataset import DatasetSpec, build_dataset
from tlab.pilot_quality import pilot_summary

DAYS = weekdays(date(2026, 3, 2), 5)
SESSIONS = [session(day) for day in DAYS]


def gappy_bars() -> dict[str, list[Bar]]:
    """Her gerekce turunden en az bir ornek; son gun (holdout) tekrarli.

    SPY: 2. gun hic bar yok; 4. gun ortada 50 dk eksik (oran > 0.10);
         5. gun (holdout) 3 tekrarli zaman damgasi.
    QQQ: 1. gun acilistan 5 dk eksik; 3. gun son 15 dk eksik (kapanis);
         4. gun acilistan TAM 1 dk eksik (esik kenari: "> 0" ile "> 1"
         ayrimini yakalar).
    """
    spy: list[Bar] = []
    qqq: list[Bar] = []
    for index, window in enumerate(SESSIONS):
        day_spy = minute_bars("SPY", window)
        day_qqq = minute_bars("QQQ", window)
        if index == 1:
            day_spy = []
        if index == 3:
            day_spy = day_spy[:100] + day_spy[150:]
        if index == 4:
            day_spy = day_spy + day_spy[10:13]
        if index == 0:
            day_qqq = day_qqq[5:]
        if index == 2:
            day_qqq = minute_bars("QQQ", window, skip=15)
        if index == 3:
            day_qqq = day_qqq[1:]
        spy += day_spy
        qqq += day_qqq
    return {"SPY": spy, "QQQ": qqq}


def gappy_manifest(tmp_path: Path) -> dict[str, Any]:
    return build_dataset(
        DatasetSpec.model_validate(
            {
                "dataset_id": "gappy",
                "status": "pilot",
                "symbols": ["SPY", "QQQ"],
                "start": DAYS[0],
                "end": DAYS[-1],
            }
        ),
        bars_source=FakeBars(gappy_bars()),
        calendar_source=FakeCalendar(SESSIONS),
        out_dir=tmp_path / "ds",
        downloaded_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        producer={"run_id": "test", "workflow": "test", "commit": "0" * 40},
    )


PILOT_EXPECTED: dict[str, Any] = {
    "adjustment": "raw",
    "dataset_id": "gappy",
    "feed": "iex",
    "kind": "pilot-quality",
    "manifest_sha256": "a" * 64,
    "policy": {
        "close_window_minutes": 10,
        "max_ineligible_sessions": 0,
        "max_missing_fraction": 0.1,
        "max_missing_open_window": 0,
        "open_window_minutes": 15,
    },
    "producer": {"commit": "0" * 40, "run_id": "test", "workflow": "test"},
    "reasons": {
        "acilis_penceresi_eksik": 2,
        "eksik_dakika_orani": 1,
        "kapanis_penceresinde_bar_yok": 1,
        "seans_ici_bar_yok": 1,
    },
    "schema": 1,
    "sessions": {"calendar": 5, "complete": 5, "eligible": 1, "incomplete": 0, "ineligible": 4},
    "spec_sha256": "74c97dfaa346aaf5e6604a84e79a29d600f8326bf0887b7524fce3a2cdab2808",
    "status": "pilot",
    "symbols": {
        "QQQ": {
            "duplicate_timestamps": 0,
            "expected_minutes": 1950,
            "ineligible_sessions": 3,
            "max_missing_open_window": 5,
            "missing_fraction": 0.010769,
            "missing_minutes": 21,
            "sessions_open_window_incomplete": 2,
            "sessions_with_bars": 5,
            "sessions_without_bars": 0,
            "sessions_without_close_bar": 1,
        },
        "SPY": {
            "duplicate_timestamps": 3,
            "expected_minutes": 1950,
            "ineligible_sessions": 2,
            "max_missing_open_window": 15,
            "missing_fraction": 0.225641,
            "missing_minutes": 440,
            "sessions_open_window_incomplete": 1,
            "sessions_with_bars": 4,
            "sessions_without_bars": 1,
            "sessions_without_close_bar": 1,
        },
    },
    "timeframe": "1Min",
    "verdict": "some_ineligible",
}
"""`gappy_manifest` icin pilot_summary ciktisi - ortak toplamaya cikarmadan
ONCE (main a466a4f) uretildi ve elle degistirilmedi."""


def test_the_pilot_summary_is_unchanged_by_the_extraction(tmp_path: Path) -> None:
    assert pilot_summary(gappy_manifest(tmp_path), "a" * 64) == PILOT_EXPECTED
