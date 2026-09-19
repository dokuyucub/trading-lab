"""Broker arayuzu.

Stratejiler ve risk kapisi bu protokole bakar, Alpaca'ya degil.
Backtest'te ayni protokolu uygulayan bir simulasyon brokeri devreye
girer ve ustteki hicbir kod degismez. "Tek beyin, uc kosum takimi"
ilkesinin execution tarafindaki karsiligi budur.

Faz 0 kapsami yalnizca OKUMA islemleridir. Emir gonderimi risk kapisi
tamamlandiktan sonra, Faz 1'de eklenecek: koruma katmani hazir
olmadan sisteme emir yetkisi vermiyoruz.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from tlab.core.types import Account, Position
from tlab.errors import BrokerError

__all__ = ["Broker", "BrokerError", "MarketClock"]


class MarketClock(Protocol):
    """Borsanin acik olup olmadigi ve sonraki acilis/kapanis."""

    @property
    def is_open(self) -> bool: ...

    @property
    def next_open(self) -> datetime: ...

    @property
    def next_close(self) -> datetime: ...


class Broker(Protocol):
    """Hesap ve pozisyon bilgisi saglayan broker."""

    def get_account(self) -> Account:
        """Hesabin anlik durumu."""
        ...

    def get_positions(self) -> list[Position]:
        """Acik pozisyonlar. Broker her zaman tek dogru kaynaktir.

        Sistem yeniden basladiginda kendi hafizasina degil bu listeye
        gore hizalanir; boylece cokme sonrasi hayali pozisyon olusmaz.
        """
        ...

    def get_market_clock(self) -> MarketClock:
        """Borsa saati. Tatil takvimini broker biliyor, biz tahmin etmiyoruz."""
        ...
