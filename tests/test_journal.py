"""Journal sema, goc ve yazma testleri."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tlab.core.types import Decision, GateVerdict, Intent
from tlab.errors import JournalError
from tlab.journal.db import apply_migrations, connect, schema_version
from tlab.journal.writer import JournalWriter

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "journal.db")
    apply_migrations(connection)
    return connection


@pytest.fixture
def writer(conn: sqlite3.Connection) -> JournalWriter:
    return JournalWriter(conn)


@pytest.fixture
def run_id(writer: JournalWriter) -> str:
    return writer.start_run(
        mode="paper", data_feed="iex", params_version="v0", config={"risk": {"max": 0.5}}
    )


# --------------------------------------------------------------------------
# Sema ve gocler
# --------------------------------------------------------------------------


def test_migrations_create_expected_tables(conn: sqlite3.Connection) -> None:
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"runs", "decisions", "orders", "fills", "trades", "params_versions"} <= tables


def test_migrations_are_idempotent(conn: sqlite3.Connection) -> None:
    """Her aciliste goc calisir; ikinci kez hicbir sey yapmamali."""
    before = schema_version(conn)
    assert apply_migrations(conn) == []
    assert schema_version(conn) == before


def test_database_is_created_with_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "journal.db"
    connect(path).close()
    assert path.exists()


def test_foreign_keys_are_enforced(conn: sqlite3.Connection) -> None:
    """Var olmayan kosuya bagli karar kaydi olusmamali."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (decision_id, run_id, ts, symbol, strategy_id,"
            " params_version, side, reference_price, stop_loss, take_profit,"
            " reward_risk, confidence, allowed, features_json)"
            " VALUES ('d1', 'olmayan-kosu', ?, 'SPY', 'orb', 'v0', 'buy',"
            " 100, 99, 101, 1.0, 0.5, 1, '{}')",
            (TS.isoformat(),),
        )


# --------------------------------------------------------------------------
# Kosu kaydi
# --------------------------------------------------------------------------


def test_run_records_reproducibility_context(conn: sqlite3.Connection, run_id: str) -> None:
    """Kosu; kod surumu, feed ve yapilandirmayla birlikte saklanmali.

    Bu bag olmadan gecmis sonuclarin neden farkli oldugu anlasilamaz.
    """
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["mode"] == "paper"
    assert row["data_feed"] == "iex"
    assert row["params_version"] == "v0"
    assert json.loads(row["config_json"])["risk"]["max"] == 0.5
    assert row["ended_at"] is None


def test_end_run_sets_timestamp(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str
) -> None:
    writer.end_run(run_id)
    row = conn.execute("SELECT ended_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["ended_at"] is not None


def test_invalid_run_mode_is_rejected(writer: JournalWriter) -> None:
    with pytest.raises(JournalError, match="Gecersiz kosu modu"):
        writer.start_run(mode="gercek", data_feed="iex", params_version="v0", config={})


def test_run_ids_are_unique(writer: JournalWriter) -> None:
    ids = {
        writer.start_run(mode="backtest", data_feed="iex", params_version="v0", config={})
        for _ in range(20)
    }
    assert len(ids) == 20


# --------------------------------------------------------------------------
# Karar kaydi
# --------------------------------------------------------------------------


def test_allowed_decision_is_recorded(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str, sample_intent: Intent
) -> None:
    writer.record_decision(
        Decision(run_id=run_id, ts=TS, intent=sample_intent, verdict=GateVerdict.allow(25))
    )
    row = conn.execute("SELECT * FROM decisions").fetchone()
    assert row["symbol"] == "SPY"
    assert row["allowed"] == 1
    assert row["qty"] == 25
    assert row["strategy_id"] == "orb"
    assert row["reward_risk"] == pytest.approx(1.5)


def test_vetoed_decision_is_recorded_with_reasons(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str, sample_intent: Intent
) -> None:
    """Yapilmayan islemler, ogrenme icin yapilanlar kadar degerli.

    "Kapi engellemeseydi ne olurdu" sorusu ancak bu kayitla cevaplanir.
    """
    writer.record_decision(
        Decision(
            run_id=run_id,
            ts=TS,
            intent=sample_intent,
            verdict=GateVerdict.veto("spread cok genis", "gunluk zarar limiti"),
        )
    )
    row = conn.execute("SELECT * FROM decisions").fetchone()
    assert row["allowed"] == 0
    assert row["qty"] == 0
    assert "spread cok genis" in row["veto_reasons"]
    assert "gunluk zarar limiti" in row["veto_reasons"]


def test_feature_snapshot_is_persisted(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str, sample_intent: Intent
) -> None:
    """Ozellik fotografi ogrenme katmaninin tek yakiti - kaybedilemez."""
    writer.record_decision(
        Decision(run_id=run_id, ts=TS, intent=sample_intent, verdict=GateVerdict.allow(10))
    )
    row = conn.execute("SELECT features_json FROM decisions").fetchone()
    assert json.loads(row["features_json"]) == {"atr": 0.8, "rvol": 1.9}


def test_decision_ids_are_unique(
    conn: sqlite3.Connection, writer: JournalWriter, run_id: str, sample_intent: Intent
) -> None:
    for _ in range(50):
        writer.record_decision(
            Decision(run_id=run_id, ts=TS, intent=sample_intent, verdict=GateVerdict.allow(1))
        )
    count = conn.execute("SELECT COUNT(DISTINCT decision_id) AS n FROM decisions").fetchone()
    assert count["n"] == 50


def test_duplicate_decision_id_is_rejected(
    writer: JournalWriter, run_id: str, sample_intent: Intent
) -> None:
    decision = Decision(
        decision_id="fixed-id",
        run_id=run_id,
        ts=TS,
        intent=sample_intent,
        verdict=GateVerdict.allow(1),
    )
    writer.record_decision(decision)
    with pytest.raises(JournalError, match="Karar kaydedilemedi"):
        writer.record_decision(decision)
