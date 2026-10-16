"""Golge toplam ozetinin sade Turkce raporu (#17, ON RAPOR 6181599904).

Girdi: toplam isinin yukledigi `shadow-total.json` (tasarim §6, `summary_schema`
1). Cikti: kullanicinin okuyabilecegi Markdown. Yorum eklemez; esiklerin
ONERI oldugunu soyler; fiyat ya da ham veri tasimaz (toplamda zaten yoktur).

`scripts/` altinda ve yalnizca standart kutuphane: uygulama parmak izinin
disinda kalir, kampanya dondurmasi sirasinda degisebilir; ag yok, tetik yok.
Beklenmeyen sema ya da alan sabit bir hata ile durdurur; sessiz tamamlama yok.

Kullanim: python3 -I scripts/shadow_report.py --summary shadow-total.json [--out rapor.md]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

SUMMARY_SCHEMA = 1
HEX64 = re.compile(r"[0-9a-f]{64}")
DAY_STATUSES = {
    "tamam": "tamam",
    "eksik": "eksik",
    "baslamadi": "başlamadı",
    "bilinmiyor": "bilinmiyor",
}
VERDICTS = {"gecti": "GEÇTİ", "kaldi": "KALDI", "belirsiz": "BELİRSİZ"}
RATE_KEYS = ("numerator", "denominator", "unknown", "distinct_days")
THRESHOLD_KEYS = (
    "completeness",
    "range_bps",
    "range_share",
    "range_min_support",
    "intent_share",
    "intent_min_support",
    "intent_min_days",
)
TOP_KEYS = frozenset(
    {
        "summary_schema",
        "planned_days",
        "symbols",
        "days",
        "day_list",
        "thresholds_are_proposals",
        "thresholds",
        "total",
        "per_symbol",
        "range_bps",
        "campaign",
        "implementation",
    }
)
MEASURES = (
    ("iex_window_initial", "Ücretsiz canlı veri açılış penceresini tam veriyor mu?"),
    ("range_within_bps", "Açılış aralığı SIP referans verisiyle aynı çıkıyor mu?"),
    ("intent_agreement", "Strateji iki veriyle aynı kararı veriyor mu?"),
)
MEASURE_EXTRAS = {
    "iex_window_initial": (),
    "range_within_bps": ("iex_window_incomplete", "sip_window_incomplete"),
    "intent_agreement": ("no_intent",),
}


class ReportError(ValueError):
    """Toplam ozeti beklenen bicimde degil. Metin SABIT: deger tasimaz."""


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_iso_day(value: Any) -> bool:
    """Tam `YYYY-AA-GG` bicimli gercek bir tarih."""
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _rate(payload: Any, name: str, *, verdict: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ReportError(f"{name} beklenen bicimde degil")
    expected = set(RATE_KEYS) | set(MEASURE_EXTRAS[name]) | ({"verdict"} if verdict else set())
    if set(payload) != expected or not all(
        _is_count(payload[key]) for key in RATE_KEYS + MEASURE_EXTRAS[name]
    ):
        raise ReportError(f"{name} beklenen bicimde degil")
    if payload["numerator"] + payload["unknown"] > payload["denominator"]:
        raise ReportError(f"{name} sayaclari tutarsiz")
    if verdict and not (isinstance(payload["verdict"], str) and payload["verdict"] in VERDICTS):
        raise ReportError(f"{name} sonucu tanimsiz")
    return payload


def _delayed(payload: Any) -> dict[str, int]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"completed_later", "incomplete_at_t_star"}
        or not all(_is_count(value) for value in payload.values())
    ):
        raise ReportError("iex_window_delayed beklenen bicimde degil")
    return payload


def _measures(payload: Any, *, verdict: bool) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "iex_window_initial",
        "iex_window_delayed",
        "range_within_bps",
        "intent_agreement",
    }:
        raise ReportError("olcu kumesi beklenen bicimde degil")
    return {
        "iex_window_initial": _rate(
            payload["iex_window_initial"], "iex_window_initial", verdict=verdict
        ),
        "iex_window_delayed": _delayed(payload["iex_window_delayed"]),
        "range_within_bps": _rate(payload["range_within_bps"], "range_within_bps", verdict=verdict),
        "intent_agreement": _rate(payload["intent_agreement"], "intent_agreement", verdict=verdict),
    }


def validate(summary: Any) -> dict[str, Any]:
    """Toplam ozetini sema ve tur bakimindan denetler; sapma `ReportError`."""
    if not isinstance(summary, dict) or set(summary) != TOP_KEYS:
        raise ReportError("toplam ozetinin alanlari beklenen kumede degil")
    if not _is_count(summary["summary_schema"]) or summary["summary_schema"] != SUMMARY_SCHEMA:
        raise ReportError("toplam ozeti semasi tanimsiz")
    symbols = summary["symbols"]
    if (
        not isinstance(symbols, list)
        or not symbols
        or not all(isinstance(item, str) and item for item in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        raise ReportError("evren beklenen bicimde degil")
    if not _is_count(summary["planned_days"]) or summary["planned_days"] == 0:
        raise ReportError("planli gun sayisi beklenen bicimde degil")
    days = summary["days"]
    if (
        not isinstance(days, dict)
        or set(days) != set(DAY_STATUSES)
        or not all(_is_count(value) for value in days.values())
    ):
        raise ReportError("gun sayimlari beklenen bicimde degil")
    day_list = summary["day_list"]
    if not isinstance(day_list, list) or len(day_list) != summary["planned_days"]:
        raise ReportError("gun listesi beklenen bicimde degil")
    for item in day_list:
        if (
            not isinstance(item, dict)
            or set(item) != {"day", "status", "reason"}
            or not _is_iso_day(item["day"])
            or not (isinstance(item["status"], str) and item["status"] in DAY_STATUSES)
            or not (item["reason"] is None or isinstance(item["reason"], str))
            or (item["status"] == "tamam") != (item["reason"] is None)
        ):
            raise ReportError("gun listesi beklenen bicimde degil")
    listed = [item["day"] for item in day_list]
    if len(set(listed)) != len(listed):
        raise ReportError("gun listesi beklenen bicimde degil")
    counted = {status: sum(1 for item in day_list if item["status"] == status) for status in days}
    if counted != days:
        raise ReportError("gun listesi ile gun sayimlari uyusmuyor")
    if summary["thresholds_are_proposals"] is not True:
        raise ReportError("esikler oneri olarak isaretli degil")
    thresholds = summary["thresholds"]
    if (
        not isinstance(thresholds, dict)
        or set(thresholds) != set(THRESHOLD_KEYS)
        or not all(_is_number(value) for value in thresholds.values())
    ):
        raise ReportError("esikler beklenen bicimde degil")
    total = _measures(summary["total"], verdict=True)
    per_symbol = summary["per_symbol"]
    if not isinstance(per_symbol, dict) or set(per_symbol) != set(symbols):
        raise ReportError("sembol ozetleri beklenen bicimde degil")
    per_symbol = {symbol: _measures(per_symbol[symbol], verdict=False) for symbol in symbols}
    if not isinstance(summary["range_bps"], list):
        raise ReportError("aralik farki listesi beklenen bicimde degil")
    for key in ("campaign", "implementation"):
        if not (isinstance(summary[key], str) and HEX64.fullmatch(summary[key])):
            raise ReportError(f"{key} kimligi beklenen bicimde degil")
    return {**summary, "total": total, "per_symbol": per_symbol}


def _fraction(rate: Mapping[str, Any]) -> str:
    known = rate["denominator"] - rate["unknown"]
    share = f"%{100 * rate['numerator'] / rate['denominator']:.1f}" if rate["denominator"] else "—"
    return (
        f"{rate['numerator']} / {rate['denominator']} ({share}); "
        f"bilinen {known}, bilinmeyen {rate['unknown']}, farklı gün {rate['distinct_days']}"
    )


def _threshold_text(name: str, thresholds: Mapping[str, Any]) -> str:
    if name == "iex_window_initial":
        return f"pay ≥ %{100 * thresholds['completeness']:.0f} (bilinmeyenler paydada)"
    if name == "range_within_bps":
        share = 100 * thresholds["range_share"]
        return (
            f"|fark| ≤ {thresholds['range_bps']:g} bps olan pay ≥ %{share:.0f}, "
            f"en az {thresholds['range_min_support']:g} bilinen gözlem"
        )
    share = 100 * thresholds["intent_share"]
    return (
        f"uyum ≥ %{share:.0f}, en az {thresholds['intent_min_support']:g} bilinen gözlem "
        f"ve {thresholds['intent_min_days']:g} farklı gün"
    )


def render(summary: Mapping[str, Any]) -> str:
    """Dogrulanmis toplam ozetinden Markdown rapor."""
    data = validate(summary)
    total, thresholds = data["total"], data["thresholds"]
    lines = [
        "# Gölge gözlem sonucu",
        "",
        f"- Planlı gün: {data['planned_days']}; sembol: {len(data['symbols'])} "
        f"({', '.join(data['symbols'])}); sembol-gün paydası: "
        f"{data['planned_days'] * len(data['symbols'])}.",
        f"- Kampanya kimliği: `{data['campaign']}`",
        f"- Uygulama parmak izi: `{data['implementation']}`",
        "",
        "Bu rapor yorum eklemez. Eşikler tasarımdaki ÖNERİLERDİR; sonuç, bilinmeyen "
        "gözlemler iki yöne de sayılarak verilir: hepsi başarısız sayılsa bile eşik "
        "aşılıyorsa GEÇTİ, hepsi başarılı sayılsa bile aşılamıyorsa KALDI, arası "
        "BELİRSİZ. GEÇTİ ya da KALDI demeden önce yeterli destek aranır: açılış "
        f"aralığı için en az {thresholds['range_min_support']:g} bilinen gözlem, "
        f"strateji kararı için en az {thresholds['intent_min_support']:g} bilinen "
        f"gözlem ve {thresholds['intent_min_days']:g} farklı gün; destek yoksa "
        "yüzde ne olursa olsun sonuç BELİRSİZ'dir. SIP hakkında kanıt yoksa gözlem "
        "bilinmeyen sayılır; SIP penceresinin eksik olduğu kanıtlanan sembol-günler "
        "aralık ölçüsünün dışında, ek sayımlarda ayrı tutulur. Fiyat ya da ham veri "
        "içermez.",
        "",
        "## Üç soru",
        "",
        "| Soru | Sonuç | Sayılar | Eşik (öneri) |",
        "|---|---|---|---|",
    ]
    for name, question in MEASURES:
        rate = total[name]
        lines.append(
            f"| {question} | **{VERDICTS[rate['verdict']]}** | {_fraction(rate)} | "
            f"{_threshold_text(name, thresholds)} |"
        )
    delayed = total["iex_window_delayed"]
    rng, intent = total["range_within_bps"], total["intent_agreement"]
    lines += [
        "",
        "Ek sayımlar:",
        "",
        f"- Açılış penceresi ilk bakışta eksik olup giriş penceresi içinde sonradan "
        f"tamamlanan sembol-gün: {delayed['completed_later']} "
        f"(ilk bakışta eksik: {delayed['incomplete_at_t_star']}).",
        f"- Aralık farkı ölçülemeyen sembol-gün: canlı pencere hiç tamamlanmadı "
        f"{rng['iex_window_incomplete']}, SIP referans penceresi eksikti "
        f"{rng['sip_window_incomplete']} (ölçü dışı, ayrı sayılır).",
        f"- İki tarafta da işlem niyeti olmayan sembol-gün: {intent['no_intent']} "
        "(uyum sayılmaz, ayrı sayılır).",
        "",
        "## Günler",
        "",
        "| Durum | Gün sayısı |",
        "|---|---|",
    ]
    lines += [f"| {label} | {data['days'][key]} |" for key, label in DAY_STATUSES.items()]
    lines += ["", "| Gün | Durum | Sebep |", "|---|---|---|"]
    lines += [
        f"| {item['day']} | {DAY_STATUSES[item['status']]} | {item['reason'] or '—'} |"
        for item in data["day_list"]
    ]
    lines += [
        "",
        "## Semboller",
        "",
        "Sembol başına yalnız sayımlar; toplam eşikler tek sembole uygulanmaz.",
        "",
        "| Sembol | Pencere tam | Aralık uyumlu | Niyet uyumlu |",
        "|---|---|---|---|",
    ]
    for symbol in data["symbols"]:
        measures = data["per_symbol"][symbol]
        lines.append(
            f"| {symbol} | {_short(measures['iex_window_initial'])} | "
            f"{_short(measures['range_within_bps'])} | {_short(measures['intent_agreement'])} |"
        )
    lines += [
        "",
        "## Eşikler (öneri)",
        "",
        *[f"- {key}: {thresholds[key]:g}" for key in THRESHOLD_KEYS],
        "",
    ]
    return "\n".join(lines)


def _short(rate: Mapping[str, Any]) -> str:
    return f"{rate['numerator']}/{rate['denominator']} (bilinmeyen {rate['unknown']})"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -I scripts/shadow_report.py")
    parser.add_argument("--summary", type=Path, required=True, help="shadow-total.json")
    parser.add_argument(
        "--out", type=Path, help="Markdown ciktisi (var olan dosya uzerine yazilmaz)"
    )
    args = parser.parse_args(argv)
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        print(f"HATA: toplam ozeti okunamadi ({type(exc).__name__})", file=sys.stderr)
        return 1
    try:
        report = render(summary)
    except ReportError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    if args.out is None:
        sys.stdout.write(report)
        return 0
    try:
        with args.out.open("x", encoding="utf-8") as handle:
            handle.write(report)
    except OSError as exc:
        print(f"HATA: rapor yazilamadi ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(f"OK rapor: {args.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
