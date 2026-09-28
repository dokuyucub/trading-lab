"""Ana baseline olcumu: IKI ADIM, tek job (#17, PR b).

Sozlesme: docs/designs/baseline-measurement-execution.md. Kisaca:

  * `download` (adim A) - secret'lar YALNIZCA bu adimin ortaminda.
    Sirasi kesin: sabit tanim okunur, `status == "approved"` denetlenir;
    ancak ondan SONRA anahtar okunur, SDK kurulur, dizin olusturulur.
    Veri ve manifest hash'i sahip olunan gecici dizine yazilir.
  * `measure` (adim B) - anahtarsiz, SDK'siz. Ortamda Alpaca anahtari
    varsa baslamaz. Hash dosyasini tek okumayla okur, `verify_baseline`
    -> `run_baseline`, raporu YALNIZCA tam basarida ve atomik yazar.
    Holdout dosyalarina erismez (verify_baseline + denetim kancasi
    testleri); holdout yasagi A icin degil B icindir.

Log'a yalnizca sabit satirlar gider: sayimlar, hash onekleri ve sabit
hata kategorileri. Fiyat, tarih, yanit govdesi, traceback ya da
PERFORMANS SAYISI basilmaz; disari cikan tek sonuc rapor artefaktidir.
Bu, varsayilan log duzeyine guvenilerek DEGIL yapisal olarak saglanir:
her iki adim boyunca `logging` tamamen kapatilir (`_silenced`). Motor
her islemi fiyat ve P&L ile INFO'da loglar; urllib3 yeniden denemeleri
istek adresiyle WARNING'de loglar.

B icin isletim sistemi duzeyinde ag yalitimi YOKTUR ve iddia edilmez;
ag cagrisi olmadigi testte `socket.connect` yasaklanarak gosterilir.
Temizlik, fiziksel olarak geri getirilemez silme garantisi degildir.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import shutil
import stat
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tlab.sdk_probe import classify

MAIN_SPEC = Path("config/datasets/orb-baseline-2026q3-u11.yaml")
"""SABIT. Workflow'dan sembol, tarih ya da yol alinmaz."""

DATASET_DIR = "dataset"
HASH_FILE = "manifest.sha256"
KEY_ENV = (
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_SECRET_KEY",
)
"""Anahtar DEGISKEN ADLARI; degerler yalnizca adim A'da ortamdan okunur."""
SECRET_ENV_PREFIXES = ("ALPACA_", "APCA_")


# --------------------------------------------------------------------------
# Ortak
# --------------------------------------------------------------------------


@contextlib.contextmanager
def _silenced() -> Iterator[None]:
    """Adim boyunca BUTUN log kayitlarini kapatir; cikista eski haline doner.

    Ciktinin tek kaynagi aracin kendi sabit `print` satirlari olur.
    Kutuphane ya da motor logu - hangi duzeyde olursa olsun - gecemez.
    """
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _inside(path: Path, directory: Path) -> bool:
    """`path`, `directory`'nin kendisi ya da altinda mi (symlink cozulerek)."""
    resolved, root = path.resolve(), directory.resolve()
    return resolved == root or root in resolved.parents


def _producer(env: Mapping[str, str]) -> dict[str, str]:
    from tlab.journal.writer import current_git_sha

    return {
        "run_id": env.get("GITHUB_RUN_ID", "local"),
        "workflow": env.get("GITHUB_WORKFLOW", "local"),
        "commit": env.get("GITHUB_SHA") or current_git_sha(Path.cwd()) or "unknown",
    }


