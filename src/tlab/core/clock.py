"""Zaman soyutlamasi.

Stratejiler ve risk kurallari ASLA `datetime.now()` cagirmaz; saati her
zaman bir Clock'tan alir. Sebebi tek ve cok onemli: backtest'te zamani
biz kontrol ediyoruz. Kod dogrudan sistem saatine bakarsa, gecmis veri
uzerinde calisirken "su an"i yanlis bilir ve farkinda olmadan
gelecege bakar (lookahead bias). Ileriye bakma hatalarinin buyuk
cogunlugu bu tek satirdan cikar.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Sistemin "su an" kaynagi. Her zaman UTC dondurur."""

    def now(self) -> datetime:
        """Timezone bilgisi iceren (aware) UTC zaman damgasi."""
        ...


class LiveClock:
    """Gercek zamanli saat. Canli ve paper calismada kullanilir."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def __repr__(self) -> str:
        return "LiveClock()"


class SimClock:
    """Elle ilerletilen saat. Backtest ve testlerde kullanilir."""

    def __init__(self, start: datetime) -> None:
        self._now = _as_utc(start)

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        """Saati belirli bir ana tasi. Geriye gitmeye izin verilmez."""
        moment = _as_utc(moment)
        if moment < self._now:
            msg = f"SimClock geriye alinamaz: {self._now.isoformat()} -> {moment.isoformat()}"
            raise ValueError(msg)
        self._now = moment

    def __repr__(self) -> str:
        return f"SimClock({self._now.isoformat()})"


def _as_utc(moment: datetime) -> datetime:
    """Naive datetime'i reddet, aware olani UTC'ye cevir.

    Naive datetime sessizce yanlis sonuc uretir; bu yuzden hata veriyoruz.
    """
    if moment.tzinfo is None:
        msg = f"Timezone bilgisi olmayan datetime kabul edilmiyor: {moment!r}"
        raise ValueError(msg)
    return moment.astimezone(UTC)
