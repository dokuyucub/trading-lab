"""Yapilandirma yukleme.

Iki ayri kaynak, bilerek ayri tutuluyor:
  * GIZLI bilgi (API anahtarlari) -> .env dosyasi, repoya asla girmez.
  * DAVRANIS ayarlari (risk limitleri, seans, feed) -> config/*.yaml,
    repoya girer ve versiyonlanir.

Bu ayrim sayesinde "hangi ayarla hangi sonucu aldik" sorusu git
gecmisinden cevaplanabilir, anahtarlar ise disarida kalir.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Annotated, Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tlab.core.types import Timeframe
from tlab.errors import ConfigError

Percent = Annotated[float, Field(gt=0, le=100)]


class Secrets(BaseSettings):
    """API anahtarlari. Sadece ortam degiskenlerinden / .env dosyasindan."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    def require(self) -> Self:
        """Anahtarlarin varligini garanti eder, yoksa anlasilir hata verir."""
        if not self.is_configured:
            msg = (
                "Alpaca anahtarlari bulunamadi. Proje kokunde .env dosyasi olusturup "
                "ALPACA_API_KEY ve ALPACA_SECRET_KEY degerlerini yaz "
                "(ornek icin .env.example dosyasina bak)."
            )
            raise ConfigError(msg)
        return self

    def masked(self) -> dict[str, str]:
        """Loglanabilir, maskelenmis gosterim. Anahtar asla duz yazilmaz."""

        def mask(value: str) -> str:
            if not value:
                return "<bos>"
            return f"{value[:4]}...{value[-2:]} ({len(value)} karakter)"

        return {
            "ALPACA_API_KEY": mask(self.alpaca_api_key),
            "ALPACA_SECRET_KEY": mask(self.alpaca_secret_key),
            "ALPACA_PAPER": str(self.alpaca_paper),
        }


class Strict(BaseModel):
    """YAML bolumlerinin ortak tabani: bilinmeyen anahtar hata verir.

    `extra="forbid"` bilincli bir tercih: config'e yazim hatasiyla
    girilmis bir satir sessizce yok sayilirsa, risk limiti sandigin
    degerde olmaz. Boyle bir hatayi calisma aninda degil, aciliste
    yakalamak istiyoruz.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class AppSection(Strict):
    exchange_timezone: str = "America/New_York"

    @field_validator("exchange_timezone")
    @classmethod
    def _valid_tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            msg = f"Bilinmeyen zaman dilimi: {value}"
            raise ValueError(msg) from exc
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.exchange_timezone)


class DataSection(Strict):
    feed: str = "iex"
    cache_dir: Path = Path("data/bars")
    default_timeframe: Timeframe = Timeframe.M1

    @field_validator("feed")
    @classmethod
    def _known_feed(cls, value: str) -> str:
        allowed = {"iex", "sip"}
        if value not in allowed:
            msg = f"feed 'iex' veya 'sip' olmali, alinan: {value!r}"
            raise ValueError(msg)
        return value


class SessionSection(Strict):
    regular_open: time = time(9, 30)
    regular_close: time = time(16, 0)
    flatten_before_close_minutes: Annotated[int, Field(ge=0, le=120)] = 10
    allow_extended_hours: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.regular_open >= self.regular_close:
            msg = "regular_open, regular_close'dan once olmali"
            raise ValueError(msg)
        return self


class RiskSection(Strict):
    max_risk_per_trade_pct: Percent = 0.5
    max_daily_loss_pct: Percent = 2.0
    max_concurrent_positions: Annotated[int, Field(ge=1, le=50)] = 3
    max_gross_exposure_pct: Percent = 50.0
    min_price: Annotated[float, Field(gt=0)] = 5.0
    max_spread_bps: Annotated[float, Field(gt=0)] = 15.0
    min_stop_bps: Annotated[float, Field(gt=0)] = 5.0
    enforce_pdt: bool = True
    pdt_equity_threshold: Annotated[float, Field(ge=0)] = 25_000.0
    max_day_trades_per_window: Annotated[int, Field(ge=0)] = 3

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.max_risk_per_trade_pct > self.max_daily_loss_pct:
            msg = (
                f"Islem basina risk (%{self.max_risk_per_trade_pct}) gunluk zarar "
                f"limitinden (%{self.max_daily_loss_pct}) buyuk olamaz: tek islem "
                "gunu bitirirdi."
            )
            raise ValueError(msg)
        return self


class JournalSection(Strict):
    path: Path = Path("data/journal.db")


class Config(Strict):
    """Cozumlenmis tam yapilandirma."""

    app: AppSection = Field(default_factory=AppSection)
    data: DataSection = Field(default_factory=DataSection)
    session: SessionSection = Field(default_factory=SessionSection)
    risk: RiskSection = Field(default_factory=RiskSection)
    journal: JournalSection = Field(default_factory=JournalSection)
    symbols: tuple[str, ...] = ()
    root: Path = Path()

    @field_validator("symbols")
    @classmethod
    def _normalize(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        seen: list[str] = []
        for raw in value:
            symbol = raw.strip().upper()
            if symbol and symbol not in seen:
                seen.append(symbol)
        return tuple(seen)

    def resolve(self, relative: Path) -> Path:
        """Config'deki goreli yollari proje kokune gore mutlaklastirir."""
        return relative if relative.is_absolute() else (self.root / relative)

    @property
    def cache_dir(self) -> Path:
        return self.resolve(self.data.cache_dir)

    @property
    def journal_path(self) -> Path:
        return self.resolve(self.journal.path)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        msg = f"Yapilandirma dosyasi bulunamadi: {path}"
        raise ConfigError(msg)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        msg = f"{path} okunamadi: {exc}"
        raise ConfigError(msg) from exc
    if not isinstance(loaded, dict):
        msg = f"{path} bir sozluk icermeli, bulunan: {type(loaded).__name__}"
        raise ConfigError(msg)
    return loaded


def load_config(root: Path | None = None) -> Config:
    """config/base.yaml + config/universe.yaml dosyalarini okur ve dogrular."""
    root = (root or Path.cwd()).resolve()
    base = _read_yaml(root / "config" / "base.yaml")
    universe = _read_yaml(root / "config" / "universe.yaml")

    symbols = universe.get("symbols") or []
    if not isinstance(symbols, list):
        msg = "universe.yaml icindeki 'symbols' bir liste olmali"
        raise ConfigError(msg)

    try:
        return Config(**base, symbols=tuple(symbols), root=root)
    except Exception as exc:  # pydantic ValidationError dahil
        msg = f"Yapilandirma gecersiz: {exc}"
        raise ConfigError(msg) from exc


def load_secrets(root: Path | None = None) -> Secrets:
    """.env dosyasindan anahtarlari okur (ortam degiskenleri onceliklidir)."""
    env_file = (root or Path.cwd()).resolve() / ".env"
    return Secrets(_env_file=env_file if env_file.exists() else None)  # type: ignore[call-arg]
