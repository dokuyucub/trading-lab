"""Seans dongusu.

Her turda sirasiyla:
  1. Broker ile mutabakat (gercek pozisyonlar ve gerceklesmeler)
  2. Kill-switch kontrolu
  3. Gun sonu zorunlu kapanis kontrolu
  4. Her sembol icin baglam kur, strateji sor, risk kapisindan gecir
  5. Izin cikarsa bracket emri gonder, her kosulda karari kaydet

Sira tesadufi degil. Mutabakat once gelir cunku her karar GERCEK
duruma gore verilmeli, hafizadaki duruma gore degil. Kill-switch
stratejilerden once gelir cunku gun kotuye gittiginde stratejinin ne
dusundugunun onemi yoktur. Kapanis kontrolu giristen once gelir cunku
kapanisa dakikalar kala acilan pozisyon, aninda zorla kapatilir.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from tlab.config import Config
from tlab.core.clock import Clock
from tlab.core.types import (
    Account,
    Bar,
    BracketOrder,
    Decision,
    EntryType,
    ExitReason,
    Intent,
    OrderRef,
    Position,
    Quote,
    Side,
    Timeframe,
)
from tlab.data.market import MarketData
from tlab.engine.reconciler import build_trade, pair_fills
from tlab.errors import BrokerError, DataError, JournalError, TradingLabError
from tlab.execution.broker import Broker
from tlab.features.context import Context, SessionPhase, SessionState, build_session_state
from tlab.journal.queries import halt_reason, open_entry_orders, unconfirmed_orders
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate, daily_loss_breached
from tlab.strategies.base import Strategy

log = logging.getLogger("tlab.runner")

MAX_BACKOFF_FACTOR = 8
"""Ardisik hatalarda beklemenin en fazla kac katina cikacagi."""


@dataclass
class LoopResult:
    """Tek bir dongu turunun sonucu."""

    now: datetime
    phase: SessionPhase
    market_open: bool
    evaluated: int = 0
    intents: int = 0
    submitted: int = 0
    vetoed: int = 0
    trades_recorded: int = 0
    flattened: int = 0
    cancelled: int = 0
    halted: bool = False
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.now:%H:%M:%S}",
            self.phase.value,
            f"borsa={'acik' if self.market_open else 'kapali'}",
            f"bakilan={self.evaluated}",
            f"niyet={self.intents}",
            f"emir={self.submitted}",
            f"veto={self.vetoed}",
        ]
        if self.trades_recorded:
            parts.append(f"kapanan={self.trades_recorded}")
        if self.flattened:
            parts.append(f"kapatilan={self.flattened}")
        if self.cancelled:
            parts.append(f"iptal={self.cancelled}")
        if self.halted:
            parts.append("DURDURULDU")
        return " | ".join(parts) + ("  " + "; ".join(self.notes) if self.notes else "")


class SessionRunner:
    """Gozetimsiz calisan seans dongusu."""

    def __init__(
        self,
        *,
        broker: Broker,
        market: MarketData,
        strategies: list[Strategy],
        gate: RiskGate,
        writer: JournalWriter,
        conn: sqlite3.Connection,
        config: Config,
        clock: Clock,
        run_id: str,
        opening_range_minutes: int = 15,
        timeframe: Timeframe = Timeframe.M1,
        history_days: int = 3,
        entry_order_ttl_minutes: int = 15,
        unconfirmed_grace_minutes: int = 5,
        dry_run: bool = False,
    ) -> None:
        self.broker = broker
        self.market = market
        self.strategies = strategies
        self.gate = gate
        self.writer = writer
        self.conn = conn
        self.config = config
        self.clock = clock
        self.run_id = run_id
        self.opening_range_minutes = opening_range_minutes
        self.timeframe = timeframe
        self.history_days = history_days
        self.entry_order_ttl_minutes = entry_order_ttl_minutes
        self.unconfirmed_grace_minutes = unconfirmed_grace_minutes
        self.dry_run = dry_run

    # ------------------------------------------------------------------
    # Ana dongu
    # ------------------------------------------------------------------

    def run_forever(self, poll_seconds: int = 60) -> None:
        """Dongu, durdurulana kadar calisir.

        Tek bir turun hatasi donguyu OLDURMEZ. Gozetimsiz calisan bir
        sistemde gecici bir ag hatasi yuzunden durmak, acik
        pozisyonlarin gun sonu kapanisini kacirmak demektir.
        Bracket emirleri borsada durdugu icin pozisyon korumasiz
        kalmaz, ama dongunun ayakta kalmasi yine de sart.
        """
        log.info("Dongu basladi (poll=%ss, dry_run=%s)", poll_seconds, self.dry_run)
        failures = 0
        while True:
            try:
                log.info("%s", self.run_once().summary())
                failures = 0
            except KeyboardInterrupt:
                log.info("Dongu elle durduruldu")
                raise
            except TradingLabError:
                failures += 1
                log.exception("Tur basarisiz (%d ardisik), dongu devam ediyor", failures)
            except Exception:
                failures += 1
                log.exception("Beklenmeyen hata (%d ardisik), dongu devam ediyor", failures)

            # Surekli basarisiz olan bir dongu, ayni hatayi dakikada bir
            # kaydederek gunlugu bogar ve gercek sorunu gorunmez kilar.
            # Ardisik hatalarda bekleme kademeli olarak uzuyor; tek bir
            # basarili tur sayaci sifirliyor.
            delay = (
                poll_seconds * min(MAX_BACKOFF_FACTOR, 2**failures) if failures else poll_seconds
            )
            time.sleep(delay)

    def run_once(self) -> LoopResult:
        """Tek tur: mutabakat, kontroller, sembol degerlendirmesi."""
        now = self.clock.now()
        market_clock = self.broker.get_market_clock()
        session = self._session_state(now)
        if market_clock.is_open:
            # Broker calendar is authoritative on shortened trading days.
            close = min(session.session_close, market_clock.next_close)
            flatten_at = close - timedelta(minutes=self.config.session.flatten_before_close_minutes)
            session = replace(
                session,
                session_close=close,
                flatten_at=flatten_at,
                phase=SessionPhase.FLATTEN if now >= flatten_at else session.phase,
            )
        result = LoopResult(now=now, phase=session.phase, market_open=market_clock.is_open)
        if market_clock.is_open and market_clock.next_close <= now:
            warning = (
                f"broker kapanis saati gecmiste: {market_clock.next_close.isoformat()} "
                f"(simdi {now.isoformat()}); guvenli kapatma uygulanacak"
            )
            log.warning(warning)
            result.notes.append(warning)

        if not market_clock.is_open:
            result.notes.append("borsa kapali (tatil ya da seans disi)")
            return result

        account = self.broker.get_account()
        positions = {position.symbol: position for position in self.broker.get_positions()}
        open_orders = self._safe_open_orders()

        # Gonderim ile kayit arasinda kalmis emirler once cozumlenir:
        # ya kesinlesirler ya da sembolun onunu tikamayi birakirlar.
        if open_orders is not None:
            self._resolve_unconfirmed(open_orders, session)

        result.trades_recorded = self._reconcile(session)

        if self._check_kill_switch(account, positions, session, result):
            return result

        if session.must_flatten:
            result.flattened = self._flatten_all(positions, ExitReason.EOD_FLATTEN)
            result.notes.append("gun sonu zorunlu kapanis")
            return result

        if open_orders is None:
            # Bekleyen emirleri bilmeden giris yapmak, dolmayi
            # bekleyen bir emrin uzerine ikincisini gondermek demek.
            result.notes.append("bekleyen emirler bilinmiyor, yeni giris yapilmadi")
            return result

        result.cancelled = self._cancel_stale_entries(open_orders, positions, session)

        if not session.can_open_new_positions:
            return result

        pending = self._pending_symbols(open_orders, positions)
        self._evaluate_universe(session, account, positions, pending, result, open_orders)
        return result

    # ------------------------------------------------------------------
    # Adimlar
    # ------------------------------------------------------------------

    def _session_state(self, now: datetime) -> SessionState:
        session_config = self.config.session
        return build_session_state(
            now,
            exchange_timezone=self.config.app.exchange_timezone,
            regular_open=(session_config.regular_open.hour, session_config.regular_open.minute),
            regular_close=(session_config.regular_close.hour, session_config.regular_close.minute),
            flatten_before_close_minutes=session_config.flatten_before_close_minutes,
            opening_range_minutes=self.opening_range_minutes,
        )

    def _reconcile(self, session: SessionState) -> int:
        """Broker gerceklesmelerinden kapanan islemleri kaydeder.

        Kayit brokerdan turetildigi icin, sistem kapaliyken olan
        bitenler de (stop tetiklenmesi, hedefe ulasma) bir sonraki
        acilista dogru sekilde journal'a duser.
        """
        since = session.session_open - timedelta(days=1)
        try:
            fills = self.broker.list_fills(since)
        except BrokerError:
            log.exception("Gerceklesmeler alinamadi, mutabakat atlandi")
            return 0

        # Her gerceklesme denetim izine dusuyor; tekrarlar yok sayiliyor.
        for single in fills:
            self.writer.record_fill(single, self.run_id)

        orders = open_entry_orders(self.conn)
        recorded = 0

        for matched in pair_fills(fills, set(orders)):
            info = orders.get(matched.entry.client_order_id)
            if info is None:
                continue
            trade = build_trade(matched, info, run_id=self.run_id, flatten_at=session.flatten_at)
            # Mukerrer kaydi veritabani engelliyor (INSERT OR IGNORE,
            # islem kimligi giris/cikis emirlerinden turetilmis).
            # Her turda tum trades tablosunu taramaya gerek yok.
            if not self.writer.record_trade(trade):
                continue
            recorded += 1
            self.writer.update_order_status(matched.entry.client_order_id, "closed")
            log.info(
                "Islem kapandi: %s %s %.4g adet | %s | net %.2f (%.2fR)",
                trade.symbol,
                trade.side.value,
                trade.qty,
                trade.exit_reason.value,
                trade.net_pnl,
                trade.r_multiple,
            )
        return recorded

    # ------------------------------------------------------------------
    # Bekleyen emirler
    # ------------------------------------------------------------------

    def _safe_open_orders(self) -> list[OrderRef] | None:
        """Brokerdaki bekleyen emirler; alinamazsa None.

        Bos liste ile "bilinmiyor" arasindaki fark kritik. Bekleyen
        emirleri goremeyen bir dongu, dolmayi bekleyen emri yok
        sanip ayni sembole yenisini gonderir. Bu yuzden hata
        durumunda bos liste DEGIL None donuyor ve cagiran taraf o
        turda yeni giris yapmiyor.
        """
        try:
            return self.broker.list_open_orders()
        except BrokerError:
            log.exception("Bekleyen emirler alinamadi")
            return None

    def _pending_symbols(
        self, open_orders: list[OrderRef], positions: dict[str, Position]
    ) -> frozenset[str]:
        """Yeni giris kabul etmeyen semboller.

        Uc kaynak birlestiriliyor: brokerdaki bekleyen emirler,
        journal'da kesinlesmemis kalan emirler ve acik pozisyonlar.
        Ucu de gerekli - broker listesi kesinlesmemis emri bilmez,
        journal ise brokerda elle acilmis emri bilmez.
        """
        pending = {order.symbol for order in open_orders}
        pending.update(row["symbol"] for row in unconfirmed_orders(self.conn))
        pending.update(positions)
        return frozenset(pending)

    def _resolve_unconfirmed(self, open_orders: list[OrderRef], session: SessionState) -> None:
        """Gonderim ile kayit arasinda kalmis emirleri cozumler.

        Emir once journal'a yaziliyor, sonra brokera gidiyor. Ikisinin
        arasinda surec olurse geriye `submitting` durumunda bir satir
        kaliyor. O satir sonsuza kadar sembolun onunu tikamamali:
          * emir brokerda bulunduysa kesinlesir,
          * bulunmadiysa ve uzerinden yeterli sure gectiyse emrin
            hic ulasmadigi kabul edilip `lost` olarak isaretlenir.
        """
        rows = unconfirmed_orders(self.conn)
        if not rows:
            return

        by_client = {order.client_order_id: order for order in open_orders}
        deadline = session.now - timedelta(minutes=self.unconfirmed_grace_minutes)

        for row in rows:
            client_id = str(row["client_order_id"])
            found = by_client.get(client_id)
            if found is not None:
                self.writer.confirm_order(client_id, found)
                log.info("Kesinlesmemis emir brokerda bulundu: %s", client_id)
                continue

            submitted = _parse_ts(str(row["submitted_at"]))
            if submitted is not None and submitted < deadline:
                self.writer.update_order_status(client_id, "lost")
                log.warning(
                    "Emir brokerda bulunamadi, kayip sayildi: %s (%s)",
                    client_id,
                    row["symbol"],
                )

    def _cancel_stale_entries(
        self,
        open_orders: list[OrderRef],
        positions: dict[str, Position],
        session: SessionState,
    ) -> int:
        """Dolmayan giris emirlerini belirli sure sonra iptal eder.

        Kirilim sinyali zamana baglidir: on dakika once gecerli olan
        bir giris fiyati artik gecerli degildir. Emri gun boyu asili
        birakmak, sinyalin ilgisiz kaldigi bir anda dolmasina yol
        acar. Koruma bacaklari bu kuralin disinda: onlar yalnizca
        acik pozisyonu olmayan sembollerde ve yalnizca bizim
        gonderdigimiz girisler icin iptal ediliyor.
        """
        if self.dry_run:
            return 0

        ours = open_entry_orders(self.conn)
        deadline = session.now - timedelta(minutes=self.entry_order_ttl_minutes)
        cancelled = 0

        for order in open_orders:
            if order.symbol in positions or order.client_order_id not in ours:
                continue
            if order.submitted_at.astimezone(UTC) >= deadline:
                continue
            try:
                self.broker.cancel_open_orders(order.symbol)
            except BrokerError:
                log.exception("%s icin bayat emir iptal edilemedi", order.symbol)
                continue
            self.writer.update_order_status(order.client_order_id, "canceled")
            cancelled += 1
            log.info(
                "Bayat giris emri iptal edildi: %s (%d dk dolmadi)",
                order.symbol,
                self.entry_order_ttl_minutes,
            )
        return cancelled

    def _check_kill_switch(
        self,
        account: Account,
        positions: dict[str, Position],
        session: SessionState,
        result: LoopResult,
    ) -> bool:
        """Gunluk zarar siniri asildiysa gunu bitirir.

        Kotu bir gunu erken kapatmak, felakete donusmesini
        beklemekten iyidir. Karar VERITABANINA yaziliyor, bellege
        degil: bellekteki bir bayrak sureci asmaz ve systemd
        yeniden baslattiginda sistem gunu kapatmis oldugunu unutup
        tekrar islem acardi.
        """
        today = session.now.date()
        existing = halt_reason(self.conn, today)
        if existing is not None:
            result.halted = True
            result.notes.append(f"gun kapali: {existing}")
            result.flattened = self._flatten_all(positions, ExitReason.KILL_SWITCH)
            return True

        if not daily_loss_breached(account, self.config.risk):
            return False

        reason = (
            f"gunluk zarar %{account.daily_pl_pct:.2f}, "
            f"sinir %{self.config.risk.max_daily_loss_pct}"
        )
        self.writer.record_halt(today, reason, self.run_id)
        result.halted = True
        result.flattened = self._flatten_all(positions, ExitReason.KILL_SWITCH)
        result.notes.append(f"KILL-SWITCH: {reason}")
        log.warning("KILL-SWITCH: %s", reason)
        return True

    def _flatten_all(self, positions: dict[str, Position], reason: ExitReason) -> int:
        """Tum pozisyonlari kapatir ve bekleyen emirleri iptal eder.

        Once emirler iptal edilir: acik bir bracket bacagi dururken
        pozisyon kapatilirsa, bacak sahipsiz kalip ters yonde yeni
        pozisyon acabilir.
        """
        if self.dry_run:
            if positions:
                log.info("[dry-run] %d pozisyon kapatilacakti (%s)", len(positions), reason.value)
            return 0

        # Include entries without positions. Refresh positions after cancellation
        # so an entry that filled during cancellation is also closed.
        try:
            self.broker.cancel_open_orders()
            remaining = self.broker.list_open_orders()
            positions = {p.symbol: p for p in self.broker.get_positions()}
        except BrokerError:
            log.exception("Kapatma oncesi emir iptali/mutabakat basarisiz; sonraki tur denenecek")
            return 0

        blocked = {order.symbol for order in remaining}
        closed = 0
        for symbol in positions:
            if symbol in blocked:
                # Cancellation can be asynchronous. Never submit a competing
                # close while a protective leg or entry is still active.
                log.warning("%s emir iptali kesinlesmedi; kapatma bekliyor", symbol)
                continue
            try:
                if self.broker.close_position(symbol) is not None:
                    closed += 1
                    log.info("Pozisyon kapatildi: %s (%s)", symbol, reason.value)
            except BrokerError:
                log.exception("%s kapatilamadi", symbol)
        return closed

    def _evaluate_universe(
        self,
        session: SessionState,
        account: Account,
        positions: dict[str, Position],
        pending: frozenset[str],
        result: LoopResult,
        open_orders: list[OrderRef],
    ) -> None:
        """Evrendeki her sembolu sirayla degerlendirir.

        Bir sembolun hatasi digerlerini etkilemez: veri gelmeyen bir
        hisse yuzunden tum seansi kaybetmek kabul edilemez.
        """
        exposure, reserved, unknown = self._pending_risk(open_orders, positions)
        for symbol in self.config.symbols:
            try:
                ctx = self._build_context(symbol, session, account, positions, pending)
            except (DataError, BrokerError):
                log.exception("%s icin baglam kurulamadi", symbol)
                continue

            if ctx is None:
                continue
            ctx = replace(
                ctx,
                reserved_exposure=exposure,
                reserved_symbols=reserved,
                unknown_order_risk=unknown,
            )
            result.evaluated += 1

            for strategy in self.strategies:
                intent = strategy.decide(ctx)
                if intent is None:
                    continue
                result.intents += 1
                try:
                    self._handle_intent(intent, ctx, result)
                except JournalError:
                    # Karar kaydedilemiyorsa emir de gonderilmiyor:
                    # kaydedilmeyen bir islem ogrenilemez ve mutabakati
                    # bozar. Kayit yoluna guvenemedigimizde islem
                    # acmamak, korumasiz islem acmaktan iyidir.
                    log.exception("%s karari kaydedilemedi, islem acilmadi", symbol)
                    result.notes.append(f"{symbol}: journal yazilamadi")
                # Reconcile a fresh broker snapshot before spending more risk.
                # A lost submit response also consumes this cycle's budget.
                if not self.dry_run and (result.submitted or unconfirmed_orders(self.conn)):
                    return
                # Ayni sembolde ilk niyet degerlendirildikten sonra
                # digerlerine bakmiyoruz: pozisyon acildiysa ikinci
                # strateji ayni riske tekrar girerdi.
                break

    def _pending_risk(
        self, orders: list[OrderRef], positions: dict[str, Position]
    ) -> tuple[float, frozenset[str], bool]:
        """Reserve pending entries; unknown external order sizes block new risk.

        Journal fallback deliberately reserves the entire original quantity:
        older adapters do not expose remaining quantity. This can over-reserve
        a partial fill but cannot under-reserve it.
        """
        known = open_entry_orders(self.conn)
        exposure = 0.0
        symbols: set[str] = set()
        unknown = bool(unconfirmed_orders(self.conn))
        reduction_budget = {symbol: position.qty for symbol, position in positions.items()}
        for order in orders:
            row = known.get(order.client_order_id)
            qty = order.remaining_qty
            side = order.side
            price = order.limit_price
            if row is not None:
                qty = float(row["qty"]) if qty is None else qty
                side = Side(str(row["side"])) if side is None else side
                price = float(row["limit_price"] or 0) if price is None else price
            if qty == 0:
                continue
            position = positions.get(order.symbol)
            # Only an identified order that cannot increase this position is
            # excluded. Missing metadata must never be treated as zero risk.
            if (
                row is None
                and position is not None
                and side is not None
                and side is not position.side
                and qty is not None
                and qty <= reduction_budget[order.symbol]
            ):
                reduction_budget[order.symbol] -= qty
                continue
            symbols.add(order.symbol)
            if qty is None or price is None or price <= 0:
                unknown = True
                continue
            exposure += qty * price
        return exposure, frozenset(symbols), unknown

    def _handle_intent(self, intent: Intent, ctx: Context, result: LoopResult) -> None:
        """Niyeti risk kapisindan gecirir, gerekirse emre cevirir."""
        verdict = self.gate.evaluate(intent, ctx)
        decision = Decision(run_id=self.run_id, ts=ctx.session.now, intent=intent, verdict=verdict)

        if not verdict.allowed:
            result.vetoed += 1
            log.debug("%s veto: %s", intent.symbol, "; ".join(verdict.vetoes))
            self.writer.record_decision(decision)
            return

        # Emir BIR KEZ uretilir. Her uretim yeni bir client_order_id
        # dogurur; ikinci kez uretmek journal'a gonderilenden farkli
        # bir kimlik yazar ve mutabakat o islemi bir daha bulamaz.
        order = BracketOrder.from_intent(intent, verdict.qty, EntryType.LIMIT)
        self.writer.record_decision(decision)

        if self.dry_run:
            result.notes.append(f"[dry-run] {intent.symbol} {verdict.qty} adet")
            return

        # Once kaydet, sonra gonder. Ters sirada calisip da ikisinin
        # arasinda surec olurse, brokerdaki emir journal'da hic
        # gorunmez: dolmasindan dogan pozisyon hicbir karara
        # atfedilemez ve mutabakat onu hesaba katamaz.
        self.writer.record_order(order, run_id=self.run_id, decision_id=decision.decision_id)

        try:
            order_ref = self.broker.submit_bracket(order)
        except BrokerError:
            log.exception("%s emri gonderilemedi", intent.symbol)
            # Emir brokera ulasmis da cevabi kaybolmus olabilir.
            # `submitting` durumunda birakiliyor; bir sonraki turda
            # brokera karsi cozumlenecek.
            return

        self.writer.confirm_order(order.client_order_id, order_ref)
        result.submitted += 1
        log.info(
            "Emir gonderildi: %s %s %d adet @ %.2f (stop %.2f, hedef %.2f)",
            order.symbol,
            order.side.value,
            order.qty,
            order.limit_price or 0.0,
            order.stop_loss,
            order.take_profit,
        )

    def _build_context(
        self,
        symbol: str,
        session: SessionState,
        account: Account,
        positions: dict[str, Position],
        pending: frozenset[str],
    ) -> Context | None:
        """Bir sembol icin karar baglamini kurar."""
        start = session.now - timedelta(days=self.history_days)
        bars = self.market.bars(symbol, self.timeframe, start=start, end=session.now)
        closed = self._closed_bars(bars, session.now)
        if not closed:
            return None

        quote: Quote | None
        try:
            quote = self.market.latest_quote(symbol)
        except DataError:
            # Kotasyon alinamazsa baglam yine kurulur; risk kapisi
            # spread'i dogrulayamadigi icin islemi zaten veto edecek.
            log.debug("%s icin kotasyon alinamadi", symbol)
            quote = None

        return Context(
            symbol=symbol,
            session=session,
            bars=tuple(closed),
            account=account,
            positions=positions,
            quote=quote,
            pending_orders=pending,
        )

    def _closed_bars(self, bars: list[Bar], now: datetime) -> list[Bar]:
        """Olusmakta olan bari ayiklar.

        Kapanmamis bir barin kapanis fiyatini karara katmak, gelecegi
        bilmek demektir. Canlida bu bari kullanmak stratejiyi
        backtest'te imkansiz olan bir bilgiye dayandirir ve iki
        ortamin sonuclarini birbirinden kopariir.
        """
        duration = self.timeframe.duration
        return [bar for bar in bars if bar.ts.astimezone(UTC) + duration <= now]


def _parse_ts(raw: str) -> datetime | None:
    """Journal'daki ISO zaman damgasini cozer; bozuksa None.

    Bozuk bir zaman damgasi yuzunden donguyu durdurmuyoruz: en
    fazla o satirin yasi bilinemez ve bir sonraki turda yeniden
    denenir.
    """
    try:
        return datetime.fromisoformat(raw).astimezone(UTC)
    except (TypeError, ValueError):
        return None
