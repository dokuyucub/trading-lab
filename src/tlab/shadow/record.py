"""Gorulen kaydi: canli dongunun her turda GERCEKTEN gordugu barlar.

Tasarim: docs/designs/shadow-observation.md §2. Kayit gecici ve
yereldir (SQLite, `RUNNER_TEMP`); disari cikmaz, is sonunda silinir.

Kurallar:

  * Bar bir kez yazilir. Degeri sonraki bir turda degisirse yeni surum
    satiri eklenir; eski satir silinmez ve uzerine yazilmaz.
  * Her tur icin istek baslangici, yanitin ilk ve son bari, erisim ani
    ve gorulen kumenin ozeti (SHA-256) yazilir. Turun gorunumu kayittan
    yeniden kurulur ve bu ozetle dogrulanir; tutmazsa gorunum
    "bilinmiyor" sayilir, tahmin edilmez.
  * Veri alinamayan tur da yazilir: erisim hatasi bir gozlem degil,
    `unknown`dur. Sebep SABIT bir siniftir (`classify`); yanit govdesi
    ne kayda ne log'a gecer.

`RecordingMarket`, dongunun veri kaynagini sarar: dongu ne gorduyse
kayit odur. Kotasyon kaydedilmez; karsilastirmaya girmez.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from tlab.core.clock import Clock
from tlab.core.types import Bar, Quote, Timeframe
from tlab.data.market import MarketData
from tlab.errors import DataError
from tlab.sdk_probe import classify

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_bar (
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (symbol, ts, version)
);
CREATE TABLE IF NOT EXISTS seen_turn (
    symbol TEXT NOT NULL,
    moment TEXT NOT NULL,
    accessed TEXT NOT NULL,
    start TEXT NOT NULL,
    ok INTEGER NOT NULL,
    bar_count INTEGER,
    first_ts TEXT,
    last_ts TEXT,
    digest TEXT,
    reason TEXT,
    PRIMARY KEY (symbol, moment)
);
"""


def _payload(bar: Bar) -> str:
    """Barin karsilastirmaya giren alanlari, sabit sirayla."""
    return json.dumps(
        [bar.open, bar.high, bar.low, bar.close, bar.volume, bar.vwap, bar.trade_count],
        separators=(",", ":"),
    )


def view_digest(bars: Sequence[Bar]) -> str:
    """Gorulen kumenin ozeti: zaman sirali (ts, alanlar) dizisinin SHA-256'si."""
    digest = hashlib.sha256()
    for bar in sorted(bars, key=lambda item: item.ts):
        digest.update(f"{bar.ts.isoformat()}|{_payload(bar)}\n".encode())
    return digest.hexdigest()


