"""Pilot veri kalitesi: gercek Alpaca verisini indirir, OLCER ve siler.

AGENTS §11 / #25. Bu arac bir soruya cevap verir: ucretsiz IEX
verisi, ana olcumun kalite politikasini karsilayacak kadar tam mi?
Esikler bu olcume bakilarak - ve P&L gorulmeden - sabitlenecek.

Dort kati kural:

  * P&L YOK. Yalnizca `status: pilot` bir tanimla calisir; strateji,
    backtest veya ogrenme katmanini ice aktarmaz (mimari test).
  * HAM VERI DISARI CIKMAZ. Barlar gecici bir dizine yazilir ve arac
    biterken - basari ya da hata - silinir. Disari cikan tek sey,
    ACIK BIR ALAN LISTESINDEN kurulan toplulastirilmis kalite ozetidir:
    fiyat, hacim, VWAP, islem sayisi, hesap degeri yoktur.
  * HATA METNI DISARI CIKMAZ. Istisna metni SDK'nin yanit govdesini
    tasiyabilir; cikti yalnizca sabit tani metni ve istisna SINIF
    adidir (`sdk_probe.classify`, metne degil tipe bakar).
  * LOG KAPALI. Arac boyunca `logging` kapatilir (`job_io.silenced`)
    ve cikista cagiranin ayari geri gelir; ana olcum ve teshis
    araclariyla ayni. Bu, dogrulanmis bir sizintinin duzeltmesi DEGIL:
    kaynagina bakilan yolda (tlab.data, alpaca-py REST istemcisi,
    urllib3/requests - son ikisi kendi NullHandler'larini takar) bilinen
    bir sizinti yok. Guvence, ileride bir log yapilandirmasi ya da
    bagimlilik degisikligi olsa da cikti siniri ayni kalsin diye YAPISAL.
    (urllib3 bozuk yanit basliginda tam istek adresini - tarih ve
    sembol - WARNING'de loglar; test bunu yapilandirilmis logla dener.)

Silme, depolama ortaminda adli olarak geri getirilemez silme iddiasi
DEGILDIR (#25 sart 6).

`tlab dataset build` bu is icin KULLANILMAZ: SDK istisna metnini
hata mesajina koyar ve CLI onu oldugu gibi basar - yerelde dogru,
herkesin okuyabildigi bir kosu kaydinda degil.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tlab.core.calendar import TradingSession
from tlab.data.quality_summary import summarize_symbols
from tlab.job_io import silenced
from tlab.sdk_probe import classify

if TYPE_CHECKING:
    from tlab.data.dataset import DatasetSpec

PILOT_SPEC = Path("config/datasets/pilot-2026-05-u12.yaml")
"""SABIT. Workflow'dan serbest sembol, tarih ya da yol alinmaz (#25 sart 1).

