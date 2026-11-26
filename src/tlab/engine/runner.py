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
from datetime import UTC, date, datetime, timedelta
from enum import Enum

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
from tlab.features.context import (
    Context,
    SessionPhase,
    SessionState,
    apply_market_close,
    build_session_state,
)
from tlab.features.indicators import opening_window_gaps
from tlab.journal.queries import (
    halt_reason,
    open_entry_orders,
    orders_submitted_since,
    orders_with_status,
    unconfirmed_orders,
)
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate, daily_loss_breached
from tlab.strategies.base import Strategy

log = logging.getLogger("tlab.runner")

MAX_BACKOFF_FACTOR = 8
"""Ardisik hatalarda beklemenin en fazla kac katina cikacagi."""


TERMINAL_ORDER_STATUSES = frozenset({"filled", "canceled", "expired", "rejected"})
"""Brokerda bir daha degismeyecek emir durumlari (Alpaca degerleri)."""

CANCEL_REQUESTED = "cancel_requested"
"""Journal durumu: iptal niyeti yazildi; brokera gidip gitmedigi bilinmiyor.

Iptal cagrisindan ONCE yazilir (write-ahead). Yeniden baslayan surec bu
satirdaki iptali yeniden gonderir: ilk istek hic gitmemis olabilir.
"""

CANCEL_PENDING = "cancel_pending"
"""Journal durumu: broker iptali ALDI (cagri hatasiz dondu ya da emir
`pending_cancel`/terminal goruldu); giris henuz terminal durumda degil."""

CANCEL_ACK_STATUSES = frozenset({"pending_cancel"}) | TERMINAL_ORDER_STATUSES
"""Iptal isteginin brokera ulastigini gosteren emir durumlari."""

PROTECTIVE_STATUSES = frozenset({"new", "partially_filled"})
"""Koruma KANITI sayilan cikis emri durumlari (pozitif liste).

Listede olmayan her durum koruma sayilmaz ve bekleme tanimaz:
  * `pending_cancel`, `pending_replace`: emir gidiyor ya da degisiyor
    (Codex #63/7115896065, 7116120239);
  * `accepted`, `pending_new`, `accepted_for_bidding`: borsaya henuz
    iletilmedi ya da kabul edilmedi; sonradan `rejected` olabilir
    (Codex #63/7139373707);
  * `held`: Alpaca bracket bacaklari ebeveyn tamamen dolunca etkinlesir;
    tam dolumdan sonra `held` gorunen stopun calistigi dogrulanmadi;
  * bilinmeyen her durum.
Bekleme sayaci tutulmaz: boyle bir sayac okuma hatasiyla ya da yeniden
baslatmayla uzayabilir (Codex #63/7154998289). Korumasi kanitlanmayan dolum
gunu hemen kapatir; gun karari kalicidir (unattended-paper.md §4).
"""

MAX_CANCEL_ATTEMPTS = 3
"""Ulasamayan iptal icin surec basina en fazla deneme (ilk gonderim dahil).
Girisin okunamadigi tur da, bir sey gonderilmese bile, denemeye sayilir.
Asilirsa gun kill-switch ile kapanir; `_flatten_all` her turda butun
emirleri iptal edip kapatmayi yeniden dener."""


class CancelOutcome(Enum):
    """Bayat giris iptalinin, girisin kendi terminal durumundan cikan sonucu."""

    CANCELED = "canceled"
    PENDING = "pending"
    FILLED = "filled"
    UNPROTECTED = "unprotected"


@dataclass(frozen=True)
class TrackedCancel:
    """Iptali istenmis, sonucu cozulene kadar izlenen giris emri."""

    broker_order_id: str
    client_order_id: str
    symbol: str
    side: Side | None = None
    """Girisin journal'daki yonu; giris brokerdan okunamadiginda kullanilir."""
    submitted_at: datetime | None = None
    """Girisin gonderildigi an; hangi seansa ait oldugunu soyler."""


def journal_side(value: object) -> Side | None:
    """Journal metnini yone cevirir; taninmiyorsa None."""
    try:
        return Side(str(value))
    except ValueError:
        return None


