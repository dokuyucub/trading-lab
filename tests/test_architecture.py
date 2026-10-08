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
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

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
    # Baglanti tanisi; karar yolu degil. Clock enjekte etmek tlab.core'u
    # - dolayisiyla pydantic'i - zorunlu kilar ve aracin bagimsizligini
    # bozardi (bkz. test_the_connection_probe_needs_no_dependencies).
    "paper_probe.py",
    # Ayni dar istisna: SDK okuma yolu tanisi da karar yolu degil.
    # `run()` zamani disaridan alir ve testler enjekte eder; yalnizca
    # CLI girisi duvar saatine bakar.
    "sdk_probe.py",
    # Pilot kalite araci: indirme anini kaydeder; karar yolu degil ve
    # P&L katmanlarini ice aktaramaz (test_the_pilot_cannot_see_performance).
    "pilot_quality.py",
    # Ana baseline isi: yalnizca `main()` indirme anini duvar saatinden
    # alir; `download()` zamani disaridan alir, testler enjekte eder.
    "baseline_job.py",
    # Baseline kalite teshisi: yalnizca `main()` erisim anini duvar
    # saatinden alir; `run()` zamani disaridan alir.
    "baseline_diagnostic.py",
    # SIP kalite karsilastirmasi: ayni dar istisna, yalnizca `main()`.
    "feed_comparison.py",
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
    # Ogrenme katmani cevrimdisi calisir ve karar yolunu tanimaz.
    # Stratejileri veya broker'i ice aktarmasi, olculen seyin olcen
    # seye bagli hale gelmesi demek olurdu.
    "learning": {"tlab.core", "tlab.errors"},
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
    # Research content IDs and calendar-day boundaries use only these stdlib modules.
    allowed_roots = {
        "tlab",
        "pydantic",
        "typing",
        "datetime",
        "enum",
        "uuid",
        "__future__",
        "hashlib",
        "json",
        "zoneinfo",
    }
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

_KEY_CHARS = "A-Za-z0-9/+"

# Katman 1 - BILINEN ALAN: Alpaca anahtar adina atanmis duz (literal) deger.
# Degerin bicimine bakmaz; tek buyukluklu ya da yalniz rakamli bir secret'i
# da yakalar. Ortam referanslari (${{ secrets.X }}, $X), bos degerler,
# <yer tutucu>lar ve fonksiyon cagrilari literal degildir. 16 karakter alt
# siniri testlerdeki bilincli kisa sahteleri (PKTEST, secret) disarida birakir.
NAMED_FIELD = re.compile(
    r"\b(?:ALPACA|APCA)_[A-Z_]*(?:KEY|SECRET)[A-Z_]*\b[\"']?\s*[:=,]\s*"
    r"(?P<q>[\"']?)(?P<value>[A-Za-z0-9/+_\-]{16,})(?P=q)(?![A-Za-z0-9/+_\-(.])"
)

# Katman 2 - SEZGISEL: alan adi olmadan anahtara BENZEYEN dizeler.
TOKEN_PATTERNS = {
    # Alpaca anahtar KIMLIGI: paper PK..., canli AK..., buyuk harf + rakam.
    "anahtar-kimligi": re.compile(r"\b[PA]K[A-Z0-9]{16,}\b"),
    # 40 karakter, buyuk harf + kucuk harf + rakam KARISIK. Karisiklik sarti
    # commit SHA'larini ve SHA256'lari eler (tek buyukluklu hex).
    "karisik-token": re.compile(
        rf"(?<![{_KEY_CHARS}])"
        rf"(?=[{_KEY_CHARS}]{{0,39}}[a-z])"
        rf"(?=[{_KEY_CHARS}]{{0,39}}[A-Z])"
        rf"(?=[{_KEY_CHARS}]{{0,39}}[0-9])"
        rf"[{_KEY_CHARS}]{{40}}"
        rf"(?![{_KEY_CHARS}])"
    ),
}
"""SINIRLARI - bu denetim GitHub secret scanning'in yerine GECMEZ:

  * Yalnizca calisma agacindaki izlenen dosyalar; git GECMISI taranmaz.
  * Alan adi olmadan yazilmis TEK BUYUKLUKLU ya da YALNIZ RAKAMLI bir
    secret yakalanmaz (katman 2 karisiklik ister; saglayicinin her
    secret'ta iki harf buyuklugunu garanti ettigi dogrulanmadi).
  * base64/hex ile gizlenmis, bolunmus ya da birlestirilerek kurulan
    anahtar yakalanmaz. Baska saglayicilarin anahtarlari kapsam disi.
  * Katman 2 sahte pozitif verebilir (secret olmayan 40 karakterlik
    karisik bir token). O durumda dize degistirilir, kural gevsetilmez.
"""


