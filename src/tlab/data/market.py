"""Piyasa verisi kaynagi.

`MarketData` protokolu, sistemin verinin NEREDEN geldigini bilmemesini
saglar. Canlida Alpaca'dan, backtest'te onbellekten ya da dosyadan
gelir; ustteki katmanlar farki gormez.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from tlab.core.types import Bar, Quote, Timeframe
from tlab.errors import DataError
from tlab.sdk_compat import sdk_field, sdk_float, sdk_int

# Kendi Timeframe tipimizden Alpaca gosterimine cevrim tablosu.
# Alpaca'nin tip sistemini ceviriyoruz ki cekirdek tipler saticiya
# bagimli olmasin.
#
# Degerler TimeFrameUnit'in ADI degil DEGERI olmali: enum'da ad
# "Minute", deger "Min" ve enum degerle kuruluyor. Bu fark, cevrimdisi
# testlerin goremedigi bir yerdeydi - test_market_contract.py artik
# her periyodu gercek SDK tipine cevirerek dogruluyor.
_TIMEFRAME_ARGS: dict[Timeframe, tuple[int, str]] = {
    Timeframe.M1: (1, "Min"),
    Timeframe.M5: (5, "Min"),
    Timeframe.M15: (15, "Min"),
    Timeframe.H1: (1, "Hour"),
    Timeframe.D1: (1, "Day"),
}


class MarketData(Protocol):
    """Bar ve kotasyon saglayan her kaynagin uydugu arayuz."""

    def bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Bar]:
        """[start, end] araligindaki barlari zaman sirali dondurur."""
        ...

    def latest_quote(self, symbol: str) -> Quote:
        """Sembolun en guncel alis/satis kotasyonu."""
        ...


class AlpacaMarketData:
    """Alpaca uzerinden gecmis bar ve anlik kotasyon saglar.

    `feed` alani kritik: ucretsiz planda sadece 'iex' erisilebilir ve bu
    toplam hacmin kucuk bir dilimidir. Hangi feed ile calisildigi
    journal'a yazilir, boylece feed degistiginde eski sonuclarla yeni
    sonuclarin neden ayristigi bilinir.
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        feed: str = "iex",
        *,
        base_url: str | None = None,
    ) -> None:
        """`base_url` icin bkz. AlpacaBroker: yerel sahte sunucuya yonlendirme."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.historical import StockHistoricalDataClient

        try:
            self._feed = DataFeed(feed)
        except ValueError as exc:
            msg = f"Desteklenmeyen veri feed'i: {feed!r}"
            raise DataError(msg) from exc

        self._client = StockHistoricalDataClient(
            api_key=api_key, secret_key=secret_key, url_override=base_url
        )
        self.feed_name = feed

    def bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Bar]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        if start.tzinfo is None or (end is not None and end.tzinfo is None):
            msg = "bars() timezone bilgisi iceren tarih bekler"
            raise DataError(msg)

        amount, unit = _TIMEFRAME_ARGS[timeframe]
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(amount, TimeFrameUnit(unit)),
            start=start,
            end=end,
            feed=self._feed,
        )
        try:
            response = self._client.get_stock_bars(request)
        except Exception as exc:
            msg = f"{symbol} icin bar verisi alinamadi: {exc}"
            raise DataError(msg) from exc

        payload = sdk_field(response, "data", {}) or {}
        bars = [self._to_bar(symbol, item) for item in payload.get(symbol, [])]
        bars.sort(key=lambda bar: bar.ts)
        return bars

    @staticmethod
    def _to_bar(symbol: str, item: Any) -> Bar:
        """SDK bar nesnesini cekirdek Bar tipine cevirir ve dogrular."""
        timestamp = sdk_field(item, "timestamp")
        if not isinstance(timestamp, datetime):
            msg = f"{symbol}: bar zaman damgasi okunamadi ({timestamp!r})"
            raise DataError(msg)
        vwap = sdk_field(item, "vwap")
        trade_count = sdk_field(item, "trade_count")
        try:
            return Bar(
                symbol=symbol,
                ts=timestamp,
                open=sdk_float(item, "open"),
                high=sdk_float(item, "high"),
                low=sdk_float(item, "low"),
                close=sdk_float(item, "close"),
                volume=sdk_float(item, "volume"),
                vwap=None if vwap is None else float(vwap),
                trade_count=None if trade_count is None else sdk_int(item, "trade_count"),
            )
        except ValueError as exc:
            # Bar dogrulamasi patlarsa veri bozuk demektir; sessizce
            # gecmek yerine hata veriyoruz ki bozuk veri stratejilere ulasmasin.
            msg = f"{symbol} @ {timestamp.isoformat()}: gecersiz bar verisi ({exc})"
            raise DataError(msg) from exc

    def latest_quote(self, symbol: str) -> Quote:
        from alpaca.data.requests import StockLatestQuoteRequest

        request = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=self._feed)
        try:
            response = self._client.get_stock_latest_quote(request)
        except Exception as exc:
            msg = f"{symbol} icin kotasyon alinamadi: {exc}"
            raise DataError(msg) from exc

        item = sdk_field(response, symbol)
        if item is None:
            msg = f"{symbol} icin kotasyon donmedi"
            raise DataError(msg)

        timestamp = sdk_field(item, "timestamp")
        if not isinstance(timestamp, datetime):
            msg = f"{symbol}: kotasyon zaman damgasi okunamadi"
            raise DataError(msg)

        try:
            return Quote(
                symbol=symbol,
                ts=timestamp,
                bid=sdk_float(item, "bid_price"),
                ask=sdk_float(item, "ask_price"),
                bid_size=sdk_float(item, "bid_size"),
                ask_size=sdk_float(item, "ask_size"),
            )
        except ValueError as exc:
            msg = f"{symbol}: gecersiz kotasyon ({exc})"
            raise DataError(msg) from exc
