"""Golge gozlem isi: bir planli gunu emirsiz gozler ve fiyatsiz ozet yazar.

Sozlesme: docs/designs/shadow-observation.md. Adimlar:

  * `gate` (kapi isi) - secret'siz, yalnizca `actions: read`. Gunun
    planli olup olmadigini, baslangic penceresini ve ayni gun kayit
    yazmis baska kosu olup olmadigini (Actions API) okur; karari
    `$GITHUB_OUTPUT`'a yazar.
  * `observe` (gozlem isi) - secret'lar YALNIZCA burada. Resmi takvimi
    dogrular, acilisa kadar bekler, canli dongu `--dry-run` ile
    `ShadowBroker` ve kaydeden veri kaynagi uzerinde calisir; giris
    penceresi bitince SIP'i son sureye kadar bekler, karsilastirir ve
    gunun ozetini yazar.
  * `late` (gec kayit isi) - secret'siz. Gunu `eksik (gec baslangic)`
    diye yazar.
  * `collect` (toplam isi, indirme) - secret'siz, `actions: read`. Son
    planli gunden sonra, kampanya basina BIR kez: gozlem kosularinin gun
    ozeti artefaktlarini secer, indirir ve denetler (digest, tek elle
    izlenen yonlendirme, Authorization tasinmaz, tek uyeli ZIP, alan
    turleri).
  * `aggregate` (toplam) - secret'siz. Gunluk ozetlerden 20 gunluk
    ozeti kurar.

Toplam kampanya basina birdir: onceki toplam kosulari artefakt adi,
zaman ve adim kanitiyla kampanyaya baglanir; yeniden deneme yalnizca
`TOTAL_RETRY_FILE` kaydiyla (parmak izi disinda, kampanya + kesin kosu).

Her gun ozeti ve toplam KAMPANYA KIMLIGINI tasir (`campaign_of`): planli
tarihler, evren, esikler, strateji surumu, sema surumleri ve uygulama
parmak izinin (`implementation_fingerprint`) ozeti. Gun ozeti ayrica
kaynak kosusunu (`run_id`, `run_attempt`, `code_sha`) tasir; toplam isi
bunu API kosusuyla eslestirir. Baska kampanyanin ya da baska kosunun
ciktisi toplama girmez.

Log'a yalnizca sabit satirlar gider. Dongu islemleri fiyatla, kesiciyi
yuzdeyle loglar; bu yuzden butun adimlar boyunca `logging` kapatilir
(`job_io.silenced`). Hata yalnizca sabit sinifiyla basilir (`classify`).
Ham bar, mutlak fiyat ve hesap degeri disari cikmaz; gorulen kayit ve
journal gecici calisma dizinindedir ve her durumda silinir.

`PLANNED_DAYS` bos: tarihler yurutme kararinda (d) sabitlenir. Bos
listeyle her gun plan disidir ve is hicbir sey yapmaz.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple, get_args, get_type_hints

from tlab.core.clock import Clock, LiveClock
from tlab.job_io import silenced, write_new
from tlab.sdk_probe import classify
from tlab.shadow.schedule import (
    GATE_SKIP,
    PriorRun,
    decide,
    regular_open,
    session_day_of,
)

PLANNED_DAYS: tuple[date, ...] = ()
"""Yurutme kararinda (d) sabitlenir. Bos: is hicbir gun calismaz."""

KEY_ENV = (
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_SECRET_KEY",
)
"""Anahtar DEGISKEN ADLARI; degerler yalnizca gozlem adiminda ortamdan okunur."""
SECRET_ENV_PREFIXES = ("ALPACA_", "APCA_")

DAY_SCHEMA = 1
TURN_OFFSET = timedelta(seconds=7)
"""Turlar dakikanin bu kadar sonrasinda: biten dakikanin bari kapanmis olur."""
LAST_START = timedelta(minutes=1)
"""Gozlem acilistan en gec bu kadar once baslamis olmali."""
SIP_DELAY = timedelta(minutes=15)
"""Ucretsiz plan SIP'in son 15 dakikasini vermez."""
SIP_DEADLINE = timedelta(minutes=45)
"""Giris penceresi sonundan sonra SIP icin son sure."""
SIP_POLL = timedelta(minutes=5)


# --------------------------------------------------------------------------
# Kampanya
# --------------------------------------------------------------------------

CAMPAIGN_PREFIX = 16
"""Toplam artefaktinin adina giren kimlik hanesi: yalnizca arama anahtari.
Gun ozetlerinde TAM kimlik karsilastirilir."""
PACKAGE_ROOT = Path(__file__).resolve().parent
IMPLEMENTATION_ROOT_FILES = (
    "requirements.lock",
    ".github/workflows/shadow-observation.yml",
    ".github/workflows/shadow-aggregate.yml",
)
"""Parmak izine giren kok dosyalari. Paketin butun `.py` dosyalari (dolayli
bagimliliklar dahil) ve `config/*.yaml` de girer."""
SOURCE_ENV = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA")
"""Gun ozetine yazilan kaynak kimligi; toplam isi API kosusuyla eslestirir."""
_SHA40 = re.compile(r"[0-9a-f]{40}")


class Campaign(NamedTuple):
    identity: str
    symbols: tuple[str, ...]
    implementation: str


