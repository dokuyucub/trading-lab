"""Sembol bazli kalite toplamasi - pilot ve baseline teshisi icin ORTAK (#17).

Girdi, `dataset.assess_quality`'nin urettigi seans x sembol olculeridir;
bu modul yeni bir kalite ALGORITMASI degildir, yalnizca sayar.

SAF: dosya, ag, saat, log yok. Kapsami CAGIRAN verir: hangi seanslarin
sayilacagini `sessions` belirler; bu modul baseline ile holdout'u
kendiliginden birlestirmez. Performans katmanlarini ice aktarmaz
(mimari test).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from tlab.core.calendar import TradingSession

REASON_CATEGORIES = {
    "seans ici bar yok": "seans_ici_bar_yok",
    "acilis penceresinde": "acilis_penceresi_eksik",
    "kapanistan onceki": "kapanis_penceresinde_bar_yok",
    "eksik dakika orani": "eksik_dakika_orani",
}
"""Gerekce metni -> sabit kategori. Ozetler gerekce METNINI tasimaz."""

OTHER_CATEGORY = "diger"
CATEGORIES = (*REASON_CATEGORIES.values(), OTHER_CATEGORY)


def reason_category(reason: str) -> str:
    for prefix, category in REASON_CATEGORIES.items():
        if reason.startswith(prefix):
            return category
    return OTHER_CATEGORY


@dataclass(frozen=True)
class SymbolQuality:
    """Bir sembolun, VERILEN seanslar uzerindeki kalite sayimlari.

    Iki farkli sey ayri tutulur:

      * `sessions_missing_fraction_above_limit` bir OLCUdur: seansin eksik
        dakika orani politika sinirini asiyor mu. Hic bar olmayan seansta
        oran 1'dir, yani bu sayima girer.
      * `reason_counts["eksik_dakika_orani"]` bir GEREKCE sayimidir:
        `assess_quality` bar olmayan seansa YALNIZCA "seans ici bar yok"
        gerekcesini verir, oran gerekcesini vermez.

    Ikisi ayni etiketle sunulmaz.
    """

    sessions_with_bars: int
    sessions_without_bars: int
    missing_minutes: int
    expected_minutes: int
    sessions_open_window_incomplete: int
    max_missing_open_window: int
    sessions_without_close_bar: int
    sessions_missing_fraction_above_limit: int
    ineligible_sessions: int
    reason_counts: Mapping[str, int]

    @property
    def missing_fraction(self) -> float | None:
        if not self.expected_minutes:
            return None
        return round(self.missing_minutes / self.expected_minutes, 6)


def summarize_symbols(
    per_session: Mapping[str, Mapping[str, Any]],
    sessions: Sequence[TradingSession],
    symbols: Sequence[str],
    *,
    max_missing_fraction: float,
) -> dict[str, SymbolQuality]:
    """Her sembol icin, YALNIZCA `sessions` uzerinden kalite sayimlari."""
    minute = timedelta(minutes=1)
    result: dict[str, SymbolQuality] = {}
    for symbol in symbols:
        with_bars = without_bars = open_incomplete = no_close = ineligible = 0
        missing = expected = max_open_missing = above_limit = 0
        reasons: Counter[str] = Counter(dict.fromkeys(CATEGORIES, 0))
        for item in sessions:
            metrics = per_session[item.day.isoformat()]["symbols"][symbol]
            session_expected = int((item.close - item.open) / minute)
            session_missing = int(metrics.get("missing_minutes", 0))
            expected += session_expected
            missing += session_missing
            if metrics["bars"]:
                with_bars += 1
            else:
                without_bars += 1
            open_missing = int(metrics.get("missing_open_window", 0))
            max_open_missing = max(max_open_missing, open_missing)
            open_incomplete += int(open_missing > 0)
            no_close += int(metrics.get("close_window_bars", 1) == 0)
            if session_expected and session_missing / session_expected > max_missing_fraction:
                above_limit += 1
            if metrics["reasons"]:
                ineligible += 1
                reasons.update(reason_category(reason) for reason in metrics["reasons"])
        result[symbol] = SymbolQuality(
            sessions_with_bars=with_bars,
            sessions_without_bars=without_bars,
            missing_minutes=missing,
            expected_minutes=expected,
            sessions_open_window_incomplete=open_incomplete,
            max_missing_open_window=max_open_missing,
            sessions_without_close_bar=no_close,
            sessions_missing_fraction_above_limit=above_limit,
            ineligible_sessions=ineligible,
            reason_counts=dict(reasons),
        )
    return result


def ineligible_symbol_counts(
    per_session: Mapping[str, Mapping[str, Any]], sessions: Sequence[TradingSession]
) -> list[int]:
    """Uygunsuz her seans icin, o seansta uygunsuz olan sembol SAYISI.

    Tarih tasimaz. Uzunlugu uygunsuz seans birlesimidir; toplami
    uygunsuz sembol-seans ciftleridir.
    """
    counts: list[int] = []
    for item in sessions:
        entry = per_session[item.day.isoformat()]
        if not entry["eligible"]:
            counts.append(sum(1 for metrics in entry["symbols"].values() if metrics["reasons"]))
    return counts
