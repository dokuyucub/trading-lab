"""Artefakt gidis-donus dogrulamasi (#17, #39 bakim plani).

`artifact-roundtrip.yml` workflow'u sabit, sentetik bir JSON'u
(`payload.json`) gercek veri workflow'lariyla AYNI upload adimiyla yukler.
Bu betik ayni kosunun ikinci isinde artefakti GitHub API'sinden ZIP olarak
geri indirir ve hash zincirini dogrular:

  1. API listesi: tek artefakt, beklenen ad ve kimlik, suresi dolmamis;
     API `digest` = upload adiminin `artifact-digest` ciktisi.
  2. ZIP: SHA256 = digest; CRC temiz; TEK uye, adi beklenen dosya adi.
  3. Icerik: uyenin SHA256'si = bu dosyadaki SABIT (yuklenen dosyadan
     hesaplanmaz); JSON ayristirilir.

Kati kurallar:

  * Token yalnizca GitHub API isteklerine gider. ZIP adresine yonlendirme
    ELLE izlenir ve o istege Authorization basligi EKLENMEZ: Python'un
    yerlesik yonlendirme izleyicisi basliklari yeni host'a tasir.
  * Yonlendirme adresi, token, yanit govdesi ya da istisna metni BASILMAZ.
    Cikti sabit satirlardir; hata yalnizca kategori ve HTTP kodu.
  * Yalnizca standart kutuphane: dogrulama kendi bagimliligini getirmez.

Gercek veri workflow'larini ya da secret'larini KANITLAMAZ; yalnizca
hosted upload/download yolunu ve dosya bicimini.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping
from typing import Any

ARTIFACT_NAME = "artifact-roundtrip"
MEMBER_NAME = "artifact-roundtrip.json"
EXPECTED_PAYLOAD_SHA256 = "f0397629c9617cdd4aaa1ef3d40aed210a41e64d89a889a5df0f9099d47362ab"
"""`payload.json`'un SHA256'si: BAGIMSIZ sabit. Testi depodaki dosyanin
bu degere esit oldugunu denetler; yuklenen dosyadan yeniden hesaplanmaz."""

MAX_API_BYTES = 1_000_000
MAX_ZIP_BYTES = 1_000_000
TIMEOUT_SECONDS = 30
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
REQUIRED_ENV = ("GITHUB_API_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GH_TOKEN")


class RoundtripError(Exception):
    """Basilabilir, SABIT bir metin tasir: adres, govde ya da token degil."""

    def __init__(self, category: str, detail: str) -> None:
        super().__init__(f"{category}: {detail}")
        self.category = category
        self.detail = detail


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Yonlendirmeyi izlemez; 3xx `HTTPError` olarak doner ve adresi
    biz okuruz. Boylece Authorization basligi yeni host'a tasinmaz."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _checked_url(url: str) -> str:
    """Yalnizca https; yerel test sunucusu (loopback) icin http."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS):
        return url
    raise RoundtripError("indirme", "beklenmeyen adres semasi")


