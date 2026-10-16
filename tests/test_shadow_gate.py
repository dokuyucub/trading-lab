"""Golge gozlem kapi isi: kosu gecmisi ve teklik (tasarim §5).

Yerel bir sahte GitHub API sunucusu kosu ve is listelerini verir; kapi
istekleri ve basliklari kaydedilir. Gosterilenler:

  * plan disi gunde API'ye hic gidilmez;
  * ayni gun kayit isi atlanmamis baska kosu varsa kapi kapali; bos
    gecen kosu, baska gunun kosusu ve kosunun kendisi sayilmaz;
  * yeniden deneme kosusu hic kosmaz;
  * API hatasi ve yonlendirme kapiyi KAPALI birakir; yonlendirme
    izlenmez, token baska host'a gitmez ve basilmaz;
  * kapi secret'li ortamda baslamaz.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from shadow_days import day_payload, write_day
from tlab import shadow_job
from tlab.core.clock import SimClock
from tlab.shadow.schedule import GATE_LATE, GATE_OBSERVE, GATE_SKIP

DAY = date(2026, 1, 5)
IN_WINDOW = datetime(2026, 1, 5, 13, 50, tzinfo=UTC)
LATE = datetime(2026, 1, 5, 14, 50, tzinfo=UTC)
PLANNED = (DAY,)
TOKEN = "GATE-CANARY-TOKEN"  # noqa: S105 - ciktida ARANAN sahte isaret
REPO = "owner/repo"
RUNS_PATH = f"/repos/{REPO}/actions/workflows/{shadow_job.WORKFLOW_FILE}/runs"


@dataclass
class Api:
    runs: list[dict[str, Any]] = field(default_factory=list)
    jobs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    status: int = 200
    redirect_to: str | None = None
    runs_total: int | None = None
    jobs_total: int | None = None
    requests: list[tuple[str, str | None]] = field(default_factory=list)


def _serve(api: Api) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            api.requests.append((self.path, self.headers.get("Authorization")))
            path = urlparse(self.path).path
            if api.redirect_to is not None:
                self.send_response(302)
                self.send_header("Location", api.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if api.status != 200:
                payload: Any = {"message": f"govde {TOKEN}"}
                status = api.status
            elif path == RUNS_PATH:
                total = len(api.runs) if api.runs_total is None else api.runs_total
                payload, status = {"total_count": total, "workflow_runs": api.runs}, 200
            elif path.startswith(f"/repos/{REPO}/actions/runs/") and path.endswith("/jobs"):
                jobs = api.jobs.get(path.split("/")[-2], [])
                total = len(jobs) if api.jobs_total is None else api.jobs_total
                payload, status = {"total_count": total, "jobs": jobs}, 200
            else:
                payload, status = {"message": "yok"}, 404
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args: Any) -> None:
            """Sessiz."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def api() -> Api:
    return Api()


@pytest.fixture
def api_url(api: Api) -> Iterator[str]:
    yield from _serve(api)


def env(api_url: str, **extra: str) -> dict[str, str]:
    return {
        "GITHUB_API_URL": api_url,
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_RUN_ID": "100",
        "GH_TOKEN": TOKEN,
        **extra,
    }


def run(
    environment: dict[str, str], tmp_path: Path, now: datetime, planned: tuple[date, ...] = PLANNED
) -> tuple[int, dict[str, str]]:
    output = tmp_path / "github_output"
    code = shadow_job.gate(environment, clock=SimClock(now), output=output, planned=planned)
    lines = output.read_text(encoding="utf-8").splitlines() if output.exists() else []
    return code, dict(line.split("=", 1) for line in lines)


def run_record(run_id: int, created: str) -> dict[str, Any]:
    return {"id": run_id, "created_at": created}


