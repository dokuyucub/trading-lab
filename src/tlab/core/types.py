"""Sistemin cekirdek alan tipleri.

Tasarim kurallari:
  * Tum tipler frozen (degismez). Bir Intent uretildikten sonra kimse
    icerigini degistiremez; risk kapisi begenmezse veto eder, duzeltmez.
  * Dogrulama tipin kendi icinde. Ters bracket (stop'u hedefin ustunde)
    gibi hatalar nesne olusurken yakalanir, brokera gitmeden once.
  * Hicbir dis bagimlilik yok - bu dosya Alpaca'yi bilmez.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

# --------------------------------------------------------------------------
# Temel takma adlar
# --------------------------------------------------------------------------

PositivePrice = Annotated[float, Field(gt=0)]
NonNegative = Annotated[float, Field(ge=0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Side(StrEnum):
    """Islem yonu."""

    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY

    @property
    def sign(self) -> int:
        """Long icin +1, short icin -1. Kar/zarar hesaplarinda kullanilir."""
        return 1 if self is Side.BUY else -1


class Timeframe(StrEnum):
    """Desteklenen bar periyotlari. Degerler Alpaca gosterimiyle ayni."""

    M1 = "1Min"
    M5 = "5Min"
    M15 = "15Min"
    H1 = "1Hour"
    D1 = "1Day"


class EntryType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"


class Frozen(BaseModel):
    """Tum alan tiplerinin ortak tabani: degismez ve siki dogrulamali."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------
# Fiyat yuvarlama
# --------------------------------------------------------------------------


def round_price(price: float) -> float:
    """Fiyati borsanin kabul ettigi adima yuvarlar.

    ABD hisselerinde 1,00 $ ve uzeri fiyatlar 2 ondalik, altindakiler
    4 ondalik basamakla gonderilir. Yanlis ondalik emir reddine yol acar.
    """
    return round(price, 2) if abs(price) >= 1.0 else round(price, 4)


# --------------------------------------------------------------------------
# Piyasa verisi
# --------------------------------------------------------------------------


class Bar(Frozen):
    """Tek bir OHLCV mumu. `ts` mumun ACILIS zamanidir (UTC)."""

    symbol: str
    ts: datetime
    open: PositivePrice
    high: PositivePrice
    low: PositivePrice
    close: PositivePrice
    volume: NonNegative
    vwap: float | None = None
    trade_count: int | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.ts.tzinfo is None:
            msg = f"Bar.ts timezone icermeli: {self.symbol} {self.ts!r}"
            raise ValueError(msg)
        if self.high < self.low:
            msg = f"Bozuk bar {self.symbol} @ {self.ts.isoformat()}: high < low"
            raise ValueError(msg)
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            msg = (
                f"Bozuk bar {self.symbol} @ {self.ts.isoformat()}: "
                f"open/close, high-low araliginin disinda"
            )
            raise ValueError(msg)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def range(self) -> float:
        """Mumun yuksek-dusuk araligi."""
        return self.high - self.low


class Quote(Frozen):
    """Anlik en iyi alis/satis kotasyonu."""

    symbol: str
    ts: datetime
    bid: PositivePrice
    ask: PositivePrice
    bid_size: NonNegative = 0.0
    ask_size: NonNegative = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        """Spread'in baz puan cinsinden genisligi (1 bps = %0,01).

        "Ufak marj" stratejilerinde tek onemli maliyet olcusu budur.
        """
        mid = self.mid
        return 0.0 if mid <= 0 else (self.spread / mid) * 10_000

    @property
    def is_crossed(self) -> bool:
        """Alis satistan yuksekse piyasa capraz/kilitli demektir.

        Nadir ama gercek bir durum; hata firlatmiyoruz ki sistem
        cokmesin - risk kapisi bu bayragi gorup islem yapmaz.
        """
        return self.bid > self.ask


# --------------------------------------------------------------------------
# Hesap ve pozisyon
# --------------------------------------------------------------------------


