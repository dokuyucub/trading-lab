"""Golge toplam raporu (`scripts/shadow_report.py`): gercek `summarize` ciktisindan
sade Turkce Markdown; sema ve alan sapmalari sabit hatayla durur; fiyat yok.

`--kabul` tablosu (`docs/designs/unattended-paper.md` §1): esikler tasarimdaki
sayilarla sabit, betigin bilemedigi satirlar elle dogrulanir, genel hukum yok."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tlab.shadow.core import (
    RANGE_COMPUTED,
    RANGE_SIP_MISSING,
    SIGNAL_MATCH,
    SIGNAL_MISMATCH,
    SIGNAL_NONE,
    Comparison,
)
from tlab.shadow.summary import Day, SymbolDay, Thresholds, summarize

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "shadow_report.py"
D1, D2, D3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
PLANNED = (D1, D2, D3)
SYMBOLS = ("SPY", "QQQ")
CAMPAIGN = "a" * 64
IMPLEMENTATION = "b" * 64
EASY = Thresholds(range_min_support=1, intent_min_support=1, intent_min_days=1)
THRESHOLDS = asdict(EASY)


@pytest.fixture(scope="module")
def report() -> ModuleType:
    spec = importlib.util.spec_from_file_location("shadow_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["shadow_report"] = module
    spec.loader.exec_module(module)
    return module


def comparison(symbol: str, *, within: bool = True, signal: str = SIGNAL_MATCH) -> Comparison:
    bps = 1.0 if within else 9.0
    first = None if signal == SIGNAL_NONE else 40.1167
    return Comparison(
        symbol=symbol,
        window_expected=15,
        iex_present=15,
        sip_present=15,
        iex_completed_later=False,
        or_high_bps=bps,
        or_low_bps=-bps,
        range_status=RANGE_COMPUTED,
        signal=signal,
        iex_first_minute=first,
        sip_first_minute=first,
        iex_unknown_turns=0,
    )


def unknown(symbol: str) -> Comparison:
    return Comparison(
        symbol=symbol,
        window_expected=15,
        iex_present=None,
        sip_present=None,
        iex_completed_later=False,
        or_high_bps=None,
        or_low_bps=None,
        range_status=RANGE_SIP_MISSING,
        signal="unknown",
        iex_first_minute=None,
        sip_first_minute=None,
        iex_unknown_turns=0,
    )


def total(
    days: list[Day],
    results: list[SymbolDay],
    thresholds: Thresholds = EASY,
    planned: Sequence[date] = PLANNED,
    symbols: Sequence[str] = SYMBOLS,
) -> dict[str, Any]:
    summary = summarize(planned, symbols, days, results, thresholds)
    summary["campaign"] = CAMPAIGN
    summary["implementation"] = IMPLEMENTATION
    loaded: dict[str, Any] = json.loads(json.dumps(summary))
    return loaded


def passing() -> dict[str, Any]:
    days = [Day(day, "tamam") for day in PLANNED]
    results = [
        SymbolDay(day, symbol, comparison(symbol), True) for day in PLANNED for symbol in SYMBOLS
    ]
    return total(days, results)


def failing() -> dict[str, Any]:
    days = [Day(day, "tamam") for day in PLANNED]
    results = [
        SymbolDay(day, symbol, comparison(symbol, within=False, signal=SIGNAL_MISMATCH), True)
        for day in PLANNED
        for symbol in SYMBOLS
    ]
    return total(days, results)


def inconclusive() -> dict[str, Any]:
    days = [Day(D1, "eksik", "gec baslangic"), Day(D2, "bilinmiyor", "kosu kaydi yok")]
    results = [SymbolDay(D3, symbol, unknown(symbol), False) for symbol in SYMBOLS]
    return total(days, results)


def test_a_passing_campaign_renders_the_three_answers(report: ModuleType) -> None:
    text = report.render(passing())
    assert text.startswith("# Gölge gözlem sonucu")
    assert text.count("**GEÇTİ**") == 3
    assert "6 / 6 (%100.0); bilinen 6, bilinmeyen 0, farklı gün 3" in text
    assert f"`{CAMPAIGN}`" in text and f"`{IMPLEMENTATION}`" in text
    assert "| 2026-11-02 | tamam | — |" in text
    assert "| SPY | 3/3 (bilinmeyen 0) | 3/3 (bilinmeyen 0) | 3/3 (bilinmeyen 0) |" in text
    assert "ÖNERİ" in text and "- range_bps: 5" in text
    assert "SIP referans verisiyle" in text and "eksiksiz" not in text
    assert "en az 1 bilinen gözlem ve 1 farklı gün; destek yoksa" in text
    assert "SIP hakkında kanıt yoksa gözlem bilinmeyen sayılır" in text
    assert "aralık ölçüsünün dışında, ek sayımlarda ayrı tutulur" in text


def test_a_failing_campaign_says_so(report: ModuleType) -> None:
    text = report.render(failing())
    assert "**GEÇTİ**" in text, "pencere tamligi gecer"
    assert text.count("**KALDI**") == 2, "aralik ve niyet kalir"
    assert "0 / 6 (%0.0); bilinen 6, bilinmeyen 0" in text


def test_an_inconclusive_campaign_keeps_unknowns_in_the_denominator(report: ModuleType) -> None:
    text = report.render(inconclusive())
    assert text.count("**BELİRSİZ**") == 3
    assert "| 2026-11-02 | eksik | gec baslangic |" in text
    assert "| 2026-11-03 | bilinmiyor | kosu kaydi yok |" in text
    assert "| 2026-11-04 | bilinmiyor | kanit yok |" in text
    assert "0 / 6 (%0.0); bilinen 0, bilinmeyen 6, farklı gün 0" in text


def test_the_report_carries_no_prices_or_raw_data(report: ModuleType) -> None:
    summary = passing()
    summary["range_bps"] = [
        {"day": "2026-11-02", "symbol": "SPY", "high_bps": 1.0, "low_bps": -1.0}
    ]
    text = report.render(summary)
    assert "high_bps" not in text and "1.0" not in text.replace("%100.0", "")
    assert "100.5" not in text


CASES: list[tuple[str, Any, str]] = [
    ("sema", {"summary_schema": 2}, "toplam ozeti semasi tanimsiz"),
    ("sema-bool", {"summary_schema": True}, "toplam ozeti semasi tanimsiz"),
    ("fazla-alan", {"price": 1}, "alanlari beklenen kumede degil"),
    ("evren-bos", {"symbols": []}, "evren beklenen bicimde degil"),
    ("evren-tekrar", {"symbols": ["SPY", "SPY"]}, "evren beklenen bicimde degil"),
    (
        "gun-sayimi",
        {"days": {"tamam": 9, "eksik": 0, "baslamadi": 0, "bilinmiyor": 0}},
        "gun sayimlari",
    ),
    ("gun-listesi", {"day_list": []}, "gun listesi beklenen bicimde degil"),
    ("oneri-degil", {"thresholds_are_proposals": False}, "esikler oneri olarak isaretli degil"),
    ("esik-eksik", {"thresholds": {"completeness": 0.95}}, "esikler beklenen bicimde degil"),
    (
        "esik-metin",
        {"thresholds": {**THRESHOLDS, "completeness": "x"}},
        "esikler beklenen bicimde degil",
    ),
    (
        "esik-bool",
        {"thresholds": {**THRESHOLDS, "range_bps": True}},
        "esikler beklenen bicimde degil",
    ),
    (
        "esik-yok",
        {"thresholds": {**THRESHOLDS, "intent_share": None}},
        "esikler beklenen bicimde degil",
    ),
    ("kampanya", {"campaign": "x"}, "campaign kimligi beklenen bicimde degil"),
    ("parmak-izi", {"implementation": "A" * 64}, "implementation kimligi beklenen bicimde degil"),
    ("aralik-liste", {"range_bps": {}}, "aralik farki listesi beklenen bicimde degil"),
]


@pytest.mark.parametrize(("overrides", "reason"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_a_field_that_breaks_the_schema_is_refused(
    overrides: dict[str, Any], reason: str, report: ModuleType
) -> None:
    summary = {**passing(), **overrides}
    with pytest.raises(report.ReportError, match=reason):
        report.render(summary)


MEASURE_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("sonuc-tanimsiz", {"verdict": "evet"}, "iex_window_initial sonucu tanimsiz"),
    ("sonuc-yok", {"verdict": None}, "iex_window_initial sonucu tanimsiz"),
    ("sonuc-liste", {"verdict": []}, "iex_window_initial sonucu tanimsiz"),
    ("sonuc-sozluk", {"verdict": {}}, "iex_window_initial sonucu tanimsiz"),
    ("pay-bool", {"numerator": True}, "iex_window_initial beklenen bicimde degil"),
    ("pay-negatif", {"numerator": -1}, "iex_window_initial beklenen bicimde degil"),
    ("gun-negatif", {"distinct_days": -1}, "iex_window_initial beklenen bicimde degil"),
    ("fazla-bilinmeyen", {"unknown": 7}, "iex_window_initial sayaclari tutarsiz"),
    (
        "fazla-bilinmeyen-paysiz",
        {"numerator": 0, "unknown": 7},
        "iex_window_initial sayaclari tutarsiz",
    ),
    ("pay-fazla", {"numerator": 7}, "iex_window_initial sayaclari tutarsiz"),
]


@pytest.mark.parametrize(
    ("overrides", "reason"), [c[1:] for c in MEASURE_CASES], ids=[c[0] for c in MEASURE_CASES]
)
def test_a_measure_that_breaks_the_contract_is_refused(
    overrides: dict[str, Any], reason: str, report: ModuleType
) -> None:
    summary = passing()
    summary["total"]["iex_window_initial"].update(overrides)
    with pytest.raises(report.ReportError, match=reason):
        report.render(summary)


@pytest.mark.parametrize(
    ("status", "reason"),
    [("tamam", "x"), ("eksik", None), ("baslamadi", None), ("bilinmiyor", None), ("yok", "x")],
    ids=[
        "tamam-sebepli",
        "eksik-sebepsiz",
        "baslamadi-sebepsiz",
        "bilinmiyor-sebepsiz",
        "durum-tanimsiz",
    ],
)
def test_a_day_whose_status_and_reason_disagree_is_refused(
    status: str, reason: str | None, report: ModuleType
) -> None:
    summary = passing()
    summary["day_list"][0].update({"status": status, "reason": reason})
    with pytest.raises(report.ReportError, match="gun listesi beklenen bicimde degil"):
        report.render(summary)


DAY_LIST_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("durum-liste", {"status": []}, "gun listesi beklenen bicimde degil"),
    ("durum-sozluk", {"status": {}}, "gun listesi beklenen bicimde degil"),
    ("tarih-bicim", {"day": "2026/11/02"}, "gun listesi beklenen bicimde degil"),
    ("tarih-kisa", {"day": "2026-11-2"}, "gun listesi beklenen bicimde degil"),
    ("tarih-gercek-degil", {"day": "2026-11-31"}, "gun listesi beklenen bicimde degil"),
    ("tarih-tekrar", {"day": "2026-11-03"}, "gun listesi beklenen bicimde degil"),
    (
        "sayimla-celisen-durum",
        {"status": "eksik", "reason": "gec baslangic"},
        "gun listesi ile gun sayimlari uyusmuyor",
    ),
]


@pytest.mark.parametrize(
    ("overrides", "reason"), [c[1:] for c in DAY_LIST_CASES], ids=[c[0] for c in DAY_LIST_CASES]
)
def test_a_day_list_that_contradicts_the_counts_or_the_calendar_is_refused(
    overrides: dict[str, Any], reason: str, report: ModuleType
) -> None:
    """Gun sayimlari ile gun listesi ayni seyi soylemeli; tarihler gercek ve
    tekrarsiz olmali. Bozuk JSON turu sabit hatayla durur, traceback ile degil."""
    summary = passing()
    summary["day_list"][0].update(overrides)
    with pytest.raises(report.ReportError, match=reason):
        report.render(summary)


def test_per_symbol_measures_carry_no_verdict_and_must_cover_the_universe(
    report: ModuleType,
) -> None:
    summary = passing()
    summary["per_symbol"]["SPY"]["iex_window_initial"]["verdict"] = "gecti"
    with pytest.raises(report.ReportError, match="iex_window_initial beklenen bicimde degil"):
        report.render(summary)
    summary = passing()
    del summary["per_symbol"]["QQQ"]
    with pytest.raises(report.ReportError, match="sembol ozetleri beklenen bicimde degil"):
        report.render(summary)


def test_the_cli_writes_once_and_refuses_bad_input(
    report: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "shadow-total.json"
    source.write_text(json.dumps(passing()), encoding="utf-8")
    out = tmp_path / "rapor.md"
    assert report.main(["--summary", str(source), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Gölge gözlem sonucu")
    assert "OK rapor: rapor.md" in capsys.readouterr().out
    assert report.main(["--summary", str(source), "--out", str(out)]) == 1
    assert "HATA: rapor yazilamadi (FileExistsError)" in capsys.readouterr().err
    assert report.main(["--summary", str(source)]) == 0
    assert capsys.readouterr().out.startswith("# Gölge gözlem sonucu")
    source.write_text("{bozuk", encoding="utf-8")
    assert report.main(["--summary", str(source)]) == 1
    assert "HATA: toplam ozeti okunamadi (JSONDecodeError)" in capsys.readouterr().err
    source.write_text(json.dumps({**passing(), "summary_schema": 9}), encoding="utf-8")
    assert report.main(["--summary", str(source)]) == 1
    assert "HATA: toplam ozeti semasi tanimsiz" in capsys.readouterr().err
    broken = passing()
    broken["total"]["iex_window_initial"]["verdict"] = []
    source.write_text(json.dumps(broken), encoding="utf-8")
    assert report.main(["--summary", str(source)]) == 1
    err = capsys.readouterr().err
    assert "HATA: iex_window_initial sonucu tanimsiz" in err and "Traceback" not in err
    broken = passing()
    broken["day_list"][0]["status"] = []
    source.write_text(json.dumps(broken), encoding="utf-8")
    assert report.main(["--summary", str(source)]) == 1
    err = capsys.readouterr().err
    assert "HATA: gun listesi beklenen bicimde degil" in err and "Traceback" not in err
    assert report.main(["--summary", str(tmp_path / "yok.json")]) == 1
    assert "HATA: toplam ozeti okunamadi (FileNotFoundError)" in capsys.readouterr().err


# --- Paper kabul olcutleri (`--kabul`): docs/designs/unattended-paper.md §1 ---

PLAN20 = tuple(day for day in (D1 + timedelta(days=n) for n in range(28)) if day.weekday() < 5)
"""Kampanya gibi 20 planli gun: 2026-11-02 .. 2026-11-27, hafta ici."""
UNIVERSE = ("SPY", "QQQ", "IWM", "DIA", "AAPL")
DEFAULTS = Thresholds()
MET, UNMET, MANUAL = "sağlandı", "sağlanmadı", "elle doğrulanacak"
WINDOW, RANGE, INTENT, COVERAGE, SYSTEMATIC, FIRST_DAY, NO_RUN = range(7)


def campaign(
    *,
    planned: Sequence[date] = PLAN20,
    marked: Sequence[Day] = (),
    absent: Sequence[date] = (),
    signal: str = SIGNAL_MATCH,
    thresholds: Thresholds = DEFAULTS,
) -> dict[str, Any]:
    """Tasarimdaki VARSAYILAN esiklerle 20 gun x 5 sembol (100 sembol-gun) toplami.

    `marked` gunler verilen durumu alir ama gozlemleri durur: degisen tek sey gun
    durumudur. `absent` gunlerin ne ozeti ne gozlemi vardir (`bilinmiyor`).
    """
    override = {day.day: day for day in marked}
    seen = [day for day in planned if day not in absent]
    days = [override.get(day, Day(day, "tamam")) for day in seen]
    results = [
        SymbolDay(day, symbol, comparison(symbol, signal=signal), True)
        for day in seen
        for symbol in UNIVERSE
    ]
    return total(days, results, thresholds, planned, UNIVERSE)


def late(count: int) -> list[Day]:
    """Planin son `count` gunu `eksik (gec baslangic)`."""
    return [Day(day, "eksik", "gec baslangic") for day in PLAN20[len(PLAN20) - count :]]


def statuses(rows: list[dict[str, str]]) -> list[str]:
    return [row["durum"] for row in rows]


def test_a_clean_campaign_meets_every_criterion_the_script_can_read(report: ModuleType) -> None:
    summary = campaign()
    assert [summary["total"][name]["verdict"] for name, _ in report.MEASURES] == ["gecti"] * 3
    assert summary["days"] == {"tamam": 20, "eksik": 0, "baslamadi": 0, "bilinmiyor": 0}
    rows = report.acceptance(summary)
    assert [set(row) for row in rows] == [{"olcut", "durum", "kanit"}] * 7
    assert statuses(rows) == [MET, MET, MET, MET, MANUAL, MANUAL, MET]
    for position, name in ((WINDOW, "iex_window_initial"), (RANGE, "range_within_bps")):
        assert f"`{name}`" in rows[position]["olcut"]
        assert rows[position]["kanit"] == "sonuç GEÇTİ; gereken GEÇTİ"
    assert "`intent_agreement`" in rows[INTENT]["olcut"]
    assert rows[COVERAGE]["kanit"] == "tamam 20 / planlı 20; gereken en az 15 / 20"
    assert rows[NO_RUN]["kanit"] == "koşusuz gün yok (başlamadı 0, bilinmiyor 0)"


def test_the_measure_thresholds_are_the_design_defaults(report: ModuleType) -> None:
    """Tasarim "GECTI (`Thresholds` varsayilani)" der. Betik `tlab`i ice aktaramaz;
    sayilarin kopyasi burada kaynagina baglanir. Gevsetilmis esikle hesaplanmis
    ozetteki GECTI olcutu saglamaz."""
    assert asdict(DEFAULTS) == report.ACCEPT_THRESHOLDS
    summary = campaign(thresholds=EASY)
    assert [summary["total"][name]["verdict"] for name, _ in report.MEASURES] == ["gecti"] * 3
    rows = report.acceptance(summary)
    assert statuses(rows) == [UNMET, UNMET, UNMET, MET, MANUAL, MANUAL, MET]
    assert rows[WINDOW]["kanit"] == (
        "sonuç GEÇTİ; gereken GEÇTİ; özet tasarımdaki varsayılan eşiklerle hesaplanmamış"
    )


@pytest.mark.parametrize(
    ("signal", "verdict", "label"),
    [(SIGNAL_NONE, "belirsiz", "BELİRSİZ"), (SIGNAL_MISMATCH, "kaldi", "KALDI")],
    ids=["belirsiz", "kaldi"],
)
def test_a_measure_that_is_not_passed_is_never_rounded_up(
    signal: str, verdict: str, label: str, report: ModuleType
) -> None:
    """Gercek `summarize` sonucu: hic niyet yoksa destek 0 < 30 ve olcu `belirsiz`;
    niyetler uyusmuyorsa `kaldi`. Ikisi de saglanmamistir."""
    summary = campaign(signal=signal)
    assert summary["total"]["intent_agreement"]["verdict"] == verdict
    rows = report.acceptance(summary)
    assert statuses(rows) == [MET, MET, UNMET, MET, MANUAL, MANUAL, MET]
    assert rows[INTENT]["kanit"] == f"sonuç {label}; gereken GEÇTİ"


@pytest.mark.parametrize("verdict", ["belirsiz", "kaldi"])
@pytest.mark.parametrize("position", [WINDOW, RANGE, INTENT])
def test_only_gecti_meets_a_measure_and_each_measure_has_its_own_row(
    position: int, verdict: str, report: ModuleType
) -> None:
    summary = campaign()
    summary["total"][report.MEASURES[position][0]]["verdict"] = verdict
    expected = [MET, MET, MET, MET, MANUAL, MANUAL, MET]
    expected[position] = UNMET
    assert statuses(report.acceptance(summary)) == expected


@pytest.mark.parametrize(("complete", "durum"), [(15, MET), (14, UNMET)], ids=["15", "14"])
def test_fifteen_of_twenty_complete_days_is_the_boundary(
    complete: int, durum: str, report: ModuleType
) -> None:
    """Yalniz gun durumu degisir (gozlemler durur): 14 `tamam` tek satiri dusurur."""
    summary = campaign(marked=late(20 - complete))
    assert summary["planned_days"] == 20
    assert summary["days"] == {
        "tamam": complete,
        "eksik": 20 - complete,
        "baslamadi": 0,
        "bilinmiyor": 0,
    }
    rows = report.acceptance(summary)
    assert statuses(rows) == [MET, MET, MET, durum, MANUAL, MANUAL, MET]
    assert rows[COVERAGE]["kanit"] == f"tamam {complete} / planlı 20; gereken en az 15 / 20"
    assert rows[SYSTEMATIC]["kanit"].startswith(f"tamam olmayan gün {20 - complete};")


@pytest.mark.parametrize(("complete", "durum"), [(15, MET), (14, UNMET)], ids=["15", "14"])
def test_only_complete_days_count_toward_the_fifteen(
    complete: int, durum: str, report: ModuleType
) -> None:
    """Esik `planli - eksik` degil, `tamam` sayisidir: `baslamadi` ve `bilinmiyor`
    gunler `eksik` sayilmadiklari icin sessizce `tamam`a eklenmez."""
    rest = PLAN20[complete:]
    summary = campaign(marked=[Day(rest[0], "baslamadi", "gozlem baslamadi")], absent=rest[1:])
    assert summary["days"] == {
        "tamam": complete,
        "eksik": 0,
        "baslamadi": 1,
        "bilinmiyor": 19 - complete,
    }
    rows = report.acceptance(summary)
    assert rows[COVERAGE]["durum"] == durum
    assert rows[COVERAGE]["kanit"] == f"tamam {complete} / planlı 20; gereken en az 15 / 20"
    assert rows[SYSTEMATIC]["kanit"].startswith(f"tamam olmayan gün {20 - complete};")


def test_the_day_threshold_is_written_for_a_twenty_day_plan(report: ModuleType) -> None:
    """Tasarim "15/20" der. Baska uzunlukta bir plan icin esik uydurulmaz: 21 gunun
    21'i `tamam` olsa da satir saglanmaz ve nedeni yazilir."""
    summary = campaign(planned=(*PLAN20, date(2026, 11, 30)))
    assert summary["days"]["tamam"] == summary["planned_days"] == 21
    row = report.acceptance(summary)[COVERAGE]
    assert row["durum"] == UNMET
    assert row["kanit"] == (
        "tamam 21 / planlı 21; gereken en az 15 / 20; ölçüt 20 günlük plan için yazıldı"
    )
    assert report.acceptance(passing())[COVERAGE]["durum"] == UNMET, "3 gunluk plan"


