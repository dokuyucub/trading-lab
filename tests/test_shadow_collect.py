"""Golge toplam isi: gun ozeti artefaktlarini indirme (tasarim §6, #17).

Iki yerel sunucu: sahte GitHub API'si ve ayri bir indirme host'u. API
ZIP adresine 302 ile yonlendirir. Gosterilenler:

  * toplam BIR kez ve son planli gunden sonra: erken, yeniden deneme,
    onceki basarili toplam, secret'li ya da eksik ortam hic istek yapmaz
    (onceki toplam denetimi disinda);
  * yonlendirme elle ve bir kez izlenir; indirme istegine Authorization
    gitmez, ikinci yonlendirme okunmaz, https disi adres reddedilir;
  * ZIP tek uyeli ve sabit adli; bicim, boyut, sema ve gun denetlenir;
  * suresi dolmus artefakt atlanir, o gun toplamda kosu kanitiyla
    siniflanir; hata kismi toplam yazdirmaz;
  * cikti token, adres ya da govde tasimaz.
"""

from __future__ import annotations

import io
import json
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from tlab import shadow_job
from tlab.core.clock import SimClock

D1, D2 = date(2026, 1, 5), date(2026, 1, 6)
PLANNED = (D1, D2)
AFTER = SimClock(datetime(2026, 1, 7, 15, 0, tzinfo=UTC))
REPO = "owner/repo"
TOKEN = "COLLECT-CANARY-TOKEN"  # noqa: S105 - ciktida ARANAN sahte isaret
BODY = "COLLECT-BODY-CANARY"
RUNS_PATH = f"/repos/{REPO}/actions/workflows/{shadow_job.WORKFLOW_FILE}/runs"
TOTAL_RUNS_PATH = f"/repos/{REPO}/actions/workflows/{shadow_job.AGGREGATE_WORKFLOW_FILE}/runs"


def day_zip(day: date, *, name: str = shadow_job.DAY_FILE, extra: bool = False) -> bytes:
    payload = {"day_schema": shadow_job.DAY_SCHEMA, "day": day.isoformat(), "status": "tamam"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, json.dumps({**payload, "reason": None, "symbols": []}))
        if extra:
            archive.writestr("ikinci.json", "{}")
    return buffer.getvalue()


@dataclass
class Host:
    """Indirme host'u: yollara gore ZIP ya da yonlendirme doner."""

    files: dict[str, bytes] = field(default_factory=dict)
    redirect_to: str | None = None
    requests: list[tuple[str, str | None]] = field(default_factory=list)


@dataclass
class Api:
    runs: list[dict[str, Any]] = field(default_factory=list)
    runs_total: int | None = None
    totals: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    jobs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    zips: dict[str, str] = field(default_factory=dict)
    """artefakt kimligi -> yonlendirme adresi."""
    requests: list[tuple[str, str | None]] = field(default_factory=list)


