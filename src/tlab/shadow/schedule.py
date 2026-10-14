"""Golge gozlemin kapisi: hangi gun, hangi an, kac kez (tasarim §5).

Kapi isinde Alpaca secret'i YOKTUR; takvimi okuyamaz. Acilisi duzenli
saatten (09:30 New York, saat dilimi kuraliyla) hesaplar. Resmi takvim
dogrulamasi gozlem isinin isidir.

Uc karar:

  * erken (pencereden once): hicbir sey yapma;
  * pencere icinde: o gun icin kayit yazmis baska kosu yoksa gozle;
  * gec (pencereden sonra): o gun icin kayit yazmis baska kosu yoksa
    gunu `eksik (gec baslangic)` diye yaz.

Boylece yaz/kis saatinin diger cron satiri ya erken kalir ya da gercek
kosudan sonra bos gecer; gercek kosu hic baslamamissa gec satir gunu
eksik diye yazar. Plan disindaki gun (son planli gunden sonrasi dahil)
hicbir sey yapmaz.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EXCHANGE_TZ = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
WINDOW_FIRST = timedelta(minutes=60)
"""Baslangic penceresi acilistan bu kadar once acilir."""
WINDOW_LAST = timedelta(minutes=1)
"""Pencerenin son ani: acilistan bu kadar once."""

GATE_SKIP = "atla"
GATE_OBSERVE = "gozle"
GATE_LATE = "gec-kayit"


@dataclass(frozen=True)
class PriorRun:
    """Ayni workflow'un baska bir kosusu (kapi kendini disarida birakir)."""

    session_day: date
    recorded: bool
    """Kayit isi (gozlem ya da gec kayit) atlanmadi: bitti ya da suruyor."""


@dataclass(frozen=True)
class GateDecision:
    action: str
    session_day: date
    reason: str


def session_day_of(now: datetime) -> date:
    """Anin borsa yerel takvim gunu."""
    if now.tzinfo is None:
        raise ValueError("kapi ani timezone icermeli")
    return now.astimezone(EXCHANGE_TZ).date()


def regular_open(day: date) -> datetime:
    """Gunun duzenli acilisi, UTC. Yaz/kis saati saat dilimi kuralindan gelir."""
    return datetime.combine(day, REGULAR_OPEN, tzinfo=EXCHANGE_TZ).astimezone(UTC)


def decide(now: datetime, planned: Sequence[date], prior: Iterable[PriorRun]) -> GateDecision:
    """Kapinin karari. `prior` bu kosuyu ICERMEZ."""
    day = session_day_of(now)
    if day not in planned:
        return GateDecision(GATE_SKIP, day, "plan disi gun")
    if any(run.session_day == day and run.recorded for run in prior):
        return GateDecision(GATE_SKIP, day, "gun zaten kaydedildi")
    opening = regular_open(day)
    if now < opening - WINDOW_FIRST:
        return GateDecision(GATE_SKIP, day, "erken")
    if now <= opening - WINDOW_LAST:
        return GateDecision(GATE_OBSERVE, day, "baslangic penceresi icinde")
    return GateDecision(GATE_LATE, day, "gec baslangic")