def implementation_fingerprint(root: Path) -> str:
    """Uygulama parmak izi: sirali dosya manifestinin SHA-256'si.

    Paketin butun `.py` dosyalari, `config/*.yaml`, `requirements.lock` ve
    iki golge workflow'u. Kampanya kimligine girer: ayni parametrelerle
    degisen kod BASKA kampanyadir; gun ozetleri karismaz, toplam ancak
    ayni uygulamayla kurulur (Codex 6172892558). Dondurma boylece kodla
    zorlanir. Eksik dosya hatadir; `_campaign` sabit satirla yakalar.
    Yeniden deneme kaydi (`TOTAL_RETRY_FILE`, JSON) bilincli olarak
    DISARIDADIR: yetki olcumu degistirmez.
    """
    entries = [
        (f"tlab/{path.relative_to(PACKAGE_ROOT).as_posix()}", path)
        for path in PACKAGE_ROOT.rglob("*.py")
    ]
    entries += [(f"config/{path.name}", path) for path in (root / "config").glob("*.yaml")]
    entries += [(name, root / name) for name in IMPLEMENTATION_ROOT_FILES]
    manifest = hashlib.sha256()
    for name, path in sorted(entries):
        manifest.update(f"{name}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return manifest.hexdigest()


def campaign_of(planned: Sequence[date], symbols: Sequence[str], root: Path) -> str:
    """Kampanya kimligi: kanonik JSON'un SHA-256'si (64 onaltilik hane).

    Icerik: planli tarihler, evren sembolleri, esikler (`Thresholds`),
    strateji `params_version`, gun ve toplam sema surumleri ve uygulama
    parmak izi. Biri degisirse kimlik de degisir: eski kampanyanin gun
    ozeti yeni toplama girmez, yeni kampanyanin toplami eskisinin teklik
    kanitina takilmaz.
    """
    from tlab.shadow.summary import SUMMARY_SCHEMA, Thresholds
    from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

    content = {
        "planned_days": sorted(day.isoformat() for day in planned),
        "symbols": sorted(symbols),
        "thresholds": asdict(Thresholds()),
        "params_version": OpeningRangeBreakout(ORBParams()).params_version,
        "day_schema": DAY_SCHEMA,
        "summary_schema": SUMMARY_SCHEMA,
        "implementation": implementation_fingerprint(root),
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _campaign(root: Path, planned: Sequence[date]) -> Campaign | None:
    """Kimlik, evren ve parmak izi; yapilandirma okunamazsa sabit satir ve None."""
    from tlab.config import load_config

    try:
        symbols = tuple(load_config(root).symbols)
        return Campaign(
            campaign_of(planned, symbols, root), symbols, implementation_fingerprint(root)
        )
    except Exception as exc:  # sinifi basilir; metni (yol, deger) basilmaz
        print(f"FAIL yapilandirma: kampanya kimligi ({type(exc).__name__})")
        return None


def _source(env: Mapping[str, str]) -> tuple[int, int, str] | None:
    """Kosu kimligi (run_id, run_attempt, code_sha); yoksa sabit satir ve None."""
    run_id, attempt, sha = (env.get(name, "").strip() for name in SOURCE_ENV)
    if (
        run_id.isdigit()
        and attempt.isdigit()
        and int(run_id) > 0
        and int(attempt) > 0
        and _SHA40.fullmatch(sha)
    ):
        return int(run_id), int(attempt), sha
    print("FAIL yapilandirma: kosu kimligi (GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, GITHUB_SHA)")
    return None


# --------------------------------------------------------------------------
# Kapi
# --------------------------------------------------------------------------

WORKFLOW_FILE = "shadow-observation.yml"
RECORD_JOB = "record"
"""Gunu kaydeden is (gozlem ya da gec kayit). Teklik bu isin atlanmadigi
kosulari sayar; bos gecen kosu sayilmaz."""
GATE_ENV = ("GITHUB_API_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GH_TOKEN")
MAX_API_BYTES = 2_000_000
PAGE_SIZE = 100
API_TIMEOUT_SECONDS = 30
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


class GateError(Exception):
    """Basilabilir, SABIT metin: adres, govde ya da token tasimaz."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Yonlendirme izlenmez: Authorization basligi baska host'a tasinmaz."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def gate(
    env: Mapping[str, str],
    *,
    clock: Clock,
    output: Path,
    planned: Sequence[date] = PLANNED_DAYS,
) -> int:
    """Kapinin karari `output`'a `action=` ve `day=` satirlari olarak yazilir.

    Plan disi gunde API'ye hic gidilmez. Kosu gecmisi okunamazsa kapi
    KAPALI kalir (gun kaybolabilir, iki kez kosmaz) ve is kirmizi biter.
    """
    with silenced():
        now = clock.now()
        day = session_day_of(now)
        if day not in planned:
            return _gate_out(output, GATE_SKIP, day, "plan disi gun", code=0)
        if any(name.startswith(SECRET_ENV_PREFIXES) for name in env):
            return _gate_out(output, GATE_SKIP, day, "kapi secret'siz calisir", code=1)
        api, repo, run_id, token = (env.get(name, "").strip() for name in GATE_ENV)
        if not (api and repo and run_id and token):
            return _gate_out(output, GATE_SKIP, day, "yapilandirma", code=1)
        if env.get("GITHUB_RUN_ATTEMPT", "1") != "1":
            # Yeniden deneme ayni kosunun onceki kaydini goremez; hic kosmaz.
            return _gate_out(output, GATE_SKIP, day, "yeniden deneme kosusu", code=0)
        try:
            prior = _prior_runs(api, repo, run_id, token, day)
        except GateError as exc:
            return _gate_out(output, GATE_SKIP, day, str(exc), code=1)
        decision = decide(now, planned, prior)
        return _gate_out(output, decision.action, day, decision.reason, code=0)


def _gate_out(output: Path, action: str, day: date, reason: str, *, code: int) -> int:
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"action={action}\nday={day.isoformat()}\n")
    print(f"{'OK' if code == 0 else 'FAIL'} kapi: {action} ({reason})")
    return code


def _prior_runs(api: str, repo: str, run_id: str, token: str, day: date) -> list[PriorRun]:
    """Ayni seans gununun bu kosudan ONCE olusturulmus kosulari.

    Sonraki kosular sayilmaz: eszamanlilik grubu workflow duzeyindedir,
    sonraki bir kosu bu kosu bitmeden baslayamaz. Onceki kosunun kayit
    isi icin durum tablosu (tasarim §5):

      * tamamlandi ve atlandi (butun denemelerde): sayilmaz;
      * tamamlandi (basarili, basarisiz, iptal...): sayilir;
      * kuyrukta, suruyor ya da bekliyor: sayilir (kapali kal);
      * is listesinde kayit isi yok: sayilir (kapali kal).

    Liste tek sayfayi asarsa kapi kapali kalir.
    """
    try:
        current = int(run_id)
    except ValueError:
        raise GateError("kosu kimligi bicimsiz") from None
    query = urllib.parse.urlencode(
        {"created": f">={(day - timedelta(days=1)).isoformat()}", "per_page": str(PAGE_SIZE)}
    )
    runs = _api_json(f"{api}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?{query}", token)
    items = _single_page(runs, "workflow_runs", "kosu listesi")
    prior: list[PriorRun] = []
    for run in items:
        try:
            identifier = int(run["id"])
            created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise GateError("kosu kaydi beklenen bicimde degil") from None
        if identifier >= current or session_day_of(created) != day:
            continue
        jobs = _single_page(
            _api_json(
                f"{api}/repos/{repo}/actions/runs/{identifier}/jobs"
                f"?filter=all&per_page={PAGE_SIZE}",
                token,
            ),
            "jobs",
            "is listesi",
        )
        record = [job for job in jobs if job.get("name") == RECORD_JOB]
        skipped = bool(record) and all(
            job.get("status") == "completed" and job.get("conclusion") == "skipped"
            for job in record
        )
        prior.append(PriorRun(day, recorded=not skipped))
    return prior


def _single_page(payload: dict[str, Any], key: str, what: str) -> list[dict[str, Any]]:
    items = payload.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise GateError(f"{what} beklenen bicimde degil")
    total = payload.get("total_count", len(items))
    if not isinstance(total, int) or total > len(items):
        raise GateError(f"{what} tek sayfayi asti")
    return items


def _api_json(url: str, token: str, what: str = "kosu gecmisi") -> dict[str, Any]:
    parts = urllib.parse.urlsplit(url)
    if not (
        parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS)
    ):
        raise GateError("beklenmeyen API adres semasi")
    request = urllib.request.Request(  # noqa: S310 - sema yukarida denetlendi
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=API_TIMEOUT_SECONDS) as response:
            body: bytes = response.read(MAX_API_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise GateError(f"{what} okunamadi (HTTP {exc.code})") from None
    except (urllib.error.URLError, OSError) as exc:
        raise GateError(f"{what} okunamadi ({type(exc).__name__})") from None
    if len(body) > MAX_API_BYTES:
        raise GateError("API yaniti boyut sinirini asti")
    try:
        payload = json.loads(body)
    except ValueError:
        raise GateError("API yaniti JSON degil") from None
    if not isinstance(payload, dict):
        raise GateError("API yaniti beklenen bicimde degil")
    return payload


# --------------------------------------------------------------------------
# Gozlem
# --------------------------------------------------------------------------


def observe(
    env: Mapping[str, str],
    *,
    clock: Clock,
    sleep: Callable[[float], None],
    workdir: Path,
    out: Path,
    root: Path,
    planned: Sequence[date] = PLANNED_DAYS,
    base_url: str | None = None,
) -> int:
    """Bir gunu gozler; ozet yazildiysa 0. Eksik gun de bir sonuctur.

    `planned` ve `base_url` YALNIZCA testler icin: `main()` gecirmez.
    """
    with silenced():
        day = session_day_of(clock.now())
        if day not in planned:
            print("SKIP gozlem: plan disi gun")
            return 0
        found = _campaign(root, planned)
        source = _source(env)
        if found is None or source is None:
            return 1
        campaign = found.identity
        if clock.now() > regular_open(day) - LAST_START:
            # Ilk denetim, ag yok: kapi pencerede gecmis olabilir ama bu is
            # kuyrukta acilisi kacirdi. Gecmis barla doldurulmaz.
            print("FAIL zamanlama: gec baslangic (is baslarken)")
            return _write_day(out, day, campaign, source, "eksik", "gec baslangic", {})
        key, secret = (env.get(name, "").strip() for name in KEY_ENV)
        if not key or not secret:
            print("FAIL yapilandirma: paper anahtar ve secret gerekli")
            return _write_day(out, day, campaign, source, "eksik", "yapilandirma", {})
        try:
            workdir.parent.mkdir(parents=True, exist_ok=True)
            workdir.mkdir()
        except OSError as exc:
            print(f"FAIL yapilandirma: calisma dizini ({type(exc).__name__})")
            return 1
        try:
            status, reason, body = _observe_day(
                key,
                secret,
                day,
                clock=clock,
                sleep=sleep,
                workdir=workdir,
                root=root,
                base_url=base_url,
            )
        except Exception as exc:  # her hata sabit sinifa cevrilir; metni basilmaz
            print(f"FAIL gozlem: {classify(exc)} ({type(exc).__name__})")
            status, reason, body = "eksik", f"beklenmeyen hata ({type(exc).__name__})", {}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        return _write_day(out, day, campaign, source, status, reason, body)


def _observe_day(
    key: str,
    secret: str,
    day: date,
    *,
    clock: Clock,
    sleep: Callable[[float], None],
    workdir: Path,
    root: Path,
    base_url: str | None,
) -> tuple[str, str | None, dict[str, Any]]:
    from tlab.config import load_config
    from tlab.core.types import Timeframe
    from tlab.data.market import AlpacaMarketData
    from tlab.engine.runner import SessionRunner
    from tlab.execution.alpaca_broker import AlpacaBroker
    from tlab.journal.db import apply_migrations, connect
    from tlab.journal.writer import JournalWriter
    from tlab.risk.gate import RiskGate
    from tlab.sdk_compat import bound_transport
    from tlab.shadow.broker import ShadowBroker
    from tlab.shadow.core import RecordingStrategy, live_pure_mismatches
    from tlab.shadow.record import RecordingMarket, SeenRecord
    from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

    config = load_config(root)
    params = ORBParams()
    strategy = RecordingStrategy(OpeningRangeBreakout(params))
    timeframe = Timeframe.M1

    try:
        broker = AlpacaBroker(key, secret, paper=True, base_url=base_url)
        live = AlpacaMarketData(key, secret, feed="iex", base_url=base_url)
        sip = AlpacaMarketData(key, secret, feed="sip", base_url=base_url)
        for client in (broker._client, live._client, sip._client):
            bound_transport(client)
    except Exception as exc:
        print(f"FAIL istemci kurulumu: {classify(exc)}")
        return "eksik", f"istemci kurulumu: {classify(exc)}", {}

    try:
        calendar = broker.get_calendar(
            day, day + timedelta(days=7), exchange_timezone=config.app.exchange_timezone
        )
    except Exception as exc:
        print(f"FAIL takvim: {classify(exc)}")
        return "eksik", f"takvim alinamadi: {classify(exc)}", {}
    today = next((session for session in calendar if session.day == day), None)
    if today is None:
        print("FAIL takvim: gun takvimde yok")
        return "eksik", "takvimde gun yok", {}
    if today.open != regular_open(day):
        print("FAIL takvim: acilis duzenli saatle uyusmuyor")
        return "eksik", "takvim acilisi uyusmuyor", {}

    clock_check = _clock_check(broker, today.open, clock)

    conn = connect(workdir / "journal.db")
    apply_migrations(conn)
    record = SeenRecord(sqlite3.connect(workdir / "seen.db"))
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(
        mode="paper", data_feed="iex", params_version=strategy.params_version, config={}
    )
    runner = SessionRunner(
        broker=ShadowBroker(calendar, clock),
        market=RecordingMarket(live, record, clock),
        strategies=[strategy],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
        opening_range_minutes=params.opening_range_minutes,
        timeframe=timeframe,
        dry_run=True,
    )

    if clock.now() > today.open - LAST_START:
        # Ikinci denetim: takvim ve kurulum bitti, gozleme hazir. Zaman
        # alan takvim cagrisi ya da kurulum acilisi kacirdiysa gozlem
        # baslamaz.
        conn.close()
        record.conn.close()
        print("FAIL zamanlama: gec baslangic (kurulumdan sonra)")
        return "eksik", "gec baslangic", {"clock_consistent": clock_check}

    first_minute = today.open + timedelta(minutes=params.opening_range_minutes)
    last_minute = today.open + timedelta(minutes=params.entry_window_minutes)
    first, last = first_minute + TURN_OFFSET, last_minute + TURN_OFFSET
    expected_turns = int((last_minute - first_minute) / timedelta(minutes=1)) + 1
    called = failed = 0
    minute = first_minute
    while minute <= last_minute:
        _wait_until(clock, sleep, minute + TURN_OFFSET)
        now = clock.now()
        if now >= minute + timedelta(minutes=1):
            # Uyku ya da onceki tur bu dakikayi tasirdi: dakikanin turu
            # KOSMAZ ve telafi edilmez; simdiki dakikadan devam edilir.
            # Son planli dakika gectiyse dongu biter (Codex 6161518682).
            minute = now.replace(second=0, microsecond=0)
            continue
        try:
            runner.run_once()
            called += 1
        except Exception:  # tur hatasi donguyu oldurmez; yalnizca sayilir
            failed += 1
        minute += timedelta(minutes=1)
    conn.close()
    missed = expected_turns - called - failed

    symbols = list(config.symbols)
    moments = {symbol: record.moments(symbol) for symbol in symbols}
    # Cagrinin donmesi veri alindigi demek degildir: dongu sembol hatasini
    # kendi icinde yakalar. Gozlem, planli dakikanin kayittan OKUNABILEN
    # sembol-turudur.
    observed = sum(
        _observed(record, symbol, moments[symbol], minute_start)
        for symbol in symbols
        for minute_start in _planned_minutes(first_minute, last_minute)
    )
    expected_symbol_turns = expected_turns * len(symbols)
    grid_start = min((m[0] for m in moments.values() if m), default=first)
    grid_end = max((m[-1] for m in moments.values() if m), default=last)

    _wait_until(clock, sleep, grid_end + SIP_DELAY)
    deadline = today.open + timedelta(minutes=params.entry_window_minutes) + SIP_DEADLINE
    sip_bars, sip_reasons = _fetch_sip(
        sip,
        symbols,
        timeframe,
        start=grid_start - timedelta(days=runner.history_days),
        end=grid_end,
        session_open=today.open,
        clock=clock,
        sleep=sleep,
        deadline=deadline,
    )

    results = [
        _compare(
            symbol,
            moments[symbol],
            record,
            sip_bars.get(symbol),
            config,
            params,
            runner.history_days,
            today.close,
        )
        for symbol in symbols
    ]
    pure = [
        item
        for symbol in symbols
        for item in _pure_intents(
            symbol, moments[symbol], record, config, params, runner.history_days, today.close
        )
    ]
    mismatches = live_pure_mismatches(strategy.seen, pure)
    record.conn.close()
    sip_missing = sum(symbol not in sip_bars for symbol in symbols)
    reasons = []
    if missed:
        reasons.append(f"tur kacti ({missed}/{expected_turns})")
    if failed:
        reasons.append(f"tur hatali ({failed}/{expected_turns})")
    if observed < expected_symbol_turns:
        reasons.append(
            f"gozlenemeyen sembol-tur ({expected_symbol_turns - observed}/{expected_symbol_turns})"
        )
    if sip_missing:
        reasons.append(f"SIP gelmedi ({sip_missing} sembol)")
    if mismatches:
        # Kod bulgusu: canli dongu ile saf yol ayni gorunumden farkli niyet uretti.
        reasons.append(f"canli-saf tutarsizligi ({mismatches})")
    status = "eksik" if reasons else "tamam"
    print(
        f"OK gozlem: tur {called}/{expected_turns}, hatali tur {failed}, kacan tur {missed}, "
        f"gozlenen sembol-tur {observed}/{expected_symbol_turns}, "
        f"SIP {len(symbols) - sip_missing}/{len(symbols)}"
    )
    body = {
        "params_version": strategy.params_version,
        "clock_consistent": clock_check,
        # Dongu cagrilari: dondu / hata atti / dakikasinda hic yapilmadi.
        "turns": {"expected": expected_turns, "called": called, "failed": failed, "missed": missed},
        # Veri gozlemi: planli dakikada kayittan okunabilen sembol-tur.
        "symbol_turns": {"expected": expected_symbol_turns, "observed": observed},
        "sip_reasons": dict(sorted(sip_reasons.items())),
        "live_pure_mismatches": mismatches,
        "symbols": results,
    }
    return status, "; ".join(reasons) or None, body


def _clock_check(broker: Any, opening: datetime, clock: Clock) -> bool | None:
    """Alpaca saati takvimle tutarli mi; okunamazsa None (karar degil, bilgi)."""
    try:
        market_clock = broker.get_market_clock()
    except Exception:
        return None
    if clock.now() < opening:
        return (not market_clock.is_open) and market_clock.next_open == opening
    return bool(market_clock.is_open)


def _planned_minutes(first: datetime, last: datetime) -> list[datetime]:
    count = int((last - first) / timedelta(minutes=1)) + 1
    return [first + timedelta(minutes=index) for index in range(count)]


def _observed(record: Any, symbol: str, moments: Sequence[datetime], minute: datetime) -> bool:
    """Planli dakikanin turu (o dakikadaki ilk tur) kayittan okunabiliyor mu."""
    end = minute + timedelta(minutes=1)
    turn = next((moment for moment in moments if minute <= moment < end), None)
    return turn is not None and record.view(symbol, turn) is not None


def _wait_until(clock: Clock, sleep: Callable[[float], None], target: datetime) -> None:
    remaining = (target - clock.now()).total_seconds()
    if remaining > 0:
        sleep(remaining)


def _fetch_sip(
    sip: Any,
    symbols: Sequence[str],
    timeframe: Any,
    *,
    start: datetime,
    end: datetime,
    session_open: datetime,
    clock: Clock,
    sleep: Callable[[float], None],
    deadline: datetime,
) -> tuple[dict[str, list[Any]], dict[str, str]]:
    """SIP'i sembol basina son sureye kadar ister; TAM gelenleri dondurur.

    Son sure seans saatine bagli TEK sabittir; her istekten once ve
    yanittan sonra denetlenir. Yavas ya da tekrarlanan istek onu
    kaydirmaz.

    Tam (tasarim §6): acilistan son turun anina kadar her dakika bari var
    (`ts + sure <= end`). Son barin varligi yetmez (Codex 6161518682).
    Eksik yanit son sureye kadar yeniden istenir; son surede hala eksikse
    o sembolun SIP'i yoktur. Gercek veri boslugu ile henuz tamamlanmamis
    yanit tek yanittan ayrilamaz; ikisi de "tam degil"dir ve SIP tam
    sayilmaz.
    """
    complete: dict[str, list[Any]] = {}
    reasons: dict[str, str] = {}
    while True:
        for symbol in symbols:
            if symbol in complete:
                continue
            if clock.now() > deadline:
                reasons.setdefault(symbol, "son sure doldu")
                continue
            try:
                bars = sip.bars(symbol, timeframe, start, end)
            except Exception as exc:
                reasons[symbol] = classify(exc)
                continue
            if clock.now() > deadline:
                # Son sureden once baslayip sonra donen yanit da kabul edilmez.
                reasons[symbol] = "son sure doldu (yanit gec)"
                continue
            gaps = _session_gaps(bars, session_open, end, timeframe.duration)
            if not gaps:
                complete[symbol] = bars
                reasons.pop(symbol, None)
            else:
                reasons[symbol] = f"yanit eksik ({gaps} dakika)"
        if len(complete) == len(symbols) or clock.now() + SIP_POLL > deadline:
            return complete, reasons
        sleep(SIP_POLL.total_seconds())


def _session_gaps(
    bars: Sequence[Any], session_open: datetime, end: datetime, duration: timedelta
) -> int:
    """Acilistan `end`e kadar kapanmis olmasi gereken ama yanitta olmayan bar sayisi."""
    present = {bar.ts.timestamp() for bar in bars}
    missing = 0
    start = session_open
    while start + duration <= end:
        missing += start.timestamp() not in present
        start += duration
    return missing


def _compare(
    symbol: str,
    moments: list[datetime],
    record: Any,
    sip_bars: list[Any] | None,
    config: Any,
    params: Any,
    history_days: int,
    close: datetime,
) -> dict[str, Any]:
    from tlab.core.types import Timeframe
    from tlab.shadow.core import Turn, compare_symbol_day, session_at, visible_bars
    from tlab.strategies.orb import OpeningRangeBreakout

    timeframe = Timeframe.M1

    def seen(moment: datetime, bars: Sequence[Any] | None) -> Turn:
        if bars is None:
            return Turn(moment, None)
        return Turn(
            moment, visible_bars(bars, moment, timeframe=timeframe, history_days=history_days)
        )

    def session_for(moment: datetime) -> Any:
        return session_at(
            moment,
            config=config,
            opening_range_minutes=params.opening_range_minutes,
            market_close=close,
        )

    comparison = compare_symbol_day(
        symbol,
        [seen(moment, record.view(symbol, moment)) for moment in moments],
        [seen(moment, sip_bars) for moment in moments],
        session_for=session_for,
        strategy=OpeningRangeBreakout(params),
        opening_range_minutes=params.opening_range_minutes,
        entry_window_minutes=params.entry_window_minutes,
        timeframe=timeframe,
    )
    return {**asdict(comparison), "sip_available": sip_bars is not None}


def _pure_intents(
    symbol: str,
    moments: list[datetime],
    record: Any,
    config: Any,
    params: Any,
    history_days: int,
    close: datetime,
) -> list[tuple[datetime, str, Any]]:
    """Kayitli IEX gorunumunden saf yolun niyetleri (canli dongu ile karsilastirma)."""
    from tlab.core.types import Timeframe
    from tlab.shadow.core import intent_at, session_at, visible_bars
    from tlab.strategies.orb import OpeningRangeBreakout

    strategy = OpeningRangeBreakout(params)
    found = []
    for moment in moments:
        seen = record.view(symbol, moment)
        if seen is None:
            continue
        bars = visible_bars(seen, moment, timeframe=Timeframe.M1, history_days=history_days)
        session = session_at(
            moment,
            config=config,
            opening_range_minutes=params.opening_range_minutes,
            market_close=close,
        )
        intent = intent_at(symbol, bars, session, strategy=strategy, timeframe=Timeframe.M1)
        if intent is not None:
            found.append((moment, symbol, intent))
    return found


def _write_day(
    out: Path,
    day: date,
    campaign: str,
    source: tuple[int, int, str],
    status: str,
    reason: str | None,
    body: Mapping[str, Any],
) -> int:
    run_id, run_attempt, code_sha = source
    payload = {
        "day_schema": DAY_SCHEMA,
        "day": day.isoformat(),
        "campaign": campaign,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "code_sha": code_sha,
        "status": status,
        "reason": reason,
        **body,
    }
    try:
        write_new(out, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
    except OSError as exc:
        print(f"FAIL ozet yazilamadi ({type(exc).__name__})")
        return 1
    print(f"OK gun {day.isoformat()}: {status}" + (f" ({reason})" if reason else ""))
    return 0


# --------------------------------------------------------------------------
# Gec kayit
# --------------------------------------------------------------------------


def record_late(
    env: Mapping[str, str],
    *,
    clock: Clock,
    out: Path,
    root: Path,
    planned: Sequence[date] = PLANNED_DAYS,
) -> int:
    """Gunu `eksik (gec baslangic)` diye yazar. Secret'li ortamda baslamaz."""
    with silenced():
        if any(name.startswith(SECRET_ENV_PREFIXES) for name in env):
            print("FAIL yapilandirma: gec kayit isi secret'siz calisir")
            return 1
        day = session_day_of(clock.now())
        if day not in planned:
            print("SKIP gec kayit: plan disi gun")
            return 0
        found = _campaign(root, planned)
        source = _source(env)
        if found is None or source is None:
            return 1
        return _write_day(out, day, found.identity, source, "eksik", "gec baslangic", {})


# --------------------------------------------------------------------------
# Toplam
# --------------------------------------------------------------------------


EVIDENCE_STEP = "adim"
"""Gunun kayit adimi (gozlem ya da gec kayit) GERCEKTEN kostu: adim kaniti var."""
EVIDENCE_RECORDED = "kayitli"
"""Kayit isi atlanmamis bir kosu var; gun rezerve edildi ama adim kaniti yok."""
EVIDENCE_NONE = "yok"
"""Kosu gecmisi okundu; gunun kosulari var ve hepsinde kayit isi atlandi."""
EVIDENCE_ABSENT = "kosu yok"
"""Gunun HIC kosu kaydi yok. Silinmis kosu ile hic tetiklenmemis cron
okunarak ayrilamaz: `baslamadi` DEGIL, `bilinmiyor` (Codex 6171961412)."""
EVIDENCE_UNCLEAR = "belirsiz"
"""Kanit yetersiz: gecmis okunamadi, kayit isi listede yok ya da hala suruyor."""
_EVIDENCE_RANK = {
    EVIDENCE_ABSENT: 0,
    EVIDENCE_NONE: 1,
    EVIDENCE_UNCLEAR: 2,
    EVIDENCE_RECORDED: 3,
    EVIDENCE_STEP: 4,
}
"""Birden cok kosuda en guclu kanit kazanir."""

RECORD_STEPS = ("Gozle", "Gec kaydi yaz")
"""Kayit isinin gunu yazan adimlari (workflow adim adlari; mimari test baglar)."""
STEP_RAN = ("success", "failure")
"""Adimin gercekten kostugunu gosteren sonuclar. `cancelled` dahil degil:
iptal, hic baslamamis adimi da isaretleyebilir; o kosu `kayitli` kalir."""

AGGREGATE_ENV = ("GITHUB_API_URL", "GITHUB_REPOSITORY", "GH_TOKEN")


def aggregate(
    env: Mapping[str, str],
    *,
    days_dir: Path,
    out: Path,
    root: Path,
    planned: Sequence[date] = PLANNED_DAYS,
) -> int:
    """Gunluk ozetler ve kosu gecmisinden toplam ozeti kurar (tasarim §6).

    Her gun ozeti once sozlesmeye gore denetlenir (`_parse_day`); biri
    uymazsa toplam yazilmaz. Ozet yoklugu `baslamadi` kaniti DEGILDIR.
    Ozeti olmayan gunun durumu kosu ve is ust verisinden gelir:

      * kayit adimi gercekten kostu: `eksik (kayit adimi kostu, ozet yok)`;
      * kayit isi atlanmamis kosu var ama adim kaniti yok (kuyruk, kurulum
        ya da iptal): `eksik (kosu var, ozet yok)`. Gun rezerve edildi;
        "basladi" denmez;
      * gunun kosulari okundu ve hepsinde kayit isi atlandi: `baslamadi`;
      * gunun hic kosu kaydi yok: `bilinmiyor (kosu kaydi yok)`;
      * gecmis okunamadi, kayit isi suruyor ya da kanit yetersiz:
        `bilinmiyor`.

    Secret'li (Alpaca) ortamda baslamaz.
    """
    from tlab.shadow.summary import (
        DAY_INCOMPLETE,
        DAY_NOT_STARTED,
        DAY_UNKNOWN,
        Day,
        SymbolDay,
        Thresholds,
        summarize,
    )

    with silenced():
        if any(name.startswith(SECRET_ENV_PREFIXES) for name in env):
            print("FAIL yapilandirma: toplam isi secret'siz calisir")
            return 1
        found = _campaign(root, planned)
        if found is None:
            return 1
        campaign, symbols, implementation = found
        days: list[Day] = []
        results: list[SymbolDay] = []
        try:
            for path in sorted(days_dir.rglob("*.json")):
                parsed = _parse_day(
                    json.loads(path.read_text(encoding="utf-8")),
                    campaign=campaign,
                    symbols=symbols,
                    planned=planned,
                )
                if any(known.day == parsed.day for known in days):
                    raise DaySummaryError("ayni gunun iki ozeti var")
                days.append(Day(parsed.day, parsed.status, parsed.reason))
                results.extend(
                    SymbolDay(parsed.day, comparison.symbol, comparison, sip_available)
                    for comparison, sip_available in parsed.symbols
                )
        except DaySummaryError as exc:
            print(f"FAIL toplam: {exc}")
            return 1
        except (OSError, ValueError, RecursionError) as exc:
            print(f"FAIL toplam: gunluk ozetler okunamadi ({type(exc).__name__})")
            return 1

        missing = [day for day in planned if not any(known.day == day for known in days)]
        evidence = _evidence_for(env, planned) if missing else {}
        for day in missing:
            kind = evidence.get(day, EVIDENCE_UNCLEAR)
            if kind == EVIDENCE_STEP:
                days.append(Day(day, DAY_INCOMPLETE, "kayit adimi kostu, ozet yok"))
            elif kind == EVIDENCE_RECORDED:
                days.append(Day(day, DAY_INCOMPLETE, "kosu var, ozet yok"))
            elif kind == EVIDENCE_NONE:
                days.append(Day(day, DAY_NOT_STARTED, "gozlem baslamadi"))
            elif kind == EVIDENCE_ABSENT:
                days.append(Day(day, DAY_UNKNOWN, "kosu kaydi yok"))
            else:
                days.append(Day(day, DAY_UNKNOWN, "kanit yetersiz"))
        try:
            summary = summarize(planned, symbols, days, results, Thresholds())
            summary["campaign"] = campaign
            summary["implementation"] = implementation
            write_new(out, (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode())
        except (OSError, ValueError) as exc:
            print(f"FAIL toplam yazilamadi ({type(exc).__name__})")
            return 1
        print(f"OK toplam: {len(planned) - len(missing)}/{len(planned)} gun ozeti")
        return 0


def _evidence_for(env: Mapping[str, str], planned: Sequence[date]) -> dict[date, str]:
    """Planli gunlerin kosu kaniti; okunamazsa bos (hepsi `belirsiz`)."""
    api, repo, token = (env.get(name, "").strip() for name in AGGREGATE_ENV)
    if not (api and repo and token):
        print("UYARI toplam: kosu gecmisi yapilandirmasi yok; ozetsiz gunler bilinmiyor")
        return {}
    try:
        return _day_evidence(api, repo, token, planned)
    except GateError as exc:
        print(f"UYARI toplam: {exc}; ozetsiz gunler bilinmiyor")
        return {}


def _day_evidence(api: str, repo: str, token: str, planned: Sequence[date]) -> dict[date, str]:
    """Her planli gun icin kosu ve is ust verisinden kanit (tasarim §6)."""
    runs = _observation_runs(api, repo, token, planned)
    evidence = dict.fromkeys(planned, EVIDENCE_ABSENT)
    for run in runs:
        try:
            identifier = int(run["id"])
            created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise GateError("kosu kaydi beklenen bicimde degil") from None
        day = session_day_of(created)
        if day not in evidence or evidence[day] == EVIDENCE_STEP:
            continue
        jobs = _single_page(
            _api_json(
                f"{api}/repos/{repo}/actions/runs/{identifier}/jobs"
                f"?filter=all&per_page={PAGE_SIZE}",
                token,
            ),
            "jobs",
            "is listesi",
        )
        found = _run_evidence([job for job in jobs if job.get("name") == RECORD_JOB])
        if _EVIDENCE_RANK[found] > _EVIDENCE_RANK[evidence[day]]:
            evidence[day] = found
    return evidence


def _observation_runs(
    api: str, repo: str, token: str, planned: Sequence[date]
) -> list[dict[str, Any]]:
    """Planli gunleri (bir gun payla) kapsayan gozlem kosulari; tek sayfa."""
    first, last = min(planned), max(planned)
    query = urllib.parse.urlencode(
        {
            "created": f"{(first - timedelta(days=1)).isoformat()}"
            f"..{(last + timedelta(days=1)).isoformat()}",
            "per_page": str(PAGE_SIZE),
        }
    )
    return _single_page(
        _api_json(f"{api}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?{query}", token),
        "workflow_runs",
        "kosu listesi",
    )


def _run_evidence(record: list[dict[str, Any]]) -> str:
    """Bir kosunun kayit isi kaydindan kanit."""
    if not record:
        return EVIDENCE_UNCLEAR
    if all(
        job.get("status") == "completed" and job.get("conclusion") == "skipped" for job in record
    ):
        return EVIDENCE_NONE
    for job in record:
        steps = job.get("steps")
        if isinstance(steps, list) and any(
            isinstance(step, dict)
            and step.get("name") in RECORD_STEPS
            and step.get("conclusion") in STEP_RAN
            for step in steps
        ):
            return EVIDENCE_STEP
    if any(job.get("status") != "completed" for job in record):
        return EVIDENCE_UNCLEAR
    return EVIDENCE_RECORDED


# --------------------------------------------------------------------------
# Gun ozeti sozlesmesi
# --------------------------------------------------------------------------


class DaySummaryError(ValueError):
    """Gun ozeti sozlesmeye uymuyor. Metin SABIT: deger tasimaz."""


DAY_HEAD = frozenset(
    {"day_schema", "day", "campaign", "run_id", "run_attempt", "code_sha", "status", "reason"}
)
"""Her gun ozetinde bulunan alanlar: kimlik (kampanya, kosu, kod) ve durum."""
DAY_BODY = frozenset(
    {
        "params_version",
        "clock_consistent",
        "turns",
        "symbol_turns",
        "sip_reasons",
        "live_pure_mismatches",
        "symbols",
    }
)
"""Gozlem govdesi. Tamamlanan gunde hepsi zorunlu; eksik gunde bulunanlar
denetlenir."""
TURN_KEYS = ("expected", "called", "failed", "missed")
SYMBOL_TURN_KEYS = ("expected", "observed")
COUNT_FIELDS = ("window_expected", "iex_present", "sip_present", "iex_unknown_turns")
"""Karsilastirmanin sayac alanlari: negatif olamaz."""


class ParsedDay(NamedTuple):
    day: date
    status: str
    reason: str | None
    symbols: list[tuple[Any, bool]]
    """(Comparison, sip_available) ciftleri."""
    run_id: int
    run_attempt: int
    code_sha: str


def _parse_day(
    payload: Any, *, campaign: str, symbols: Sequence[str], planned: Sequence[date]
) -> ParsedDay:
    """Gun ozetini tur ve tutarlilik bakimindan denetler (tasarim §6).

    Her sapma `DaySummaryError`dir: ozet sessizce dusurulmez, butun
    toplama durur. Beklenen tur ve pencere sayilari sabit stratejiden
    turetilir; `params_version` kampanyaninkine esit olmali (Codex
    6175607709). Tamamlanan gun sayaclarla tutarli olmalidir: kacan ya da
    hatali tur yok, butun sembol-turlar gozlendi, canli-saf tutarsizligi
    yok, evrenin her sembolu SIP'li (SIP sebebi yoklugu bundan cikar:
    sebep anahtarlari SIP'siz sembollerle birebir).
    """
    from tlab.shadow.summary import DAY_COMPLETE, DAY_INCOMPLETE
    from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

    params = ORBParams()
    expected_turns = params.entry_window_minutes - params.opening_range_minutes + 1

    if not isinstance(payload, dict):
        raise DaySummaryError("gun ozeti beklenen bicimde degil")
    keys = set(payload)
    if not keys >= DAY_HEAD or not keys <= DAY_HEAD | DAY_BODY:
        raise DaySummaryError("gun ozetinin alanlari beklenen kumede degil")
    if not _typed(payload["day_schema"], int) or payload["day_schema"] != DAY_SCHEMA:
        raise DaySummaryError("gun ozeti semasi tanimsiz")
    raw_day = payload["day"]
    try:
        day = date.fromisoformat(raw_day)
    except (TypeError, ValueError):
        raise DaySummaryError("gun ozetinin gunu bicimsiz") from None
    if day.isoformat() != raw_day:
        raise DaySummaryError("gun ozetinin gunu bicimsiz")
    if day not in planned:
        raise DaySummaryError("gun ozetinin gunu planda yok")
    if payload["campaign"] != campaign:
        raise DaySummaryError("gun ozeti baska kampanyanin")
    run_id, attempt, sha = payload["run_id"], payload["run_attempt"], payload["code_sha"]
    if not (_typed(run_id, int) and run_id > 0 and _typed(attempt, int) and attempt == 1):
        raise DaySummaryError("gun ozetinin kosu kimligi beklenen bicimde degil")
    if not (isinstance(sha, str) and _SHA40.fullmatch(sha)):
        raise DaySummaryError("gun ozetinin kod kimligi beklenen bicimde degil")
    status, reason = payload["status"], payload["reason"]
    if status == DAY_COMPLETE:
        consistent = reason is None
    elif status == DAY_INCOMPLETE:
        consistent = isinstance(reason, str) and bool(reason)
    else:
        raise DaySummaryError("gun durumu tanimsiz")
    if not consistent:
        raise DaySummaryError("gun durumu ve sebebi tutarsiz")

    if "params_version" in payload:
        if not isinstance(payload["params_version"], str):
            raise DaySummaryError("strateji surumu beklenen bicimde degil")
        if payload["params_version"] != OpeningRangeBreakout(params).params_version:
            raise DaySummaryError("strateji surumu kampanyayla uyusmuyor")
    if "clock_consistent" in payload and not _typed(payload["clock_consistent"], bool | None):
        raise DaySummaryError("saat denetimi beklenen bicimde degil")
    turns = _counts(payload, "turns", TURN_KEYS)
    if turns and turns["expected"] != expected_turns:
        raise DaySummaryError("tur sayaclari stratejiyle uyusmuyor")
    if turns and turns["called"] + turns["failed"] + turns["missed"] != turns["expected"]:
        raise DaySummaryError("tur sayaclari tutarsiz")
    symbol_turns = _counts(payload, "symbol_turns", SYMBOL_TURN_KEYS)
    if symbol_turns and symbol_turns["expected"] != expected_turns * len(symbols):
        raise DaySummaryError("sembol-tur sayaclari stratejiyle uyusmuyor")
    if symbol_turns and symbol_turns["observed"] > symbol_turns["expected"]:
        raise DaySummaryError("sembol-tur sayaclari tutarsiz")
    sip_reasons = payload.get("sip_reasons", {})
    if not isinstance(sip_reasons, dict) or not all(
        name in symbols and isinstance(text, str) for name, text in sip_reasons.items()
    ):
        raise DaySummaryError("SIP sebepleri beklenen bicimde degil")
    mismatches = payload.get("live_pure_mismatches", 0)
    if not _is_count(mismatches):
        raise DaySummaryError("canli-saf sayaci beklenen bicimde degil")
    items = payload.get("symbols", [])
    if not isinstance(items, list):
        raise DaySummaryError("sembol sonuclari beklenen bicimde degil")
    parsed = [_parse_symbol(item, symbols, params, expected_turns) for item in items]
    names = [comparison.symbol for comparison, _ in parsed]
    if len(set(names)) != len(names):
        raise DaySummaryError("bir sembol iki kez raporlandi")
    if set(sip_reasons) != {comparison.symbol for comparison, sip in parsed if not sip}:
        raise DaySummaryError("SIP sebepleri SIP'siz sembollerle uyusmuyor")

    if status == DAY_COMPLETE and not (
        keys == DAY_HEAD | DAY_BODY
        and turns["failed"] == turns["missed"] == 0
        and symbol_turns["observed"] == symbol_turns["expected"]
        and mismatches == 0
        and set(names) == set(symbols)
        and all(sip_available for _, sip_available in parsed)
    ):
        raise DaySummaryError("tamamlanan gun sayaclarla tutarsiz")
    return ParsedDay(day, status, reason, parsed, run_id, attempt, sha)


def _parse_symbol(
    item: Any, symbols: Sequence[str], params: Any, expected_turns: int
) -> tuple[Any, bool]:
    """Bir sembol sonucu: alanlar `Comparison` + `sip_available`, turleriyle.

    Tutarlilik `compare_symbol_day`in uretebildigi birlesimlerdir: pencere
    sayaclari stratejinin penceresini asmaz, SIP penceresi IEX'siz
    sayilmaz, gecikmeli tamlik eksik pencere ister, aralik farki yalnizca
    `hesaplandi` ile gelir, ilk niyet dakikasi planli pencerede, sinyal ilk
    niyet dakikalariyla uyumlu, SIP'siz sembolde SIP'e dayanan alan yok.
    """
    from tlab.shadow.core import (
        RANGE_COMPUTED,
        RANGE_IEX_INCOMPLETE,
        RANGE_SIP_MISSING,
        RANGE_STATUSES,
        RANGE_UNKNOWN,
        SIGNAL_MATCH,
        SIGNAL_MISMATCH,
        SIGNAL_NONE,
        SIGNAL_UNKNOWN,
        SIGNALS,
        Comparison,
    )

    hints = get_type_hints(Comparison)
    if not isinstance(item, dict) or set(item) != set(hints) | {"sip_available"}:
        raise DaySummaryError("sembol sonucunun alanlari beklenen kumede degil")
    if not all(_typed(item[name], hint) for name, hint in hints.items()) or not _typed(
        item["sip_available"], bool
    ):
        raise DaySummaryError("sembol sonucunun turleri beklenen gibi degil")
    if item["symbol"] not in symbols:
        raise DaySummaryError("sembol kampanya evreninde yok")
    if item["range_status"] not in RANGE_STATUSES or item["signal"] not in SIGNALS:
        raise DaySummaryError("sembol sonucunun durumu tanimsiz")
    if any(item[name] is not None and item[name] < 0 for name in COUNT_FIELDS):
        raise DaySummaryError("sembol sonucunda negatif sayac")
    window = params.opening_range_minutes
    present = (item["iex_present"], item["sip_present"])
    if item["window_expected"] != window or any(p is not None and p > window for p in present):
        raise DaySummaryError("pencere sayaclari stratejiyle uyusmuyor")
    if present[1] is not None and present[0] is None:
        raise DaySummaryError("SIP penceresi IEX penceresi olmadan sayilmaz")
    if item["iex_completed_later"] and not (present[0] is not None and present[0] < window):
        raise DaySummaryError("gecikmeli tamlik eksik pencere gerektirir")
    if item["iex_unknown_turns"] > expected_turns:
        raise DaySummaryError("bilinmeyen tur sayisi planli turlari asiyor")
    computed = item["range_status"] == RANGE_COMPUTED
    if (item["or_high_bps"] is not None, item["or_low_bps"] is not None) != (computed, computed):
        raise DaySummaryError("aralik durumu ve farklari tutarsiz")
    firsts = (item["iex_first_minute"], item["sip_first_minute"])
    if any(m is not None and not window <= m < params.entry_window_minutes + 1 for m in firsts):
        raise DaySummaryError("ilk niyet dakikasi planli pencerenin disinda")
    signal, both, neither = item["signal"], None not in firsts, firsts == (None, None)
    if (
        (signal == SIGNAL_MATCH and not both)
        or (signal == SIGNAL_NONE and not neither)
        or (signal == SIGNAL_MISMATCH and neither)
    ):
        raise DaySummaryError("sinyal ve ilk niyet dakikalari tutarsiz")
    if not item["sip_available"] and (
        present[1] is not None
        or firsts[1] is not None
        or signal != SIGNAL_UNKNOWN
        or item["range_status"] not in (RANGE_SIP_MISSING, RANGE_UNKNOWN, RANGE_IEX_INCOMPLETE)
    ):
        raise DaySummaryError("SIP'siz sembolde SIP'e dayanan alan var")
    return Comparison(**{name: item[name] for name in hints}), item["sip_available"]


def _typed(value: Any, hint: Any) -> bool:
    """JSON degeri alan turune uyuyor mu. bool tamsayi sayilmaz; tamsayi
    ondalik alana uyar; ondalik sonlu olmali."""
    options = get_args(hint) or (hint,)
    if value is None:
        return type(None) in options
    if isinstance(value, bool):
        return bool in options
    if isinstance(value, int):
        return int in options or float in options
    if isinstance(value, float):
        return float in options and math.isfinite(value)
    if isinstance(value, str):
        return str in options
    return False


def _is_count(value: Any) -> bool:
    return _typed(value, int) and value >= 0


def _counts(payload: dict[str, Any], key: str, names: tuple[str, ...]) -> dict[str, int]:
    """Sayac sozlugu: tam olarak `names`, negatif olmayan tamsayilar. Yoksa bos."""
    if key not in payload:
        return {}
    value = payload[key]
    if (
        not isinstance(value, dict)
        or set(value) != set(names)
        or not all(_is_count(value[name]) for name in names)
    ):
        raise DaySummaryError(f"{key} beklenen bicimde degil")
    return value


# --------------------------------------------------------------------------
# Toplam isi: gun ozetlerini indirme
# --------------------------------------------------------------------------

AGGREGATE_WORKFLOW_FILE = "shadow-aggregate.yml"
TOTAL_JOB = "total"
TOTAL_STEPS = ("Indir", "Topla")
"""Toplam isinin indirme ve toplam adimlari (workflow adim adlari; mimari
test baglar). Sonraki toplam kosusu bunlarin sonucunu kanit olarak okur."""
TOTAL_RETRY_FILE = "config/shadow-total-retry.json"
"""Yeniden deneme yetkisi kaydi: `{"campaign": <tam kimlik>, "failed_run":
<kosu kimligi>, "decision": "#17/<yorum>"}`. Parmak izinin BILINCLI olarak
disindadir (yalnizca `config/*.yaml` girer): bu dosyayi degistiren karar
PR'i kampanya kimligini degistirmez, mevcut gunlukler gecerli kalir.
Yetki yalnizca o kampanyanin O basarisiz kosusunu kanit disi birakir;
baska kampanyanin kaydi isi durdurur (Codex 6177175728)."""
OBSERVATION_EVENTS = frozenset({"schedule", "workflow_dispatch"})
"""Gun ozeti alinabilen tetikler: GitHub cron'u ve dis baslaticinin
`workflow_dispatch`'i (docs/designs/scheduler-alternatives.md A; Codex
6196548874). Baska tetik (push, pull_request, workflow_run...) secilmez;
mimari test bu kumeyi workflow'un tetikleriyle esitler."""
OBSERVATION_SOURCE = ("main", f".github/workflows/{WORKFLOW_FILE}", 1)
"""Gun ozeti alinan kosu: `main` dali, gozlem workflow'u, ilk deneme
(`head_branch`, `path`, `run_attempt`); tetigi ayrica `OBSERVATION_EVENTS`
icinde olmali."""
DAY_ARTIFACT = "shadow-day"
DAY_FILE = "shadow-day.json"
"""Kayit isinin yukledigi TEK dosya (workflow `Gun ozetini yukle`)."""
TOTAL_ARTIFACT = "shadow-total"
"""Toplam artefaktinin ad koku: `shadow-total-<kampanya kimliginin ilk 16 hanesi>`."""
DIGEST_PREFIX = "sha256:"
MAX_ZIP_BYTES = 1_000_000
MAX_DAY_BYTES = 1_000_000
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
COLLECT_ENV = ("GITHUB_API_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GH_TOKEN")


def total_artifact(campaign: str) -> str:
    return f"{TOTAL_ARTIFACT}-{campaign[:CAMPAIGN_PREFIX]}"


def collect(
    env: Mapping[str, str],
    *,
    clock: Clock,
    days_dir: Path,
    root: Path,
    output: Path,
    planned: Sequence[date] = PLANNED_DAYS,
) -> int:
    """Gozlem kosularinin gun ozetlerini `days_dir`e indirir; basariliysa 0.

    Toplam kampanya basina BIR kez uretilir (tasarim §6). Hicbir gozlem
    artefakti indirilmeden is kirmizi biter:

      * New York tarihi son planli gunden sonra degilse;
      * yeniden deneme kosusunda;
      * bu kosudan once olusturulmus bir toplam kosusu henuz bitmediyse,
        BU kampanya icin toplam adimi kostuysa (cikti yok ya da silinmis
        olsa da) ya da kaynagi belirsizse (`_prior_total_blocks`);
        `Indir`de duran bos, erken ya da reddedilmis kosu ve kanitli
        baska kampanyanin kosusu engel degildir; kayitli tekrar yetkisi
        (`TOTAL_RETRY_FILE`) yalnizca o kosuyu disarida birakir;
      * bu kampanyanin toplam artefakti depoda varsa (suresi dolmus
        olsa da);
      * planli gunun bir gozlem kosusu henuz bitmediyse.

    Gun ozetinin kaynagi (`run_id`, `run_attempt`, `code_sha`) API
    kosusuyla eslesmeli; kampanya kimligi uygulama parmak izini tasir.

    Okunamayan ya da tek sayfayi asan liste, eksik ya da uyusmaz digest,
    beklenmeyen ZIP ya da sozlesmeye uymayan gun ozeti KISMI toplam
    yazdirmaz: is kirmizi biter. Suresi dolmus artefakt ve secilmeyen
    kosu atlanir; o gunun durumu toplamda kosu kanitiyla belirlenir.
    Basarida `output`a `campaign=<ilk 16 hane>` yazilir (yukleme adi).
    """
    with silenced():
        if any(name.startswith(SECRET_ENV_PREFIXES) for name in env):
            print("FAIL yapilandirma: toplam isi secret'siz calisir")
            return 1
        if not planned:
            print("FAIL toplam: planli gun yok")
            return 1
        # session_day_of: America/New_York takvim gunu (tlab.shadow.schedule).
        if session_day_of(clock.now()) <= max(planned):
            print("FAIL toplam: son planli gun henuz bitmedi (New York tarihi)")
            return 1
        api, repo, run_id, token = (env.get(name, "").strip() for name in COLLECT_ENV)
        if not (api and repo and run_id and token):
            print("FAIL yapilandirma: Actions API ortami eksik")
            return 1
        if env.get("GITHUB_RUN_ATTEMPT", "1") != "1":
            print("FAIL toplam: yeniden deneme kosusu (ayri karar gerekir)")
            return 1
        found = _campaign(root, planned)
        if found is None:
            return 1
        campaign, symbols = found.identity, found.symbols
        try:
            retry = _retry_authorisation(root, campaign)
            blocker = _prior_total_blocks(
                api, repo, run_id, token, campaign=campaign, planned=planned, retry=retry
            )
            if blocker is not None:
                print(f"FAIL toplam: {blocker}")
                return 1
            if _artifact_exists(api, repo, token, total_artifact(campaign)):
                print("FAIL toplam: bu kampanyanin toplami daha once uretildi")
                return 1
            written = _download_days(
                api, repo, token, planned, days_dir, campaign=campaign, symbols=symbols
            )
        except GateError as exc:
            print(f"FAIL toplam: {exc}")
            return 1
        try:
            with output.open("a", encoding="utf-8") as handle:
                handle.write(f"campaign={campaign[:CAMPAIGN_PREFIX]}\n")
        except OSError as exc:
            print(f"FAIL toplam: adim ciktisi yazilamadi ({type(exc).__name__})")
            return 1
        print(f"OK toplam: kampanya {campaign[:CAMPAIGN_PREFIX]}, {written} gun ozeti indirildi")
        return 0


def _retry_authorisation(root: Path, campaign: str) -> int | None:
    """Kayitli tekrar yetkisi: bu kampanyanin kanit disi birakilan kosusu.

    Dosya yoksa None. Biciminde degilse ya da baska kampanyaya aitse
    `GateError`: eski kayit yeni kampanyada birakilamaz.
    """
    path = root / TOTAL_RETRY_FILE
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GateError("tekrar kaydi beklenen bicimde degil") from None
    if (
        not isinstance(record, dict)
        or set(record) != {"campaign", "failed_run", "decision"}
        or not isinstance(record["campaign"], str)
        or not _is_count(record["failed_run"])
        or record["failed_run"] == 0
        or not isinstance(record["decision"], str)
        or not record["decision"]
    ):
        raise GateError("tekrar kaydi beklenen bicimde degil")
    if record["campaign"] != campaign:
        raise GateError("tekrar kaydi baska kampanyanin")
    failed_run: int = record["failed_run"]
    return failed_run


def _prior_total_blocks(
    api: str,
    repo: str,
    run_id: str,
    token: str,
    *,
    campaign: str,
    planned: Sequence[date],
    retry: int | None,
) -> str | None:
    """Bu kosudan ONCE olusturulmus toplam kosularinin kaniti; engel sebebi ya da None.

    Teklik kampanyaya baglidir, workflow omrune degil (Codex 6171961412,
    6177175728). Bitmis her onceki kosu icin sirayla:

      1. kosu bitmemis: engel (suruyor; eszamanlilik);
      2. kayitli tekrar yetkisi bu kosuyu gosteriyorsa: kanit disi;
      3. kosunun `shadow-total-*` artefakti varsa (suresi dolmus dahil):
         bu kampanyanin onekiyle engel; baska onekle kanit degil;
      4. artefakti yok ve kosu bu kampanyanin son planli gununden once ya
         da o gun (New York) olusturulmussa: bu kampanyanin toplami
         olamaz (`collect` o tarihte reddederdi); kanit degil;
      5. artefakti yok ve son planli gunden sonra: kaynagi belirsiz, adim
         kaniti okunur (Codex 6175607709):
           * `total` isi listede yok ya da adimlari okunamiyor: engel;
           * `Topla` kostu (`success`/`failure`): engel; upload hatasi ve
             silinmis artefakt burada yakalanir;
           * `Topla` atlandi ve `Indir` `failure`/`skipped`: engel degil
             (bos, erken, ret ya da indirme hatasi; cikti uretilmedi);
           * baska her birlesim (iptal, sonucsuz): engel (belirsiz).
    """
    try:
        current = int(run_id)
    except ValueError:
        raise GateError("kosu kimligi bicimsiz") from None
    prefix = total_artifact(campaign)
    last_day = max(planned)
    runs = _single_page(
        _api_json(
            f"{api}/repos/{repo}/actions/workflows/{AGGREGATE_WORKFLOW_FILE}/runs"
            f"?per_page={PAGE_SIZE}",
            token,
            "toplam kosu listesi",
        ),
        "workflow_runs",
        "toplam kosu listesi",
    )
    for run in runs:
        try:
            identifier = int(run["id"])
            created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise GateError("kosu kaydi beklenen bicimde degil") from None
        if identifier >= current:
            continue
        if run.get("status") != "completed":
            return "onceki toplam kosusu suruyor"
        if identifier == retry:
            continue  # kayitli tekrar yetkisi: yalnizca bu kosu
        totals = [
            str(item.get("name", ""))
            for item in _single_page(
                _api_json(
                    f"{api}/repos/{repo}/actions/runs/{identifier}/artifacts?per_page={PAGE_SIZE}",
                    token,
                    "artefakt listesi",
                ),
                "artifacts",
                "artefakt listesi",
            )
            if str(item.get("name", "")).startswith(TOTAL_ARTIFACT + "-")
        ]
        if totals:
            if prefix in totals:
                return "bu kampanyanin toplami daha once uretildi"
            continue  # kanitli baska kampanya
        if session_day_of(created) <= last_day:
            continue  # bu kampanyanin toplami olamaz: son planli gun gecmemisti
        jobs = _single_page(
            _api_json(
                f"{api}/repos/{repo}/actions/runs/{identifier}/jobs"
                f"?filter=all&per_page={PAGE_SIZE}",
                token,
                "toplam is listesi",
            ),
            "jobs",
            "toplam is listesi",
        )
        total = [job for job in jobs if job.get("name") == TOTAL_JOB]
        if not total:
            return "onceki toplam kosusunun kaniti yok"
        for job in total:
            if job.get("conclusion") == "skipped" and job.get("status") == "completed":
                continue  # is hic kosmadi (ornegin main disi dal)
            if job.get("status") != "completed":
                return "onceki toplam kosusu suruyor"
            steps = job.get("steps")
            if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
                return "onceki toplam kosusunun kaniti okunamadi"
            found = {
                step.get("name"): step.get("conclusion")
                for step in steps
                if step.get("name") in TOTAL_STEPS
            }
            if set(found) != set(TOTAL_STEPS):
                return "onceki toplam kosusunun kaniti okunamadi"
            collected, totaled = (found[name] for name in TOTAL_STEPS)
            if totaled in STEP_RAN:
                return "onceki toplam adimi kostu (cikti yok ya da silinmis)"
            if totaled == "skipped" and collected in ("failure", "skipped"):
                continue
            return "onceki toplam kosusu belirsiz"
    return None


def _artifact_exists(api: str, repo: str, token: str, name: str) -> bool:
    """Depoda bu adda artefakt var mi; suresi dolmus olanlar da listelenir."""
    query = urllib.parse.urlencode({"name": name, "per_page": str(PAGE_SIZE)})
    items = _single_page(
        _api_json(f"{api}/repos/{repo}/actions/artifacts?{query}", token, "artefakt listesi"),
        "artifacts",
        "artefakt listesi",
    )
    return any(item.get("name") == name for item in items)


def _download_days(
    api: str,
    repo: str,
    token: str,
    planned: Sequence[date],
    days_dir: Path,
    *,
    campaign: str,
    symbols: Sequence[str],
) -> int:
    """Planli gunlerin gozlem kosularindan gun ozetlerini indirir.

    Once BUTUN kosular okunur: planli gunun bitmemis kosusu varsa hicbir
    sey indirilmez. Plan disi gunun kosusu listelenmez. Tetigi
    `OBSERVATION_EVENTS` disinda ya da kaynagi `OBSERVATION_SOURCE`
    olmayan kosu sabit satirla atlanir.
    """
    selected: list[tuple[int, date, str]] = []
    for run in _observation_runs(api, repo, token, planned):
        try:
            identifier = int(run["id"])
            created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise GateError("kosu kaydi beklenen bicimde degil") from None
        day = session_day_of(created)
        if day not in planned:
            continue
        if run.get("status") != "completed":
            raise GateError("planli gunun gozlem kosusu henuz bitmedi")
        event = run.get("event")
        source = tuple(run.get(key) for key in ("head_branch", "path", "run_attempt"))
        if (
            not (isinstance(event, str) and event in OBSERVATION_EVENTS)
            or source != OBSERVATION_SOURCE
            or not _typed(source[-1], int)
        ):
            print(f"UYARI toplam: {day.isoformat()} kosusu secilmedi (kaynak ya da deneme)")
            continue
        head_sha = run.get("head_sha")
        if not (isinstance(head_sha, str) and _SHA40.fullmatch(head_sha)):
            raise GateError("kosu kaydi beklenen bicimde degil")
        selected.append((identifier, day, head_sha))

    days_dir.mkdir(parents=True, exist_ok=True)
    seen: set[date] = set()
    for identifier, day, head_sha in selected:
        query = urllib.parse.urlencode({"name": DAY_ARTIFACT, "per_page": str(PAGE_SIZE)})
        artifacts = [
            item
            for item in _single_page(
                _api_json(
                    f"{api}/repos/{repo}/actions/runs/{identifier}/artifacts?{query}",
                    token,
                    "artefakt listesi",
                ),
                "artifacts",
                "artefakt listesi",
            )
            if item.get("name") == DAY_ARTIFACT
        ]
        if not artifacts:
            continue
        if len(artifacts) > 1:
            raise GateError("bir kosuda birden cok gun ozeti artefakti")
        (artifact,) = artifacts
        expired = artifact.get("expired")
        if not isinstance(expired, bool):
            raise GateError("artefakt kaydi beklenen bicimde degil")
        if expired:
            print(f"UYARI toplam: {day.isoformat()} artefakti suresi dolmus")
            continue
        try:
            artifact_id = int(artifact["id"])
        except (KeyError, TypeError, ValueError):
            raise GateError("artefakt kaydi beklenen bicimde degil") from None
        digest = artifact.get("digest")
        if not isinstance(digest, str) or not digest.startswith(DIGEST_PREFIX):
            raise GateError("artefakt digest'i yok")
        data = _download_zip(api, repo, artifact_id, token)
        if hashlib.sha256(data).hexdigest() != digest.removeprefix(DIGEST_PREFIX):
            raise GateError("artefakt digest'i uyusmuyor")
        content = _day_from_zip(data)
        parsed = _check_day(content, day, campaign=campaign, symbols=symbols, planned=planned)
        if (parsed.run_id, parsed.run_attempt, parsed.code_sha) != (identifier, 1, head_sha):
            # Kaynak kimligi kosuyla eslesmeli: baska kosunun, denemenin ya
            # da kodun ozeti bu kosunun artefakti olamaz (Codex 6172892558).
            raise GateError("gun ozetinin kaynagi kosuyla uyusmuyor")
        if day in seen:
            raise GateError("ayni gunun iki gun ozeti var")
        seen.add(day)
        try:
            write_new(days_dir / f"{identifier}.json", content)
        except OSError as exc:
            raise GateError(f"gun ozeti yazilamadi ({type(exc).__name__})") from None
    return len(seen)


def _download_zip(api: str, repo: str, artifact_id: int, token: str) -> bytes:
    """API ZIP adresi -> TEK, elle izlenen yonlendirme -> baytlar.

    Ikinci istek YENI bir istektir: Authorization basligi YOKTUR ve o da
    yonlendirme izlemez. Ikinci yonlendirme okunmaz ve istenmez. Adres,
    token ve yanit govdesi basilmaz.
    """
    url = f"{api}/repos/{repo}/actions/artifacts/{artifact_id}/zip"
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(  # noqa: S310 - sema _checked_url ile denetlendi
        _checked_url(url),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener.open(request, timeout=API_TIMEOUT_SECONDS) as response:
            return _read_limited(response, MAX_ZIP_BYTES)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code not in REDIRECT_CODES:
            raise GateError(f"ZIP adresi okunamadi (HTTP {exc.code})") from None
        location = exc.headers.get("Location") if exc.headers is not None else None
    except (urllib.error.URLError, OSError) as exc:
        raise GateError(f"ZIP adresi okunamadi ({type(exc).__name__})") from None
    if not location:
        raise GateError("yonlendirme adresi yok")
    plain = urllib.request.Request(_checked_url(location))  # noqa: S310 - sema denetlendi
    try:
        with opener.open(plain, timeout=API_TIMEOUT_SECONDS) as response:
            return _read_limited(response, MAX_ZIP_BYTES)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in REDIRECT_CODES:
            raise GateError(f"ikinci yonlendirme reddedildi (HTTP {exc.code})") from None
        raise GateError(f"ZIP okunamadi (HTTP {exc.code})") from None
    except (urllib.error.URLError, OSError) as exc:
        raise GateError(f"ZIP okunamadi ({type(exc).__name__})") from None


def _checked_url(url: str) -> str:
    """Yalnizca https; yerel test sunucusu (loopback) icin http."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS):
        return url
    raise GateError("beklenmeyen adres semasi")


def _read_limited(response: Any, limit: int) -> bytes:
    body: bytes = response.read(limit + 1)
    if len(body) > limit:
        raise GateError("yanit boyut sinirini asti")
    return body


def _day_from_zip(data: bytes) -> bytes:
    """Tek uyeli ZIP'ten gun ozeti: ad sabit, yol bileseni yok, CRC temiz."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != DAY_FILE:
                raise GateError("ZIP beklenen tek uyeyi tasimiyor")
            (member,) = members
            if member.file_size > MAX_DAY_BYTES:
                raise GateError("gun ozeti boyut sinirini asti")
            # Okuma bildirilen boyutta durur ve sonunda CRC denetlenir:
            # boyutu yanlis bildiren uye `BadZipFile` olur.
            with archive.open(member) as handle:
                content: bytes = handle.read()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError):
        raise GateError("ZIP okunamadi (bicim ya da CRC)") from None
    return content


def _check_day(
    content: bytes,
    run_day: date,
    *,
    campaign: str,
    symbols: Sequence[str],
    planned: Sequence[date],
) -> ParsedDay:
    """Gun ozeti sozlesmeye uyuyor ve gunu kosunun seans gunuyle ayni."""
    try:
        payload = json.loads(content)
    except (ValueError, RecursionError):
        raise GateError("gun ozeti JSON degil") from None
    try:
        parsed = _parse_day(payload, campaign=campaign, symbols=symbols, planned=planned)
    except DaySummaryError as exc:
        raise GateError(str(exc)) from None
    if parsed.day != run_day:
        raise GateError("gun ozetinin gunu kosuyla uyusmuyor")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tlab.shadow_job")
    sub = parser.add_subparsers(dest="step", required=True)
    step_observe = sub.add_parser("observe", help="Gozlem isi (secret'li)")
    step_observe.add_argument("--workdir", type=Path, required=True)
    step_observe.add_argument("--out", type=Path, required=True)
    step_late = sub.add_parser("late", help="Gec kayit isi (secret'siz)")
    step_late.add_argument("--out", type=Path, required=True)
    step_collect = sub.add_parser("collect", help="Gun ozetlerini indir (secret'siz)")
    step_collect.add_argument("--days", type=Path, required=True)
    step_collect.add_argument("--output", type=Path, required=True)
    step_total = sub.add_parser("aggregate", help="Toplam ozet (secret'siz)")
    step_total.add_argument("--days", type=Path, required=True)
    step_total.add_argument("--out", type=Path, required=True)
    step_gate = sub.add_parser("gate", help="Kapi isi (secret'siz, actions: read)")
    step_gate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    clock = LiveClock()
    if args.step == "gate":
        return gate(os.environ, clock=clock, output=args.output)
    if args.step == "observe":
        return observe(
            os.environ,
            clock=clock,
            sleep=time.sleep,
            workdir=args.workdir,
            out=args.out,
            root=Path.cwd(),
        )
    if args.step == "late":
        return record_late(os.environ, clock=clock, out=args.out, root=Path.cwd())
    if args.step == "collect":
        return collect(
            os.environ, clock=clock, days_dir=args.days, root=Path.cwd(), output=args.output
        )
    return aggregate(os.environ, days_dir=args.days, out=args.out, root=Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
