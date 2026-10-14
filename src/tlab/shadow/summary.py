"""Golge gozlem ozeti: paydalar, unknown ve belirsizlik (tasarim §4).

Disari cikan TEK sey bu ozettir: sayimlar, baz puan farklari ve
bayraklar. Ham bar, mutlak fiyat ve hesap degeri yoktur.

Kurallar:

  * Planli her gun raporlanir: `tamam`, `eksik`, `baslamadi` (kanitli)
    ya da `bilinmiyor`. Hicbiri paydadan sessizce dusmez; ozeti olmayan
    gunun sembol-gunleri `unknown`dur.
  * Her olcu pay, payda ve `unknown`u ayri tasir. Unknown, sonucun iki
    yonune de sayilarak karara baglanir: unknown'larin hepsi basarisiz
    sayildiginda bile esik asiliyorsa `gecti`; hepsi basarili
    sayildiginda bile esik asilamiyorsa `kaldi`; arasi `belirsiz`.
  * Asgari destek (bilinen gozlem sayisi, gerekiyorsa farkli gun
    sayisi) saglanmazsa sonuc `belirsiz`tir.
  * Iki tarafta da niyet yoksa bu uyum DEGILDIR; ayri sayilir.
  * Kosullu olculerde (aralik farki: iki pencere tam) kosulun saglanip
    saglanmadigi BILINMEYEN sembol-gun paydada `unknown`dur. Yalnizca
    kosulun saglanmadigi GOZLENEN sembol-gun disarida kalir ve ayri
    sayacla gorunur (Codex 6158917217).

Esikler burada yalnizca ONERI olarak durur; kalibre edilmis kapi
degildir ve yurutme kararinda sabitlenir.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from tlab.shadow.core import (
    RANGE_COMPUTED,
    RANGE_IEX_INCOMPLETE,
    RANGE_SIP_INCOMPLETE,
    SIGNAL_MATCH,
    SIGNAL_NONE,
    SIGNAL_UNKNOWN,
    Comparison,
)

SUMMARY_SCHEMA = 1

DAY_COMPLETE = "tamam"
DAY_INCOMPLETE = "eksik"
DAY_NOT_STARTED = "baslamadi"
"""Hic gozlem baslamadigi KANITLI (kosu gecmisi okundu)."""
DAY_UNKNOWN = "bilinmiyor"
"""Kanit yetersiz: kosu gecmisi okunamadi ya da eksik."""
DAY_STATUSES = (DAY_COMPLETE, DAY_INCOMPLETE, DAY_NOT_STARTED, DAY_UNKNOWN)

PASSED = "gecti"
FAILED = "kaldi"
INCONCLUSIVE = "belirsiz"


@dataclass(frozen=True)
class Thresholds:
    """Esik ONERILERI (tasarim §4). Yurutme kararinda sabitlenir."""

    completeness: float = 0.95
    range_bps: float = 5.0
    range_share: float = 0.90
    range_min_support: int = 100
    intent_share: float = 0.80
    intent_min_support: int = 30
    intent_min_days: int = 10


@dataclass(frozen=True)
class SymbolDay:
    """Bir planli sembol-gunun sonucu.

    `comparison` None ise sembol-gun hic gozlenemedi (gun baslamadi ya
    da canli taraf hic veri alamadi). `sip_available` False ise SIP
    tarafi son sureye kadar tam gelmedi.
    """

    day: date
    symbol: str
    comparison: Comparison | None
    sip_available: bool


@dataclass(frozen=True)
class Day:
    day: date
    status: str
    reason: str | None = None
    """Eksik ya da baslamamis gunun SABIT sebebi (ornegin 'gec baslangic')."""

    def __post_init__(self) -> None:
        if self.status not in DAY_STATUSES:
            raise ValueError(f"bilinmeyen gun durumu: {self.status}")
        if (self.status == DAY_COMPLETE) != (self.reason is None):
            raise ValueError("yalnizca tamamlanmamis gunun sebebi olur")


@dataclass
class Rate:
    """Pay, payda ve unknown. Payda unknown'lari DA icerir."""

    numerator: int = 0
    denominator: int = 0
    unknown: int = 0
    days: set[date] = field(default_factory=set)
    """Bilinen gozlemlerin geldigi farkli gunler (destek icin)."""

    def add(self, day: date, *, success: bool | None) -> None:
        """`success` None ise gozlem bilinmiyor."""
        self.denominator += 1
        if success is None:
            self.unknown += 1
            return
        self.days.add(day)
        self.numerator += success

    @property
    def known(self) -> int:
        return self.denominator - self.unknown

    def verdict(self, share: float, *, min_support: int = 1, min_days: int = 0) -> str:
        if self.known < min_support or len(self.days) < min_days or self.denominator == 0:
            return INCONCLUSIVE
        if self.numerator / self.denominator >= share:
            return PASSED
        if (self.numerator + self.unknown) / self.denominator < share:
            return FAILED
        return INCONCLUSIVE

    def payload(self) -> dict[str, int]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unknown": self.unknown,
            "distinct_days": len(self.days),
        }


