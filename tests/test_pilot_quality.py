"""Pilot kalite araci: gercek SDK -> yerel taklit sunucu.

#25 kabul sartlari burada OLCULUYOR, yazili kalmiyor:

  * Ozet ACIK BIR ALAN LISTESINDEN kurulur (sart 4). Anahtar kumeleri
    birebir sabit; yeni bir alan sessizce eklenemez.
  * Basari ve hata yollarinda fiyat, hacim, VWAP, islem sayisi, anahtar
    ve yanit govdesi hicbir ciktiya gecmez (sart 4-5). Yontem #18'deki
    gibi: sunucu yanitlarina SAHTE ISARETLER konur, butun cikti
    (stdout + stderr + logging + ozet dosyasi) yakalanip aranir.
  * Ham veri dizini her durumda silinir (sart 6).
  * Pilot disi bir tanim, tek bir ag istegi yapilmadan reddedilir.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpaca_stub import StubState, alpaca_stub
from tlab import pilot_quality
from tlab.data.dataset import DatasetSpec, QualityPolicy

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
DAYS = ("2026-01-05", "2026-01-06")

MARKERS = {
    "api_key": "PILOTCANARYKEYAAAAAA",
    "secret": "PILOTCANARYSECRETBBB",
    "open": "9876.54321",
    "close": "9876.12345",
    "vwap": "8765.4321",
    "volume": "3141592653",
    "trade_count": "2718281",
    "body": "PILOT-RESPONSE-BODY-CANARY",
}
"""Sunucu yanitlarina konan sahte isaretler. Ciktida ARANIR; biri
gorunurse arac sizdiriyor demektir."""


def _rows(day: str, *, skip_first: int = 0) -> list[dict[str, Any]]:
    opening = datetime.fromisoformat(f"{day}T14:30:00+00:00")
    rows = []
    for minute in range(skip_first, 390):
        rows.append(
            {
                "t": (opening + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "o": float(MARKERS["open"]),
                "h": float(MARKERS["open"]) + 1,
                "l": float(MARKERS["close"]) - 1,
                "c": float(MARKERS["close"]),
                "v": int(MARKERS["volume"]),
                "n": int(MARKERS["trade_count"]),
                "vw": float(MARKERS["vwap"]),
            }
        )
    return rows


def _market(state: StubState, *, qqq_skip_first: int = 0) -> None:
    state.calendar = [{"date": day, "open": "09:30", "close": "16:00"} for day in DAYS]
    state.bars = {
        "bars": {
            "SPY": [row for day in DAYS for row in _rows(day)],
            "QQQ": [
                row
                for index, day in enumerate(DAYS)
                for row in _rows(day, skip_first=qqq_skip_first if index == 0 else 0)
            ],
        },
        "next_page_token": None,
    }


def _spec(tmp_path: Path, status: str = "pilot") -> Path:
    path = tmp_path / "pilot.yaml"
    path.write_text(
        f"dataset_id: pilot-test\nstatus: {status}\nsymbols: [SPY, QQQ]\n"
        f"start: {DAYS[0]}\nend: {DAYS[1]}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def _run(
    stub: tuple[str, StubState],
    tmp_path: Path,
    status: str = "pilot",
    *,
    workdir: Path | None = None,
    out: Path | None = None,
    base_url: str | None = None,
) -> int:
    url, _ = stub
    return pilot_quality.run(
        MARKERS["api_key"],
        MARKERS["secret"],
        NOW,
        workdir=workdir or tmp_path / "raw",
        out=out or tmp_path / "summary.json",
        spec_path=_spec(tmp_path, status),
        base_url=base_url or url,
    )


def _all_output(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> str:
    captured = capsys.readouterr()
    summary = tmp_path / "summary.json"
    return (
        captured.out
        + captured.err
        + caplog.text
        + (summary.read_text("utf-8") if summary.exists() else "")
    )


def _leaked(output: str) -> list[str]:
    return sorted(name for name, value in MARKERS.items() if value in output)


# --------------------------------------------------------------------------
# Basari yolu
# --------------------------------------------------------------------------


def test_complete_data_gives_an_allowlisted_summary_and_no_raw_values(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _market(stub[1])
    with caplog.at_level(logging.DEBUG):
        assert _run(stub, tmp_path) == 0

    output = _all_output(capsys, caplog, tmp_path)
    assert not _leaked(output), f"cikti ham deger tasiyor: {_leaked(output)}"

    summary = json.loads((tmp_path / "summary.json").read_text("utf-8"))
    assert set(summary) == pilot_quality.SUMMARY_KEYS
    assert set(summary["sessions"]) == pilot_quality.SESSION_KEYS
    assert set(summary["producer"]) == pilot_quality.PRODUCER_KEYS
    for stats in summary["symbols"].values():
        assert set(stats) == pilot_quality.SYMBOL_KEYS
    assert summary["status"] == "pilot"
    assert summary["verdict"] == "all_eligible"
    assert summary["symbols"]["SPY"]["missing_fraction"] == 0.0
    assert summary["sessions"] == {
        "calendar": 2,
        "complete": 2,
        "incomplete": 0,
        "eligible": 2,
        "ineligible": 0,
    }


def test_the_raw_data_is_deleted_after_success(stub: tuple[str, StubState], tmp_path: Path) -> None:
    _market(stub[1])
    assert _run(stub, tmp_path) == 0
    assert not (tmp_path / "raw").exists(), "ham veri dizini silinmedi"


def test_gaps_are_counted_by_category_not_by_value(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    """Acilisin ilk 5 dakikasi eksik: seans uygunsuz, gerekce SAYILIR."""
    _market(stub[1], qqq_skip_first=5)
    assert _run(stub, tmp_path) == 0
    summary = json.loads((tmp_path / "summary.json").read_text("utf-8"))

    qqq = summary["symbols"]["QQQ"]
    assert qqq["sessions_open_window_incomplete"] == 1
    assert qqq["max_missing_open_window"] == 5
    assert qqq["ineligible_sessions"] == 1
    assert summary["reasons"] == {"acilis_penceresi_eksik": 1}
    assert summary["verdict"] == "some_ineligible"
    # Gerekce METNI ozete girmez; yalnizca kategori.
    assert "dk eksik" not in json.dumps(summary)


# --------------------------------------------------------------------------
# Hata yollari
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v2/stocks/bars", "/v2/calendar"])
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_errors_print_a_fixed_diagnosis_and_leak_nothing(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    path: str,
    status: int,
) -> None:
    """Hata govdesi sahte isaret tasirken hicbiri ciktiya gecmemeli.

    Hata KALICI: tek atimlik bir hata SDK'nin yeniden denemesiyle
    basariya doner ve test sessizce anlamsizlasir.
    """
    _, state = stub
    _market(state)
    body = {
        "message": f"{MARKERS['body']} key={MARKERS['api_key']}",
        "secret": MARKERS["secret"],
        "price": float(MARKERS["open"]),
    }
    state.fail(path, status, times=None, body=body)

    with caplog.at_level(logging.DEBUG):
        assert _run(stub, tmp_path) == 1

    output = _all_output(capsys, caplog, tmp_path)
    assert not _leaked(output), f"hata ciktisi sizdiriyor: {_leaked(output)}\n{output}"
    assert "FAIL indirme:" in output
    assert not (tmp_path / "summary.json").exists()
    assert not (tmp_path / "raw").exists(), "hata yolunda ham veri kaldi"


# --------------------------------------------------------------------------
# Tanim kapisi
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["draft", "approved"])
def test_only_a_pilot_spec_is_accepted_and_before_any_request(
    stub: tuple[str, StubState], tmp_path: Path, status: str
) -> None:
    _, state = stub
    _market(state)
    assert _run(stub, tmp_path, status=status) == 1
    assert state.requests == [], "tanim reddedilmeden ag istegi yapildi"


def test_the_workflow_entry_point_uses_the_fixed_pilot_spec() -> None:
    """`main()` spec yolunu disaridan almaz; sabit tanim pilot durumunda."""
    repo = Path(__file__).resolve().parents[1]
    spec = DatasetSpec.from_yaml(repo / pilot_quality.PILOT_SPEC)
    assert spec.status == "pilot"
    assert spec.dataset_id == pilot_quality.PILOT_SPEC.stem


def test_missing_keys_fail_before_anything(tmp_path: Path) -> None:
    code = pilot_quality.run(
        "", "", NOW, workdir=tmp_path / "raw", out=tmp_path / "s.json", spec_path=tmp_path
    )
    assert code == 1
    assert not (tmp_path / "raw").exists()


# --------------------------------------------------------------------------
# Calisma dizini sahipligi (Codex #27 P2)
#
# Eski surum var olan bir dizini reddettikten sonra `finally` icinde
# kosulsuz siliyordu: Codex existing/keep.txt ile calistirdi, dosya
# gitti. Arac yalnizca KENDI olusturdugu dizini silebilir.
# --------------------------------------------------------------------------


def test_an_existing_directory_is_refused_and_left_untouched(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("degerli veri", "utf-8")

    _market(stub[1])
    assert _run(stub, tmp_path, workdir=existing) == 1
    assert (existing / "keep.txt").read_text("utf-8") == "degerli veri"
    assert stub[1].requests == [], "dizin reddedilmeden ag istegi yapildi"


def test_an_existing_file_at_the_workdir_path_is_left_untouched(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    existing = tmp_path / "a-file"
    existing.write_text("dokunma", "utf-8")
    assert _run(stub, tmp_path, workdir=existing) == 1
    assert existing.read_text("utf-8") == "dokunma"
    assert stub[1].requests == []


def test_a_symlink_at_the_workdir_path_is_not_followed(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("hedef", "utf-8")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    assert _run(stub, tmp_path, workdir=link) == 1
    assert link.is_symlink()
    assert (target / "keep.txt").read_text("utf-8") == "hedef"
    assert stub[1].requests == []


def test_the_summary_cannot_live_inside_the_raw_directory(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    """Ham dizin silinirken ozet de giderdi - ya da ozet ham verinin
    yaninda disari tasinmaya aday olurdu. Ag isteginden once ret."""
    raw = tmp_path / "raw"
    assert _run(stub, tmp_path, workdir=raw, out=raw / "summary.json") == 1
    assert not raw.exists()
    assert stub[1].requests == []


def test_the_raw_directory_created_by_the_call_is_removed_on_error(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    _market(state)
    state.fail("/v2/stocks/bars", 500, times=None)
    assert _run(stub, tmp_path) == 1
    assert not (tmp_path / "raw").exists()


# --------------------------------------------------------------------------
# Codex #17 onerileri: politika alanlari, HTTP disi hata yollari
# --------------------------------------------------------------------------


def test_the_policy_in_the_summary_is_an_explicit_field_set(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    """Manifest sozlugu oldugu gibi gecmez; alanlar tek tek secilir.
    QualityPolicy'ye alan eklenirse bu test kumenin bilincli
    guncellenmesini ister."""
    assert set(QualityPolicy.model_fields) == pilot_quality.POLICY_KEYS
    _market(stub[1])
    assert _run(stub, tmp_path) == 0
    summary = json.loads((tmp_path / "summary.json").read_text("utf-8"))
    assert set(summary["policy"]) == pilot_quality.POLICY_KEYS


def test_an_invalid_bar_is_diagnosed_without_echoing_its_values(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bar dogrulama hatasi mesaja DEGERI koyar (ornegin high < low).
    Arac o mesaji basmamali: yalnizca sabit tani ve sinif adi."""
    _, state = stub
    _market(state)
    broken = dict(state.bars["bars"]["SPY"][0])
    broken["h"] = float(MARKERS["close"]) - 50  # high < low: gecersiz OHLC
    state.bars["bars"]["SPY"][0] = broken

    with caplog.at_level(logging.DEBUG):
        assert _run(stub, tmp_path) == 1
    output = _all_output(capsys, caplog, tmp_path)
    assert not _leaked(output), f"gecersiz bar hatasi deger sizdirdi: {_leaked(output)}"
    assert "FAIL indirme:" in output
    assert not (tmp_path / "raw").exists()


