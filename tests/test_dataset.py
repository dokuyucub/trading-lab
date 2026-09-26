"""Sabit veri kumesi: bolme, manifest, dogrulama ve holdout'un kapali kalmasi.

En onemli test `test_verifying_the_baseline_never_touches_the_holdout`.
Holdout'un ilk olcumde kullanilmamasi yazili bir kural olarak
kalsaydi, bu projedeki diger yazili ama denetlenmeyen kurallar gibi
bir gun kirilirdi. Test, holdout dizinine yonelik HER dosya acma ve
dizin listeleme olayini dogrudan yakalar.

Yontem notu: `chmod 000` KULLANILMIYOR. Konteynerde root olarak
kosuyoruz ve root dosya izinlerini yok sayar - o test hicbir sey
olcmeden gecerdi. Python'un denetim kancasi (`sys.addaudithook`)
izinlerden bagimsiz olarak her `open` ve `os.scandir` olayini gorur.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from fs_audit import filesystem_access, touched_under
from tlab.core.calendar import TradingSession
from tlab.core.types import Bar, Timeframe
from tlab.data.dataset import (
    DatasetIntegrityError,
    DatasetSpec,
    build_dataset,
    classify_sessions,
    content_sha256,
    file_sha256,
    manifest_sha256,
    split_sessions,
    verify_baseline,
)
from tlab.errors import DataError

NY = ZoneInfo("America/New_York")


def session(day: date, close: time = time(16, 0)) -> TradingSession:
    return TradingSession(
        day=day,
        open=datetime.combine(day, time(9, 30), NY).astimezone(UTC),
        close=datetime.combine(day, close, NY).astimezone(UTC),
    )


def minute_bars(symbol: str, window: TradingSession, *, skip: int = 0) -> list[Bar]:
    """Seans boyunca dakikalik barlar; `skip` sondan eksik dakika."""
    bars: list[Bar] = []
    moment = window.open
    price = 100.0
    while moment < window.close - timedelta(minutes=skip):
        bars.append(
            Bar(
                symbol=symbol,
                ts=moment,
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price + 0.1,
                volume=1_000,
                vwap=price,
                trade_count=10,
            )
        )
        moment += timedelta(minutes=1)
        price += 0.01
    return bars


def weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


class FakeCalendar:
    def __init__(self, sessions: list[TradingSession]) -> None:
        self.sessions = sessions

    def get_calendar(self, start: date, end: date) -> list[TradingSession]:
        return [item for item in self.sessions if start <= item.day <= end]


class FakeBars:
    def __init__(self, by_symbol: dict[str, list[Bar]]) -> None:
        self.by_symbol = by_symbol

    def bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None
    ) -> list[Bar]:
        return [
            bar
            for bar in self.by_symbol[symbol]
            if start <= bar.ts and (end is None or bar.ts < end)
        ]


DAYS = weekdays(date(2026, 3, 2), 10)
SESSIONS = [session(day) for day in DAYS]
DOWNLOADED_AT = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
PRODUCER = {"run_id": "test", "commit": "0" * 40}


def spec(**changes: Any) -> DatasetSpec:
    base: dict[str, Any] = {
        "dataset_id": "test-set",
        "symbols": ["SPY"],
        "start": DAYS[0],
        "end": DAYS[-1],
    }
    base.update(changes)
    return DatasetSpec.model_validate(base)


def sources(symbols: tuple[str, ...] = ("SPY",)) -> tuple[FakeBars, FakeCalendar]:
    bars = {
        symbol: [bar for item in SESSIONS for bar in minute_bars(symbol, item)]
        for symbol in symbols
    }
    return FakeBars(bars), FakeCalendar(SESSIONS)


def build(tmp_path: Path, name: str = "ds", **spec_changes: Any) -> tuple[Path, dict[str, Any]]:
    bars, calendar = sources(tuple(spec_changes.get("symbols", ("SPY",))))
    out = tmp_path / name
    manifest = build_dataset(
        spec(**spec_changes),
        bars_source=bars,
        calendar_source=calendar,
        out_dir=out,
        downloaded_at=DOWNLOADED_AT,
        producer=PRODUCER,
    )
    return out, manifest


# --------------------------------------------------------------------------
# Bolme
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("count", "kept", "held"), [(10, 8, 2), (12, 9, 3), (5, 4, 1), (2, 1, 1)])
def test_split_is_chronological_and_rounds_the_holdout_up(count: int, kept: int, held: int) -> None:
    """Son %20 holdout, yukari yuvarlanarak.

    Tereddutte daha fazlasini ayirmak dogru taraf: fazla ayrilan veri
    sonradan kullanilabilir, erken bakilan veri geri alinamaz.
    """
    items = [session(day) for day in weekdays(date(2026, 3, 2), count)]
    baseline, holdout = split_sessions(list(reversed(items)), 0.20)
    assert len(baseline) == kept
    assert len(holdout) == held
    assert max(item.day for item in baseline) < min(item.day for item in holdout)


def test_too_few_sessions_cannot_be_split() -> None:
    with pytest.raises(DataError, match="bolunemez"):
        split_sessions([session(DAYS[0])], 0.20)


def test_a_session_not_yet_settled_is_incomplete() -> None:
    last = SESSIONS[-1]
    downloaded = last.close + timedelta(minutes=5)
    verdicts = classify_sessions(SESSIONS, downloaded_at=downloaded, settle_minutes=20)
    assert not verdicts[-1].complete
    assert "kapanmamisti" in verdicts[-1].reason
    assert all(item.complete for item in verdicts[:-1])


def test_a_symbol_without_bars_does_not_move_the_holdout_boundary(tmp_path: Path) -> None:
    """Codex B2: bolme yalnizca TAKVIME bakar.

    Eskiden bir sembolun hic bari olmayan gun bolmeden dusuyor ve
    holdout siniri o bosluga gore kayiyordu. Artik gun bolmede kalir;
    veri eksikligi kalite olcusunde gorunur ve olcumu durdurur.
    """
    full = {
        "SPY": [bar for item in SESSIONS for bar in minute_bars("SPY", item)],
        "QQQ": [bar for item in SESSIONS for bar in minute_bars("QQQ", item)],
    }
    gap = {**full, "QQQ": [b for item in SESSIONS[1:] for b in minute_bars("QQQ", item)]}

    splits = []
    for name, bars in (("full", full), ("gap", gap)):
        manifest = build_dataset(
            spec(symbols=["SPY", "QQQ"]),
            bars_source=FakeBars(bars),
            calendar_source=FakeCalendar(SESSIONS),
            out_dir=tmp_path / name,
            downloaded_at=DOWNLOADED_AT,
            producer=PRODUCER,
        )
        splits.append(manifest["split"])

    assert splits[0]["baseline"] == splits[1]["baseline"]
    assert splits[0]["holdout"] == splits[1]["holdout"]

    first = manifest["quality"]["sessions"][DAYS[0].isoformat()]
    assert not first["eligible"]
    assert first["symbols"]["QQQ"]["reasons"] == ["seans ici bar yok"]
    assert first["symbols"]["SPY"]["reasons"] == []


def test_missing_minutes_do_not_move_the_split(tmp_path: Path) -> None:
    """Eksik dakikalar kalite raporunda sayilir, bolmeyi DEGISTIRMEZ.

    Aksi halde bolme sinirinin yeri verinin gurultusune bagli olurdu.
    """
    bars = {"SPY": [bar for item in SESSIONS for bar in minute_bars("SPY", item, skip=7)]}
    manifest = build_dataset(
        spec(),
        bars_source=FakeBars(bars),
        calendar_source=FakeCalendar(SESSIONS),
        out_dir=tmp_path / "ds",
        downloaded_at=DOWNLOADED_AT,
        producer=PRODUCER,
    )
    assert len(manifest["split"]["baseline"]) == 8
    assert manifest["quality"]["symbols"]["SPY"]["missing_regular_minutes"] == 7 * 10


def test_a_half_day_is_measured_against_its_official_close(tmp_path: Path) -> None:
    """Yarim gunde borsa 13:00'te kapanir; eksik dakika 390'a gore degil 210'a gore.

    Sabit 16:00 varsayan bir kural bu gunde 180 "eksik" dakika
    sayardi - veri tam olsa bile.
    """
    half = [session(DAYS[0], close=time(13, 0)), *SESSIONS[1:]]
    bars = {"SPY": [bar for item in half for bar in minute_bars("SPY", item)]}
    manifest = build_dataset(
        spec(),
        bars_source=FakeBars(bars),
        calendar_source=FakeCalendar(half),
        out_dir=tmp_path / "ds",
        downloaded_at=DOWNLOADED_AT,
        producer=PRODUCER,
    )
    assert DAYS[0].isoformat() in manifest["sessions"]["complete"]
    assert manifest["quality"]["symbols"]["SPY"]["missing_regular_minutes"] == 0
    half_day = manifest["quality"]["sessions"][DAYS[0].isoformat()]
    assert half_day["eligible"], "tam veri yarim gunde uygun sayilmali"
    assert half_day["symbols"]["SPY"]["close_window_bars"] == 10


# --------------------------------------------------------------------------
# Kalite politikasi (Codex B2)
# --------------------------------------------------------------------------


def quality_of(tmp_path: Path, bars: list[Bar], **policy: Any) -> dict[str, Any]:
    manifest = build_dataset(
        spec(quality=policy) if policy else spec(),
        bars_source=FakeBars({"SPY": bars}),
        calendar_source=FakeCalendar(SESSIONS),
        out_dir=tmp_path / "q",
        downloaded_at=DOWNLOADED_AT,
        producer=PRODUCER,
    )
    quality: dict[str, Any] = manifest["quality"]
    return quality


def test_missing_opening_minutes_make_the_session_ineligible(tmp_path: Path) -> None:
    """Acilis araligi eksik dakikalarla olculurse yanlis sinyal uretir."""
    bars = [
        bar
        for item in SESSIONS
        for bar in minute_bars("SPY", item)
        if not (item.day == DAYS[1] and bar.ts < item.open + timedelta(minutes=5))
    ]
    quality = quality_of(tmp_path, bars)
    entry = quality["sessions"][DAYS[1].isoformat()]
    assert not entry["eligible"]
    assert entry["symbols"]["SPY"]["missing_open_window"] == 5
    assert "acilis penceresinde 5 dk eksik" in entry["symbols"]["SPY"]["reasons"][0]


def test_no_bar_before_the_bell_makes_the_session_ineligible(tmp_path: Path) -> None:
    """Kapanistan onceki pencerede bar yoksa gun sonu kapatmasi dolamaz."""
    bars = [
        bar
        for item in SESSIONS
        for bar in minute_bars("SPY", item, skip=10 if item.day == DAYS[2] else 0)
    ]
    quality = quality_of(tmp_path, bars)
    entry = quality["sessions"][DAYS[2].isoformat()]
    assert not entry["eligible"]
    assert entry["symbols"]["SPY"]["close_window_bars"] == 0


def test_heavily_missing_data_is_ineligible_even_with_open_and_close(tmp_path: Path) -> None:
    """Codex'in sinamasi: seans basina yuzlerce eksik dakika 'tamamlanmis' sayiliyordu."""
    bars = [
        bar
        for item in SESSIONS
        for index, bar in enumerate(minute_bars("SPY", item))
        if index < 20 or index % 3 == 0 or index > 380
    ]
    quality = quality_of(tmp_path, bars)
    assert quality["ineligible"] == {"baseline": 8, "holdout": 2}
    reasons = quality["sessions"][DAYS[0].isoformat()]["symbols"]["SPY"]["reasons"]
    assert any("eksik dakika orani" in reason for reason in reasons)