@dataclass
class _Tally:
    completeness: Rate = field(default_factory=Rate)
    range_: Rate = field(default_factory=Rate)
    intent: Rate = field(default_factory=Rate)
    no_intent: int = 0
    completed_later: int = 0
    iex_window_incomplete: int = 0
    sip_window_incomplete: int = 0


def summarize(
    planned_days: Sequence[date],
    symbols: Sequence[str],
    days: Iterable[Day],
    results: Iterable[SymbolDay],
    thresholds: Thresholds,
) -> dict[str, Any]:
    """Planli gunler ve sembollerden ozeti kurar.

    Planli olup sonucu verilmeyen her sembol-gun unknown sayilir;
    plan disi bir gun ya da sembol hatadir.
    """
    planned = set(planned_days)
    if len(planned) != len(planned_days):
        raise ValueError("planli gunler tekrar etmez")
    by_day = {day.day: day for day in days}
    if not set(by_day) <= planned:
        raise ValueError("plan disi gun raporlanamaz")
    observed: dict[tuple[date, str], SymbolDay] = {}
    for result in results:
        if result.day not in planned or result.symbol not in symbols:
            raise ValueError(f"plan disi sembol-gun: {result.day} {result.symbol}")
        key = (result.day, result.symbol)
        if key in observed:
            raise ValueError(f"sembol-gun iki kez raporlandi: {result.day} {result.symbol}")
        observed[key] = result

    total = _Tally()
    per_symbol = {symbol: _Tally() for symbol in symbols}
    range_values: list[dict[str, Any]] = []
    for day in sorted(planned):
        for symbol in symbols:
            found = observed.get((day, symbol))
            for tally in (total, per_symbol[symbol]):
                _count(tally, day, found, thresholds)
            if found is not None and found.comparison is not None:
                comparison = found.comparison
                if comparison.or_high_bps is not None and comparison.or_low_bps is not None:
                    range_values.append(
                        {
                            "day": day.isoformat(),
                            "symbol": symbol,
                            "high_bps": comparison.or_high_bps,
                            "low_bps": comparison.or_low_bps,
                        }
                    )

    # Durumu verilmeyen gun icin kanit yok: `baslamadi` DEGIL, `bilinmiyor`.
    statuses = [by_day.get(day, Day(day, DAY_UNKNOWN, "kanit yok")) for day in sorted(planned)]
    return {
        "summary_schema": SUMMARY_SCHEMA,
        "planned_days": len(planned),
        "symbols": list(symbols),
        "days": {status: sum(day.status == status for day in statuses) for status in DAY_STATUSES},
        "day_list": [
            {"day": day.day.isoformat(), "status": day.status, "reason": day.reason}
            for day in statuses
        ],
        "thresholds_are_proposals": True,
        "thresholds": {
            "completeness": thresholds.completeness,
            "range_bps": thresholds.range_bps,
            "range_share": thresholds.range_share,
            "range_min_support": thresholds.range_min_support,
            "intent_share": thresholds.intent_share,
            "intent_min_support": thresholds.intent_min_support,
            "intent_min_days": thresholds.intent_min_days,
        },
        "total": _payload(total, thresholds),
        # Sembol bazinda yalnizca sayimlar: toplam esikler tek sembolun
        # 20 gunune uygulanamaz, ama surekli basarisizligi gorunur kilar.
        "per_symbol": {
            symbol: _payload(tally, thresholds, verdicts=False)
            for symbol, tally in per_symbol.items()
        },
        "range_bps": range_values,
    }


