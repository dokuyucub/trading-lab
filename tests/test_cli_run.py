"""Canli `run` komutunun feed bagi (AGENTS §11.4).

`cmd_run` sahte broker, sahte veri kaynagi ve sahte saatle kosar: journal'a
yazilan `runs.data_feed`, karar verisini ceken istemcinin feed'i ve
config'teki feed ayni olmali. Anahtarlar sahte sabit metin; ag yok.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from conftest import SESSION_OPEN
from test_runner import FakeBroker, FakeMarket, breakout_bars_at
from tlab import cli
from tlab.config import load_config
from tlab.core.clock import SimClock

NOW = SESSION_OPEN + timedelta(minutes=30)


@dataclass
class Built:
    """Monkeypatch edilen istemci kurucularinin gordugu argumanlar."""

    broker_kwargs: list[dict[str, Any]] = field(default_factory=list)
    market_kwargs: list[dict[str, Any]] = field(default_factory=list)
    broker: FakeBroker = field(default_factory=FakeBroker)
    market: FakeMarket = field(default_factory=FakeMarket)


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> Built:
    seen = Built()

    def broker(*args: Any, **kwargs: Any) -> FakeBroker:
        seen.broker_kwargs.append({"positional": len(args), **kwargs})
        return seen.broker

    def market(*args: Any, **kwargs: Any) -> FakeMarket:
        seen.market_kwargs.append({"positional": len(args), **kwargs})
        return seen.market

    monkeypatch.setattr(cli, "AlpacaBroker", broker)
    monkeypatch.setattr(cli, "AlpacaMarketData", market)
    monkeypatch.setattr(cli, "LiveClock", lambda: SimClock(NOW))
    monkeypatch.setenv("ALPACA_API_KEY", "PKTEST")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.delenv("ALPACA_PAPER", raising=False)
    monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
    return seen


def run_once(root: Path, *extra: str) -> int:
    args = cli.build_parser().parse_args(["--root", str(root), "run", "--once", *extra])
    result: int = args.func(args)
    return result


def run_once_dry(root: Path) -> int:
    return run_once(root, "--dry-run")


def counts(root: Path) -> tuple[int, int]:
    """(karar sayisi, emir sayisi) journal'dan."""
    conn = sqlite3.connect(load_config(root).journal_path)
    try:
        decisions = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    finally:
        conn.close()
    return int(decisions), int(orders)


def runs(root: Path) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(load_config(root).journal_path)
    try:
        return conn.execute(
            "SELECT mode, data_feed, params_version, notes, ended_at FROM runs"
        ).fetchall()
    finally:
        conn.close()


def set_feed(root: Path, feed: str) -> None:
    base = root / "config" / "base.yaml"
    text = base.read_text(encoding="utf-8")
    assert text.count("feed: iex") == 1
    base.write_text(text.replace("feed: iex", f"feed: {feed}"), encoding="utf-8")


@pytest.mark.parametrize("feed", ["iex", "sip"])
def test_the_journal_run_carries_the_feed_the_decisions_were_made_with(
    project_root: Path, built: Built, feed: str
) -> None:
    set_feed(project_root, feed)
    assert run_once_dry(project_root) == 0
    rows = runs(project_root)
    assert len(rows) == 1
    mode, data_feed, params_version, notes, ended_at = rows[0]
    assert (mode, data_feed, notes) == ("paper", feed, "dry-run")
    assert params_version and ended_at is not None, "kosu kapatilmadan birakilmaz"
    assert [k["feed"] for k in built.market_kwargs] == [feed], "karar verisi ayni feed'den"
    assert [k["paper"] for k in built.broker_kwargs] == [True]
    assert built.broker.submitted == [], "dry-run emir gondermez"


def test_dry_run_records_the_decision_but_sends_no_order(project_root: Path, built: Built) -> None:
    """Sinyal ureten veriyle: --dry-run bayragi SessionRunner'a gercekten
    aktariliyor. Bayrak aktarilmasaydi sahte broker emri gorurdu."""
    built.market.bars_by_symbol["SPY"] = breakout_bars_at(SESSION_OPEN)
    assert run_once_dry(project_root) == 0
    assert built.broker.submitted == [], "dry-run emir gondermez"
    decisions, orders = counts(project_root)
    assert decisions >= 1, "karar yine de kaydedilir"
    assert orders == 0


def test_without_dry_run_the_same_signal_reaches_the_fake_broker(
    project_root: Path, built: Built
) -> None:
    """Karsi ornek: ayni veri, bayrak yok -> sahte broker'a bir bracket gider.
    Gercek istemci yok; monkeypatch edilmis sahte broker."""
    built.market.bars_by_symbol["SPY"] = breakout_bars_at(SESSION_OPEN)
    assert run_once(project_root) == 0
    assert len(built.broker.submitted) == 1
    assert built.broker.submitted[0].symbol == "SPY"
    decisions, orders = counts(project_root)
    assert decisions >= 1 and orders == 1
    rows = runs(project_root)
    assert rows[0][3] is None, "dry-run notu yok"


def test_live_money_is_refused_without_the_flag_and_no_client_is_built(
    project_root: Path,
    built: Built,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ALPACA_PAPER", "false")
    assert run_once_dry(project_root) == 1
    assert "GERCEK PARA" in capsys.readouterr().err
    assert built.broker_kwargs == [] and built.market_kwargs == []
    assert not load_config(project_root).journal_path.exists(), "kosu kaydi acilmaz"