def _write_new(path: Path, payload: bytes) -> None:
    """`path`'e ATOMIK ve USTUNE YAZMADAN yazar.

    Once ayni dizinde O_EXCL ile gecici dosya, sonra `os.link` ile hedef:
    hedef varsa link basarisiz olur ve hicbir sey ezilmez. Hangi yoldan
    cikilirsa cikilsin gecici dosya silinir; yarim bir hedef olusmaz.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            view = memoryview(payload)
            while view:
                written = os.write(handle, view)
                view = view[written:]
            os.fsync(handle)
        finally:
            os.close(handle)
        os.link(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


# --------------------------------------------------------------------------
# Adim A: indirme
# --------------------------------------------------------------------------


def download(
    env: Mapping[str, str],
    now: datetime,
    *,
    workdir: Path,
    spec_path: Path = MAIN_SPEC,
    base_url: str | None = None,
) -> int:
    """Onayli tanimi indirir; veri ve manifest hash'i `workdir`'e yazilir.

    `env` yalnizca onay kapisindan SONRA okunur (testler erisimi
    kaydeder). `spec_path` ve `base_url` YALNIZCA testler icin: `main()`
    ikisini de gecirmez.
    """
    with _silenced():
        return _download_step(env, now, workdir=workdir, spec_path=spec_path, base_url=base_url)


def _download_step(
    env: Mapping[str, str],
    now: datetime,
    *,
    workdir: Path,
    spec_path: Path,
    base_url: str | None,
) -> int:
    from tlab.data.dataset import DatasetSpec

    try:
        spec = DatasetSpec.from_yaml(spec_path)
    except Exception as exc:
        print(f"FAIL tanim: okunamadi ({type(exc).__name__})")
        return 1
    if spec.status != "approved":
        # `require_downloadable` yalnizca draft'i reddeder ve pilot
        # indirmesine BILEREK izin verir. Ana olcumun kapisi ayri ve
        # daha dar: anahtar, SDK ve dizin bu satirdan sonra.
        print(f"FAIL onay: tanim '{spec.status}', ana olcum yalnizca 'approved' indirir")
        return 1

    key, secret = (env.get(name, "").strip() for name in KEY_ENV)
    if not key or not secret:
        print("FAIL yapilandirma: paper anahtar ve secret gerekli")
        return 1
    if any(not 33 <= ord(char) <= 126 for value in (key, secret) for char in value):
        print("FAIL yapilandirma: anahtar gecersiz karakter iceriyor")
        return 1
    if now.tzinfo is None or now.utcoffset() is None:
        print("FAIL yapilandirma: zaman dilimi gerekli")
        return 1

    workdir = Path(workdir)
    # Sahiplik (#27 dersi): dizini BU cagri olusturur. Onceden var olan
    # bir yol reddedilir ve ona dokunulmaz.
    try:
        workdir.parent.mkdir(parents=True, exist_ok=True)
        workdir.mkdir()
    except FileExistsError:
        print("FAIL yapilandirma: calisma dizini zaten var; dokunulmadi")
        return 1
    except OSError as exc:
        print(f"FAIL yapilandirma: calisma dizini olusturulamadi ({type(exc).__name__})")
        return 1

    succeeded = False
    try:
        code = _download(key, secret, now, spec, env, workdir=workdir, base_url=base_url)
        succeeded = code == 0
        return code
    finally:
        if not succeeded:
            # Yalnizca bu cagrinin olusturdugu dizin. Basarida B'ye kalir;
            # workflow'un temizlik adimi her durumda siler.
            shutil.rmtree(workdir, ignore_errors=True)


def _download(
    key: str,
    secret: str,
    now: datetime,
    spec: Any,
    env: Mapping[str, str],
    *,
    workdir: Path,
    base_url: str | None,
) -> int:
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

    dataset = workdir / DATASET_DIR
    try:
        manifest = build_dataset(
            spec,
            bars_source=market,
            calendar_source=_Calendar(),
            out_dir=dataset,
            downloaded_at=now,
            producer=_producer(env),
        )
        digest = manifest_sha256(dataset)
    except Exception as exc:
        print(f"FAIL indirme: {classify(exc)} ({type(exc).__name__})")
        return 1
    try:
        _write_new(workdir / HASH_FILE, (digest + "\n").encode("ascii"))
    except Exception as exc:
        print(f"FAIL hash dosyasi: {type(exc).__name__}")
        return 1

    sessions, split = manifest["sessions"], manifest["split"]
    print(f"OK indirme {manifest['dataset_id']} (manifest {digest[:12]})")
    print(
        f"seans: takvim {sessions['calendar']}, tamamlanmis {len(sessions['complete'])}, "
        f"baseline {len(split['baseline'])}, holdout {len(split['holdout'])}"
    )
    # Holdout hakkinda YALNIZCA seans sayisi (Codex #33 P2). Holdout'un
    # kalite sonucu - uygunsuz sayisi dahil - veriye bagli bir bilgidir
    # ve disari cikmaz; manifestte kalir, veri dizini temizlikte silinir.
    print(f"kaliteye uymayan baseline seansi: {manifest['quality']['ineligible']['baseline']}")
    return 0


# --------------------------------------------------------------------------
# Adim B: olcum
# --------------------------------------------------------------------------


def _secret_names(env: Mapping[str, str]) -> list[str]:
    return sorted(
        name for name, value in env.items() if name.startswith(SECRET_ENV_PREFIXES) and value
    )


def _read_digest(workdir: Path) -> str | None:
    from tlab.data.dataset import read_once

    try:
        text = read_once(workdir, HASH_FILE).decode("ascii").strip()
    except Exception as exc:
        print(f"FAIL butunluk: hash dosyasi okunamadi ({type(exc).__name__})")
        return None
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        print("FAIL butunluk: hash dosyasi bicimsiz")
        return None
    return text


def measure(env: Mapping[str, str], *, workdir: Path, out: Path, root: Path) -> int:
    """Dogrulanmis baseline'i olcer; rapor YALNIZCA tam basarida yazilir.

    Gecersiz bir kosuda tamamlanmis bir performans raporu yazilmaz.
    Onay, butunluk ve kalite hatalari P&L hesabindan ONCE durdurur;
    seans sinirinda acik pozisyon (`CarriedPositionError`) simulasyon
    SIRASINDA durdurur ve o ana kadarki sonuc yazilmaz.
    """
    with _silenced():
        return _measure_step(env, workdir=workdir, out=out, root=root)


def _measure_step(env: Mapping[str, str], *, workdir: Path, out: Path, root: Path) -> int:
    leaked = _secret_names(env)
    if leaked:
        # Yalnizca ad yazdirilir; deger yazdirilmaz.
        print(f"FAIL yapilandirma: olcum adiminda anahtar degiskeni var ({', '.join(leaked)})")
        return 1

    workdir, out = Path(workdir), Path(out)
    try:
        info = os.lstat(workdir)
    except OSError:
        print("FAIL yapilandirma: calisma dizini yok")
        return 1
    if not stat.S_ISDIR(info.st_mode):
        print("FAIL yapilandirma: calisma dizini gercek bir dizin degil")
        return 1
    if _inside(out, workdir):
        print("FAIL yapilandirma: rapor calisma dizininin icinde olamaz")
        return 1
    if os.path.lexists(out):
        print("FAIL yapilandirma: rapor yolu zaten var; dokunulmadi")
        return 1

    digest = _read_digest(workdir)
    if digest is None:
        return 1

    from tlab.backtest.baseline import report_bytes, run_baseline
    from tlab.backtest.engine import CarriedPositionError
    from tlab.config import load_config
    from tlab.data.dataset import (
        DatasetIntegrityError,
        DatasetQualityError,
        DatasetStatusError,
        verify_baseline,
    )

    try:
        config = load_config(root)
    except Exception as exc:
        print(f"FAIL ayarlar: okunamadi ({type(exc).__name__})")
        return 1

    verified = None
    try:
        verified = verify_baseline(workdir / DATASET_DIR, digest)
        report = run_baseline(verified, config, code_commit=_producer(env)["commit"])
        payload = report_bytes(report)
    except DatasetStatusError:
        print("FAIL onay: veri kumesi tanimi 'approved' degil; rapor yazilmadi")
        return 1
    except DatasetIntegrityError:
        print("FAIL butunluk: veri kumesi dogrulanamadi; rapor yazilmadi")
        return 1
    except DatasetQualityError:
        count = len(verified.ineligible()) if verified is not None else 0
        if count:
            print(f"FAIL kalite: {count} baseline seansi uygunsuz; rapor yazilmadi")
        else:
            print("FAIL kalite: politika stratejiyle tutarsiz; rapor yazilmadi")
        return 1
    except CarriedPositionError:
        print("FAIL seans siniri: acik pozisyon kaldi; rapor yazilmadi")
        return 1
    except Exception as exc:
        print(f"FAIL beklenmeyen hata ({type(exc).__name__}); rapor yazilmadi")
        return 1

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_new(out, payload)
    except FileExistsError:
        print("FAIL yapilandirma: rapor yolu zaten var; dokunulmadi")
        return 1
    except Exception as exc:
        print(f"FAIL rapor yazimi ({type(exc).__name__})")
        return 1

    # Performans sayisi LOG'A BASILMAZ; sonuc yalnizca rapor artefaktinda.
    print(f"OK olcum {report['dataset_id']} (manifest {digest[:12]})")
    print(
        f"rapor: sema {report['report_schema']}, senaryo {len(report['scenarios'])}, "
        f"baseline {report['baseline_sessions']['count']} seans, "
        f"holdout {report['holdout']['sessions']} seans (acilmadi)"
    )
    return 0


# --------------------------------------------------------------------------
# Giris
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tlab.baseline_job")
    sub = parser.add_subparsers(dest="step", required=True)
    step_a = sub.add_parser("download", help="Adim A: onayli tanimi indir")
    step_a.add_argument("--workdir", type=Path, required=True)
    step_b = sub.add_parser("measure", help="Adim B: anahtarsiz olcum")
    step_b.add_argument("--workdir", type=Path, required=True)
    step_b.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.step == "download":
        # Duvar saati bilincli ve karar yolu disi: indirme ani.
        return download(os.environ, datetime.now(UTC), workdir=args.workdir)
    return measure(os.environ, workdir=args.workdir, out=args.out, root=Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
