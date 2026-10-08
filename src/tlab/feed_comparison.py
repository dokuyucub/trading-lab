"""Tarihsel SIP kalite karsilastirmasi: P&L'SIZ, holdout barsiz, tek seferlik (#17).

DURUM (2026-10-08): kaynak tanim aktif tanimlardan cikarildi (AGENTS
§11.4). Arac depo dizininde kaynak kilidinde, anahtar ve SDK'dan ONCE
durur; tekrar kosulmaz. Tanimin bayt-bayt kopyasi
tests/fixtures/closed_datasets/ altinda (regresyon testleri onu kullanir).

IEX ana olcum denemesi kalite kapisinda kapatildi (AGENTS §7, §11.2):
50 baseline seansinin 10'u uygunsuz, hepsi AMD. Bu arac iki soruyu
cevaplar, AYNI 11 sembol, AYNI baseline kapsami ve AYNI kalite
politikasiyla:

  (a) bu hesap tarihsel SIP 1Min bari alabiliyor mu;
  (b) SIP verisi bu politikayi geciyor mu.

Sozlesme: docs/designs/baseline-feed-comparison.md; karar kaydi AGENTS
§11.3. Yeni bir veri kumesi DEGIL: `config/datasets/` degismez, manifest
uretilmez, ham veri diske yazilmaz, P&L yok.

Kati sinirlar (IEX teshisiyle ayni adimlar - `baseline_diagnostic`):

  * KAYNAK KILIDI. Sabit `SIP_TASK` ana tanimi hash'iyle ve tanimdaki
    feed'le kilitler; anahtar okunmadan ve SDK kurulmadan. Takvim sayim
    kilidi bar isteginden once.
  * FEED OVERRIDE ACIK. SIP tanim dosyasinda degil, gorevde yazili.
    Kaynak hash'i override'i KAPSAMAZ; provenance = kaynak hash'i +
    gorevdeki override, birlikte. Bu gorev HIC IEX istegi yapmaz; SIP
    reddedilirse IEX'e ya da baska bir feed'e donulmez.
  * HOLDOUT BARI ISTENMEZ. Bar istegi yalnizca baseline araligi; gelen
    her bar hesaptan once baseline seans pencerelerine gore ayrilir.
  * ERISIM KAPISI. Bar isteginde HTTP 401/403 -> `FAIL erisim` ve dur.
    Kesin neden belirlenmez (yanit metni basilmaz); basarili paper
    takvimi, 403'un SIP aboneliginden oldugunu KANITLAMAZ. 200 ama bos
    yanit erisim reddi sayilmaz: kalite olcusudur.
  * TAM SONUC YA DA HIC. 11 sembolun hepsi yanitlanmadan ozet yazilmaz;
    kismi sembol sonucu yayimlanmaz.
  * Yeni dongu ya da otomatik tekrar YOK: SDK'nin mevcut sinirli HTTP
    tekrari disinda her basarisizlik bir olaydir; yeniden kosu ayri
    karardir (AGENTS §11.3).
  * Log kapali; cikti yalnizca sabit satirlar, hata yalnizca kategori.

IEX referansiyla karsilastirma ARACTA DEGIL, incelemede yapilir: iki
gozlem farkli erisim zamanlarina aittir; es zamanli degil, neden kaniti
degil. Fiziksel bellek silme garantisi degildir.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tlab.baseline_diagnostic import (
    MAIN_SPEC,
    PRODUCER_KEYS,
    baseline_sessions,
    baseline_stamps,
    lock_source,
    open_clients,
    print_quality,
    quality_fields,
    read_keys,
    write_summary,
)
from tlab.baseline_diagnostic import POLICY_KEYS as POLICY_KEYS
from tlab.baseline_diagnostic import SESSION_KEYS as SESSION_KEYS
from tlab.baseline_diagnostic import SYMBOL_KEYS as SYMBOL_KEYS
from tlab.job_io import silenced
from tlab.sdk_probe import classify


@dataclass(frozen=True)
class FeedComparisonTask:
    """Feed karsilastirmasinin gorev sozlesmesi - veri kumesi tanimi DEGIL."""

    comparison_id: str
    source_spec: Path
    source_dataset_id: str
    source_spec_sha256: str
    source_feed: str
    """Kaynak tanimdaki feed; kilit bunu da denetler."""
    feed: str
    """Gorev duzeyinde istenen feed (acik override)."""
    reference: Mapping[str, Any] = field(default_factory=dict)
    """Karsilastirilacak IEX teshisi. YALNIZCA kayit: arac ona erismez."""
    expected_sessions: Mapping[str, int] = field(default_factory=dict)


SIP_TASK = FeedComparisonTask(
    comparison_id="feedcmp-orb-baseline-2026q3-u11-sip-1",
    source_spec=MAIN_SPEC,
    source_dataset_id="orb-baseline-2026q3-u11",
    source_spec_sha256="369f4e7fc94267583bf848fc4b983915525ac461c0fae5725b79e72c027dc505",
    source_feed="iex",
    feed="sip",
    reference={
        "diagnostic_id": "diag-orb-baseline-2026q3-u11-quality-1",
        "run_id": 36502365666,
        "artifact_id": 11004953510,
        "artifact_zip_sha256": "5ae3e3e0ab21e3a3bb70d3b6cfe7fadebe506c90f4b200c863fb43711dd7ea98",
    },
    expected_sessions={"calendar": 63, "complete": 63, "baseline": 50, "holdout": 13},
)
"""SABIT. Workflow girdi almaz; `main()` bu gorevi calistirir."""

SUMMARY_SCHEMA = 1
KIND = "baseline-feed-comparison"

SUMMARY_KEYS = frozenset(
    {
        "schema",
        "kind",
        "comparison_id",
        "source",
        "feed_override",
        "reference",
        "producer",
        "feed",
        "timeframe",
        "adjustment",
        "policy",
        "sessions",
        "access",
        "symbols",
        "ineligible_symbol_sessions",
        "reason_counts",
        "symbols_per_ineligible_session",
        "verdict",
        "notes",
    }
)
SOURCE_KEYS = frozenset({"dataset_id", "spec_sha256", "spec_feed"})
FEED_OVERRIDE_KEYS = frozenset({"source_feed", "feed"})
REFERENCE_KEYS = frozenset({"diagnostic_id", "run_id", "artifact_id", "artifact_zip_sha256"})
ACCESS_KEYS = frozenset({"symbols_requested", "symbols_answered", "symbols_with_baseline_bars"})

NOTES = (
    "Feed karsilastirmasi: kaynak tanimin feed'i source.spec_feed; bu gorev "
    "feed_override.feed ister. Override tanim dosyasinda degil gorevdedir; "
    "kaynak hash'i override'i kapsamaz. Provenance: kaynak hash'i ve "
    "gorevdeki override birlikte.",
    "Yalnizca BASELINE seanslari. Holdout icin yalnizca seans sayisi; "
    "holdout bari hicbir feed'den istenmedi.",
    "Bu ozet ile reference'taki IEX teshisi FARKLI erisim zamanlarina "
    "aittir: es zamanli degil, neden kaniti degil; saglayici revizyonu "
    "mumkun.",
    "access yalnizca alinan yanitlari soyler. 200 ama bos yanit erisim "
    "reddi sayilmaz; kullanilabilir bar da dogrulamaz.",
    "Kalite kapsami veri tamligi olcusudur; islem, dolum ya da P&L anlami "
    "tasimaz. Tarihsel SIP erisimi canli IEX/SIP esdegerligini ya da "
    "canliya hazirligi gostermez; abonelik karari degildir.",
    "Sembol ve gerekce toplamlari ortusur: bir seansta birden cok sembol, "
    "bir sembol-seansta birden cok gerekce olabilir. Toplanarak uygunsuz "
    "seans birlesimi aciklanmaz.",
    "sessions_missing_fraction_above_limit bir OLCUdur (bar olmayan seansta "
    "oran 1); reason_counts.eksik_dakika_orani bir GEREKCE sayimidir.",
    "symbols_per_ineligible_session yayginligi gosterir; tek basina feed "
    "arizasi ya da kok neden kaniti degildir.",
)

ACCESS_DENIED = (401, 403)


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
    task: FeedComparisonTask = SIP_TASK,
    base_url: str | None = None,
) -> int:
    """Karsilastirmayi calistirir; ozet YALNIZCA tam basarida yazilir.

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
    task: FeedComparisonTask,
    base_url: str | None,
) -> int:
    # 1) Kaynak kilidi (kimlik, hash, approved) + tanimdaki feed.
    locked = lock_source(task.source_spec, task.source_dataset_id, task.source_spec_sha256)
    if locked is None:
        return 1
    spec, spec_sha = locked
    if spec.feed != task.source_feed:
        print("FAIL kaynak: tanimin feed'i gorevle uyusmuyor")
        return 1
    if task.feed == task.source_feed:
        print("FAIL kaynak: override kaynak feed'iyle ayni; karsilastirma degil")
        return 1
    keys = read_keys(env, now, out)
    if keys is None:
        return 1
    key, secret = keys

    clients = open_clients(key, secret, spec, feed=task.feed, base_url=base_url)
    if clients is None:
        return 1
    broker, market = clients

    # 2) Takvim ve bolme; sayim kilidi. Bar YOK.
    split = baseline_sessions(broker, spec, now, task.expected_sessions)
    if split is None:
        return 1
    counts, baseline = split

    # 3) Yalnizca baseline araligi, yalnizca gorevin feed'i.
    def bar_failure(error: BaseException, index: int, total: int) -> str:
        from tlab.sdk_compat import http_status_of

        where = f"sembol {index + 1}/{total}"
        status = http_status_of(error)
        if status in ACCESS_DENIED:
            return (
                f"FAIL erisim: {task.feed} tarihsel bar istegi reddedildi "
                f"(HTTP {status}), {where}; kesin neden belirlenmedi; "
                "baska feed'e donulmedi"
            )
        return f"FAIL indirme: {classify(error)} ({type(error).__name__}), {where}"

    fetched = baseline_stamps(market, spec, baseline, on_error=bar_failure)
    if fetched is None:
        return 1
    stamps_by_symbol, duplicates = fetched

    try:
        summary = _summary(
            spec, spec_sha, counts, baseline, stamps_by_symbol, duplicates, env, task=task
        )
    except Exception as exc:
        print(f"FAIL ozet: {type(exc).__name__}")
        return 1
    if not write_summary(out, summary):
        return 1

    _print_summary(summary)
    return 0