def test_the_quality_policy_is_part_of_the_fixed_spec(tmp_path: Path) -> None:
    """Politika spec hash'ine girer: sonradan gevsetmek yeni bir veri kumesidir."""
    _, strict = build(tmp_path, name="a")
    _, loose = build(tmp_path, name="b", quality={"max_missing_fraction": 0.5})
    assert strict["spec_sha256"] != loose["spec_sha256"]
    assert loose["quality"]["policy"]["max_missing_fraction"] == 0.5


def test_an_inconsistent_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="acilis penceresinden buyuk"):
        spec(quality={"open_window_minutes": 5, "max_missing_open_window": 6})


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


REQUIRED_MANIFEST_FIELDS = {
    "dataset_id",
    "producer",
    "feed",
    "range_utc",
    "exchange_timezone",
    "timeframe",
    "symbols",
    "adjustment",
    "downloaded_at",
    "quality",
    "files",
    "retention_days",
    "expires_at",
    "split",
    "sessions",
}
"""Codex'in #17'de saydigi alanlar. Biri dusurulurse bu test kirilir."""


def test_manifest_carries_every_agreed_field(tmp_path: Path) -> None:
    _, manifest = build(tmp_path)
    assert set(manifest) >= REQUIRED_MANIFEST_FIELDS
    assert manifest["split"]["unit"] == "session"
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])


