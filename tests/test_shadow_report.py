"""Golge toplam raporu (`scripts/shadow_report.py`): gercek `summarize` ciktisindan
sade Turkce Markdown; sema ve alan sapmalari sabit hatayla durur; fiyat yok."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from datetime import date
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
    days: list[Day], results: list[SymbolDay], thresholds: Thresholds = EASY
) -> dict[str, Any]:
    summary = summarize(PLANNED, SYMBOLS, days, results, thresholds)
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
    assert report.main(["--summary", str(tmp_path / "yok.json")]) == 1
    assert "HATA: toplam ozeti okunamadi (FileNotFoundError)" in capsys.readouterr().err