class Account(Frozen):
    """Broker hesabinin anlik goruntusu."""

    equity: float
    last_equity: float
    cash: float
    buying_power: float
    daytrade_count: int = 0
    pattern_day_trader: bool = False
    trading_blocked: bool = False
    account_blocked: bool = False
    currency: str = "USD"

    @property
    def daily_pl(self) -> float:
        """Gunun basindan bu yana kar/zarar (para birimi cinsinden)."""
        return self.equity - self.last_equity

    @property
    def daily_pl_pct(self) -> float:
        """Gunun basindan bu yana kar/zarar (yuzde)."""
        return 0.0 if self.last_equity <= 0 else (self.daily_pl / self.last_equity) * 100

    @property
    def is_healthy(self) -> bool:
        """Hesap islem yapmaya uygun mu."""
        return not (self.trading_blocked or self.account_blocked)


class Position(Frozen):
    """Acik pozisyon. `qty` her zaman pozitif; yon `side` alaninda."""

    symbol: str
    side: Side
    qty: Annotated[int, Field(gt=0)]
    avg_entry_price: PositivePrice
    current_price: PositivePrice
    unrealized_pl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.qty * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.qty * self.avg_entry_price


# --------------------------------------------------------------------------
# Strateji ciktisi
# --------------------------------------------------------------------------


class Intent(Frozen):
    """Bir stratejinin "su islemi yapmak istiyorum" ifadesi.

    Intent bir EMIR DEGILDIR: miktar icermez ve brokera gitmez. Once
    risk kapisindan gecer, orada boyutlandirilir veya veto edilir.

    `features` alani karar anindaki tam fotograftir ve journal'a
    oldugu gibi yazilir. Ogrenme katmaninin tek yakiti bu alandir;
    bos birakilan her Intent, ileride analiz edilemeyecek bir islemdir.
    """

    strategy_id: str
    params_version: str = "v0"
    symbol: str
    side: Side
    reference_price: PositivePrice
    stop_loss: PositivePrice
    take_profit: PositivePrice
    confidence: Confidence = 0.5
    reason: str = ""
    features: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_bracket_geometry(self) -> Self:
        """Stop ve hedefin yone gore dogru tarafta oldugunu garanti eder.

        Ters cevrilmis bir bracket, stop'u aninda tetikleyerek girisle
        birlikte zarar yazar. Bu hatayi brokera hic ulastirmiyoruz.
        """
        if self.side is Side.BUY:
            if not self.stop_loss < self.reference_price:
                msg = (
                    f"{self.symbol} BUY: stop ({self.stop_loss}) giris fiyatinin "
                    f"({self.reference_price}) altinda olmali"
                )
                raise ValueError(msg)
            if not self.take_profit > self.reference_price:
                msg = (
                    f"{self.symbol} BUY: hedef ({self.take_profit}) giris fiyatinin "
                    f"({self.reference_price}) ustunde olmali"
                )
                raise ValueError(msg)
        else:
            if not self.stop_loss > self.reference_price:
                msg = (
                    f"{self.symbol} SELL: stop ({self.stop_loss}) giris fiyatinin "
                    f"({self.reference_price}) ustunde olmali"
                )
                raise ValueError(msg)
            if not self.take_profit < self.reference_price:
                msg = (
                    f"{self.symbol} SELL: hedef ({self.take_profit}) giris fiyatinin "
                    f"({self.reference_price}) altinda olmali"
                )
                raise ValueError(msg)
        return self

    @property
    def risk_per_share(self) -> float:
        """Hisse basina riske edilen tutar (giris ile stop arasi mesafe)."""
        return abs(self.reference_price - self.stop_loss)

    @property
    def reward_per_share(self) -> float:
        return abs(self.take_profit - self.reference_price)

    @property
    def reward_risk(self) -> float:
        """Hedef/risk orani (R katsayisi). 1.5 = riskin 1,5 kati hedef."""
        risk = self.risk_per_share
        return 0.0 if risk <= 0 else self.reward_per_share / risk


# --------------------------------------------------------------------------
# Risk kapisi ve emir
# --------------------------------------------------------------------------