class SeenRecord:
    """Gorulen kaydinin deposu. Baglanti cagirana aittir."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.executescript(_SCHEMA)

    def seen(
        self,
        symbol: str,
        *,
        moment: datetime,
        start: datetime,
        accessed: datetime,
        bars: Sequence[Bar],
    ) -> None:
        """Bir turun gordugu barlari yazar; degisen bar yeni surum olur."""
        with self.conn:
            for bar in bars:
                if bar.symbol != symbol:
                    raise DataError(f"kayit sembolu tutmuyor: {bar.symbol} != {symbol}")
                payload = _payload(bar)
                row = self.conn.execute(
                    "SELECT version, payload FROM seen_bar WHERE symbol = ? AND ts = ?"
                    " ORDER BY version DESC LIMIT 1",
                    (symbol, _iso(bar.ts)),
                ).fetchone()
                if row is not None and row[1] == payload:
                    continue
                version = 0 if row is None else row[0] + 1
                self.conn.execute(
                    "INSERT INTO seen_bar (symbol, ts, version, payload, first_seen)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (symbol, _iso(bar.ts), version, payload, _iso(moment)),
                )
            first_ts = _iso(min(bar.ts for bar in bars)) if bars else None
            last_ts = _iso(max(bar.ts for bar in bars)) if bars else None
            self.conn.execute(
                "INSERT INTO seen_turn"
                " (symbol, moment, accessed, start, ok, bar_count, first_ts, last_ts, digest)"
                " VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (
                    symbol,
                    _iso(moment),
                    _iso(accessed),
                    _iso(start),
                    len(bars),
                    first_ts,
                    last_ts,
                    view_digest(bars),
                ),
            )

    def failed(
        self, symbol: str, *, moment: datetime, start: datetime, accessed: datetime, reason: str
    ) -> None:
        """Verinin alinamadigi turu sabit sebebiyle yazar."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO seen_turn (symbol, moment, accessed, start, ok, reason)"
                " VALUES (?, ?, ?, ?, 0, ?)",
                (symbol, _iso(moment), _iso(accessed), _iso(start), reason),
            )

    def moments(self, symbol: str) -> list[datetime]:
        """Sembolun kayitli turlari, zaman sirali."""
        rows = self.conn.execute(
            "SELECT moment FROM seen_turn WHERE symbol = ? ORDER BY moment", (symbol,)
        ).fetchall()
        return [datetime.fromisoformat(row[0]) for row in rows]

    def view(self, symbol: str, moment: datetime) -> tuple[Bar, ...] | None:
        """Turun gorunumunu kayittan yeniden kurar; kurulamazsa None.

        Gorunum: o turun yanitindaki ilk ve son bar arasinda, o tura kadar
        gorulmus barlarin o andaki en son surumu. Aralik istek araligi
        degil YANITIN araligidir: saglayici ne dondurduyse kayit odur.
        Ozet tutmazsa (ornegin saglayici araliktaki bir bari sonraki turda
        dusurmusse) gorunum tahmin edilmez.
        """
        turn = self.conn.execute(
            "SELECT ok, bar_count, first_ts, last_ts, digest FROM seen_turn"
            " WHERE symbol = ? AND moment = ?",
            (symbol, _iso(moment)),
        ).fetchone()
        if turn is None or not turn[0]:
            return None
        _, count, first_ts, last_ts, digest = turn
        if count == 0:
            return ()
        # Her bar icin o tura kadar gorulmus EN SON surum. O turdan sonra
        # ilk kez gorulen bar icin alt sorgu NULL doner ve satir dusar.
        rows = self.conn.execute(
            "SELECT ts, payload FROM seen_bar AS outer_bar"
            " WHERE symbol = ? AND ts >= ? AND ts <= ?"
            " AND version = (SELECT MAX(version) FROM seen_bar AS inner_bar"
            "   WHERE inner_bar.symbol = outer_bar.symbol AND inner_bar.ts = outer_bar.ts"
            "   AND inner_bar.first_seen <= ?)"
            " ORDER BY ts",
            (symbol, first_ts, last_ts, _iso(moment)),
        ).fetchall()
        bars = tuple(_bar(symbol, ts, payload) for ts, payload in rows)
        if len(bars) != count or view_digest(bars) != digest:
            return None
        return bars


class RecordingMarket:
    """Dongunun veri kaynagini sarar ve her bar istegini kayda yazar.

    Dongu bar istegini `end=simdi` ile yapar; tur ani `end`dir. Erisim
    ani saatten alinir. Hata kayda yazilir ve SABIT metinle yukari
    iletilir: dongu o sembolu o tur atlar ve hatayi log'a basar; SDK
    istisnasi yanit govdesini tasiyabilir, o yuzden zincir kesilir
    (`from None`). Golge isinin loglari herkese acik Actions loglaridir.
    """

    def __init__(self, inner: MarketData, record: SeenRecord, clock: Clock) -> None:
        self.inner = inner
        self.record = record
        self.clock = clock

    def bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Bar]:
        moment = end if end is not None else self.clock.now()
        try:
            bars = self.inner.bars(symbol, timeframe, start, end)
        except DataError as exc:
            reason = classify(exc)
            self.record.failed(
                symbol, moment=moment, start=start, accessed=self.clock.now(), reason=reason
            )
            raise DataError(f"{symbol} bar verisi alinamadi: {reason}") from None
        self.record.seen(symbol, moment=moment, start=start, accessed=self.clock.now(), bars=bars)
        return bars

    def latest_quote(self, symbol: str) -> Quote:
        return self.inner.latest_quote(symbol)


def _iso(value: datetime) -> str:
    """Kayit anahtari: mikrosaniyeli UTC ISO-8601.

    Ayni an tek yazimla saklanir ve metin sirasi zaman sirasidir; SQL
    karsilastirmalari buna dayanir.
    """
    if value.tzinfo is None:
        raise ValueError("kayit anlari timezone icermeli")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _bar(symbol: str, ts: str, payload: str) -> Bar:
    open_, high, low, close, volume, vwap, trade_count = json.loads(payload)
    return Bar(
        symbol=symbol,
        ts=datetime.fromisoformat(ts),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        vwap=vwap,
        trade_count=trade_count,
    )
