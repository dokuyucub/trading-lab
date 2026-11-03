"""Gun ici kill-switch kalicilgi: journal kaybolursa ne olur.

Gozetimsiz paper icin on kosul (docs/designs/unattended-paper.md §4,
Codex #57/6225592912). Surec duzeyi kalicilik `test_runner.py`'de
gosteriliyor: ayni veritabaniyla yeniden baslayan surec gunu kapali
bilir. Burada ORTAM duzeyi var: her gun temiz baslayan bir ortamda
(Actions) yeniden deneme ya da elle ikinci baslatma journal'i
bulamaz. O surecin elindeki tek kanit brokerdaki hesaptir.

Bu dosya bugunku davranisi sabitler:
  * Zarar hesapta hala sinirin altindaysa taze surec de ilk turda
    durur, karari yeniden yazar ve emir gondermez.
  * Gun durumu okunamazsa tur hata ile biter; emir gonderilmez.

Bilinen acik (testle degil tasarimla kayitli, duzeltmesi kampanya
sonrasi ayri dalda): kapanis sinirin hemen ustunde gerceklesirse
(ornek: -%2,1'de tetiklenip -%1,95'te kapanmak) taze surec zarari
sinirin ustunde gorur ve ayni gun yeniden islem acar.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import make_account
from test_runner import FakeBroker, FakeMarket, breakout_bars, build_runner
from tlab.config import Config, load_config
from tlab.journal.db import apply_migrations, connect
from tlab.journal.queries import halt_reason


@pytest.fixture
def config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    return load_config(project_root)


def fresh_journal(tmp_path: Path, name: str) -> sqlite3.Connection:
    """Bu gune ait hicbir kaydi olmayan bos bir journal."""
    connection = connect(tmp_path / name)
    apply_migrations(connection)
    return connection


def test_a_fresh_process_halts_again_while_the_loss_is_still_on_the_account(
    config: Config, tmp_path: Path
) -> None:
    """Ilk surecin journal'i yok; zarar hesapta duruyor."""
    broker = FakeBroker(account=make_account(equity=97_000, last_equity=100_000))
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    first = fresh_journal(tmp_path, "first.db")
    assert build_runner(config=config, conn=first, broker=broker, market=market).run_once().halted
    first.close()

    second = fresh_journal(tmp_path, "second.db")
    runner = build_runner(config=config, conn=second, broker=broker, market=market)
    result = runner.run_once()

    assert result.halted
    assert broker.submitted == []
    assert "KILL-SWITCH" in " ".join(result.notes)
    # Karar yeni journal'a da yazilir: ayni surecin sonraki turlari
    # hesap toparlansa bile gunu kapali bilir.
    assert halt_reason(second, result.now.date()) is not None


def test_an_unreadable_day_state_ends_the_turn_without_orders(
    config: Config, tmp_path: Path
) -> None:
    """Gun durumunu okuyamayan surec karar veremez; hata gorunur kalir."""
    broker = FakeBroker(account=make_account())
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = fresh_journal(tmp_path, "broken.db")
    conn.execute("DROP TABLE daily_state")
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    with pytest.raises(sqlite3.Error):
        runner.run_once()

    assert broker.submitted == []
