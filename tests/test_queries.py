"""Journal okuma sorgulari.

Bu modul Faz 3'un (ogrenme katmani) tabani: gece analizi, walk-forward
degerlendirme ve terfi kapisi journal'i buradan okuyacak. Sorgular
yanlissa ogrenme katmani yanlis veriyle ogrenir - ve yanlis veriyle
ogrenen bir sistem, hic ogrenmeyenden kotudur cunku yanlis bir
guvenle hareket eder.

Ayrica bu sorgularin cogu SEANS SIRASINDA calisiyor (mutabakat her
turda `open_entry_orders` ve `unconfirmed_orders` cagiriyor), yani
buradaki bir hata dogrudan canli davranisi bozar.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tlab.core.types import (
    BracketOrder,
    Decision,
    EntryType,
    ExitReason,
    GateVerdict,
    Intent,
    OrderRef,
    Side,
    Trade,
)
from tlab.journal.db import apply_migrations, connect
from tlab.journal.queries import (
    decision_count,
    halt_reason,
    open_entry_orders,
    session_summary,
    top_veto_reasons,
    unconfirmed_orders,
)
from tlab.journal.writer import JournalWriter

TS = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "q.db")
    apply_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def writer(conn: sqlite3.Connection) -> JournalWriter:
    return JournalWriter(conn)


@pytest.fixture
def run_id(writer: JournalWriter) -> str:
    return writer.start_run(mode="paper", data_feed="iex", params_version="orb-v1", config={})


def make_intent(symbol: str = "SPY", *, reason: str = "kirilim") -> Intent:
    return Intent(
        strategy_id="orb",
        params_version="orb-v1",
        symbol=symbol,
        side=Side.BUY,
        reference_price=100.0,
        stop_loss=99.0,
        take_profit=101.5,
        reason=reason,
        features={"atr": 0.8},
    )


def record(
    writer: JournalWriter,
    run_id: str,
    *,
    symbol: str = "SPY",
    allowed: bool = True,
    vetoes: tuple[str, ...] = (),
) -> Decision:
    verdict = GateVerdict.allow(10) if allowed else GateVerdict.veto(*vetoes)
    decision = Decision(run_id=run_id, ts=TS, intent=make_intent(symbol), verdict=verdict)
    writer.record_decision(decision)
    return decision


def record_trade(
    writer: JournalWriter,
    run_id: str,
    *,
    symbol: str = "SPY",
    exit_price: float = 101.5,
    decision_id: str | None = None,
) -> Trade:
    trade = Trade(
        run_id=run_id,
        decision_id=decision_id,
        symbol=symbol,
        strategy_id="orb",
        params_version="orb-v1",
        side=Side.BUY,
        qty=100,
        entry_ts=TS,
        entry_price=100.0,
        exit_ts=TS + timedelta(minutes=30),
        exit_price=exit_price,
        planned_stop=99.0,
        planned_target=101.5,
        exit_reason=ExitReason.TARGET if exit_price > 100 else ExitReason.STOP,
    )
    writer.record_trade(trade)
    return trade


# --------------------------------------------------------------------------
# open_entry_orders
# --------------------------------------------------------------------------


def test_orders_are_indexed_by_client_order_id(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Mutabakat, gerceklesmenin BIZE ait olup olmadigini buradan anlar."""
    decision = record(writer, run_id)
    order = BracketOrder(
        symbol="SPY",
        side=Side.BUY,
        qty=10,
        entry_type=EntryType.LIMIT,
        limit_price=100.0,
        stop_loss=99.0,
        take_profit=101.5,
        client_order_id="tlab-known",
    )
    writer.record_order(order, run_id=run_id, decision_id=decision.decision_id)

    found = open_entry_orders(conn)
    assert set(found) == {"tlab-known"}
    row = found["tlab-known"]
    assert row["symbol"] == "SPY"
    assert row["stop_loss"] == pytest.approx(99.0)
    # Karar kaydiyla birlesim: strateji kimligi buradan geliyor.
    assert row["strategy_id"] == "orb"
    assert row["params_version"] == "orb-v1"


