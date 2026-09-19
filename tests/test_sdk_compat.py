"""SDK uyum katmani testleri.

alpaca-py ayni bilgiyi model nesnesi ya da ham sozluk olarak
dondurebiliyor. Bu fark normalde ancak canli seansta patlar; burada
her iki sekli de cevrimdisi dogruluyoruz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from tlab.data.market import AlpacaMarketData
from tlab.errors import DataError
from tlab.sdk_compat import sdk_bool, sdk_field, sdk_float, sdk_int

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


@dataclass
class FakeBar:
    """Alpaca'nin model seklindeki bar yaniti."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None


DICT_BAR: dict[str, Any] = {
    "timestamp": TS,
    "open": "100.0",
    "high": "101.0",
    "low": "99.0",
    "close": "100.5",
    "volume": "1000",
    "vwap": 100.2,
    "trade_count": 42,
}


# --------------------------------------------------------------------------
# Alan okuma
# --------------------------------------------------------------------------


def test_reads_from_object_and_dict_identically() -> None:
    obj = FakeBar(timestamp=TS, open=100, high=101, low=99, close=100.5, volume=1000)
    assert sdk_field(obj, "close") == 100.5
    assert sdk_field(DICT_BAR, "close") == "100.5"
    # Ham deger sozlukte string, nesnede float; sdk_float ikisini esitler.
    assert sdk_float(obj, "close") == sdk_float(DICT_BAR, "close") == pytest.approx(100.5)


def test_string_numbers_are_converted() -> None:
    """Alpaca parasal degerleri cogu zaman string dondurur."""
    assert sdk_float({"cash": "12345.67"}, "cash") == pytest.approx(12345.67)
    assert sdk_int({"daytrade_count": "3"}, "daytrade_count") == 3


def test_missing_and_unparsable_values_fall_back() -> None:
    assert sdk_float({}, "cash", default=-1.0) == -1.0
    assert sdk_float({"cash": None}, "cash") == 0.0
    assert sdk_float({"cash": "abc"}, "cash") == 0.0
    assert sdk_int({"n": "not-a-number"}, "n", default=7) == 7


def test_string_booleans_are_interpreted() -> None:
    """'false' string'i Python'da dogru sayilir - bu tuzagi kapatiyoruz."""
    assert sdk_bool({"blocked": "false"}, "blocked") is False
    assert sdk_bool({"blocked": "true"}, "blocked") is True
    assert sdk_bool({"blocked": False}, "blocked") is False
    assert sdk_bool({}, "blocked", default=True) is True


# --------------------------------------------------------------------------
# Bar cevrimi
# --------------------------------------------------------------------------


def test_bar_conversion_from_model_object() -> None:
    bar = AlpacaMarketData._to_bar(
        "SPY",
        FakeBar(
            timestamp=TS,
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=1000,
            vwap=100.2,
            trade_count=42,
        ),
    )
    assert bar.symbol == "SPY"
    assert bar.close == pytest.approx(100.5)
    assert bar.trade_count == 42


def test_bar_conversion_from_raw_dict() -> None:
    bar = AlpacaMarketData._to_bar("SPY", DICT_BAR)
    assert bar.close == pytest.approx(100.5)
    assert bar.volume == pytest.approx(1000)
    assert bar.trade_count == 42


def test_optional_fields_may_be_absent() -> None:
    bar = AlpacaMarketData._to_bar(
        "SPY", FakeBar(timestamp=TS, open=100, high=101, low=99, close=100.5, volume=1000)
    )
    assert bar.vwap is None
    assert bar.trade_count is None


def test_corrupt_bar_raises_instead_of_reaching_strategies() -> None:
    """Bozuk veri sessizce gecmemeli: strateji onu gercek sanip islem acar."""
    corrupt = dict(DICT_BAR, high="98.0")  # high < low
    with pytest.raises(DataError, match="gecersiz bar"):
        AlpacaMarketData._to_bar("SPY", corrupt)


def test_missing_timestamp_raises() -> None:
    with pytest.raises(DataError, match="zaman damgasi"):
        AlpacaMarketData._to_bar("SPY", dict(DICT_BAR, timestamp=None))


def test_none_value_falls_back_identically_for_dict_and_object() -> None:
    """Uyum katmaninin varlik sebebi bu esitlik.

    Alani None olan bir sozluk, alani None olan bir nesneyle ayni
    sonucu vermeli. Aksi halde `str(sdk_field(...))` cagrisi bir
    tarafta "USD", diger tarafta "None" uretirdi.
    """

    @dataclass
    class WithNone:
        currency: str | None = None

    assert sdk_field(WithNone(), "currency", "USD") == "USD"
    assert sdk_field({"currency": None}, "currency", "USD") == "USD"
    assert sdk_field({}, "currency", "USD") == "USD"
    assert str(sdk_field({"currency": None}, "currency", "USD")) == "USD"