def test_days_without_a_run_are_listed_and_left_to_a_person(report: ModuleType) -> None:
    """Ozeti ve gozlemi olmayan gun `bilinmiyor`dur; kayit isinin hic kosmadigi
    `baslamadi` gunuyle birlikte satirda adiyla gorunur. Kosusu olan `eksik` gun
    bu satira girmez. Sebebin aciklanip aciklanmadigini betik bilemez."""
    summary = campaign(
        marked=[Day(PLAN20[1], "baslamadi", "gozlem baslamadi"), late(1)[0]],
        absent=[PLAN20[2]],
    )
    assert summary["day_list"][2] == {
        "day": "2026-11-04",
        "status": "bilinmiyor",
        "reason": "kanit yok",
    }
    assert summary["days"] == {"tamam": 17, "eksik": 1, "baslamadi": 1, "bilinmiyor": 1}
    row = report.acceptance(summary)[NO_RUN]
    assert row["durum"] == MANUAL
    assert row["kanit"] == (
        "koşusuz ya da koşusu bilinmeyen gün 2: 2026-11-03 (başlamadı), "
        "2026-11-04 (bilinmiyor); açıklaması günlük kayıtlardan doğrulanır"
    )
    assert "2026-11-27" not in row["kanit"], "eksik gunun kosusu vardir"


