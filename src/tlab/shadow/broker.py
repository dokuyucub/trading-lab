"""Golge gozlemin broker'i: hesap ve emir uclarina HIC gitmez.

Tasarim: docs/designs/shadow-observation.md §3. Hesap ya da emir
adaptorune delegasyon YOKTUR:

  * okuma: sentetik hesap; pozisyon, bekleyen emir ve dolum bos liste
    (mutabakat yolu dahil);
  * borsa saati: resmi takvimden turetilir;
  * yazma: hata (fail-fast). Dongu `--dry-run` ile calisir ve yazma
    yoluna zaten girmez; bu, ikinci emniyettir.

Bu sinif hicbir ag istemcisi tutmaz. Yasak uclara istek gitmedigini
yerel HTTP sozlesme testi ayrica gosterir.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tlab.core.calendar import TradingSession
from tlab.core.clock import Clock
from tlab.core.types import Account, BracketOrder, Fill, OrderRef, Position
from tlab.errors import BrokerError
from tlab.shadow.core import SYNTHETIC_ACCOUNT

REFUSAL = "golge gozlem emir gondermez"


@dataclass(frozen=True)
class CalendarClock:
    """Takvimden turetilmis borsa saati (Alpaca saatiyle ayni anlam)."""

    is_open: bool
    next_open: datetime
    next_close: datetime


class ShadowBroker:
    """Emirsiz, hesapsiz broker. Takvim cagirandan gelir, saat disaridan verilir."""

    def __init__(self, sessions: Sequence[TradingSession], clock: Clock) -> None:
        if not sessions:
            raise BrokerError("golge broker takvimsiz kurulamaz")
        self.sessions = tuple(sorted(sessions, key=lambda session: session.open))
        self.clock = clock

    # -- okuma: sentetik --------------------------------------------------

    def get_account(self) -> Account:
        return SYNTHETIC_ACCOUNT

    def get_positions(self) -> list[Position]:
        return []

    def list_open_orders(self) -> list[OrderRef]:
        return []

    def list_fills(self, since: datetime) -> list[Fill]:  # noqa: ARG002 - protokol imzasi
        return []

    def get_market_clock(self) -> CalendarClock:
        """Alpaca saatiyle ayni anlam: acikken `next_open` sonraki seansin acilisidir.

        Takvim ani kapsamiyorsa tahmin edilmez; hata verilir.
        """
        now = self.clock.now()
        upcoming = [session for session in self.sessions if session.close > now]
        if not upcoming:
            raise BrokerError(f"takvim bu ani kapsamiyor: {now.isoformat()}")
        current = upcoming[0]
        if current.contains(now):
            if len(upcoming) < 2:
                raise BrokerError(f"takvimde sonraki seans yok: {now.isoformat()}")
            return CalendarClock(is_open=True, next_open=upcoming[1].open, next_close=current.close)
        return CalendarClock(is_open=False, next_open=current.open, next_close=current.close)

    # -- yazma: fail-fast -------------------------------------------------

    def submit_bracket(self, order: BracketOrder) -> OrderRef:  # noqa: ARG002
        raise BrokerError(REFUSAL)

    def close_position(self, symbol: str) -> OrderRef | None:  # noqa: ARG002
        raise BrokerError(REFUSAL)

    def cancel_open_orders(self, symbol: str | None = None) -> int:  # noqa: ARG002
        raise BrokerError(REFUSAL)
