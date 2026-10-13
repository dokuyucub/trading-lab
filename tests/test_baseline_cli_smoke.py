"""Ana baseline isi: gercek CLI, IKI AYRI SUREC, workflow sirasi (#17 PR b, c).

Birim testleri fonksiyonlari cagirir; bu dosya workflow'un gercekte
yapacagini yerelde taklit eder:

  * `python -m tlab.baseline_job download` - AYRI surec, ortaminda
    YALNIZCA sahte anahtarlar. Gercek giris noktasi: argparse, `main()`,
    ortamdan okuma, goreli `MAIN_SPEC`, duvar saati.
  * `python -m tlab.baseline_job measure` - AYRI surec, TEMIZ ortam
    (yalnizca PATH ve PYTHONPATH) ve ag baglantisi yasak.
  * Temizlik her durumda; "yuklenebilir" rapor yalnizca A, B ve temizlik
    basariliysa.

Kok, gecici bir dizin: sabit dosya adiyla SENTETIK `approved` bir ana
tanim tasir. Depodaki ana tanim bu testte KULLANILMAZ.

Yonlendirme URETIM KODUNA dokunmadan yapilir: test dizinindeki bir
`sitecustomize`, SDK sarmalayicilarinin `base_url` varsayilanini yerel
sahte sunucuya cevirir.

SINIR: bu yerel bir kanittir. Hosted GitHub Actions'i, secret
enjeksiyonunu ya da artifact yukleme hizmetini DOGRULAMAZ.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from alpaca_stub import StubState, alpaca_stub
from test_baseline_job import DAYS, MARKERS, market
from tlab.backtest.baseline import FEED_MISMATCH_CAVEAT

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

STUB_SITE = """
import os
from tlab.data import market
from tlab.execution import alpaca_broker

URL = os.environ["SMOKE_STUB_URL"]


def _redirect(cls):
    original = cls.__init__

    def init(self, *args, base_url=None, **kwargs):
        original(self, *args, base_url=base_url or URL, **kwargs)

    cls.__init__ = init


_redirect(alpaca_broker.AlpacaBroker)
_redirect(market.AlpacaMarketData)
"""
"""Adim A'nin sureci: SDK istemcilerini yerel sahte sunucuya yonlendirir."""

NO_NETWORK_SITE = """
import socket


def _refuse(*args, **kwargs):
    raise OSError("smoke: olcum adiminda ag baglantisi yasak")


socket.socket.connect = _refuse
socket.socket.connect_ex = _refuse
socket.create_connection = _refuse
"""
"""Adim B'nin sureci: herhangi bir ag baglantisi denemesi hata verir."""


@dataclass
class Workflow:
    download: subprocess.CompletedProcess[str]
    measure: subprocess.CompletedProcess[str] | None
    workdir_after_cleanup: bool
    uploadable: Path | None

    @property
    def output(self) -> str:
        parts = [self.download.stdout, self.download.stderr]
        if self.measure is not None:
            parts += [self.measure.stdout, self.measure.stderr]
        return "".join(parts)


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def _site(tmp_path: Path, name: str, body: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "sitecustomize.py").write_text(body, "utf-8")
    return folder


def _root(tmp_path: Path, status: str) -> Path:
    """Gecici kok: sabit dosya adiyla sentetik ana tanim + depo ayarlari."""
    root = tmp_path / "root"
    (root / "config" / "datasets").mkdir(parents=True)
    for name in ("base.yaml", "universe.yaml"):
        shutil.copy(REPO / "config" / name, root / "config" / name)
    # Kod sabit `MAIN_SPEC` yolunu okur: aktif ana tanim SIP taslagi (§11.4).
    spec = root / "config" / "datasets" / "orb-baseline-2026q3-u11-sip.yaml"
    spec.write_text(
        f"dataset_id: orb-baseline-2026q3-u11-sip\nstatus: {status}\nsymbols: [SPY, QQQ]\n"
        f"feed: sip\nstart: {DAYS[0]}\nend: {DAYS[-1]}\n",
        encoding="utf-8",
    )
    return root


