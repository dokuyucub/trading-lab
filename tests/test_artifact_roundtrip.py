"""Artefakt gidis-donus dogrulayicisi: iki yerel sahte sunucuya karsi (#17, #39).

Biri GitHub API'sini (liste + ZIP yonlendirmesi), digeri yonlendirilen
indirme host'unu taklit eder. Kanitlananlar:

  * Basarida zincir tam: liste, digest, ZIP hash'i, CRC, tek uye, ad,
    BAGIMSIZ sabite karsi icerik hash'i, JSON.
  * Token yalnizca API host'una gider; indirme host'una Authorization
    basligi GITMEZ.
  * TEK yonlendirme: indirme host'unun ikinci yonlendirmesi izlenmez.
    Baglanti korumasi (`connections`) iki test sunucusu disindaki her
    hedefe baglanma denemesini kaydeder ve durdurur.
  * Token ve yonlendirme adresi (imzali sorgu dahil) hicbir ciktida yok.
  * Zincirin her halkasi bozulunca kirmizi ve SABIT bir kategoriyle.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import socket
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "artifact_roundtrip" / "verify.py"
PAYLOAD = REPO / "scripts" / "artifact_roundtrip" / "payload.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("artifact_roundtrip_verify", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load()

# Calisma aninda kurulur: kaynakta duz bir token benzeri dize durmasin.
TOKEN = "".join(["ghs", "_", "roundtrip", "canary", "token"])
SIGNATURE = "".join(["SAS", "CANARY", "signature"])
ARTIFACT_ID = 4242
RUN_ID = "777"


def make_zip(members: dict[str, bytes], *, stored: bool = False) -> bytes:
    buffer = io.BytesIO()
    method = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(buffer, "w", compression=method) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def good_zip() -> bytes:
    return make_zip({verify.MEMBER_NAME: PAYLOAD.read_bytes()})


@dataclass
class Fake:
    """Iki sunucunun gordukleri ve dondurecekleri."""

    blob: bytes = b""
    artifacts: list[dict[str, Any]] | None = None
    list_status: int = 200
    zip_status: int = 302
    location: str | None = None
    blob_status: int = 200
    blob_location: str | None = None
    api_headers: list[dict[str, str]] = field(default_factory=list)
    blob_headers: list[dict[str, str]] = field(default_factory=list)
    api_paths: list[str] = field(default_factory=list)


def _send(handler: BaseHTTPRequestHandler, status: int, body: bytes, **headers: str) -> None:
    handler.send_response(status)
    for key, value in headers.items():
        handler.send_header(key.replace("_", "-"), value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _api_handler(fake: Fake) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            fake.api_headers.append(dict(self.headers.items()))
            fake.api_paths.append(self.path)
            parsed = urlparse(self.path)
            if parsed.path == f"/repos/o/r/actions/runs/{RUN_ID}/artifacts":
                body = json.dumps({"artifacts": fake.artifacts or []}).encode()
                _send(self, fake.list_status, body, Content_Type="application/json")
            elif parsed.path == f"/repos/o/r/actions/artifacts/{ARTIFACT_ID}/zip":
                if fake.zip_status in (301, 302, 303, 307, 308):
                    extra = {} if fake.location is None else {"Location": fake.location}
                    _send(self, fake.zip_status, b"", **extra)
                else:
                    _send(self, fake.zip_status, fake.blob)
            else:
                _send(self, 404, b"{}")

        def log_message(self, *args: Any) -> None:
            """Sessiz."""

    return Handler


def _blob_handler(fake: Fake) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            fake.blob_headers.append(dict(self.headers.items()))
            if fake.blob_status in (301, 302, 303, 307, 308):
                extra = {} if fake.blob_location is None else {"Location": fake.blob_location}
                _send(self, fake.blob_status, b"", **extra)
            else:
                _send(self, fake.blob_status, fake.blob, Content_Type="application/zip")

        def log_message(self, *args: Any) -> None:
            """Sessiz."""

    return Handler


@dataclass
class Servers:
    fake: Fake
    api: str
    blob: str


@pytest.fixture
def servers() -> Iterator[Servers]:
    fake = Fake()
    started = []
    for handler in (_api_handler(fake), _blob_handler(fake)):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
    api = f"http://127.0.0.1:{started[0][0].server_address[1]}"
    blob = f"http://127.0.0.1:{started[1][0].server_address[1]}"
    try:
        yield Servers(fake, api, blob)
    finally:
        for server, thread in started:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def server_addresses(servers: Servers) -> set[tuple[str, int]]:
    addresses = set()
    for url in (servers.api, servers.blob):
        parts = urlparse(url)
        assert parts.hostname is not None and parts.port is not None
        addresses.add((parts.hostname, parts.port))
    return addresses


@pytest.fixture
def connections(servers: Servers, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Dogrulayicinin denedigi HER TCP baglantisi kaydedilir. Iki test
    sunucusunun TAM adres-port cifti disindaki hedef, baglanmadan durdurulur.
    "Loopback'e izin" yetmez: bu ortamda HTTPS_PROXY de loopback'te."""
    allowed = server_addresses(servers)
    seen: list[tuple[str, int]] = []
    real = socket.create_connection

    def guarded(address: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        seen.append((address[0], address[1]))
        if (address[0], address[1]) not in allowed:
            raise AssertionError("test sunuculari disinda bir adrese baglanti denendi")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)
    return seen


