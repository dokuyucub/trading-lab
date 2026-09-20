"""Simulasyon brokeri.

Broker protokolunu uygular, ama emirleri gercek bir borsaya degil
gecmis barlara karsi isletir. Ustteki hicbir katman farki gormez:
strateji, risk kapisi ve seans dongusu aynen calisir.

DOLUM MODELI BILINCLI OLARAK KOTUMSERDIR. Backtest'in isi guzel
rakamlar uretmek degil, gercekte olabilecegin ALT sinirini vermektir.
Iyimser bir simulasyon, canliya gecince kaybolan bir karlilik
gosterir - ve bu, hic backtest yapmamaktan daha zararlidir cunku
yanlis bir guven verir.

Somut kotumser secimler:
  * Limit emri, barin fiyat araligi limite DOKUNSA bile ancak
    limitin otesine gecildiginde dolar. Fiyata sadece degip donen
    bir barda sirada onumuzde kimsenin olmadigini varsaymiyoruz.
  * Ayni barda hem stop hem hedef tetiklenirse STOP kabul edilir.
    Bar icindeki siralamayi bilmiyoruz; bilmedigimiz yerde aleyhimize
    olani seciyoruz.
  * Gap'lerde dolum, aleyhimize olan fiyattan yapilir.
  * Her dolumda kayma (slippage) ve komisyon dusulur.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tlab.core.types import (
    Account,
    Bar,
    BracketOrder,
    EntryType,
    Fill,
    OrderRef,
    Position,
    Side,
)
from tlab.errors import BrokerError


@dataclass(frozen=True)
class SimFillModel:
    """Dolum varsayimlari.

    Varsayilanlar muhafazakar. Alpaca ABD hisselerinde komisyon
    almadigi icin komisyon sifir; asil maliyet kayma ve spread.
    """

    slippage_bps: float = 1.0
    """Her dolumda aleyhimize uygulanan kayma."""

    commission_bps: float = 0.0
    """Islem hacmi uzerinden komisyon."""

    require_penetration: bool = True
    """Limit emri icin fiyata degmek yetmez, otesine gecilmeli."""


@dataclass
class _SimOrder:
    """Simulasyondaki bekleyen bir bracket emri."""

    order: BracketOrder
    broker_order_id: str
    submitted_at: datetime
    filled: bool = False
    entry_price: float = 0.0


@dataclass
class _SimClock:
    """Borsa saati; motor tarafindan her adimda guncellenir."""

    is_open: bool = False
    next_open: datetime = datetime(1970, 1, 1, tzinfo=UTC)
    next_close: datetime = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass
class SimBroker:
    """Gecmis barlara karsi calisan broker."""

    starting_equity: float = 100_000.0
    fill_model: SimFillModel = field(default_factory=SimFillModel)

    def __post_init__(self) -> None:
        self.cash = self.starting_equity
        self.realized_pnl = 0.0
        self.day_start_equity = self.starting_equity
        self._positions: dict[str, Position] = {}
        self._pending: list[_SimOrder] = []
        self._active: dict[str, _SimOrder] = {}
        self._fills: list[Fill] = []
        self._last_price: dict[str, float] = {}
        self._clock = _SimClock()
        self._now = datetime(1970, 1, 1, tzinfo=UTC)

    # ------------------------------------------------------------------
    # Motor arayuzu (Broker protokolunun disinda)
    # ------------------------------------------------------------------

    def set_clock(
        self, *, is_open: bool, now: datetime, next_open: datetime, next_close: datetime
    ) -> None:
        """Motorun sagladigi borsa saati ve simulasyon ani."""
        self._clock = _SimClock(is_open=is_open, next_open=next_open, next_close=next_close)
        self._now = now

    def start_day(self) -> None:
        """Yeni islem gunu: gunluk kar/zarar referansi sifirlanir."""
        self.day_start_equity = self.equity

    def advance(self, bar: Bar) -> None:
        """Bir bari isler: once girisler, sonra cikislar.

        Sira onemli: ayni barda hem giris hem cikis olmasi gercekci
        degildir. Giris o barda dolduysa cikis kontrolu BIR SONRAKI
        bara birakilir; aksi halde simulasyon, gercekte olmasi cok
        zor bir kazanci ucretsiz sayardi.
        """
        self._last_price[bar.symbol] = bar.close
        just_entered = self._process_entries(bar)
        self._process_exits(bar, skip=just_entered)

    @property
    def equity(self) -> float:
        """Nakit + acik pozisyonlarin gerceklesmemis kar/zarari.

        Muhasebe modeli basit tutuldu: pozisyon acarken maliyet nakitten
        DUSULMUYOR, kapanista yalnizca kar/zarar ekleniyor. Bu, marjsiz
        bir hesabin ozsermaye egrisini dogru verir; alim gucu ise ayrica
        acik maruziyet dusulerek hesaplaniyor.
        """
        return self.cash + sum(
            self._unrealized(symbol, position) for symbol, position in self._positions.items()
        )

    @property
    def gross_exposure(self) -> float:
        return sum(
            position.qty * self._last_price.get(symbol, position.avg_entry_price)
            for symbol, position in self._positions.items()
        )

    def _unrealized(self, symbol: str, position: Position) -> float:
        price = self._last_price.get(symbol, position.avg_entry_price)
        return (price - position.avg_entry_price) * position.qty * position.side.sign

    # ------------------------------------------------------------------
    # Broker protokolu - okuma
    # ------------------------------------------------------------------

    def get_account(self) -> Account:
        equity = self.equity
        return Account(
            equity=equity,
            last_equity=self.day_start_equity,
            cash=self.cash,
            # Marj YOK: kullanilabilir alim gucu, ozsermayeden acik
            # maruziyet dusulerek bulunur. Kaldirac varsaymak,
            # backtest'i gercekte alinamayacak pozisyonlarla sisirir.
            buying_power=max(0.0, equity - self.gross_exposure),
            daytrade_count=0,
            pattern_day_trader=False,
        )

    def get_positions(self) -> list[Position]:
        return [
            position.model_copy(
                update={
                    "current_price": self._last_price.get(symbol, position.avg_entry_price),
                    "unrealized_pl": self._unrealized(symbol, position),
                }
            )
            for symbol, position in self._positions.items()
        ]

    def get_market_clock(self) -> _SimClock:
        return self._clock

    def list_open_orders(self) -> list[OrderRef]:
        refs = [
            OrderRef(
                broker_order_id=pending.broker_order_id,
                client_order_id=pending.order.client_order_id,
                symbol=pending.order.symbol,
                submitted_at=pending.submitted_at,
                status="new",
            )
            for pending in self._pending
        ]
        # Dolmus girislerin koruma bacaklari da acik emirdir.
        refs.extend(
            OrderRef(
                broker_order_id=f"{active.broker_order_id}-leg",
                client_order_id=f"{active.order.client_order_id}-leg",
                symbol=symbol,
                submitted_at=active.submitted_at,
                status="new",
            )
            for symbol, active in self._active.items()
        )
        return refs

    def list_fills(self, since: datetime) -> list[Fill]:
        return [fill for fill in self._fills if fill.filled_at >= since]

    # ------------------------------------------------------------------
    # Broker protokolu - yazma
    # ------------------------------------------------------------------

    def submit_bracket(self, order: BracketOrder) -> OrderRef:
        if order.symbol in self._active or any(
            pending.order.symbol == order.symbol for pending in self._pending
        ):
            msg = f"{order.symbol}: simulasyonda zaten acik bir emir var"
            raise BrokerError(msg)

        broker_order_id = f"sim-{uuid.uuid4().hex[:12]}"
        self._pending.append(
            _SimOrder(order=order, broker_order_id=broker_order_id, submitted_at=self._now)
        )
        return OrderRef(
            broker_order_id=broker_order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            submitted_at=self._now,
            status="accepted",
        )

    def close_position(self, symbol: str) -> OrderRef | None:
        position = self._positions.get(symbol)
        if position is None:
            return None
        price = self._last_price.get(symbol, position.avg_entry_price)
        self._close(symbol, price=price, order_type="market")
        return OrderRef(
            broker_order_id=f"sim-close-{uuid.uuid4().hex[:8]}",
            client_order_id=f"sim-close-{symbol}",
            symbol=symbol,
            submitted_at=self._now,
            status="filled",
        )

    def cancel_open_orders(self, symbol: str | None = None) -> int:
        before = len(self._pending)
        self._pending = [
            pending
            for pending in self._pending
            if symbol is not None and pending.order.symbol != symbol
        ]
        return before - len(self._pending)

    # ------------------------------------------------------------------
    # Dolum mantigi
    # ------------------------------------------------------------------

    def _process_entries(self, bar: Bar) -> bool:
        """Bekleyen giris emirlerini bu bara karsi dener."""
        entered = False
        for pending in list(self._pending):
            order = pending.order
            if order.symbol != bar.symbol:
                continue

            price = self._entry_price(order, bar)
            if price is None:
                continue

            filled_at = self._adjust(price, order.side)
            self._open(order, filled_at, pending, bar.ts)
            self._pending.remove(pending)
            entered = True
        return entered

    def _entry_price(self, order: BracketOrder, bar: Bar) -> float | None:
        """Giris bu barda dolar mi, dolarsa hangi fiyattan."""
        if order.entry_type is EntryType.MARKET:
            return bar.open

        limit = order.limit_price
        if limit is None:
            return None

        # Emir piyasaya gore "marketable" ise (alis limiti acilisin
        # ustunde) aninda dolar. Degilse pasif bir emirdir ve dolmasi
        # icin fiyatin gelip limiti ASMASI gerekir - sadece degip
        # donen bir barda sirada onumuzde kimse olmadigini varsaymak
        # simulasyonu iyimser yapardi.
        strict = self.fill_model.require_penetration
        if order.side is Side.BUY:
            if bar.open <= limit:
                return limit
            touched = bar.low < limit if strict else bar.low <= limit
        else:
            if bar.open >= limit:
                return limit
            touched = bar.high > limit if strict else bar.high >= limit
        return limit if touched else None

    def _process_exits(self, bar: Bar, *, skip: bool) -> None:
        """Acik pozisyonun stop ve hedefini bu bara karsi dener."""
        active = self._active.get(bar.symbol)
        if active is None or skip:
            return

        order = active.order
        long_side = order.side is Side.BUY
        stop_hit = bar.low <= order.stop_loss if long_side else bar.high >= order.stop_loss
        target_hit = bar.high >= order.take_profit if long_side else bar.low <= order.take_profit

        # Bar icindeki siralamayi bilmiyoruz; bilmedigimiz yerde
        # aleyhimize olani seciyoruz.
        if stop_hit:
            # Gap asagi acildiysa stop fiyatindan degil, acilistan
            # cikilir: stop emri bir GARANTI DEGIL, tetikleyicidir.
            price = min(order.stop_loss, bar.open) if long_side else max(order.stop_loss, bar.open)
            self._close(bar.symbol, price=price, order_type="stop", ts=bar.ts)
        elif target_hit:
            # Hedef lehimize gap yapsa bile hedef fiyati kullaniliyor:
            # limit emri hedefin otesinde dolmaz.
            self._close(bar.symbol, price=order.take_profit, order_type="limit", ts=bar.ts)

    def _open(self, order: BracketOrder, price: float, pending: _SimOrder, ts: datetime) -> None:
        notional = price * order.qty
        self.cash -= self.fill_model.commission_bps / 10_000 * notional
        self._positions[order.symbol] = Position(
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            avg_entry_price=price,
            current_price=price,
        )
        pending.filled = True
        pending.entry_price = price
        self._active[order.symbol] = pending
        self._fills.append(
            Fill(
                broker_order_id=pending.broker_order_id,
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=price,
                filled_at=ts,
                order_type=order.entry_type.value,
            )
        )

    def _close(
        self, symbol: str, *, price: float, order_type: str, ts: datetime | None = None
    ) -> None:
        position = self._positions.pop(symbol)
        active = self._active.pop(symbol, None)
        exit_side = position.side.opposite
        price = self._adjust(price, exit_side)

        pnl = (price - position.avg_entry_price) * position.qty * position.side.sign
        notional = price * position.qty
        self.cash += pnl - self.fill_model.commission_bps / 10_000 * notional
        self.realized_pnl += pnl

        self._fills.append(
            Fill(
                broker_order_id=f"{active.broker_order_id}-exit" if active else f"sim-{symbol}",
                client_order_id=f"{active.order.client_order_id}-leg"
                if active
                else f"sim-{symbol}",
                symbol=symbol,
                side=exit_side,
                qty=position.qty,
                price=price,
                filled_at=ts or self._now,
                order_type=order_type,
            )
        )

    def _adjust(self, price: float, side: Side) -> float:
        """Kaymayi her zaman ALEYHIMIZE uygular."""
        drift = price * self.fill_model.slippage_bps / 10_000
        return price + drift if side is Side.BUY else price - drift
