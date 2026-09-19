"""Broker arayuzu.

Stratejiler ve risk kapisi bu protokole bakar, Alpaca'ya degil.
Backtest'te ayni protokolu uygulayan bir simulasyon brokeri devreye
girer ve ustteki hicbir kod degismez. "Tek beyin, uc kosum takimi"
ilkesinin execution tarafindaki karsiligi budur.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from tlab.core.types import Account, BracketOrder, Fill, OrderRef, Position
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
    """Hesap okuma ve emir gonderme yetenekleri."""

    # -- okuma ---------------------------------------------------------

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

    def list_open_orders(self) -> list[OrderRef]:
        """Bekleyen emirler."""
        ...

    def list_fills(self, since: datetime) -> list[Fill]:
        """Verilen andan bu yana gerceklesmis emirler (bacaklar dahil).

        Mutabakatin girdisi. Ne gonderdigimiz degil, ne gerceklestigi
        onemli: emir dolmamis, kismi dolmus ya da planlanandan farkli
        fiyattan dolmus olabilir.
        """
        ...

    # -- yazma ---------------------------------------------------------

    def submit_bracket(self, order: BracketOrder) -> OrderRef:
        """Giris, stop ve hedefi TEK PAKET halinde gonderir.

        Bracket kullanmanin sebebi dogrudan gozetimsiz calisma
        gereksinimi: koruma emirleri girisle birlikte borsaya
        yerlesir. Bot cokerse, sunucu kapanirsa ya da ag giderse bile
        stop ve hedef borsada durmaya devam eder. Girisi gonderip
        korumayi sonra eklemek, aradaki saniyelerde pozisyonu
        savunmasiz birakirdi.
        """
        ...

    def close_position(self, symbol: str) -> OrderRef | None:
        """Pozisyonu piyasa emriyle kapatir. Pozisyon yoksa None."""
        ...

    def cancel_open_orders(self, symbol: str | None = None) -> int:
        """Bekleyen emirleri iptal eder, iptal edilen sayiyi dondurur."""
        ...
