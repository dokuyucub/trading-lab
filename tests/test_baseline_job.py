"""Ana baseline isi: iki adim, tek job (#17, PR b).

Tasarim belgesinin sartlari burada OLCULUYOR:

  * Onay kapisi anahtar okumadan, istemci kurmadan ve dizin olusturmadan
    ONCE (ortam erisimi kaydeden bir eslemeyle).
  * Indirme yalnizca izinli GET yollarini cagirir; hesap uc noktasi yok.
  * Olcum anahtarsiz ve AG CAGRISIZ (socket.connect yasakken basarili).
  * Gecersiz kosuda rapor yazilmaz; rapor atomik ve ustune yazmaz.
  * Basari ve hata yollarinda stdout + stderr + logging'de anahtar,
    yanit govdesi, ham deger, holdout gunu ya da performans sayisi yok.
  * Rapor alan kumeleri birebir sabit.
"""

from __future__ import annotations

import json
import logging
import socket
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from alpaca_stub import StubState, alpaca_stub
from fs_audit import filesystem_access, touched_under
from test_baseline_run import breakout_session
from test_dataset import FakeBars, FakeCalendar, session, weekdays
from tlab import baseline_job
from tlab.backtest.engine import CarriedPositionError
from tlab.config import load_config
from tlab.core.types import Bar
from tlab.data.dataset import DatasetSpec, build_dataset, manifest_sha256

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
DAYS = weekdays(date(2026, 1, 5), 5)
SYMBOLS = ("SPY", "QQQ")

MARKERS = {
    "api_key": "BASELINECANARYKEYAAA",
    "secret": "BASELINECANARYSECRET",
    "trade_count": "2718281",
    "body": "BASELINE-RESPONSE-BODY-CANARY",
}
"""Sunucu yanitlarina ve ortama konan sahte isaretler; ciktida ARANIR."""


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------


class RecordingEnv(Mapping[str, str]):
    """Hangi ortam degiskeninin okundugunu kaydeden esleme."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.read: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.read.append(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def keys_env() -> RecordingEnv:
    return RecordingEnv(
        {
            "ALPACA_PAPER_API_KEY": MARKERS["api_key"],
            "ALPACA_PAPER_SECRET_KEY": MARKERS["secret"],
            "GITHUB_SHA": "a" * 40,
        }
    )


def breakout_bars(symbol: str, *, skip_first_day: int = 0) -> list[Bar]:
    bars: list[Bar] = []
    for index, day in enumerate(DAYS):
        day_bars = breakout_session(session(day), symbol=symbol)
        if index == 0 and skip_first_day:
            day_bars = day_bars[skip_first_day:]
        bars.extend(day_bars)
    return bars


def stub_rows(bars: list[Bar]) -> list[dict[str, Any]]:
    return [
        {
            "t": bar.ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "o": bar.open,
            "h": bar.high,
            "l": bar.low,
            "c": bar.close,
            "v": bar.volume,
            "n": int(MARKERS["trade_count"]),
            "vw": bar.vwap,
        }
        for bar in bars
    ]


def market(state: StubState) -> None:
    state.calendar = [{"date": day.isoformat(), "open": "09:30", "close": "16:00"} for day in DAYS]
    state.bars = {
        "bars": {symbol: stub_rows(breakout_bars(symbol)) for symbol in SYMBOLS},
        "next_page_token": None,
    }


def spec_file(tmp_path: Path, status: str = "approved") -> Path:
    path = tmp_path / "main.yaml"
    path.write_text(
        f"dataset_id: main-test\nstatus: {status}\nsymbols: [SPY, QQQ]\n"
        f"start: {DAYS[0]}\nend: {DAYS[-1]}\n",
        encoding="utf-8",
    )
    return path


def prepare(tmp_path: Path, *, status: str = "approved", qqq_skip: int = 0) -> Path:
    """Adim A'nin birakacagi calisma dizini - ag olmadan, ayni duzenle."""
    workdir = tmp_path / "work"
    dataset = workdir / baseline_job.DATASET_DIR
    bars = {
        "SPY": breakout_bars("SPY"),
        "QQQ": breakout_bars("QQQ", skip_first_day=qqq_skip),
    }
    build_dataset(
        DatasetSpec.model_validate(
            {
                "dataset_id": "main-test",
                "status": status,
                "symbols": SYMBOLS,
                "start": DAYS[0],
                "end": DAYS[-1],
            }
        ),
        bars_source=FakeBars(bars),
        calendar_source=FakeCalendar([session(day) for day in DAYS]),
        out_dir=dataset,
        downloaded_at=NOW,
        producer={"run_id": "test", "commit": "0" * 40},
    )
    (workdir / baseline_job.HASH_FILE).write_text(manifest_sha256(dataset) + "\n", "ascii")
    return workdir


