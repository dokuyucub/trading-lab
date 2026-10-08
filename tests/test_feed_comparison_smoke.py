"""SIP kalite karsilastirmasi: gercek CLI, tek surec, GERCEK gorev (#17).

`python -m tlab.feed_comparison` sabit `SIP_TASK` ile calisir: gecici
kokte depodaki ana tanimin BAYT BAYT kopyasi, takvim ana tanimin gercek
63 seansi. `sitecustomize` teshis smoke testiyle ayni: SDK'yi yerel
sahte sunucuya yonlendirir, ham veri yazicilarini yasaklar, yuklenen
performans modullerini kaydeder.

Kanitlananlar: basarida ve erisim reddinde izinli ozet disinda HICBIR
dosya olusmaz; her bar istegi `feed=sip`; ham yazici cagrilmaz;
performans katmani yuklenmez.

SINIR: yerel kanittir; hosted Actions'i, secret enjeksiyonunu, artifact
yukleme hizmetini ya da bu hesabin gercek SIP erisimini dogrulamaz.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from alpaca_stub import StubState, alpaca_stub
from test_baseline_diagnostic import MARKERS
from test_baseline_diagnostic_smoke import DAYS, SITE, files_under, market

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
OUT_NAME = "baseline-feed-comparison.json"


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def run_cli(tmp_path: Path, url: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    support = tmp_path / "support"
    support.mkdir()
    (support / "sitecustomize.py").write_text(SITE, "utf-8")
    work = tmp_path / "work"
    shutil.copytree(REPO / "config", work / "root" / "config")
    # Kapatilan IEX tanimi aktif dizinde yok (§11.4); gorev o tanima
    # kilitli. Regresyon kaniti, bayt-bayt kopyasi eski yoluna konarak.
    shutil.copy(
        REPO / "tests" / "fixtures" / "closed_datasets" / "orb-baseline-2026q3-u11.yaml",
        work / "root" / "config" / "datasets" / "orb-baseline-2026q3-u11.yaml",
    )
    (work / "runner-temp").mkdir()
    before = files_under(work)

    process = subprocess.run(  # noqa: S603 - sabit arguman listesi, kabuk yok
        [
            sys.executable,
            "-m",
            "tlab.feed_comparison",
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


def bar_queries(state: StubState) -> list[dict[str, list[str]]]:
    return [
        parse_qs(urlparse(path).query)
        for _, path, _ in state.requests
        if urlparse(path).path == "/v2/stocks/bars"
    ]


def test_the_real_sip_task_runs_once_and_leaves_only_the_summary(
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
    assert summary["comparison_id"] == "feedcmp-orb-baseline-2026q3-u11-sip-1"
    assert summary["feed"] == "sip"
    assert summary["source"]["spec_feed"] == "iex"
    assert summary["sessions"]["baseline"] == 50
    assert summary["sessions"]["holdout"] == 13
    assert summary["access"]["symbols_answered"] == 11

    assert process.stderr == "", output
    assert process.stdout.startswith(
        "OK karsilastirma feedcmp-orb-baseline-2026q3-u11-sip-1 "
        "(kaynak orb-baseline-2026q3-u11; feed iex -> sip, gorev duzeyinde)"
    )
    assert "2026-" not in output, "cikti bir tarih tasiyor"
    assert not [value for value in MARKERS.values() if value in output]

    queries = bar_queries(state)
    assert len(queries) == 11
    last_close = datetime.combine(DAYS[49], datetime.min.time(), UTC) + timedelta(hours=20)
    for query in queries:
        assert query["feed"] == ["sip"]
        assert query["adjustment"] == ["raw"]
        assert datetime.fromisoformat(query["end"][0]) <= last_close


def test_an_access_denial_leaves_nothing(stub: tuple[str, StubState], tmp_path: Path) -> None:
    url, state = stub
    market(state)
    state.fail("/v2/stocks/bars", 403, times=None, body={"message": MARKERS["body"]})
    process, seen = run_cli(tmp_path, url)
    output = process.stdout + process.stderr

    assert process.returncode != 0
    assert process.stdout.startswith("FAIL erisim: sip tarihsel bar istegi reddedildi (HTTP 403)")
    assert seen["new_files"] == set(), seen["new_files"]
    assert not seen["raw_write"]
    assert seen["modules"] == []
    assert len(bar_queries(state)) == 1
    assert MARKERS["body"] not in output
    assert "Traceback" not in output
