"""Golge toplam isi: gun ozeti artefaktlarini secme ve indirme (tasarim §6, #17).

Iki yerel sunucu: sahte GitHub API'si ve ayri bir indirme host'u. API
ZIP adresine 302 ile yonlendirir. Gosterilenler:

  * toplam kampanya basina BIR kez ve son planli gunden sonra: erken (New
    York tarihi), yeniden deneme, secret'li ya da eksik ortam hic istek
    yapmaz; bu kampanyanin toplam artefakti varsa ya da onceki toplam
    kosusu bitmediyse hicbir gozlem artefakti indirilmez. Basariyla biten
    ama cikti birakmayan toplam kosusu engel degildir;
  * yalnizca `main` dalindaki zamanlanmis, ilk denemeli gozlem kosusu
    secilir; plan disi gunun kosusu listelenmez; planli gunun bitmemis
    kosusu varsa hicbir sey indirilmez; gun ozetinin kaynagi (run_id,
    run_attempt, code_sha) API kosusuyla eslesmeli;
  * onceki toplam kosularinin ADIM kaniti okunur: toplam adimi kostuysa
    (upload hatasi, silinmis cikti) ya da sonucu belirsizse durur; bos,
    erken ya da reddedilmis kosu engel degil; yeniden deneme yalnizca
    koddaki `TOTAL_RETRY_AFTER` ile (Codex 6172892558, 6175607709);
  * digest eksikse indirilmez, uyusmazsa kabul edilmez;
  * yonlendirme elle ve bir kez izlenir; indirme istegine Authorization
    gitmez, ikinci yonlendirme okunmaz, https disi adres reddedilir;
  * ZIP tek uyeli ve sabit adli; gun ozeti alan alan sozlesmeye gore
    denetlenir, biri uymazsa butun toplama durur;
  * suresi dolmus artefakt atlanir, o gun toplamda kosu kanitiyla
    siniflanir; hata kismi toplam yazdirmaz;
  * cikti token, adres ya da govde tasimaz.
"""

from __future__ import annotations

import hashlib
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
from urllib.parse import parse_qs, urlparse

import pytest

from shadow_days import (
    CODE_SHA,
    PARAMS_VERSION,
    TURNS,
    campaign,
    comparison,
    day_payload,
    no_sip,
    symbols_of,
    write_day,
)
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
ARTIFACTS_PATH = f"/repos/{REPO}/actions/artifacts"