def secret_findings(text: str) -> list[tuple[int, str]]:
    """(satir, kategori) listesi. Eslesen DEGER asla donmez: test ciktisi
    gercek bir anahtari loga basmamali."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if NAMED_FIELD.search(line):
            found.append((number, "bilinen-alan"))
            continue
        for category, pattern in TOKEN_PATTERNS.items():
            if pattern.search(line):
                found.append((number, category))
                break
    return found


def _fake(*parts: str) -> str:
    """Sahte anahtari calisma aninda kurar: kaynakta DUZ halde durmasin,
    yoksa tarama bu dosyanin kendisini yakalar."""
    return "".join(parts)


@pytest.mark.parametrize(
    ("text", "category"),
    [
        (_fake("ALPACA_SECRET_KEY=", "abcd1234" * 5), "bilinen-alan"),  # tek buyukluk
        (_fake("ALPACA_PAPER_SECRET_KEY: '", "7" * 40, "'"), "bilinen-alan"),  # yalniz rakam
        (_fake('"APCA_API_KEY_ID": "', "PK", "X" * 18, '"'), "bilinen-alan"),
        (_fake('setenv("ALPACA_API_KEY", "', "q" * 20, '")'), "bilinen-alan"),
        (_fake("PK", "ABCDEFGH", "12345678", "XY"), "anahtar-kimligi"),
        (_fake("AK", "ZZZZ9999", "QQQQ1111", "RS"), "anahtar-kimligi"),
        (_fake("aB3d" * 10), "karisik-token"),
        (_fake("token ", "Zx9/" * 10, " son"), "karisik-token"),
    ],
    ids=[
        "field-lowercase",
        "field-digits",
        "field-json",
        "field-setenv",
        "paper-key-id",
        "live-key-id",
        "mixed-token",
        "mixed-token-slash",
    ],
)
def test_the_scanner_catches_key_shaped_values(text: str, category: str) -> None:
    assert secret_findings(text) == [(1, category)]


@pytest.mark.parametrize(
    "text",
    [
        "ALPACA_API_KEY=",  # .env.example: bos
        "ALPACA_API_KEY=<paper key>",  # belgede yer tutucu
        "ALPACA_PAPER_SECRET_KEY: ${{ secrets.ALPACA_PAPER_SECRET_KEY }}",  # workflow
        'key = os.environ.get("ALPACA_PAPER_API_KEY", "")',  # ortamdan okuma
        '"ALPACA_API_KEY": mask(self.alpaca_api_key),',  # cagri, literal degil
        'monkeypatch.setenv("ALPACA_PAPER_API_KEY", "PKTEST")',  # kisa sahte
        "ALPACA_API_KEY=PKTEST123",  # kisa sahte
        "4ff2013ae05c261f3bfd5eb98843e0cb72e97145",  # commit SHA
        "4FF2013AE05C261F3BFD5EB98843E0CB72E97145",  # buyuk hex
        "df8f2247cef8c463af62edb29707584e3810bc3a" * 2,  # bitisik hash
        _fake("aB3d" * 10, "e"),  # 41 karakter
    ],
    ids=[
        "empty",
        "placeholder",
        "actions-secret-ref",
        "environ-get",
        "function-call",
        "setenv-short-fake",
        "short-fake",
        "sha1",
        "sha1-upper",
        "hash-pair",
        "41-chars",
    ],
)
def test_the_scanner_ignores_what_it_must_not_flag(text: str) -> None:
    assert secret_findings(text) == []


@pytest.mark.parametrize(
    "text",
    [_fake("abcd1234" * 5), _fake("7" * 40), _fake("aBcD" * 10)],
    ids=["unnamed-lowercase", "unnamed-digits", "unnamed-no-digit"],
)
def test_known_misses_are_documented_not_hidden(text: str) -> None:
    """BILINEN KACIRMALAR: alan adi olmadan tek buyuklukte, yalniz rakamli
    ya da rakamsiz bir secret yakalanmaz. Bu test o sinirin varligini
    sabitliyor; biri 'artik her seyi yakaliyor' diye yazarsa kirilir."""
    assert secret_findings(text) == []


def test_no_api_key_is_tracked_by_git() -> None:
    """Hicbir izlenen dosya API anahtari icermemeli.

    Git gecmisi kalicidir: dosyayi sonradan duzeltmek eski
    commit'lerdeki anahtari silmez. Bu testin ucuz olmasi ve her
    kosuda calismasi, tam da bu geri donusu olmayan hatayi
    engellemek icin. Sinirlari TOKEN_PATTERNS'in aciklamasinda.
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
        offenders.extend(
            f"{name}:{line} ({category})" for line, category in secret_findings(content)
        )

    # Yalnizca dosya:satir ve kategori basilir; eslesen deger asla.
    assert not offenders, "Izlenen dosyada anahtara benzeyen deger:\n  " + "\n  ".join(offenders)


def test_env_file_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", ".env"], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, ".env .gitignore tarafindan dislanmali"


# --------------------------------------------------------------------------
# Bagimlilik kilidi
# --------------------------------------------------------------------------


TARGET_ENVIRONMENT = {
    "python_version": "3.12",
    "python_full_version": "3.12.0",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "os_name": "posix",
    "implementation_name": "cpython",
    "platform_machine": "x86_64",
}
"""Kilidin uretildigi ve CI'nin kullandigi ortam.

Marker'lar bu ortama gore degerlendiriliyor: yalnizca baska bir
platformda gecerli olan bir bagimlilik, burada eksik sayilmamali.
"""


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_requirements(*, include_extras: bool = True) -> list[str]:
    """pyproject.toml icindeki dogrudan bagimlilik ifadeleri (ham).

    `include_extras=False` yalnizca calisma zamani bagimliliklarini
    verir: uretim imaji gelistirme araclarini tasimamali.
    """
    import tomllib

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    entries = list(project.get("dependencies", []))
    if include_extras:
        for extra in project.get("optional-dependencies", {}).values():
            entries.extend(extra)
    return entries


def declared_dependencies() -> set[str]:
    """Dogrudan bagimlilik adlari."""
    from packaging.requirements import Requirement

    return {canonical(Requirement(entry).name) for entry in declared_requirements()}