def test_order_without_a_decision_still_appears(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """LEFT JOIN bilincli: karar kaydi kayipsa emir yine gorulmeli.

    Aksi halde, karar yazilamadigi bir durumda gonderilmis emir
    mutabakatta tamamen kaybolur ve ondan dogan pozisyon hicbir yere
    baglanmaz.
    """
    order = BracketOrder(
        symbol="AAPL",
        side=Side.BUY,
        qty=5,
        entry_type=EntryType.MARKET,
        stop_loss=99.0,
        take_profit=101.5,
        client_order_id="tlab-orphan",
    )
    writer.record_order(order, run_id=run_id, decision_id=None)

    row = open_entry_orders(conn)["tlab-orphan"]
    assert row["symbol"] == "AAPL"
    assert row["strategy_id"] is None


def test_empty_journal_returns_empty_index(conn: sqlite3.Connection) -> None:
    assert open_entry_orders(conn) == {}


# --------------------------------------------------------------------------
# unconfirmed_orders
# --------------------------------------------------------------------------


def test_only_submitting_orders_are_unconfirmed(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Gonderim ile kayit arasinda kalmis emirlerin izi."""
    pending = BracketOrder(
        symbol="SPY",
        side=Side.BUY,
        qty=1,
        entry_type=EntryType.MARKET,
        stop_loss=99.0,
        take_profit=101.5,
        client_order_id="tlab-pending",
    )
    confirmed = pending.model_copy(update={"client_order_id": "tlab-confirmed"})
    writer.record_order(pending, run_id=run_id)
    writer.record_order(confirmed, run_id=run_id)
    writer.confirm_order(
        "tlab-confirmed",
        OrderRef(
            broker_order_id="b1",
            client_order_id="tlab-confirmed",
            symbol="SPY",
            submitted_at=TS,
            status="accepted",
        ),
    )

    rows = unconfirmed_orders(conn)
    assert [row["client_order_id"] for row in rows] == ["tlab-pending"]
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["submitted_at"]


def test_lost_orders_are_no_longer_unconfirmed(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Kayip isaretlenen emir sembolun onunu tikamayi birakmali."""
    order = BracketOrder(
        symbol="SPY",
        side=Side.BUY,
        qty=1,
        entry_type=EntryType.MARKET,
        stop_loss=99.0,
        take_profit=101.5,
        client_order_id="tlab-lost",
    )
    writer.record_order(order, run_id=run_id)
    assert unconfirmed_orders(conn)

    writer.update_order_status("tlab-lost", "lost")
    assert unconfirmed_orders(conn) == []


# --------------------------------------------------------------------------
# halt_reason
# --------------------------------------------------------------------------


def test_halt_is_remembered_for_the_day(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    today = date(2026, 1, 5)
    assert halt_reason(conn, today) is None

    writer.record_halt(today, "gunluk zarar %-2.40", run_id)
    assert halt_reason(conn, today) == "gunluk zarar %-2.40"


def test_halt_does_not_leak_into_other_days(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Kill-switch gunluk: ertesi gun sistem normale donmeli."""
    writer.record_halt(date(2026, 1, 5), "zarar siniri", run_id)
    assert halt_reason(conn, date(2026, 1, 6)) is None
    assert halt_reason(conn, date(2026, 1, 4)) is None


def test_halt_is_recorded_once_per_day(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Dongu her turda cagiriyor; kayit bir kez dusmeli."""
    today = date(2026, 1, 5)
    writer.record_halt(today, "ilk sebep", run_id)
    writer.record_halt(today, "ikinci sebep", run_id)
    assert halt_reason(conn, today) == "ilk sebep"


# --------------------------------------------------------------------------
# decision_count / session_summary
# --------------------------------------------------------------------------


def test_decision_count_splits_allowed_and_vetoed(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    record(writer, run_id, allowed=True)
    record(writer, run_id, allowed=True)
    record(writer, run_id, allowed=False, vetoes=("spread cok genis",))
    assert decision_count(conn, run_id) == (2, 1)


def test_counts_are_scoped_to_the_run(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Kosular birbirine karismamali: her kosu kendi kosullarini tasiyor."""
    other = writer.start_run(mode="backtest", data_feed="sip", params_version="orb-v2", config={})
    record(writer, run_id, allowed=True)
    record(writer, other, allowed=False, vetoes=("test",))

    assert decision_count(conn, run_id) == (1, 0)
    assert decision_count(conn, other) == (0, 1)


def test_summary_of_an_empty_run(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    stats = session_summary(conn, run_id)
    assert stats["trades"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["net_pnl"] == pytest.approx(0.0)


def test_summary_aggregates_trades(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    record_trade(writer, run_id, exit_price=101.5)  # +1.5R
    record_trade(writer, run_id, symbol="AAPL", exit_price=101.5)
    record_trade(writer, run_id, symbol="MSFT", exit_price=99.0)  # -1R

    stats = session_summary(conn, run_id)
    assert stats["trades"] == 3
    assert stats["wins"] == 2
    assert stats["win_rate"] == pytest.approx(66.67, abs=0.01)
    assert stats["net_pnl"] == pytest.approx(200.0)
    assert stats["total_r"] == pytest.approx(2.0)


def test_summary_only_counts_its_own_run(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    other = writer.start_run(mode="paper", data_feed="iex", params_version="x", config={})
    record_trade(writer, run_id, exit_price=101.5)
    record_trade(writer, other, symbol="AAPL", exit_price=99.0)

    assert session_summary(conn, run_id)["trades"] == 1
    assert session_summary(conn, other)["trades"] == 1


# --------------------------------------------------------------------------
# top_veto_reasons
# --------------------------------------------------------------------------


def test_veto_reasons_are_counted_and_ranked(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Sistem hic islem acmiyorsa sebebi bu listede yazili."""
    for _ in range(3):
        record(writer, run_id, allowed=False, vetoes=("spread cok genis",))
    record(writer, run_id, allowed=False, vetoes=("PDT siniri",))

    ranked = top_veto_reasons(conn, run_id)
    assert ranked[0] == ("spread cok genis", 3)
    assert ("PDT siniri", 1) in ranked


def test_multiple_reasons_on_one_decision_are_counted_separately(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    """Kapi kisa devre yapmiyor; her sebep ayri sayilmali."""
    record(writer, run_id, allowed=False, vetoes=("spread cok genis", "PDT siniri"))
    counts = dict(top_veto_reasons(conn, run_id))
    assert counts == {"spread cok genis": 1, "PDT siniri": 1}


def test_allowed_decisions_contribute_no_veto_reasons(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    record(writer, run_id, allowed=True)
    assert top_veto_reasons(conn, run_id) == []


def test_veto_ranking_respects_the_limit(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    for index in range(8):
        record(writer, run_id, allowed=False, vetoes=(f"sebep-{index}",))
    assert len(top_veto_reasons(conn, run_id, limit=3)) == 3