class GateVerdict(Frozen):
    """Risk kapisinin bir Intent hakkindaki karari.

    Veto sebepleri journal'a yazilir. "Kapi engellemeseydi ne olurdu"
    sorusunun cevabi, risk parametrelerini ogrenmenin tek yoludur.
    """

    allowed: bool
    qty: int = 0
    vetoes: tuple[str, ...] = ()

    @classmethod
    def allow(cls, qty: int) -> GateVerdict:
        if qty <= 0:
            msg = f"Izin verilen kararin miktari pozitif olmali, alinan: {qty}"
            raise ValueError(msg)
        return cls(allowed=True, qty=qty)

    @classmethod
    def veto(cls, *reasons: str) -> GateVerdict:
        if not reasons:
            msg = "Veto en az bir sebep icermeli"
            raise ValueError(msg)
        return cls(allowed=False, qty=0, vetoes=tuple(reasons))


class BracketOrder(Frozen):
    """Brokera gonderilecek emir: giris + stop + hedef, tek paket.

    Giris her zaman stop ve hedefiyle BIRLIKTE gonderilir. Sebebi
    dogrudan senin gereksinimin: sistem gozetimsiz calisiyor. Bot
    cokerse, sunucu kapanirsa, ag giderse bile koruma emirleri
    borsada durmaya devam eder ve pozisyon korumasiz kalmaz.
    """

    symbol: str
    side: Side
    qty: Annotated[int, Field(gt=0)]
    entry_type: EntryType = EntryType.LIMIT
    limit_price: PositivePrice | None = None
    stop_loss: PositivePrice
    take_profit: PositivePrice
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: str = Field(default_factory=lambda: f"tlab-{uuid.uuid4().hex[:16]}")

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.entry_type is EntryType.LIMIT and self.limit_price is None:
            msg = f"{self.symbol}: limit emri icin limit_price zorunlu"
            raise ValueError(msg)
        if self.entry_type is EntryType.MARKET and self.limit_price is not None:
            msg = f"{self.symbol}: market emrinde limit_price bulunamaz"
            raise ValueError(msg)
        return self

    @classmethod
    def from_intent(cls, intent: Intent, qty: int, entry_type: EntryType) -> BracketOrder:
        """Onaylanmis bir Intent'i emre cevirir, fiyatlari yuvarlayarak."""
        return cls(
            symbol=intent.symbol,
            side=intent.side,
            qty=qty,
            entry_type=entry_type,
            limit_price=(
                round_price(intent.reference_price) if entry_type is EntryType.LIMIT else None
            ),
            stop_loss=round_price(intent.stop_loss),
            take_profit=round_price(intent.take_profit),
        )


class OrderRef(Frozen):
    """Brokera gonderilmis emrin kimligi ve son bilinen durumu."""

    broker_order_id: str
    client_order_id: str
    symbol: str
    submitted_at: datetime
    status: str


# --------------------------------------------------------------------------
# Karar kaydi
# --------------------------------------------------------------------------


class Decision(Frozen):
    """Tek bir karar ani: strateji ne istedi, kapi ne dedi, ne oldu.

    Veto edilen kararlar da kaydedilir - ogrenme katmani icin
    yapilmayan islemler en az yapilanlar kadar degerli.
    """

    decision_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    ts: datetime
    intent: Intent
    verdict: GateVerdict
    order: OrderRef | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.ts.tzinfo is None:
            msg = "Decision.ts timezone icermeli"
            raise ValueError(msg)
        if self.order is not None and not self.verdict.allowed:
            msg = "Veto edilmis karara emir baglanamaz"
            raise ValueError(msg)
        return self

    def to_row(self) -> dict[str, Any]:
        """Journal'a yazilacak duz sozluk gosterimi."""
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "ts": self.ts.astimezone(UTC).isoformat(),
            "symbol": self.intent.symbol,
            "strategy_id": self.intent.strategy_id,
            "params_version": self.intent.params_version,
            "side": self.intent.side.value,
            "reference_price": self.intent.reference_price,
            "stop_loss": self.intent.stop_loss,
            "take_profit": self.intent.take_profit,
            "reward_risk": self.intent.reward_risk,
            "confidence": self.intent.confidence,
            "reason": self.intent.reason,
            "allowed": int(self.verdict.allowed),
            "qty": self.verdict.qty,
            "veto_reasons": ",".join(self.verdict.vetoes),
            "broker_order_id": self.order.broker_order_id if self.order else None,
        }
