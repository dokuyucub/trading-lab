"""Onbellekten beslenen piyasa verisi.

Backtest'in veri kaynagi. MarketData protokolunu uyguladigi icin
strateji ve dongu, verinin Alpaca'dan mi yoksa diskten mi geldigini
bilmez.

Iki onemli ozellik:
  * Bar dilimleme ikili arama ile yapiliyor. Backtest yuz binlerce
    kez veri istiyor; her seferinde tum listeyi taramak motoru
    kullanilamaz hale getirir.
  * Kotasyon SENTETIK uretiliyor (asagida ayrintili not var).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime

from tlab.core.clock import Clock
from tlab.core.types import Bar, Quote, Timeframe
from tlab.data.cache import BarCache
from tlab.errors import DataError


class CachedMarketData:
    """Parquet onbellegindeki barlari sunar, kotasyonu turetir."""

    def __init__(
        self,
        cache: BarCache,
        *,
        timeframe: Timeframe = Timeframe.M1,
        synthetic_spread_bps: float = 2.0,
        clock: Clock | None = None,
    ) -> None:
        self._cache = cache
        self._timeframe = timeframe
        self.synthetic_spread_bps = synthetic_spread_bps
        self._clock = clock
        self._bars: dict[str, list[Bar]] = {}
        self._stamps: dict[str, list[datetime]] = {}

    def bind_clock(self, clock: Clock) -> None:
        """Kotasyonlarin hangi ana gore uretilecegini belirler.

        Backtest motoru bunu kendi simulasyon saatiyle cagirir.
        Baglanmazsa kotasyon veri setinin SONUNDAN gelir ve
        strateji Ocak ayindaki karari Mart ayindaki fiyatla verir.
        """
        self._clock = clock

    def preload(self, symbols: list[str]) -> dict[str, int]:
        """Sembolleri bellege alir ve bar sayilarini dondurur."""
        loaded: dict[str, int] = {}
        for symbol in symbols:
            bars = self._cache.load(symbol, self._timeframe)
            self._bars[symbol] = bars
            self._stamps[symbol] = [bar.ts for bar in bars]
            loaded[symbol] = len(bars)
        return loaded

    def _series(self, symbol: str) -> tuple[list[Bar], list[datetime]]:
        if symbol not in self._bars:
            self.preload([symbol])
        return self._bars[symbol], self._stamps[symbol]

    def bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Bar]:
        if timeframe is not self._timeframe:
            msg = f"Onbellek {self._timeframe.value} icin hazirlandi, {timeframe.value} istendi"
            raise DataError(msg)

        series, stamps = self._series(symbol)
        if not series:
            return []

        left = bisect_left(stamps, start)
        right = len(series) if end is None else bisect_right(stamps, end)
        return series[left:right]

    def latest_quote(self, symbol: str) -> Quote:
        """O ANKI sentetik kotasyon.

        Saat verilmisse kotasyon o ana gore uretilir. Bu ayrinti
        atlanirsa backtest dogrudan gelecege bakar: "son" kotasyon,
        veri setinin en sonundaki fiyat olurdu ve strateji Ocak
        ayindaki bir karari Mart ayindaki fiyatla verirdi.

        Gecmis bar verisi kotasyon icermedigi icin spread SENTETIK
        uretiliyor. Bu, modelin bilinen en buyuk iyimserligi:
        gercekte spread gun icinde degisir, acilista ve haber aninda
        acilir. Yani backtest bu kalemde gercekten daha IYIMSER
        davraniyor - ama bu, sonucun gercegin ust siniri oldugu
        anlamina gelmez, cunku ters yonde calisan modellenmemis
        etkiler de var. Yalnizca su soylenebilir: "ufak marj"
        kovalayan stratejilerde bu varsayim sonucu oldugundan iyi
        gosterme egilimindedir.
        """
        if self._clock is not None:
            return self.quote_at(symbol, self._clock.now())

        series, _ = self._series(symbol)
        if not series:
            msg = f"{symbol} icin onbellekte veri yok"
            raise DataError(msg)
        return self._quote_from(series[-1])

    def quote_at(self, symbol: str, moment: datetime) -> Quote:
        """Belirli bir andaki sentetik kotasyon."""
        series, stamps = self._series(symbol)
        index = bisect_right(stamps, moment) - 1
        if index < 0:
            msg = f"{symbol} icin {moment.isoformat()} oncesinde veri yok"
            raise DataError(msg)
        return self._quote_from(series[index])

    def _quote_from(self, bar: Bar) -> Quote:
        half = bar.close * self.synthetic_spread_bps / 10_000 / 2
        return Quote(
            symbol=bar.symbol,
            ts=bar.ts,
            bid=bar.close - half,
            ask=bar.close + half,
            bid_size=100,
            ask_size=100,
        )