Ilk pilot `pilot-2026-06-u12` bir kez olculdu (kosu 36369564690); tanimi
kayit olarak depoda kalir. Bu, ayni politikayla ek pilottur (#17)."""

SUMMARY_SCHEMA = 1

SUMMARY_KEYS = frozenset(
    {
        "schema",
        "kind",
        "dataset_id",
        "status",
        "spec_sha256",
        "manifest_sha256",
        "producer",
        "feed",
        "timeframe",
        "adjustment",
        "policy",
        "sessions",
        "symbols",
        "reasons",
        "verdict",
    }
)
"""Ozetin EN UST alanlari. Burada olmayan hicbir alan ozete giremez;
`test_pilot_quality` kumeyi birebir sabitliyor."""

SESSION_KEYS = frozenset({"calendar", "complete", "incomplete", "eligible", "ineligible"})

SYMBOL_KEYS = frozenset(
    {
        "sessions_with_bars",
        "sessions_without_bars",
        "missing_minutes",
        "expected_minutes",
        "missing_fraction",
        "sessions_open_window_incomplete",
        "max_missing_open_window",
        "sessions_without_close_bar",
        "duplicate_timestamps",
        "ineligible_sessions",
    }
)

PRODUCER_KEYS = frozenset({"run_id", "workflow", "commit"})

POLICY_KEYS = frozenset(
    {
        "open_window_minutes",
        "max_missing_open_window",
        "close_window_minutes",
        "max_missing_fraction",
        "max_ineligible_sessions",
    }
)
"""Politikadan ozete gecen alanlar - manifest sozlugu OLDUGU GIBI gecmez.
`QualityPolicy`'ye alan eklenirse test bu kumenin bilincli
guncellenmesini ister."""


def pilot_summary(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    """Manifestten toplulastirilmis kalite ozeti - YALNIZCA acik alanlar.

    Her deger ya bir sayim, ya bir oran, ya da tanimin kendisinden
    (spec/politika) gelen bir sabit. Tarih yok: pilot ana kumenin
    tarihlerinden once ve sayimlar soruyu cevapliyor (#17 on rapor).
    """
    quality = manifest["quality"]
    per_session = quality["sessions"]
    hours = manifest["sessions"]["hours"]
    split_days = [*manifest["split"]["baseline"], *manifest["split"]["holdout"]]

    # Kapsam ACIK: pilot bolmenin iki tarafini da olcer (pilot P&L
    # uretemez). Toplama ortak modulde; kapsami burada biz veriyoruz.
    scope = [
        TradingSession(
            day=date.fromisoformat(day),
            open=datetime.fromisoformat(hours[day][0]),
            close=datetime.fromisoformat(hours[day][1]),
        )
        for day in split_days
    ]
    quality_by_symbol = summarize_symbols(
        per_session,
        scope,
        manifest["symbols"],
        max_missing_fraction=float(quality["policy"]["max_missing_fraction"]),
    )
    symbols: dict[str, dict[str, Any]] = {}
    reasons: Counter[str] = Counter()
    for symbol, stats in quality_by_symbol.items():
        reasons.update({key: value for key, value in stats.reason_counts.items() if value})
        symbols[symbol] = {
            "sessions_with_bars": stats.sessions_with_bars,
            "sessions_without_bars": stats.sessions_without_bars,
            "missing_minutes": stats.missing_minutes,
            "expected_minutes": stats.expected_minutes,
            "missing_fraction": stats.missing_fraction,
            "sessions_open_window_incomplete": stats.sessions_open_window_incomplete,
            "max_missing_open_window": stats.max_missing_open_window,
            "sessions_without_close_bar": stats.sessions_without_close_bar,
            "duplicate_timestamps": int(quality["symbols"][symbol]["duplicate_timestamps"]),
            "ineligible_sessions": stats.ineligible_sessions,
        }

    eligible = sum(1 for day in split_days if per_session[day]["eligible"])
    producer = manifest["producer"]
    return {
        "schema": SUMMARY_SCHEMA,
        "kind": "pilot-quality",
        "dataset_id": manifest["dataset_id"],
        "status": manifest["spec"]["status"],
        "spec_sha256": manifest["spec_sha256"],
        "manifest_sha256": manifest_sha256,
        "producer": {key: str(producer.get(key, "")) for key in sorted(PRODUCER_KEYS)},
        "feed": manifest["feed"],
        "timeframe": manifest["timeframe"],
        "adjustment": manifest["adjustment"],
        "policy": {key: quality["policy"][key] for key in sorted(POLICY_KEYS)},
        "sessions": {
            "calendar": manifest["sessions"]["calendar"],
            "complete": len(manifest["sessions"]["complete"]),
            "incomplete": len(manifest["sessions"]["incomplete"]),
            "eligible": eligible,
            "ineligible": len(split_days) - eligible,
        },
        "symbols": symbols,
        "reasons": dict(sorted(reasons.items())),
        "verdict": "all_eligible" if eligible == len(split_days) else "some_ineligible",
    }


def _producer() -> dict[str, str]:
    from tlab.journal.writer import current_git_sha

    return {
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "workflow": os.environ.get("GITHUB_WORKFLOW", "local"),
        "commit": os.environ.get("GITHUB_SHA") or current_git_sha(Path.cwd()) or "unknown",
    }


def _print_summary(summary: dict[str, Any]) -> None:
    sessions = summary["sessions"]
    print(f"OK pilot {summary['dataset_id']} (spec {summary['spec_sha256'][:12]})")
    print(
        f"seans: takvim {sessions['calendar']}, tamamlanmis {sessions['complete']}, "
        f"uygun {sessions['eligible']}, uygunsuz {sessions['ineligible']}"
    )
    for symbol, stats in summary["symbols"].items():
        fraction = stats["missing_fraction"]
        shown = "-" if fraction is None else f"{fraction * 100:.2f}%"
        print(
            f"  {symbol:<6} bar olan seans {stats['sessions_with_bars']}, "
            f"eksik {shown}, acilis eksikli seans {stats['sessions_open_window_incomplete']}, "
            f"kapanis barsiz seans {stats['sessions_without_close_bar']}, "
            f"uygunsuz {stats['ineligible_sessions']}"
        )
    print(f"sonuc: {summary['verdict']}")


def run(
    key: str,
    secret: str,
    now: datetime,
    *,
    workdir: Path,
    out: Path,
    spec_path: Path = PILOT_SPEC,
    base_url: str | None = None,
) -> int:
    """Indir, olc, ozeti yaz, HAM VERIYI SIL. Cikti yalnizca sabit satirlar.

    `spec_path` ve `base_url` YALNIZCA testler icin: `main()` ikisini de
    gecirmez ve ortamdan da okumaz. Arac boyunca `logging` kapalidir.
    """
    with silenced():
        return _run(
            key, secret, now, workdir=workdir, out=out, spec_path=spec_path, base_url=base_url
        )


def _run(
    key: str,
    secret: str,
    now: datetime,
    *,
    workdir: Path,
    out: Path,
    spec_path: Path,
    base_url: str | None,
) -> int:
    key, secret = key.strip(), secret.strip()
    if not key or not secret:
        print("FAIL yapilandirma: paper anahtar ve secret gerekli")
        return 1
    if any(not 33 <= ord(char) <= 126 for value in (key, secret) for char in value):
        print("FAIL yapilandirma: anahtar gecersiz karakter iceriyor")
        return 1
    if now.tzinfo is None or now.utcoffset() is None:
        print("FAIL yapilandirma: zaman dilimi gerekli")
        return 1

    from tlab.data.dataset import DatasetSpec

    try:
        spec = DatasetSpec.from_yaml(spec_path)
    except Exception as exc:
        print(f"FAIL tanim: okunamadi ({type(exc).__name__})")
        return 1
    if spec.status != "pilot":
        # Ag istegi yapilmadan: pilot araci ne taslak ne onayli bir
        # tanimi indirir. Onayli tanimin indirilmesi ayri bir istir.
        print(f"FAIL tanim: status '{spec.status}', yalnizca 'pilot' kabul edilir")
        return 1

    workdir, out = Path(workdir), Path(out)
    if _inside(out, workdir):
        print("FAIL yapilandirma: ozet dosyasi ham veri dizininin icinde olamaz")
        return 1
    # Sahiplik: dizini BU cagri olusturur (ozel mkdir). Onceden var olan
    # bir dizin, dosya ya da symlink reddedilir ve ona DOKUNULMAZ; silme
    # yalnizca bu cagrinin olusturdugu dizini kapsar (Codex #27 P2: eski
    # surum var olan bir dizini reddettikten sonra kosulsuz siliyordu).
    try:
        workdir.parent.mkdir(parents=True, exist_ok=True)
        workdir.mkdir()
    except FileExistsError:
        print("FAIL yapilandirma: calisma dizini zaten var; dokunulmadi")
        return 1
    except OSError as exc:
        print(f"FAIL yapilandirma: calisma dizini olusturulamadi ({type(exc).__name__})")
        return 1

    try:
        return _measure(key, secret, now, spec, workdir=workdir, out=out, base_url=base_url)
    finally:
        # Ham veri basari ya da hata - her durumda - silinir. Yalnizca
        # yukarida bu cagrinin olusturdugu dizin.
        shutil.rmtree(workdir, ignore_errors=True)


def _inside(path: Path, directory: Path) -> bool:
    """`path`, `directory`'nin kendisi ya da altinda mi (symlink cozulerek)."""
    resolved, root = path.resolve(), directory.resolve()
    return resolved == root or root in resolved.parents


def _measure(
    key: str,
    secret: str,
    now: datetime,
    spec: DatasetSpec,
    *,
    workdir: Path,
    out: Path,
    base_url: str | None,
) -> int:
    """Indirme ve olcum. Cagiran `workdir`'in sahibi ve temizleyicisi."""
    from tlab.data.dataset import build_dataset, manifest_sha256
    from tlab.data.market import AlpacaMarketData
    from tlab.execution.alpaca_broker import AlpacaBroker
    from tlab.sdk_compat import bound_transport

    try:
        # paper=True SABIT: bu arac canli hesaba hicbir kosulda baglanmaz.
        broker = AlpacaBroker(key, secret, paper=True, base_url=base_url)
        market = AlpacaMarketData(
            key, secret, feed=spec.feed, adjustment=spec.adjustment, base_url=base_url
        )
        for client in (broker._client, market._client):
            bound_transport(client)
    except Exception as exc:
        print(f"FAIL istemci kurulumu: {classify(exc)} ({type(exc).__name__})")
        return 1

    class _Calendar:
        def get_calendar(self, start: date, end: date) -> Any:
            return broker.get_calendar(start, end, exchange_timezone=spec.exchange_timezone)

    try:
        manifest = build_dataset(
            spec,
            bars_source=market,
            calendar_source=_Calendar(),
            out_dir=workdir,
            downloaded_at=now,
            producer=_producer(),
        )
    except Exception as exc:
        print(f"FAIL indirme: {classify(exc)} ({type(exc).__name__})")
        return 1
    try:
        summary = pilot_summary(manifest, manifest_sha256(workdir))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", "utf-8")
    except Exception as exc:
        print(f"FAIL kalite ozeti: {type(exc).__name__}")
        return 1
    _print_summary(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tlab.pilot_quality")
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(
        os.environ.get("ALPACA_PAPER_API_KEY", ""),
        os.environ.get("ALPACA_PAPER_SECRET_KEY", ""),
        # Duvar saati bilincli ve karar yolu disi: indirme ani. `run()`
        # zamani disaridan alir, testler enjekte eder.
        datetime.now(UTC),
        workdir=args.workdir,
        out=args.out,
    )


if __name__ == "__main__":
    raise SystemExit(main())