def _count(tally: _Tally, day: date, result: SymbolDay | None, thresholds: Thresholds) -> None:
    comparison = result.comparison if result is not None else None

    # Baslangic tamligi (`t*`): paydasi butun planli sembol-gunler.
    if comparison is None or comparison.iex_present is None:
        tally.completeness.add(day, success=None)
    else:
        tally.completeness.add(day, success=comparison.iex_present == comparison.window_expected)
        tally.completed_later += comparison.iex_completed_later

    if comparison is None or result is None:
        # Hic gozlenemedi: kosulun saglanip saglanmadigi da bilinmiyor.
        tally.range_.add(day, success=None)
        tally.intent.add(day, success=None)
        return

    # Aralik farki: iki pencere de tam olan sembol-gunler. Kabul MUTLAK
    # degerle; isaretli fark yalnizca raporda kalir. Bilinen eksik pencere
    # kosul disidir ve ayri sayilir; bilinmeyen (RANGE_UNKNOWN, SIP yok,
    # gecersiz payda) paydada `unknown`dur.
    status = comparison.range_status
    if status == RANGE_IEX_INCOMPLETE:
        tally.iex_window_incomplete += 1
    elif status == RANGE_SIP_INCOMPLETE and result.sip_available:
        tally.sip_window_incomplete += 1
    elif status != RANGE_COMPUTED or not result.sip_available:
        tally.range_.add(day, success=None)
    else:
        high, low = comparison.or_high_bps, comparison.or_low_bps
        within = (
            high is not None
            and low is not None
            and abs(high) <= thresholds.range_bps
            and abs(low) <= thresholds.range_bps
        )
        tally.range_.add(day, success=within)

    # Niyet uyumu: en az bir tarafta niyet olan, iki tarafi bilinen sembol-gunler.
    if not result.sip_available or comparison.signal == SIGNAL_UNKNOWN:
        tally.intent.add(day, success=None)
    elif comparison.signal == SIGNAL_NONE:
        tally.no_intent += 1
    else:
        tally.intent.add(day, success=comparison.signal == SIGNAL_MATCH)


def _payload(tally: _Tally, thresholds: Thresholds, *, verdicts: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "iex_window_initial": tally.completeness.payload(),
        "iex_window_delayed": {
            "completed_later": tally.completed_later,
            "incomplete_at_t_star": tally.completeness.known - tally.completeness.numerator,
        },
        "range_within_bps": {
            **tally.range_.payload(),
            "iex_window_incomplete": tally.iex_window_incomplete,
            "sip_window_incomplete": tally.sip_window_incomplete,
        },
        "intent_agreement": {**tally.intent.payload(), "no_intent": tally.no_intent},
    }
    if verdicts:
        payload["iex_window_initial"]["verdict"] = tally.completeness.verdict(
            thresholds.completeness
        )
        payload["range_within_bps"]["verdict"] = tally.range_.verdict(
            thresholds.range_share, min_support=thresholds.range_min_support
        )
        payload["intent_agreement"]["verdict"] = tally.intent.verdict(
            thresholds.intent_share,
            min_support=thresholds.intent_min_support,
            min_days=thresholds.intent_min_days,
        )
    return payload