def test_baseline_and_holdout_are_written_to_separate_directories(tmp_path: Path) -> None:
    out, manifest = build(tmp_path)
    splits = {entry["split"]: entry for entry in manifest["files"]}
    assert splits["baseline"]["path"].startswith("baseline/")
    assert splits["holdout"]["path"].startswith("holdout/")
    assert splits["baseline"]["bars"] == 8 * 390
    assert splits["holdout"]["bars"] == 2 * 390
    # Manifestin soyledigi yer ile diskteki yer ayni olmali.
    assert (out / splits["baseline"]["path"]).is_file()
    assert (out / splits["holdout"]["path"]).is_file()


def test_the_same_inputs_produce_the_same_manifest(tmp_path: Path) -> None:
    """Ayni kaynak + ayni indirme ani -> bayt bayt ayni manifest."""
    first, _ = build(tmp_path, "a")
    second, _ = build(tmp_path, "b")
    assert manifest_sha256(first) == manifest_sha256(second)


def test_content_hash_ignores_order_and_detects_a_single_changed_price() -> None:
    bars = minute_bars("SPY", SESSIONS[0])
    assert content_sha256(bars) == content_sha256(list(reversed(bars)))
    changed = [*bars[:-1], bars[-1].model_copy(update={"close": bars[-1].close + 0.01})]
    assert content_sha256(changed) != content_sha256(bars)


