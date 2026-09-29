"""Gercek veri islerinin tarafsiz cikti yardimcilari (#17).

Ana baseline isi ve baseline kalite teshisi ikisini de kullanir. Bu
modul bilerek kucuk ve tarafsizdir: performans katmanlarini, SDK'yi ya
da veri kumesi kodunu ice aktarmaz. Boylece teshis, ana olcum
yurutucusune baglanmadan ayni guvenceleri kullanir.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def silenced() -> Iterator[None]:
    """Blok boyunca BUTUN log kayitlarini kapatir; cikista eski haline doner.

    Ciktinin tek kaynagi aracin kendi sabit `print` satirlari olur.
    Kutuphane ya da motor logu - hangi duzeyde olursa olsun - gecemez.
    """
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def write_new(path: Path, payload: bytes) -> None:
    """`path`'e ATOMIK ve USTUNE YAZMADAN yazar.

    Once ayni dizinde O_EXCL ile gecici dosya, sonra `os.link` ile hedef:
    hedef varsa link basarisiz olur ve hicbir sey ezilmez. Hangi yoldan
    cikilirsa cikilsin gecici dosya silinir; yarim bir hedef olusmaz.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            view = memoryview(payload)
            while view:
                written = os.write(handle, view)
                view = view[written:]
            os.fsync(handle)
        finally:
            os.close(handle)
        os.link(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
