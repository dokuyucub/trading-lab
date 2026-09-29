"""Baseline kalite teshisi: gercek CLI, tek surec, GERCEK gorev (#17).

`python -m tlab.baseline_diagnostic` sabit `TASK` ile calisir: gecici
kokte depodaki ana tanimin BAYT BAYT kopyasi var (hash kilidi gecsin
diye) ve takvim, ana tanimin gercek 63 seansi. Test dizinindeki
`sitecustomize`:

  * SDK sarmalayicilarini yerel sahte sunucuya yonlendirir (uretim
    kodunda test kancasi yok);
  * ham veri yazicilarini (BarCache.save, DataFrame.to_parquet/to_csv)
    YASAKLAR ve cagrilirsa iz birakir;
  * surec biterken yuklenmis performans modullerini kaydeder.

Kanitlananlar: basarida ve hatada izinli ozet disinda HICBIR dosya
olusmaz; ham yazici cagrilmaz; performans katmani yuklenmez.

SINIR: yerel kanittir; hosted Actions'i, secret enjeksiyonunu ya da
artifact yukleme hizmetini dogrulamaz.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from alpaca_stub import StubState, alpaca_stub
from test_baseline_diagnostic import MARKERS, rows
from test_dataset import minute_bars, session

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
OUT_NAME = "baseline-quality-diagnostic.json"

SITE = """
import atexit
import json
import os
import sys

from tlab.data import cache, market
from tlab.execution import alpaca_broker

URL = os.environ["SMOKE_STUB_URL"]


def _redirect(cls):
    original = cls.__init__

    def init(self, *args, base_url=None, **kwargs):
        original(self, *args, base_url=base_url or URL, **kwargs)

    cls.__init__ = init


_redirect(alpaca_broker.AlpacaBroker)
_redirect(market.AlpacaMarketData)


def _forbidden(*args, **kwargs):
    with open(os.environ["SMOKE_RAW_WRITE"], "a") as handle:
        handle.write("ham veri yazicisi cagrildi\\n")
    raise RuntimeError("smoke: ham veri yazimi yasak")


import pandas

cache.BarCache.save = _forbidden
pandas.DataFrame.to_parquet = _forbidden
pandas.DataFrame.to_csv = _forbidden

PERFORMANCE = (
    "tlab.backtest",
    "tlab.learning",
    "tlab.strategies",
    "tlab.engine",
    "tlab.baseline_job",
)


def _report():
    loaded = sorted(name for name in sys.modules if name.startswith(PERFORMANCE))
    with open(os.environ["SMOKE_MODULES"], "w") as handle:
        json.dump(loaded, handle)


atexit.register(_report)
"""


def main_spec_sessions() -> list[date]:
    """Ana tanimin resmi seanslari: 2026-06-22..09-18, 3 Temmuz ve 7 Eylul tatil."""
    days: list[date] = []
    cursor = date(2026, 6, 22)
    while cursor <= date(2026, 9, 18):
        if cursor.weekday() < 5 and cursor not in (date(2026, 7, 3), date(2026, 9, 7)):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


DAYS = main_spec_sessions()


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def market(state: StubState) -> None:
    """Takvim gercek 63 seans; bar yalnizca SPY icin ilk baseline gunu ve
    (kapsam disi olarak) ilk holdout gunu. Diger semboller bos."""
    state.calendar = [{"date": day.isoformat(), "open": "09:30", "close": "16:00"} for day in DAYS]
    spy = minute_bars("SPY", session(DAYS[0])) + minute_bars("SPY", session(DAYS[50]))[:30]
    state.bars = {"bars": {"SPY": rows(spy)}, "next_page_token": None}


def files_under(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def run_cli(tmp_path: Path, url: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    support = tmp_path / "support"
    support.mkdir()
    (support / "sitecustomize.py").write_text(SITE, "utf-8")
    work = tmp_path / "work"
    shutil.copytree(REPO / "config", work / "root" / "config")
    (work / "runner-temp").mkdir()
    before = files_under(work)

    process = subprocess.run(  # noqa: S603 - sabit arguman listesi, kabuk yok
        [
            sys.executable,
            "-m",
            "tlab.baseline_diagnostic",
            "--out",
            str(work / "runner-temp" / OUT_NAME),
        ],
        cwd=work / "root",
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": f"{support}{os.pathsep}{SRC}",
            "SMOKE_STUB_URL": url,
            "SMOKE_RAW_WRITE": str(support / "raw-write.txt"),
            "SMOKE_MODULES": str(support / "modules.json"),
            "ALPACA_PAPER_API_KEY": MARKERS["api_key"],
            "ALPACA_PAPER_SECRET_KEY": MARKERS["secret"],
        },
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return process, {
        "new_files": files_under(work) - before,
        "raw_write": (support / "raw-write.txt").exists(),
        "modules": json.loads((support / "modules.json").read_text("utf-8")),
        "out": work / "runner-temp" / OUT_NAME,
    }


def test_the_real_task_runs_once_and_leaves_only_the_summary(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    url, state = stub
    market(state)
    process, seen = run_cli(tmp_path, url)
    output = process.stdout + process.stderr

    assert process.returncode == 0, output
    assert seen["new_files"] == {f"runner-temp/{OUT_NAME}"}, seen["new_files"]
    assert not seen["raw_write"], "ham veri yazicisi cagrildi"
    assert seen["modules"] == [], f"performans modulu yuklendi: {seen['modules']}"

    summary = json.loads(seen["out"].read_bytes())
    assert summary["diagnostic_id"] == "diag-orb-baseline-2026q3-u11-quality-1"
    assert summary["sessions"]["baseline"] == 50
    assert summary["sessions"]["holdout"] == 13

    assert process.stderr == "", output
    assert process.stdout.startswith("OK teshis diag-orb-baseline-2026q3-u11-quality-1")
    assert "2026-" not in output, "cikti bir tarih tasiyor"
    assert not [value for value in MARKERS.values() if value in output]

    last_close = datetime.combine(DAYS[49], datetime.min.time(), UTC) + timedelta(hours=20)
    for _, path, _ in state.requests:
        if urlparse(path).path == "/v2/stocks/bars":
            end = datetime.fromisoformat(parse_qs(urlparse(path).query)["end"][0])
            assert end <= last_close, "bar istegi baseline sonunu asti"


def test_a_failed_download_leaves_nothing(stub: tuple[str, StubState], tmp_path: Path) -> None:
    url, state = stub
    market(state)
    state.fail("/v2/stocks/bars", 500, times=None, body={"message": MARKERS["body"]})
    process, seen = run_cli(tmp_path, url)
    output = process.stdout + process.stderr

    assert process.returncode != 0
    assert "FAIL indirme" in process.stdout
    assert seen["new_files"] == set(), seen["new_files"]
    assert not seen["raw_write"]
    assert seen["modules"] == []
    assert MARKERS["body"] not in output
    assert "Traceback" not in output