def test_build_refuses_to_write_over_an_existing_dataset(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    bars, calendar = sources()
    with pytest.raises(DataError, match="bos degil"):
        build_dataset(
            spec(),
            bars_source=bars,
            calendar_source=calendar,
            out_dir=out,
            downloaded_at=DOWNLOADED_AT,
            producer=PRODUCER,
        )


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"symbols": ["SPY", "spy"]}, "tekrar"),
        ({"dataset_id": "Bad Id"}, "dataset_id"),
        ({"start": DAYS[-1], "end": DAYS[0]}, "baslangic"),
        ({"exchange_timezone": "Mars/Olympus"}, "exchange_timezone"),
        ({"holdout_fraction": 0.0}, "holdout_fraction"),
    ],
)
def test_a_bad_spec_is_rejected(changes: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        spec(**changes)


def test_adjustment_is_recorded_as_requested(tmp_path: Path) -> None:
    """Manifest, istegin garanti ettigi degeri tasir - varsayilani degil."""
    _, manifest = build(tmp_path, adjustment="split")
    assert manifest["adjustment"] == "split"


# --------------------------------------------------------------------------
# Dogrulama
# --------------------------------------------------------------------------


def test_verification_returns_only_baseline_sessions(tmp_path: Path) -> None:
    out, manifest = build(tmp_path)
    verified = verify_baseline(out, manifest_sha256(out))
    assert set(verified.bars) == set(manifest["symbols"])
    declared = {f["symbol"]: f["bars"] for f in manifest["files"] if f["split"] == "baseline"}
    assert {symbol: len(bars) for symbol, bars in verified.bars.items()} == declared
    assert not hasattr(verified, "root"), "dogrulanmis baseline dosya yolu tasimamali"
    assert [day.isoformat() for day in verified.days] == manifest["split"]["baseline"]


def test_a_wrong_manifest_hash_stops_everything(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    with pytest.raises(DatasetIntegrityError, match="manifest hash"):
        verify_baseline(out, "0" * 64)


@pytest.mark.parametrize("expected", ["", "latest", "abc", "g" * 64])
def test_there_is_no_way_to_ask_for_the_latest_dataset(tmp_path: Path, expected: str) -> None:
    """ "En son veri kumesini al" diye bir yol yok: kesin hash zorunlu."""
    out, _ = build(tmp_path)
    with pytest.raises(DatasetIntegrityError, match="SHA256"):
        verify_baseline(out, expected)


def test_a_single_changed_byte_in_a_baseline_file_stops_everything(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    target = out / "baseline" / "SPY" / "1Min.parquet"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0x01
    target.write_bytes(bytes(data))
    with pytest.raises(DatasetIntegrityError, match="hash'i uyusmuyor"):
        verify_baseline(out, manifest_sha256(out))


def test_a_missing_baseline_file_stops_everything(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    (out / "baseline" / "SPY" / "1Min.parquet").unlink()
    with pytest.raises(DatasetIntegrityError, match="eksik"):
        verify_baseline(out, manifest_sha256(out))


def test_an_undeclared_file_in_the_baseline_stops_everything(tmp_path: Path) -> None:
    """Manifestte olmayan bir dosya, veri kumesine sonradan bir sey eklendi demek."""
    out, _ = build(tmp_path)
    (out / "baseline" / "SPY" / "extra.parquet").write_bytes(b"x")
    with pytest.raises(DatasetIntegrityError, match="manifestte olmayan"):
        verify_baseline(out, manifest_sha256(out))


def test_a_manifest_path_cannot_escape_the_dataset(tmp_path: Path) -> None:
    out, manifest = build(tmp_path)
    manifest["files"][0]["path"] = "../outside.parquet"
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (out / "manifest.json").write_bytes(raw)
    with pytest.raises(DatasetIntegrityError, match="guvensiz yol"):
        verify_baseline(out, hashlib.sha256(raw).hexdigest())


# --------------------------------------------------------------------------
# Holdout - dosyanin asil sebebi
# --------------------------------------------------------------------------


def test_verifying_the_baseline_never_touches_the_holdout(tmp_path: Path) -> None:
    """Holdout'a yonelik tek bir dosya acma ya da listeleme olmamali.

    Yalnizca "holdout okunmadi" demek yetmez: listelemek de bir
    bakistir (hangi semboller, kac dosya), hash'lemek de okumaktir.
    Ucu de yasak.
    """
    out, _ = build(tmp_path)
    expected = manifest_sha256(out)

    with filesystem_access() as seen:
        verify_baseline(out, expected)

    assert seen, "denetim kancasi hicbir olay gormedi - test kendi kendini olcmuyor"
    touched = touched_under(seen, out / "holdout")
    assert not touched, f"holdout'a erisildi: {touched}"


@pytest.mark.parametrize("peek", ["read", "list", "hash"])
def test_the_audit_hook_would_catch_any_look_at_the_holdout(tmp_path: Path, peek: str) -> None:
    """Kapinin kendi sinavi: holdout'a UC tur bakisin ucu de yakalanir mi.

    Yalnizca okumayi yakalayan bir kapi, "hangi semboller holdout'ta,
    kac dosya var" diye listeleyen bir kodu kacirirdi.
    """
    out, _ = build(tmp_path)
    holdout = out / "holdout"
    target = holdout / "SPY" / "1Min.parquet"

    with filesystem_access() as seen:
        if peek == "read":
            target.read_bytes()
        elif peek == "list":
            list(holdout.rglob("*"))
        else:
            file_sha256(target)

    assert touched_under(seen, holdout), f"{peek} yakalanmadi"


# --------------------------------------------------------------------------
# Takma adlar (Codex B3)
#
# Denetim kancasi CAGRILAN yolu gorur, cozuldugu yeri degil. baseline/
# altindaki bir symlink holdout/'taki bir dosyaya cozulurse kanca
# yalnizca baseline yolunu gorur ve "holdout'a dokunulmadi" der -
# Codex tam olarak bunu gosterdi. Savunma kancada degil yapida:
# takma adlar hic okunmadan reddedilir.
# --------------------------------------------------------------------------


def _move_to_holdout(out: Path) -> tuple[Path, Path]:
    """Baseline dosyasini holdout/'a tasir; eski yeri bos kalir."""
    original = out / "baseline" / "SPY" / "1Min.parquet"
    borrowed = out / "holdout" / "borrowed.parquet"
    original.rename(borrowed)
    return original, borrowed


def _rejected_without_touching_holdout(out: Path, match: str) -> None:
    with filesystem_access() as seen, pytest.raises(DatasetIntegrityError, match=match):
        verify_baseline(out, manifest_sha256(out))
    touched = touched_under(seen, out / "holdout")
    assert not touched, f"reddedilmeden once holdout okundu: {touched}"


def test_a_file_symlink_into_the_holdout_is_rejected(tmp_path: Path) -> None:
    """Codex'in senaryosu: manifest ve hash degismeden holdout okunuyordu."""
    out, _ = build(tmp_path)
    original, borrowed = _move_to_holdout(out)
    original.symlink_to(borrowed)
    _rejected_without_touching_holdout(out, "symlink")


def test_a_directory_symlink_into_the_holdout_is_rejected(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    folder = out / "baseline" / "SPY"
    moved = out / "holdout" / "SPY-baseline"
    folder.rename(moved)
    folder.symlink_to(moved, target_is_directory=True)
    _rejected_without_touching_holdout(out, "symlink")


def test_the_whole_baseline_directory_cannot_be_a_symlink(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    baseline = out / "baseline"
    moved = out / "holdout" / "old-baseline"
    baseline.rename(moved)
    baseline.symlink_to(moved, target_is_directory=True)
    _rejected_without_touching_holdout(out, "gercek bir dizin")


def test_a_hardlink_shared_with_the_holdout_is_rejected(tmp_path: Path) -> None:
    """Hardlink'te iki ad da 'gercek': hangisinin asil oldugu bilinemez."""
    out, _ = build(tmp_path)
    original, borrowed = _move_to_holdout(out)
    original.hardlink_to(borrowed)
    _rejected_without_touching_holdout(out, "hardlink")


def test_a_symlinked_manifest_is_rejected(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    manifest = out / "manifest.json"
    moved = out / "holdout" / "manifest.json"
    manifest.rename(moved)
    manifest.symlink_to(moved)
    with pytest.raises(DatasetIntegrityError, match="symlink"):
        verify_baseline(out, file_sha256(moved))


def test_a_special_file_in_the_baseline_is_rejected(tmp_path: Path) -> None:
    out, _ = build(tmp_path)
    os.mkfifo(out / "baseline" / "SPY" / "pipe")
    with pytest.raises(DatasetIntegrityError, match="ozel dosya"):
        verify_baseline(out, manifest_sha256(out))


def test_the_bytes_that_were_hashed_are_the_bytes_that_are_used(tmp_path: Path) -> None:
    """Dogrulamadan SONRA dosyayi degistirmek olcumu etkilemez.

    Barlar dogrulanan baytlardan cozulup bellekte tutuluyor; olcum
    dosyayi bir daha okumuyor. Dosya silinse bile sonuc ayni.
    """
    out, _ = build(tmp_path)
    verified = verify_baseline(out, manifest_sha256(out))
    before = verified.store().load("SPY", Timeframe.M1)
    (out / "baseline" / "SPY" / "1Min.parquet").unlink()
    assert verified.store().load("SPY", Timeframe.M1) == before
    assert before, "bos baseline ile test hicbir sey olcmez"


def test_building_the_dataset_computes_no_performance(tmp_path: Path) -> None:
    """Bolme, tek bir P&L satiri hesaplanmadan yapilir.

    Bunu yapisal olarak garanti eden sey import grafigi: veri kumesi
    modulu backtest'i, ogrenme katmanini ya da stratejileri ice
    aktarmiyor. Mimari testte ayrica denetleniyor; burada davranis
    olarak: manifestte performansla ilgili tek bir alan yok.
    """
    _, manifest = build(tmp_path)
    text = json.dumps(manifest).lower()
    for word in ("pnl", "p&l", "expectancy", "return", "drawdown", "sharpe", "profit"):
        assert word not in text, f"manifest performans bilgisi tasiyor: {word}"