def arrange(servers: Servers, blob: bytes, **changes: Any) -> str:
    """Tutarli bir senaryo kurar; `changes` tek bir halkayi bozar. Upload
    digest'ini doner."""
    fake = servers.fake
    digest = hashlib.sha256(blob).hexdigest()
    fake.blob = blob
    fake.location = f"{servers.blob}/artifacts/{ARTIFACT_ID}.zip?sig={SIGNATURE}"
    fake.artifacts = [
        {
            "id": ARTIFACT_ID,
            "name": verify.ARTIFACT_NAME,
            "size_in_bytes": len(blob),
            "digest": f"sha256:{digest}",
            "expired": False,
        }
    ]
    for key, value in changes.items():
        setattr(fake, key, value)
    return digest


def run(servers: Servers, digest: str, **env: str) -> int:
    environ = {
        "GITHUB_API_URL": servers.api,
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": RUN_ID,
        "GH_TOKEN": TOKEN,
        **env,
    }
    code: int = verify.main(["--artifact-id", str(ARTIFACT_ID), "--upload-digest", digest], environ)
    return code


def assert_clean(text: str) -> None:
    assert TOKEN not in text, "token ciktiya dustu"
    assert SIGNATURE not in text, "yonlendirme adresi ciktiya dustu"
    assert "127.0.0.1" not in text, "adres ciktiya dustu"


# --------------------------------------------------------------------------
# Sabit ve basari yolu
# --------------------------------------------------------------------------


def test_the_payload_matches_the_independent_constant() -> None:
    """Beklenen icerik hash'i dogrulayicidaki SABIT; depodaki dosya ona esit.
    Biri payload'i degistirirse sabit de bilincli olarak degismeli."""
    data = PAYLOAD.read_bytes()
    assert hashlib.sha256(data).hexdigest() == verify.EXPECTED_PAYLOAD_SHA256
    document = json.loads(data)
    assert document["kind"] == verify.ARTIFACT_NAME
    assert set(document) == {"kind", "note", "schema"}


def test_a_consistent_roundtrip_passes_and_the_token_stays_on_the_api_host(
    servers: Servers, connections: list[tuple[str, int]], capsys: pytest.CaptureFixture[str]
) -> None:
    digest = arrange(servers, good_zip())
    assert run(servers, digest) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert [line.split(":")[0] for line in lines] == ["OK artefakt", "OK zip", "OK icerik"]
    assert_clean(captured.out + captured.err)

    fake = servers.fake
    assert all(headers.get("Authorization") == f"Bearer {TOKEN}" for headers in fake.api_headers)
    assert len(fake.api_headers) == 2
    listing = urlparse(fake.api_paths[0])
    assert parse_qs(listing.query) == {"name": [verify.ARTIFACT_NAME]}
    assert len(fake.blob_headers) == 1
    assert "Authorization" not in fake.blob_headers[0], "token indirme host'una gitti"
    assert set(connections) == server_addresses(servers)


def test_the_sha256_prefix_on_the_upload_digest_is_accepted(servers: Servers) -> None:
    digest = arrange(servers, good_zip())
    assert run(servers, f"sha256:{digest.upper()}") == 0


def test_a_direct_zip_answer_without_redirect_is_accepted(servers: Servers) -> None:
    digest = arrange(servers, good_zip(), zip_status=200)
    assert run(servers, digest) == 0
    assert servers.fake.blob_headers == []


# --------------------------------------------------------------------------
# Her halka bozulunca kirmizi
# --------------------------------------------------------------------------


def _fails(
    servers: Servers, capsys: pytest.CaptureFixture[str], digest: str, category: str
) -> None:
    assert run(servers, digest) == 1
    captured = capsys.readouterr()
    assert captured.out.startswith(f"FAIL {category}: "), captured.out
    assert "OK " not in captured.out
    assert_clean(captured.out + captured.err)