def zipped(content: bytes | str, *, name: str = shadow_job.DAY_FILE, extra: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
        if extra:
            archive.writestr("ikinci.json", "{}")
    return buffer.getvalue()


def day_zip(root: Path, day: date, **overrides: Any) -> bytes:
    return zipped(json.dumps(day_payload(root, PLANNED, day, **overrides)))


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
    repo_artifacts: list[dict[str, Any]] = field(default_factory=list)
    """Depo artefakt listesi; `name` suzgeci uygulanMAZ (istemci de denetler)."""
    artifacts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    jobs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    zips: dict[str, str] = field(default_factory=dict)
    """artefakt kimligi -> yonlendirme adresi."""
    requests: list[tuple[str, str | None]] = field(default_factory=list)

    def paths(self) -> list[str]:
        return [urlparse(path).path for path, _ in self.requests]


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
            elif path == ARTIFACTS_PATH:
                items = state.repo_artifacts
                _reply(self, 200, {"total_count": len(items), "artifacts": items})
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


def run(run_id: int, created: str, **overrides: Any) -> dict[str, Any]:
    """Secilecek bicimde gozlem kosusu: main, zamanlanmis, ilk deneme, bitti,
    kodu `CODE_SHA` (gun ozeti fixture'inin yazdigi kaynak)."""
    return {
        "id": run_id,
        "created_at": created,
        "status": "completed",
        "head_branch": "main",
        "event": "schedule",
        "path": f".github/workflows/{shadow_job.WORKFLOW_FILE}",
        "run_attempt": 1,
        "head_sha": CODE_SHA,
        **overrides,
    }


def total_run(
    run_id: int, status: str = "completed", conclusion: str | None = "failure"
) -> dict[str, Any]:
    return {"id": run_id, "status": status, "conclusion": conclusion}


def total_job(
    collected: str | None,
    totaled: str | None,
    *,
    upload: str | None = None,
    status: str = "completed",
    conclusion: str | None = "failure",
    steps: Any = "",
) -> dict[str, Any]:
    """Onceki toplam kosusunun `total` isi: `Indir`, `Topla` ve yukleme adimlari."""
    if steps == "":
        steps = [
            {"name": "Kilitli calisma zamani bagimliliklarini kur", "conclusion": "success"},
            {"name": shadow_job.TOTAL_STEPS[0], "conclusion": collected},
            {"name": shadow_job.TOTAL_STEPS[1], "conclusion": totaled},
            {"name": "Toplami yukle", "conclusion": upload},
        ]
    return {
        "name": shadow_job.TOTAL_JOB,
        "status": status,
        "conclusion": conclusion,
        "steps": steps,
    }


def artifact(artifact_id: int, *, expired: bool = False, digest: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {"id": artifact_id, "name": shadow_job.DAY_ARTIFACT, "expired": expired}
    if digest is not None:
        item["digest"] = digest
    return item


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def serve(
    api: Api, host: Host, host_url: str, run_id: int, data: bytes, *, digest: Any = ""
) -> None:
    """Bir kosunun gun ozeti: API listesi (digest'le), 302 ve indirme host'undaki ZIP."""
    artifact_id = 1000 + run_id
    api.artifacts[str(run_id)] = [
        artifact(artifact_id, digest=sha256(data) if digest == "" else digest)
    ]
    api.zips[str(artifact_id)] = f"{host_url}/blob/{artifact_id}?sig=IMZA"
    host.files[f"/blob/{artifact_id}?sig=IMZA"] = data


def collect(
    environment: dict[str, str],
    tmp_path: Path,
    root: Path,
    clock: SimClock = AFTER,
    planned: tuple[date, ...] = PLANNED,
) -> tuple[int, Path]:
    days = tmp_path / "days"
    code = shadow_job.collect(
        environment,
        clock=clock,
        days_dir=days,
        root=root,
        output=tmp_path / "github-output",
        planned=planned,
    )
    return code, days


def written(days: Path) -> list[str]:
    return sorted(path.name for path in days.glob("*.json"))


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
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
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
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 0
    assert written(days) == ["11.json"]
    prefix = campaign(project_root, PLANNED)[: shadow_job.CAMPAIGN_PREFIX]
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == f"campaign={prefix}\n"
    total_query = parse_qs(urlparse(state.requests[1][0]).query)
    assert total_query["name"] == [f"{shadow_job.TOTAL_ARTIFACT}-{prefix}"]

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
    assert total["campaign"] == campaign(project_root, PLANNED)
    text = capsys.readouterr().out
    assert f"OK toplam: kampanya {prefix}, 1 gun ozeti indirildi" in text
    assert "suresi dolmus" in text
    assert TOKEN not in text and "IMZA" not in text and BODY not in text


def test_the_token_goes_only_to_the_api_and_the_redirect_is_followed_once(
    api: tuple[Api, str], host: tuple[Host, str], tmp_path: Path, project_root: Path
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    code, _ = collect(env(api_url), tmp_path, project_root)
    assert code == 0
    assert state.requests and all(auth == f"Bearer {TOKEN}" for _, auth in state.requests)
    assert blobs.requests == [("/blob/1011?sig=IMZA", None)], "indirmeye Authorization gitmez"


def test_a_second_redirect_is_refused_and_not_followed(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    blobs.redirect_to = f"{host_url}/third?sig=IKINCI"
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 1
    assert "ikinci yonlendirme reddedildi (HTTP 302)" in capsys.readouterr().out
    assert [path for path, _ in blobs.requests] == ["/blob/1011?sig=IMZA"], "ucuncu adres istenmez"
    assert not written(days)


def test_a_non_https_download_address_is_refused(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, _ = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.artifacts["11"] = [artifact(1011, digest=sha256(b"x"))]
    state.zips["1011"] = "http://example.invalid/blob?sig=IMZA"
    code, _ = collect(env(api_url), tmp_path, project_root)
    assert code == 1
    text = capsys.readouterr().out
    assert "beklenmeyen adres semasi" in text
    assert "example.invalid" not in text and "IMZA" not in text
    assert blobs.requests == []


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (zipped("{}", extra=True), "ZIP beklenen tek uyeyi tasimiyor"),
        (zipped("{}", name="baska.json"), "ZIP beklenen tek uyeyi tasimiyor"),
        (zipped("{}", name="../shadow-day.json"), "ZIP beklenen tek uyeyi tasimiyor"),
        (zipped("{}", name="alt/shadow-day.json"), "ZIP beklenen tek uyeyi tasimiyor"),
        (b"PK\x03\x04bozuk", "ZIP okunamadi (bicim ya da CRC)"),
        (zipped("{bozuk"), "gun ozeti JSON degil"),
        (zipped(b"\xff\xfe"), "gun ozeti JSON degil"),
        (zipped("[" * 100_000), "gun ozeti JSON degil"),
    ],
    ids=[
        "iki-uye",
        "baska-ad",
        "ust-dizin",
        "alt-dizin",
        "bozuk",
        "json-degil",
        "utf8-degil",
        "derin",
    ],
)
def test_an_unexpected_archive_fails_the_whole_collection(
    data: bytes,
    reason: str,
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z"), run(12, "2026-01-06T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    serve(state, blobs, host_url, 12, data)
    code, _ = collect(env(api_url), tmp_path, project_root)
    assert code == 1
    assert reason in capsys.readouterr().out
    assert not (tmp_path / "github-output").exists(), "yukleme adi yazilmaz"


def test_a_summary_of_another_day_or_campaign_fails_the_whole_collection(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D2))
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    assert "gun ozetinin gunu kosuyla uyusmuyor" in capsys.readouterr().out

    other = day_zip(project_root, D1, campaign=campaign(project_root, (D1,)))
    serve(state, blobs, host_url, 11, other)
    assert collect(env(api_url), tmp_path / "ikinci", project_root)[0] == 1
    assert "gun ozeti baska kampanyanin" in capsys.readouterr().out


def test_an_oversized_member_is_refused(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, api_url = api
    blobs, host_url = host
    monkeypatch.setattr(shadow_job, "MAX_DAY_BYTES", 10)
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
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
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Okuma bildirilen boyutta durur ve CRC tutmaz: kisaltilmis icerik kabul edilmez."""
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, lying_zip(D1, declared=10))
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    assert "ZIP okunamadi (bicim ya da CRC)" in capsys.readouterr().out


def test_two_day_artifacts_in_one_run_fail(
    api: tuple[Api, str], tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.artifacts["11"] = [artifact(1), artifact(2)]
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    assert "birden cok gun ozeti artefakti" in capsys.readouterr().out


def test_two_selected_summaries_of_one_day_fail(
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T12:50:03Z"), run(12, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    serve(state, blobs, host_url, 12, day_zip(project_root, D1, run_id=12))
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    assert "ayni gunun iki gun ozeti var" in capsys.readouterr().out


def test_more_than_one_page_of_runs_fails(
    api: tuple[Api, str], tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.runs_total = 101
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    assert "kosu listesi tek sayfayi asti" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Kosu secimi, son gun ve digest (Codex 6171961412)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "workflow_dispatch"},
        {"event": "push"},
        {"head_branch": "feature"},
        {"head_branch": None},
        {"path": ".github/workflows/baska.yml"},
        {"run_attempt": 2},
        {"run_attempt": True},
        {"run_attempt": "1"},
    ],
    ids=["dispatch", "push", "dal", "dal-yok", "yol", "deneme-2", "deneme-bool", "deneme-metin"],
)
def test_only_a_scheduled_first_attempt_main_run_is_selected(
    overrides: dict[str, Any],
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z"), run(12, "2026-01-06T13:50:03Z", **overrides)]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    serve(state, blobs, host_url, 12, day_zip(project_root, D2))
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 0
    assert written(days) == ["11.json"]
    assert f"/repos/{REPO}/actions/runs/12/artifacts" not in state.paths()
    assert f"UYARI toplam: {D2.isoformat()} kosusu secilmedi" in capsys.readouterr().out


def test_an_unplanned_day_run_is_not_listed(
    api: tuple[Api, str], host: tuple[Host, str], tmp_path: Path, project_root: Path
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [
        run(10, "2026-01-04T13:50:03Z", status="in_progress"),
        run(11, "2026-01-05T13:50:03Z"),
        run(13, "2026-01-07T13:50:03Z", status="queued"),
    ]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    serve(state, blobs, host_url, 13, day_zip(project_root, D2))
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 0
    assert written(days) == ["11.json"]
    listed = [path for path in state.paths() if path.endswith("/artifacts")]
    assert listed == [ARTIFACTS_PATH, f"/repos/{REPO}/actions/runs/11/artifacts"]


@pytest.mark.parametrize("status", ["in_progress", "queued", "waiting", None])
def test_an_unfinished_planned_day_run_stops_before_any_download(
    status: str | None,
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Son gunun gozlemi ya da SIP bekleyisi suruyorsa toplam baslamaz;
    once butun kosular okunur, hicbir artefakt listelenmez."""
    state, api_url = api
    blobs, host_url = host
    state.runs = [
        run(11, "2026-01-05T13:50:03Z"),
        run(12, "2026-01-06T13:50:03Z", status=status, event="workflow_dispatch"),
    ]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 1
    assert "planli gunun gozlem kosusu henuz bitmedi" in capsys.readouterr().out
    assert not [path for path in state.paths() if "/actions/runs/" in path]
    assert blobs.requests == []
    assert not days.exists()


@pytest.mark.parametrize(
    ("digest", "reason", "downloaded"),
    [
        (None, "artefakt digest'i yok", False),
        (12, "artefakt digest'i yok", False),
        ("md5:abc", "artefakt digest'i yok", False),
        ("sha256:" + "0" * 64, "artefakt digest'i uyusmuyor", True),
    ],
    ids=["yok", "metin-degil", "baska-algoritma", "uyusmaz"],
)
def test_a_missing_or_wrong_digest_fails_the_collection(
    digest: Any,
    reason: str,
    downloaded: bool,
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1), digest=digest)
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 1
    assert reason in capsys.readouterr().out
    assert bool(blobs.requests) is downloaded
    assert not written(days)


@pytest.mark.parametrize(
    ("run_overrides", "summary_overrides", "reason"),
    [
        ({"head_sha": "f" * 40}, {}, "gun ozetinin kaynagi kosuyla uyusmuyor"),
        ({}, {"code_sha": "f" * 40}, "gun ozetinin kaynagi kosuyla uyusmuyor"),
        ({}, {"run_id": 12}, "gun ozetinin kaynagi kosuyla uyusmuyor"),
        ({}, {"run_attempt": 2}, "gun ozetinin kosu kimligi beklenen bicimde degil"),
        ({"head_sha": "F" * 40}, {}, "kosu kaydi beklenen bicimde degil"),
        ({"head_sha": None}, {}, "kosu kaydi beklenen bicimde degil"),
        ({"head_sha": "a" * 39}, {}, "kosu kaydi beklenen bicimde degil"),
    ],
    ids=["kosu-sha", "ozet-sha", "ozet-kosu", "ozet-deneme", "sha-buyuk", "sha-yok", "sha-kisa"],
)
def test_a_summary_whose_source_does_not_match_the_run_fails(
    run_overrides: dict[str, Any],
    summary_overrides: dict[str, Any],
    reason: str,
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Codex 6175607709 karsi ornegi: secilen kosuya `head_sha='f'*40` koymak
    indirmeyi engellemeliydi. Gun ozetinin run_id / run_attempt / code_sha
    alanlari API kosusuyla eslesmezse butun toplama durur."""
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z", **run_overrides)]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1, **summary_overrides))
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 1
    assert reason in capsys.readouterr().out
    assert not written(days)


# --------------------------------------------------------------------------
# Tek toplam: kampanya kaniti ve hic istek yapmadan reddedilen durumlar
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "clock", "planned", "reason"),
    [
        ({"ALPACA_PAPER_API_KEY": "x"}, AFTER, PLANNED, "toplam isi secret'siz calisir"),
        ({}, AFTER, (), "planli gun yok"),
        # UTC tarihi 7 Ocak, New York tarihi hala 6 Ocak (son planli gun).
        (
            {},
            SimClock(datetime(2026, 1, 7, 4, 59, tzinfo=UTC)),
            PLANNED,
            "son planli gun henuz bitmedi (New York tarihi)",
        ),
        ({"GITHUB_RUN_ATTEMPT": "2"}, AFTER, PLANNED, "yeniden deneme kosusu"),
        ({"GH_TOKEN": ""}, AFTER, PLANNED, "Actions API ortami eksik"),
    ],
    ids=["secret", "plan-bos", "erken-new-york", "yeniden-deneme", "ortam-eksik"],
)
def test_a_refused_collection_makes_no_request(
    environment: dict[str, str],
    clock: SimClock,
    planned: tuple[date, ...],
    reason: str,
    api: tuple[Api, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, api_url = api
    code, _ = collect(env(api_url, **environment), tmp_path, project_root, clock, planned)
    assert code == 1
    assert reason in capsys.readouterr().out
    assert state.requests == []


def test_the_first_new_york_day_after_the_campaign_may_collect(
    api: tuple[Api, str], tmp_path: Path, project_root: Path
) -> None:
    _, api_url = api
    clock = SimClock(datetime(2026, 1, 7, 5, 0, tzinfo=UTC))
    assert collect(env(api_url), tmp_path, project_root, clock)[0] == 0


def test_an_unreadable_configuration_makes_no_request(
    api: tuple[Api, str], tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, api_url = api
    (project_root / "config" / "universe.yaml").unlink()
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    assert "FAIL yapilandirma: kampanya kimligi" in capsys.readouterr().out
    assert state.requests == []


@pytest.mark.parametrize("expired", [False, True])
def test_an_existing_total_of_this_campaign_blocks_a_second_one(
    expired: bool,
    api: tuple[Api, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Teklik kaniti gercek cikti: suresi dolmus olsa da bu kampanyanin
    toplam artefakti varsa gozlem artefakti indirilmez, yeni toplam
    uretilmez."""
    state, api_url = api
    name = shadow_job.total_artifact(campaign(project_root, PLANNED))
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    state.repo_artifacts = [{"id": 5, "name": name, "expired": expired}]
    code, days = collect(env(api_url), tmp_path, project_root)
    assert code == 1
    assert "bu kampanyanin toplami daha once uretildi" in capsys.readouterr().out
    assert state.paths() == [TOTAL_RUNS_PATH, ARTIFACTS_PATH]
    assert not days.exists()


def test_another_campaign_total_does_not_block(
    api: tuple[Api, str], tmp_path: Path, project_root: Path
) -> None:
    state, api_url = api
    other = shadow_job.total_artifact(campaign(project_root, (D1,)))
    state.repo_artifacts = [{"id": 5, "name": other, "expired": False}]
    assert collect(env(api_url), tmp_path, project_root)[0] == 0


RAN = "onceki toplam adimi kostu (cikti yok ya da silinmis)"
UNCLEAR = "onceki toplam kosusu belirsiz"
RUNNING = "onceki toplam kosusu suruyor"
EVIDENCE_CASES: list[tuple[str, dict[str, Any], list[dict[str, Any]] | None, str | None]] = [
    # Codex 6175607709 karsi ornegi: hesaplama bitti, yukleme kirildi, artefakt yok.
    ("upload-hatasi", total_run(800), [total_job("success", "success", upload="failure")], RAN),
    # Toplam uretildi ve yuklendi, sonra artefakt silindi: adim kaniti kalir.
    (
        "silinmis-cikti",
        total_run(800, conclusion="success"),
        [total_job("success", "success", upload="success")],
        RAN,
    ),
    ("topla-hatasi", total_run(800), [total_job("success", "failure", upload="skipped")], RAN),
    # Bos, erken ya da reddedilmis kosu `Indir`de durur: cikti yok, engel yok.
    ("erken-ret", total_run(800), [total_job("failure", "skipped", upload="skipped")], None),
    (
        "bos-basarili",
        total_run(800, conclusion="success"),
        [total_job("skipped", "skipped", upload="skipped", conclusion="success")],
        None,
    ),
    (
        "is-atlandi",
        total_run(800, conclusion="success"),
        [total_job(None, None, conclusion="skipped", steps=[])],
        None,
    ),
    ("indirme-hatasi", total_run(800), [total_job("failure", "skipped", upload="skipped")], None),
    # Belirsiz: iptal ya da sonucsuz adimlar.
    (
        "indir-iptal",
        total_run(800, conclusion="cancelled"),
        [total_job("cancelled", "skipped", upload="skipped", conclusion="cancelled")],
        UNCLEAR,
    ),
    (
        "topla-iptal",
        total_run(800, conclusion="cancelled"),
        [total_job("success", "cancelled", upload="skipped", conclusion="cancelled")],
        UNCLEAR,
    ),
    (
        "indir-basarili-topla-yok",
        total_run(800),
        [total_job("success", "skipped", upload="skipped")],
        UNCLEAR,
    ),
    ("indir-sonucsuz", total_run(800), [total_job(None, "skipped", upload="skipped")], UNCLEAR),
    # Suruyor.
    ("kosu-suruyor", total_run(800, status="in_progress", conclusion=None), None, RUNNING),
    ("kosu-kuyrukta", total_run(800, status="queued", conclusion=None), None, RUNNING),
    ("kosu-durumsuz", {"id": 800}, None, RUNNING),
    (
        "is-suruyor",
        total_run(800),
        [total_job("success", None, status="in_progress", conclusion=None)],
        RUNNING,
    ),
    # Kanit okunamiyor: eksik gecmis basari ya da "hic baslamadi" kaniti degildir.
    ("is-yok", total_run(800), [], "onceki toplam kosusunun kaniti yok"),
    (
        "adimlar-yok",
        total_run(800),
        [{"name": shadow_job.TOTAL_JOB, "status": "completed", "conclusion": "failure"}],
        "onceki toplam kosusunun kaniti okunamadi",
    ),
    (
        "adimlar-metin",
        total_run(800),
        [total_job(None, None, steps="Indir")],
        "onceki toplam kosusunun kaniti okunamadi",
    ),
    (
        "adimlar-sozluk-degil",
        total_run(800),
        [total_job(None, None, steps=["Indir", "Topla"])],
        "onceki toplam kosusunun kaniti okunamadi",
    ),
    (
        "adim-eksik",
        total_run(800),
        [total_job(None, None, steps=[{"name": "Indir", "conclusion": "success"}])],
        "onceki toplam kosusunun kaniti okunamadi",
    ),
]


@pytest.mark.parametrize(
    ("prior", "jobs", "reason"),
    [case[1:] for case in EVIDENCE_CASES],
    ids=[case[0] for case in EVIDENCE_CASES],
)
def test_prior_total_runs_block_by_step_evidence(
    prior: dict[str, Any],
    jobs: list[dict[str, Any]] | None,
    reason: str | None,
    api: tuple[Api, str],
    host: tuple[Host, str],
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Onceki toplam kosusunun durumu yetmez; `total` isinin adimlari okunur
    (6172892558 kabul ornekleri). Engelde hicbir gozlem artefakti
    listelenmez ve indirilmez."""
    state, api_url = api
    blobs, host_url = host
    state.runs = [run(11, "2026-01-05T13:50:03Z")]
    serve(state, blobs, host_url, 11, day_zip(project_root, D1))
    state.totals = [prior]
    if jobs is not None:
        state.jobs["800"] = jobs
    code, days = collect(env(api_url), tmp_path, project_root)
    text = capsys.readouterr().out
    if reason is None:
        assert code == 0 and written(days) == ["11.json"]
        return
    assert code == 1
    assert f"FAIL toplam: {reason}" in text
    assert blobs.requests == [] and not days.exists()
    assert not [path for path in state.paths() if path.endswith("/artifacts")]
    if jobs is not None:
        assert f"/repos/{REPO}/actions/runs/800/jobs" in state.paths()


def test_later_total_runs_and_this_run_are_not_evidence(
    api: tuple[Api, str], tmp_path: Path, project_root: Path
) -> None:
    state, api_url = api
    state.totals = [total_run(950, status="in_progress", conclusion=None), total_run(900)]
    state.jobs["900"] = [total_job("success", "success", upload="failure")]
    assert collect(env(api_url), tmp_path, project_root)[0] == 0
    assert not [path for path in state.paths() if path.endswith("/jobs")]


def test_a_retry_is_authorised_only_by_the_code_constant(
    api: tuple[Api, str],
    tmp_path: Path,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Yeni dispatch izin degildir. `TOTAL_RETRY_AFTER` basarisiz kosunun
    kimligine cekilirse (ayri karar PR'i) o ve oncekiler kanit sayilmaz;
    sonrakiler sayilmaya devam eder."""
    state, api_url = api
    state.totals = [total_run(800), total_run(801)]
    state.jobs["800"] = [total_job("success", "success", upload="failure")]
    state.jobs["801"] = [total_job("success", "success", upload="failure")]
    assert shadow_job.TOTAL_RETRY_AFTER == 0
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    monkeypatch.setattr(shadow_job, "TOTAL_RETRY_AFTER", 800)
    assert collect(env(api_url), tmp_path / "ikinci", project_root)[0] == 1
    assert RAN in capsys.readouterr().out
    monkeypatch.setattr(shadow_job, "TOTAL_RETRY_AFTER", 801)
    assert collect(env(api_url), tmp_path / "ucuncu", project_root)[0] == 0


def test_an_unwritable_step_output_fails(
    api: tuple[Api, str], tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, api_url = api
    (tmp_path / "github-output").mkdir()
    assert collect(env(api_url), tmp_path, project_root)[0] == 1
    assert "adim ciktisi yazilamadi (IsADirectoryError)" in capsys.readouterr().out


def test_an_unreadable_history_fails_without_leaks(
    tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = collect(env("http://127.0.0.1:9"), tmp_path, project_root)
    assert code == 1
    text = capsys.readouterr().out
    assert "toplam kosu listesi okunamadi" in text
    assert TOKEN not in text


# --------------------------------------------------------------------------
# Gun ozeti sozlesmesi (tasarim §6): tur ve tutarlilik
# --------------------------------------------------------------------------


def parse(root: Path, payload: Any) -> shadow_job.ParsedDay:
    return shadow_job._parse_day(
        payload, campaign=campaign(root, PLANNED), symbols=symbols_of(root), planned=PLANNED
    )


def with_symbol(root: Path, index: int, **overrides: Any) -> list[dict[str, Any]]:
    items = [comparison(symbol) for symbol in symbols_of(root)]
    items[index] = {**items[index], **overrides}
    return items


INCOMPLETE = {"status": "eksik", "reason": "tur kacti (1/106)"}
CASES: list[tuple[str, dict[str, Any], str]] = [
    ("schema-99", {"day_schema": 99}, "gun ozeti semasi tanimsiz"),
    ("schema-bool", {"day_schema": True}, "gun ozeti semasi tanimsiz"),
    ("gun-bicimi", {"day": "20260105"}, "gun ozetinin gunu bicimsiz"),
    ("gun-sayi", {"day": 5}, "gun ozetinin gunu bicimsiz"),
    ("gun-plan-disi", {"day": "2026-01-08"}, "gun ozetinin gunu planda yok"),
    ("kampanya", {"campaign": "0" * 64}, "gun ozeti baska kampanyanin"),
    ("durum", {"status": "baslamadi"}, "gun durumu tanimsiz"),
    ("tamam-sebepli", {"reason": "x"}, "gun durumu ve sebebi tutarsiz"),
    ("eksik-sebepsiz", {"status": "eksik"}, "gun durumu ve sebebi tutarsiz"),
    ("eksik-bos-sebep", {"status": "eksik", "reason": ""}, "gun durumu ve sebebi tutarsiz"),
    ("surum", {"params_version": 5}, "strateji surumu beklenen bicimde degil"),
    ("saat-metin", {"clock_consistent": "evet"}, "saat denetimi beklenen bicimde degil"),
    ("saat-sayi", {"clock_consistent": 1}, "saat denetimi beklenen bicimde degil"),
    (
        "tur-toplami",
        {"turns": {"expected": 106, "called": 100, "failed": 0, "missed": 0}},
        "tur sayaclari tutarsiz",
    ),
    (
        "tur-bool",
        {"turns": {"expected": 1, "called": True, "failed": 0, "missed": 0}},
        "turns beklenen",
    ),
    (
        "tur-negatif",
        {"turns": {"expected": 0, "called": 1, "failed": -1, "missed": 0}},
        "turns beklenen",
    ),
    ("tur-anahtar", {"turns": {"expected": 106, "called": 106}}, "turns beklenen"),
    ("tur-liste", {"turns": [106, 106, 0, 0]}, "turns beklenen"),
    (
        "sembol-tur-fazla",  # project_root evreni 2 sembol: 106 x 2
        {"symbol_turns": {"expected": 212, "observed": 213}},
        "sembol-tur sayaclari tutarsiz",
    ),
    # Codex 6175607709: sifir ya da azaltilmis beklenen sayilar ve yanlis surum.
    (
        "tur-beklenen-sifir",
        {"turns": {"expected": 0, "called": 0, "failed": 0, "missed": 0}},
        "tur sayaclari stratejiyle uyusmuyor",
    ),
    (
        "tur-beklenen-az",
        {"turns": {"expected": 100, "called": 100, "failed": 0, "missed": 0}},
        "tur sayaclari stratejiyle uyusmuyor",
    ),
    (
        "sembol-tur-beklenen-sifir",
        {"symbol_turns": {"expected": 0, "observed": 0}},
        "sembol-tur sayaclari stratejiyle uyusmuyor",
    ),
    ("surum-baska", {"params_version": "orb-test"}, "strateji surumu kampanyayla uyusmuyor"),
    ("kosu-sifir", {"run_id": 0}, "gun ozetinin kosu kimligi beklenen bicimde degil"),
    ("kosu-bool", {"run_id": True}, "gun ozetinin kosu kimligi beklenen bicimde degil"),
    ("kosu-metin", {"run_id": "11"}, "gun ozetinin kosu kimligi beklenen bicimde degil"),
    ("deneme-2", {"run_attempt": 2}, "gun ozetinin kosu kimligi beklenen bicimde degil"),
    ("sha-kisa", {"code_sha": "a" * 39}, "gun ozetinin kod kimligi beklenen bicimde degil"),
    ("sha-buyuk", {"code_sha": "A" * 40}, "gun ozetinin kod kimligi beklenen bicimde degil"),
    ("sha-sayi", {"code_sha": 1}, "gun ozetinin kod kimligi beklenen bicimde degil"),
    (
        "sembol-tur-metin",
        {"symbol_turns": {"expected": "2", "observed": 2}},
        "symbol_turns beklenen",
    ),
    ("sip-sebep-sembol", {"sip_reasons": {"MSFT": "x"}}, "SIP sebepleri beklenen bicimde degil"),
    ("sip-sebep-deger", {"sip_reasons": {"SPY": 1}}, "SIP sebepleri beklenen bicimde degil"),
    ("sip-sebep-liste", {"sip_reasons": ["SPY"]}, "SIP sebepleri beklenen bicimde degil"),
    ("canli-saf-negatif", {"live_pure_mismatches": -1}, "canli-saf sayaci beklenen bicimde degil"),
    ("canli-saf-bool", {"live_pure_mismatches": False}, "canli-saf sayaci beklenen bicimde degil"),
    ("semboller-sozluk", {"symbols": {}}, "sembol sonuclari beklenen bicimde degil"),
    ("fazla-alan", {"price": 100.5}, "gun ozetinin alanlari beklenen kumede degil"),
]


@pytest.mark.parametrize(
    ("overrides", "reason"), [case[1:] for case in CASES], ids=[case[0] for case in CASES]
)
def test_a_summary_field_that_breaks_the_contract_is_refused(
    overrides: dict[str, Any], reason: str, project_root: Path
) -> None:
    payload = day_payload(project_root, PLANNED, D1, **overrides)
    with pytest.raises(shadow_job.DaySummaryError, match=reason):
        parse(project_root, payload)


@pytest.mark.parametrize("missing", sorted(shadow_job.DAY_HEAD))
def test_a_summary_without_a_head_field_is_refused(missing: str, project_root: Path) -> None:
    payload = day_payload(project_root, PLANNED, D1)
    del payload[missing]
    with pytest.raises(shadow_job.DaySummaryError, match="alanlari beklenen kumede degil"):
        parse(project_root, payload)


@pytest.mark.parametrize("payload", [[], "tamam", None, 1])
def test_a_summary_that_is_not_an_object_is_refused(payload: Any, project_root: Path) -> None:
    with pytest.raises(shadow_job.DaySummaryError, match="gun ozeti beklenen bicimde degil"):
        parse(project_root, payload)


SYMBOL_CASES: list[tuple[str, int, dict[str, Any], str]] = [
    ("sayi-metin", 0, {"window_expected": "15"}, "turleri beklenen gibi degil"),
    ("bool-sayi", 0, {"iex_completed_later": 0}, "turleri beklenen gibi degil"),
    ("sayi-bool", 0, {"iex_present": True}, "turleri beklenen gibi degil"),
    ("ondalik-bool", 0, {"or_high_bps": True}, "turleri beklenen gibi degil"),
    ("ondalik-nan", 0, {"or_low_bps": float("nan")}, "turleri beklenen gibi degil"),
    ("ondalik-sonsuz", 0, {"iex_first_minute": float("inf")}, "turleri beklenen gibi degil"),
    ("ondalik-sayiya", 0, {"window_expected": 15.0}, "turleri beklenen gibi degil"),
    ("sip-sayi", 1, {"sip_available": 1}, "turleri beklenen gibi degil"),
    ("sembol-yok", 0, {"symbol": None}, "turleri beklenen gibi degil"),
    ("evren-disi", 1, {"symbol": "MSFT"}, "sembol kampanya evreninde yok"),
    ("aralik-durumu", 0, {"range_status": "tamam"}, "sembol sonucunun durumu tanimsiz"),
    ("sinyal", 0, {"signal": "buy"}, "sembol sonucunun durumu tanimsiz"),
    ("negatif-pencere", 0, {"window_expected": -1}, "sembol sonucunda negatif sayac"),
    ("negatif-iex", 0, {"iex_present": -1}, "sembol sonucunda negatif sayac"),
    ("negatif-sip", 1, {"sip_present": -1}, "sembol sonucunda negatif sayac"),
    ("negatif-tur", 1, {"iex_unknown_turns": -2}, "sembol sonucunda negatif sayac"),
    ("fazla-alan", 0, {"close": 100.5}, "sembol sonucunun alanlari beklenen kumede degil"),
    # compare_symbol_day'in uretemeyecegi birlesimler (Codex 6175607709).
    ("pencere-16", 0, {"window_expected": 16}, "pencere sayaclari stratejiyle uyusmuyor"),
    ("iex-16", 0, {"iex_present": 16}, "pencere sayaclari stratejiyle uyusmuyor"),
    ("sip-16", 1, {"sip_present": 16}, "pencere sayaclari stratejiyle uyusmuyor"),
    ("sip-iexsiz", 0, {"iex_present": None}, "SIP penceresi IEX penceresi olmadan sayilmaz"),
    (
        "gecikmeli-tam",
        0,
        {"iex_completed_later": True},
        "gecikmeli tamlik eksik pencere gerektirir",
    ),
    (
        "gecikmeli-bilinmeyen",
        0,
        {"iex_completed_later": True, "iex_present": None, "sip_present": None},
        "gecikmeli tamlik eksik pencere gerektirir",
    ),
    (
        "bilinmeyen-tur-107",
        1,
        {"iex_unknown_turns": 107},
        "bilinmeyen tur sayisi planli turlari asiyor",
    ),
    ("bps-hesaplanmadan", 0, {"range_status": "sip_eksik"}, "aralik durumu ve farklari tutarsiz"),
    ("hesaplandi-bpssiz", 0, {"or_high_bps": None}, "aralik durumu ve farklari tutarsiz"),
    (
        "dakika-14",
        0,
        {"iex_first_minute": 14.0, "signal": "mismatch"},
        "ilk niyet dakikasi planli pencerenin disinda",
    ),
    (
        "dakika-121",
        1,
        {"sip_first_minute": 121, "signal": "mismatch"},
        "ilk niyet dakikasi planli pencerenin disinda",
    ),
    (
        "match-tek-taraf",
        0,
        {"signal": "match", "iex_first_minute": 40.1167},
        "sinyal ve ilk niyet dakikalari tutarsiz",
    ),
    (
        "none-dakikali",
        0,
        {"signal": "none", "sip_first_minute": 40.1167},
        "sinyal ve ilk niyet dakikalari tutarsiz",
    ),
    ("mismatch-dakikasiz", 1, {"signal": "mismatch"}, "sinyal ve ilk niyet dakikalari tutarsiz"),
]

NO_SIP_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("sip-penceresi", {"sip_present": 15}, "SIP'siz sembolde SIP'e dayanan alan var"),
    ("sip-dakikasi", {"sip_first_minute": 40.1167}, "SIP'siz sembolde SIP'e dayanan alan var"),
    ("sinyal-none", {"signal": "none"}, "SIP'siz sembolde SIP'e dayanan alan var"),
    ("aralik-sip-eksik", {"range_status": "sip_eksik"}, "SIP'siz sembolde SIP'e dayanan alan var"),
    (
        "aralik-hesaplandi",
        {"range_status": "hesaplandi", "or_high_bps": 1.0, "or_low_bps": 1.0},
        "SIP'siz sembolde SIP'e dayanan alan var",
    ),
]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [case[1:] for case in NO_SIP_CASES],
    ids=[case[0] for case in NO_SIP_CASES],
)
def test_a_symbol_without_sip_cannot_carry_sip_based_fields(
    overrides: dict[str, Any], reason: str, project_root: Path
) -> None:
    first, second = symbols_of(project_root)
    symbols = [no_sip(first, **overrides), comparison(second)]
    payload = day_payload(
        project_root,
        PLANNED,
        D1,
        **INCOMPLETE,
        sip_reasons={first: "son sure doldu"},
        symbols=symbols,
    )
    with pytest.raises(shadow_job.DaySummaryError, match=reason):
        parse(project_root, payload)


def test_sip_reasons_must_name_exactly_the_symbols_without_sip(project_root: Path) -> None:
    first, second = symbols_of(project_root)
    symbols = [no_sip(first), comparison(second)]
    with pytest.raises(shadow_job.DaySummaryError, match="SIP sebepleri SIP'siz sembollerle"):
        parse(project_root, day_payload(project_root, PLANNED, D1, **INCOMPLETE, symbols=symbols))
    with pytest.raises(shadow_job.DaySummaryError, match="SIP sebepleri SIP'siz sembollerle"):
        parse(
            project_root,
            day_payload(
                project_root, PLANNED, D1, **INCOMPLETE, sip_reasons={second: "son sure doldu"}
            ),
        )
    parsed = parse(
        project_root,
        day_payload(
            project_root,
            PLANNED,
            D1,
            **INCOMPLETE,
            sip_reasons={first: "son sure doldu"},
            symbols=symbols,
        ),
    )
    assert [sip for _, sip in parsed.symbols] == [False, True]


def test_codex_counterexample_zero_expected_complete_day_is_refused(project_root: Path) -> None:
    """6175607709: turns ve symbol_turns sifir, diger alanlar normal, surum
    `orb-test` iken `tamam` kabul ediliyordu."""
    payload = day_payload(
        project_root,
        PLANNED,
        D1,
        turns={"expected": 0, "called": 0, "failed": 0, "missed": 0},
        symbol_turns={"expected": 0, "observed": 0},
        params_version="orb-test",
    )
    with pytest.raises(
        shadow_job.DaySummaryError, match=r"^strateji surumu kampanyayla uyusmuyor$"
    ):
        parse(project_root, payload)
    payload["params_version"] = PARAMS_VERSION
    with pytest.raises(shadow_job.DaySummaryError, match=r"^tur sayaclari stratejiyle uyusmuyor$"):
        parse(project_root, payload)
    payload["turns"] = {"expected": TURNS, "called": TURNS, "failed": 0, "missed": 0}
    with pytest.raises(
        shadow_job.DaySummaryError, match=r"^sembol-tur sayaclari stratejiyle uyusmuyor$"
    ):
        parse(project_root, payload)


@pytest.mark.parametrize(
    ("index", "overrides", "reason"),
    [case[1:] for case in SYMBOL_CASES],
    ids=[case[0] for case in SYMBOL_CASES],
)
def test_a_symbol_result_that_breaks_the_contract_is_refused(
    index: int, overrides: dict[str, Any], reason: str, project_root: Path
) -> None:
    payload = day_payload(
        project_root,
        PLANNED,
        D1,
        **INCOMPLETE,
        symbols=with_symbol(project_root, index, **overrides),
    )
    with pytest.raises(shadow_job.DaySummaryError, match=reason):
        parse(project_root, json.loads(json.dumps(payload)))


def test_a_symbol_result_without_a_field_or_as_a_list_is_refused(project_root: Path) -> None:
    items = with_symbol(project_root, 0)
    del items[0]["sip_available"]
    for symbols in (items, [["SPY"]]):
        payload = day_payload(project_root, PLANNED, D1, **INCOMPLETE, symbols=symbols)
        with pytest.raises(shadow_job.DaySummaryError, match="alanlari beklenen kumede degil"):
            parse(project_root, payload)


def test_a_symbol_reported_twice_is_refused(project_root: Path) -> None:
    first = comparison(symbols_of(project_root)[0])
    payload = day_payload(project_root, PLANNED, D1, **INCOMPLETE, symbols=[first, first])
    with pytest.raises(shadow_job.DaySummaryError, match="bir sembol iki kez raporlandi"):
        parse(project_root, payload)


def complete_breaks(root: Path) -> list[tuple[str, dict[str, Any]]]:
    n = len(symbols_of(root))
    first, second = symbols_of(root)
    return [
        (
            "hatali-tur",
            {"turns": {"expected": TURNS, "called": TURNS - 1, "failed": 1, "missed": 0}},
        ),
        (
            "kacan-tur",
            {"turns": {"expected": TURNS, "called": TURNS - 1, "failed": 0, "missed": 1}},
        ),
        ("eksik-gozlem", {"symbol_turns": {"expected": TURNS * n, "observed": TURNS * n - 1}}),
        ("canli-saf", {"live_pure_mismatches": 1}),
        (
            "sip-sebebi",
            {
                "sip_reasons": {first: "yanit eksik (1 dakika)"},
                "symbols": [no_sip(first), comparison(second)],
            },
        ),
        ("eksik-sembol", {"symbols": [comparison(first)]}),
        (
            "sipsiz-sembol",
            {
                "sip_reasons": {second: "son sure doldu"},
                "symbols": [comparison(first), no_sip(second)],
            },
        ),
    ]


@pytest.mark.parametrize("case", range(7))
def test_a_complete_day_must_agree_with_its_counters(case: int, project_root: Path) -> None:
    """`tamam` ancak hicbir sebep yokken: sayaclarla celisen tam gun reddedilir;
    ayni govde `eksik` olarak kabul edilir (sebep sayaclari tasir)."""
    name, overrides = complete_breaks(project_root)[case]
    payload = day_payload(project_root, PLANNED, D1, **overrides)
    with pytest.raises(shadow_job.DaySummaryError, match="tamamlanan gun sayaclarla tutarsiz"):
        parse(project_root, payload)
    parsed = parse(project_root, {**payload, **INCOMPLETE})
    assert (parsed.day, parsed.status) == (D1, "eksik"), name


@pytest.mark.parametrize("missing", sorted(shadow_job.DAY_BODY))
def test_a_complete_day_needs_the_whole_body(missing: str, project_root: Path) -> None:
    payload = day_payload(project_root, PLANNED, D1)
    del payload[missing]
    with pytest.raises(shadow_job.DaySummaryError, match="tamamlanan gun sayaclarla tutarsiz"):
        parse(project_root, payload)


def test_valid_summaries_are_parsed_with_their_results(project_root: Path) -> None:
    complete = parse(project_root, day_payload(project_root, PLANNED, D1))
    assert (complete.day, complete.status, complete.reason) == (D1, "tamam", None)
    assert [result.symbol for result, _ in complete.symbols] == list(symbols_of(project_root))
    assert all(sip for _, sip in complete.symbols)
    late = parse(project_root, day_payload(project_root, PLANNED, D2, "eksik", "gec baslangic"))
    assert (late.day, late.status, late.reason, late.symbols) == (
        D2,
        "eksik",
        "gec baslangic",
        [],
    )
    unknown = with_symbol(
        project_root,
        0,
        iex_present=None,
        sip_present=None,
        or_high_bps=None,
        or_low_bps=None,
        range_status="bilinmiyor",
        signal="unknown",
        iex_first_minute=40,  # tamsayi, ondalik alana girer
        sip_available=False,
    )
    partial = parse(
        project_root,
        day_payload(
            project_root,
            PLANNED,
            D1,
            **INCOMPLETE,
            clock_consistent=None,
            sip_reasons={symbols_of(project_root)[0]: "son sure doldu"},
            symbols=unknown,
        ),
    )
    assert partial.symbols[0][0].iex_first_minute == 40
    assert (partial.run_id, partial.run_attempt, partial.code_sha) == (11, 1, CODE_SHA)


def test_the_aggregate_refuses_a_summary_that_breaks_the_contract(
    tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    days = tmp_path / "days"
    days.mkdir()
    write_day(days, day_payload(project_root, PLANNED, D1, campaign="0" * 64))
    out = tmp_path / "total.json"
    code = shadow_job.aggregate({}, days_dir=days, out=out, root=project_root, planned=PLANNED)
    assert code == 1
    assert "FAIL toplam: gun ozeti baska kampanyanin" in capsys.readouterr().out
    assert not out.exists()


def test_the_aggregate_refuses_an_unreadable_summary(
    tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    days = tmp_path / "days"
    days.mkdir()
    (days / "derin.json").write_text("[" * 100_000, encoding="utf-8")
    out = tmp_path / "total.json"
    code = shadow_job.aggregate({}, days_dir=days, out=out, root=project_root, planned=PLANNED)
    assert code == 1
    assert "gunluk ozetler okunamadi (RecursionError)" in capsys.readouterr().out
    assert not out.exists()
