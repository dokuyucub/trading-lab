"""Once kaydet, sonra gonder: emir kaydinin sirasi ve hata yollari.

`_handle_intent` emri once journal'a yazar, sonra brokera gonderir.
Iki adimin arasinda surec olurse geride `submitting` durumunda bir
satir kalir ve sonraki tur onu brokera karsi cozumler. Sira ters
olsaydi brokerdaki emir journal'da hic gorunmezdi: dolmasindan dogan
pozisyon hicbir karara atfedilemezdi.

`test_runner.py::test_order_is_journaled_before_it_is_sent` bu sirayi
sabitlemiyor: satira gonderim BITTIKTEN sonra bakiyor ve "once gonder,
sonra kaydet" mutasyonu orada yesil kaliyor. Buradaki sahte broker
journal'i emrin kendisine ULASTIGI anda okur.

Okuma ayri, salt okunur bir baglantidan yapilir. Kayit yalnizca
yazildigi baglantida gorunuyorsa (commit edilmemis islem) surec olunce
o da kaybolur; yeniden baslayan surecin gorecegi sey baska bir
baglantinin gordugudur.

Sabitlenen bugunku davranis:
  * emir brokera ulastiginda satiri commit edilmistir, `submitting`
    durumundadir ve brokera giden kimligi tasir;
  * emir kaydi yazilamazsa emir gonderilmez; tur hata firlatmaz,
    `<sembol>: journal yazilamadi` notunu duser, karar satiri kalir;
  * gonderim hata verirse satir `submitting` kalir; emir brokera
    ulasmissa sonraki tur ayni satiri kesinlestirir, yeniden gondermez.

Her test hem alis hem aciga satis girisi icin kosar.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from conftest import make_bars
from test_runner import FakeBroker, FakeMarket, breakout_bars, build_runner
from tlab.config import Config, load_config
from tlab.core.types import Bar, BracketOrder, OrderRef, Side
from tlab.errors import BrokerError
from tlab.journal.db import apply_migrations, connect
from tlab.journal.queries import unconfirmed_orders

pytestmark = pytest.mark.parametrize("side", [Side.BUY, Side.SELL], ids=["alis", "aciga_satis"])

ORDER_ROWS = (
    "SELECT client_order_id, broker_order_id, status, symbol, side, qty,"
    " limit_price, stop_loss, take_profit FROM orders ORDER BY rowid"
)

Row = dict[str, object]


def order_rows(conn: sqlite3.Connection) -> list[Row]:
    return [dict(row) for row in conn.execute(ORDER_ROWS).fetchall()]


def recorded(order: BracketOrder, *, broker_order_id: str | None, status: str) -> Row:
    """`order`in journal satiri: kimlik, yon, miktar ve fiyatlar gonderilenle ayni."""
    return {
        "client_order_id": order.client_order_id,
        "broker_order_id": broker_order_id,
        "status": status,
        "symbol": order.symbol,
        "side": order.side.value,
        "qty": order.qty,
        "limit_price": order.limit_price,
        "stop_loss": order.stop_loss,
        "take_profit": order.take_profit,
    }


@dataclass(kw_only=True)
class ObservingBroker(FakeBroker):
    """Emir kendisine ULASTIGI anda journal'i ikinci baglantidan okuyan broker.

    `received`, `FakeBroker.submitted`in aksine basarisiz gonderimleri de
    tutar: "brokera hic gidilmedi" iddiasi ancak boyle sinanir.
    """

    observer: sqlite3.Connection
    lose_response: bool = False
    """Emir brokera ulasir ama cevabi kaybolur (`BrokerError`)."""
    received: list[BracketOrder] = field(default_factory=list)
    journal_at_submit: list[list[Row]] = field(default_factory=list)

    def submit_bracket(self, order: BracketOrder) -> OrderRef:
        self.received.append(order)
        self.journal_at_submit.append(order_rows(self.observer))
        ref = super().submit_bracket(order)
        if self.lose_response:
            msg = "cevap kayboldu"
            raise BrokerError(msg)
        return ref


def breakdown_bars() -> list[Bar]:
    """Acilis araligi olusmus ve asagi kirilmis bir seans (`breakout_bars`in aynasi)."""
    bars = make_bars(30, symbol="SPY", base=100.0, spread=0.5, volume=10_000)
    bars[-1] = bars[-1].model_copy(
        update={"open": 100.0, "close": 99.2, "high": 100.5, "low": 99.2, "volume": 30_000.0}
    )
    return bars


def market_for(side: Side) -> FakeMarket:
    if side is Side.BUY:
        return FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    return FakeMarket(bars_by_symbol={"SPY": breakdown_bars()}, quote_mid=99.2)


def reject_order_inserts(conn: sqlite3.Connection) -> None:
    """Yalnizca `orders` tablosuna EKLEMEYI bozar.

    Hata gercek SQLite katmaninda dogar ve `JournalWriter.record_order`
    icinden gecer; yazicinin kendisi taklit edilmiyor. Okumalar, karar
    kaydi ve `orders` guncellemeleri calismaya devam eder.
    """
    conn.execute(
        "CREATE TRIGGER orders_yazilamaz BEFORE INSERT ON orders"
        " BEGIN SELECT RAISE(ABORT, 'emir kaydi yazilamiyor'); END"
    )


@pytest.fixture
def config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    return load_config(project_root)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    apply_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def observer(tmp_path: Path, conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Ayni dosyaya ikinci, salt okunur baglanti: yeniden baslayan surecin gozu."""
    connection = sqlite3.connect(f"{(tmp_path / 'journal.db').as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_the_order_row_is_committed_before_the_broker_is_called(
    config: Config, conn: sqlite3.Connection, observer: sqlite3.Connection, side: Side
) -> None:
    """Emir brokera ulastigi anda kaydi baska bir baglantidan gorunur."""
    broker = ObservingBroker(observer=observer)
    runner = build_runner(config=config, conn=conn, broker=broker, market=market_for(side))

    result = runner.run_once()

    assert result.submitted == 1
    assert len(broker.received) == 1
    sent = broker.received[0]
    assert sent.side is side
    # Tek satir, gonderilen kimlikle, broker cevabindan ONCEKI durumda.
    assert broker.journal_at_submit == [[recorded(sent, broker_order_id=None, status="submitting")]]


