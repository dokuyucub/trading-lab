"""Mimari kurallarin kendini korudugu testler.

Bu dosyanin varlik sebebi, projede birden fazla gelistiricinin
(insan ya da ajan) calismasi. Yazili bir kural, onu okumayan birine
hicbir sey yapmaz; calistirilabilir bir kural herkese ayni seyi
soyler ve CI'da durur.

Buradaki her kural, gercekten YASANMIS bir hatanin karsiligi.
Aciklamalar bilincli olarak uzun: kurali ilk kez goren biri, neden
var oldugunu anlamadan onu kaldirmasin.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "tlab"


def python_files(*parts: str) -> list[Path]:
    root = SRC.joinpath(*parts) if parts else SRC
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imports_of(path: Path) -> set[str]:
    """Dosyanin ictegi modul adlari - fonksiyon icindekiler dahil.

    AST kullaniliyor, metin arama degil: Alpaca importlarinin bir
    kismi bilincli olarak fonksiyon govdesinde duruyor ve metin
    aramasi yorum/docstring iceriklerini de yakalayip yanlis alarm
    veriyor.
    """
    found: set[str] = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def wall_clock_calls(path: Path) -> list[tuple[int, str]]:
    """Dosyadaki gercek duvar saati cagrilari.

    Yine AST: `datetime.now()` ifadesi bir docstring ya da hata
    mesaji icinde gectiginde bu bir cagri DEGILDIR. Metin aramasi
    ikisini ayirt edemiyor ve kurali gurultuye bogar.
    """
    bases = {"datetime", "date", "time"}
    names = {"now", "today", "utcnow", "time"}
    hits: list[tuple[int, str]] = []

    for node in ast.walk(parse(path)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in names:
            continue
        base = node.func.value
        base_name = (
            base.id
            if isinstance(base, ast.Name)
            else base.attr
            if isinstance(base, ast.Attribute)
            else None
        )
        if base_name in bases:
            hits.append((node.lineno, f"{base_name}.{node.func.attr}()"))
    return hits


# --------------------------------------------------------------------------
# Saat disiplini
# --------------------------------------------------------------------------

# Duvar saatine bakmasina izin verilen dosyalar. Hepsi "kenar":
# saati URETEN ya da kullanicidan varsayilan tarih alan yerler.
CLOCK_ALLOWLIST = {
    "core/clock.py",  # LiveClock'un kendisi
    "cli.py",  # komut satiri varsayilanlari
    "backtest/engine.py",  # default_range yardimcisi
}


def test_decision_path_never_reads_the_wall_clock() -> None:
    """Karar yolundaki hicbir kod `datetime.now()` cagirmamali.

    Saat her zaman disaridan verilir. Sebep: backtest'te zamani biz
    kontrol ediyoruz. Duvar saatine bakan bir kod, gecmis veri
    uzerinde calisirken "su an"i yanlis bilir ve farkinda olmadan
    gelecege bakar.

    Bu kural bir kez kirildi: JournalWriter zaman damgalarini
    `datetime.now()` ile aliyordu. Canlida fark edilmiyordu ama
    backtest kayitlari bugunun tarihini tasiyor, yani o kosudan
    uretilen istatistikler zaman ekseninde yerinden oynuyordu.
    """
    offenders = [
        f"{path.relative_to(SRC).as_posix()}:{line}: {call}"
        for path in python_files()
        if path.relative_to(SRC).as_posix() not in CLOCK_ALLOWLIST
        for line, call in wall_clock_calls(path)
    ]

    assert not offenders, (
        "Karar yolunda duvar saati cagrisi var. Saati Clock'tan al:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# Katman bagimliliklari
# --------------------------------------------------------------------------

# Her katmanin ictegi tlab paketleri. Liste disinda bir sey ictegi
# anda test duruyor.
LAYER_RULES: dict[str, set[str]] = {
    "core": {"tlab.core", "tlab.errors"},
    "features": {"tlab.core", "tlab.errors"},
    "strategies": {"tlab.core", "tlab.features", "tlab.errors"},
    "risk": {"tlab.core", "tlab.features", "tlab.config", "tlab.errors"},
}


@pytest.mark.parametrize("layer", sorted(LAYER_RULES))
def test_layer_only_depends_on_lower_layers(layer: str) -> None:
    """Alt katmanlar ust katmanlari tanimamali.

    Sistemin tum gucu bu yonde: strateji broker'i bilmedigi icin
    backtest'te de canlida da ayni calisiyor. Ters yonde tek bir
    import, bu ozelligi sessizce yok eder - kod calismaya devam eder
    ama backtest artik canlinin aynisi olmaz.
    """
    # Katmanin kendini ictegi her zaman serbest.
    allowed = LAYER_RULES[layer] | {f"tlab.{layer}"}
    violations: list[str] = []

    for path in python_files(layer):
        for module in imports_of(path):
            if not module.startswith("tlab"):
                continue
            package = ".".join(module.split(".")[:2])
            if package not in allowed:
                violations.append(f"{path.relative_to(SRC)}: {module}")

    assert not violations, (
        f"{layer}/ katmani izin verilmeyen bir katmani ictiyor "
        f"(izinli: {sorted(allowed)}):\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize("layer", ["core", "features", "strategies", "risk", "engine"])
def test_business_layers_never_import_the_vendor_sdk(layer: str) -> None:
    """Alpaca SDK'si yalnizca kenar katmanlarda gorunmeli.

    Saticiya bagimlilik execution/ ve data/ ile sinirli. Bu sinir
    silinirse broker degistirmek - ya da sadece test etmek -
    imkansiz hale gelir.
    """
    offenders = [
        f"{path.relative_to(SRC)}: {module}"
        for path in python_files(layer)
        for module in imports_of(path)
        if module.split(".")[0] == "alpaca"
    ]
    assert not offenders, f"{layer}/ icinde Alpaca SDK importu:\n  " + "\n  ".join(offenders)


def test_core_has_no_third_party_dependency_beyond_pydantic() -> None:
    """Cekirdek tipler saf kalmali.

    core/ tum sistemin tabani; buraya giren her bagimlilik her yere
    bulasir.
    """
    allowed_roots = {"tlab", "pydantic", "typing", "datetime", "enum", "uuid", "__future__"}
    offenders = [
        f"{path.relative_to(SRC)}: {module}"
        for path in python_files("core")
        for module in imports_of(path)
        if module.split(".")[0] not in allowed_roots
    ]
    assert not offenders, "core/ icinde beklenmeyen bagimlilik:\n  " + "\n  ".join(offenders)


# --------------------------------------------------------------------------
# Veritabani gocleri
# --------------------------------------------------------------------------


def migration_files() -> list[Path]:
    return sorted((SRC / "journal" / "migrations").glob("*.sql"))


def test_migrations_are_uniquely_and_sequentially_numbered() -> None:
    """Goc numaralari benzersiz ve arasiz olmali.

    Iki gelistirici ayni anda calisirken en olasi catisma bu: ikisi
    de '003_...' yazar, ikisi de kendi makinesinde calisir, birlestikten
    sonra veritabani sessizce yanlis sirayla kurulur.
    """
    numbers = [int(path.stem[:3]) for path in migration_files()]
    assert numbers, "en az bir goc dosyasi olmali"
    assert len(numbers) == len(set(numbers)), f"mukerrer goc numarasi: {numbers}"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"goc numaralari 001'den baslayip arasiz ilerlemeli: {numbers}"
    )


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.name)
def test_migration_filenames_follow_the_convention(path: Path) -> None:
    assert re.fullmatch(r"\d{3}_[a-z0-9_]+", path.stem), (
        f"goc adi 'NNN_kucuk_harfli_ad.sql' olmali: {path.name}"
    )


def test_applied_migrations_are_not_edited() -> None:
    """Uygulanmis bir goc dosyasi degistirilmemeli.

    Goc bir kez calistigi veritabaninda tekrar calismaz; dosyayi
    sonradan duzenlemek, yeni kurulan veritabani ile mevcut olani
    birbirinden farkli hale getirir. Degisiklik her zaman YENI bir
    numarali dosyadir.

    Test, dosyalarin git gecmisindeki son haliyle ayni oldugunu
    dogruluyor; henuz commit edilmemis yeni goc dosyalari muaf.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "src/tlab/journal/migrations"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("git gecmisi okunamadi")
    changed = [line for line in result.stdout.split() if line]
    assert not changed, (
        "Uygulanmis goc dosyasi degistirilmis. Degisiklik yeni bir dosya olmali:\n  "
        + "\n  ".join(changed)
    )