def measure(tmp_path: Path, workdir: Path, env: Mapping[str, str] | None = None) -> int:
    return baseline_job.measure(
        env if env is not None else {"GITHUB_SHA": "b" * 40},
        workdir=workdir,
        out=tmp_path / "report.json",
        root=REPO,
    )


def holdout_days(workdir: Path) -> list[str]:
    manifest = json.loads((workdir / baseline_job.DATASET_DIR / "manifest.json").read_bytes())
    return list(manifest["split"]["holdout"])


def output(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err + caplog.text


def leaked(text: str) -> list[str]:
    return sorted(name for name, value in MARKERS.items() if value in text)


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def download(
    stub: tuple[str, StubState], tmp_path: Path, env: Mapping[str, str], status: str = "approved"
) -> int:
    url, _ = stub
    return baseline_job.download(
        env, NOW, workdir=tmp_path / "work", spec_path=spec_file(tmp_path, status), base_url=url
    )


# --------------------------------------------------------------------------
# Adim A: onay kapisi ve indirme
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["draft", "pilot"])
def test_an_unapproved_spec_stops_before_keys_requests_and_directories(
    stub: tuple[str, StubState], tmp_path: Path, status: str
) -> None:
    """`require_downloadable` pilotu kabul eder; ana isin kapisi etmez."""
    _, state = stub
    market(state)
    env = keys_env()

    assert download(stub, tmp_path, env, status) == 1
    assert env.read == [], f"onaydan once ortam okundu: {env.read}"
    assert state.requests == [], "onaydan once ag istegi yapildi"
    assert not (tmp_path / "work").exists(), "onaydan once dizin olusturuldu"


