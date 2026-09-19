"""Alpaca SDK yanitlari icin ince uyum katmani.

alpaca-py, ayarlara ve cagriya gore ayni bilgiyi iki farkli sekilde
dondurebiliyor: tipli bir model nesnesi ya da ham sozluk (raw_data).
`getattr` ile okumak sozluk halinde, `[...]` ile okumak model halinde
patlar - ve bu fark ancak calisma aninda, canli seansta ortaya cikar.

Bu modul farki tek yerde kapatir. Sisteme SDK'nin sizdigi tek nokta
burasi olsun diye ayri bir dosyada duruyor.
"""

from __future__ import annotations

from typing import Any


def sdk_field(source: Any, name: str, default: Any = None) -> Any:
    """Alan degerini, kaynak ister model ister sozluk olsun okur."""
    if isinstance(source, dict):
        return source.get(name, default)
    value = getattr(source, name, default)
    return default if value is None else value


def sdk_float(source: Any, name: str, default: float = 0.0) -> float:
    """Sayisal alani float olarak okur.

    Alpaca sayilari cogu zaman string dondurur; bos veya bicimsiz
    gelen degerler varsayilana duser, cagiran tarafta try/except
    yigini olusmasin diye.
    """
    raw = sdk_field(source, name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def sdk_int(source: Any, name: str, default: int = 0) -> int:
    """Tamsayi alani okur."""
    raw = sdk_field(source, name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def sdk_bool(source: Any, name: str, *, default: bool = False) -> bool:
    """Mantiksal alani okur; string 'false' degerini de dogru yorumlar."""
    raw = sdk_field(source, name)
    if raw is None:
        return default
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "yes"}
    return bool(raw)
