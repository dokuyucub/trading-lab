"""Gorulen kaydi (docs/designs/shadow-observation.md §2).

Kayit, dongunun her turda GERCEKTEN gordugunu saklar: sonradan gelen
deger eski gorunumu yeniden yazmaz, kurulamayan gorunum tahmin
edilmez, erisim hatasi gozlem sayilmaz.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from conftest import SESSION_OPEN, make_bars, make_quote
from tlab.core.types import Bar, Quote, Timeframe
from tlab.errors import DataError
from tlab.shadow.record import RecordingMarket, SeenRecord, view_digest

START = SESSION_OPEN - timedelta(days=3)


@pytest.fixture
def record() -> SeenRecord:
    return SeenRecord(sqlite3.connect(":memory:"))


def at(minute: int) -> datetime:
    return SESSION_OPEN + timedelta(minutes=minute, seconds=5)


def revised(bar: Bar, close: float) -> Bar:
    return bar.model_copy(update={"close": close, "high": max(bar.high, close)})


class Clock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class Market:
    def __init__(self, bars: list[Bar]) -> None:
        self.data = bars
        self.fail = False
        self.quotes = 0

    def bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None
    ) -> list[Bar]:
        if self.fail:
            raise DataError("RESPONSE-BODY-CANARY")
        return [bar for bar in self.data if start <= bar.ts and (end is None or bar.ts <= end)]

    def latest_quote(self, symbol: str) -> Quote:
        self.quotes += 1
        return make_quote(symbol)


# --------------------------------------------------------------------------
# Depo
# --------------------------------------------------------------------------


def test_a_turn_view_is_rebuilt_exactly(record: SeenRecord) -> None:
    bars = make_bars(5)
    record.seen("SPY", moment=at(5), start=START, accessed=at(5), bars=bars)
    assert record.view("SPY", at(5)) == tuple(bars)


def test_a_revised_bar_does_not_rewrite_the_earlier_view(record: SeenRecord) -> None:
    first = make_bars(5)
    second = [*first[:4], revised(first[4], 100.3)]
    record.seen("SPY", moment=at(5), start=START, accessed=at(5), bars=first)
    record.seen("SPY", moment=at(6), start=START, accessed=at(6), bars=second)
    assert record.view("SPY", at(5)) == tuple(first)
    assert record.view("SPY", at(6)) == tuple(second)
    versions = record.conn.execute(
        "SELECT COUNT(*) FROM seen_bar WHERE ts = ?",
        (first[4].ts.isoformat(timespec="microseconds"),),
    ).fetchone()[0]
    assert versions == 2


def test_an_unchanged_bar_is_written_once(record: SeenRecord) -> None:
    bars = make_bars(5)
    for minute in (5, 6, 7):
        record.seen("SPY", moment=at(minute), start=START, accessed=at(minute), bars=bars)
    assert record.conn.execute("SELECT COUNT(*) FROM seen_bar").fetchone()[0] == 5


def test_a_bar_dropped_later_makes_that_view_unknown(record: SeenRecord) -> None:
    """Saglayici bir bari sonraki turda dusururse gorunum tahmin edilmez."""
    bars = make_bars(5)
    record.seen("SPY", moment=at(5), start=START, accessed=at(5), bars=bars)
    record.seen("SPY", moment=at(6), start=START, accessed=at(6), bars=bars[:3] + bars[4:])
    assert record.view("SPY", at(5)) == tuple(bars)
    assert record.view("SPY", at(6)) is None


def test_a_late_bar_does_not_enter_the_earlier_view(record: SeenRecord) -> None:
    """Sonraki turda ilk kez gorulen eski bar, onceki turun gorunumune girmez."""
    bars = make_bars(5)
    record.seen("SPY", moment=at(5), start=START, accessed=at(5), bars=bars[:2] + bars[3:])
    record.seen("SPY", moment=at(6), start=START, accessed=at(6), bars=bars)
    assert record.view("SPY", at(5)) == tuple(bars[:2] + bars[3:])
    assert record.view("SPY", at(6)) == tuple(bars)


def test_a_failed_turn_is_unknown_not_empty(record: SeenRecord) -> None:
    record.failed("SPY", moment=at(5), start=START, accessed=at(5), reason="hiz siniri (429)")
    record.seen("SPY", moment=at(6), start=START, accessed=at(6), bars=[])
    assert record.view("SPY", at(5)) is None
    assert record.view("SPY", at(6)) == ()
    assert record.moments("SPY") == [at(5), at(6)]


def test_symbols_do_not_mix(record: SeenRecord) -> None:
    spy = make_bars(3)
    aapl = make_bars(3, symbol="AAPL", base=200.0)
    record.seen("SPY", moment=at(3), start=START, accessed=at(3), bars=spy)
    record.seen("AAPL", moment=at(3), start=START, accessed=at(3), bars=aapl)
    assert record.view("SPY", at(3)) == tuple(spy)
    assert record.view("AAPL", at(3)) == tuple(aapl)
    with pytest.raises(DataError, match="sembolu tutmuyor"):
        record.seen("SPY", moment=at(4), start=START, accessed=at(4), bars=aapl)


def test_the_view_honours_the_request_range(record: SeenRecord) -> None:
    """Gorunum turun istek araligidir: daha once gorulmus eski barlar girmez."""
    bars = make_bars(5)
    record.seen("SPY", moment=at(5), start=START, accessed=at(5), bars=bars)
    later_start = bars[2].ts
    record.seen("SPY", moment=at(6), start=later_start, accessed=at(6), bars=bars[2:])
    assert record.view("SPY", at(6)) == tuple(bars[2:])


def test_the_view_is_what_the_provider_returned(record: SeenRecord) -> None:
    """Saglayici istek sonundan sonraki bari da dondurduyse gorunum odur.

    Kapanmis bar suzmesi karar yolunun isidir (`visible_bars`); kayit
    gorulen yaniti oldugu gibi yeniden kurar.
    """
    bars = make_bars(10)
    record.seen("SPY", moment=at(3), start=START, accessed=at(3), bars=bars)
    assert record.view("SPY", at(3)) == tuple(bars)


def test_the_digest_is_order_independent_and_value_sensitive() -> None:
    bars = make_bars(3)
    assert view_digest(bars) == view_digest(list(reversed(bars)))
    assert view_digest(bars) != view_digest([*bars[:2], revised(bars[2], 100.2)])


def test_naive_moments_are_refused(record: SeenRecord) -> None:
    with pytest.raises(ValueError, match="timezone"):
        record.seen(
            "SPY", moment=datetime(2026, 1, 5, 14, 35), start=START, accessed=at(5), bars=[]
        )


# --------------------------------------------------------------------------
# Kaydeden veri kaynagi
# --------------------------------------------------------------------------


def test_the_market_wrapper_records_what_the_loop_sees(record: SeenRecord) -> None:
    market = Market(make_bars(10))
    wrapped = RecordingMarket(market, record, Clock(at(5) + timedelta(seconds=1)))
    returned = wrapped.bars("SPY", Timeframe.M1, START, at(5))
    assert record.view("SPY", at(5)) == tuple(returned)
    accessed = record.conn.execute("SELECT accessed FROM seen_turn").fetchone()[0]
    assert accessed == (at(5) + timedelta(seconds=1)).isoformat(timespec="microseconds")


def test_a_market_error_is_recorded_and_raised(record: SeenRecord) -> None:
    market = Market(make_bars(10))
    market.fail = True
    wrapped = RecordingMarket(market, record, Clock(at(5)))
    with pytest.raises(DataError) as raised:
        wrapped.bars("SPY", Timeframe.M1, START, at(5))
    assert str(raised.value).startswith("SPY bar verisi alinamadi: ")
    assert "CANARY" not in str(raised.value)
    # `from exc` de baglami bastirir ama nedeni (__cause__) traceback'e
    # yazdirir; zincir hic olmamali.
    assert raised.value.__cause__ is None, "SDK istisnasi traceback'e zincirlenmemeli"
    assert raised.value.__suppress_context__
    assert record.moments("SPY") == [at(5)]
    assert record.view("SPY", at(5)) is None
    reason = record.conn.execute("SELECT reason FROM seen_turn").fetchone()[0]
    assert "CANARY" not in reason


def test_quotes_pass_through_unrecorded(record: SeenRecord) -> None:
    market = Market(make_bars(3))
    wrapped = RecordingMarket(market, record, Clock(at(5)))
    assert wrapped.latest_quote("SPY").symbol == "SPY"
    assert market.quotes == 1
    assert record.conn.execute("SELECT COUNT(*) FROM seen_turn").fetchone()[0] == 0