def _summary(
    spec: Any,
    spec_sha: str,
    counts: dict[str, int],
    baseline: list[Any],
    stamps_by_symbol: dict[str, list[datetime]],
    duplicates: dict[str, int],
    env: Mapping[str, str],
    *,
    task: FeedComparisonTask,
) -> dict[str, Any]:
    """Acik alan listesiyle ozet. Manifest ya da olcu sozlugu AKTARILMAZ."""
    quality = quality_fields(spec, baseline, stamps_by_symbol, duplicates)
    ineligible_union = quality["baseline_ineligible"]
    producer = _producer(env)
    requested = len(spec.symbols)
    return {
        "schema": SUMMARY_SCHEMA,
        "kind": KIND,
        "comparison_id": task.comparison_id,
        "source": {
            "dataset_id": task.source_dataset_id,
            "spec_sha256": spec_sha,
            "spec_feed": spec.feed,
        },
        "feed_override": {"source_feed": task.source_feed, "feed": task.feed},
        "reference": {key: task.reference[key] for key in sorted(REFERENCE_KEYS)},
        "producer": {key: str(producer.get(key, "")) for key in sorted(PRODUCER_KEYS)},
        "feed": task.feed,
        "timeframe": spec.timeframe.value,
        "adjustment": spec.adjustment,
        "policy": quality["policy"],
        "sessions": {
            **counts,
            "baseline_eligible": len(baseline) - ineligible_union,
            "baseline_ineligible": ineligible_union,
        },
        # Ozet yalnizca her sembol yanitlandiysa kurulur.
        "access": {
            "symbols_requested": requested,
            "symbols_answered": len(stamps_by_symbol),
            "symbols_with_baseline_bars": sum(1 for stamps in stamps_by_symbol.values() if stamps),
        },
        "symbols": quality["symbols"],
        "ineligible_symbol_sessions": quality["ineligible_symbol_sessions"],
        "reason_counts": quality["reason_counts"],
        "symbols_per_ineligible_session": quality["symbols_per_ineligible_session"],
        "verdict": "all_eligible" if ineligible_union == 0 else "some_ineligible",
        "notes": list(NOTES),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    override = summary["feed_override"]
    print(
        f"OK karsilastirma {summary['comparison_id']} (kaynak "
        f"{summary['source']['dataset_id']}; feed {override['source_feed']} -> "
        f"{override['feed']}, gorev duzeyinde)"
    )
    access = summary["access"]
    print(
        f"erisim: {access['symbols_answered']}/{access['symbols_requested']} sembol "
        f"yanit aldi; baseline bari gelen sembol "
        f"{access['symbols_with_baseline_bars']}/{access['symbols_requested']}"
    )
    if access["symbols_with_baseline_bars"] == 0:
        print("not: hic baseline bari gelmedi; kullanilabilir bar DOGRULANMADI")
    print_quality(summary)
    print("not: referans IEX teshisiyle farkli erisim zamani; karsilastirma incelemede")
    print(f"sonuc: {summary['verdict']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tlab.feed_comparison")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Duvar saati bilincli ve karar yolu disi: erisim ani (bolme icin).
    return run(os.environ, datetime.now(UTC), out=args.out)


if __name__ == "__main__":
    raise SystemExit(main())
