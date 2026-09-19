"""Bar verisi icin yerel parquet onbellegi.

Neden onbellek: ayni gecmis veriyi her backtest kosusunda yeniden
indirmek hem yavas hem de API limitlerini tuketir. Daha onemlisi,
tekrarlanabilirlik: bugun indirdigin veri uzerinde alinan sonuc,
yarin da ayni veriyle dogrulanabilmeli.

Dosya duzeni: <root>/<SEMBOL>/<timeframe>.parquet
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from tlab.core.types import Bar, Timeframe
from tlab.errors import DataError

_COLUMNS = ["ts", "open", "high", "low", "close", "volume", "vwap", "trade_count"]


def _require_aware(label: str, moment: datetime | None) -> None:
    """Naive tarih, pandas'in anlasilmaz bir TypeError'i ile patlardi.

    Hatayi kendi sinirimizda, ne yapilmasi gerektigini soyleyerek
    veriyoruz.
    """
    if moment is not None and moment.tzinfo is None:
        msg = f"{label} timezone bilgisi icermeli (ornegin datetime.now(UTC))"
        raise DataError(msg)


class BarCache:
    """Barlari sembol ve periyot bazinda parquet dosyalarinda saklar."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, symbol: str, timeframe: Timeframe) -> Path:
        return self.root / symbol.upper() / f"{timeframe.value}.parquet"

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """Onbellekten barlari okur. Dosya yoksa bos liste doner."""
        _require_aware("start", start)
        _require_aware("end", end)

        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return []

        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            msg = f"Onbellek okunamadi: {path} ({exc})"
            raise DataError(msg) from exc

        if frame.empty:
            return []

        frame = frame.assign(ts=pd.to_datetime(frame["ts"], utc=True))
        if start is not None:
            frame = frame[frame["ts"] >= pd.Timestamp(start)]
        if end is not None:
            frame = frame[frame["ts"] <= pd.Timestamp(end)]

        symbol = symbol.upper()
        return [
            Bar(
                symbol=symbol,
                ts=row.ts.to_pydatetime().astimezone(UTC),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                vwap=None if pd.isna(row.vwap) else float(row.vwap),
                trade_count=None if pd.isna(row.trade_count) else int(row.trade_count),
            )
            for row in frame.itertuples()
        ]

    def coverage(self, symbol: str, timeframe: Timeframe) -> tuple[datetime, datetime] | None:
        """Onbellekteki en eski ve en yeni bar zamani; veri yoksa None."""
        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return None
        frame = pd.read_parquet(path, columns=["ts"])
        if frame.empty:
            return None
        timestamps = pd.to_datetime(frame["ts"], utc=True)
        return (
            timestamps.min().to_pydatetime().astimezone(UTC),
            timestamps.max().to_pydatetime().astimezone(UTC),
        )

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def save(self, symbol: str, timeframe: Timeframe, bars: list[Bar]) -> int:
        """Barlari onbellege birlestirir ve toplam bar sayisini dondurur.

        Ayni zaman damgasi iki kez gelirse yeni kayit eskisini ezer
        (Alpaca gecmis barlari duzeltebiliyor). Sonuc her zaman
        zaman sirali ve tekilligi garantili.
        """
        if not bars:
            path = self.path_for(symbol, timeframe)
            if not path.exists():
                return 0
            # Sadece ts kolonu okunur: sayim icin tum dosyayi
            # cozmenin anlami yok.
            return len(pd.read_parquet(path, columns=["ts"]))

        mismatched = {bar.symbol.upper() for bar in bars} - {symbol.upper()}
        if mismatched:
            msg = f"{symbol} onbellegine baska sembol yazilamaz: {sorted(mismatched)}"
            raise DataError(msg)

        incoming = pd.DataFrame(
            [
                {
                    "ts": bar.ts.astimezone(UTC),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "vwap": bar.vwap,
                    "trade_count": bar.trade_count,
                }
                for bar in bars
            ],
            columns=_COLUMNS,
        )

        path = self.path_for(symbol, timeframe)
        if path.exists():
            existing = pd.read_parquet(path)
            existing["ts"] = pd.to_datetime(existing["ts"], utc=True)
            incoming = pd.concat([existing, incoming], ignore_index=True)

        incoming["ts"] = pd.to_datetime(incoming["ts"], utc=True)
        merged = (
            incoming.drop_duplicates(subset="ts", keep="last")
            .sort_values("ts")
            .reset_index(drop=True)
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        merged.to_parquet(tmp, index=False)
        tmp.replace(path)  # atomik degistirme: yarim yazilmis dosya kalmaz
        return len(merged)