def journal_instant(value: object) -> datetime | None:
    """Journal'daki UTC ISO metnini ana cevirir; okunamiyorsa None."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def may_still_execute(order: OrderRef, exit_side: Side) -> bool:
    """Cikis yonunde ve hala gerceklesebilir mi: terminal degilse evet.

    Koruma kanitindan ayri bir sorudur: `pending_cancel`, `held` ya da
    bilinmeyen durumdaki emir koruma sayilmaz ama dolabilir.
    """
    return order.side is exit_side and order.status not in TERMINAL_ORDER_STATUSES


def stops_cover(exit_side: Side, qty: float, orders: list[OrderRef]) -> bool:
    """Cikis yonunde, koruma kaniti olan stop emirleri `qty` miktari kapsiyor mu.

    Kalan miktari bilinmeyen emir ve `PROTECTIVE_STATUSES` disindaki her
    durum kapsam saymaz (fail-closed).
    """
    covered = sum(
        order.remaining_qty or 0.0
        for order in orders
        if order.side is exit_side
        and order.status in PROTECTIVE_STATUSES
        and order.stop_price is not None
    )
    return covered >= qty


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
    entries_blocked: bool = False
    """Gun durumu bilinmiyor: yeni giris yok, koruma ve kapanis surer."""
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
        self._gap_noted: set[tuple[str, str]] = set()
        """(seans acilisi, sembol): eksik acilis bari notu yazilmis olanlar."""
        self._pending_cancels: dict[str, TrackedCancel] = {}
        """Iptali istenmis ama terminal durumu gorulmemis girisler.

        Journal'da `cancel_pending` olarak da yazilir; yeniden baslayan
        surec izlemeyi oradan devralir.
        """
        self._unconfirmed_cancels: set[str] = set()
        self._adopted_cancels: set[str] = set()
        """Bu surecin journal'dan `cancel_requested` olarak devraldigi iptaller.
        Yalniz istek dogrulanmamisken sorulur (`_confirm_cancel`). Deneme
        sayaci surec bellegindedir; devralinan istek yeni bir sayac almaz:
        giris okunamazsa ya da tek yeniden gonderim ulasmazsa gun o turda
        kapanir (Codex #63/7168523270)."""
        """Iptali gonderilen ama brokerin aldigi dogrulanmamis girisler."""
        self._cancel_attempts: dict[str, int] = {}
        """Giris basina bu surecte yapilan iptal gonderimi sayisi."""
        self._cancels_seen_this_turn: set[str] = set()
        """Bu turun basinda izlemede olan girisler (cozulen ya da suren).
        Turun basindaki acik emir listesi onlari hala gosterebilir; bayat
        iptal yolu onlara yeni iptal gondermemeli."""
        self._unpersisted_halts: dict[date, str] = {}
        """Kalici yazilamamis kill-switch kararlari (gun -> sebep).

        Yazma hatasi karari unutturmamali: bu surec gunu kapali bilir
        ve yazmayi her turda yeniden dener. Surec yeniden baslarsa bu
        bellek kaybolur; kabul sinirlari unattended-paper.md §4'te.
        """

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
            session = apply_market_close(
                session,
                market_clock.next_close,
                flatten_before_close_minutes=self.config.session.flatten_before_close_minutes,
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

        # Onceki turlarda istenmis iptaller once cozulur: pozisyon
        # gorunse bile. Gec gorunen dolum koruma kontrolunden dusmemeli.
        if not self._resolve_pending_cancels(positions, session, result):
            return result

        if open_orders is None:
            # Bekleyen emirleri bilmeden giris yapmak, dolmayi
            # bekleyen bir emrin uzerine ikincisini gondermek demek.
            result.notes.append("bekleyen emirler bilinmiyor, yeni giris yapilmadi")
            return result

        if not self._cancel_stale_entries(
            open_orders, positions, session, result, every_age=result.entries_blocked
        ):
            return result

        if not session.can_open_new_positions:
            return result

        if result.entries_blocked:
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
            # Iptal izlemesindeki satir ezilmez: iz ayni sutunda durur ve
            # yeni surec onu oradan devralir.
            self.writer.mark_order_closed(
                matched.entry.client_order_id, unless=(CANCEL_REQUESTED, CANCEL_PENDING)
            )
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
        result: LoopResult,
        *,
        every_age: bool = False,
    ) -> bool:
        """Dolmayan giris emirlerini belirli sure sonra iptal eder.

        Korumasiz dolum yuzunden gun kapandiysa False doner.

        Kirilim sinyali zamana baglidir: on dakika once gecerli olan
        bir giris fiyati artik gecerli degildir. Emri gun boyu asili
        birakmak, sinyalin ilgisiz kaldigi bir anda dolmasina yol
        acar. Yalnizca bizim gonderdigimiz girisler, yalnizca kendi
        kimlikleriyle ve yalnizca acik pozisyonu olmayan sembollerde
        iptal edilir; koruma bacaklari hicbir zaman iptal cagrisina
        girmez. Izlemedeki girise ikinci iptal gonderilmez.

        `every_age`: gun durumu bilinmiyorken (`entries_blocked`) yasina
        bakmadan butun bekleyen girisler iptal edilir; yeni giris yoksa
        eski giris de dolmamali. Pozisyonu olan semboller yine disarida:
        kismen dolmus girisin kalan miktari bekler, o miktar risk
        kapisindan gecmis ilk emrin parcasidir (unattended-paper.md §4).
        """
        if self.dry_run:
            return True

        ours = open_entry_orders(self.conn)
        deadline = session.now - timedelta(minutes=self.entry_order_ttl_minutes)

        for order in open_orders:
            if order.symbol in positions or order.client_order_id not in ours:
                continue
            if order.client_order_id in self._cancels_seen_this_turn:
                # Izlemedeki (ya da bu turda cozulen) girise ikinci iptal yok.
                continue
            if not every_age and order.submitted_at.astimezone(UTC) >= deadline:
                continue
            tracked = TrackedCancel(
                broker_order_id=order.broker_order_id,
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=journal_side(ours[order.client_order_id].get("side")),
                submitted_at=order.submitted_at,
            )
            # Write-ahead: niyet kalici yazilmadan iptal gonderilmez.
            # Aksi halde iptal ile kayit arasinda yeniden baslayan surec
            # iptali ve olasi dolumu hic gormez (Codex #63/6863854867).
            try:
                self.writer.update_order_status(order.client_order_id, CANCEL_REQUESTED)
            except JournalError:
                log.exception("%s iptal niyeti yazilamadi; iptal gonderilmedi", order.symbol)
                self._block_entries(
                    result, f"{order.symbol} iptal niyeti yazilamadi; iptal gonderilmedi"
                )
                continue
            self._send_cancel(tracked)
            if not self._settle_cancel(tracked, positions, session, result):
                return False
        return True

    def _send_cancel(self, item: TrackedCancel) -> None:
        """Iptali girisin kimligine gonderir; ulastiysa `cancel_pending` yazar.

        Hata, istegin brokera ulasmadigi ya da cevabin kayboldugu
        anlamina gelebilir. Ikisi ayirt edilemedigi icin satir
        `cancel_requested` kalir ve sonraki tur emrin durumunu okuyarak
        karar verir (`_confirm_cancel`). Basari ise brokerin istegi
        aldiginin kanitidir.
        """
        cid = item.client_order_id
        self._cancel_attempts[cid] = self._cancel_attempts.get(cid, 0) + 1
        try:
            self.broker.cancel_order(item.broker_order_id)
        except BrokerError:
            log.exception("%s giris emri iptal edilemedi (%s)", item.symbol, item.broker_order_id)
            self._unconfirmed_cancels.add(cid)
            return
        self._mark_cancel_confirmed(item)

    def _mark_cancel_confirmed(self, item: TrackedCancel) -> None:
        self._unconfirmed_cancels.discard(item.client_order_id)
        self._write_order_status(item, CANCEL_PENDING)

    def _confirm_cancel(self, item: TrackedCancel) -> bool:
        """Dogrulanmamis iptali uzlastirir; deneme hakki bittiyse False.

        Emir `pending_cancel` ya da terminal ise istek ulasmistir: yeni
        iptal gonderilmez. Hala aktifse ayni giris kimligine yeniden
        gonderilir (en fazla MAX_CANCEL_ATTEMPTS). Emir okunamazsa bu
        turda bir sey gonderilmez, ama tur denemeye sayilir: sinir okuma
        hatasiyla suresiz uzamamali. Hak bitince gun kapanir ve hesap
        genelindeki iptal bayat girisi de kapsar.

        Journal'dan devralinan istekte sinir surecler arasidir: sayac surec
        bellegindedir ve yeniden baslatma onu sifirlar. Bu yuzden devralinan
        istek tek bir firsat alir. Giris okunamiyorsa ya da tek yeniden
        gonderim de ulasmazsa gun O TURDA kapanir; boylece yeniden baslatma
        sureyi uzatamaz (Codex #63/7168523270).
        """
        cid = item.client_order_id
        try:
            order = self.broker.get_order(item.broker_order_id)
        except BrokerError:
            log.exception("%s giris emri okunamadi (%s)", item.symbol, item.broker_order_id)
            attempts = self._cancel_attempts.get(cid, 0)
            if cid in self._adopted_cancels or attempts >= MAX_CANCEL_ATTEMPTS:
                return False
            self._cancel_attempts[cid] = attempts + 1
            return True
        if order.status in CANCEL_ACK_STATUSES:
            self._mark_cancel_confirmed(item)
            return True
        if self._cancel_attempts.get(item.client_order_id, 0) >= MAX_CANCEL_ATTEMPTS:
            return False
        self._send_cancel(item)
        # Devralinan istek yeniden gonderildi ve yine dogrulanmadiysa bekleme yok.
        return not (cid in self._adopted_cancels and cid in self._unconfirmed_cancels)

    def _resolve_pending_cancels(
        self, positions: dict[str, Position], session: SessionState, result: LoopResult
    ) -> bool:
        """Bellekte ve journal'da izlenen iptalleri cozer.

        `cancel_requested` (bellekte ya da journal'da) iptalin brokera
        ulastigi dogrulanmamis demektir: once emrin durumu okunur, ulasmissa
        yeni istek gitmez, hala aktifse ayni girisin kimligine sinirli
        sayida yeniden gonderilir (`_confirm_cancel`). Deneme hakki biterse
        gun kapanir. `cancel_pending` satirina ikinci iptal gitmez.

        Korumasiz dolum yuzunden gun kapandiysa False doner.
        """
        self._cancels_seen_this_turn = set()
        if self.dry_run:
            return True
        tracked = dict(self._pending_cancels)
        try:
            rows = orders_with_status(self.conn, CANCEL_REQUESTED, CANCEL_PENDING)
        except JournalError:
            log.exception("Izlenen iptaller journal'dan okunamadi")
            self._block_entries(result, "izlenen iptaller journal'dan okunamadi")
            rows = []
        for row in rows:
            client_order_id = str(row["client_order_id"])
            if row["broker_order_id"] is None or client_order_id in tracked:
                continue
            tracked[client_order_id] = TrackedCancel(
                broker_order_id=str(row["broker_order_id"]),
                client_order_id=client_order_id,
                symbol=str(row["symbol"]),
                side=journal_side(row["side"]),
                submitted_at=journal_instant(row["submitted_at"]),
            )
            if row["status"] == CANCEL_REQUESTED:
                self._unconfirmed_cancels.add(client_order_id)
                # Bu surecin baslatmadigi cozumsuz istek: kor tur hakki yok.
                self._adopted_cancels.add(client_order_id)
        self._cancels_seen_this_turn = set(tracked)
        for item in tracked.values():
            if item.client_order_id in self._unconfirmed_cancels and not self._confirm_cancel(item):
                self._halt_day(
                    f"iptal iletilemedi: {item.symbol} ({MAX_CANCEL_ATTEMPTS} deneme)",
                    positions,
                    session,
                    result,
                )
                return False
            if not self._settle_cancel(item, positions, session, result):
                return False
        return True

    def _settle_cancel(
        self,
        item: TrackedCancel,
        positions: dict[str, Position],
        session: SessionState,
        result: LoopResult,
    ) -> bool:
        """Iptalin sonucunu uygular; gun kapandiysa False doner."""
        outcome = self._cancel_outcome(item, positions, session)
        if outcome is CancelOutcome.PENDING:
            self._pending_cancels[item.client_order_id] = item
            # Dogrulanmamis iptal `cancel_requested` kalir; bu ayrim
            # PENDING cozumunde silinmemeli (Codex #63/6993997992).
            if item.client_order_id not in self._unconfirmed_cancels:
                self._write_order_status(item, CANCEL_PENDING)
            self._block_entries(result, f"{item.symbol} giris iptali kesinlesmedi")
            return True

        self._pending_cancels.pop(item.client_order_id, None)
        self._unconfirmed_cancels.discard(item.client_order_id)
        self._adopted_cancels.discard(item.client_order_id)
        self._cancel_attempts.pop(item.client_order_id, None)
        if outcome is CancelOutcome.CANCELED:
            self._write_order_status(item, "canceled")
            result.cancelled += 1
            log.info("Bayat giris emri iptal edildi: %s", item.symbol)
            return True
        if outcome is CancelOutcome.FILLED:
            self._write_order_status(item, "filled")
            log.warning("%s girisi iptal sirasinda doldu; stop bacagi kapsiyor", item.symbol)
            result.notes.append(
                f"{item.symbol} girisi iptal sirasinda doldu; stop bacagi dolumu kapsiyor"
            )
            return True
        # Korumasiz dolum: durum degistirilmez (giris kesinlesmemis
        # olabilir). Gun karari kalici; kapatma her turda yeniden denenir.
        self._halt_unprotected(item.symbol, positions, session, result)
        return False

    def _cancel_outcome(
        self, item: TrackedCancel, positions: dict[str, Position], session: SessionState
    ) -> CancelOutcome:
        """Iptalin sonucunu girisin KENDI durumundan cikarir.

        Iptal isteginin kabulu ya da girisin acik listeden kaybolmasi
        sonuc degildir: iptal asenkron kesinlesir ve giris iki okuma
        arasinda dolabilir (Codex #63/6840456161). Iki soru ayri
        cevaplanir (Codex #63/6844629736):
          * iptal kesinlesti mi: `get_order` durumu terminal mi;
          * dolan miktar korunuyor mu: dolum varsa, terminal olsun ya da
            olmasin, HEMEN kontrol edilir.
        Sonuc:
          * giris okunamiyor: dolum bilinmez, ama sembolde gorunen
            pozisyonun korumasi yine olculur (`_outcome_without_entry`);
          * terminal, dolum sifir -> CANCELED;
          * terminal degil, dolum sifir -> PENDING;
          * dolum sifir ya da bilinmiyor: iz kapanmadan once sembolun
            pozisyonu GUNCEL okumayla uzlastirilir (`_current_position`),
            cunku brokerin dolum bilgisi bayat olabilir ve pozisyon tur
            icinde sonradan gorunebilir. Pozisyon varsa korumasi olculur,
            kanitlanamazsa UNPROTECTED. Pozisyon bilinmiyorsa (okuma hata
            verdi, tur basi goruntusu de bos) duz hesap kanitlanmamistir:
            PENDING, iz kapanmaz (Codex #63/7168523270);
          * dolum var (ya da terminal ve dolum bilinmiyor): stop
            bacaklari `max(dolum, pozisyon)` miktarini kapsamiyorsa ya
            da durum okunamiyorsa UNPROTECTED; kapsiyorsa terminalde
            FILLED, degilse PENDING. PENDING her turda yeniden
            degerlendirildigi icin dolum arttikca kapsam yeniden olculur.
        Koruma icin bekleme yoktur; gecis durumundaki stop da korumasizdir
        (`PROTECTIVE_STATUSES`).
        """
        try:
            order = self.broker.get_order(item.broker_order_id)
        except BrokerError:
            log.exception("%s giris emri okunamadi (%s)", item.symbol, item.broker_order_id)
            return self._outcome_without_entry(item, positions, session)
        unconfirmed = item.client_order_id in self._unconfirmed_cancels
        if unconfirmed and order.status in CANCEL_ACK_STATUSES:
            # Giris `pending_cancel` ya da terminal okundu: iptal isteginin
            # akibeti artik belirsiz degil (broker reddetmis olsa bile emir
            # bitmis). Satir `cancel_requested` kalirsa yeni surec onu
            # cozumsuz istek diye devralir ve tek okuma hatasinda gunu kapatir.
            self._mark_cancel_confirmed(item)
        terminal = order.status in TERMINAL_ORDER_STATUSES
        if order.filled_qty == 0 or (not terminal and order.filled_qty is None):
            position, known = self._current_position(item.symbol, positions)
            if position is not None and not self._position_is_covered(item.symbol, position):
                return CancelOutcome.UNPROTECTED
            if not known:
                return CancelOutcome.PENDING
            return CancelOutcome.CANCELED if terminal else CancelOutcome.PENDING
        if not self._fill_is_protected(item, order, session):
            return CancelOutcome.UNPROTECTED
        return CancelOutcome.FILLED if terminal else CancelOutcome.PENDING

    def _current_position(
        self, symbol: str, positions: dict[str, Position]
    ) -> tuple[Position | None, bool]:
        """Sembolun pozisyonu ve bu bilginin kanitli olup olmadigi.

        Once guncel okuma. Okuma hata verirse tur basindaki goruntuye
        dusulur: sembol oradaysa pozisyon vardir. Orada da yoksa pozisyon
        BILINMIYOR demektir (`None, False`); duz hesap kanitlanmis sayilmaz.
        """
        try:
            current = next((p for p in self.broker.get_positions() if p.symbol == symbol), None)
        except BrokerError:
            log.exception("%s pozisyonu okunamadi; tur basi goruntusu kullaniliyor", symbol)
            seen = positions.get(symbol)
            return seen, seen is not None
        return current, True

    def _outcome_without_entry(
        self, item: TrackedCancel, positions: dict[str, Position], session: SessionState
    ) -> CancelOutcome:
        """Giris okunamiyorken sembolun gorunen durumundan sonuc cikarir.

        Dolum miktari bilinmez. Ama girisin okunamamasi, daha once gorulmus
        ya da yeni olusmus korumasiz bir pozisyonu gizlememeli (Codex
        #63/7154998289):
          * pozisyon goruluyor: korumasi olculur; kanitlanamazsa
            UNPROTECTED, kapsaniyorsa PENDING;
          * pozisyon yok ya da bilinmiyor ve journal girisi ONCEKI seanstan
            gosteriyor: sembolde hala gerceklesebilecek bir cikis emri
            goruluyorsa sahipsizdir; dolarsa ters pozisyon acar.
            UNPROTECTED: gun kapanir, hesap genelindeki iptal emri de
            kapsar (Codex #63/7168523270). Ayni seansin girisinde bu
            kontrol yapilmaz: kendi bekleyen bacaklari sahipsiz degildir.
            Journal'daki gonderim ani okunamiyorsa seans kanitlanamaz:
            giris onceki seanstan sayilir (fail-closed).
        Diger her durumda PENDING: izleme ve giris engeli surer.
        """
        position, _known = self._current_position(item.symbol, positions)
        if position is not None:
            if self._position_is_covered(item.symbol, position):
                return CancelOutcome.PENDING
            return CancelOutcome.UNPROTECTED
        same_session = (
            item.submitted_at is not None
            and item.submitted_at.astimezone(UTC) >= session.session_open
        )
        if same_session:
            return CancelOutcome.PENDING
        try:
            symbol_orders = [o for o in self.broker.list_open_orders() if o.symbol == item.symbol]
        except BrokerError:
            # Hesap duz, sahipsiz emir kaniti yok; giris engeli zaten suruyor.
            log.exception("%s acik emirleri okunamadi", item.symbol)
            return CancelOutcome.PENDING
        if self._has_orphan_exit(item, item.side, symbol_orders):
            return CancelOutcome.UNPROTECTED
        return CancelOutcome.PENDING

    def _position_is_covered(self, symbol: str, position: Position) -> bool:
        """Gorunen pozisyonu koruma kaniti olan stoplar kapsiyor mu.

        Acik emirler okunamazsa koruma kanitlanamaz: False (fail-closed).
        """
        try:
            symbol_orders = [o for o in self.broker.list_open_orders() if o.symbol == symbol]
        except BrokerError:
            log.exception("%s acik emirleri okunamadi", symbol)
            return False
        exit_side = Side.SELL if position.side is Side.BUY else Side.BUY
        return stops_cover(exit_side, position.qty, symbol_orders)

    def _fill_is_protected(
        self, item: TrackedCancel, order: OrderRef, session: SessionState
    ) -> bool:
        """Dolan miktari stop bacaklari kapsiyor mu; okunamazsa False.

        Ayni seansta gereken miktar `max(dolum, pozisyon)`: pozisyon
        okumasi dolumu henuz gostermiyor olabilir. Giris onceki bir
        seanstansa bu gecikme mumkun degil; tutulan miktar brokerdaki
        pozisyondur. Pozisyon yoksa hesap duz dogrulanmistir (Codex
        #63/6993997992); varsa normal kapsam kontrolu yapilir.
        """
        try:
            position = next(
                (p for p in self.broker.get_positions() if p.symbol == item.symbol), None
            )
            symbol_orders = [o for o in self.broker.list_open_orders() if o.symbol == item.symbol]
        except BrokerError:
            log.exception("%s dolum sonrasi broker durumu okunamadi", item.symbol)
            return False

        same_session = order.submitted_at.astimezone(UTC) >= session.session_open
        held = position.qty if position else 0.0
        if not same_session and held == 0:
            # Duz hesap ancak sembolde etkin cikis emri de yoksa dogrulanir.
            # Kalan bir stop ya da hedef dolarsa ters pozisyon acar; sahipligi
            # kimlikle kanitlanamadigi icin gun kapanir ve `_flatten_all`
            # butun emirleri iptal eder (Codex #63/7115896065).
            return not self._has_orphan_exit(item, order.side, symbol_orders)
        filled = (order.filled_qty or 0.0) if same_session else 0.0
        required = max(filled, held)
        entry_side = position.side if position else order.side
        if required <= 0 or entry_side is None:
            return False
        exit_side = Side.SELL if entry_side is Side.BUY else Side.BUY
        return stops_cover(exit_side, required, symbol_orders)

    @staticmethod
    def _has_orphan_exit(
        item: TrackedCancel, entry_side: Side | None, orders: list[OrderRef]
    ) -> bool:
        """Pozisyon yokken sembolde hala gerceklesebilecek bir cikis emri var mi."""
        if entry_side is None:
            # Yon bilinmiyorsa girisin kendisi disindaki her terminal olmayan
            # emir sayilir.
            return any(
                o.broker_order_id != item.broker_order_id
                and o.status not in TERMINAL_ORDER_STATUSES
                for o in orders
            )
        exit_side = Side.SELL if entry_side is Side.BUY else Side.BUY
        return any(may_still_execute(o, exit_side) for o in orders)

    def _write_order_status(self, item: TrackedCancel, status: str) -> None:
        """Durumu journal'a yazar; yazilamazsa izleme bellekte surer."""
        try:
            self.writer.update_order_status(item.client_order_id, status)
        except JournalError:
            log.exception("%s emir durumu yazilamadi (%s)", item.symbol, status)

    def _halt_unprotected(
        self,
        symbol: str,
        positions: dict[str, Position],
        session: SessionState,
        result: LoopResult,
    ) -> None:
        """Korumasi dogrulanamayan dolum: gun kill-switch ile kapanir.

        Tek sembolu kapatmak yetmezdi: kapatma, iptal kesinlesmeden
        gonderilemez ve bu sembol sonraki turlarda bu yoldan gecmez.
        Kalici gun karari ise her turda `_flatten_all`'u yeniden dener.
        """
        reason = f"koruma dogrulanamadi: {symbol} girisi iptal sirasinda doldu"
        self._halt_day(reason, positions, session, result)

    def _halt_day(
        self,
        reason: str,
        positions: dict[str, Position],
        session: SessionState,
        result: LoopResult,
    ) -> None:
        self._record_halt(session.now.date(), reason, result)
        result.halted = True
        result.flattened = self._flatten_all(positions, ExitReason.KILL_SWITCH)
        result.notes.append(f"KILL-SWITCH: {reason}")
        log.warning("KILL-SWITCH: %s", reason)

    def _check_kill_switch(
        self,
        account: Account,
        positions: dict[str, Position],
        session: SessionState,
        result: LoopResult,
    ) -> bool:
        """Gunluk zarar siniri asildiysa ya da gun belirsizse gunu bitirir.

        Kotu bir gunu erken kapatmak, felakete donusmesini
        beklemekten iyidir. Karar VERITABANINA yaziliyor, bellege
        degil: bellekteki bir bayrak sureci asmaz ve systemd
        yeniden baslattiginda sistem gunu kapatmis oldugunu unutup
        tekrar islem acardi.

        Gun durumu okunamazsa tur burada BITMEZ: yeni giris yapilmaz
        (`entries_blocked`) ama gun sonu kapanisi ve emir iptali
        surer. Okuma hatasi korumayi kesmemeli (Codex #61/6694382019).
        """
        today = session.now.date()
        unpersisted = self._unpersisted_halts.get(today)
        if unpersisted is not None:
            # Onceki turda karar verildi ama yazilamadi: gun bu surec
            # icin kapali kalir; kalici yazma yeniden denenir.
            self._record_halt(today, unpersisted, result)
            result.halted = True
            result.notes.append(f"gun kapali: {unpersisted}")
            result.flattened = self._flatten_all(positions, ExitReason.KILL_SWITCH)
            return True

        try:
            existing = halt_reason(self.conn, today)
        except (sqlite3.Error, JournalError):
            log.exception("Gun durumu okunamadi; yeni giris yok, koruma ve kapanis suruyor")
            self._block_entries(result, "gun durumu okunamadi")
            existing = None
            readable = False
        else:
            readable = True

        if existing is not None:
            result.halted = True
            result.notes.append(f"gun kapali: {existing}")
            result.flattened = self._flatten_all(positions, ExitReason.KILL_SWITCH)
            return True

        reason: str | None = None
        if daily_loss_breached(account, self.config.risk):
            reason = (
                f"gunluk zarar %{account.daily_pl_pct:.2f}, "
                f"sinir %{self.config.risk.max_daily_loss_pct}"
            )
        elif readable:
            reason = self._unexplained_day(session, result)
        if reason is None:
            return False

        self._record_halt(today, reason, result)
        result.halted = True
        result.flattened = self._flatten_all(positions, ExitReason.KILL_SWITCH)
        result.notes.append(f"KILL-SWITCH: {reason}")
        log.warning("KILL-SWITCH: %s", reason)
        return True

    def _unexplained_day(self, session: SessionState, result: LoopResult) -> str | None:
        """Journal bu gunu hic bilmiyor ama brokerda bugun dolum var mi?

        Her gun temiz baslayan bir ortamda yeniden baslatilan surec,
        onceki surecin kill-switch kararini goremez; zarar kapanista
        sinirin hemen ustunde gerceklestiyse hesaptan da tureyemez.
        Bu gune ait gonderilmis emir kaydi yokken brokerda bugun
        gerceklesme varsa gun BELIRSIZ sayilir ve kapatilir
        (fail-closed). Ayni surec kendi emirlerini gondermeden once
        yazdigi icin normal gunde bu kural tetiklenmez.
        """
        try:
            if orders_submitted_since(self.conn, session.session_open) > 0:
                return None
        except JournalError:
            log.exception("Bugunku emir kayitlari okunamadi; yeni giris yok")
            self._block_entries(result, "bugunku emir kayitlari okunamadi")
            return None
        try:
            fills = self.broker.list_fills(session.session_open)
        except BrokerError:
            log.exception("Bugunku gerceklesmeler okunamadi; yeni giris yok")
            self._block_entries(result, "bugunku gerceklesmeler okunamadi")
            return None
        if not fills:
            return None
        return (
            f"gun belirsiz: journal'da bugune ait emir yok, brokerda bugun "
            f"{len(fills)} gerceklesme var"
        )

    def _record_halt(self, today: date, reason: str, result: LoopResult) -> None:
        """Karari kalici yazar; yazilamazsa bellekte tutar ve sonra yeniden dener.

        Kapatma yazmayi beklemez. Yazilamayan karar bu surecte kaybolmaz:
        `_unpersisted_halts` sonraki turlarda gunu kapali tutar.
        """
        try:
            self.writer.record_halt(today, reason, self.run_id)
        except JournalError:
            log.exception("Kill-switch karari yazilamadi; gun bellekte kapali, yeniden denenecek")
            self._unpersisted_halts[today] = reason
            result.notes.append("kill-switch karari journal'a yazilamadi")
            return
        self._unpersisted_halts.pop(today, None)

    @staticmethod
    def _block_entries(result: LoopResult, why: str) -> None:
        result.entries_blocked = True
        result.notes.append(f"{why}; yeni giris yok, koruma ve kapanis suruyor")

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
            self._note_opening_gaps(ctx, result)

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
            timeframe=self.timeframe,
        )

    def _note_opening_gaps(self, ctx: Context, result: LoopResult) -> None:
        """Acilis penceresinde eksik bar varsa sembol ve gun basina BIR KEZ yazar.

        ORB, pencere o anda eksikse aralik kurmaz ve o turda islem acmaz
        (AGENTS §11.4). Eksik bar sonradan gelirse pencere tamamlanir ve
        normal degerlendirme surer. Bu not o sessiz "islem yok"u gorunur
        kilar; golge gozlemin olcecegi sey de budur.

        Sinirlari:
          * Not GOZLEMDIR, kapi degildir: hicbir stratejiyi bloklamaz.
            Kapi ORB'nin aralik hesabindadir; ikisi ayni yardimciyi
            (`opening_window_gaps`) kullanir.
          * Notun gunde bir kez yazilmasi vetonun suresi DEGILDIR.
          * Anahtar (seans acilisi, sembol): bir sembol ya da gun
            digerini susturmaz. Kume bellektedir; surec yeniden
            baslarsa ayni gunun notu yeniden yazilabilir.
          * Pencere veride henuz kapanmadiysa (sonraki bar gelmediyse)
            karar verilmez: gecikmeyi eksiklik saymak yanlis alarm olurdu.
        """
        session_open = ctx.session.session_open
        key = (session_open.isoformat(), ctx.symbol)
        if key in self._gap_noted:
            return
        window_end = session_open + timedelta(minutes=self.opening_range_minutes)
        bars = list(ctx.session_bars)
        if not bars or max(bar.ts for bar in bars) < window_end:
            return
        inside = [bar for bar in bars if bar.ts < window_end]
        duration = ctx.timeframe.duration
        gaps = opening_window_gaps(inside, session_open, self.opening_range_minutes, duration)
        if not gaps:
            return
        self._gap_noted.add(key)
        expected = timedelta(minutes=self.opening_range_minutes) // duration
        note = f"eksik acilis bari: {ctx.symbol} {expected - len(gaps)}/{expected}"
        log.warning("%s (ilk eksik %s)", note, gaps[0].isoformat())
        result.notes.append(note)

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