def record_job(
    status: str = "completed",
    conclusion: str | None = "success",
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    job: dict[str, Any] = {
        "name": shadow_job.RECORD_JOB,
        "status": status,
        "conclusion": conclusion,
    }
    if steps is not None:
        job["steps"] = steps
    return job


def step(name: str, conclusion: str | None) -> dict[str, Any]:
    status = "completed" if conclusion is not None else "in_progress"
    return {"name": name, "status": status, "conclusion": conclusion}


# --------------------------------------------------------------------------
# Kararlar
# --------------------------------------------------------------------------


def test_an_unplanned_day_never_calls_the_api(api: Api, api_url: str, tmp_path: Path) -> None:
    code, out = run(env(api_url), tmp_path, IN_WINDOW, planned=())
    assert (code, out["action"]) == (0, GATE_SKIP)
    assert api.requests == []


def test_a_clean_day_in_the_window_observes(api: Api, api_url: str, tmp_path: Path) -> None:
    code, out = run(env(api_url), tmp_path, IN_WINDOW)
    assert (code, out) == (0, {"action": GATE_OBSERVE, "day": DAY.isoformat()})
    assert [urlparse(path).path for path, _ in api.requests] == [RUNS_PATH]


def test_a_recorded_run_the_same_day_closes_the_gate(
    api: Api, api_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.runs = [run_record(90, "2026-01-05T12:50:03Z")]
    api.jobs = {
        "90": [{"name": "gate", "status": "completed", "conclusion": "success"}, record_job()]
    }
    code, out = run(env(api_url), tmp_path, LATE)
    assert (code, out["action"]) == (0, GATE_SKIP)
    assert "gun zaten kaydedildi" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("jobs", "expected"),
    [
        ([record_job("completed", "skipped")], GATE_LATE),
        ([record_job("completed", "success")], GATE_SKIP),
        ([record_job("completed", "failure")], GATE_SKIP),
        ([record_job("completed", "cancelled")], GATE_SKIP),
        ([record_job("queued", None)], GATE_SKIP),
        ([record_job("in_progress", None)], GATE_SKIP),
        ([record_job("waiting", None)], GATE_SKIP),
        ([{"name": "gate", "status": "completed", "conclusion": "success"}], GATE_SKIP),
        ([], GATE_SKIP),
        ([record_job("completed", "skipped"), record_job("completed", "success")], GATE_SKIP),
    ],
    ids=[
        "skipped-does-not-count",
        "success-counts",
        "failure-counts",
        "cancelled-counts",
        "queued-counts",
        "running-counts",
        "waiting-counts",
        "no-record-job-counts",
        "no-jobs-counts",
        "any-attempt-not-skipped-counts",
    ],
)
def test_the_uniqueness_state_table(
    api: Api, api_url: str, tmp_path: Path, jobs: list[dict[str, Any]], expected: str
) -> None:
    """Tasarim §5 durum tablosu: yalnizca butun denemelerde atlanmis kayit
    isi sayilmaz; bilinmeyen her durum kapiyi kapali tutar."""
    api.runs = [run_record(90, "2026-01-05T12:50:03Z")]
    api.jobs = {"90": jobs}
    _, out = run(env(api_url), tmp_path, LATE)
    assert out["action"] == expected


def test_a_later_run_does_not_count(api: Api, api_url: str, tmp_path: Path) -> None:
    """Sonraki kosu bu kosu bitmeden baslayamaz (eszamanlilik grubu)."""
    api.runs = [run_record(110, "2026-01-05T13:50:03Z")]
    api.jobs = {"110": [record_job("in_progress", None)]}
    _, out = run(env(api_url), tmp_path, IN_WINDOW)
    assert out["action"] == GATE_OBSERVE
    assert [urlparse(path).path for path, _ in api.requests] == [RUNS_PATH]


@pytest.mark.parametrize("which", ["runs", "jobs"])
def test_more_than_one_page_keeps_the_gate_closed(
    which: str, api: Api, api_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.runs = [run_record(90, "2026-01-05T12:50:03Z")]
    api.jobs = {"90": [record_job("completed", "skipped")]}
    if which == "runs":
        api.runs_total = 101
    else:
        api.jobs_total = 101
    code, out = run(env(api_url), tmp_path, LATE)
    assert (code, out["action"]) == (1, GATE_SKIP)
    assert "tek sayfayi asti" in capsys.readouterr().out


def test_other_days_and_this_run_are_ignored(api: Api, api_url: str, tmp_path: Path) -> None:
    api.runs = [run_record(80, "2026-01-02T13:50:03Z"), run_record(100, "2026-01-05T13:50:03Z")]
    api.jobs = {"80": [record_job()], "100": [record_job()]}
    _, out = run(env(api_url), tmp_path, IN_WINDOW)
    assert out["action"] == GATE_OBSERVE
    assert [urlparse(path).path for path, _ in api.requests] == [RUNS_PATH]


def test_a_rerun_never_runs(api: Api, api_url: str, tmp_path: Path) -> None:
    code, out = run(env(api_url, GITHUB_RUN_ATTEMPT="2"), tmp_path, IN_WINDOW)
    assert (code, out["action"]) == (0, GATE_SKIP)
    assert api.requests == []


@pytest.mark.parametrize(
    ("event", "conclusion", "expected"),
    [
        ("schedule", "success", GATE_SKIP),
        ("workflow_dispatch", "success", GATE_SKIP),
        ("workflow_dispatch", "failure", GATE_SKIP),
        ("workflow_dispatch", "skipped", GATE_OBSERVE),
    ],
    ids=["cron-kaydetti", "dispatch-kaydetti", "dispatch-basarisiz", "dispatch-bos-gecti"],
)
def test_the_trigger_kind_does_not_change_uniqueness(
    event: str, conclusion: str, expected: str, api: Api, api_url: str, tmp_path: Path
) -> None:
    """Cron ya da dis baslatici (Codex 6197450956): kapi tetik turune
    bakmaz. Kayit yazmis onceki kosu gunu kapatir, bos gecen kosu
    kapatmaz; kosu kaydi gercek Actions kaydinin seklinde (ek alanlar
    yok sayilir)."""
    api.runs = [
        {
            "id": 90,
            "event": event,
            "head_branch": "main",
            "path": f".github/workflows/{shadow_job.WORKFLOW_FILE}",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-01-05T12:50:03Z",
            "run_started_at": "2026-01-05T12:50:03Z",
            "head_sha": "55eb8659c30c89016bf77de46e45b70a3c979d9b",
            "display_title": "Shadow observation",
        }
    ]
    api.jobs = {"90": [record_job("completed", conclusion)]}
    _, out = run(env(api_url), tmp_path, IN_WINDOW)
    assert out["action"] == expected


# --------------------------------------------------------------------------
# Hata yollari ve token
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_an_api_error_keeps_the_gate_closed_without_leaks(
    api: Api, api_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], status: int
) -> None:
    api.status = status
    code, out = run(env(api_url), tmp_path, IN_WINDOW)
    assert (code, out["action"]) == (1, GATE_SKIP)
    text = capsys.readouterr().out
    assert f"HTTP {status}" in text
    assert TOKEN not in text
    assert "govde" not in text


def test_a_redirect_is_not_followed_and_the_token_stays_home(
    api: Api, api_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = Api()
    for other_url in _serve(elsewhere):
        api.redirect_to = f"{other_url}/collect"
        code, out = run(env(api_url), tmp_path, IN_WINDOW)
        assert (code, out["action"]) == (1, GATE_SKIP)
        assert elsewhere.requests == [], "yonlendirme izlenmemeli"
    text = capsys.readouterr().out
    assert "HTTP 302" in text
    assert "collect" not in text


def test_the_token_goes_only_to_the_api(api: Api, api_url: str, tmp_path: Path) -> None:
    api.runs = [run_record(90, "2026-01-05T12:50:03Z")]
    api.jobs = {"90": [record_job("completed", "skipped")]}
    run(env(api_url), tmp_path, IN_WINDOW)
    assert api.requests
    assert {auth for _, auth in api.requests} == {f"Bearer {TOKEN}"}


@pytest.mark.parametrize("url", ["http://api.example.com", "ftp://127.0.0.1"])
def test_a_non_https_api_url_is_refused(
    url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(env(url), tmp_path, IN_WINDOW)
    assert (code, out["action"]) == (1, GATE_SKIP)
    assert "beklenmeyen API adres semasi" in capsys.readouterr().out


def test_missing_configuration_keeps_the_gate_closed(tmp_path: Path) -> None:
    code, out = run({}, tmp_path, IN_WINDOW)
    assert (code, out["action"]) == (1, GATE_SKIP)


def test_the_gate_refuses_a_secret_environment(api: Api, api_url: str, tmp_path: Path) -> None:
    code, out = run(env(api_url, ALPACA_PAPER_API_KEY="x"), tmp_path, IN_WINDOW)
    assert (code, out["action"]) == (1, GATE_SKIP)
    assert api.requests == []


def test_a_malformed_api_answer_keeps_the_gate_closed(
    api: Api, api_url: str, tmp_path: Path
) -> None:
    api.runs = [{"id": 90}]
    code, out = run(env(api_url), tmp_path, IN_WINDOW)
    assert (code, out["action"]) == (1, GATE_SKIP)


# --------------------------------------------------------------------------
# Toplam: ozet yoklugu kanit degildir (Codex 6155755867)
# --------------------------------------------------------------------------

D1, D2, D3, D4 = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))


def day_summary(
    directory: Path,
    root: Path,
    planned: tuple[date, ...],
    day: date,
    status: str,
    reason: str | None,
) -> None:
    write_day(directory, day_payload(root, planned, day, status, reason))


def aggregate_env(api_url: str) -> dict[str, str]:
    return {"GITHUB_API_URL": api_url, "GITHUB_REPOSITORY": REPO, "GH_TOKEN": TOKEN}


def total_days(out: Path) -> dict[str, tuple[str, str | None]]:
    summary = json.loads(out.read_text(encoding="utf-8"))
    return {item["day"]: (item["status"], item["reason"]) for item in summary["day_list"]}


def test_missing_summaries_are_classified_by_run_evidence(
    api: Api, api_url: str, tmp_path: Path, project_root: Path
) -> None:
    days = tmp_path / "days"
    days.mkdir()
    d5, d6 = date(2026, 1, 9), date(2026, 1, 12)
    planned = (D1, D2, D3, D4, d5, d6)
    day_summary(days, project_root, planned, D1, "tamam", None)
    api.runs = [
        run_record(11, "2026-01-06T12:50:03Z"),
        run_record(12, "2026-01-07T12:50:03Z"),
        run_record(13, "2026-01-07T13:50:03Z"),
        run_record(14, "2026-01-08T12:50:03Z"),
        run_record(15, "2026-01-09T12:50:03Z"),
        run_record(16, "2026-01-12T12:50:03Z"),
    ]
    api.jobs = {
        # D2: gozlem adimi kostu, ozet yok (runner kaybi, zaman asimi, yukleme hatasi).
        "11": [record_job("completed", "failure", [step("Gozle", "failure")])],
        # D3: iki kosu da bos gecti: gozlem baslamadigi kanitli.
        "12": [record_job("completed", "skipped")],
        "13": [record_job("completed", "skipped")],
        # D4: kayit isi listede yok: kanit yetersiz.
        "14": [{"name": "gate", "status": "completed", "conclusion": "success"}],
        # D5: kayit isi atlanmamis ama hicbir kayit adimi kosmamis (kurulumda dustu).
        "15": [
            record_job("completed", "failure", [step("Kur", "failure"), step("Gozle", "skipped")])
        ],
        # D6: kayit isi hala suruyor: ozet gelebilir, karar verilmez.
        "16": [record_job("in_progress", None, [step("Gozle", None)])],
    }
    out = tmp_path / "total.json"
    code = shadow_job.aggregate(
        aggregate_env(api_url),
        days_dir=days,
        out=out,
        root=project_root,
        planned=planned,
    )
    assert code == 0
    assert total_days(out) == {
        D1.isoformat(): ("tamam", None),
        D2.isoformat(): ("eksik", "kayit adimi kostu, ozet yok"),
        D3.isoformat(): ("baslamadi", "gozlem baslamadi"),
        D4.isoformat(): ("bilinmiyor", "kanit yetersiz"),
        d5.isoformat(): ("eksik", "kosu var, ozet yok"),
        d6.isoformat(): ("bilinmiyor", "kanit yetersiz"),
    }
    assert all("basladi, ozet" not in reason for _, reason in total_days(out).values() if reason)


ADIM, KAYITLI, YOK, BELIRSIZ = (
    shadow_job.EVIDENCE_STEP,
    shadow_job.EVIDENCE_RECORDED,
    shadow_job.EVIDENCE_NONE,
    shadow_job.EVIDENCE_UNCLEAR,
)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ([], BELIRSIZ),
        ([record_job("completed", "skipped")], YOK),
        ([record_job("completed", "skipped", [step("Gozle", "skipped")])], YOK),
        # Is atlanmamis; adim kaniti yok: gun rezerve, "basladi" denmez.
        ([record_job("completed", "failure")], KAYITLI),
        ([record_job("completed", "cancelled")], KAYITLI),
        ([{**record_job("completed", "success"), "steps": "Gozle"}], KAYITLI),
        ([{**record_job("completed", "success"), "steps": ["Gozle"]}], KAYITLI),
        ([record_job("completed", "failure", [step("Kur", "success")])], KAYITLI),
        ([record_job("completed", "cancelled", [step("Gozle", "skipped")])], KAYITLI),
        # Iptal hic baslamamis adimi da isaretleyebilir: kosma kaniti sayilmaz.
        ([record_job("completed", "cancelled", [step("Gozle", "cancelled")])], KAYITLI),
        ([record_job("completed", "failure", [step("Gozle", None)])], KAYITLI),
        # Adim gercekten kostu.
        ([record_job("completed", "success", [step("Gozle", "success")])], ADIM),
        ([record_job("completed", "failure", [step("Gozle", "failure")])], ADIM),
        ([record_job("completed", "success", [step("Gec kaydi yaz", "success")])], ADIM),
        ([record_job("in_progress", None, [step("Gozle", "success")])], ADIM),
        # Is suruyor ve adim kaniti yok: belirsiz.
        ([record_job("queued", None)], BELIRSIZ),
        ([record_job("in_progress", None, [step("Gozle", None)])], BELIRSIZ),
        ([record_job("waiting", None, [step("Gozle", "skipped")])], BELIRSIZ),
    ],
)
def test_run_evidence_needs_a_real_step_to_say_the_record_step_ran(
    record: list[dict[str, Any]], expected: str
) -> None:
    assert shadow_job._run_evidence(record) == expected


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (record_job("completed", "skipped"), record_job("completed", "failure"), "kosu var"),
        (
            record_job("queued", None),
            record_job("completed", "failure", [step("Gozle", "failure")]),
            "kayit adimi",
        ),
        (record_job("completed", "skipped"), record_job("queued", None), "kanit yetersiz"),
    ],
)
@pytest.mark.parametrize("order", ["forward", "reverse"])
def test_the_strongest_evidence_of_a_day_wins_in_any_order(
    first: dict[str, Any],
    second: dict[str, Any],
    expected: str,
    order: str,
    api: Api,
    api_url: str,
    tmp_path: Path,
    project_root: Path,
) -> None:
    days = tmp_path / "days"
    days.mkdir()
    api.runs = [run_record(21, "2026-01-05T12:50:03Z"), run_record(22, "2026-01-05T13:50:03Z")]
    pair = [first, second] if order == "forward" else [second, first]
    api.jobs = {"21": [pair[0]], "22": [pair[1]]}
    out = tmp_path / "total.json"
    shadow_job.aggregate(
        aggregate_env(api_url), days_dir=days, out=out, root=project_root, planned=(D1,)
    )
    _, reason = total_days(out)[D1.isoformat()]
    assert reason is not None
    assert reason.startswith(expected)


