"""Sabit, dogrulanabilir ve onceden bolunmus piyasa verisi kumesi.

Bu modulun varlik sebebi tek bir risk: sonucu gordukten sonra ayni
veriye bakarak stratejiyi ayarlamak ve bunu basari diye sunmak. Ilk
kotu sonuctan sonra bu baski en guclu halindedir, ve yalnizca yazili
bir kurala guvenmek yetmez - bu projede yazili ama denetlenmeyen her
kural bir sekilde kirildi.

Bu yuzden ayrim VERI ALINIRKEN yapilir, tek bir P&L satiri
hesaplanmadan:

    tamamlanmis seanslarin ilk %80'i  ->  baseline/   (ilk olcum)
    son %20'si                         ->  holdout/    (ACILMAZ)

Ilk olcum yalnizca baseline/'i gorur. Yukleyici holdout/ dizinine
dokunmaz - listelemez, okumaz, hash'lemez. Bunun guvencesi iki
parcali:

  * Yapisal: dosyalar TEK kez okunur. Hash'lenen baytlar bellekte
    cozulur ve olcume o barlar verilir; olcum hicbir dosya yolu
    almaz, veri kumesi dizinini bir daha acmaz. Symlink, hardlink ve
    ozel dosyalar reddedilir: baseline/ altindaki bir takma ad
    holdout/'taki bir dosyaya cozulemez.
  * Olcum: testler Python'un denetim kancasiyla holdout/ altinda
    hicbir `open`/`scandir`/`listdir` olmadigini dogrular. Kanca
    YALNIZCA Python seviyesindeki olaylari gorur; yerel kutuphanelerin
    kendi I/O'sunu gordugu iddia edilmez - bu yuzden yapisal kisim
    ayrica var.

Ikinci risk sessiz degisim: "ayni veri" sanilan seyin aslinda farkli
olmasi. Her dosyanin SHA256'si manifestte; yukleyici kesin bir
manifest hash'i ister ("en sonuncuyu al" yok) ve tek bir bayt bile
tutmazsa durur.

Bu modul ag erisimi yapmaz ve duvar saatine bakmaz: veri ve takvim
kaynaklari ile indirme zamani disaridan verilir.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import stat
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tlab.core.calendar import TradingSession
from tlab.core.types import Bar, Timeframe
from tlab.data.cache import BarCache, bars_from_frame
from tlab.errors import DataError

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
BASELINE_DIR = "baseline"
HOLDOUT_DIR = "holdout"


class DatasetIntegrityError(DataError):
    """Veri kumesi manifestiyle uyusmuyor. Devam etmek, dogrulanmamis
    veriyle olcum yapmak demek olurdu."""


class DatasetStatusError(DataError):
    """Veri kumesi tanimi bu islem icin onayli degil (draft/pilot)."""


class DatasetQualityError(DataError):
    """Veri, onceden sabitlenmis kalite politikasini karsilamiyor.

    Olcum P&L URETMEDEN durur: eksik acilis dakikalari yanlis bir
    acilis araligi, eksik kapanis barlari dolamayan bir gun sonu
    kapatmasi demektir. Bu veriyle cikan sonuc stratejiyi degil veri
    boslugunu olcerdi.
    """


# ---------------------------------------------------------------------------
# Tanim
# ---------------------------------------------------------------------------


class QualityPolicy(BaseModel):
    """Bir seansin OLCULEBILIR sayilmasi icin veri sartlari.

    Spec'in parcasi: spec hash'ine girer ve INDIRMEDEN ONCE sabitlenir.
    Sonuc gorulduken sonra gevsetilemez; degistirmek yeni bir
    dataset_id gerektirir.

    Takvimsel tamamlanma ile veri uygunlugu AYRI seylerdir (Codex B2).
    Bolme yalnizca takvime bakar; bir sembolun verisi eksik diye bir
    gun bolmeden dusmez - aksi halde holdout sinirinin yeri verinin
    gurultusune bagli olurdu. Kalite ayrica olculur ve olcum kapisi
    olarak uygulanir.

    Dakika kurallari yalnizca 1Min veride anlamlidir; diger periyotlarda
    yalnizca "seans icinde en az bir bar" aranir.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    open_window_minutes: int = Field(default=15, ge=1, le=120)
    """Acilistan sonraki pencere. Acilis araligina dayanan bir strateji
    bu dakikalar eksikse yanlis bir aralik olcer."""

    max_missing_open_window: int = Field(default=0, ge=0)
    """Acilis penceresinde izin verilen eksik dakika. Varsayilan sifir:
    tek bir eksik dakika acilis araliginin tepe/dibini bozabilir ve veri
    yoklugu "islem olmadi" diye varsayilamaz."""

    close_window_minutes: int = Field(default=10, ge=1, le=120)
    """Kapanistan onceki pencere: her sembolde EN AZ BIR bar olmali.
    Yoksa gun sonu kapatmasi dolacak bir fiyat bulamaz. Olcum bu
    degerin gun sonu tamponundan buyuk olmadigini ayrica denetler."""

    max_missing_fraction: float = Field(default=0.10, ge=0.0, le=1.0)
    """Seans genelinde eksik dakika orani."""

    max_ineligible_sessions: Literal[0] = 0
    """Baseline'da izin verilen uygun olmayan seans sayisi: YALNIZCA sifir.

    Tek bir uygun olmayan seans olcumu P&L uretmeden durdurur. Gun
    dislama yolu bilincli olarak YOK (Codex, #19): dislanan gunun barlari
    sonraki gunlerin gecmis penceresinde kalir ve hesaplari etkiler;
    ayrica eksik gunu atmak ornekleme veriye bakarak mudahale etmektir.
    Tolerans ileride gerekirse ayri tasarim ve test ister.
    """

    @model_validator(mode="after")
    def _consistent(self) -> QualityPolicy:
        if self.max_missing_open_window > self.open_window_minutes:
            msg = "max_missing_open_window acilis penceresinden buyuk olamaz"
            raise ValueError(msg)
        return self


