"""Teknik gostergeler.

Tasarim kurallari:
  * Hepsi saf fonksiyon: ayni girdi her zaman ayni ciktiyi verir.
  * Veri yetmiyorsa None doner, tahmin URETMEZ. Yarim veriyle
    hesaplanmis bir ATR, stop mesafesini yanlis belirler ve bu
    dogrudan para kaybidir.
  * Girdi barlari her zaman KAPANMIS barlardir. Olusmakta olan bar
    cagiran tarafta ayiklanir; burada bunu varsayiyoruz.
"""

from __future__ import annotations

from datetime import datetime

from tlab.core.types import Bar


def true_range(bar: Bar, previous_close: float | None) -> float:
    """Tek barin gercek araligi (True Range).

    Onceki kapanis bilinmiyorsa yuksek-dusuk araligi kullanilir.
    Gercek aralik, gap'leri de hesaba kattigi icin ham bar
    araligindan daha dogru bir oynaklik olcusudur.
    """
    if previous_close is None:
        return bar.high - bar.low
    return max(
        bar.high - bar.low,
        abs(bar.high - previous_close),
        abs(bar.low - previous_close),
    )


def atr(bars: list[Bar], period: int = 14) -> float | None:
    """Ortalama Gercek Aralik (Wilder yontemi).

    Stop mesafesini oynakliga gore olceklendirmek icin kullanilir:
    sabit bir kurus degeri, sakin bir hissede cok genis, oynak bir
    hissede cok dar olur.
    """
    if period < 1 or len(bars) < period + 1:
        return None

    ranges = [true_range(bars[i], bars[i - 1].close) for i in range(1, len(bars))]
    # Wilder yumusatmasi: ilk deger basit ortalama, sonrasi kademeli.
    value = sum(ranges[:period]) / period
    for current in ranges[period:]:
        value = (value * (period - 1) + current) / period
    return value


def ema(values: list[float], period: int) -> float | None:
    """Ussel hareketli ortalama."""
    if period < 1 or len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def session_vwap(bars: list[Bar]) -> float | None:
    """Verilen barlarin hacim agirlikli ortalama fiyati.

    Gun ici islemde en cok izlenen referans seviyedir. Cagiran taraf
    yalnizca O SEANSIN barlarini gondermelidir; VWAP tanimi geregi
    seans basinda sifirlanir.
    """
    if not bars:
        return None

    total_volume = sum(bar.volume for bar in bars)
    if total_volume <= 0:
        return None

    # Tipik fiyat (H+L+C)/3, borsa VWAP hesabinin standardi.
    weighted = sum(((bar.high + bar.low + bar.close) / 3) * bar.volume for bar in bars)
    return weighted / total_volume


def average_volume(bars: list[Bar], lookback: int) -> float | None:
    """Son `lookback` barin ortalama hacmi."""
    if lookback < 1 or len(bars) < lookback:
        return None
    return sum(bar.volume for bar in bars[-lookback:]) / lookback


def relative_volume(bars: list[Bar], lookback: int = 20) -> float | None:
    """Son barin hacmi, onceki barlarin ortalamasina orani (RVOL).

    1,0 normal; 2,0 normalin iki kati ilgi demektir. Kirilimlarin
    kalicilik ihtimali hacimle birlikte artar, bu yuzden hacimsiz
    kirilimlari elemekte kullanilir.
    """
    if lookback < 1 or len(bars) < lookback + 1:
        return None

    baseline = average_volume(bars[:-1], lookback)
    if baseline is None or baseline <= 0:
        return None
    return bars[-1].volume / baseline


def opening_range(
    bars: list[Bar], session_open: datetime, minutes: int
) -> tuple[float, float] | None:
    """Seansin ilk `minutes` dakikasinin yuksek/dusuk araligi.

    Acilis araligi, gunun ilk fiyat kesfinin sinirlaridir; disina
    cikilmasi yon secimi olarak yorumlanir.

    Aralik henuz TAMAMLANMADIYSA None doner. Yarim aralikla islem
    acmak, olusmamis bir seviyeyi kirmis gibi davranmaktir.
    """
    if minutes < 1 or not bars:
        return None

    window_end = session_open.timestamp() + minutes * 60
    inside = [bar for bar in bars if session_open.timestamp() <= bar.ts.timestamp() < window_end]
    if not inside:
        return None

    # Aralik ancak penceresi kapanmis barlarla tamamlanmis sayilir.
    last_ts = max(bar.ts.timestamp() for bar in bars)
    if last_ts < window_end:
        return None

    return max(bar.high for bar in inside), min(bar.low for bar in inside)