def test_a_day_with_no_runs_at_all_is_unknown_not_not_started(
    api: Api, api_url: str, tmp_path: Path, project_root: Path
) -> None:
    """Silinmis kosu ile hic tetiklenmemis cron okunarak ayrilamaz
    (Codex 6171961412): kosu kaydi olmayan gun `baslamadi` DEGIL."""
    days = tmp_path / "days"
    days.mkdir()
    api.runs = [run_record(21, "2026-01-06T12:50:03Z")]
    api.jobs = {"21": [record_job("completed", "skipped")]}
    out = tmp_path / "total.json"
    shadow_job.aggregate(
        aggregate_env(api_url), days_dir=days, out=out, root=project_root, planned=(D1, D2)
    )
    assert total_days(out) == {
        D1.isoformat(): ("bilinmiyor", "kosu kaydi yok"),
        D2.isoformat(): ("baslamadi", "gozlem baslamadi"),
    }


@pytest.mark.parametrize("failure", ["status", "page", "env"])
def test_unreadable_history_makes_missing_days_unknown_not_not_started(
    failure: str,
    api: Api,
    api_url: str,
    tmp_path: Path,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    days = tmp_path / "days"
    days.mkdir()
    day_summary(days, project_root, (D1, D2), D1, "eksik", "gec baslangic")
    if failure == "status":
        api.status = 500
    elif failure == "page":
        api.runs_total = 101
    environment = {} if failure == "env" else aggregate_env(api_url)
    out = tmp_path / "total.json"
    code = shadow_job.aggregate(
        environment, days_dir=days, out=out, root=project_root, planned=(D1, D2)
    )
    assert code == 0
    assert total_days(out) == {
        D1.isoformat(): ("eksik", "gec baslangic"),
        D2.isoformat(): ("bilinmiyor", "kanit yetersiz"),
    }
    text = capsys.readouterr().out
    assert "UYARI toplam" in text
    assert TOKEN not in text


def test_the_aggregate_does_not_call_the_api_when_every_day_has_a_summary(
    api: Api, api_url: str, tmp_path: Path, project_root: Path
) -> None:
    days = tmp_path / "days"
    days.mkdir()
    day_summary(days, project_root, (D1,), D1, "tamam", None)
    shadow_job.aggregate(
        aggregate_env(api_url),
        days_dir=days,
        out=tmp_path / "t.json",
        root=project_root,
        planned=(D1,),
    )
    assert api.requests == []
