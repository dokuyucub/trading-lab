"""Acilis Araligi Kirilimi (Opening Range Breakout).

Seansin ilk dakikalarinda olusan yuksek/dusuk araligi, gunun ilk
fiyat kesfinin sinirlaridir. Bu araligin disina cikilmasi yon secimi
olarak yorumlanir; islem kirilim yonunde acilir, stop araligin karsi
tarafina konur.

Bu strateji ILK OLARAK secildi cunku KARLI oldugu biliniyor degil,
DOGRULANABILIR oldugu icin: kurallari tamamen net, girisi ve cikisi
tek bara bagli, bu yuzden backtest'i durust cikar. Gercekten para
kazanip kazanmadigi Faz 2'de olculecek; kazanmiyorsa degistirilecek.
Onemli olan altyapinin hazir olmasi.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from tlab.core.types import Bar, Intent, Side
from tlab.features.context import Context
from tlab.features.indicators import atr, opening_range, relative_volume, session_vwap
from tlab.strategies.base import StrategyParams


class ORBParams(StrategyParams):
    """ORB parametreleri.

    Varsayilanlar muhafazakar secildi: az ve secici islem, cok ve
    gevsek islemden iyidir. Bu degerler Faz 3'teki terfi kapisinin
    ogrenecegi asil yuzeydir.
    """

    opening_range_minutes: Annotated[int, Field(ge=1, le=120)] = 15
    """Acilis araliginin suresi."""

    entry_window_minutes: Annotated[int, Field(ge=1, le=390)] = 120
    """Acilistan sonra giris aranan sure. Gun ilerledikce kirilimlarin
    kalicilik ihtimali dustugu icin pencere sinirli tutulur."""

    atr_period: Annotated[int, Field(ge=2, le=100)] = 14
    rvol_lookback: Annotated[int, Field(ge=2, le=200)] = 20

    min_rvol: Annotated[float, Field(ge=0)] = 1.2
    """Asgari bagil hacim. Hacimsiz kirilimlar cogunlukla geri alinir."""

    target_r: Annotated[float, Field(gt=0, le=10)] = 1.5
    """Hedef, riskin kac kati olsun."""

    max_extension_atr: Annotated[float, Field(gt=0, le=10)] = 1.0
    """Fiyat, aralik sinirindan bu kadar ATR'den fazla uzaklastiysa
    giris yapilmaz. Kacan trenin arkasindan kosmak, stop'u hem uzatir
    hem de en kotu fiyattan girmek demektir."""

    min_stop_atr_frac: Annotated[float, Field(ge=0, le=5)] = 0.25
    """Stop mesafesi en az bu kadar ATR olmali."""

    min_stop_bps: Annotated[float, Field(ge=0)] = 10.0
    """Stop mesafesi en az fiyatin bu kadar baz puani olmali. Cok dar
    bir stop, piyasa gurultusuyle tetiklenir ve yuvarlandiktan sonra
    girisle cakisabilir."""

    allow_short: bool = True


class OpeningRangeBreakout:
    """Acilis araligi kirilimi stratejisi.

    Durum tutmaz: her cagri yalnizca verilen Context'e bakar. Ayni
    Context her zaman ayni karari uretir.
    """

    def __init__(self, params: ORBParams | None = None) -> None:
        self.params = params or ORBParams()

    @property
    def strategy_id(self) -> str:
        return "orb"

    @property
    def params_version(self) -> str:
        return f"orb-{self.params.fingerprint()}"

    def decide(self, ctx: Context) -> Intent | None:
        """Kirilim kosullari saglaniyorsa islem niyeti uretir.

        Her erken cikis bilincli bir 'islem yapma' karari. Sirayla:
        seans uygun mu, pozisyon zaten var mi, aralik olustu mu,
        gostergeler hesaplanabiliyor mu, hacim yeterli mi, kirilim
        gercek mi, fiyat cok uzaklasmis mi.
        """
        params = self.params

        # Yalnizca normal seansta ve giris penceresi icinde.
        if not ctx.session.can_open_new_positions:
            return None
        if not 0 <= ctx.session.minutes_since_open <= params.entry_window_minutes:
            return None

        # Sembol basina tek maruziyet: ayni fikre iki kez risk alinmaz.
        # Bekleyen emir de maruziyettir - dolmayi bekleyen bir limit
        # emri ortada pozisyon yokken de sermayeyi baglar.
        if ctx.has_open_exposure:
            return None

        last = ctx.last_bar
        if last is None:
            return None

        session_bars = list(ctx.session_bars)
        levels = opening_range(session_bars, ctx.session.session_open, params.opening_range_minutes)
        if levels is None:
            return None
        or_high, or_low = levels

        history = list(ctx.bars)
        atr_value = atr(history, params.atr_period)
        rvol = relative_volume(history, params.rvol_lookback)
        if atr_value is None or atr_value <= 0 or rvol is None:
            return None
        if rvol < params.min_rvol:
            return None

        price = last.close
        if price > or_high:
            side, boundary = Side.BUY, or_high
        elif price < or_low and params.allow_short:
            side, boundary = Side.SELL, or_low
        else:
            return None

        # Kirilim sinirdan cok uzaklastiysa giris yapma.
        if abs(price - boundary) > params.max_extension_atr * atr_value:
            return None

        stop_loss = self._stop_for(side, price, or_high, or_low, atr_value)
        risk_per_share = abs(price - stop_loss)
        if risk_per_share <= 0:
            return None

        take_profit = (
            price + params.target_r * risk_per_share
            if side is Side.BUY
            else price - params.target_r * risk_per_share
        )

        return Intent(
            strategy_id=self.strategy_id,
            params_version=self.params_version,
            symbol=ctx.symbol,
            side=side,
            reference_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=self._confidence(rvol),
            reason=(
                f"acilis araligi kirilimi ({side.value}): fiyat {price:.2f}, "
                f"aralik {or_low:.2f}-{or_high:.2f}, rvol {rvol:.2f}"
            ),
            features=self._features(ctx, last, or_high, or_low, atr_value, rvol, risk_per_share),
        )

    # ------------------------------------------------------------------
    # Yardimcilar
    # ------------------------------------------------------------------

    def _stop_for(
        self, side: Side, price: float, or_high: float, or_low: float, atr_value: float
    ) -> float:
        """Stop seviyesi: araligin karsi tarafi, asgari mesafe garantili.

        Yapisal stop (araligin karsi ucu) tercih edilir cunku oraya
        donulmesi kirilimin gecersiz oldugu anlamina gelir. Ancak dar
        bir aralikta bu stop fiyata cok yakin dusebilir; o durumda
        gurultuye ve yuvarlamaya dayanikli bir asgari mesafe uygulanir.
        """
        params = self.params
        minimum = max(
            params.min_stop_atr_frac * atr_value,
            price * params.min_stop_bps / 10_000,
        )
        if side is Side.BUY:
            return min(or_low, price - minimum)
        return max(or_high, price + minimum)

    def _confidence(self, rvol: float) -> float:
        """Hacim arttikca guven artar, 0,4 ile 1,0 arasinda kalir.

        Guven skoru emir boyutunu BELIRLEMEZ - boyutlandirma risk
        kapisinin isi. Burada uretilmesinin sebebi journal'a yazilip
        ileride 'yuksek guvenli islemler gercekten daha mi iyi' diye
        olculebilmesi.
        """
        return max(0.4, min(1.0, 0.4 + 0.3 * (rvol - self.params.min_rvol)))

    def _features(
        self,
        ctx: Context,
        last: Bar,
        or_high: float,
        or_low: float,
        atr_value: float,
        rvol: float,
        risk_per_share: float,
    ) -> dict[str, float]:
        """Karar anindaki ozellik fotografi.

        Ogrenme katmaninin tek yakiti bu sozluk. Karar icin
        KULLANILMAYAN olculer de bilincli olarak ekleniyor (VWAP
        uzakligi, spread gibi): ileride 'bu olcu isimize yarar miydi'
        sorusu ancak veri toplanmissa cevaplanabilir.
        """
        price = last.close

        features: dict[str, float] = {
            "price": price,
            "or_high": or_high,
            "or_low": or_low,
            "or_range": or_high - or_low,
            "or_range_pct": (or_high - or_low) / price * 100 if price else 0.0,
            "atr": atr_value,
            "rvol": rvol,
            "risk_per_share": risk_per_share,
            "risk_bps": risk_per_share / price * 10_000 if price else 0.0,
            "minutes_since_open": ctx.session.minutes_since_open,
            "minutes_to_close": ctx.session.minutes_to_close,
            "bar_volume": last.volume,
            "bar_range": last.range,
        }

        vwap = session_vwap(list(ctx.session_bars))
        if vwap is not None and price:
            features["vwap"] = vwap
            features["dist_to_vwap_bps"] = (price - vwap) / price * 10_000

        if ctx.quote is not None:
            features["spread_bps"] = ctx.quote.spread_bps

        return features
