"""Karar bagalami: stratejinin gordugu her sey.

Bir strateji yalnizca kendisine verilen Context'i gorur. Ag cagrisi
yapmaz, saat okumaz, broker'a sormaz. Bu kisitlama backtest ile
canli calismanin ayni kodu paylasabilmesinin on sarti: Context'i
kim doldurursa doldursun, strateji ayni karari verir.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from tlab.core.types import Account, Bar, Position, Quote


class SessionPhase(StrEnum):
    """Seansin hangi asamasinda oldugumuz."""

    PRE_OPEN = "pre_open"
    """Acilis oncesi. Islem yok."""

    OPENING_RANGE = "opening_range"
    """Acilis araligi olusuyor. Seviye henuz tamamlanmadi, islem yok."""

    REGULAR = "regular"
    """Normal seans. Islem acilabilir."""

    FLATTEN = "flatten"
    """Kapanis tamponu. Yeni islem yok, acik pozisyonlar kapatilir."""

    CLOSED = "closed"
    """Seans disi."""


@dataclass(frozen=True)
class SessionState:
    """Gun icindeki konumumuz.

    Takvim (tatil, yarim gun) bilgisi BURADA DEGIL: onu broker'in
    kendi saati biliyor ve runner ayrica kontrol ediyor. Bu yapi
    yalnizca "gun icinde neredeyiz" sorusunu cevaplar.
    """

    now: datetime
    session_open: datetime
    session_close: datetime
    flatten_at: datetime
    opening_range_end: datetime
    phase: SessionPhase

    @property
    def minutes_since_open(self) -> float:
        return (self.now - self.session_open).total_seconds() / 60

    @property
    def minutes_to_close(self) -> float:
        return (self.session_close - self.now).total_seconds() / 60

    @property
    def can_open_new_positions(self) -> bool:
        """Yeni pozisyon acmaya uygun tek asama normal seans."""
        return self.phase is SessionPhase.REGULAR

    @property
    def must_flatten(self) -> bool:
        """Acik pozisyonlarin kapatilmasi gereken an geldi mi."""
        return self.phase is SessionPhase.FLATTEN


def build_session_state(
    now: datetime,
    *,
    exchange_timezone: str,
    regular_open: str | tuple[int, int],
    regular_close: str | tuple[int, int],
    flatten_before_close_minutes: int,
    opening_range_minutes: int,
) -> SessionState:
    """Verilen ana gore seans durumunu hesaplar.

    Seans saatleri borsa saat diliminde tanimlanir ve UTC'ye orada
    cevrilir. Sabit bir saat farki VARSAYILMAZ: ABD ve Avrupa yaz
    saatine farkli tarihlerde gectigi icin fark yil icinde degisir ve
    sabit kabul etmek yilda iki kez bir saatlik kaymaya yol acar.
    """
    if now.tzinfo is None:
        msg = "build_session_state timezone bilgisi iceren bir an bekler"
        raise ValueError(msg)

    tz = ZoneInfo(exchange_timezone)
    local_now = now.astimezone(tz)

    open_h, open_m = _as_hm(regular_open)
    close_h, close_m = _as_hm(regular_close)

    session_open = local_now.replace(
        hour=open_h, minute=open_m, second=0, microsecond=0
    ).astimezone(UTC)
    session_close = local_now.replace(
        hour=close_h, minute=close_m, second=0, microsecond=0
    ).astimezone(UTC)

    flatten_at = session_close - timedelta(minutes=flatten_before_close_minutes)
    opening_range_end = session_open + timedelta(minutes=opening_range_minutes)

    now_utc = now.astimezone(UTC)
    if now_utc < session_open:
        phase = SessionPhase.PRE_OPEN
    elif now_utc >= session_close:
        phase = SessionPhase.CLOSED
    elif now_utc >= flatten_at:
        phase = SessionPhase.FLATTEN
    elif now_utc < opening_range_end:
        phase = SessionPhase.OPENING_RANGE
    else:
        phase = SessionPhase.REGULAR

    return SessionState(
        now=now_utc,
        session_open=session_open,
        session_close=session_close,
        flatten_at=flatten_at,
        opening_range_end=opening_range_end,
        phase=phase,
    )


def _as_hm(value: str | tuple[int, int]) -> tuple[int, int]:
    """'09:30' ya da (9, 30) girdisini saat/dakika ikilisine cevirir."""
    if isinstance(value, tuple):
        return value
    hour, _, minute = value.partition(":")
    return int(hour), int(minute)


@dataclass(frozen=True)
class Context:
    """Bir sembol icin tek bir karar aninin tam fotografi."""

    symbol: str
    session: SessionState
    bars: tuple[Bar, ...]
    """Yalnizca KAPANMIS barlar, zaman sirali.

    Olusmakta olan bar buraya asla girmez: kapanmamis bir barin
    kapanisini bilmek, gelecegi bilmektir ve backtest sonuclarini
    sessizce sisirir.
    """

    account: Account
    positions: Mapping[str, Position]
    quote: Quote | None = None

    @property
    def last_bar(self) -> Bar | None:
        return self.bars[-1] if self.bars else None

    @property
    def last_price(self) -> float | None:
        """Karar icin kullanilacak fiyat: son kapanmis barin kapanisi."""
        return self.bars[-1].close if self.bars else None

    @property
    def position(self) -> Position | None:
        """Bu sembolde acik pozisyon (varsa)."""
        return self.positions.get(self.symbol)

    @property
    def session_bars(self) -> tuple[Bar, ...]:
        """Yalnizca bugunku seansa ait barlar.

        VWAP ve acilis araligi gibi seans basinda sifirlanan
        hesaplarin onceki gunun verisine bulasmamasi icin.
        """
        start = self.session.session_open
        return tuple(bar for bar in self.bars if bar.ts >= start)