def test_a_dropped_connection_is_a_network_diagnosis(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sunucu yok: baglanti reddedilir. Tani 'ag' olmali ve sizinti olmamali."""
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    with caplog.at_level(logging.DEBUG):
        code = _run(stub, tmp_path, base_url=f"http://127.0.0.1:{closed_port}")
    assert code == 1
    output = _all_output(capsys, caplog, tmp_path)
    assert "ag, TLS veya zaman asimi hatasi" in output
    assert not _leaked(output)
    assert not (tmp_path / "raw").exists()


# --------------------------------------------------------------------------
# Log kapali (#17): arac boyunca `logging` kapatilir
#
# Bugun pilotun yolunda loglayan bir modul yok; urllib3 ve requests kendi
# NullHandler'larini takar, yani log yapilandirmasi YOKKEN hicbir kayit
# ekrana dusmez. Guvence yapilandirma VARKEN de gecerli olmali: pytest'in
# log yakalamasi tam da o durumu kurar.
# --------------------------------------------------------------------------


def _address_warnings(records: list[logging.LogRecord]) -> list[str]:
    return [
        record.getMessage()
        for record in records
        if record.levelno >= logging.WARNING and "/v2/stocks/bars" in record.getMessage()
    ]


def test_the_broken_header_really_logs_the_request_address(
    stub: tuple[str, StubState], caplog: pytest.LogCaptureFixture
) -> None:
    """KONTROL: senaryo gercek. Arac DISINDA ayni istek, adresi tarih ve
    sembolle WARNING duzeyinde loglar. Bu test duserse asagidaki log
    testi bos yere yesil kalir (ornegin urllib3 bu uyariyi kaldirdi)."""
    from tlab.core.types import Timeframe
    from tlab.data.market import AlpacaMarketData

    url, state = stub
    _market(state)
    state.broken_header_paths.add("/v2/stocks/bars")
    market = AlpacaMarketData(MARKERS["api_key"], MARKERS["secret"], base_url=url)
    start = datetime.fromisoformat(f"{DAYS[0]}T14:30:00+00:00")
    with caplog.at_level(logging.DEBUG):
        bars = market.bars("SPY", Timeframe.M1, start=start)

    assert bars, "bozuk baslik govdeyi okutmadi; senaryo gecersiz"
    warnings = _address_warnings(caplog.records)
    assert warnings, "bozuk baslik adresli bir WARNING uretmedi"
    assert "symbols=SPY" in warnings[0]
    assert DAYS[0] in warnings[0]


@pytest.mark.parametrize("fails", [False, True], ids=["basari", "indirme-hatasi"])
def test_no_log_record_is_created_while_the_tool_runs(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    fails: bool,
) -> None:
    """Ayni senaryo ARACIN ICINDE: hicbir duzeyde kayit olusmaz; istek
    adresi ve tarih hicbir ciktida yok."""
    _, state = stub
    _market(state)
    state.broken_header_paths.add("/v2/stocks/bars")
    if fails:
        state.fail("/v2/stocks/bars", 500, times=None)

    with caplog.at_level(logging.DEBUG):
        assert _run(stub, tmp_path) == (1 if fails else 0)

    assert caplog.records == [], [record.getMessage()[:80] for record in caplog.records]
    output = _all_output(capsys, caplog, tmp_path)
    assert "/v2/stocks/bars" not in output
    for day in DAYS:
        assert day not in output, f"cikti bir gun tasiyor: {day}"


@pytest.mark.parametrize("fails", [False, True], ids=["basari", "indirme-hatasi"])
@pytest.mark.parametrize("previous", [logging.NOTSET, logging.INFO], ids=["acik", "info-kapali"])
def test_the_callers_logging_setting_is_restored(
    stub: tuple[str, StubState], tmp_path: Path, fails: bool, previous: int
) -> None:
    """Kapatma aracla sinirli: cikista cagiranin ayari - ne ise - geri gelir."""
    _, state = stub
    _market(state)
    if fails:
        state.fail("/v2/stocks/bars", 500, times=None)
    logging.disable(previous)
    try:
        assert _run(stub, tmp_path) == (1 if fails else 0)
        assert logging.root.manager.disable == previous
    finally:
        logging.disable(logging.NOTSET)
