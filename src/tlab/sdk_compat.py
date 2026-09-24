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
    """Alan degerini, kaynak ister model ister sozluk olsun okur.

    Degeri None olan bir alan, hic olmayan alanla ayni sayilir ve
    varsayilana duser. Bu esitlik sart: aksi halde ayni bilgi sozlukte
    None, nesnede varsayilan dondururdu ve uyum katmani tam da
    kapatmak icin var oldugu farki yeniden uretirdi.
    """
    value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
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


# ---------------------------------------------------------------------------
# Tasima katmani hatalarinin siniflandirilmasi
#
# Burada durmasinin sebebi dosyanin kendi gerekcesi: SDK'nin sisteme
# sizdigi tek nokta burasi olsun. Hata TIPLERI de SDK bilgisidir.
# ---------------------------------------------------------------------------

MAX_CAUSE_DEPTH = 20
"""Istisna zincirinde en fazla bu kadar derine inilir.

`__cause__` zincirleri dongu olusturabilir (elle kurulmus zincirlerde
gorulur). Sinir olmadan tani araci sonsuz donguye girerdi - hata
ayiklamak icin yazilmis bir aracin en kotu davranisi.
"""


def _chain(error: BaseException) -> list[BaseException]:
    """Istisna ve onu doguran butun istisnalar, donguye karsi korumali."""
    found: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and len(found) < MAX_CAUSE_DEPTH:
        if id(current) in seen:
            break
        seen.add(id(current))
        found.append(current)
        current = current.__cause__ or current.__context__
    return found


def http_status_of(error: BaseException) -> int | None:
    """Zincirdeki ilk HTTP durum kodu.

    alpaca-py `APIError.status_code` alanini zaten sunuyor ve
    adaptorlerimiz `raise ... from exc` ile zinciri koruyor. Yani
    kod METINDE aranmak zorunda degil - ki aranmasi hataliydi.
    """
    from alpaca.common.exceptions import APIError

    for item in _chain(error):
        if isinstance(item, APIError):
            status = item.status_code
            if isinstance(status, int):
                return status
        response = getattr(item, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def is_network_error(error: BaseException) -> bool:
    """Zincirde ag/TLS/zaman asimi hatasi var mi - TIPE bakarak."""
    import requests

    network_types = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.SSLError,
    )
    return any(isinstance(item, network_types) for item in _chain(error))


CONNECT_TIMEOUT_SECONDS = 5.0

READ_TIMEOUT_SECONDS = 15.0
"""Okuma zaman asimi - DIKKAT: toplam sure DEGIL.

`requests` icin bu deger, iki veri parcasi arasinda beklenecek en uzun
suredir. Damla damla yanit gonderen bir sunucu, her aralikta sinirin
altinda kalarak toplamda cok daha uzun surebilir.

Yani bu sinir "istek en fazla 15 saniye surer" demiyor; "sunucu 15
saniye boyunca hic veri gondermezse vazgecilir" diyor. Sonsuz asili
kalmayi onler, sureyi garanti etmez. Gercek ust sinir workflow'un
kendi zaman asimidir.
"""


def bound_transport(client: Any, *, retries: int = 1) -> None:
    """Istemcinin HTTP cagrilarina SONLU bir zaman asimi ve retry butcesi koyar.

    Kilitli alpaca-py surumunde `RESTClient._one_request`,
    `self._session.request(method, url, **opts)` cagriyor ve `opts`
    icinde timeout YOK. Yani sessiz bir sunucu karsisinda istek
    suresiz asili kalir.

    Bunun bir tani araci icin bedeli buyuk: ilk asama asili kalirsa
    digerleri hic calismaz ve "her asama ayri sonuc verir" ozelligi -
    aracin butun degeri - kaybolur. Workflow'un kendi sure siniri
    yalnizca dis kapidir; oraya gelindiginde hicbir satir basilmamis
    olur.

    Oturumun `request` metodu sariliyor: cagiran timeout vermediyse
    varsayilan konuyor, verdiyse dokunulmuyor. Sarmalayici
    idempotent - iki kez uygulanmasi ikinci bir katman eklemez.
    """
    session = getattr(client, "_session", None)
    if session is None:  # pragma: no cover - surum degisikligine karsi
        return

    if not getattr(session.request, "_tlab_bounded", False):
        original = session.request

        def request(method: str, url: str, **kwargs: Any) -> Any:
            kwargs.setdefault("timeout", (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS))
            return original(method, url, **kwargs)

        request._tlab_bounded = True  # type: ignore[attr-defined]
        session.request = request

    # Kalici 429 karsisinda varsayilan 3 deneme x 3 saniye bekleme,
    # dort asamada toplam butceyi gereksiz buyutuyor. Tani icin bir
    # tekrar yeterli: sorunun gecici mi kalici mi oldugunu soyler.
    if hasattr(client, "_retry"):
        client._retry = retries
