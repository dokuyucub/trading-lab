"""Olcum feed'inin rapordaki ve journal'daki izi (#17, AGENTS §11.4).

Codex karari A ve kabul sartlari (#17 6052081621). Kanitlananlar:

  * Rapor v3 `data_feed`'i YALNIZCA dogrulanmis manifestten alir. Config
    sessizce degistirilmez: `config.data.feed` ayarlanmis feed olarak ayri
    gorunur, `config_sha256` ayni semantik anlami tasir.
  * Iki feed farkliysa raporda KALICI bir uyari vardir; esitse yoktur.
  * Her maliyet senaryosunun GERCEK journal satiri (`runs.data_feed`)
    manifest feed'ini tasir.
  * Manifest feed'i bos, bilinmeyen ya da spec'le tutarsizsa olcum tek bir
    backtest kurulmadan durur.
  * Motor acik feed'i dogrular; `None` config'e duser (bu bir onbellek
    provenance dogrulamasi DEGILDIR).
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, get_args

import pytest

from test_baseline_run import DAYS, DOWNLOADED_AT, SESSIONS, breakout_session
from test_dataset import FakeBars, FakeCalendar
from tlab.backtest import baseline as baseline_module
from tlab.backtest.baseline import (
    CAVEATS,
    DEFAULT_SCENARIOS,
    FEED_MISMATCH_CAVEAT,
    REPORT_SCHEMA_VERSION,
    run_baseline,
)
from tlab.backtest.engine import Backtest, BacktestResult
from tlab.config import SUPPORTED_FEEDS, Config, load_config
from tlab.data.cached import CachedMarketData
from tlab.data.dataset import (
    DatasetIntegrityError,
    DatasetSpec,
    VerifiedBaseline,
    build_dataset,
    canonical_json,
    manifest_sha256,
    verify_baseline,
)
from tlab.errors import DataError
from tlab.journal.db import apply_migrations
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

REPO = Path(__file__).resolve().parents[1]


def verified_with_feed(tmp_path: Path, feed: str) -> VerifiedBaseline:
    """Temiz kirilimli, onayli, tek sembollu ve verilen feed'li veri kumesi."""
    bars = {"SPY": [bar for item in SESSIONS for bar in breakout_session(item)]}
    out = tmp_path / f"ds-{feed}"
    build_dataset(
        DatasetSpec(
            dataset_id=f"breakouts-{feed}",
            status="approved",
            symbols=("SPY",),
            start=DAYS[0],
            end=DAYS[-1],
            feed=feed,  # type: ignore[arg-type]
        ),
        bars_source=FakeBars(bars),
        calendar_source=FakeCalendar(SESSIONS),
        out_dir=out,
        downloaded_at=DOWNLOADED_AT,
        producer={"run_id": "test", "commit": "0" * 40},
    )
    return verify_baseline(out, manifest_sha256(out))


def config_with_feed(feed: str) -> Config:
    config = load_config(REPO)
    return config.model_copy(update={"data": config.data.model_copy(update={"feed": feed})})