def _run(step: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # Sabit arguman listesi, kabuk yok; `step` yalnizca bu dosyadan gelir.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "tlab.baseline_job", *step],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def run_workflow(
    tmp_path: Path, url: str, *, status: str = "approved", corrupt_hash: bool = False
) -> Workflow:
    """alpaca-baseline-measure.yml'nin adim sirasini yerelde uygular."""
    root = _root(tmp_path, status)
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    workdir, report = temp / "baseline-data", temp / "baseline-report.json"
    base_path = os.environ["PATH"]

    step_a = _run(
        ["download", "--workdir", str(workdir)],
        cwd=root,
        env={
            "PATH": base_path,
            "PYTHONPATH": f"{_site(tmp_path, 'stub-site', STUB_SITE)}{os.pathsep}{SRC}",
            "SMOKE_STUB_URL": url,
            "ALPACA_PAPER_API_KEY": MARKERS["api_key"],
            "ALPACA_PAPER_SECRET_KEY": MARKERS["secret"],
        },
    )
    step_b = None
    if step_a.returncode == 0:
        if corrupt_hash:
            (workdir / "manifest.sha256").write_text("0" * 64 + "\n", "ascii")
        step_b = _run(
            ["measure", "--workdir", str(workdir), "--out", str(report)],
            cwd=root,
            env={
                "PATH": base_path,
                "PYTHONPATH": f"{_site(tmp_path, 'guard-site', NO_NETWORK_SITE)}{os.pathsep}{SRC}",
            },
        )

    # Temizlik: if: always()
    shutil.rmtree(workdir, ignore_errors=True)
    cleaned = not workdir.exists()
    # Upload: kosulsuz adim = onceki her adim basariliysa.
    succeeded = step_a.returncode == 0 and step_b is not None and step_b.returncode == 0
    uploadable = report if succeeded and cleaned and report.exists() else None
    return Workflow(step_a, step_b, workdir.exists(), uploadable)


def test_success_publishes_one_report_after_cleanup(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    url, state = stub
    market(state)
    flow = run_workflow(tmp_path, url)

    assert flow.download.returncode == 0, flow.output
    assert flow.measure is not None and flow.measure.returncode == 0, flow.output
    assert not flow.workdir_after_cleanup
    assert flow.uploadable is not None, "basarili kosuda yuklenebilir rapor yok"
    report = json.loads(flow.uploadable.read_bytes())
    assert report["dataset_id"] == "orb-baseline-2026q3-u11-sip"
    # Indirme tanimin feed'iyle yapilir: her bar istegi `feed=sip`.
    bar_queries = [
        parse_qs(urlparse(path).query)
        for _, path, _ in state.requests
        if urlparse(path).path == "/v2/stocks/bars"
    ]
    assert bar_queries, "bar istegi yapilmadi"
    assert all(query["feed"] == ["sip"] for query in bar_queries)
    assert report["starting_equity_basis"] == "synthetic_assumption"
    # Rapor v4 (feed alani v3'ten): olcum feed'i manifestten; depo config'i
    # (iex) ayri gorunur ve uyusmazlik uyarisi raporda kalici (#17 6052081621).
    assert report["report_schema"] == 4
    assert report["data_feed"] == "sip"
    assert report["config"]["data"]["feed"] == "iex"
    assert FEED_MISMATCH_CAVEAT.format(data_feed="sip", configured="iex") in report["caveats"]
    assert "feed sip (ayar iex)" in flow.measure.stdout

    # Ciktilar yalnizca aracin sabit satirlari; sizinti ve traceback yok.
    assert flow.download.stdout.startswith("OK indirme")
    assert flow.measure.stdout.startswith("OK olcum")
    assert flow.download.stderr == "" and flow.measure.stderr == "", flow.output
    leaked = [name for name, value in MARKERS.items() if value in flow.output]
    assert not leaked, f"surec ciktisi sizdiriyor: {leaked}"

    # A yalnizca okuma yapti; B hic baglanti kurmadi (kurmaya calissaydi
    # guard-site OSError verir ve olcum dusardi).
    assert {method for method, _, _ in state.requests} == {"GET"}
    assert set(state.paths()) <= {"/v2/calendar", "/v2/stocks/bars"}


def test_a_failed_measurement_publishes_nothing(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    url, state = stub
    market(state)
    flow = run_workflow(tmp_path, url, corrupt_hash=True)

    assert flow.download.returncode == 0, flow.output
    assert flow.measure is not None and flow.measure.returncode != 0
    assert "FAIL butunluk" in flow.measure.stdout
    assert not flow.workdir_after_cleanup
    assert flow.uploadable is None
    assert not (tmp_path / "runner-temp" / "baseline-report.json").exists()
    assert "Traceback" not in flow.output


def test_an_unapproved_spec_stops_the_first_process(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    url, state = stub
    market(state)
    flow = run_workflow(tmp_path, url, status="draft")

    assert flow.download.returncode != 0
    assert "FAIL onay" in flow.download.stdout
    assert flow.measure is None
    assert state.requests == [], "onaysiz tanimda ag istegi yapildi"
    assert flow.uploadable is None
    assert not (tmp_path / "runner-temp" / "baseline-data").exists()


def test_the_network_guard_is_active_in_the_measurement_process(tmp_path: Path) -> None:
    """Bekci gercekten yukleniyor mu? Yuklenmeseydi yukaridaki 'B hic
    baglanmadi' kaniti bos olurdu."""
    guard = _site(tmp_path, "guard-site", NO_NETWORK_SITE)
    probe = subprocess.run(
        [sys.executable, "-c", "import socket; socket.create_connection(('127.0.0.1', 9))"],
        env={"PATH": os.environ["PATH"], "PYTHONPATH": f"{guard}{os.pathsep}{SRC}"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert probe.returncode != 0
    assert "olcum adiminda ag baglantisi yasak" in probe.stderr