def _api_request(url: str, token: str) -> urllib.request.Request:
    return urllib.request.Request(  # noqa: S310 - sema _checked_url ile denetlendi
        _checked_url(url),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _read_limited(response: Any, limit: int, category: str) -> bytes:
    body: bytes = response.read(limit + 1)
    if len(body) > limit:
        raise RoundtripError(category, "yanit boyut sinirini asti")
    return body


def list_artifacts(api: str, repo: str, run_id: str, token: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"name": ARTIFACT_NAME})
    url = f"{api}/repos/{repo}/actions/runs/{run_id}/artifacts?{query}"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(_api_request(url, token), timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(_read_limited(response, MAX_API_BYTES, "api"))
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RoundtripError("api", f"artefakt listesi HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RoundtripError("api", f"artefakt listesi okunamadi ({type(exc).__name__})") from None
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list):
        raise RoundtripError("api", "artefakt listesi beklenen bicimde degil")
    return [item for item in artifacts if isinstance(item, dict)]


def download_zip(api: str, repo: str, artifact_id: int, token: str) -> bytes:
    """API ZIP adresi -> (elle izlenen) yonlendirme -> baytlar.

    Ikinci istek YENI bir `Request`'tir: Authorization basligi yoktur.
    """
    url = f"{api}/repos/{repo}/actions/artifacts/{artifact_id}/zip"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(_api_request(url, token), timeout=TIMEOUT_SECONDS) as response:
            return _read_limited(response, MAX_ZIP_BYTES, "indirme")
    except urllib.error.HTTPError as exc:
        # Yanit nesnesi kapatilir; adres yalnizca bellekte tutulur, basilmaz.
        exc.close()
        if exc.code not in REDIRECT_CODES:
            raise RoundtripError("indirme", f"ZIP adresi HTTP {exc.code}") from None
        location = exc.headers.get("Location") if exc.headers is not None else None
    except (urllib.error.URLError, OSError) as exc:
        raise RoundtripError("indirme", f"ZIP adresi okunamadi ({type(exc).__name__})") from None
    if not location:
        raise RoundtripError("indirme", "yonlendirme adresi yok")

    plain = urllib.request.Request(_checked_url(location))  # noqa: S310 - sema denetlendi
    try:
        with urllib.request.urlopen(plain, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return _read_limited(response, MAX_ZIP_BYTES, "indirme")
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RoundtripError("indirme", f"ZIP HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise RoundtripError("indirme", f"ZIP okunamadi ({type(exc).__name__})") from None


def _hex_digest(value: str) -> str:
    """`sha256:<hex>` ya da `<hex>` -> kucuk harf hex; baska bicim hata."""
    text = value.strip().lower().removeprefix("sha256:")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise RoundtripError("digest", "digest bicimi gecersiz")
    return text


def verify(
    *, api: str, repo: str, run_id: str, token: str, artifact_id: int, upload_digest: str
) -> list[str]:
    """Butun zinciri dogrular; basilacak SABIT satirlari doner."""
    expected_digest = _hex_digest(upload_digest)

    listed = list_artifacts(api, repo, run_id, token)
    matches = [item for item in listed if item.get("name") == ARTIFACT_NAME]
    if len(matches) != 1:
        raise RoundtripError("artefakt", f"beklenen ad icin {len(matches)} artefakt")
    (artifact,) = matches
    if artifact.get("id") != artifact_id:
        raise RoundtripError("artefakt", "artefakt kimligi upload ciktisiyla uyusmuyor")
    if artifact.get("expired") is not False:
        raise RoundtripError("artefakt", "artefakt suresi dolmus ya da durum bilinmiyor")
    api_digest = _hex_digest(str(artifact.get("digest") or ""))
    if api_digest != expected_digest:
        raise RoundtripError("digest", "API digest'i upload ciktisiyla uyusmuyor")

    blob = download_zip(api, repo, artifact_id, token)
    if hashlib.sha256(blob).hexdigest() != expected_digest:
        raise RoundtripError("digest", "indirilen ZIP'in SHA256'si digest'le uyusmuyor")
    if artifact.get("size_in_bytes") != len(blob):
        raise RoundtripError("zip", "ZIP boyutu API'deki boyutla uyusmuyor")

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            if archive.testzip() is not None:
                raise RoundtripError("zip", "CRC hatasi")
            names = archive.namelist()
            if names != [MEMBER_NAME]:
                raise RoundtripError("zip", f"tek uye ve beklenen ad degil ({len(names)} uye)")
            member = archive.read(MEMBER_NAME)
    except zipfile.BadZipFile:
        raise RoundtripError("zip", "gecerli bir ZIP degil") from None

    member_digest = hashlib.sha256(member).hexdigest()
    if member_digest != EXPECTED_PAYLOAD_SHA256:
        raise RoundtripError("icerik", "uye SHA256'si beklenen sabitle uyusmuyor")
    try:
        document = json.loads(member)
    except ValueError:
        raise RoundtripError("icerik", "uye JSON olarak ayristirilamadi") from None
    if not isinstance(document, dict) or document.get("kind") != ARTIFACT_NAME:
        raise RoundtripError("icerik", "JSON beklenen turde degil")

    return [
        f"OK artefakt: kimlik {artifact_id}, {len(blob)} bayt, digest {expected_digest[:12]}",
        f"OK zip: tek uye {MEMBER_NAME}, CRC temiz, SHA256 digest'le ayni",
        f"OK icerik: SHA256 {member_digest[:12]} beklenen sabitle ayni, JSON gecerli",
    ]


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify.py")
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--upload-digest", required=True)
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ

    missing = [name for name in REQUIRED_ENV if not env.get(name, "").strip()]
    if missing:
        print(f"FAIL yapilandirma: eksik ortam degiskeni: {', '.join(missing)}")
        return 1
    try:
        artifact_id = int(args.artifact_id)
    except ValueError:
        print("FAIL yapilandirma: artefakt kimligi sayi degil")
        return 1

    try:
        lines = verify(
            api=env["GITHUB_API_URL"].rstrip("/"),
            repo=env["GITHUB_REPOSITORY"],
            run_id=env["GITHUB_RUN_ID"],
            token=env["GH_TOKEN"].strip(),
            artifact_id=artifact_id,
            upload_digest=args.upload_digest,
        )
    except RoundtripError as exc:
        print(f"FAIL {exc.category}: {exc.detail}")
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