def _start(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _reply(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


@pytest.fixture
def host() -> Iterator[tuple[Host, str]]:
    state = Host()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append((self.path, self.headers.get("Authorization")))
            if state.redirect_to is not None:
                self.send_response(302)
                self.send_header("Location", state.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = state.files.get(self.path)
            _reply(self, 200 if data is not None else 404, data or {"message": BODY})

        def log_message(self, *args: Any) -> None:
            """Sessiz."""

    server, url = _start(Handler)
    try:
        yield state, url
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def api() -> Iterator[tuple[Api, str]]:
    state = Api()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append((self.path, self.headers.get("Authorization")))
            path = urlparse(self.path).path
            parts = path.split("/")
            if path == RUNS_PATH:
                total = len(state.runs) if state.runs_total is None else state.runs_total
                _reply(self, 200, {"total_count": total, "workflow_runs": state.runs})
            elif path == TOTAL_RUNS_PATH:
                _reply(self, 200, {"total_count": len(state.totals), "workflow_runs": state.totals})
            elif path.endswith("/artifacts") and "/actions/runs/" in path:
                items = state.artifacts.get(parts[-2], [])
                _reply(self, 200, {"total_count": len(items), "artifacts": items})
            elif path.endswith("/jobs") and "/actions/runs/" in path:
                items = state.jobs.get(parts[-2], [])
                _reply(self, 200, {"total_count": len(items), "jobs": items})
            elif path.endswith("/zip") and parts[-2] in state.zips:
                self.send_response(302)
                self.send_header("Location", state.zips[parts[-2]])
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                _reply(self, 404, {"message": BODY})

        def log_message(self, *args: Any) -> None:
            """Sessiz."""

    server, url = _start(Handler)
    try:
        yield state, url
    finally:
        server.shutdown()
        server.server_close()


def env(api_url: str, **extra: str) -> dict[str, str]:
    return {
        "GITHUB_API_URL": api_url,
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_RUN_ID": "900",
        "GH_TOKEN": TOKEN,
        **extra,
    }


def run(run_id: int, created: str) -> dict[str, Any]:
    return {"id": run_id, "created_at": created}


def artifact(artifact_id: int, *, expired: bool = False) -> dict[str, Any]:
    return {"id": artifact_id, "name": shadow_job.DAY_ARTIFACT, "expired": expired}


def serve(api: Api, host: Host, host_url: str, run_id: int, day: date, data: bytes) -> None:
    """Bir kosunun gun ozeti: API listesi, 302 ve indirme host'undaki ZIP."""
    artifact_id = 1000 + run_id
    api.artifacts[str(run_id)] = [artifact(artifact_id)]
    api.zips[str(artifact_id)] = f"{host_url}/blob/{artifact_id}?sig=IMZA"
    host.files[f"/blob/{artifact_id}?sig=IMZA"] = data


def collect(
    environment: dict[str, str], tmp_path: Path, clock: SimClock = AFTER
) -> tuple[int, Path]:
    days = tmp_path / "days"
    return shadow_job.collect(environment, clock=clock, days_dir=days, planned=PLANNED), days


# --------------------------------------------------------------------------
# Indirme ve toplam
# --------------------------------------------------------------------------


def test_day_summaries_are_downloaded_and_the_total_classifies_the_rest(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [
        run(11, "2026-01-05T13:50:03Z"),
        run(12, "2026-01-06T13:50:03Z"),
        run(13, "2026-01-06T12:50:03Z"),
    ]
    serve(state, blobs, host_url, 11, D1, day_zip(D1))
    # D2: ozeti suresi dolmus; kayit adimi gercekten kostu.
    state.artifacts["12"] = [artifact(112, expired=True)]
    state.jobs["12"] = [
        {
            "name": shadow_job.RECORD_JOB,
            "status": "completed",
            "conclusion": "success",
            "steps": [{"name": "Gozle", "status": "completed", "conclusion": "success"}],
        }
    ]
    code, days = collect(env(api_url), tmp_path)
    assert code == 0
    assert sorted(path.name for path in days.iterdir()) == ["11.json"]

    out = tmp_path / "total.json"
    assert (
        shadow_job.aggregate(
            env(api_url), days_dir=days, out=out, root=project_root, planned=PLANNED
        )
        == 0
    )
    total = json.loads(out.read_text(encoding="utf-8"))
    assert [(item["day"], item["status"], item["reason"]) for item in total["day_list"]] == [
        (D1.isoformat(), "tamam", None),
        (D2.isoformat(), "eksik", "kayit adimi kostu, ozet yok"),
    ]
    text = capsys.readouterr().out
    assert "OK toplam: 1 gun ozeti indirildi" in text
    assert "suresi dolmus" in text
    assert TOKEN not in text and "IMZA" not in text and BODY not in text


def test_the_token_goes_only_to_the_api_and_the_redirect_is_followed_once(
    api: tuple[Api, str], host: tuple[Host, str], tmp_path: Path
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, D1, day_zip(D1))
    code, _ = collect(env(api_url), tmp_path)
    assert code == 0
    assert state.requests and all(auth == f"Bearer {TOKEN}" for _, auth in state.requests)
    assert blobs.requests == [("/blob/1011?sig=IMZA", None)], "indirmeye Authorization gitmez"


def test_a_second_redirect_is_refused_and_not_followed(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, D1, day_zip(D1))
    blobs.redirect_to = f"{host_url}/third?sig=IKINCI"
    code, days = collect(env(api_url), tmp_path)
    assert code == 1
    assert "ikinci yonlendirme reddedildi (HTTP 302)" in capsys.readouterr().out
    assert [path for path, _ in blobs.requests] == ["/blob/1011?sig=IMZA"], "ucuncu adres istenmez"
    assert not list(days.glob("*.json"))


def test_a_non_https_download_address_is_refused(
    api: tuple[Api, str], host: tuple[Host, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    blobs, _ = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.artifacts["11"] = [artifact(1011)]
    state.zips["1011"] = "http://example.invalid/blob?sig=IMZA"
    code, _ = collect(env(api_url), tmp_path)
    assert code == 1
    text = capsys.readouterr().out
    assert "beklenmeyen adres semasi" in text
    assert "example.invalid" not in text and "IMZA" not in text
    assert blobs.requests == []


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (day_zip(D1, extra=True), "ZIP beklenen tek uyeyi tasimiyor"),
        (day_zip(D1, name="baska.json"), "ZIP beklenen tek uyeyi tasimiyor"),
        (day_zip(D1, name="../shadow-day.json"), "ZIP beklenen tek uyeyi tasimiyor"),
        (day_zip(D1, name="alt/shadow-day.json"), "ZIP beklenen tek uyeyi tasimiyor"),
        (b"PK\x03\x04bozuk", "ZIP okunamadi (bicim ya da CRC)"),
        (day_zip(D2), "gun ozetinin gunu kosuyla ya da planla uyusmuyor"),
    ],
    ids=["iki-uye", "baska-ad", "ust-dizin", "alt-dizin", "bozuk", "baska-gun"],
)
def test_an_unexpected_archive_fails_the_whole_collection(
    data: bytes,
    reason: str,
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, D1, data)
    code, days = collect(env(api_url), tmp_path)
    assert code == 1
    assert reason in capsys.readouterr().out
    assert not list(days.glob("*.json"))


def test_an_undefined_schema_is_refused(
    api: tuple[Api, str], host: tuple[Host, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    blobs, host_url = host
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(shadow_job.DAY_FILE, json.dumps({"day_schema": 99, "day": "2026-01-05"}))
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, D1, buffer.getvalue())
    assert collect(env(api_url), tmp_path)[0] == 1
    assert "gun ozeti semasi tanimsiz" in capsys.readouterr().out


def test_an_oversized_member_is_refused(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, api_url = api
    blobs, host_url = host
    monkeypatch.setattr(shadow_job, "MAX_DAY_BYTES", 10)
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, D1, day_zip(D1))
    assert collect(env(api_url), tmp_path)[0] == 1
    assert "gun ozeti boyut sinirini asti" in capsys.readouterr().out


def lying_zip(day: date, declared: int) -> bytes:
    """Uye boyutunu (yerel ve merkezi baslikta) oldugundan kucuk bildiren ZIP."""
    buffer = io.BytesIO()
    payload = json.dumps({"day_schema": shadow_job.DAY_SCHEMA, "day": day.isoformat()})
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(shadow_job.DAY_FILE, payload)
    data = bytearray(buffer.getvalue())
    size = declared.to_bytes(4, "little")
    local = data.index(b"PK\x03\x04")
    data[local + 18 : local + 26] = size + size
    central = data.index(b"PK\x01\x02")
    data[central + 20 : central + 28] = size + size
    return bytes(data)


def test_a_member_that_lies_about_its_size_is_refused(
    api: tuple[Api, str], host: tuple[Host, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Okuma bildirilen boyutta durur ve CRC tutmaz: kisaltilmis icerik kabul edilmez."""
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, D1, lying_zip(D1, declared=10))
    assert collect(env(api_url), tmp_path)[0] == 1
    assert "ZIP okunamadi (bicim ya da CRC)" in capsys.readouterr().out


def test_two_day_artifacts_in_one_run_fail(
    api: tuple[Api, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.artifacts["11"] = [artifact(1), artifact(2)]
    assert collect(env(api_url), tmp_path)[0] == 1
    assert "birden cok gun ozeti artefakti" in capsys.readouterr().out


def test_more_than_one_page_of_runs_fails(
    api: tuple[Api, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.runs_total = 101
    assert collect(env(api_url), tmp_path)[0] == 1
    assert "kosu listesi tek sayfayi asti" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Tek toplam: hic istek yapmadan reddedilen durumlar
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "clock", "planned", "reason"),
    [
        ({"ALPACA_PAPER_API_KEY": "x"}, AFTER, PLANNED, "toplam isi secret'siz calisir"),
        ({}, AFTER, (), "planli gun yok"),
        ({}, SimClock(datetime(2026, 1, 6, 23, 0, tzinfo=UTC)), PLANNED, "henuz bitmedi"),
        ({"GITHUB_RUN_ATTEMPT": "2"}, AFTER, PLANNED, "yeniden deneme kosusu"),
        ({"GH_TOKEN": ""}, AFTER, PLANNED, "Actions API ortami eksik"),
    ],
    ids=["secret", "plan-bos", "erken", "yeniden-deneme", "ortam-eksik"],
)
def test_a_refused_collection_makes_no_request(
    environment: dict[str, str],
    clock: SimClock,
    planned: tuple[date, ...],
    reason: str,
    api: tuple[Api, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    code = shadow_job.collect(
        env(api_url, **environment), clock=clock, days_dir=tmp_path / "days", planned=planned
    )
    assert code == 1
    assert reason in capsys.readouterr().out
    assert state.requests == []


def test_a_prior_successful_total_blocks_a_second_one(
    api: tuple[Api, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.totals = [{"id": 800, "conclusion": "success"}, {"id": 950, "conclusion": "success"}]
    assert collect(env(api_url), tmp_path)[0] == 1
    assert "toplam daha once uretildi" in capsys.readouterr().out
    assert [urlparse(path).path for path, _ in state.requests] == [TOTAL_RUNS_PATH]


def test_a_later_or_failed_total_does_not_block(api: tuple[Api, str], tmp_path: Path) -> None:
    state, api_url = api
    state.totals = [{"id": 950, "conclusion": "success"}, {"id": 800, "conclusion": "failure"}]
    assert collect(env(api_url), tmp_path)[0] == 0


def test_an_unreadable_history_fails_without_leaks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = shadow_job.collect(
        env("http://127.0.0.1:9"), clock=AFTER, days_dir=tmp_path / "days", planned=PLANNED
    )
    assert code == 1
    text = capsys.readouterr().out
    assert "toplam kosu listesi okunamadi" in text
    assert TOKEN not in text
