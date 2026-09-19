"""Mutabakat: broker gerceklesmelerinden islem kaydi uretir.

Islem kayitlari bizim ne gonderdigimizden DEGIL, broker'in ne
gerceklestirdiginden turetilir. Sebep basit: emir gonderilmis olabilir
ama dolmamis olabilir, kismi dolmus olabilir, ya da planlanandan farkli
fiyattan dolmus olabilir. Gercek olan tek sey gerceklesmedir.

Bu modulun tamami saf fonksiyonlardan olusur: girdisi gerceklesme
listesi, ciktisi eslestirilmis islemler. Ag yok, veritabani yok. Bu
sayede en karmasik mantik parcasi tamamen cevrimdisi test edilebiliyor.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tlab.core.types import ExitReason, Fill, Side, Trade


@dataclass(frozen=True)
class MatchedTrade:
    """Eslestirilmis giris-cikis cifti."""

    entry: Fill
    exit: Fill
    qty: float

    @property
    def trade_id(self) -> str:
        """Giris ve cikis emirlerinden TURETILEN kararli kimlik.

        Rastgele olmamasi onemli: mutabakat dongusu ayni islemi her
        turda yeniden gorur. Turetilmis kimlik sayesinde kayit bir kez
        duser, yeniden baslatma sonrasi mukerrer islem olusmaz.
        """
        seed = f"{self.entry.broker_order_id}|{self.exit.broker_order_id}"
        return hashlib.sha256(seed.encode()).hexdigest()[:32]


def pair_fills(fills: Sequence[Fill], our_entry_ids: set[str]) -> list[MatchedTrade]:
    """Gerceklesmeleri giris-cikis ciftlerine ayirir.

    Yalnizca BIZIM gonderdigimiz giris emirleri (our_entry_ids) bir
    islem baslatir. Elle acilmis ya da baska bir araciyla girilmis
    pozisyonlar yok sayilir; aksi halde bize ait olmayan sonuclar
    stratejilerin istatistiklerini kirletirdi.

    Sistem sembol basina tek pozisyon acacak sekilde tasarlandigi
    icin her sembolde ayni anda tek bir acik giris varsayiliyor.
    """
    by_symbol: dict[str, list[Fill]] = {}
    for fill in fills:
        by_symbol.setdefault(fill.symbol, []).append(fill)

    matched: list[MatchedTrade] = []
    for symbol_fills in by_symbol.values():
        ordered = sorted(symbol_fills, key=lambda fill: fill.filled_at)
        open_entry: Fill | None = None
        open_qty = 0.0

        for fill in ordered:
            if open_entry is None:
                if fill.client_order_id in our_entry_ids:
                    open_entry, open_qty = fill, fill.qty
                continue

            if fill.side is open_entry.side:
                # Ayni yonde ikinci bir dolum: pozisyona ekleme.
                open_qty += fill.qty
                continue

            closed = min(open_qty, fill.qty)
            matched.append(MatchedTrade(entry=open_entry, exit=fill, qty=closed))
            open_qty -= closed
            if open_qty <= 0:
                open_entry, open_qty = None, 0.0

    return matched


def infer_exit_reason(exit_fill: Fill, flatten_at: datetime | None = None) -> ExitReason:
    """Cikisin neden olustugunu emir tipinden ve zamanindan cikarir.

    Bracket bacaklarinda tip dogrudan sebebi soyler: limit bacagi
    hedefe, stop bacagi stop'a ulasildigini gosterir. Piyasa emriyle
    yapilan cikis ise ya gun sonu zorunlu kapanistir ya da elle
    mudahale; ikisi kapanis tamponuna gore ayirt edilir.
    """
    if exit_fill.order_type == "limit":
        return ExitReason.TARGET
    if exit_fill.order_type in {"stop", "stop_limit"}:
        return ExitReason.STOP
    if flatten_at is not None and exit_fill.filled_at >= flatten_at:
        return ExitReason.EOD_FLATTEN
    return ExitReason.MANUAL


def build_trade(
    matched: MatchedTrade,
    order_info: Mapping[str, Any],
    *,
    run_id: str,
    flatten_at: datetime | None = None,
) -> Trade:
    """Eslestirilmis bir cifti journal'a yazilabilir islem kaydina cevirir.

    `order_info`, giris emrinin journal kaydidir: planlanan stop,
    hedef ve limit fiyatini oradan aliyoruz. Planlanan ile gerceklesen
    arasindaki fark (slippage) bu sayede olculebiliyor - stratejinin
    kagit uzerindeki performansi ile gercek performansi arasindaki
    fark tam olarak budur.
    """
    entry, exit_fill = matched.entry, matched.exit
    planned_stop = float(order_info["stop_loss"])
    planned_target = float(order_info["take_profit"])
    exit_reason = infer_exit_reason(exit_fill, flatten_at)

    planned_exit = {
        ExitReason.TARGET: planned_target,
        ExitReason.STOP: planned_stop,
    }.get(exit_reason)

    return Trade(
        trade_id=matched.trade_id,
        run_id=run_id,
        decision_id=order_info.get("decision_id"),
        symbol=entry.symbol,
        strategy_id=str(order_info.get("strategy_id") or "unknown"),
        params_version=str(order_info.get("params_version") or "unknown"),
        side=entry.side,
        qty=matched.qty,
        entry_ts=entry.filled_at,
        entry_price=entry.price,
        exit_ts=exit_fill.filled_at,
        exit_price=exit_fill.price,
        planned_stop=planned_stop,
        planned_target=planned_target,
        exit_reason=exit_reason,
        entry_slippage_bps=_slippage_bps(
            planned=_as_float(order_info.get("limit_price")),
            actual=entry.price,
            paying=entry.side is Side.BUY,
        ),
        exit_slippage_bps=_slippage_bps(
            planned=planned_exit,
            actual=exit_fill.price,
            paying=exit_fill.side is Side.BUY,
        ),
    )


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slippage_bps(planned: float | None, actual: float, *, paying: bool) -> float | None:
    """Planlanan ve gerceklesen fiyat arasindaki fark, baz puan cinsinden.

    Isaret her zaman MALIYET yonunde: pozitif deger aleyhimize
    gerceklesmeyi gosterir. Alirken planlanandan pahaliya, satarken
    planlanandan ucuza kapatmak maliyettir. Isaretin yone gore
    degismemesi, farkli islemleri toplayip ortalama alabilmek icin
    sart.
    """
    if planned is None or planned <= 0:
        return None
    difference = (actual - planned) if paying else (planned - actual)
    return difference / planned * 10_000
