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
from test_runner import FakeBroker, FakeMarket
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


def run_once_dry(root: Path) -> int:
    args = cli.build_parser().parse_args(["--root", str(root), "run", "--once", "--dry-run"])
    result: int = args.func(args)
    return result


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