def test_wrong_member_content_fails_against_the_constant(
    servers: Servers, capsys: pytest.CaptureFixture[str]
) -> None:
    """ZIP ve digest kendi icinde tutarli; icerik sabitle uyusmuyor."""
    blob = make_zip({verify.MEMBER_NAME: b'{"kind": "artifact-roundtrip", "x": 1}\n'})
    _fails(servers, capsys, arrange(servers, blob), "icerik")


def test_valid_json_of_the_wrong_kind_still_fails_on_the_hash(
    servers: Servers, capsys: pytest.CaptureFixture[str]
) -> None:
    blob = make_zip({verify.MEMBER_NAME: b"{}\n"})
    _fails(servers, capsys, arrange(servers, blob), "icerik")


@pytest.mark.parametrize(
    "members",
    [
        {verify.MEMBER_NAME: PAYLOAD.read_bytes(), "extra.json": b"{}"},
        {"other-name.json": PAYLOAD.read_bytes()},
        {},
    ],
    ids=["iki-uye", "farkli-ad", "bos"],
)
def test_the_zip_must_hold_exactly_the_expected_member(
    servers: Servers, capsys: pytest.CaptureFixture[str], members: dict[str, bytes]
) -> None:
    _fails(servers, capsys, arrange(servers, make_zip(members)), "zip")


def test_a_bad_crc_fails(servers: Servers, capsys: pytest.CaptureFixture[str]) -> None:
    payload = PAYLOAD.read_bytes()
    blob = bytearray(make_zip({verify.MEMBER_NAME: payload}, stored=True))
    start = bytes(blob).index(payload)
    blob[start] ^= 0x01  # CRC tutmaz; digest bozuk ZIP uzerinden hesaplanir
    _fails(servers, capsys, arrange(servers, bytes(blob)), "zip")


def test_garbage_instead_of_a_zip_fails(
    servers: Servers, capsys: pytest.CaptureFixture[str]
) -> None:
    _fails(servers, capsys, arrange(servers, b"bu bir zip degil"), "zip")


