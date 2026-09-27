"""Dosya sistemi erisimini dogrudan olcen test yardimcisi.

`chmod 000` KULLANILMIYOR: konteynerde root olarak kosuyoruz ve root
dosya izinlerini yok sayar - o tur bir test hicbir sey olcmeden
gecerdi. Python'un denetim kancasi izinlerden bagimsiz olarak her
Python seviyesindeki `open` (`os.open` dahil), `os.scandir` ve
`os.listdir` olayini gorur.

SINIRLARI - bunlari bilmeden sonucunu okuma:

  * CAGRILAN yolu gorur, cozuldugu yeri degil. baseline/ altindaki bir
    symlink holdout/'a cozulse kanca yalnizca baseline yolunu kaydeder
    (Codex B3 bunu gosterdi). Takma adlar bu yuzden dogrulamada hic
    okunmadan reddediliyor; kanca o savunmanin yerine gecmez.
  * Yerel kutuphanelerin (C/C++) kendi G/C'sini gordugu IDDIA EDILMEZ.
    Olcumun dosya yolu almamasi bu yuzden yapisal olarak saglaniyor.

Kanca bir kez kurulur ve surec boyunca kalir (kaldirilamaz); yalnizca
`filesystem_access()` blogu icinde kayit tutar, disarida maliyeti bir
bayrak kontroludur.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_EVENTS = frozenset({"open", "os.scandir", "os.listdir"})
_SEEN: list[tuple[str, str]] = []
_ACTIVE = False


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if not _ACTIVE or event not in _EVENTS or not args:
        return
    target = args[0]
    if isinstance(target, bytes):
        target = target.decode(errors="replace")
    if isinstance(target, (str, Path)):
        _SEEN.append((event, str(target)))


sys.addaudithook(_hook)


@contextmanager
def filesystem_access() -> Iterator[list[tuple[str, str]]]:
    """Blok icindeki her dosya acma ve dizin listeleme olayini kaydeder."""
    global _ACTIVE
    _SEEN.clear()
    _ACTIVE = True
    try:
        yield _SEEN
    finally:
        _ACTIVE = False


def touched_under(seen: list[tuple[str, str]], root: Path) -> list[tuple[str, str]]:
    prefix = str(root)
    return [item for item in seen if item[1] == prefix or item[1].startswith(prefix + "/")]