@pytest.mark.parametrize("build", [campaign, passing, failing, inconclusive])
def test_the_script_never_answers_what_it_cannot_know(
    build: Callable[[], dict[str, Any]], report: ModuleType
) -> None:
    """Ilk gun denetimi ve "sistematik degil" #17 kayitlarindadir: sonuc ne olursa
    olsun, eksik gun hic olmasa da, bu iki satir elle dogrulanir."""
    rows = report.acceptance(build())
    assert len(rows) == 7 and set(statuses(rows)) <= {MET, UNMET, MANUAL}
    assert "sistematik değil" in rows[SYSTEMATIC]["olcut"]
    assert rows[FIRST_DAY]["olcut"].startswith("İlk gün denetimi")
    assert rows[SYSTEMATIC]["durum"] == rows[FIRST_DAY]["durum"] == MANUAL
    assert "betik" in rows[SYSTEMATIC]["kanit"] and "betik" in rows[FIRST_DAY]["kanit"]


def test_the_table_says_it_is_not_a_decision_and_gives_no_overall_verdict(
    report: ModuleType,
) -> None:
    """Tablo disindaki metin sonuca gore DEGISMEZ ve hukum sozcugu tasimaz; tabloda
    yedi olcut satirindan baska satir (toplam, genel sonuc) yoktur. Bolum kimlik
    tekrarlamaz: kampanya ve parmak izi yalniz raporun basindadir."""
    section = report.render_acceptance(report.acceptance(campaign()))
    assert CAMPAIGN not in section and IMPLEMENTATION not in section
    met = section.splitlines()
    unmet = report.render_acceptance(report.acceptance(failing())).splitlines()
    assert "## Paper kabul ölçütleri (karar değildir)" in met
    prose = [line for line in met if not line.startswith("|")]
    assert prose == [line for line in unmet if not line.startswith("|")]
    assert any(line.startswith("Bu tablo karar değildir.") for line in prose)
    for word in (MET, UNMET, "GEÇTİ", "geçti", "KALDI", "kaldı", "geçilebilir", "geçilir"):
        assert word not in "\n".join(prose), word
    table = [line for line in met if line.startswith("|")]
    assert table[:2] == ["| Ölçüt | Durum | Kanıt |", "|---|---|---|"] and len(table) == 2 + 7
    assert all(f"| {MET} |" in line or f"| {MANUAL} |" in line for line in table[2:])
    assert sum(f"| {UNMET} |" in line for line in unmet) == 4, "uc olcu ve gun kapsamasi"


