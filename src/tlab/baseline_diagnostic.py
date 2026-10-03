"""Baseline kalite teshisi: P&L'SIZ, holdout barsiz, tek seferlik (#17).

Ana olcumun ilk gercek kosusu (run 36474064587) kalite kapisinda durdu:
50 baseline seansinin 10'u uygunsuz; hangi sembol ve gerekce oldugu
bilinmiyor. Bu arac yalnizca o soruyu cevaplar. Sozlesme:
docs/designs/baseline-quality-diagnostic.md; karar kaydi AGENTS §11.2.

Kati sinirlar:

  * KAYNAK KILIDI. Tanim yeni bir spec degil; dondurulmus `TASK` ana
    tanimi hash'iyle kilitler. Kaynak uyusmazligi anahtar okunmadan ve
    SDK kurulmadan; takvim sayimi uyusmazligi bar istenmeden durdurur.
  * HOLDOUT BARI ISTENMEZ. Takvim tamami icin okunur (bolme icin), bar
    istegi yalnizca [ilk baseline acilisi, son baseline kapanisi]. Gelen
    her bar, HICBIR hesaptan once baseline duzenli seans pencerelerine
    gore ayrilir; kapsam disi barlar ve tekrarlari sonucu degistiremez.
  * IKINCI ALGORITMA YOK. Bolme `classify_sessions`/`split_sessions`,
    kalite `assess_quality`, toplama `quality_summary` ile.
  * P&L YOK. Performans katmanlari ice aktarilmaz (mimari test) ve
    calisan CLI onlari yuklemez (smoke testi).
  * HAM VERI DISKE YAZILMAZ. Barlar bellekte olculur. Disari cikan tek
    sey acik alan listeli ozet; atomik yazilir, ustune yazmaz.
  * Log kapali; cikti yalnizca sabit satirlar, hata yalnizca kategori.

Bu bir YENI ERISIMDEKI kalite gozlemidir: eski kosunun manifesti geri
getirilmis degildir, ayni baytlar kanitlanamaz, sonuc 10 cikmak zorunda
degildir. Fiziksel bellek silme garantisi degildir.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tlab.job_io import silenced, write_new
from tlab.sdk_probe import classify

MAIN_SPEC = Path("config/datasets/orb-baseline-2026q3-u11.yaml")
KEY_ENV = (
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_SECRET_KEY",
)
"""Anahtar DEGISKEN ADLARI; degerler kaynak kilidinden SONRA okunur."""


@dataclass(frozen=True)
class DiagnosticTask:
    """Teshisin gorev sozlesmesi - yeni bir veri kumesi tanimi DEGIL."""

    diagnostic_id: str
    source_spec: Path
    source_dataset_id: str
    source_spec_sha256: str
    """`sha256(canonical_json(spec.model_dump(mode="json")))` - manifestteki
    `spec_sha256` ile ayni anlam."""
    failed_run_id: int
    failed_head: str
    failed_manifest_prefix: str
    """Eski kosunun manifest hash ONEKI; yalnizca kayit, eslesme iddiasi yok."""
    expected_sessions: Mapping[str, int] = field(default_factory=dict)


TASK = DiagnosticTask(
    diagnostic_id="diag-orb-baseline-2026q3-u11-quality-1",
    source_spec=MAIN_SPEC,
    source_dataset_id="orb-baseline-2026q3-u11",
    source_spec_sha256="369f4e7fc94267583bf848fc4b983915525ac461c0fae5725b79e72c027dc505",
    failed_run_id=36474064587,
    failed_head="c6c19dba93699de580b7ff6f12e04d224eb56048",
    failed_manifest_prefix="faffa591bba1",
    expected_sessions={"calendar": 63, "complete": 63, "baseline": 50, "holdout": 13},
)
"""SABIT. Workflow girdi almaz; `main()` bu gorevi calistirir."""

SUMMARY_SCHEMA = 1
KIND = "baseline-quality-diagnostic"

SUMMARY_KEYS = frozenset(
    {
        "schema",
        "kind",
        "diagnostic_id",
        "source",
        "producer",
        "feed",
        "timeframe",
        "adjustment",
        "policy",
        "sessions",
        "symbols",
        "ineligible_symbol_sessions",
        "reason_counts",
        "symbols_per_ineligible_session",
        "verdict",
        "notes",
    }
)
SOURCE_KEYS = frozenset(
    {
        "dataset_id",
        "spec_sha256",
        "failed_run_id",
        "failed_head",
        "failed_manifest_prefix",
    }
)
PRODUCER_KEYS = frozenset({"run_id", "workflow", "commit"})
SESSION_KEYS = frozenset(
    {"calendar", "complete", "baseline", "holdout", "baseline_eligible", "baseline_ineligible"}
)
SYMBOL_KEYS = frozenset(
    {
        "sessions_with_bars",
        "sessions_without_bars",
        "missing_fraction",
        "sessions_open_window_incomplete",
        "max_missing_open_window",
        "sessions_without_close_bar",
        "sessions_missing_fraction_above_limit",
        "duplicate_timestamps",
        "ineligible_sessions",
        "reason_counts",
    }
)
POLICY_KEYS = frozenset(
    {
        "open_window_minutes",
        "max_missing_open_window",
        "close_window_minutes",
        "max_missing_fraction",
        "max_ineligible_sessions",
    }
)

NOTES = (
    "Yalnizca BASELINE seanslari. Holdout icin yalnizca seans sayisi.",
    "Sembol ve gerekce toplamlari ortusur: bir seansta birden cok sembol, "
    "bir sembol-seansta birden cok gerekce olabilir. Toplanarak uygunsuz "
    "seans birlesimi aciklanmaz.",
    "sessions_missing_fraction_above_limit bir OLCUdur (bar olmayan seansta "
    "oran 1); reason_counts.eksik_dakika_orani bir GEREKCE sayimidir.",
    "symbols_per_ineligible_session yayginligi gosterir; tek basina feed "
    "arizasi ya da kok neden kaniti degildir.",
    "Yeni bir erisimdeki kalite gozlemidir: eski kosunun manifesti geri "
    "getirilmedi, ayni baytlar kanitlanamaz, saglayici ya da takvim "
    "revizyonu mumkundur; uygunsuz seans sayisinin eskisiyle ayni cikmasi "
    "garanti degildir.",
)


def _producer(env: Mapping[str, str]) -> dict[str, str]:
    from tlab.journal.writer import current_git_sha

    return {
        "run_id": env.get("GITHUB_RUN_ID", "local"),
        "workflow": env.get("GITHUB_WORKFLOW", "local"),
        "commit": env.get("GITHUB_SHA") or current_git_sha(Path.cwd()) or "unknown",
    }


def run(
    env: Mapping[str, str],
    now: datetime,
    *,
    out: Path,
    task: DiagnosticTask = TASK,
    base_url: str | None = None,
) -> int:
    """Teshisi calistirir; ozet YALNIZCA tam basarida yazilir.

    `task` ve `base_url` YALNIZCA testler icin: `main()` ikisini de
    gecirmez. `env` kaynak kilidinden SONRA okunur.
    """
    with silenced():
        return _run(env, now, out=Path(out), task=task, base_url=base_url)


def _run(
    env: Mapping[str, str],
    now: datetime,
    *,
    out: Path,
    task: DiagnosticTask,
    base_url: str | None,
) -> int:
    # 1) Kaynak kilidi: anahtar, SDK ve cikti dosyasindan ONCE.
    locked = lock_source(task.source_spec, task.source_dataset_id, task.source_spec_sha256)
    if locked is None:
        return 1
    spec, spec_sha = locked
    keys = read_keys(env, now, out)
    if keys is None:
        return 1
    key, secret = keys
    return _diagnose(key, secret, now, spec, spec_sha, env, out=out, task=task, base_url=base_url)


# --------------------------------------------------------------------------
# Ortak adimlar - IEX teshisi ve feed karsilastirmasi (#17, AGENTS §11.3)
#
# Ortaklastirma DAR: kilitler, istemci, takvim/bolme, baseline bar toplama
# ve kalite toplamasi. Gorev kimligi, alan listesi, notlar ve hata metni
# sinifi her aracin kendisinde kalir.
# --------------------------------------------------------------------------


def lock_source(path: Path, dataset_id: str, spec_sha256: str) -> tuple[Any, str] | None:
    """Kaynak kilidi. Uyusmazlikta sabit FAIL satirini basar ve None doner.

    Anahtar, SDK ve cikti dosyasindan ONCE cagrilir.
    """
    from tlab.data.dataset import DatasetSpec, canonical_json

    try:
        spec = DatasetSpec.from_yaml(path)
    except Exception as exc:
        print(f"FAIL kaynak: tanim okunamadi ({type(exc).__name__})")
        return None
    spec_sha = hashlib.sha256(canonical_json(spec.model_dump(mode="json"))).hexdigest()
    if spec.dataset_id != dataset_id:
        print("FAIL kaynak: dataset_id gorevle uyusmuyor")
        return None
    if spec_sha != spec_sha256:
        print(f"FAIL kaynak: tanim hash'i gorevle uyusmuyor ({spec_sha[:12]})")
        return None
    if spec.status != "approved":
        print(f"FAIL kaynak: tanim '{spec.status}', teshis yalnizca 'approved' kaynagi okur")
        return None
    return spec, spec_sha


def read_keys(env: Mapping[str, str], now: datetime, out: Path) -> tuple[str, str] | None:
    """Cikti yolu, anahtarlar ve saat. Kaynak kilidinden SONRA cagrilir."""
    if os.path.lexists(out):
        print("FAIL yapilandirma: ozet yolu zaten var; dokunulmadi")
        return None
    key, secret = (env.get(name, "").strip() for name in KEY_ENV)
    if not key or not secret:
        print("FAIL yapilandirma: paper anahtar ve secret gerekli")
        return None
    if any(not 33 <= ord(char) <= 126 for value in (key, secret) for char in value):
        print("FAIL yapilandirma: anahtar gecersiz karakter iceriyor")
        return None
    if now.tzinfo is None or now.utcoffset() is None:
        print("FAIL yapilandirma: zaman dilimi gerekli")
        return None
    return key, secret


def open_clients(
    key: str, secret: str, spec: Any, *, feed: str, base_url: str | None
) -> tuple[Any, Any] | None:
    """Paper broker (takvim) ve `feed` ile bar istemcisi."""
    from tlab.data.market import AlpacaMarketData
    from tlab.execution.alpaca_broker import AlpacaBroker
    from tlab.sdk_compat import bound_transport

    try:
        # paper=True SABIT: bu arac canli hesaba hicbir kosulda baglanmaz.
        broker = AlpacaBroker(key, secret, paper=True, base_url=base_url)
        market = AlpacaMarketData(
            key, secret, feed=feed, adjustment=spec.adjustment, base_url=base_url
        )
        for client in (broker._client, market._client):
            bound_transport(client)
    except Exception as exc:
        print(f"FAIL istemci kurulumu: {classify(exc)} ({type(exc).__name__})")
        return None
    return broker, market


def baseline_sessions(
    broker: Any, spec: Any, now: datetime, expected: Mapping[str, int]
) -> tuple[dict[str, int], list[Any]] | None:
    """Takvim (tamami), mevcut bolme ve sayim kilidi. Bar ISTENMEZ."""
    from tlab.data.dataset import classify_sessions, split_sessions

    try:
        sessions = broker.get_calendar(
            spec.start, spec.end, exchange_timezone=spec.exchange_timezone
        )
    except Exception as exc:
        print(f"FAIL takvim: {classify(exc)} ({type(exc).__name__})")
        return None
    verdicts = classify_sessions(sessions, downloaded_at=now, settle_minutes=spec.settle_minutes)
    complete = [item.session for item in verdicts if item.complete]
    try:
        baseline, holdout = split_sessions(complete, spec.holdout_fraction)
    except Exception as exc:
        print(f"FAIL bolme: bolunemedi ({type(exc).__name__})")
        return None
    counts = {
        "calendar": len(sessions),
        "complete": len(complete),
        "baseline": len(baseline),
        "holdout": len(holdout),
    }
    if counts != dict(expected):
        found = ", ".join(f"{name} {value}" for name, value in counts.items())
        print(f"FAIL bolme: seans sayimlari gorevle uyusmuyor ({found}); bar istenmedi")
        return None
    return counts, baseline


BarFailure = Callable[[BaseException, int, int], str]
"""(istisna, sembol sirasi 0'dan, sembol sayisi) -> basilacak sabit satir."""


def download_failure(error: BaseException, _index: int, _total: int) -> str:
    """IEX teshisinin bar hatasi satiri - degismedi."""
    return f"FAIL indirme: {classify(error)} ({type(error).__name__})"


def baseline_stamps(
    market: Any, spec: Any, baseline: list[Any], *, on_error: BarFailure = download_failure
) -> tuple[dict[str, list[datetime]], dict[str, int]] | None:
    """Yalnizca baseline araligi istenir; gelen her bar HICBIR hesaptan
    once baseline duzenli seans pencerelerine gore ayrilir.

    Bir sembolde hata olursa sabit satir basilir ve None doner: eksik
    sembollu bir ozet hic kurulmaz.
    """
    start, end = baseline[0].open, baseline[-1].close
    zone = ZoneInfo(spec.exchange_timezone)
    windows = {item.day: item for item in baseline}
    stamps_by_symbol: dict[str, list[datetime]] = {}
    duplicates: dict[str, int] = {}
    symbols = list(spec.symbols)
    for index, symbol in enumerate(symbols):
        try:
            bars = market.bars(symbol, spec.timeframe, start=start, end=end)
        except Exception as exc:
            print(on_error(exc, index, len(symbols)))
            return None
        kept: list[datetime] = []
        for bar in bars:
            window = windows.get(_local_day(bar.ts, zone))
            if window is not None and window.open <= bar.ts < window.close:
                kept.append(bar.ts)
        del bars
        unique = set(kept)
        duplicates[symbol] = len(kept) - len(unique)
        stamps_by_symbol[symbol] = sorted(unique)
    return stamps_by_symbol, duplicates


def quality_fields(
    spec: Any,
    baseline: list[Any],
    stamps_by_symbol: dict[str, list[datetime]],
    duplicates: dict[str, int],
) -> dict[str, Any]:
    """Kalite alanlari, acik alan listesiyle. Manifest ya da olcu sozlugu
    AKTARILMAZ. Sayim anlamlari birbirini dogrulamali; tutmazsa hata."""
    from tlab.data.dataset import assess_quality
    from tlab.data.quality_summary import CATEGORIES, ineligible_symbol_counts, summarize_symbols

    categories = CATEGORIES
    policy = spec.quality
    per_session = assess_quality(
        baseline, stamps_by_symbol, policy=policy, timeframe=spec.timeframe
    )
    stats = summarize_symbols(
        per_session,
        baseline,
        list(spec.symbols),
        max_missing_fraction=policy.max_missing_fraction,
    )
    per_ineligible = ineligible_symbol_counts(per_session, baseline)

    symbols: dict[str, dict[str, Any]] = {}
    reasons: Counter[str] = Counter(dict.fromkeys(categories, 0))
    for symbol, item in stats.items():
        reasons.update(item.reason_counts)
        symbols[symbol] = {
            "sessions_with_bars": item.sessions_with_bars,
            "sessions_without_bars": item.sessions_without_bars,
            "missing_fraction": item.missing_fraction,
            "sessions_open_window_incomplete": item.sessions_open_window_incomplete,
            "max_missing_open_window": item.max_missing_open_window,
            "sessions_without_close_bar": item.sessions_without_close_bar,
            "sessions_missing_fraction_above_limit": item.sessions_missing_fraction_above_limit,
            "duplicate_timestamps": duplicates[symbol],
            "ineligible_sessions": item.ineligible_sessions,
            "reason_counts": {category: item.reason_counts[category] for category in categories},
        }

    histogram = {
        str(width): per_ineligible.count(width) for width in range(1, len(spec.symbols) + 1)
    }
    ineligible_union = len(per_ineligible)
    weighted = sum(per_ineligible)
    # Tutarlilik: sayim anlamlari birbirini dogrulamali; tutmazsa ozet yok.
    if sum(histogram.values()) != ineligible_union:
        msg = "histogram toplami uygunsuz seans birlesimine esit degil"
        raise ValueError(msg)
    if sum(item["ineligible_sessions"] for item in symbols.values()) != weighted:
        msg = "sembol toplami agirlikli histogram toplamina esit degil"
        raise ValueError(msg)

    return {
        "policy": {key: getattr(policy, key) for key in sorted(POLICY_KEYS)},
        "baseline_ineligible": ineligible_union,
        "symbols": symbols,
        "ineligible_symbol_sessions": weighted,
        "reason_counts": {category: reasons[category] for category in categories},
        "symbols_per_ineligible_session": histogram,
    }


def write_summary(out: Path, summary: dict[str, Any]) -> bool:
    """Atomik, ustune yazmaz. Hata satirini basar ve False doner."""
    payload = (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        write_new(out, payload)
    except FileExistsError:
        print("FAIL yapilandirma: ozet yolu zaten var; dokunulmadi")
        return False
    except Exception as exc:
        print(f"FAIL ozet yazimi ({type(exc).__name__})")
        return False
    return True


def print_quality(summary: dict[str, Any]) -> None:
    """Seans, sembol ve yayginlik satirlari - iki aracta ayni bicim."""
    sessions = summary["sessions"]
    print(
        f"seans: takvim {sessions['calendar']}, tamamlanmis {sessions['complete']}, "
        f"baseline {sessions['baseline']}, holdout {sessions['holdout']}"
    )
    print(
        f"baseline: uygun {sessions['baseline_eligible']}, "
        f"uygunsuz {sessions['baseline_ineligible']} (seans birlesimi); "
        f"uygunsuz sembol-seans {summary['ineligible_symbol_sessions']}"
    )
    for symbol, stats in summary["symbols"].items():
        reasons = stats["reason_counts"]
        fraction = stats["missing_fraction"]
        shown = "-" if fraction is None else f"{fraction:.2%}"
        print(
            f"  {symbol:<6} uygunsuz {stats['ineligible_sessions']:>2} | gerekce: "
            f"bar yok {reasons['seans_ici_bar_yok']}, "
            f"acilis {reasons['acilis_penceresi_eksik']}, "
            f"kapanis {reasons['kapanis_penceresinde_bar_yok']}, "
            f"oran {reasons['eksik_dakika_orani']}, "
            f"diger {reasons['diger']} | eksik {shown}, "
            f"tekrar {stats['duplicate_timestamps']}"
        )
    spread = ", ".join(
        f"{width} sembol: {count}"
        for width, count in summary["symbols_per_ineligible_session"].items()
        if count
    )
    print(f"yayginlik (uygunsuz seans basina uygunsuz sembol): {spread or 'yok'}")
    print("not: sembol ve gerekce toplamlari ortusur; toplanarak seans birlesimi aciklanmaz")


# --------------------------------------------------------------------------
# IEX teshisi
# --------------------------------------------------------------------------


def _diagnose(
    key: str,
    secret: str,
    now: datetime,
    spec: Any,
    spec_sha: str,
    env: Mapping[str, str],
    *,
    out: Path,
    task: DiagnosticTask,
    base_url: str | None,
) -> int:
    clients = open_clients(key, secret, spec, feed=spec.feed, base_url=base_url)
    if clients is None:
        return 1
    broker, market = clients

    # 2) Takvim (tamami) ve bolme - mevcut fonksiyonlarla. Bar YOK.
    split = baseline_sessions(broker, spec, now, task.expected_sessions)
    if split is None:
        return 1
    counts, baseline = split

    # 3) Yalnizca baseline araligi; kapsam disi barlar hesaptan once ayrilir.
    fetched = baseline_stamps(market, spec, baseline)
    if fetched is None:
        return 1
    stamps_by_symbol, duplicates = fetched

    try:
        summary = _summary(
            spec, spec_sha, counts, baseline, stamps_by_symbol, duplicates, env, task=task
        )
        json.dumps(summary)
    except Exception as exc:
        print(f"FAIL ozet: {type(exc).__name__}")
        return 1
    if not write_summary(out, summary):
        return 1

    _print_summary(summary)
    return 0


def _local_day(moment: datetime, zone: ZoneInfo) -> date:
    return moment.astimezone(zone).date()


def _summary(
    spec: Any,
    spec_sha: str,
    counts: dict[str, int],
    baseline: list[Any],
    stamps_by_symbol: dict[str, list[datetime]],
    duplicates: dict[str, int],
    env: Mapping[str, str],
    *,
    task: DiagnosticTask,
) -> dict[str, Any]:
    """Acik alan listesiyle ozet. Manifest ya da olcu sozlugu AKTARILMAZ."""
    quality = quality_fields(spec, baseline, stamps_by_symbol, duplicates)
    ineligible_union = quality["baseline_ineligible"]
    producer = _producer(env)
    return {
        "schema": SUMMARY_SCHEMA,
        "kind": KIND,
        "diagnostic_id": task.diagnostic_id,
        "source": {
            "dataset_id": task.source_dataset_id,
            "spec_sha256": spec_sha,
            "failed_run_id": task.failed_run_id,
            "failed_head": task.failed_head,
            "failed_manifest_prefix": task.failed_manifest_prefix,
        },
        "producer": {key: str(producer.get(key, "")) for key in sorted(PRODUCER_KEYS)},
        "feed": spec.feed,
        "timeframe": spec.timeframe.value,
        "adjustment": spec.adjustment,
        "policy": quality["policy"],
        "sessions": {
            **counts,
            "baseline_eligible": len(baseline) - ineligible_union,
            "baseline_ineligible": ineligible_union,
        },
        "symbols": quality["symbols"],
        "ineligible_symbol_sessions": quality["ineligible_symbol_sessions"],
        "reason_counts": quality["reason_counts"],
        "symbols_per_ineligible_session": quality["symbols_per_ineligible_session"],
        "verdict": "all_eligible" if ineligible_union == 0 else "some_ineligible",
        "notes": list(NOTES),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"OK teshis {summary['diagnostic_id']} (kaynak {summary['source']['dataset_id']})")
    print_quality(summary)
    print(f"sonuc: {summary['verdict']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tlab.baseline_diagnostic")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Duvar saati bilincli ve karar yolu disi: erisim ani (bolme icin).
    return run(os.environ, datetime.now(UTC), out=args.out)


if __name__ == "__main__":
    raise SystemExit(main())
