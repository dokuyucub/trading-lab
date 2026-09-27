"""Resmi islem seansi.

Seansin nerede basladigi ve bittigi SABIT bir saatten okunamaz: yarim
gunlerde (Sukran Gunu ertesi, Noel arifesi) borsa 13:00'te kapanir.
Sabit 16:00 varsayan bir kural o gunleri "tamamlanmamis" sayar - ya
da daha kotusu, kapanistan sonraki uc saati bos veri olarak okur.

Bu yuzden seans sinirlari broker'in resmi takviminden gelir ve burada
tip olarak tasinir. Runner ayni ilkeyi zaten uyguluyor (bkz.
engine/runner.py: "Broker calendar is authoritative on shortened
trading days").
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator


class TradingSession(BaseModel):
    """Tek bir islem gununun resmi acilis ve kapanisi (UTC)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    day: date
    """Borsa yerel takvim gunu."""

    open: AwareDatetime
    close: AwareDatetime

    @model_validator(mode="after")
    def _check(self) -> TradingSession:
        if self.open >= self.close:
            msg = f"{self.day}: acilis kapanistan once olmali ({self.open} >= {self.close})"
            raise ValueError(msg)
        return self

    def contains(self, moment: datetime) -> bool:
        """An seansin [acilis, kapanis) araliginda mi."""
        return self.open <= moment < self.close