def write_summary(tmp_path: Path, summary: dict[str, Any]) -> str:
    source = tmp_path / "shadow-total.json"
    source.write_text(json.dumps(summary), encoding="utf-8")
    return str(source)


@pytest.mark.parametrize("other", ["c" * 64, CAMPAIGN.upper(), CAMPAIGN[:63], ""])
def test_a_campaign_mismatch_is_a_fixed_error(other: str, report: ModuleType) -> None:
    summary = campaign()
    with pytest.raises(report.ReportError, match=r"^kampanya kimligi beklenenle uyusmuyor$"):
        report.acceptance(summary, expected_campaign=other)
    assert report.acceptance(summary, expected_campaign=CAMPAIGN) == report.acceptance(summary)


def test_the_cli_prints_no_report_and_no_table_for_another_campaign(
    report: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, out = write_summary(tmp_path, campaign()), tmp_path / "rapor.md"
    wrong = ["--summary", source, "--kabul", "--campaign", "c" * 64]
    for argv in (wrong, [*wrong, "--out", str(out)]):
        assert report.main(argv) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "HATA: kampanya kimligi beklenenle uyusmuyor\n"
    assert not out.exists()
    with pytest.raises(SystemExit):
        report.main(["--summary", source, "--campaign", CAMPAIGN])
    assert "--campaign yalniz --kabul ile kullanilir" in capsys.readouterr().err


def test_without_the_flag_the_output_is_byte_for_byte_the_unmodified_report(
    report: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Altin metni AYNI kosuda, dokunulmamis `render` uretir: bayraksiz CLI ciktisi
    (stdout ve `--out`) onunla bayt bayt esittir. Tablo yalniz `--kabul` ile, raporun
    sonuna eklenir; rapor govdesi degismez. Cikis kodu da hukum degildir: 14/20 ile
    gun kapsamasi saglanmamisken `--kabul` 0 doner."""
    summary = campaign(marked=late(6))
    assert report.acceptance(summary)[COVERAGE]["durum"] == UNMET
    golden = report.render(summary)
    source, out = write_summary(tmp_path, summary), tmp_path / "rapor.md"
    assert report.main(["--summary", source]) == 0
    assert capsys.readouterr().out == golden
    assert report.main(["--summary", source, "--out", str(out)]) == 0
    assert out.read_bytes() == golden.encode("utf-8")
    assert "kabul" not in golden and "karar değildir" not in golden
    capsys.readouterr()
    assert report.main(["--summary", source, "--kabul", "--campaign", CAMPAIGN]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(golden)
    assert printed[len(golden) :] == report.render_acceptance(report.acceptance(summary))
    assert printed[len(golden) :].startswith("\n## Paper kabul ölçütleri (karar değildir)\n")


@pytest.mark.parametrize("flags", [["-I"], ["-I", "-S"]], ids=["yalitilmis", "site-paketsiz"])
def test_the_script_runs_isolated_with_only_the_standard_library(
    flags: list[str], report: ModuleType, tmp_path: Path
) -> None:
    """Belgelenen cagri `python3 -I`. `-S` ile site-packages de yoktur: `tlab` ya da
    ucuncu taraf bir paket ice aktarilsaydi betik burada duserdi."""
    summary = campaign(marked=late(6))
    source = write_summary(tmp_path, summary)
    plain, kabul = tmp_path / "plain.md", tmp_path / "kabul.md"
    for out, extra in ((plain, []), (kabul, ["--kabul", "--campaign", CAMPAIGN])):
        result = subprocess.run(  # noqa: S603 - sabit arguman listesi, kabuk yok
            [sys.executable, *flags, str(SCRIPT), "--summary", source, "--out", str(out), *extra],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            f"OK rapor: {out.name}\n",
            "",
        )
    golden = report.render(summary)
    assert plain.read_bytes() == golden.encode("utf-8")
    table = report.render_acceptance(report.acceptance(summary))
    assert kabul.read_bytes() == (golden + table).encode("utf-8")
