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
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from tlab.backtest.metrics import Metrics, compute_metrics
from tlab.backtest.sim_broker import SimBroker, SimFillModel
from tlab.config import Config
from tlab.core.calendar import TradingSession
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


class CarriedPositionError(DataError):
    """Seans sinirinda acik pozisyon ya da emir kaldi.

    Sistem gun ici calisir; seans sinirindan pozisyon tasimak, olcumun
    stratejiyi degil gece boslugunu olctugu anlamina gelir. Resmi
    takvimle kosulan olcumde bu bir SONUC degil, gecersiz olcumdur.
    """


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
    carried_overnight: int = 0
    """Seans sinirina acik pozisyon/emirle gelinen gun sayisi.

    Resmi takvimle kosulan olcumde bu her zaman sifirdir (sifir
    degilse kosu hata verir). Takvimsiz kosuda sayilir ve rapora
    yazilir, cunku o gunlerin sonucu gece boslugunu icerir.
    """

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
        if self.carried_overnight:
            lines.append(
                f"  UYARI               : {self.carried_overnight} gun sinirinda acik "
                "pozisyon/emir kaldi; bu gunlerin sonucu gece boslugunu iceriyor"
            )
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
        sessions: Sequence[TradingSession] | None = None,
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
        self.sessions: tuple[TradingSession, ...] | None = (
            None if sessions is None else tuple(sorted(sessions, key=lambda item: item.open))
        )
        """RESMI seans saatleri. Verildiginde:

        * broker saati config'in sabit 16:00'i yerine bunlardan kurulur,
          yani yarim gunlerde kapanis 13:00'dir;
        * yalnizca seans ici barlar isletilir;
        * seans sinirinda ya da kosu sonunda acik pozisyon veya emir
          kalirsa kosu `CarriedPositionError` ile durur.
        """
        if self.sessions is not None and not self.sessions:
            msg = "resmi takvim verildi ama bos; hic seans yokken olcum yapilamaz"
            raise DataError(msg)
        self._opens = [item.open for item in self.sessions or ()]
        self._closes = [item.close for item in self.sessions or ()]
        self._zone = ZoneInfo(config.app.exchange_timezone)
        self.carried_overnight = 0

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

        self.carried_overnight = 0
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
            carried_overnight=self.carried_overnight,
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
                if self.sessions is not None and self._session_at(bar.ts) is None:
                    # Resmi takvim varken seans disi barlar isletilmez:
                    # emirlerimiz uzatilmis seansta dolamaz.
                    continue
                grouped.setdefault(bar.ts, []).append(bar)
        return sorted(grouped.items())

    def _session_at(self, moment: datetime) -> TradingSession | None:
        """`moment` resmi bir seansin icindeyse o seans."""
        sessions = self.sessions or ()
        index = bisect_right(self._opens, moment) - 1
        if index >= 0 and sessions[index].contains(moment):
            return sessions[index]
        return None

    def _official_clock(self, now: datetime) -> tuple[bool, datetime, datetime]:
        """Resmi takvime gore (acik mi, sonraki acilis, sonraki kapanis).

        Alpaca saatinin anlamiyla ayni: seans aciksa `next_close`
        bugunun kapanisi, `next_open` bir sonraki seansin acilisi;
        kapaliysa ikisi de gelecek seansa aittir.
        """
        sessions = self.sessions or ()
        index = bisect_right(self._closes, now)
        if index >= len(sessions):
            last = sessions[-1]
            return False, last.open, last.close
        current = sessions[index]
        if current.open <= now:
            upcoming = sessions[index + 1] if index + 1 < len(sessions) else current
            return True, upcoming.open, current.close
        return False, current.open, current.close

    def _check_boundary(self, broker: SimBroker, where: str) -> None:
        """Seans sinirinda acik pozisyon ya da emir var mi."""
        positions = sorted(position.symbol for position in broker.get_positions())
        orders = sorted({order.symbol for order in broker.list_open_orders()})
        if not positions and not orders:
            return
        detail = f"{where}: acik pozisyon {positions}, acik emir {orders}"
        if self.sessions is not None:
            msg = (
                f"{detail}. Gun ici sistem seans sinirindan pozisyon tasimaz; "
                "cogu zaman kapanis oncesi barlar eksik oldugu icin gun sonu "
                "kapatmasi dolamadi. Olcum gecersiz, rapor uretilmedi."
            )
            raise CarriedPositionError(msg)
        self.carried_overnight += 1
        log.warning("%s - bu gunun sonucu gece boslugunu iceriyor", detail)

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

            # Gun, UTC'ye gore degil BORSA takvimine gore degisir.
            day = bar_open.astimezone(self._zone).date()
            if day != current_day:
                if current_day is not None:
                    self._check_boundary(broker, f"{current_day} -> {day}")
                current_day = day
                broker.start_day()

            if self.sessions is not None:
                is_open, next_open, next_close = self._official_clock(now)
                broker.set_clock(
                    is_open=is_open, now=now, next_open=next_open, next_close=next_close
                )
            else:
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

        if self.sessions is not None and current_day is not None:
            self._check_boundary(broker, f"{current_day} kosu sonu")
        return curve


def default_range(days: int = 30, *, today: datetime | None = None) -> tuple[datetime, datetime]:
    """Son `days` gunluk varsayilan aralik."""
    end = today or datetime.now(UTC)
    return end - timedelta(days=days), end