def test_the_confirmed_row_is_the_order_the_broker_received(
    config: Config, conn: sqlite3.Connection, observer: sqlite3.Connection, side: Side
) -> None:
    """Kimlik tek: yazilan, brokera giden ve kesinlesen ayni emir."""
    broker = ObservingBroker(observer=observer)
    build_runner(config=config, conn=conn, broker=broker, market=market_for(side)).run_once()

    (sent,) = broker.received
    (ref,) = broker.open_orders
    assert ref.client_order_id == sent.client_order_id
    # Ikinci bir kimlik yazilmadi; ayni satir broker cevabiyla kesinlesti.
    assert order_rows(observer) == [
        recorded(sent, broker_order_id=ref.broker_order_id, status="accepted")
    ]


def test_a_failed_order_record_sends_nothing(
    config: Config, conn: sqlite3.Connection, observer: sqlite3.Connection, side: Side
) -> None:
    """Emir kaydi yazilamazsa emir gitmez; tur hata firlatmaz, not duser."""
    broker = ObservingBroker(observer=observer)
    runner = build_runner(config=config, conn=conn, broker=broker, market=market_for(side))
    reject_order_inserts(conn)

    result = runner.run_once()

    assert broker.received == [], "kaydedilemeyen emir brokera gitmemeli"
    assert result.intents == 1
    assert result.vetoed == 0
    assert result.submitted == 0
    assert "SPY: journal yazilamadi" in result.notes
    # Hata emir kaydinda dogdu: izinli karar satiri yazildi, emir satiri yok.
    assert [row["allowed"] for row in observer.execute("SELECT allowed FROM decisions")] == [1]
    assert order_rows(observer) == []


def test_a_lost_response_leaves_a_row_the_next_turn_confirms(
    config: Config, conn: sqlite3.Connection, observer: sqlite3.Connection, side: Side
) -> None:
    """Gonderim hata verse de satir kalir; emir brokerdaysa sonraki tur kesinlestirir."""
    broker = ObservingBroker(observer=observer, lose_response=True)
    runner = build_runner(config=config, conn=conn, broker=broker, market=market_for(side))

    first = runner.run_once()

    (sent,) = broker.received
    assert first.submitted == 0
    assert order_rows(observer) == [recorded(sent, broker_order_id=None, status="submitting")]
    # Mutabakatin okudugu sorgu satiri buluyor: sonraki tur onu cozebilir.
    assert [row["client_order_id"] for row in unconfirmed_orders(conn)] == [sent.client_order_id]

    runner.run_once()

    (ref,) = broker.open_orders
    assert order_rows(observer) == [
        recorded(sent, broker_order_id=ref.broker_order_id, status="accepted")
    ]
    assert len(broker.received) == 1, "kesinlesen emir yeniden gonderilmemeli"
