"""Backtest motoru.

Bu dosyanin en dikkat cekici ozelligi NE KADAR AZ SEY yaptigi.
Strateji, risk kapisi, emir uretimi, mutabakat ve journal kaydi -
hepsi canlida calisan kodun AYNISI. Motor yalnizca uc seyi
degistiriyor:

    canli                     backtest
    ---------------------     --------------------------
    AlpacaBroker         ->   SimBroker
    AlpacaMarketData     ->   CachedMarketData
    LiveClock            ->   SimClock

Ustteki hicbir katman bu degisimi gormuyor. "Tek beyin, uc kosum
takimi" ilkesinin tum anlami burada: backtest'te olculen sey,
canlida calisacak olanin ta kendisi. Ayri bir backtest motoru
yazilsaydi, olculen ile calisan arasindaki fark zamanla acilir ve
ogrenilen her sey dogrulanamaz hale gelirdi.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from tlab.backtest.metrics import Metrics, compute_metrics
from tlab.backtest.sim_broker import SimBroker, SimFillModel
from tlab.config import Config
from tlab.core.clock import SimClock
from tlab.core.types import Bar, Timeframe
from tlab.data.cached import CachedMarketData
from tlab.engine.runner import SessionRunner
from tlab.errors import DataError
from tlab.features.context import build_session_state
from tlab.journal.writer import JournalWriter, current_git_sha
from tlab.risk.gate import RiskGate
from tlab.strategies.base import Strategy

log = logging.getLogger("tlab.backtest")


@dataclass
class BacktestResult:
    """Bir backtest kosusunun sonucu."""

    run_id: str
    start: datetime
    end: datetime
    steps: int
    trading_days: int
    symbols: tuple[str, ...]
    starting_equity: float
    ending_equity: float
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    metrics: Metrics | None = None

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return (self.ending_equity - self.starting_equity) / self.starting_equity * 100

    def report(self) -> str:
        days = self.trading_days
        lines = [
            f"Backtest {self.run_id[:12]}",
            f"  aralik              : {self.start:%Y-%m-%d} - {self.end:%Y-%m-%d} ({days} gun)",
            f"  semboller           : {', '.join(self.symbols)}",
            f"  adim sayisi         : {self.steps:,}",
            f"  ozsermaye           : {self.starting_equity:,.2f} -> "
            f"{self.ending_equity:,.2f}  (%{self.total_return_pct:+.2f})",
        ]
        if self.metrics is not None:
            lines.append("")
            lines.append(self.metrics.report())
        return "\n".join(lines)


class Backtest:
    """Gecmis barlar uzerinde seans dongusunu isletir."""

    def __init__(
        self,
        *,
        config: Config,
        strategy: Strategy,
        market: CachedMarketData,
        conn: sqlite3.Connection,
        starting_equity: float = 100_000.0,
        fill_model: SimFillModel | None = None,
        timeframe: Timeframe = Timeframe.M1,
        opening_range_minutes: int = 15,
        history_days: int = 1,
        notes: str | None = None,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.market = market
        self.conn = conn
        self.starting_equity = starting_equity
        self.fill_model = fill_model or SimFillModel()
        self.timeframe = timeframe
        self.opening_range_minutes = opening_range_minutes
        self.history_days = history_days
        self.notes = notes

    def run(self, start: datetime, end: datetime) -> BacktestResult:
        """Verilen aralikta backtest calistirir."""
        symbols = tuple(self.config.symbols)
        if not symbols:
            msg = "Backtest icin en az bir sembol gerekli"
            raise DataError(msg)

        loaded = self.market.preload(list(symbols))
        if not any(loaded.values()):
            msg = (
                "Onbellekte bar verisi yok. Once 'tlab fetch' ile veri indir "
                f"(semboller: {', '.join(symbols)})"
            )
            raise DataError(msg)

        timeline = self._timeline(symbols, start, end)
        if not timeline:
            msg = f"{start:%Y-%m-%d} - {end:%Y-%m-%d} araliginda bar bulunamadi"
            raise DataError(msg)

        broker = SimBroker(starting_equity=self.starting_equity, fill_model=self.fill_model)
        clock = SimClock(timeline[0][0] + self.timeframe.duration)
        # Kotasyonlar simulasyon anina baglanir; aksi halde veri
        # setinin sonundaki fiyat okunur ve bu dogrudan gelecege
        # bakmaktir.
        self.market.bind_clock(clock)
        writer = JournalWriter(self.conn, clock)
        run_id = writer.start_run(
            mode="backtest",
            data_feed=self.config.data.feed,
            params_version=self.strategy.params_version,
            config=self.config.model_dump(mode="json"),
            git_sha=current_git_sha(self.config.root),
            notes=self.notes,
        )

        runner = SessionRunner(
            broker=broker,
            market=self.market,
            strategies=[self.strategy],
            gate=RiskGate(self.config.risk),
            writer=writer,
            conn=self.conn,
            config=self.config,
            clock=clock,
            run_id=run_id,
            opening_range_minutes=self.opening_range_minutes,
            timeframe=self.timeframe,
            history_days=self.history_days,
            entry_order_ttl_minutes=self.config.session.entry_order_ttl_minutes,
        )

        curve = self._drive(runner, broker, clock, timeline)
        writer.end_run(run_id)

        trading_days = len({moment.date() for moment, _ in timeline})
        return BacktestResult(
            run_id=run_id,
            start=timeline[0][0],
            end=timeline[-1][0],
            steps=len(timeline),
            trading_days=trading_days,
            symbols=symbols,
            starting_equity=self.starting_equity,
            ending_equity=broker.equity,
            equity_curve=curve,
            metrics=compute_metrics(self.conn, run_id, curve),
        )

    # ------------------------------------------------------------------
    # Ic isleyis
    # ------------------------------------------------------------------

    def _timeline(
        self, symbols: tuple[str, ...], start: datetime, end: datetime
    ) -> list[tuple[datetime, list[Bar]]]:
        """Aralikta bar bulunan anlari, o andaki barlarla birlikte verir.

        Zaman cizgisi VERIDEN turetiliyor, takvimden degil: tatil
        gunlerinde bar olmadigi icin o gunler kendiliginden atlaniyor.
        Boylece ayri bir tatil takvimi tutmak gerekmiyor - ve tutulan
        takvimin eskimesi gibi bir risk de olusmuyor.
        """
        grouped: dict[datetime, list[Bar]] = {}
        for symbol in symbols:
            for bar in self.market.bars(symbol, self.timeframe, start, end):
                grouped.setdefault(bar.ts, []).append(bar)
        return sorted(grouped.items())

    def _drive(
        self,
        runner: SessionRunner,
        broker: SimBroker,
        clock: SimClock,
        timeline: list[tuple[datetime, list[Bar]]],
    ) -> list[tuple[datetime, float]]:
        """Zaman cizgisini adim adim isletir."""
        curve: list[tuple[datetime, float]] = []
        current_day: date | None = None
        duration = self.timeframe.duration

        for bar_open, bars in timeline:
            # Karar ani, barin KAPANDIGI andir. Barin acilis zamanini
            # kullanmak, henuz olusmamis bir kapanisi bilmek olurdu.
            now = bar_open + duration
            clock.set(now)

            if now.date() != current_day:
                current_day = now.date()
                broker.start_day()

            session = build_session_state(
                now,
                exchange_timezone=self.config.app.exchange_timezone,
                regular_open=(
                    self.config.session.regular_open.hour,
                    self.config.session.regular_open.minute,
                ),
                regular_close=(
                    self.config.session.regular_close.hour,
                    self.config.session.regular_close.minute,
                ),
                flatten_before_close_minutes=(self.config.session.flatten_before_close_minutes),
                opening_range_minutes=self.opening_range_minutes,
            )
            broker.set_clock(
                is_open=session.session_open <= now < session.session_close,
                now=now,
                next_open=session.session_open,
                next_close=session.session_close,
            )

            for bar in bars:
                broker.advance(bar)

            runner.run_once()
            curve.append((now, broker.equity))

        return curve


def default_range(days: int = 30, *, today: datetime | None = None) -> tuple[datetime, datetime]:
    """Son `days` gunluk varsayilan aralik."""
    end = today or datetime.now(UTC)
    return end - timedelta(days=days), end
