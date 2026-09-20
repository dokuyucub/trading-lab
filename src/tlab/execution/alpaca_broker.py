"""Alpaca broker baglantisi (Faz 0: salt okunur)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tlab.core.types import (
    Account,
    BracketOrder,
    EntryType,
    Fill,
    OrderRef,
    Position,
    Side,
    TimeInForce,
)
from tlab.errors import BrokerError
from tlab.sdk_compat import sdk_bool, sdk_field, sdk_float, sdk_int


@dataclass(frozen=True)
class AlpacaMarketClock:
    is_open: bool
    next_open: datetime
    next_close: datetime


class AlpacaBroker:
    """Alpaca hesabina baglanir ve hesap/pozisyon durumunu okur."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        paper: bool = True,
        base_url: str | None = None,
    ) -> None:
        """`base_url` Alpaca'nin adresini degistirir.

        Uretimde bos birakilir. Varlik sebebi, istemciyi Alpaca'nin
        yanit sekillerini taklit eden yerel bir sunucuya
        yonlendirebilmek: boylece istek kurulumu, JSON serilestirmesi
        ve yanit ayristirmasi - yani bizim kodumuzun tum HTTP yuzeyi -
        ag erisimi olmadan uctan uca dogrulanabiliyor.
        """
        from alpaca.trading.client import TradingClient

        self.paper = paper
        self._client = TradingClient(
            api_key=api_key, secret_key=secret_key, paper=paper, url_override=base_url
        )

    def get_account(self) -> Account:
        try:
            raw: Any = self._client.get_account()
        except Exception as exc:
            msg = f"Hesap bilgisi alinamadi: {exc}"
            raise BrokerError(msg) from exc

        equity = sdk_float(raw, "equity")
        return Account(
            equity=equity,
            # Hesabin ilk gununde last_equity bos gelebilir; o durumda
            # gunluk kar/zarari sifir saymak icin equity'ye esitliyoruz.
            last_equity=sdk_float(raw, "last_equity", default=equity),
            cash=sdk_float(raw, "cash"),
            buying_power=sdk_float(raw, "buying_power"),
            daytrade_count=sdk_int(raw, "daytrade_count"),
            pattern_day_trader=sdk_bool(raw, "pattern_day_trader"),
            trading_blocked=sdk_bool(raw, "trading_blocked"),
            account_blocked=sdk_bool(raw, "account_blocked"),
            currency=str(sdk_field(raw, "currency", "USD")),
        )

    def get_positions(self) -> list[Position]:
        try:
            raw_positions: Any = self._client.get_all_positions()
        except Exception as exc:
            msg = f"Pozisyonlar alinamadi: {exc}"
            raise BrokerError(msg) from exc

        positions: list[Position] = []
        for raw in raw_positions:
            qty = sdk_float(raw, "qty")
            if qty == 0:
                continue
            entry_price = sdk_float(raw, "avg_entry_price")
            positions.append(
                Position(
                    symbol=str(sdk_field(raw, "symbol", "")),
                    # Alpaca short pozisyonlari negatif miktarla bildirir;
                    # biz yonu ayri alanda tutup miktari pozitif sakliyoruz.
                    side=Side.BUY if qty > 0 else Side.SELL,
                    # Yuvarlama yok: 0,5 hisselik bir pozisyon int()
                    # ile sifira duser ve sistem onu hic gormez.
                    # Mutabakatta pozisyonu kacirmak, gozetimsiz
                    # calisan bir sistemde en tehlikeli hatadir.
                    qty=abs(qty),
                    avg_entry_price=entry_price,
                    # Piyasa kapaliyken current_price bos gelebilir.
                    current_price=sdk_float(raw, "current_price") or entry_price,
                    unrealized_pl=sdk_float(raw, "unrealized_pl"),
                )
            )
        return positions

    def get_market_clock(self) -> AlpacaMarketClock:
        try:
            raw: Any = self._client.get_clock()
        except Exception as exc:
            msg = f"Borsa saati alinamadi: {exc}"
            raise BrokerError(msg) from exc

        next_open = sdk_field(raw, "next_open")
        next_close = sdk_field(raw, "next_close")
        if not isinstance(next_open, datetime) or not isinstance(next_close, datetime):
            msg = "Borsa saati yaniti beklenen bicimde degil"
            raise BrokerError(msg)

        return AlpacaMarketClock(
            is_open=sdk_bool(raw, "is_open"),
            next_open=next_open,
            next_close=next_close,
        )

    # ------------------------------------------------------------------
    # Emirler
    # ------------------------------------------------------------------

    def list_open_orders(self) -> list[OrderRef]:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        try:
            raw_orders: Any = self._client.get_orders(
                filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)
            )
        except Exception as exc:
            msg = f"Bekleyen emirler alinamadi: {exc}"
            raise BrokerError(msg) from exc

        return [self._to_order_ref(raw) for raw in raw_orders]

    def submit_bracket(self, order: BracketOrder) -> OrderRef:
        """Giris + stop + hedefi tek paket halinde gonderir."""
        from alpaca.trading.enums import OrderClass, OrderSide
        from alpaca.trading.enums import TimeInForce as AlpacaTIF
        from alpaca.trading.requests import (
            LimitOrderRequest,
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        common = {
            "symbol": order.symbol,
            "qty": order.qty,
            "side": OrderSide.BUY if order.side is Side.BUY else OrderSide.SELL,
            "time_in_force": (
                AlpacaTIF.DAY if order.time_in_force is TimeInForce.DAY else AlpacaTIF.GTC
            ),
            "order_class": OrderClass.BRACKET,
            "take_profit": TakeProfitRequest(limit_price=order.take_profit),
            "stop_loss": StopLossRequest(stop_price=order.stop_loss),
            "client_order_id": order.client_order_id,
        }

        request = (
            LimitOrderRequest(limit_price=order.limit_price, **common)
            if order.entry_type is EntryType.LIMIT
            else MarketOrderRequest(**common)
        )

        try:
            raw: Any = self._client.submit_order(order_data=request)
        except Exception as exc:
            msg = f"{order.symbol} emri gonderilemedi: {exc}"
            raise BrokerError(msg) from exc

        return self._to_order_ref(raw)

    def close_position(self, symbol: str) -> OrderRef | None:
        """Pozisyonu piyasa emriyle kapatir.

        Alpaca pozisyon yoksa hata dondurur; bunu None'a ceviriyoruz
        cunku "zaten kapali" bir hata degil, istenen son durumdur.
        """
        try:
            raw: Any = self._client.close_position(symbol)
        except Exception as exc:
            if _is_position_missing(exc):
                return None
            msg = f"{symbol} pozisyonu kapatilamadi: {exc}"
            raise BrokerError(msg) from exc
        return self._to_order_ref(raw)

    def cancel_open_orders(self, symbol: str | None = None) -> int:
        """Bekleyen emirleri iptal eder."""
        if symbol is None:
            try:
                cancelled: Any = self._client.cancel_orders()
            except Exception as exc:
                msg = f"Emirler iptal edilemedi: {exc}"
                raise BrokerError(msg) from exc
            return len(list(cancelled))

        count = 0
        for order in self.list_open_orders():
            if order.symbol != symbol:
                continue
            try:
                self._client.cancel_order_by_id(order.broker_order_id)
            except Exception as exc:
                msg = f"{symbol} emri iptal edilemedi ({order.broker_order_id}): {exc}"
                raise BrokerError(msg) from exc
            count += 1
        return count

    @staticmethod
    def _to_order_ref(raw: Any) -> OrderRef:
        """SDK emir nesnesini cekirdek OrderRef tipine cevirir."""
        submitted = sdk_field(raw, "submitted_at") or sdk_field(raw, "created_at")
        if not isinstance(submitted, datetime):
            msg = "Emir yanitinda gecerli bir zaman damgasi yok"
            raise BrokerError(msg)

        status = sdk_field(raw, "status", "unknown")
        side_raw = sdk_field(raw, "side")
        side_value = str(getattr(side_raw, "value", side_raw)).lower()
        qty_raw = sdk_field(raw, "qty")
        price = sdk_float(raw, "limit_price")
        return OrderRef(
            side=Side(side_value) if side_value in ("buy", "sell") else None,
            remaining_qty=(
                max(0.0, sdk_float(raw, "qty") - sdk_float(raw, "filled_qty"))
                if qty_raw is not None
                else None
            ),
            limit_price=price if price > 0 else None,
            broker_order_id=str(sdk_field(raw, "id", "")),
            client_order_id=str(sdk_field(raw, "client_order_id", "")),
            symbol=str(sdk_field(raw, "symbol", "")),
            submitted_at=submitted,
            status=str(getattr(status, "value", status)),
        )

    def list_fills(self, since: datetime) -> list[Fill]:
        """Verilen andan bu yana gerceklesmis emirleri bacaklariyla dondurur."""
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        try:
            raw_orders: Any = self._client.get_orders(
                filter=GetOrdersRequest(
                    status=QueryOrderStatus.ALL,
                    after=since,
                    # Bracket bacaklari ebeveynin icinde geliyor; duz
                    # listede kayboluyorlar ve cikislari kaciririz.
                    nested=True,
                    limit=500,
                )
            )
        except Exception as exc:
            msg = f"Gerceklesmeler alinamadi: {exc}"
            raise BrokerError(msg) from exc

        fills: list[Fill] = []
        for raw in raw_orders:
            fills.extend(self._collect_fills(raw))
        fills.sort(key=lambda fill: fill.filled_at)
        return fills

    @classmethod
    def _collect_fills(cls, raw: Any) -> list[Fill]:
        """Bir emri ve tum bacaklarini gerceklesme listesine cevirir."""
        fills: list[Fill] = []
        single = cls._to_fill(raw)
        if single is not None:
            fills.append(single)
        for leg in sdk_field(raw, "legs", []) or []:
            fills.extend(cls._collect_fills(leg))
        return fills

    @staticmethod
    def _to_fill(raw: Any) -> Fill | None:
        """Dolmus bir emri Fill'e cevirir; dolmamissa None."""
        filled_at = sdk_field(raw, "filled_at")
        qty = sdk_float(raw, "filled_qty")
        price = sdk_float(raw, "filled_avg_price")
        if not isinstance(filled_at, datetime) or qty <= 0 or price <= 0:
            return None

        side_raw = sdk_field(raw, "side", "")
        side_value = str(getattr(side_raw, "value", side_raw)).lower()
        order_type = sdk_field(raw, "order_type") or sdk_field(raw, "type", "market")

        return Fill(
            broker_order_id=str(sdk_field(raw, "id", "")),
            client_order_id=str(sdk_field(raw, "client_order_id", "")),
            symbol=str(sdk_field(raw, "symbol", "")),
            side=Side.BUY if side_value == "buy" else Side.SELL,
            qty=qty,
            price=price,
            filled_at=filled_at,
            order_type=str(getattr(order_type, "value", order_type)).lower(),
        )


def _is_position_missing(exc: Exception) -> bool:
    """Alpaca'nin "pozisyon yok" hatasini ayirt eder."""
    text = str(exc).lower()
    return "position does not exist" in text or "position not found" in text