def test_download_writes_the_dataset_and_its_hash_and_leaks_nothing(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, state = stub
    market(state)
    with caplog.at_level(logging.DEBUG):
        assert download(stub, tmp_path, keys_env()) == 0

    workdir = tmp_path / "work"
    digest = (workdir / baseline_job.HASH_FILE).read_text("ascii").strip()
    assert digest == manifest_sha256(workdir / baseline_job.DATASET_DIR)

    text = output(capsys, caplog)
    assert not leaked(text), f"indirme ciktisi sizdiriyor: {leaked(text)}"
    # DEBUG'da bile log YOK: urllib3 istek adresini (tanim tarihleriyle)
    # loglardi; adim boyunca logging kapali.
    assert caplog.text == "", "indirme adiminda log kaydi gecti"
    for day in holdout_days(workdir):
        assert day not in text, "indirme ciktisi holdout gununu iceriyor"
    assert text.startswith("OK indirme main-test")

    # Yalnizca okuma; hesap uc noktasi hic cagrilmaz.
    assert {method for method, _, _ in state.requests} == {"GET"}
    assert set(state.paths()) <= {"/v2/calendar", "/v2/stocks/bars"}


def test_download_never_touches_an_existing_directory(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    market(state)
    existing = tmp_path / "work"
    existing.mkdir()
    (existing / "keep.txt").write_text("kullanicinin dosyasi", "utf-8")

    assert download(stub, tmp_path, keys_env()) == 1
    assert (existing / "keep.txt").read_text("utf-8") == "kullanicinin dosyasi"
    assert state.requests == []


@pytest.mark.parametrize("path", ["/v2/stocks/bars", "/v2/calendar"])
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_download_errors_are_fixed_and_remove_the_directory(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    path: str,
    status: int,
) -> None:
    _, state = stub
    market(state)
    body = {"message": f"{MARKERS['body']} key={MARKERS['api_key']}", "s": MARKERS["secret"]}
    state.fail(path, status, times=None, body=body)

    with caplog.at_level(logging.DEBUG):
        assert download(stub, tmp_path, keys_env()) == 1

    text = output(capsys, caplog)
    assert not leaked(text), f"hata ciktisi sizdiriyor: {leaked(text)}\n{text}"
    assert "FAIL indirme:" in text
    assert not (tmp_path / "work").exists(), "hata yolunda veri dizini kaldi"


def test_missing_keys_stop_after_the_gate_without_a_directory(tmp_path: Path) -> None:
    code = baseline_job.download(
        RecordingEnv({}), NOW, workdir=tmp_path / "work", spec_path=spec_file(tmp_path)
    )
    assert code == 1
    assert not (tmp_path / "work").exists()


# --------------------------------------------------------------------------
# Adim B: olcum
# --------------------------------------------------------------------------

REPORT_KEYS = {
    "report_schema",
    "dataset_id",
    "manifest_sha256",
    "baseline_sessions",
    "holdout",
    "quality",
    "code_commit",
    "config",
    "config_sha256",
    "deterministic",
    "starting_equity",
    "starting_equity_basis",
    "primary_scenario",
    "scenarios",
    "caveats",
}
SCENARIO_KEYS = {
    "name",
    "slippage_bps",
    "spread_bps",
    "commission_bps",
    "trading_days",
    "trades",
    "expectancy_r",
    "win_rate_pct",
    "profit_factor",
    "total_r",
    "net_pnl",
    "max_drawdown_pct",
    "total_return_pct",
    "strategy",
    "evidence",
}
EVIDENCE_KEYS = {"verdict", "mean_r", "ci_low", "ci_high", "confidence", "trades_needed"}


def test_the_report_has_exactly_the_reviewed_fields(tmp_path: Path) -> None:
    """Disari cikan tek sey; alan kumesi her duzeyde birebir sabit."""
    assert measure(tmp_path, prepare(tmp_path)) == 0
    report = json.loads((tmp_path / "report.json").read_bytes())

    assert set(report) == REPORT_KEYS
    assert set(report["baseline_sessions"]) == {"first", "last", "count"}
    assert set(report["holdout"]) == {"sessions", "opened", "commitment"}
    assert set(report["holdout"]["commitment"]) == {"version", "sha256"}
    assert set(report["quality"]) == {"policy"}
    assert set(report["config"]) == set(load_config(REPO).semantic_dump())
    for scenario in report["scenarios"]:
        assert set(scenario) == SCENARIO_KEYS
        assert set(scenario["evidence"]) == EVIDENCE_KEYS
    assert report["starting_equity_basis"] == "synthetic_assumption"
    assert report["code_commit"] == "b" * 40
    # Emir/pozisyon yolu gercekten kullanildi - bos bir olcum degil.
    primary = next(item for item in report["scenarios"] if item["name"] == "temel")
    assert primary["trades"] > 0


def test_the_log_carries_no_performance_numbers_and_no_holdout_day(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    workdir = prepare(tmp_path)
    with caplog.at_level(logging.DEBUG):
        assert measure(tmp_path, workdir) == 0
    text = output(capsys, caplog)
    report = json.loads((tmp_path / "report.json").read_bytes())

    # Motor her islemi fiyat ve P&L ile INFO'da loglar; adim boyunca
    # logging kapali oldugu icin DEBUG'da bile hicbiri gecmez.
    assert caplog.text == "", "olcum adiminda log kaydi gecti"
    assert [line.split(" ")[0] for line in text.strip().splitlines()] == ["OK", "rapor:"]
    for scenario in report["scenarios"]:
        for field in ("expectancy_r", "total_r", "net_pnl", "win_rate_pct"):
            value = scenario[field]
            if value not in (None, 0, 0.0):
                assert str(value) not in text, f"log performans sayisi tasiyor: {field}"
        assert scenario["evidence"]["verdict"] not in text
    for day in holdout_days(workdir):
        assert day not in text


def test_measurement_makes_no_network_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ag yalitimi iddiasi YOK; ama olcumun kendisi hic baglanti kurmaz."""
    workdir = prepare(tmp_path)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("olcum adimi ag baglantisi denedi")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert measure(tmp_path, workdir) == 0


def test_measurement_never_opens_the_holdout(tmp_path: Path) -> None:
    workdir = prepare(tmp_path)
    with filesystem_access() as seen:
        assert measure(tmp_path, workdir) == 0
    assert seen, "denetim kancasi hicbir olay gormedi"
    touched = touched_under(seen, workdir / baseline_job.DATASET_DIR / "holdout")
    assert not touched, f"olcum holdout'a eristi: {touched}"


SECRET_ENV_NAMES = (
    "ALPACA_PAPER_API_KEY",
    "APCA_API_SECRET_KEY",
)


@pytest.mark.parametrize("name", SECRET_ENV_NAMES)
def test_a_key_in_the_measurement_environment_stops_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    workdir = prepare(tmp_path)
    assert measure(tmp_path, workdir, env={name: MARKERS["secret"]}) == 1
    text = capsys.readouterr().out
    assert MARKERS["secret"] not in text, "anahtar DEGERI basildi"
    assert name in text
    assert not (tmp_path / "report.json").exists()


def test_an_existing_report_is_refused_and_untouched(tmp_path: Path) -> None:
    workdir = prepare(tmp_path)
    (tmp_path / "report.json").write_text("eski rapor", "utf-8")
    assert measure(tmp_path, workdir) == 1
    assert (tmp_path / "report.json").read_text("utf-8") == "eski rapor"


def test_the_report_cannot_live_inside_the_work_directory(tmp_path: Path) -> None:
    workdir = prepare(tmp_path)
    code = baseline_job.measure({}, workdir=workdir, out=workdir / "report.json", root=REPO)
    assert code == 1
    assert not (workdir / "report.json").exists()


def test_a_symlinked_work_directory_is_refused(tmp_path: Path) -> None:
    workdir = prepare(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(workdir, target_is_directory=True)
    assert measure(tmp_path, alias) == 1
    assert not (tmp_path / "report.json").exists()


def test_a_symlinked_hash_file_is_refused(tmp_path: Path) -> None:
    workdir = prepare(tmp_path)
    real = tmp_path / "elsewhere.sha256"
    (workdir / baseline_job.HASH_FILE).rename(real)
    (workdir / baseline_job.HASH_FILE).symlink_to(real)
    assert measure(tmp_path, workdir) == 1
    assert not (tmp_path / "report.json").exists()


def test_a_manifest_that_does_not_match_the_hash_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workdir = prepare(tmp_path)
    (workdir / baseline_job.HASH_FILE).write_text("0" * 64 + "\n", "ascii")
    assert measure(tmp_path, workdir) == 1
    assert "FAIL butunluk" in capsys.readouterr().out
    assert not (tmp_path / "report.json").exists()


def test_an_unapproved_dataset_writes_no_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workdir = prepare(tmp_path, status="pilot")
    assert measure(tmp_path, workdir) == 1
    assert "FAIL onay" in capsys.readouterr().out
    assert not (tmp_path / "report.json").exists()


def test_a_quality_failure_reports_a_count_not_dates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ilk baseline gununde QQQ'nun ilk 5 dakikasi eksik: P&L'den once durur."""
    workdir = prepare(tmp_path, qqq_skip=5)
    assert measure(tmp_path, workdir) == 1
    text = capsys.readouterr().out
    assert "FAIL kalite: 1 baseline seansi uygunsuz" in text
    assert DAYS[0].isoformat() not in text, "kalite hatasi gun basti"
    assert "QQQ" not in text, "kalite hatasi sembol basti"
    assert not (tmp_path / "report.json").exists()


def test_a_carried_position_writes_no_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulasyon SIRASINDA duran kosu: o ana kadarki sonuc yazilmaz."""
    workdir = prepare(tmp_path)

    def carried(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise CarriedPositionError(f"SPY {DAYS[0]} seans sonunda acik")

    monkeypatch.setattr("tlab.backtest.baseline.run_baseline", carried)
    assert measure(tmp_path, workdir) == 1
    text = capsys.readouterr().out
    assert "FAIL seans siniri" in text
    assert DAYS[0].isoformat() not in text
    remaining = sorted(path.name for path in tmp_path.iterdir())
    assert remaining == ["work"], f"yarim ya da gecici rapor dosyasi kaldi: {remaining}"


def test_an_unexpected_error_prints_only_its_class(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = prepare(tmp_path)

    def boom(*_args: object, **_kwargs: object) -> bytes:
        raise RuntimeError(f"{MARKERS['body']} {DAYS[-1]}")

    monkeypatch.setattr("tlab.backtest.baseline.report_bytes", boom)
    assert measure(tmp_path, workdir) == 1
    text = capsys.readouterr().out
    assert "FAIL beklenmeyen hata (RuntimeError)" in text
    assert MARKERS["body"] not in text
    assert not (tmp_path / "report.json").exists()


def test_logging_is_restored_after_each_step(tmp_path: Path) -> None:
    """Kapatma adimla sinirli; cagiranin log ayari geri gelir."""
    logging.disable(logging.NOTSET)
    assert measure(tmp_path, prepare(tmp_path)) == 0
    assert logging.root.manager.disable == logging.NOTSET


def test_the_writer_is_atomic_and_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    baseline_job._write_new(target, b"ilk")
    with pytest.raises(FileExistsError):
        baseline_job._write_new(target, b"ikinci")
    assert target.read_bytes() == b"ilk"
    assert [path.name for path in tmp_path.iterdir()] == ["report.json"], "gecici dosya kaldi"


# --------------------------------------------------------------------------
# Uctan uca: A -> B, sahte sunucu
# --------------------------------------------------------------------------


def test_download_then_measure_end_to_end(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, state = stub
    market(state)
    with caplog.at_level(logging.DEBUG):
        assert download(stub, tmp_path, keys_env()) == 0
        assert measure(tmp_path, tmp_path / "work") == 0

    text = output(capsys, caplog)
    report_text = (tmp_path / "report.json").read_text("utf-8")
    assert not leaked(text + report_text), f"sizinti: {leaked(text + report_text)}"
    report = json.loads(report_text)
    assert report["dataset_id"] == "main-test"
    assert report["holdout"]["sessions"] == 1
    assert report["holdout"]["opened"] is False


def test_the_entry_point_fixes_the_main_spec(tmp_path: Path) -> None:
    """`main()` tanim yolunu disaridan almaz: `--spec` bir hata."""
    spec = DatasetSpec.from_yaml(REPO / baseline_job.MAIN_SPEC)
    assert spec.dataset_id == baseline_job.MAIN_SPEC.stem
    with pytest.raises(SystemExit):
        baseline_job.main(["download", "--workdir", str(tmp_path / "w"), "--spec", "x.yaml"])
    assert not (tmp_path / "w").exists()