# --------------------------------------------------------------------------
# Sir sizintisi
# --------------------------------------------------------------------------

SECRET_PATTERNS = [
    re.compile(r"\bPK[A-Z0-9]{16,}\b"),  # Alpaca anahtar bicimi
    re.compile(r"\bAK[A-Z0-9]{16,}\b"),  # Alpaca canli anahtar bicimi
]


def test_no_api_key_is_tracked_by_git() -> None:
    """Hicbir izlenen dosya API anahtari icermemeli.

    Git gecmisi kalicidir: dosyayi sonradan duzeltmek eski
    commit'lerdeki anahtari silmez. Bu testin ucuz olmasi ve her
    kosuda calismasi, tam da bu geri donusu olmayan hatayi
    engellemek icin.
    """
    listing = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
    )
    if listing.returncode != 0:
        pytest.skip("git dosya listesi okunamadi")

    offenders: list[str] = []
    for name in listing.stdout.split():
        path = REPO / name
        if not path.is_file() or path.suffix in {".parquet", ".db", ".png"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Testlerdeki sahte anahtarlar ("PKTEST") kasten kisa tutuldu.
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                offenders.append(name)
                break

    assert not offenders, "Izlenen dosyada API anahtari bulundu:\n  " + "\n  ".join(offenders)


def test_env_file_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", ".env"], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, ".env .gitignore tarafindan dislanmali"