@pytest.fixture
def journal_feeds(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Olcumun kurdugu HER backtest'in GERCEK journal satirindaki feed.

    Kosu bittiginde ayni bellek ici veritabanindan okunur; olcum o
    baglantiyi senaryo bitince kapatir.
    """
    seen: list[str] = []

    class Recording(Backtest):
        def run(self, start: datetime, end: datetime) -> BacktestResult:
            result = super().run(start, end)
            row = self.conn.execute(
                "SELECT data_feed FROM runs WHERE run_id = ?", (result.run_id,)
            ).fetchone()
            seen.append(str(row[0]))
            return result

    monkeypatch.setattr(baseline_module, "Backtest", Recording)
    yield seen


def expected_config_sha256(config: Config) -> str:
    """Olcumun kullandigi config: sembolleri manifestten, baska degisiklik yok."""
    measured = config.model_copy(update={"symbols": ("SPY",)})
    return hashlib.sha256(canonical_json(measured.semantic_dump())).hexdigest()


# --------------------------------------------------------------------------
# Rapor ve journal
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dataset_feed", "configured_feed"),
    [("sip", "iex"), ("iex", "sip"), ("iex", "iex"), ("sip", "sip")],
    ids=["sip-veri-iex-ayar", "iex-veri-sip-ayar", "esit-iex", "esit-sip"],
)
def test_the_report_and_journal_carry_the_manifest_feed(
    tmp_path: Path, journal_feeds: list[str], dataset_feed: str, configured_feed: str
) -> None:
    verified = verified_with_feed(tmp_path, dataset_feed)
    config = config_with_feed(configured_feed)
    report = run_baseline(verified, config, code_commit="c0ffee")

    assert report["report_schema"] == REPORT_SCHEMA_VERSION == 4
    assert report["data_feed"] == dataset_feed
    # Config sessizce degismez: ayarlanmis feed ayri gorunur, hash ayni anlam.
    assert report["config"]["data"]["feed"] == configured_feed
    assert report["config_sha256"] == expected_config_sha256(config)

    mismatch = FEED_MISMATCH_CAVEAT.format(data_feed=dataset_feed, configured=configured_feed)
    if dataset_feed == configured_feed:
        assert report["caveats"] == list(CAVEATS)
    else:
        assert report["caveats"] == [*CAVEATS, mismatch]

    # Her senaryonun gercek journal satiri manifest feed'ini tasir.
    assert journal_feeds == [dataset_feed] * len(DEFAULT_SCENARIOS)


def test_the_measured_feed_never_changes_the_config_or_its_hash(tmp_path: Path) -> None:
    """Ayni config, farkli feed'li iki veri kumesi: `config` ve hash'i ayni."""
    config = config_with_feed("iex")
    sip = run_baseline(verified_with_feed(tmp_path, "sip"), config, code_commit="c0ffee")
    iex = run_baseline(verified_with_feed(tmp_path, "iex"), config, code_commit="c0ffee")
    assert (sip["data_feed"], iex["data_feed"]) == ("sip", "iex")
    assert sip["config"] == iex["config"]
    assert sip["config_sha256"] == iex["config_sha256"]


def test_the_config_hash_follows_the_config_not_the_dataset(tmp_path: Path) -> None:
    """Codex 6063982093: hash, o kosunun GIRIS config'inin semantik hash'idir
    (semboller olcum evrenine normalize). Config gercekten degisirse
    (ayarlanmis feed iex -> sip) hash degisir; ayni veri kumesiyle bile."""
    verified = verified_with_feed(tmp_path, "sip")
    iex_config, sip_config = config_with_feed("iex"), config_with_feed("sip")
    with_iex = run_baseline(verified, iex_config, code_commit="c0ffee")
    with_sip = run_baseline(verified, sip_config, code_commit="c0ffee")
    assert with_iex["config_sha256"] == expected_config_sha256(iex_config)
    assert with_sip["config_sha256"] == expected_config_sha256(sip_config)
    assert with_iex["config_sha256"] != with_sip["config_sha256"]
    assert with_iex["data_feed"] == with_sip["data_feed"] == "sip"


# --------------------------------------------------------------------------
# P&L'den once: tutarsiz manifest feed'i
# --------------------------------------------------------------------------


def _with_manifest(verified: VerifiedBaseline, **changes: Any) -> VerifiedBaseline:
    manifest = copy.deepcopy(verified.manifest)
    for key, value in changes.items():
        if value is _DELETE:
            del manifest[key]
        else:
            manifest[key] = value
    return dataclasses.replace(verified, manifest=manifest)


_DELETE = object()

BAD_FEEDS: dict[str, Any] = {
    "bos": "",
    "bilinmeyen": "xyz",
    "spec-ile-uyusmuyor": "iex",
    "eksik": _DELETE,
}


@pytest.mark.parametrize("feed", list(BAD_FEEDS.values()), ids=list(BAD_FEEDS))
def test_an_inconsistent_manifest_feed_stops_before_any_backtest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feed: Any
) -> None:
    built: list[object] = []

    class Refusing(Backtest):
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)
            raise AssertionError("tutarsiz feed'le backtest kuruldu")

    monkeypatch.setattr(baseline_module, "Backtest", Refusing)
    verified = _with_manifest(verified_with_feed(tmp_path, "sip"), feed=feed)
    with pytest.raises(DatasetIntegrityError, match="olcum feed'i belirlenemedi"):
        run_baseline(verified, config_with_feed("iex"), code_commit="c0ffee")
    assert built == []


def test_an_invalid_spec_feed_is_never_returned(tmp_path: Path) -> None:
    """Spec'in kendisi gecersiz bir feed beyan ederse ozellik deger dondurmez."""
    verified = verified_with_feed(tmp_path, "sip")
    spec = dict(verified.manifest["spec"], feed="xyz")
    with pytest.raises(DatasetIntegrityError, match="manifestteki spec gecersiz"):
        _ = _with_manifest(verified, spec=spec, feed="xyz").data_feed


def test_the_feed_comes_from_the_verified_manifest(tmp_path: Path) -> None:
    verified = verified_with_feed(tmp_path, "sip")
    assert verified.manifest["feed"] == verified.manifest["spec"]["feed"] == "sip"
    assert verified.data_feed == "sip"


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------


def _engine(
    verified: VerifiedBaseline, config: Config, conn: sqlite3.Connection, **kwargs: Any
) -> Backtest:
    strategy = OpeningRangeBreakout(ORBParams())
    return Backtest(
        config=config.model_copy(update={"symbols": ("SPY",)}),
        strategy=strategy,
        market=CachedMarketData(verified.store()),
        conn=conn,
        opening_range_minutes=strategy.params.opening_range_minutes,
        sessions=verified.sessions,
        **kwargs,
    )


def _journal_feed(verified: VerifiedBaseline, config: Config, **kwargs: Any) -> str:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        apply_migrations(conn)
        first, last = min(verified.days), max(verified.days)
        result = _engine(verified, config, conn, **kwargs).run(
            datetime.combine(first, time(), UTC),
            datetime.combine(last, time(), UTC) + timedelta(days=1),
        )
        row = conn.execute(
            "SELECT data_feed FROM runs WHERE run_id = ?", (result.run_id,)
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def test_the_engine_journals_an_explicit_feed(tmp_path: Path) -> None:
    verified = verified_with_feed(tmp_path, "sip")
    assert _journal_feed(verified, config_with_feed("iex"), data_feed="sip") == "sip"


def test_without_an_explicit_feed_the_engine_falls_back_to_the_config(tmp_path: Path) -> None:
    """Geriye uyum: acik deger yoksa AYARLANMIS feed yazilir. Bu, onbellekteki
    barlarin gercek feed'inin dogrulamasi degildir (docstring de bunu soyler)."""
    verified = verified_with_feed(tmp_path, "sip")
    assert _journal_feed(verified, config_with_feed("iex")) == "iex"


@pytest.mark.parametrize(
    "feed", ["", "xyz", "SIP", " sip"], ids=["bos", "bilinmeyen", "buyuk-harf", "bosluklu"]
)
def test_the_engine_refuses_an_unsupported_explicit_feed(tmp_path: Path, feed: str) -> None:
    """Sessiz kabul yok: kurulumda, hicbir bar okunmadan durur."""
    verified = verified_with_feed(tmp_path, "sip")
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(DataError, match="desteklenmeyen data_feed"):
            _engine(verified, config_with_feed("iex"), conn, data_feed=feed)
    finally:
        conn.close()


def test_the_supported_feeds_have_one_source() -> None:
    """Ayar, veri kumesi tanimi ve motor ayni feed kumesine bakar."""
    declared = DatasetSpec.model_fields["feed"].annotation
    assert set(get_args(declared)) == SUPPORTED_FEEDS == {"iex", "sip"}
