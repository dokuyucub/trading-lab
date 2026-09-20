"""Katmanlar arasi sozlesme testleri.

Sistemin tamami protokoller uzerine kurulu: ust katmanlar Alpaca'yi
degil arayuzu goruyor. Bu, mimarinin gucu - ama ayni zamanda sessiz
bir kirilma noktasi: protokole bir metot eklenip uygulamalardan
birine eklenmezse, hata ancak o metodun ilk cagrildigi anda,
muhtemelen canli seansin ortasinda ortaya cikar.

Buradaki testler o kopuklugu derleme ve test zamaninda yakaliyor.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Protocol, get_type_hints

from tlab.core.clock import Clock, LiveClock, SimClock
from tlab.data.market import AlpacaMarketData, MarketData
from tlab.execution.alpaca_broker import AlpacaBroker, AlpacaMarketClock
from tlab.execution.broker import Broker, MarketClock
from tlab.strategies.base import Strategy
from tlab.strategies.orb import OpeningRangeBreakout

# --------------------------------------------------------------------------
# Statik uyum
# --------------------------------------------------------------------------
#
# Asagidaki fonksiyonlar calisma aninda hicbir sey yapmiyor; varlik
# sebepleri mypy'nin onlari denetlemesi. Uygulama protokolden
# ayrisirsa tip denetimi tam bu satirlarda duruyor.


def _as_broker(broker: Broker) -> Broker:
    return broker


def _as_market_data(market: MarketData) -> MarketData:
    return market


def _as_strategy(strategy: Strategy) -> Strategy:
    return strategy


def _as_clock(clock: Clock) -> Clock:
    return clock


def _as_market_clock(clock: MarketClock) -> MarketClock:
    return clock


def test_alpaca_broker_satisfies_the_broker_protocol() -> None:
    broker = AlpacaBroker("PKTEST", "secret", paper=True)
    assert _as_broker(broker) is broker


def test_alpaca_market_data_satisfies_the_market_data_protocol() -> None:
    market = AlpacaMarketData("PKTEST", "secret", feed="iex")
    assert _as_market_data(market) is market


def test_simulation_components_satisfy_the_same_protocols(tmp_path: Path) -> None:
    """Backtest ve canli AYNI sozlesmeyi paylasmali.

    Simulasyon brokeri ile canli broker ayni protokole uymazsa,
    backtest'te olculen sey canlida calisacak olan DEGILDIR ve
    ogrenilen her sey dogrulanamaz hale gelir.
    """
    from tlab.backtest.sim_broker import SimBroker
    from tlab.data.cache import BarCache
    from tlab.data.cached import CachedMarketData

    sim = SimBroker()
    assert _as_broker(sim) is sim
    assert_signatures_match(Broker, SimBroker)

    cached = CachedMarketData(BarCache(tmp_path))
    assert _as_market_data(cached) is cached
    assert_signatures_match(MarketData, CachedMarketData)


def test_orb_satisfies_the_strategy_protocol() -> None:
    strategy = OpeningRangeBreakout()
    assert _as_strategy(strategy) is strategy


def test_clocks_satisfy_the_clock_protocol() -> None:
    live = LiveClock()
    assert _as_clock(live) is live


def test_alpaca_clock_satisfies_the_market_clock_protocol() -> None:
    from datetime import UTC, datetime

    clock = AlpacaMarketClock(
        is_open=True, next_open=datetime.now(UTC), next_close=datetime.now(UTC)
    )
    assert _as_market_clock(clock) is clock


# --------------------------------------------------------------------------
# Calisma anindaki uyum
# --------------------------------------------------------------------------


def protocol_methods(protocol: type) -> list[str]:
    """Protokolun tanimladigi genel metotlar."""
    inherited = set(dir(Protocol))
    return sorted(
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and name not in inherited and callable(value)
    )


def assert_signatures_match(protocol: type, implementation: type) -> None:
    """Uygulamanin protokoldeki her metodu ayni imzayla tasidigini dogrular.

    Yalnizca metodun VARLIGI yetmez: parametre adi degisirse anahtar
    kelimeyle yapilan cagri calisma aninda kirilir.
    """
    for name in protocol_methods(protocol):
        assert hasattr(implementation, name), f"{implementation.__name__}.{name} eksik"

        expected = inspect.signature(getattr(protocol, name))
        actual = inspect.signature(getattr(implementation, name))
        expected_params = [p for p in expected.parameters if p != "self"]
        actual_params = [p for p in actual.parameters if p != "self"]
        assert expected_params == actual_params, (
            f"{implementation.__name__}.{name} parametreleri protokolden farkli: "
            f"{actual_params} != {expected_params}"
        )


def test_alpaca_broker_method_signatures_match() -> None:
    assert_signatures_match(Broker, AlpacaBroker)


def test_alpaca_market_data_method_signatures_match() -> None:
    assert_signatures_match(MarketData, AlpacaMarketData)


def test_broker_protocol_surface_is_complete() -> None:
    """Protokolun kapsami beklenen yetenekleri iceriyor mu.

    Bu liste bilincli olarak elle yazildi: bir metot protokolden
    sessizce dusurulurse test bunu soyluyor.
    """
    assert protocol_methods(Broker) == [
        "cancel_open_orders",
        "close_position",
        "get_account",
        "get_market_clock",
        "get_positions",
        "list_fills",
        "list_open_orders",
        "submit_bracket",
    ]


def test_market_data_protocol_surface_is_complete() -> None:
    assert protocol_methods(MarketData) == ["bars", "latest_quote"]


def test_fakes_used_in_tests_match_the_protocols() -> None:
    """Testlerdeki sahteler de ayni sozlesmeye tabi.

    Sahteler protokolden ayrisirsa testler yesil kalirken gercek
    sistem kirilabilirdi - testin verdigi guven yanlis olurdu.
    """
    from test_runner import FakeBroker, FakeMarket

    assert_signatures_match(Broker, FakeBroker)
    assert_signatures_match(MarketData, FakeMarket)


def test_sim_and_live_clocks_agree_on_the_contract() -> None:
    """Backtest ve canli ayni Clock sozlesmesini paylasmali."""
    from datetime import UTC, datetime

    sim = SimClock(datetime(2026, 1, 5, tzinfo=UTC))
    assert _as_clock(sim) is sim
    assert get_type_hints(LiveClock.now) == get_type_hints(SimClock.now)
    assert sim.now().tzinfo is not None
    assert LiveClock().now().tzinfo is not None