def locked_versions(filename: str = "requirements-dev.lock") -> dict[str, str]:
    """Kilitteki paket adi -> tam surum."""
    lock = REPO / filename
    if not lock.exists():
        pytest.skip(f"{filename} yok")

    versions: dict[str, str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", " ", "\t")) or not line.strip():
            continue
        name, separator, version = line.partition("==")
        if separator:
            versions[canonical(name.strip())] = version.split(";")[0].strip()
    return versions


def lock_violations(
    declared: list[str], locked: dict[str, str], environment: dict[str, str]
) -> list[str]:
    """Kilidin bildirilen sartlari karsilamadigi noktalar.

    Ad karsilastirmasi YETMEZ: pyproject'te `pandas>=999` yazip kilitte
    `pandas==3.0.6` birakmak, yalnizca adlara bakan bir kapidan gecer.
    Surum sartinin gercekten saglandigi dogrulanmali.

    Fonksiyon saf tutuldu ki hem gercek dosyalarla hem de sentetik
    girdilerle test edilebilsin - bir kapinin kendisi de test
    edilmeden guvenilmez.
    """
    from packaging.requirements import Requirement
    from packaging.version import InvalidVersion, Version

    violations: list[str] = []
    for entry in declared:
        requirement = Requirement(entry)
        # Bu ortamda gecerli olmayan bagimlilik (ornegin yalnizca
        # Windows icin) kilitte aranmaz.
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue

        name = canonical(requirement.name)
        pinned = locked.get(name)
        if pinned is None:
            violations.append(f"{name}: kilitte yok (bildirilen: {entry})")
            continue

        try:
            version = Version(pinned)
        except InvalidVersion:
            violations.append(f"{name}: kilitteki surum okunamadi ({pinned!r})")
            continue

        if not requirement.specifier.contains(version, prereleases=True):
            violations.append(f"{name}: kilitteki {pinned} surumu '{entry}' sartini karsilamiyor")
    return violations


def test_dev_lock_satisfies_every_declared_constraint() -> None:
    """Gelistirme kilidi tum bagimliliklari kapsamali (CI bunu kuruyor).

    Kilit tazeleme:  make lock
    """
    violations = lock_violations(
        declared_requirements(), locked_versions("requirements-dev.lock"), TARGET_ENVIRONMENT
    )
    assert not violations, "requirements-dev.lock guncel degil:\n  " + "\n  ".join(violations)


def test_runtime_lock_satisfies_runtime_constraints() -> None:
    """Calisma zamani kilidi (Docker imaji) calisma bagimliliklarini kapsamali."""
    violations = lock_violations(
        declared_requirements(include_extras=False),
        locked_versions("requirements.lock"),
        TARGET_ENVIRONMENT,
    )
    assert not violations, "requirements.lock guncel degil:\n  " + "\n  ".join(violations)


def test_runtime_lock_excludes_development_tools() -> None:
    """Uretim imaji test ve linter araclarini tasimamali.

    Yalnizca boyut meselesi degil: uretimde bulunmayan bir arac,
    uretimde calisan bir seyi degistiremez.
    """
    runtime = locked_versions("requirements.lock")
    leaked = sorted({"pytest", "mypy", "ruff", "pre-commit", "coverage"} & set(runtime))
    assert not leaked, f"calisma zamani kilidinde gelistirme araci: {leaked}"


def test_both_locks_agree_on_shared_packages() -> None:
    """Ortak paketler iki kilitte ayni surumde olmali.

    Ayrisirlarsa, CI'da test edilen surum ile uretimde calisan surum
    farkli olur - kilit kullanmanin butun amaci bu farki ortadan
    kaldirmakti.
    """
    runtime = locked_versions("requirements.lock")
    development = locked_versions("requirements-dev.lock")
    mismatched = sorted(
        f"{name}: calisma {runtime[name]} != gelistirme {development[name]}"
        for name in set(runtime) & set(development)
        if runtime[name] != development[name]
    )
    assert not mismatched, "Kilitler ayrismis:\n  " + "\n  ".join(mismatched)


def test_lock_gate_catches_a_missing_package() -> None:
    violations = lock_violations(["pandas>=2.2"], {}, TARGET_ENVIRONMENT)
    assert violations and "kilitte yok" in violations[0]


def test_lock_gate_catches_a_version_that_does_not_satisfy() -> None:
    """Kapinin asil sinavi: ad dogru ama surum yanlis.

    Bu senaryo gercekten kacmisti - eski kapi yalnizca ad setlerini
    karsilastirdigi icin pyproject'teki 'pandas>=999' sarti kilitteki
    'pandas==3.0.6' ile celistigi halde gecmisti.
    """
    violations = lock_violations(["pandas>=999"], {"pandas": "3.0.6"}, TARGET_ENVIRONMENT)
    assert violations and "sartini karsilamiyor" in violations[0]


def test_lock_gate_accepts_a_satisfying_version() -> None:
    assert lock_violations(["pandas>=2.2"], {"pandas": "3.0.6"}, TARGET_ENVIRONMENT) == []


def test_lock_gate_normalizes_package_names() -> None:
    """pyproject'te 'types-PyYAML', kilitte 'types-pyyaml' olabilir."""
    assert lock_violations(["types-PyYAML"], {"types-pyyaml": "6.0.1"}, TARGET_ENVIRONMENT) == []


def test_lock_gate_skips_dependencies_not_active_in_this_environment() -> None:
    """Yalnizca baska platformda gecerli bir bagimlilik eksik sayilmamali."""
    assert lock_violations(['colorama; sys_platform == "win32"'], {}, TARGET_ENVIRONMENT) == []
    assert lock_violations(['tomli; python_version < "3.11"'], {}, TARGET_ENVIRONMENT) == []


def test_lock_gate_reports_an_unreadable_pin() -> None:
    violations = lock_violations(["pandas>=2.2"], {"pandas": "bozuk"}, TARGET_ENVIRONMENT)
    assert violations and "okunamadi" in violations[0]


@pytest.mark.parametrize("filename", ["requirements.lock", "requirements-dev.lock"])
def test_lock_file_pins_exact_versions(filename: str) -> None:
    """Kilitte aralik degil TAM surum olmali.

    '>=' ile sabitlenmis bir kilit, kilit degildir: ayni commit iki
    hafta arayla farkli surumlerle kurulur ve CI kodla ilgisi
    olmayan bir sebeple kirilir. Bu bir kez yasandi (numpy 2.5.3).
    """
    loose: list[str] = []
    for line in (REPO / filename).read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", " ", "\t")) or not line.strip():
            continue
        if "==" not in line:
            loose.append(line.strip())
    assert not loose, f"{filename} icinde tam surum olmayan satirlar:\n  " + "\n  ".join(loose)


# ---------------------------------------------------------------------------
# Makefile hedefleri
#
# Bu bolum iki gercek hatanin karsiligi. Ikisi de `make check` yesilken
# vardi, cunku test kapisi Makefile hedeflerinin KENDISINI calistirmiyor:
#
#   make hooks  ->  $(PY) -m pre-commit install
#                   "No module named pre-commit" (modul adi pre_commit)
#   make lock   ->  $(PY) -m uv pip compile ...
#                   "No module named uv" (uv bagimliliklara yazili degildi)
#
# Ders: calistirilmayan bir hedef curur. Araclari yorumlayicidan cagirmak
# dogru karardi, ama bu kararin bedeli `-m`'in DAGITIM adini degil MODUL
# adini istemesi. Asagidaki kapi tam bu farki olcuyor.
# ---------------------------------------------------------------------------

# Tire de yakalaniyor: `-m pre-commit` gibi bir yazim sessizce "pre"ye
# dusup tesaduefen gecmesin, acik bir kural olarak reddedilsin.
MODULE_INVOCATION = re.compile(r"\$\(PY\)\s+-m\s+([A-Za-z_][\w.\-]*)")


def makefile_modules(text: str) -> set[str]:
    """Makefile'in yorumlayici uzerinden cagirdigi modul adlari.

    Saf tutuldu: bir kapinin kendisi de test edilmeden guvenilmez -
    bu ders lock kapisinda ogrenildi, burada tekrarlanmiyor.
    """
    return {
        match.group(1)
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
        for match in MODULE_INVOCATION.finditer(line)
    }


def test_makefile_invokes_only_importable_modules() -> None:
    """`$(PY) -m X` icindeki her X gercekten ice aktarilabilmeli.

    Bu test `pre-commit` tuzagini dogrudan yakalar: dagitim adi tireli,
    modul adi alt cizgili. Ayni zamanda `uv` gibi bir aracin
    bagimliliklara yazilmayi unutulmasini da yakalar - cunku modul
    ancak kilitten kurulduysa ice aktarilabilir.
    """
    from importlib.util import find_spec

    missing: list[str] = []
    for module in sorted(makefile_modules((REPO / "Makefile").read_text(encoding="utf-8"))):
        # Tireli ad hicbir zaman gecerli bir modul adi degildir; import
        # denemesine gerek yok, dogrudan hata.
        if "-" in module:
            missing.append(module)
            continue
        try:
            if find_spec(module) is None:
                missing.append(module)
        except (ImportError, ValueError):
            missing.append(module)
    assert not missing, (
        "Makefile ice aktarilamayan modul cagiriyor: "
        + ", ".join(missing)
        + "\n  `-m` MODUL adi ister (pre_commit), dagitim adini degil (pre-commit);"
        + "\n  arac gelistirme bagimliliklarinda tanimli ve kilitte olmali."
    )


def test_makefile_gate_finds_the_module_names() -> None:
    """Kapinin kendi sinavi: hedefleri gercekten ayikliyor mu."""
    assert makefile_modules("build:\n\t$(PY) -m pytest --cov\n") == {"pytest"}
    assert makefile_modules("doctor:\n\t$(PY) -m tlab.cli doctor\n") == {"tlab.cli"}
    assert makefile_modules("a:\n\t$(PY) -m ruff check .\n\t$(PY) -m mypy\n") == {"ruff", "mypy"}


def test_makefile_gate_ignores_commented_out_lines() -> None:
    """Yorum satirindaki ornek bir komut kapiyi kirmamali."""
    assert makefile_modules("# eskiden: $(PY) -m eski_arac\nx:\n\t$(PY) -m pytest\n") == {"pytest"}


def test_makefile_gate_would_catch_a_hyphenated_module_name() -> None:
    """Yasanan hata sentetik girdiyle de yakalanabilmeli.

    Tireli ad butun olarak ayiklaniyor ve gecersiz sayiliyor. Onemi:
    ad yalnizca "pre"ye kirpilsaydi, "pre" adli bir paketin ortamda
    bulunmasi durumunda hata sessizce gecerdi.
    """
    assert makefile_modules("hooks:\n\t$(PY) -m pre-commit install\n") == {"pre-commit"}


SYSTEM_HOOK_ENTRY = re.compile(r"^\s*entry:\s*(.+?)\s*$")


def system_hook_entries(text: str) -> list[str]:
    """`language: system` kancalarinin calistirdigi komutlar.

    Basit satir tabanli okuma yeterli: config duz ve kisa, YAML
    ayristiricisi eklemek kapinin kendisine bagimlilik katardi.
    """
    entries: list[str] = []
    pending: str | None = None
    for line in text.splitlines():
        match = SYSTEM_HOOK_ENTRY.match(line)
        if match:
            pending = match.group(1)
        elif "language: system" in line and pending is not None:
            entries.append(pending)
            pending = None
    return entries


def test_local_hooks_call_tools_through_the_interpreter() -> None:
    """Kancalar da araci PATH'ten degil yorumlayicidan cagirmali.

    Makefile'da ogrenilen ders bu dosyada tekrarlanmisti: `entry: pytest`
    PATH'teki pytest'i buluyordu ve o kurulum `tlab` paketini
    goremedigi icin her commit kanca hatasiyla dusuyordu. Hata
    gorunmemisti, cunku kancayi kuran hedef (`make hooks`) zaten
    calismiyordu - iki kusur birbirini gizlemisti.
    """
    entries = system_hook_entries((REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    assert entries, "yerel kanca bulunamadi - config bicimi mi degisti?"

    bare = [entry for entry in entries if not entry.startswith(("python -m ", "$(PY) -m "))]
    assert not bare, (
        "Kanca araci PATH'ten cagiriyor: "
        + ", ".join(bare)
        + "\n  `python -m <arac>` kullanin; ciplak ad projenin bagimliliklarini"
        + "\n  gormeyen baska bir kurulumu bulabilir."
    )


def test_hook_entry_gate_reads_only_system_hooks() -> None:
    """Kapinin kendi sinavi."""
    config = (
        "repos:\n"
        "  - repo: https://example.invalid\n"
        "    hooks:\n"
        "      - id: ruff\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: mypy\n"
        "        entry: python -m mypy\n"
        "        language: system\n"
    )
    assert system_hook_entries(config) == ["python -m mypy"]


def test_hook_entry_gate_catches_a_bare_tool_name() -> None:
    """Yasanan hata sentetik girdiyle de yakalanmali."""
    config = (
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: pytest\n"
        "        entry: pytest -q\n"
        "        language: system\n"
    )
    entries = system_hook_entries(config)
    assert entries == ["pytest -q"]
    assert not entries[0].startswith("python -m ")


# --------------------------------------------------------------------------
# Baglanti tanisinin bagimsizligi
# --------------------------------------------------------------------------


def test_the_connection_probe_needs_no_dependencies() -> None:
    """Paper baglanti probu yalnizca standart kutuphaneyi ictegi.

    Bu arac tam da baska seyler bozukken "anahtarlar ve ag saglam mi"
    sorusunu cevaplayabilmek icin var. Kurulum gerektirseydi,
    kurulumun bozuk oldugu durumda - yani en cok ihtiyac duyuldugu
    anda - susardi.

    Kural yazili olarak vardi ama DENETLENMIYORDU, ve ilk gercek
    kosuda kirildi:

        PYTHONPATH=src python -m tlab.data.paper_probe
        ModuleNotFoundError: No module named 'pandas'

    Modul `tlab/data/` altinda durdugu icin, `-m` ile calistirmak
    `tlab.data` paketini ice aktariyor, o da onbellek modulu uzerinden
    pandas'i cekiyordu. Probun kendi kodunda tek bir ucuncu taraf
    importu yoktu - paketin konumu yetti.

    Bu yuzden test yalnizca dosyanin importlarina degil, ICE AKTARMA
    ZINCIRININ TAMAMINA bakiyor: modulun bulundugu paketlerin
    __init__ dosyalari da sayiliyor.
    """
    probe = SRC / "paper_probe.py"
    assert probe.exists(), (
        "paper_probe.py tlab paketinin KOKUNDE olmali. Bir alt pakete "
        "tasinirsa o paketin __init__ dosyasi da yuklenir ve arac "
        "sessizce bagimlilik kazanir."
    )

    # Probun kendisi + kok paketin __init__'i: calistirmada yuklenen her sey.
    chain = [probe, SRC / "__init__.py"]
    third_party = sorted(
        {
            module.split(".")[0]
            for path in chain
            for module in imports_of(path)
            if module.split(".")[0] not in sys.stdlib_module_names and not module.startswith("tlab")
        }
    )
    assert not third_party, (
        "Baglanti probu ucuncu taraf paket ictegi: "
        + ", ".join(third_party)
        + "\n  Bu arac kurulum olmadan calisabilmeli."
    )


def test_the_probe_does_not_import_the_tlab_package() -> None:
    """Prob `tlab` icinden de bir sey ice aktarmamali.

    `tlab.core` pydantic'e, `tlab.data` pandas'a bagli. Ikisi de
    kurulum gerektirir; biri ice aktarildiginda bagimsizlik biter.
    """
    offenders = sorted(m for m in imports_of(SRC / "paper_probe.py") if m.startswith("tlab"))
    assert not offenders, (
        "Baglanti probu tlab paketinden ice aktariyor: "
        + ", ".join(offenders)
        + "\n  Bu importlar kurulum gerektiren bagimliliklari zincirle getirir."
    )


# --------------------------------------------------------------------------
# Veri kumesi bolmesi performans goremez
# --------------------------------------------------------------------------

PERFORMANCE_PACKAGES = ("tlab.backtest", "tlab.learning", "tlab.strategies", "tlab.engine")


def test_the_dataset_split_cannot_see_performance() -> None:
    """Holdout bolmesi yapilirken tek bir P&L satiri hesaplanamaz.

    Bu yazili bir kural olarak kalsaydi, ilk kotu sonuctan sonra
    "bolme sinirini biraz kaydiralim" demek bir satirlik is olurdu.
    Burada YAPISAL: veri kumesi modulu backtest'i, stratejileri,
    ogrenme katmanini ya da seans dongusunu ice aktaramaz. Performans
    hesaplayamayan bir kod, bolme sinirini performansa gore secemez.
    """
    path = SRC / "data" / "dataset.py"
    offenders = sorted(
        module for module in imports_of(path) if module.startswith(PERFORMANCE_PACKAGES)
    )
    assert not offenders, (
        "Veri kumesi modulu performans hesaplayabilen bir katmani ice aktariyor: "
        + ", ".join(offenders)
        + "\n  Bolme, sonuc gorulmeden yapilmali (AGENTS §3)."
    )


def test_the_pilot_cannot_see_performance() -> None:
    """Pilot yalnizca veri kalitesini olcer; P&L hesaplayabilecek hicbir
    katmani ice aktaramaz (AGENTS §11, #25 sart 3)."""
    path = SRC / "pilot_quality.py"
    offenders = sorted(
        module for module in imports_of(path) if module.startswith(PERFORMANCE_PACKAGES)
    )
    assert not offenders, "Pilot araci performans katmani ice aktariyor: " + ", ".join(offenders)


# --------------------------------------------------------------------------
# CI tetikleyici sozlesmesi
# --------------------------------------------------------------------------


def test_every_pull_request_passes_the_same_quality_gate() -> None:
    """CI: main'e push + filtresiz pull_request + haftalik kanarya.

    Dallara push kosusu kaldirildi (ayni commit iki kez kosuyordu), ama
    bunun bir atlatma yoluna donusmemesi gerekiyor: pull_request'e dal
    ya da yol filtresi eklenirse bazi PR'lar `quality` kapisindan
    gecmeden birlesebilirdi. Bu test o sessiz gevsemeyi yakalar.
    """
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    # PyYAML (YAML 1.1) `on` anahtarini True olarak okur.
    triggers = workflow.get("on", workflow.get(True))

    assert triggers["push"] == {"branches": ["main"]}
    assert triggers["pull_request"] is None, "pull_request filtresiz olmali"
    assert "schedule" in triggers

    quality = workflow["jobs"]["quality"]
    assert quality["name"] == "quality"
    assert quality["if"] == "github.event_name != 'schedule'"
    commands = " ".join(step.get("run", "") for step in quality["steps"])
    for gate in ("ruff check", "ruff format --check", "mypy", "pytest --cov"):
        assert gate in commands, f"quality kapisindan dusmus: {gate}"


# --------------------------------------------------------------------------
# Pilot kalite workflow sozlesmesi (AGENTS §11, #25)
# --------------------------------------------------------------------------


def _workflow(name: str) -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(
        (REPO / ".github" / "workflows" / name).read_text("utf-8")
    )
    return loaded


def test_the_pilot_workflow_keeps_raw_data_and_secrets_contained() -> None:
    """Ham veri disari cikmaz, secret'lar tek adimda, tetik yalnizca elle.

    Her madde #25'in bir kabul sartina karsilik geliyor; biri gevserse
    bu test kirilir.
    """
    workflow = _workflow("alpaca-pilot-quality.yml")
    # PyYAML (YAML 1.1) `on` anahtarini True olarak okur.
    triggers: dict[str, Any] = workflow["on"] if "on" in workflow else workflow[True]
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"] is None, "workflow girdi (input) almamali"
    assert workflow["permissions"] == {"contents": "read"}

    (job,) = workflow["jobs"].values()
    assert job["if"] == "github.ref == 'refs/heads/main'"
    steps = job["steps"]

    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["persist-credentials"] is False

    with_secrets = [step for step in steps if "secrets." in yaml.safe_dump(step)]
    assert len(with_secrets) == 1, "secret'lar yalnizca indirme adiminda olmali"
    assert "tlab.pilot_quality" in with_secrets[0]["run"]
    assert "--spec" not in with_secrets[0]["run"], "tanim yolu kodda sabit olmali"

    uploads = [step for step in steps if str(step.get("uses", "")).startswith("actions/upload")]
    assert len(uploads) == 1
    assert uploads[0]["with"]["path"] == "${{ runner.temp }}/pilot-summary.json"
    assert uploads[0]["with"]["if-no-files-found"] == "error"
    assert not any(str(step.get("uses", "")).startswith("actions/cache") for step in steps)

    # Secret'lar workflow ya da job duzeyinde de olamaz: orada tanimlanan
    # env her adima gecer (Codex #27 notu). Ayni sekilde hicbir adim
    # hatayi yutmaz, ve yalnizca temizlik kosullu calisir.
    outside_steps = {key: value for key, value in workflow.items() if key != "jobs"}
    outside_steps["job"] = {key: value for key, value in job.items() if key != "steps"}
    assert "secrets." not in yaml.safe_dump(outside_steps)
    assert "env" not in workflow and "env" not in job
    assert "continue-on-error" not in job
    assert not [step.get("name") for step in steps if "continue-on-error" in step]
    assert [step.get("name") for step in steps if "if" in step] == [steps[-1].get("name")]

    cleanup = steps[-1]
    assert cleanup["if"] == "always()"
    assert 'rm -rf "$RUNNER_TEMP/pilot-data"' in cleanup["run"]
    assert 'test ! -e "$RUNNER_TEMP/pilot-data"' in cleanup["run"]


# --------------------------------------------------------------------------
# Ana baseline olcumu workflow sozlesmesi (#17, tasarim belgesi)
# --------------------------------------------------------------------------


def test_the_baseline_workflow_separates_secrets_from_measurement() -> None:
    """Iki adim, tek job: secret yalnizca indirmede; rapor temizlikten sonra.

    Her madde docs/designs/baseline-measurement-execution.md'deki bir
    sarta karsilik geliyor; biri gevserse bu test kirilir.
    """
    workflow = _workflow("alpaca-baseline-measure.yml")
    # PyYAML (YAML 1.1) `on` anahtarini True olarak okur.
    triggers: dict[str, Any] = workflow["on"] if "on" in workflow else workflow[True]
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"] is None, "workflow girdi (input) almamali"
    assert workflow["permissions"] == {"contents": "read"}

    (job,) = workflow["jobs"].values()
    assert job["if"] == "github.ref == 'refs/heads/main'"
    steps = job["steps"]
    names = [step.get("name") for step in steps]

    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["persist-credentials"] is False

    # Secret'lar workflow/job duzeyinde olamaz: oradaki env her adima gecer.
    outside_steps = {key: value for key, value in workflow.items() if key != "jobs"}
    outside_steps["job"] = {key: value for key, value in job.items() if key != "steps"}
    assert "secrets." not in yaml.safe_dump(outside_steps)
    assert "env" not in workflow and "env" not in job

    runs = [step for step in steps if "tlab.baseline_job" in step.get("run", "")]
    assert len(runs) == 2, "tam olarak iki adim: indirme ve olcum"
    download, measure = runs
    assert "tlab.baseline_job download" in download["run"]
    assert "tlab.baseline_job measure" in measure["run"]
    assert steps.index(download) < steps.index(measure)

    with_secrets = [step for step in steps if "secrets." in yaml.safe_dump(step)]
    assert with_secrets == [download], "secret'lar yalnizca indirme adiminda olmali"
    assert "env" not in measure, "olcum adiminin ortami bos olmali"
    for step in runs:
        assert "--spec" not in step["run"], "tanim yolu kodda sabit olmali"

    # Hicbir adim hatayi yutmaz; yalnizca temizlik kosullu calisir.
    assert "continue-on-error" not in job
    assert not [step.get("name") for step in steps if "continue-on-error" in step]
    conditional = [step for step in steps if "if" in step]
    assert len(conditional) == 1
    cleanup = conditional[0]
    assert cleanup["if"] == "always()"
    assert 'rm -rf "$RUNNER_TEMP/baseline-data"' in cleanup["run"]
    assert 'test ! -e "$RUNNER_TEMP/baseline-data"' in cleanup["run"]
    assert '--workdir "$RUNNER_TEMP/baseline-data"' in download["run"]
    assert '--workdir "$RUNNER_TEMP/baseline-data"' in measure["run"]

    # Tek upload, KOSULSUZ (yani yalnizca onceki her adim - temizlik
    # dahil - basariliysa) ve temizlikten SONRA. Rapor veri dizininin
    # disinda.
    uploads = [step for step in steps if str(step.get("uses", "")).startswith("actions/upload")]
    assert len(uploads) == 1
    upload = uploads[0]
    assert names.index(upload.get("name")) > names.index(cleanup.get("name"))
    assert upload["with"]["path"] == "${{ runner.temp }}/baseline-report.json"
    assert '--out "$RUNNER_TEMP/baseline-report.json"' in measure["run"]
    assert upload["with"]["if-no-files-found"] == "error"
    assert not any(str(step.get("uses", "")).startswith("actions/cache") for step in steps)
    assert "GITHUB_STEP_SUMMARY" not in yaml.safe_dump(workflow), "log'a rapor yazilmaz"


@pytest.mark.parametrize(
    "relative",
    ["baseline_diagnostic.py", "feed_comparison.py", "job_io.py", "data/quality_summary.py"],
)
def test_the_quality_diagnostic_cannot_see_performance(relative: str) -> None:
    """Teshis P&L'siz: ne kendisi ne ortak yardimcilari performans
    katmani ice aktarir (#17). `job_io` bu yuzden `baseline_job`'dan
    ayri; teshis ana olcum yurutucusune baglanmaz."""
    path = SRC / relative
    offenders = sorted(
        module
        for module in imports_of(path)
        if module.startswith(PERFORMANCE_PACKAGES) or module == "tlab.baseline_job"
    )
    assert not offenders, f"{relative} performans katmani ice aktariyor: " + ", ".join(offenders)


@pytest.mark.parametrize(
    ("file", "module", "out"),
    [
        (
            "alpaca-baseline-quality-diagnostic.yml",
            "tlab.baseline_diagnostic",
            "baseline-quality-diagnostic.json",
        ),
        (
            "alpaca-baseline-feed-comparison.yml",
            "tlab.feed_comparison",
            "baseline-feed-comparison.json",
        ),
    ],
    ids=["iex-teshis", "sip-karsilastirma"],
)
def test_the_diagnostic_workflow_is_one_step_with_secrets_and_one_upload(
    file: str, module: str, out: str
) -> None:
    """Teshis ve SIP karsilastirmasi: manuel, yalniz main, secret tek
    adimda, ham veri yok, tek ozet, feed/tanim/gorev girdisi yok."""
    workflow = _workflow(file)
    # PyYAML (YAML 1.1) `on` anahtarini True olarak okur.
    triggers: dict[str, Any] = workflow["on"] if "on" in workflow else workflow[True]
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"] is None, "workflow girdi (input) almamali"
    assert workflow["permissions"] == {"contents": "read"}

    (job,) = workflow["jobs"].values()
    assert job["if"] == "github.ref == 'refs/heads/main'"
    steps = job["steps"]
    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["persist-credentials"] is False

    outside_steps = {key: value for key, value in workflow.items() if key != "jobs"}
    outside_steps["job"] = {key: value for key, value in job.items() if key != "steps"}
    assert "secrets." not in yaml.safe_dump(outside_steps)
    assert "env" not in workflow and "env" not in job

    runs = [step for step in steps if module in step.get("run", "")]
    assert len(runs) == 1
    (diagnose,) = runs
    with_secrets = [step for step in steps if "secrets." in yaml.safe_dump(step)]
    assert with_secrets == [diagnose], "secret'lar yalnizca teshis adiminda olmali"
    for flag in ("--spec", "--task", "--feed"):
        assert flag not in diagnose["run"]
    assert f'--out "$RUNNER_TEMP/{out}"' in diagnose["run"]

    # Hicbir adim kosullu degil ve hatayi yutmaz: upload yalnizca teshis
    # basariliysa calisir.
    assert "continue-on-error" not in job
    assert not [step for step in steps if "continue-on-error" in step or "if" in step]
    uploads = [step for step in steps if str(step.get("uses", "")).startswith("actions/upload")]
    assert len(uploads) == 1
    (upload,) = uploads
    assert steps.index(upload) > steps.index(diagnose)
    assert upload["with"]["path"] == "${{ runner.temp }}/" + out
    assert upload["with"]["if-no-files-found"] == "error"
    assert not any(str(step.get("uses", "")).startswith("actions/cache") for step in steps)
    assert "GITHUB_STEP_SUMMARY" not in yaml.safe_dump(workflow)


def test_the_baseline_job_measures_one_fixed_spec() -> None:
    """Ana is tek bir tanimi olcer ve o tanim depoda."""
    from tlab.baseline_job import MAIN_SPEC

    assert (REPO / MAIN_SPEC).is_file()
    assert MAIN_SPEC.stem.startswith("orb-baseline-")


# --------------------------------------------------------------------------
# Artefakt yukleme sozlesmesi ve gidis-donus dogrulamasi (#17, #39)
# --------------------------------------------------------------------------

UPLOAD_ACTION = "actions/upload-artifact@"
UPLOAD_INPUTS = frozenset({"name", "path", "if-no-files-found", "retention-days"})
UPLOAD_RETENTION_DAYS = {
    "alpaca-pilot-quality.yml": 30,
    "alpaca-baseline-measure.yml": 90,
    "alpaca-baseline-quality-diagnostic.yml": 90,
    "alpaca-baseline-feed-comparison.yml": 90,
    "artifact-roundtrip.yml": 1,
}
"""Upload adimi olan BUTUN workflow'lar ve saklama sureleri, MEVCUT
degerleriyle: pilot ozeti 30 gun, uc gercek rapor 90 gun. Yalnizca sentetik
dogrulama 1 gun; bu kisa sure gercek raporlara tasinmaz. Yeni bir upload
yolu ya da sure degisikligi buraya bilincli olarak yazilir."""

ROUNDTRIP = "artifact-roundtrip.yml"
ROUNDTRIP_PATHS = [".github/workflows/**", "scripts/artifact_roundtrip/**"]


def _upload_steps() -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        for job in _workflow(path.name).get("jobs", {}).values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith(UPLOAD_ACTION):
                    found.setdefault(path.name, []).append(step)
    return found


def test_every_upload_uses_one_version_and_one_input_contract() -> None:
    """Butun artefakt yuklemeleri AYNI surumde ve AYNI girdi sozlesmesinde.

    Bir yukseltme kullanimlardan birini atlarsa burada kirmizi olur: #39
    (Dependabot) sonradan eklenen SIP workflow'unu kapsamiyordu. Gidis-donus
    dogrulamasi da ayni surumu ve ayni girdi anahtarlarini kullandigi icin,
    onun hosted kosuda yesil olmasi gercek veri workflow'larinin upload
    adimi icin anlamlidir.
    """
    steps = _upload_steps()
    assert set(steps) == set(UPLOAD_RETENTION_DAYS), "upload yolu listesi degisti"
    versions = {step["uses"] for items in steps.values() for step in items}
    assert len(versions) == 1, f"upload surumleri karisik: {sorted(versions)}"
    for name, items in steps.items():
        assert len(items) == 1, f"{name}: birden cok upload adimi"
        (step,) = items
        inputs = step["with"]
        assert set(inputs) == UPLOAD_INPUTS, f"{name}: upload girdi kumesi farkli"
        assert inputs["if-no-files-found"] == "error", name
        assert str(inputs["path"]).startswith("${{ runner.temp }}/"), name
        assert str(inputs["path"]).endswith(".json"), name
        assert inputs["retention-days"] == UPLOAD_RETENTION_DAYS[name], name


def test_the_roundtrip_check_is_secret_free_and_least_privileged() -> None:
    """Gidis-donus dogrulamasi: secret yok, pull_request_target yok, token
    yalnizca dogrulama adiminda, en az izin; quality kapisindan bagimsiz."""
    workflow = _workflow(ROUNDTRIP)
    dumped = yaml.safe_dump(workflow)
    # PyYAML (YAML 1.1) `on` anahtarini True olarak okur.
    triggers: dict[str, Any] = workflow["on"] if "on" in workflow else workflow[True]
    assert set(triggers) == {"pull_request", "workflow_dispatch"}
    assert triggers["pull_request"] == {"paths": ROUNDTRIP_PATHS}
    assert triggers["workflow_dispatch"] is None, "workflow girdi almamali"
    assert "pull_request_target" not in dumped
    assert "secrets." not in dumped
    assert "set -x" not in dumped
    assert workflow["permissions"] == {"contents": "read"}
    assert "env" not in workflow

    jobs = workflow["jobs"]
    assert set(jobs) == {"upload", "verify"}
    assert "permissions" not in jobs["upload"], "upload isi ek izin almamali"
    assert jobs["verify"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["verify"]["needs"] == "upload"
    for name, job in jobs.items():
        assert "env" not in job, f"{name}: is duzeyinde env olmamali"
        assert "continue-on-error" not in job
        assert not [step for step in job["steps"] if "continue-on-error" in step or "if" in step]
        checkout = next(
            step
            for step in job["steps"]
            if str(step.get("uses", "")).startswith("actions/checkout")
        )
        assert checkout["with"]["persist-credentials"] is False, name

    with_token = [
        (name, step)
        for name, job in jobs.items()
        for step in job["steps"]
        if "github.token" in yaml.safe_dump(step)
    ]
    assert [(name, step["name"]) for name, step in with_token] == [
        ("verify", "Geri indir ve dogrula")
    ], "token yalnizca dogrulama adiminda olmali"
    (_, verify_step) = with_token[0]
    reference = "${{ github.token }}"  # Actions ifadesi; deger degil
    assert verify_step["env"]["GH_TOKEN"] == reference
    assert "github.token" not in verify_step["run"], "token komut satirina yazilmaz"
    assert "scripts/artifact_roundtrip/verify.py" in verify_step["run"]

    # Yuklenen dosya depodaki SABIT sentetik dosya; gercek veri yok.
    prepare = " ".join(step.get("run", "") for step in jobs["upload"]["steps"])
    assert "scripts/artifact_roundtrip/payload.json" in prepare
    assert "tlab" not in dumped, "dogrulama trading koduna dokunmaz"
