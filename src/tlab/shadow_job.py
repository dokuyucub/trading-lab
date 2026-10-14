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
  * `aggregate` (toplam) - secret'siz. Gunluk ozetlerden 20 gunluk
    ozeti kurar.

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
import json
import os
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

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


def _api_json(url: str, token: str) -> dict[str, Any]:
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
        raise GateError(f"kosu gecmisi okunamadi (HTTP {exc.code})") from None
    except (urllib.error.URLError, OSError) as exc:
        raise GateError(f"kosu gecmisi okunamadi ({type(exc).__name__})") from None
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
        if clock.now() > regular_open(day) - LAST_START:
            # Ilk denetim, ag yok: kapi pencerede gecmis olabilir ama bu is
            # kuyrukta acilisi kacirdi. Gecmis barla doldurulmaz.
            print("FAIL zamanlama: gec baslangic (is baslarken)")
            return _write_day(out, day, "eksik", "gec baslangic", {})
        key, secret = (env.get(name, "").strip() for name in KEY_ENV)
        if not key or not secret:
            print("FAIL yapilandirma: paper anahtar ve secret gerekli")
            return _write_day(out, day, "eksik", "yapilandirma", {})
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
        return _write_day(out, day, status, reason, body)


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
    out: Path, day: date, status: str, reason: str | None, body: Mapping[str, Any]
) -> int:
    payload = {
        "day_schema": DAY_SCHEMA,
        "day": day.isoformat(),
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
    env: Mapping[str, str], *, clock: Clock, out: Path, planned: Sequence[date] = PLANNED_DAYS
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
        return _write_day(out, day, "eksik", "gec baslangic", {})


# --------------------------------------------------------------------------
# Toplam
# --------------------------------------------------------------------------


EVIDENCE_STEP = "adim"
"""Gunun kayit adimi (gozlem ya da gec kayit) GERCEKTEN kostu: adim kaniti var."""
EVIDENCE_RECORDED = "kayitli"
"""Kayit isi atlanmamis bir kosu var; gun rezerve edildi ama adim kaniti yok."""
EVIDENCE_NONE = "yok"
"""Kosu gecmisi okundu; gunun butun kosularinda kayit isi atlandi ya da kosu yok."""
EVIDENCE_UNCLEAR = "belirsiz"
"""Kanit yetersiz: gecmis okunamadi, kayit isi listede yok ya da hala suruyor."""
_EVIDENCE_RANK = {EVIDENCE_NONE: 0, EVIDENCE_UNCLEAR: 1, EVIDENCE_RECORDED: 2, EVIDENCE_STEP: 3}
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

    Ozet yoklugu `baslamadi` kaniti DEGILDIR. Ozeti olmayan gunun durumu
    kosu ve is ust verisinden gelir:

      * kayit adimi gercekten kostu: `eksik (kayit adimi kostu, ozet yok)`;
      * kayit isi atlanmamis kosu var ama adim kaniti yok (kuyruk, kurulum
        ya da iptal): `eksik (kosu var, ozet yok)`. Gun rezerve edildi;
        "basladi" denmez;
      * gecmis okundu, boyle kosu yok: `baslamadi`;
      * gecmis okunamadi, kayit isi suruyor ya da kanit yetersiz:
        `bilinmiyor`.

    Secret'li (Alpaca) ortamda baslamaz.
    """
    from tlab.config import load_config
    from tlab.shadow.core import Comparison
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
        symbols = list(load_config(root).symbols)
        days: list[Day] = []
        results: list[SymbolDay] = []
        fields = set(Comparison.__dataclass_fields__)
        try:
            for path in sorted(days_dir.rglob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("day_schema") != DAY_SCHEMA:
                    raise ValueError("gunluk ozet semasi tanimsiz")
                day = date.fromisoformat(payload["day"])
                if any(known.day == day for known in days):
                    raise ValueError("ayni gunun iki ozeti var")
                days.append(Day(day, payload["status"], payload["reason"]))
                for item in payload.get("symbols", []):
                    comparison = Comparison(**{key: item[key] for key in fields})
                    results.append(
                        SymbolDay(day, comparison.symbol, comparison, bool(item["sip_available"]))
                    )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"FAIL toplam: gunluk ozetler okunamadi ({type(exc).__name__})")
            return 1

        missing = [day for day in planned if not any(known.day == day for known in days)]
        evidence = _evidence_for(env, planned) if missing else {}
        for day in missing:
            found = evidence.get(day, EVIDENCE_UNCLEAR)
            if found == EVIDENCE_STEP:
                days.append(Day(day, DAY_INCOMPLETE, "kayit adimi kostu, ozet yok"))
            elif found == EVIDENCE_RECORDED:
                days.append(Day(day, DAY_INCOMPLETE, "kosu var, ozet yok"))
            elif found == EVIDENCE_NONE:
                days.append(Day(day, DAY_NOT_STARTED, "gozlem baslamadi"))
            else:
                days.append(Day(day, DAY_UNKNOWN, "kanit yetersiz"))
        try:
            summary = summarize(planned, symbols, days, results, Thresholds())
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
    first, last = min(planned), max(planned)
    query = urllib.parse.urlencode(
        {
            "created": f"{(first - timedelta(days=1)).isoformat()}"
            f"..{(last + timedelta(days=1)).isoformat()}",
            "per_page": str(PAGE_SIZE),
        }
    )
    runs = _single_page(
        _api_json(f"{api}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?{query}", token),
        "workflow_runs",
        "kosu listesi",
    )
    evidence = dict.fromkeys(planned, EVIDENCE_NONE)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tlab.shadow_job")
    sub = parser.add_subparsers(dest="step", required=True)
    step_observe = sub.add_parser("observe", help="Gozlem isi (secret'li)")
    step_observe.add_argument("--workdir", type=Path, required=True)
    step_observe.add_argument("--out", type=Path, required=True)
    step_late = sub.add_parser("late", help="Gec kayit isi (secret'siz)")
    step_late.add_argument("--out", type=Path, required=True)
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
        return record_late(os.environ, clock=clock, out=args.out)
    return aggregate(os.environ, days_dir=args.days, out=args.out, root=Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