def test_the_downloaded_zip_must_match_the_digest(
    servers: Servers, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = arrange(servers, good_zip())
    servers.fake.blob = make_zip({verify.MEMBER_NAME: PAYLOAD.read_bytes() + b" "})
    artifacts = servers.fake.artifacts
    assert artifacts is not None
    artifacts[0]["size_in_bytes"] = len(servers.fake.blob)
    _fails(servers, capsys, digest, "digest")


def test_the_api_digest_must_match_the_upload_output(
    servers: Servers, capsys: pytest.CaptureFixture[str]
) -> None:
    """Yalnizca API'nin bildirdigi digest yanlis: upload ciktisi ve ZIP
    birbiriyle tutarli. Bu halka tek basina kirmizi olmali (bozma turu:
    onceki surum sonraki halkaya yaslaniyordu)."""
    digest = arrange(servers, good_zip())
    artifacts = servers.fake.artifacts
    assert artifacts is not None
    artifacts[0]["digest"] = "sha256:" + "0" * 64
    _fails(servers, capsys, digest, "digest")
    assert servers.fake.blob_headers == [], "digest tutmazken ZIP indirildi"


def test_a_wrong_upload_digest_fails(servers: Servers, capsys: pytest.CaptureFixture[str]) -> None:
    arrange(servers, good_zip())
    _fails(servers, capsys, "0" * 64, "digest")


def test_a_malformed_upload_digest_fails(
    servers: Servers, capsys: pytest.CaptureFixture[str]
) -> None:
    arrange(servers, good_zip())
    _fails(servers, capsys, "", "digest")


def test_the_size_must_match_the_api(servers: Servers, capsys: pytest.CaptureFixture[str]) -> None:
    digest = arrange(servers, good_zip())
    artifacts = servers.fake.artifacts
    assert artifacts is not None
    artifacts[0]["size_in_bytes"] = 1
    _fails(servers, capsys, digest, "zip")


@pytest.mark.parametrize(
    "case",
    ["yok", "iki", "kimlik", "suresi-dolmus", "durum-bilinmiyor"],
)
def test_the_artifact_listing_must_name_exactly_the_uploaded_one(
    servers: Servers, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    digest = arrange(servers, good_zip())
    fake = servers.fake
    assert fake.artifacts is not None
    item = fake.artifacts[0]
    if case == "yok":
        fake.artifacts = []
    elif case == "iki":
        fake.artifacts = [item, dict(item, id=ARTIFACT_ID + 1)]
    elif case == "kimlik":
        item["id"] = ARTIFACT_ID + 1
    elif case == "suresi-dolmus":
        item["expired"] = True
    else:
        del item["expired"]
    _fails(servers, capsys, digest, "artefakt")


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_api_errors_print_only_the_status(
    servers: Servers, capsys: pytest.CaptureFixture[str], status: int
) -> None:
    digest = arrange(servers, good_zip(), list_status=status)
    _fails(servers, capsys, digest, "api")


@pytest.mark.parametrize(
    "changes",
    [{"zip_status": 403}, {"location": None}, {"blob_status": 403}],
    ids=["zip-adresi-403", "yonlendirme-adresi-yok", "indirme-403"],
)
def test_download_errors_print_a_fixed_category(
    servers: Servers, capsys: pytest.CaptureFixture[str], changes: dict[str, Any]
) -> None:
    digest = arrange(servers, good_zip())
    for key, value in changes.items():
        setattr(servers.fake, key, value)
    _fails(servers, capsys, digest, "indirme")


def test_a_non_https_redirect_off_loopback_is_refused_before_any_request(
    servers: Servers, connections: list[tuple[str, int]], capsys: pytest.CaptureFixture[str]
) -> None:
    """Sema denetimi istekten ONCE: adres ne istenir ne basilir. Kanit
    baglanti duzeyinde: yalnizca API sunucusuna baglanildi."""
    location = f"http://example.invalid/a.zip?sig={SIGNATURE}"
    digest = arrange(servers, good_zip(), location=location)
    _fails(servers, capsys, digest, "indirme")
    assert servers.fake.blob_headers == []
    api = urlparse(servers.api)
    assert connections, "API'ye bile baglanilmadi"
    assert set(connections) == {(api.hostname, api.port)}, "guvensiz adrese baglanti denendi"


SECOND_HOPS = {
    "loopback-disi-http": "http://example.invalid/second-hop.zip?sig={sig}",
    "https": "https://example.invalid/second-hop.zip?sig={sig}",
    "ayni-host": "{blob}/second-hop.zip?sig={sig}",
}


@pytest.mark.parametrize("second_hop", list(SECOND_HOPS.values()), ids=list(SECOND_HOPS))
def test_a_second_redirect_is_refused_and_never_followed(
    servers: Servers,
    connections: list[tuple[str, int]],
    capsys: pytest.CaptureFixture[str],
    second_hop: str,
) -> None:
    """TEK yonlendirme (Codex P2, #41): indirme host'u yeniden yonlendirirse
    ikinci adres, semasi ne olursa olsun, okunmaz, istenmez ve basilmaz.
    Indirme host'u tek istek gorur ve Authorization almaz."""
    location = second_hop.format(blob=servers.blob, sig=SIGNATURE)
    digest = arrange(servers, good_zip(), blob_status=302, blob_location=location)
    assert run(servers, digest) == 1
    captured = capsys.readouterr()
    assert captured.out == "FAIL indirme: ikinci yonlendirme reddedildi (HTTP 302)\n"
    assert captured.err == ""
    assert_clean(captured.out)

    fake = servers.fake
    assert len(fake.blob_headers) == 1, "ikinci yonlendirme izlendi"
    assert "Authorization" not in fake.blob_headers[0], "token indirme host'una gitti"
    assert set(connections) <= server_addresses(servers), "baska bir adrese baglanti denendi"


def test_an_oversized_download_is_refused(
    servers: Servers, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = arrange(servers, good_zip())
    monkeypatch.setattr(verify, "MAX_ZIP_BYTES", 16)
    _fails(servers, capsys, digest, "indirme")


def test_an_oversized_listing_is_refused(
    servers: Servers, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = arrange(servers, good_zip())
    monkeypatch.setattr(verify, "MAX_API_BYTES", 16)
    _fails(servers, capsys, digest, "api")


@pytest.mark.parametrize(
    "missing", ["GITHUB_API_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GH_TOKEN"]
)
def test_missing_configuration_fails_before_any_request(
    servers: Servers, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    digest = arrange(servers, good_zip())
    assert run(servers, digest, **{missing: ""}) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL yapilandirma: ")
    assert servers.fake.api_headers == [], "yapilandirma eksikken istek yapildi"
    assert_clean(out)


def test_a_non_numeric_artifact_id_fails(capsys: pytest.CaptureFixture[str]) -> None:
    environ = dict.fromkeys(verify.REQUIRED_ENV, "x")
    assert verify.main(["--artifact-id", "abc", "--upload-digest", "0" * 64], environ) == 1
    assert capsys.readouterr().out.startswith("FAIL yapilandirma: ")