class DatasetSpec(BaseModel):
    """Veri kumesinin ONCEDEN sabitlenmis tanimi.

    Tarihler ve semboller bir dosyada durur ve commit edilir;
    indirme aninda serbest girdi olarak verilmez. Sebep: sonuc
    gorulduken sonra "bir de su tarihlere bakalim" demenin en kolay
    yolu, tarihleri calistirma aninda secilebilir birakmaktir.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    status: Literal["draft", "pilot", "approved"]
    """Tanimin ne icin kullanilabilecegi - MAKINE tarafindan uygulanir.

      draft     indirilemez, olculemez. Esikleri henuz kesinlesmemis
                bir tanim; "oneri" demek bir yorum satirina birakilmaz.
      pilot     indirilebilir (erisim + kalite), ama P&L URETEMEZ.
      approved  indirilebilir ve baseline olculebilir.

    Zorunlu alan, varsayilani yok: sentetik test tanimlari dahil her
    tanim durumunu acikca soyler. Onay, ayri bir commit ile draft ->
    approved degisikligidir ve spec hash'ini degistirir.
    """

    symbols: tuple[str, ...] = Field(min_length=1)
    timeframe: Timeframe = Timeframe.M1
    feed: Literal["iex", "sip"] = "iex"
    adjustment: Literal["raw", "split", "dividend", "all"] = "raw"
    """Istekte ACIKCA gonderilir. SDK varsayilani `None`'dir ve istege
    hic yazilmaz - yani sunucu karar verir. Manifestin iddia ettigi
    deger, istegin garanti ettigi deger olmali."""

    start: date
    end: date
    """Dahil. Borsa yerel takvim gunleri."""

    exchange_timezone: str = "America/New_York"
    holdout_fraction: float = Field(default=0.20, gt=0.0, lt=1.0)
    split_unit: Literal["session"] = "session"
    """Bolme birimi TAKVIM GUNU degil ISLEM SEANSI. Hafta sonu ve
    tatiller sayilmaz; "son %20" gercek islem gunlerinin son %20'si."""

    settle_minutes: int = Field(default=20, ge=0, le=24 * 60)
    """Kapanistan sonra verinin oturmasi icin beklenen sure. Ucretsiz
    IEX planinda son 15 dakika gecikmeli gelir; kapanistan hemen sonra
    indirilen bir seans eksik olabilir."""

    retention_days: int = Field(default=90, ge=1, le=400)
    quality: QualityPolicy = Field(default_factory=QualityPolicy)

    @field_validator("symbols")
    @classmethod
    def _normalize(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        upper = tuple(symbol.strip().upper() for symbol in value)
        if len(set(upper)) != len(upper):
            msg = "sembol listesi tekrar iceriyor"
            raise ValueError(msg)
        return upper

    @field_validator("exchange_timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        # ZoneInfoNotFoundError bir KeyError alt sinifi, ValueError degil;
        # pydantic onu dogrulama hatasina cevirmez ve ham istisna sizar.
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"bilinmeyen saat dilimi: {value!r}"
            raise ValueError(msg) from exc
        return value

    @model_validator(mode="after")
    def _range(self) -> DatasetSpec:
        if self.start > self.end:
            msg = f"baslangic bitisten sonra: {self.start} > {self.end}"
            raise ValueError(msg)
        return self

    def require_downloadable(self) -> None:
        """Taslak bir tanim hicbir yan etkiden (ag, dizin) ONCE reddedilir."""
        if self.status == "draft":
            msg = (
                f"{self.dataset_id} taslak (status: draft): esikleri kesinlesmeden "
                "indirilemez. Onay ayri bir commit ile status: approved yapilarak verilir."
            )
            raise DatasetStatusError(msg)

    @classmethod
    def from_yaml(cls, path: Path) -> DatasetSpec:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = f"{path}: veri kumesi tanimi bir sozluk olmali"
            raise DataError(msg)
        return cls.model_validate(raw)


class BarsSource(Protocol):
    def bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None
    ) -> list[Bar]: ...


class CalendarSource(Protocol):
    def get_calendar(self, start: date, end: date) -> list[TradingSession]: ...


# ---------------------------------------------------------------------------
# Seans siniflandirma ve bolme - saf fonksiyonlar
# ---------------------------------------------------------------------------


def _count_in_session(stamps: Sequence[datetime], session: TradingSession) -> int:
    """Sirali zaman damgalarindan kacinin seans icinde oldugu - ikili arama.

    Dogrudan tarama seans basina butun barlari gezerdi: 90 gun x 12
    sembol x ~35 bin dakikalik bar, on milyonlarca karsilastirma.
    """
    return bisect_left(stamps, session.close) - bisect_left(stamps, session.open)


@dataclass(frozen=True)
class SessionVerdict:
    session: TradingSession
    complete: bool
    reason: str = ""


def classify_sessions(
    sessions: Sequence[TradingSession],
    *,
    downloaded_at: datetime,
    settle_minutes: int,
) -> list[SessionVerdict]:
    """Her seansin TAKVIMSEL olarak tamamlanip tamamlanmadigini soyler.

    Tamamlanmis = kapanis + oturma suresi indirme anindan once. Bar
    sayisina BAKILMAZ (Codex B2): bir sembolun verisi eksik diye bir
    gun bolmeden dusseydi, holdout sinirinin yeri veri boslugu
    tarafindan oynatilabilirdi. Veri eksikligi `assess_quality` ile
    ayrica olculur ve olcum kapisi olarak uygulanir.
    """
    if downloaded_at.tzinfo is None:
        msg = "downloaded_at zaman dilimi icermeli"
        raise DataError(msg)
    settle = timedelta(minutes=settle_minutes)

    verdicts: list[SessionVerdict] = []
    for session in sorted(sessions, key=lambda item: item.day):
        if session.close + settle > downloaded_at:
            verdicts.append(SessionVerdict(session, False, "indirme aninda kapanmamisti"))
        else:
            verdicts.append(SessionVerdict(session, True))
    return verdicts


def _count_between(stamps: Sequence[datetime], start: datetime, end: datetime) -> int:
    return bisect_left(stamps, end) - bisect_left(stamps, start)


def assess_quality(
    sessions: Sequence[TradingSession],
    stamps_by_symbol: dict[str, list[datetime]],
    *,
    policy: QualityPolicy,
    timeframe: Timeframe,
) -> dict[str, dict[str, Any]]:
    """Her (seans, sembol) icin kalite olculeri ve uygunluk.

    Donen yapi manifeste aynen yazilir:
    `{gun: {"eligible": bool, "symbols": {sembol: {...olculer, "reasons": [...]}}}}`.
    Bu fonksiyon performans gormez; yalnizca zaman damgalarina bakar.
    """
    minute = timedelta(minutes=1)
    result: dict[str, dict[str, Any]] = {}
    for session in sorted(sessions, key=lambda item: item.day):
        per_symbol: dict[str, Any] = {}
        eligible = True
        for symbol in sorted(stamps_by_symbol):
            stamps = stamps_by_symbol[symbol]
            count = _count_between(stamps, session.open, session.close)
            reasons: list[str] = []
            metrics: dict[str, Any] = {"bars": count}
            if count == 0:
                reasons.append("seans ici bar yok")
            if timeframe is Timeframe.M1:
                expected = int((session.close - session.open) / minute)
                open_end = min(session.close, session.open + policy.open_window_minutes * minute)
                open_expected = int((open_end - session.open) / minute)
                open_missing = max(
                    0, open_expected - _count_between(stamps, session.open, open_end)
                )
                close_start = max(
                    session.open, session.close - policy.close_window_minutes * minute
                )
                close_bars = _count_between(stamps, close_start, session.close)
                missing = max(0, expected - count)
                fraction = missing / expected if expected else 1.0
                metrics |= {
                    "missing_minutes": missing,
                    "missing_open_window": open_missing,
                    "close_window_bars": close_bars,
                }
                if count and open_missing > policy.max_missing_open_window:
                    reasons.append(
                        f"acilis penceresinde {open_missing} dk eksik "
                        f"(sinir {policy.max_missing_open_window})"
                    )
                if count and close_bars == 0:
                    reasons.append(
                        f"kapanistan onceki {policy.close_window_minutes} dk icinde bar yok"
                    )
                if count and fraction > policy.max_missing_fraction:
                    reasons.append(
                        f"eksik dakika orani {fraction:.3f} (sinir {policy.max_missing_fraction})"
                    )
            metrics["reasons"] = reasons
            eligible = eligible and not reasons
            per_symbol[symbol] = metrics
        result[session.day.isoformat()] = {"eligible": eligible, "symbols": per_symbol}
    return result


def split_sessions(
    complete: Sequence[TradingSession], holdout_fraction: float
) -> tuple[list[TradingSession], list[TradingSession]]:
    """Kronolojik bolme: ilk kisim baseline, SON kisim holdout.

    Holdout sayisi YUKARI yuvarlanir. Tereddutte daha fazlasini ayirmak
    dogru taraf: fazla ayrilan veri sonradan kullanilabilir, erken
    bakilan veri geri alinamaz.

    Rastgele degil kronolojik: rastgele secilen bir gun, komsu
    gunlerin rejimini paylasir ve "gorulmemis" sayilamaz.
    """
    ordered = sorted(complete, key=lambda item: item.day)
    kept, _ = split_sizes(len(ordered), holdout_fraction)
    return ordered[:kept], ordered[kept:]


def split_sizes(count: int, holdout_fraction: float) -> tuple[int, int]:
    """(baseline, holdout) seans sayilari - bolmenin TEK kurali.

    Veri kumesi uretimi ve holdout taahhudu ayni kurali kullanir; biri
    degisip digeri eski kalamaz.
    """
    held = math.ceil(count * holdout_fraction)
    kept = count - held
    if kept < 1 or held < 1:
        msg = (
            f"{count} tamamlanmis seans bolunemez (baseline {kept}, holdout {held}); "
            "tarih araligini genislet"
        )
        raise DataError(msg)
    return kept, held


# ---------------------------------------------------------------------------
# Hash ve manifest
# ---------------------------------------------------------------------------


def canonical_json(payload: Any) -> bytes:
    """Ayni icerik her zaman ayni baytlar: sirali anahtar, sabit ayirici."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def content_sha256(bars: Sequence[Bar]) -> str:
    """Barlarin ICERIK hash'i, dosya bicimden bagimsiz.

    Parquet dosyasinin baytlari yazici kutuphane surumune gore
    degisebilir; ayni veri iki farkli dosya hash'i uretebilir. Bu
    hash "ayni veri mi" sorusunu serilestirmeden bagimsiz cevaplar.
    Float degerler `repr` ile yazilir: Python'da en kisa, geri
    donusumlu ve deterministik gosterim.
    """
    digest = hashlib.sha256()
    for bar in sorted(bars, key=lambda item: item.ts):
        row = (
            bar.ts.astimezone(UTC).isoformat(),
            repr(bar.open),
            repr(bar.high),
            repr(bar.low),
            repr(bar.close),
            repr(bar.volume),
            repr(bar.vwap),
            repr(bar.trade_count),
        )
        digest.update(("|".join(row) + "\n").encode())
    return digest.hexdigest()


def _local_day(moment: datetime, zone: ZoneInfo) -> date:
    return moment.astimezone(zone).date()


def _safe_relative(path_text: str) -> PurePosixPath:
    """Manifestteki yol veri kumesinin disina cikamaz."""
    candidate = PurePosixPath(path_text)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        msg = f"manifestte guvensiz yol: {path_text!r}"
        raise DatasetIntegrityError(msg)
    return candidate


# ---------------------------------------------------------------------------
# Uretim
# ---------------------------------------------------------------------------


def build_dataset(
    spec: DatasetSpec,
    *,
    bars_source: BarsSource,
    calendar_source: CalendarSource,
    out_dir: Path,
    downloaded_at: datetime,
    producer: dict[str, str],
) -> dict[str, Any]:
    """Veriyi indirir, seanslari siniflar, BOLER ve manifesti yazar.

    Bolme bu fonksiyonun icinde, hicbir performans olcumu yapilmadan
    gerceklesir. Donen manifest ve diske yazilan dosyalar ayni seydir.
    """
    spec.require_downloadable()
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        msg = f"{out_dir} bos degil; bir veri kumesi mevcut dosyalarin uzerine yazilmaz"
        raise DataError(msg)
    out_dir.mkdir(parents=True, exist_ok=True)

    zone = ZoneInfo(spec.exchange_timezone)
    sessions = calendar_source.get_calendar(spec.start, spec.end)
    if not sessions:
        msg = f"{spec.start} - {spec.end} araliginda resmi islem gunu yok"
        raise DataError(msg)

    range_start = min(item.open for item in sessions)
    range_end = max(item.close for item in sessions)

    raw_bars: dict[str, list[Bar]] = {}
    for symbol in spec.symbols:
        raw_bars[symbol] = bars_source.bars(
            symbol, spec.timeframe, start=range_start, end=range_end
        )

    verdicts = classify_sessions(
        sessions, downloaded_at=downloaded_at, settle_minutes=spec.settle_minutes
    )
    complete = [item.session for item in verdicts if item.complete]
    baseline, holdout = split_sessions(complete, spec.holdout_fraction)
    baseline_days = {item.day for item in baseline}
    holdout_days = {item.day for item in holdout}
    sessions_by_day = {item.day: item for item in sessions}

    files: list[dict[str, Any]] = []
    symbol_quality: dict[str, Any] = {}
    stamps_by_symbol: dict[str, list[datetime]] = {}
    for symbol in spec.symbols:
        bars = raw_bars[symbol]
        stamps = [bar.ts for bar in bars]
        duplicates = len(stamps) - len(set(stamps))
        unique = list({bar.ts: bar for bar in bars}.values())
        stamps_by_symbol[symbol] = sorted(bar.ts for bar in unique)

        parts: dict[str, list[Bar]] = {BASELINE_DIR: [], HOLDOUT_DIR: []}
        dropped = 0
        for bar in unique:
            day = _local_day(bar.ts, zone)
            if day in baseline_days:
                parts[BASELINE_DIR].append(bar)
            elif day in holdout_days:
                parts[HOLDOUT_DIR].append(bar)
            else:
                dropped += 1

        missing = 0
        if spec.timeframe is Timeframe.M1:
            ordered = stamps_by_symbol[symbol]
            for day in sorted(baseline_days | holdout_days):
                session = sessions_by_day[day]
                expected = int((session.close - session.open) / timedelta(minutes=1))
                missing += max(0, expected - _count_in_session(ordered, session))

        symbol_quality[symbol] = {
            "bars_received": len(bars),
            "duplicate_timestamps": duplicates,
            "bars_outside_split_sessions": dropped,
            "missing_regular_minutes": missing if spec.timeframe is Timeframe.M1 else None,
        }

        for split_name, split_bars in parts.items():
            cache = BarCache(out_dir / split_name)
            cache.save(symbol, spec.timeframe, split_bars)
            path = cache.path_for(symbol, spec.timeframe)
            files.append(
                {
                    "split": split_name,
                    "symbol": symbol,
                    "path": path.relative_to(out_dir).as_posix(),
                    "sha256": file_sha256(path),
                    "bytes": path.stat().st_size,
                    "bars": len(split_bars),
                    "content_sha256": content_sha256(split_bars),
                }
            )

    per_session = assess_quality(
        [*baseline, *holdout], stamps_by_symbol, policy=spec.quality, timeframe=spec.timeframe
    )
    quality: dict[str, Any] = {
        "policy": spec.quality.model_dump(mode="json"),
        "symbols": symbol_quality,
        "sessions": per_session,
        "ineligible": {
            "baseline": sum(
                1 for item in baseline if not per_session[item.day.isoformat()]["eligible"]
            ),
            "holdout": sum(
                1 for item in holdout if not per_session[item.day.isoformat()]["eligible"]
            ),
        },
    }

    expires_at = downloaded_at + timedelta(days=spec.retention_days)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_id": spec.dataset_id,
        "spec": spec.model_dump(mode="json"),
        "spec_sha256": hashlib.sha256(canonical_json(spec.model_dump(mode="json"))).hexdigest(),
        "producer": dict(sorted(producer.items())),
        "feed": spec.feed,
        "timeframe": spec.timeframe.value,
        "adjustment": spec.adjustment,
        "symbols": list(spec.symbols),
        "exchange_timezone": spec.exchange_timezone,
        "range_utc": [
            range_start.astimezone(UTC).isoformat(),
            range_end.astimezone(UTC).isoformat(),
        ],
        "downloaded_at": downloaded_at.astimezone(UTC).isoformat(),
        "retention_days": spec.retention_days,
        "expires_at": expires_at.astimezone(UTC).isoformat(),
        "sessions": {
            "calendar": len(sessions),
            # Resmi acilis/kapanis (UTC). Olcum yarim gunleri bunlardan
            # bilir; gun listesi tek basina 13:00 kapanisini tasimaz.
            "hours": {
                item.day.isoformat(): [
                    item.open.astimezone(UTC).isoformat(),
                    item.close.astimezone(UTC).isoformat(),
                ]
                for item in sorted(sessions, key=lambda entry: entry.day)
            },
            "complete": [item.day.isoformat() for item in complete],
            "incomplete": [
                {"day": item.session.day.isoformat(), "reason": item.reason}
                for item in verdicts
                if not item.complete
            ],
        },
        "split": {
            "unit": spec.split_unit,
            "holdout_fraction": spec.holdout_fraction,
            "rounding": "holdout yukari yuvarlanir",
            "baseline": [item.day.isoformat() for item in baseline],
            "holdout": [item.day.isoformat() for item in holdout],
        },
        "quality": quality,
        "files": sorted(files, key=lambda item: item["path"]),
    }
    (out_dir / MANIFEST_NAME).write_bytes(canonical_json(manifest))
    return manifest


# ---------------------------------------------------------------------------
# Holdout taahhudu - dosya ACMAZ, yalnizca dogrulanmis manifest bellegi
# ---------------------------------------------------------------------------

HOLDOUT_COMMITMENT_VERSION = "tlab/holdout-commitment/v1"
_HEX_DIGITS = frozenset("0123456789abcdef")


def _commitment_error(reason: str) -> DatasetIntegrityError:
    return DatasetIntegrityError(f"holdout taahhudu uretilemedi: {reason}")


def _feed_error(reason: str) -> DatasetIntegrityError:
    return DatasetIntegrityError(f"olcum feed'i belirlenemedi: {reason}")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX_DIGITS


def _day_list(value: Any, label: str) -> list[str]:
    """Kanonik ISO gunler, tekrarsiz; sirali dondurur."""
    if not isinstance(value, list):
        raise _commitment_error(f"{label} bir liste degil")
    days: list[str] = []
    for text in value:
        try:
            canonical = isinstance(text, str) and date.fromisoformat(text).isoformat() == text
        except ValueError:
            canonical = False
        if not canonical:
            raise _commitment_error(f"{label} icinde gecersiz gun: {text!r}")
        days.append(text)
    if len(set(days)) != len(days):
        raise _commitment_error(f"{label} icinde tekrarli gun")
    return sorted(days)


def holdout_commitment(manifest: Mapping[str, Any]) -> dict[str, str]:
    """Holdout'un icerigine baglanan tek bir hash (rapor semasi v2, #17).

    Manifest disari cikmadigi icin holdout dosyalarinin hash'leri kosu
    bitince kaybolurdu; rapor bu taahhudu tasir, tarihleri ve girdileri
    TASIMAZ. Yuk: surum etiketi, dataset_id, spec_sha256, sirali holdout
    seanslari ve her holdout girdisinin (split, symbol, path, bars,
    content_sha256) bilgisi. Dosya hash'i degil semantik `content_sha256`:
    Parquet yazicisi degisince ayni icerik baska bayt uretebilir.

    SAF fonksiyon: holdout dosyasi acilmaz, listelenmez. Tutarsiz bir
    manifest reddedilir - yanlis bir taahhut, taahhut olmamasindan kotudur.

    Sinirlar: saglayicinin dogru veri verdigini ya da ayni verinin ileride
    yeniden temin edilebilecegini KANITLAMAZ. Holdout acilirken yeni
    indirmenin beyanina guvenilmez; gercek barlardan hash'ler yeniden
    hesaplanip BU taahhutle karsilastirilir, uyusmazlikta yeni taahhut
    kabul edilmez (docs/designs/baseline-measurement-execution.md).
    """
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise _commitment_error("desteklenmeyen manifest surumu")
    spec = manifest.get("spec")
    spec_sha = manifest.get("spec_sha256")
    if not isinstance(spec, dict) or not _is_digest(spec_sha):
        raise _commitment_error("spec veya spec_sha256 eksik")
    if hashlib.sha256(canonical_json(spec)).hexdigest() != spec_sha:
        raise _commitment_error("spec_sha256 spec ile uyusmuyor")
    try:
        declared = DatasetSpec.model_validate(spec)
    except ValueError:
        raise _commitment_error("manifestteki spec gecersiz") from None
    dataset_id = manifest.get("dataset_id")
    if dataset_id != declared.dataset_id:
        raise _commitment_error("dataset_id spec ile uyusmuyor")
    # Dosyalar ONAYLI sembol evrenine ait olmali: spec baska, manifest
    # baska sembol soylerse taahhut neye bagli oldugunu bilemez.
    symbols = manifest.get("symbols")
    if symbols != list(declared.symbols):
        raise _commitment_error("manifest sembolleri spec ile uyusmuyor")

    split = manifest.get("split")
    sessions = manifest.get("sessions")
    if not isinstance(split, dict) or not isinstance(sessions, dict):
        raise _commitment_error("split veya sessions eksik")
    holdout_days = _day_list(split.get("holdout"), "holdout")
    baseline_days = _day_list(split.get("baseline"), "baseline")
    complete_days = _day_list(sessions.get("complete"), "tamamlanmis")
    if any(not declared.start <= date.fromisoformat(day) <= declared.end for day in complete_days):
        raise _commitment_error("tamamlanmis seans spec araliginin disinda")
    # Bolme, spec'in kuralindan YENIDEN hesaplanir: ayriklik ve alt kume
    # yetmez - ilk baseline gunu holdout'a tasinsa ikisi de gecerdi.
    try:
        kept, _ = split_sizes(len(complete_days), declared.holdout_fraction)
    except DataError:
        raise _commitment_error("tamamlanmis seanslar bolunemiyor") from None
    if baseline_days != complete_days[:kept] or holdout_days != complete_days[kept:]:
        raise _commitment_error("bolme, spec'e gore kronolojik son kisim degil")

    files = manifest.get("files")
    if not isinstance(files, list):
        raise _commitment_error("dosya listesi eksik")
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_symbols: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise _commitment_error("gecersiz dosya girdisi")
        path = entry["path"]
        if path in seen_paths:
            raise _commitment_error(f"tekrarli yol: {path}")
        seen_paths.add(path)
        try:
            parts = _safe_relative(path).parts
        except DatasetIntegrityError:
            raise _commitment_error(f"guvensiz yol: {path!r}") from None
        split_name = entry.get("split")
        if split_name not in (BASELINE_DIR, HOLDOUT_DIR) or parts[0] != split_name:
            raise _commitment_error(f"bolum ile yol uyusmuyor: {path}")
        if split_name != HOLDOUT_DIR:
            continue
        symbol = entry.get("symbol")
        bars = entry.get("bars")
        digest = entry.get("content_sha256")
        if not isinstance(symbol, str) or symbol not in declared.symbols:
            raise _commitment_error(f"manifestte olmayan sembol: {symbol!r}")
        if symbol in seen_symbols:
            raise _commitment_error(f"tekrarli holdout sembolu: {symbol}")
        seen_symbols.add(symbol)
        if isinstance(bars, bool) or not isinstance(bars, int) or bars < 0:
            raise _commitment_error(f"gecersiz bar sayisi: {path}")
        if not _is_digest(digest):
            raise _commitment_error(f"gecersiz content_sha256: {path}")
        entries.append(
            {
                "split": split_name,
                "symbol": symbol,
                "path": path,
                "bars": bars,
                "content_sha256": digest,
            }
        )
    if seen_symbols != set(declared.symbols):
        missing = sorted(set(declared.symbols) - seen_symbols)
        raise _commitment_error(f"holdout girdisi eksik: {missing}")

    payload = {
        "version": HOLDOUT_COMMITMENT_VERSION,
        "dataset_id": dataset_id,
        "spec_sha256": spec_sha,
        "holdout_sessions": holdout_days,
        "entries": sorted(entries, key=lambda item: (item["symbol"], item["path"])),
    }
    return {
        "version": HOLDOUT_COMMITMENT_VERSION,
        "sha256": hashlib.sha256(canonical_json(payload)).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Dogrulama ve yukleme - HOLDOUT'A DOKUNMAZ
# ---------------------------------------------------------------------------


class MemoryBarStore:
    """Dogrulanmis barlari bellekten sunar. Dosya yolu tasimaz.

    `CachedMarketData`'nin istedigi `load` arayuzunu uygular; boylece
    olcum, dogrulanan baytlardan baska bir seyi okuyamaz.
    """

    def __init__(self, bars: Mapping[str, Sequence[Bar]], timeframe: Timeframe) -> None:
        self._bars = {symbol.upper(): tuple(items) for symbol, items in bars.items()}
        self._timeframe = timeframe

    def load(self, symbol: str, timeframe: Timeframe) -> list[Bar]:
        if timeframe is not self._timeframe:
            msg = f"veri kumesi {self._timeframe.value}, istenen {timeframe.value}"
            raise DataError(msg)
        return list(self._bars.get(symbol.upper(), ()))


@dataclass(frozen=True)
class VerifiedBaseline:
    """Dogrulanmis baseline. Holdout hakkinda yalnizca gun LISTESI tasir.

    Dosya yolu TASIMAZ: barlar dogrulanan baytlardan cozulmus halde
    burada durur. Olcum veri kumesi dizinini bir daha acamaz.
    """

    manifest_sha256: str
    manifest: dict[str, Any]
    sessions: tuple[TradingSession, ...]
    """Baseline seanslari, RESMI acilis/kapanis saatleriyle."""

    bars: Mapping[str, tuple[Bar, ...]]
    timeframe: Timeframe

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])

    @property
    def days(self) -> tuple[date, ...]:
        return tuple(item.day for item in self.sessions)

    @property
    def data_feed(self) -> str:
        """Olcumun feed'i: YALNIZCA dogrulanmis manifestten.

        Manifest feed'i spec'in beyanindan ayrica yazar. Ikisi ayni ve
        desteklenen bir deger olmali; bos, bilinmeyen ya da spec'le
        uyusmayan deger sessizce kabul edilmez (Codex, #17 6052081621).
        Config'in AYARLANMIS feed'iyle karistirilmaz.
        """
        try:
            declared = DatasetSpec.model_validate(self.manifest.get("spec"))
        except ValueError:
            raise _feed_error("manifestteki spec gecersiz") from None
        if self.manifest.get("feed") != declared.feed:
            raise _feed_error("manifest feed'i spec ile uyusmuyor")
        return declared.feed

    def store(self) -> MemoryBarStore:
        return MemoryBarStore(self.bars, self.timeframe)

    @property
    def policy(self) -> QualityPolicy:
        return QualityPolicy.model_validate(self.manifest["quality"]["policy"])

    def ineligible(self) -> dict[str, dict[str, list[str]]]:
        """Uygun olmayan BASELINE seanslari: {gun: {sembol: gerekceler}}."""
        per_session = self.manifest["quality"]["sessions"]
        found: dict[str, dict[str, list[str]]] = {}
        for day in self.days:
            entry = per_session[day.isoformat()]
            if not entry["eligible"]:
                found[day.isoformat()] = {
                    symbol: metrics["reasons"]
                    for symbol, metrics in entry["symbols"].items()
                    if metrics["reasons"]
                }
        return found

    def measurable_sessions(
        self, *, opening_range_minutes: int, flatten_before_close_minutes: int
    ) -> tuple[TradingSession, ...]:
        """Olculebilir baseline seanslari - ya da P&L'DEN ONCE bir hata.

        Sirasiyla: tanim onayli mi (pilot ve taslak P&L uretemez),
        politika olcumle tutarli mi, her seans kaliteyi karsiliyor mu.
        Politikanin tutarliligi burada denetlenir cunku veri kumesi
        modulu stratejiyi ve config'i bilmez (mimari test); sayilar
        cagirandan gelir. Gun DISLANMAZ: donen seanslar baseline'in
        tamamidir.
        """
        status = self.manifest["spec"].get("status")
        if status != "approved":
            msg = (
                f"{self.dataset_id} tanimi '{status}': yalnizca 'approved' veri kumesi "
                "olculebilir. Pilot yalnizca erisim ve kalite icindir. P&L uretilmedi."
            )
            raise DatasetStatusError(msg)

        policy = self.policy
        if self.timeframe is Timeframe.M1:
            if policy.open_window_minutes < opening_range_minutes:
                msg = (
                    f"kalite politikasinin acilis penceresi ({policy.open_window_minutes} dk) "
                    f"stratejinin acilis araligini ({opening_range_minutes} dk) kapsamiyor"
                )
                raise DatasetQualityError(msg)
            if policy.close_window_minutes > flatten_before_close_minutes:
                msg = (
                    f"kalite politikasinin kapanis penceresi ({policy.close_window_minutes} dk) "
                    f"gun sonu tamponundan ({flatten_before_close_minutes} dk) buyuk: "
                    "penceredeki bar kapatma anindan once kalabilir"
                )
                raise DatasetQualityError(msg)

        ineligible = self.ineligible()
        if ineligible:
            lines = [
                f"  {day}: " + "; ".join(f"{sym}: {', '.join(why)}" for sym, why in reasons.items())
                for day, reasons in sorted(ineligible.items())
            ]
            msg = (
                f"{len(ineligible)} baseline seansi kalite politikasini karsilamiyor. "
                "P&L uretilmedi.\n" + "\n".join(lines)
            )
            raise DatasetQualityError(msg)
        return self.sessions


def _baseline_sessions(manifest: dict[str, Any]) -> tuple[TradingSession, ...]:
    """Manifestteki baseline gunlerini resmi saatleriyle kurar."""
    hours = manifest["sessions"].get("hours", {})
    found: list[TradingSession] = []
    for text in manifest["split"]["baseline"]:
        if text not in hours:
            msg = f"manifestte {text} icin resmi seans saati yok"
            raise DatasetIntegrityError(msg)
        open_text, close_text = hours[text]
        found.append(
            TradingSession(
                day=date.fromisoformat(text),
                open=datetime.fromisoformat(open_text),
                close=datetime.fromisoformat(close_text),
            )
        )
    return tuple(found)


def manifest_sha256(dataset_dir: Path) -> str:
    return file_sha256(Path(dataset_dir) / MANIFEST_NAME)


def _reject_links(root: Path, relative: PurePosixPath) -> None:
    """Yolun HICBIR bileseni symlink olamaz.

    `O_NOFOLLOW` yalnizca son bileseni korur; `baseline/SPY` bir dizin
    symlink'i olup holdout/'a cozulebilirdi.
    """
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            msg = f"manifestteki dosya eksik: {relative}"
            raise DatasetIntegrityError(msg) from None
        if stat.S_ISLNK(info.st_mode):
            msg = f"veri kumesinde symlink reddedildi: {current.relative_to(root)}"
            raise DatasetIntegrityError(msg)


def _read_once(root: Path, relative: PurePosixPath) -> bytes:
    """Dosyayi TEK kez okur: dogrulanan baytlar, kullanilan baytlardir.

    Dosya once hash'lenip sonra baska bir kutuphane tarafindan yoldan
    YENIDEN okunsaydi, iki okuma arasinda ne oldugu - ve ikinci
    okumanin nereye cozuldugu - denetlenmemis olurdu.
    """
    _reject_links(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        handle = os.open(root / relative, flags)
    except FileNotFoundError:
        msg = f"manifestteki dosya eksik: {relative}"
        raise DatasetIntegrityError(msg) from None
    except OSError as exc:
        msg = f"{relative} guvenli acilamadi: {exc.strerror}"
        raise DatasetIntegrityError(msg) from exc
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode):
            msg = f"{relative} duz bir dosya degil"
            raise DatasetIntegrityError(msg)
        if info.st_nlink != 1:
            # Hardlink: ayni icerik baska bir yoldan - holdout/'tan -
            # da erisilebilir. Hangisinin "asil" oldugunu bilemeyiz.
            msg = f"{relative} birden fazla ada bagli (hardlink); reddedildi"
            raise DatasetIntegrityError(msg)
        chunks: list[bytes] = []
        while chunk := os.read(handle, 1 << 20):
            chunks.append(chunk)
    finally:
        os.close(handle)
    return b"".join(chunks)


def read_once(root: Path, relative: str) -> bytes:
    """`root` altindaki duz bir dosyayi TEK kez, link reddiyle okur.

    Veri kumesi dogrulamasiyla ayni guvenceler: yolun hicbir bileseni
    symlink olamaz, dosya hardlink olamaz, duz dosya olmali.
    """
    return _read_once(Path(root), _safe_relative(relative))


def _baseline_tree(dataset_dir: Path) -> set[PurePosixPath]:
    """baseline/ agacindaki duz dosyalar; symlink ve ozel dosya reddedilir."""
    baseline_root = dataset_dir / BASELINE_DIR
    try:
        info = os.lstat(baseline_root)
    except FileNotFoundError:
        return set()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        msg = f"{BASELINE_DIR}/ gercek bir dizin olmali (symlink degil)"
        raise DatasetIntegrityError(msg)

    present: set[PurePosixPath] = set()
    for folder, dirnames, filenames in os.walk(baseline_root, followlinks=False):
        for name in [*dirnames, *filenames]:
            full = Path(folder) / name
            mode = os.lstat(full).st_mode
            relative = PurePosixPath(full.relative_to(dataset_dir).as_posix())
            if stat.S_ISLNK(mode):
                msg = f"veri kumesinde symlink reddedildi: {relative}"
                raise DatasetIntegrityError(msg)
            if stat.S_ISREG(mode):
                present.add(relative)
            elif not stat.S_ISDIR(mode):
                msg = f"veri kumesinde ozel dosya reddedildi: {relative}"
                raise DatasetIntegrityError(msg)
    return present


def verify_baseline(dataset_dir: Path, expected_manifest_sha256: str) -> VerifiedBaseline:
    """Manifesti ve BASELINE dosyalarini dogrular; barlari bellekte dondurur.

    Kesin bir manifest hash'i ZORUNLU. "En son veri kumesini al" diye
    bir yol yok: o yol, kimin neyi olctugunu belirsiz birakir.

    holdout/ dizini hicbir sekilde acilmaz - listelenmez, okunmaz,
    hash'lenmez. Holdout dosyalarinin hash'i manifestte duruyor ama
    ancak holdout'un acilmasi ayri ve kayitli bir olay oldugunda
    dogrulanir.

    Her baseline dosyasi TEK kez okunur; ayni baytlar hash'lenir ve
    cozulur. Donen yapi dosya yolu tasimaz.
    """
    dataset_dir = Path(dataset_dir)
    expected = expected_manifest_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        msg = "beklenen manifest hash'i 64 haneli onaltilik bir SHA256 olmali"
        raise DatasetIntegrityError(msg)

    raw = _read_once(dataset_dir, PurePosixPath(MANIFEST_NAME))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        msg = f"manifest hash'i uyusmuyor: beklenen {expected}, bulunan {actual}"
        raise DatasetIntegrityError(msg)

    manifest = json.loads(raw)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        msg = f"desteklenmeyen manifest surumu: {manifest.get('schema_version')!r}"
        raise DatasetIntegrityError(msg)
    timeframe = Timeframe(manifest["timeframe"])

    declared: dict[PurePosixPath, dict[str, Any]] = {}
    for entry in manifest["files"]:
        relative = _safe_relative(entry["path"])
        if entry["split"] != BASELINE_DIR:
            continue
        if relative.parts[0] != BASELINE_DIR:
            msg = f"baseline dosyasi baseline/ disinda: {entry['path']}"
            raise DatasetIntegrityError(msg)
        declared[relative] = entry

    # Agac OKUMADAN ONCE denetlenir: bir symlink varsa hicbir dosya
    # acilmadan reddedilir.
    present = _baseline_tree(dataset_dir)
    extra = sorted(str(item) for item in present - set(declared))
    if extra:
        msg = f"baseline/ icinde manifestte olmayan dosya: {extra}"
        raise DatasetIntegrityError(msg)

    bars: dict[str, tuple[Bar, ...]] = {}
    for relative, entry in sorted(declared.items()):
        data = _read_once(dataset_dir, relative)
        found = hashlib.sha256(data).hexdigest()
        if found != entry["sha256"]:
            msg = f"{relative} hash'i uyusmuyor: beklenen {entry['sha256']}, bulunan {found}"
            raise DatasetIntegrityError(msg)
        decoded = bars_from_frame(pd.read_parquet(io.BytesIO(data)), entry["symbol"])
        if content_sha256(decoded) != entry["content_sha256"] or len(decoded) != entry["bars"]:
            msg = f"{relative} icerigi manifestle uyusmuyor"
            raise DatasetIntegrityError(msg)
        bars[str(entry["symbol"]).upper()] = tuple(decoded)

    return VerifiedBaseline(
        manifest_sha256=actual,
        manifest=manifest,
        sessions=_baseline_sessions(manifest),
        bars=bars,
        timeframe=timeframe,
    )
