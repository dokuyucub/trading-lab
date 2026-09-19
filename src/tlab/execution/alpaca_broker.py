"""Alpaca broker baglantisi (Faz 0: salt okunur)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tlab.core.types import Account, Position, Side
from tlab.errors import BrokerError
from tlab.sdk_compat import sdk_bool, sdk_field, sdk_float, sdk_int


@dataclass(frozen=True)
class AlpacaMarketClock:
    is_open: bool
    next_open: datetime
    next_close: datetime


class AlpacaBroker:
    """Alpaca hesabina baglanir ve hesap/pozisyon durumunu okur."""

    def __init__(self, api_key: str, secret_key: str, *, paper: bool = True) -> None:
        from alpaca.trading.client import TradingClient

        self.paper = paper
        self._client = TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)

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
