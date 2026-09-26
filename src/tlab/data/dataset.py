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
dokunmaz - listelemez, okumaz, hash'lemez - ve bunu bir test dogrudan
olcer.

Ikinci risk sessiz degisim: "ayni veri" sanilan seyin aslinda farkli
olmasi. Her dosyanin SHA256'si manifestte; yukleyici kesin bir
manifest hash'i ister ("en sonuncuyu al" yok) ve tek bir bayt bile
tutmazsa durur.

Bu modul ag erisimi yapmaz ve duvar saatine bakmaz: veri ve takvim
kaynaklari ile indirme zamani disaridan verilir.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tlab.core.calendar import TradingSession
from tlab.core.types import Bar, Timeframe
from tlab.data.cache import BarCache
from tlab.errors import DataError

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
BASELINE_DIR = "baseline"
HOLDOUT_DIR = "holdout"


class DatasetIntegrityError(DataError):
    """Veri kumesi manifestiyle uyusmuyor. Devam etmek, dogrulanmamis
    veriyle olcum yapmak demek olurdu."""


# ---------------------------------------------------------------------------
# Tanim
# ---------------------------------------------------------------------------


class DatasetSpec(BaseModel):
    """Veri kumesinin ONCEDEN sabitlenmis tanimi.

    Tarihler ve semboller bir dosyada durur ve commit edilir;
    indirme aninda serbest girdi olarak verilmez. Sebep: sonuc
    gorulduken sonra "bir de su tarihlere bakalim" demenin en kolay
    yolu, tarihleri calistirma aninda secilebilir birakmaktir.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
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
    bars_by_symbol: dict[str, list[Bar]],
    *,
    downloaded_at: datetime,
    settle_minutes: int,
) -> list[SessionVerdict]:
    """Her seansin TAMAMLANMIS olup olmadigini soyler.

    Tamamlanmis = (1) kapanis + oturma suresi indirme anindan once
    ve (2) HER sembol icin seans icinde en az bir bar var.

    Ikinci kosul veri kalitesini bolmeye karistirmak degil: bir
    sembolun hic bari olmayan bir gun, o gunun o sembol icin
    olculemeyecegi demek. Eksik dakikalar ise bolmeyi DEGISTIRMEZ,
    yalnizca kalite raporunda sayilir - aksi halde bolme sinirinin
    yeri verinin gurultusune bagli olurdu.
    """
    if downloaded_at.tzinfo is None:
        msg = "downloaded_at zaman dilimi icermeli"
        raise DataError(msg)
    settle = timedelta(minutes=settle_minutes)
    stamps = {symbol: sorted(bar.ts for bar in bars) for symbol, bars in bars_by_symbol.items()}

    verdicts: list[SessionVerdict] = []
    for session in sorted(sessions, key=lambda item: item.day):
        if session.close + settle > downloaded_at:
            verdicts.append(SessionVerdict(session, False, "indirme aninda kapanmamisti"))
            continue
        empty = sorted(
            symbol for symbol, ordered in stamps.items() if _count_in_session(ordered, session) == 0
        )
        if empty:
            reason = f"seans ici bar yok: {', '.join(empty)}"
            verdicts.append(SessionVerdict(session, False, reason))
            continue
        verdicts.append(SessionVerdict(session, True))
    return verdicts


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
    count = len(ordered)
    held = math.ceil(count * holdout_fraction)
    kept = count - held
    if kept < 1 or held < 1:
        msg = (
            f"{count} tamamlanmis seans bolunemez (baseline {kept}, holdout {held}); "
            "tarih araligini genislet"
        )
        raise DataError(msg)
    return ordered[:kept], ordered[kept:]


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
        sessions, raw_bars, downloaded_at=downloaded_at, settle_minutes=spec.settle_minutes
    )
    complete = [item.session for item in verdicts if item.complete]
    baseline, holdout = split_sessions(complete, spec.holdout_fraction)
    baseline_days = {item.day for item in baseline}
    holdout_days = {item.day for item in holdout}
    sessions_by_day = {item.day: item for item in sessions}

    files: list[dict[str, Any]] = []
    quality: dict[str, Any] = {}
    for symbol in spec.symbols:
        bars = raw_bars[symbol]
        stamps = [bar.ts for bar in bars]
        duplicates = len(stamps) - len(set(stamps))
        unique = list({bar.ts: bar for bar in bars}.values())

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
            ordered = sorted(bar.ts for bar in unique)
            for day in sorted(baseline_days | holdout_days):
                session = sessions_by_day[day]
                expected = int((session.close - session.open) / timedelta(minutes=1))
                missing += max(0, expected - _count_in_session(ordered, session))

        quality[symbol] = {
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
# Dogrulama ve yukleme - HOLDOUT'A DOKUNMAZ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedBaseline:
    """Dogrulanmis baseline. Holdout hakkinda yalnizca gun LISTESI tasir."""

    root: Path
    manifest_sha256: str
    manifest: dict[str, Any]
    sessions: tuple[date, ...]

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])


def manifest_sha256(dataset_dir: Path) -> str:
    return file_sha256(Path(dataset_dir) / MANIFEST_NAME)


def verify_baseline(dataset_dir: Path, expected_manifest_sha256: str) -> VerifiedBaseline:
    """Manifesti ve BASELINE dosyalarini dogrular; baseline kokunu dondurur.

    Kesin bir manifest hash'i ZORUNLU. "En son veri kumesini al" diye
    bir yol yok: o yol, kimin neyi olctugunu belirsiz birakir.

    holdout/ dizini hicbir sekilde acilmaz - listelenmez, okunmaz,
    hash'lenmez. Holdout dosyalarinin hash'i manifestte duruyor ama
    ancak holdout'un acilmasi ayri ve kayitli bir olay oldugunda
    dogrulanir.
    """
    dataset_dir = Path(dataset_dir)
    expected = expected_manifest_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        msg = "beklenen manifest hash'i 64 haneli onaltilik bir SHA256 olmali"
        raise DatasetIntegrityError(msg)

    manifest_path = dataset_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        msg = f"{manifest_path} bulunamadi"
        raise DatasetIntegrityError(msg)
    raw = manifest_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        msg = f"manifest hash'i uyusmuyor: beklenen {expected}, bulunan {actual}"
        raise DatasetIntegrityError(msg)

    manifest = json.loads(raw)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        msg = f"desteklenmeyen manifest surumu: {manifest.get('schema_version')!r}"
        raise DatasetIntegrityError(msg)

    baseline_root = dataset_dir / BASELINE_DIR
    declared: dict[PurePosixPath, dict[str, Any]] = {}
    for entry in manifest["files"]:
        relative = _safe_relative(entry["path"])
        if entry["split"] != BASELINE_DIR:
            continue
        if relative.parts[0] != BASELINE_DIR:
            msg = f"baseline dosyasi baseline/ disinda: {entry['path']}"
            raise DatasetIntegrityError(msg)
        declared[relative] = entry

    for relative, entry in declared.items():
        path = dataset_dir / relative
        if not path.is_file():
            msg = f"manifestteki dosya eksik: {relative}"
            raise DatasetIntegrityError(msg)
        found = file_sha256(path)
        if found != entry["sha256"]:
            msg = f"{relative} hash'i uyusmuyor: beklenen {entry['sha256']}, bulunan {found}"
            raise DatasetIntegrityError(msg)

    present = {
        PurePosixPath(path.relative_to(dataset_dir).as_posix())
        for path in baseline_root.rglob("*")
        if path.is_file()
    }
    extra = sorted(str(item) for item in present - set(declared))
    if extra:
        msg = f"baseline/ icinde manifestte olmayan dosya: {extra}"
        raise DatasetIntegrityError(msg)

    days = tuple(date.fromisoformat(item) for item in manifest["split"]["baseline"])
    return VerifiedBaseline(
        root=baseline_root, manifest_sha256=actual, manifest=manifest, sessions=days
    )
