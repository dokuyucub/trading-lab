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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

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
    Position,
    Quote,
    Timeframe,
)
from tlab.data.market import MarketData
from tlab.engine.reconciler import build_trade, pair_fills
from tlab.errors import BrokerError, DataError, TradingLabError
from tlab.execution.broker import Broker
from tlab.features.context import Context, SessionPhase, SessionState, build_session_state
from tlab.journal.queries import open_entry_orders, recorded_trade_ids
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate, daily_loss_breached
from tlab.strategies.base import Strategy

log = logging.getLogger("tlab.runner")


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
        self.dry_run = dry_run

        # Kill-switch tetiklendiginde gunun geri kalaninda islem yok.
        # Tarihe bagli tutuluyor: ertesi gun otomatik sifirlanir.
        self._halted_on: date | None = None

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
        while True:
            try:
                log.info("%s", self.run_once().summary())
            except TradingLabError:
                log.exception("Tur basarisiz, dongu devam ediyor")
            except KeyboardInterrupt:
                log.info("Dongu elle durduruldu")
                raise
            except Exception:
                log.exception("Beklenmeyen hata, dongu devam ediyor")
            time.sleep(poll_seconds)

    def run_once(self) -> LoopResult:
        """Tek tur: mutabakat, kontroller, sembol degerlendirmesi."""
        now = self.clock.now()
        session = self._session_state(now)
        market_clock = self.broker.get_market_clock()
        result = LoopResult(now=now, phase=session.phase, market_open=market_clock.is_open)

        if not market_clock.is_open:
            result.notes.append("borsa kapali (tatil ya da seans disi)")
            return result

        account = self.broker.get_account()
        positions = {position.symbol: position for position in self.broker.get_positions()}

        result.trades_recorded = self._reconcile(session)

        if self._check_kill_switch(account, positions, session, result):
            return result

        if session.must_flatten:
            result.flattened = self._flatten_all(positions, ExitReason.EOD_FLATTEN)
            result.notes.append("gun sonu zorunlu kapanis")
            return result

        if not session.can_open_new_positions:
            return result

        self._evaluate_universe(session, account, positions, result)
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

        orders = open_entry_orders(self.conn)
        already = recorded_trade_ids(self.conn)
        recorded = 0

        for matched in pair_fills(fills, set(orders)):
            if matched.trade_id in already:
                continue
            info = orders.get(matched.entry.client_order_id)
            if info is None:
                continue
            trade = build_trade(matched, info, run_id=self.run_id, flatten_at=session.flatten_at)
            if self.writer.record_trade(trade):
                recorded += 1
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

    def _check_kill_switch(
        self,
        account: Account,
        positions: dict[str, Position],
        session: SessionState,
        result: LoopResult,
    ) -> bool:
        """Gunluk zarar siniri asildiysa gunu bitirir.

        Kotu bir gunu erken kapatmak, felakete donusmesini
        beklemekten iyidir. Karar yeniden acilmaz: gun sonuna kadar
        hicbir yeni pozisyon girilmez.
        """
        today = session.now.date()
        if self._halted_on == today:
            result.halted = True
            result.notes.append("gun kill-switch ile kapatildi")
            return True

        if not daily_loss_breached(account, self.config.risk):
            return False

        self._halted_on = today
        result.halted = True
        result.flattened = self._flatten_all(positions, ExitReason.KILL_SWITCH)
        result.notes.append(
            f"KILL-SWITCH: gunluk zarar %{account.daily_pl_pct:.2f}, "
            f"sinir %{self.config.risk.max_daily_loss_pct}"
        )
        log.warning("%s", result.notes[-1])
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

        closed = 0
        for symbol in positions:
            try:
                self.broker.cancel_open_orders(symbol)
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
        result: LoopResult,
    ) -> None:
        """Evrendeki her sembolu sirayla degerlendirir.

        Bir sembolun hatasi digerlerini etkilemez: veri gelmeyen bir
        hisse yuzunden tum seansi kaybetmek kabul edilemez.
        """
        for symbol in self.config.symbols:
            try:
                ctx = self._build_context(symbol, session, account, positions)
            except (DataError, BrokerError):
                log.exception("%s icin baglam kurulamadi", symbol)
                continue

            if ctx is None:
                continue
            result.evaluated += 1

            for strategy in self.strategies:
                intent = strategy.decide(ctx)
                if intent is None:
                    continue
                result.intents += 1
                self._handle_intent(intent, ctx, result)
                # Ayni sembolde ilk niyet degerlendirildikten sonra
                # digerlerine bakmiyoruz: pozisyon acildiysa ikinci
                # strateji ayni riske tekrar girerdi.
                break

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
        # dogurur; ikinci kez uretmek, journal'a gonderilenden farkli
        # bir kimlik yazar ve mutabakat o islemi bir daha bulamaz.
        order = BracketOrder.from_intent(intent, verdict.qty, EntryType.LIMIT)

        if self.dry_run:
            result.notes.append(f"[dry-run] {intent.symbol} {verdict.qty} adet")
            self.writer.record_decision(decision)
            return

        try:
            order_ref = self.broker.submit_bracket(order)
        except BrokerError:
            log.exception("%s emri gonderilemedi", intent.symbol)
            self.writer.record_decision(decision)
            return

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

        # Karar once yazilir: emir kaydi karara yabanci anahtarla bagli.
        decision = decision.model_copy(update={"order": order_ref})
        self.writer.record_decision(decision)
        self.writer.record_order(order, order_ref, decision.decision_id)

    def _build_context(
        self,
        symbol: str,
        session: SessionState,
        account: Account,
        positions: dict[str, Position],
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
