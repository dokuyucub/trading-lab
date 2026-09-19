"""SQLite baglantisi ve sema goclleri (migration).

Sema, numarali .sql dosyalari halinde versiyonlanir. Uygulanan her
goc `schema_migrations` tablosuna yazilir, boylece ayni goc iki kez
calismaz ve veritabaninin hangi surumde oldugu her an bellidir.

Elle ALTER TABLE yapilmaz: sema degisikligi her zaman yeni bir
numarali dosyadir. Aylar sonra "bu kolon ne zaman geldi" sorusu
git gecmisinden cevaplanabilsin diye.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from tlab.errors import JournalError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Goc adi SQL metnine gomuldugu icin karakter kumesi kisitli tutuluyor.
# Parametre baglama executescript icinde calismiyor; bu yuzden guvenlik
# adin kendisinde saglaniyor.
_MIGRATION_NAME = re.compile(r"^\d{3}_[a-z0-9_]+$")


def connect(path: Path) -> sqlite3.Connection:
    """Journal veritabanina baglanir ve gerekli PRAGMA'lari ayarlar."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(path, isolation_level=None)
    except sqlite3.Error as exc:
        msg = f"Journal veritabanina baglanilamadi: {path} ({exc})"
        raise JournalError(msg) from exc

    conn.row_factory = sqlite3.Row
    # WAL: yazma sirasinda okuma engellenmez. Bot islem yazarken
    # analiz sorgusu ayni anda calisabilsin diye.
    conn.execute("PRAGMA journal_mode = WAL")
    # Referans butunlugu: yetim karar/emir kaydi olusmasin.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    """Uygulanmis en yuksek goc numarasi. Hic goc yoksa 0."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    return int(row["v"])


def _discover_migrations() -> list[tuple[int, str, Path]]:
    found: list[tuple[int, str, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if not _MIGRATION_NAME.match(path.stem):
            msg = f"Goc dosyasi 'NNN_kucuk_harfli_ad.sql' bicimini izlemeli: {path.name}"
            raise JournalError(msg)
        found.append((int(path.stem[:3]), path.stem, path))
    return found


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Bekleyen gocleri sirayla uygular; uygulananlarin adini dondurur.

    Her goc tek bir islem (transaction) icinde calisir: yarim
    uygulanmis sema birakmaz.
    """
    current = schema_version(conn)
    applied: list[str] = []

    for version, name, path in _discover_migrations():
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        # BEGIN/COMMIT script'in ICINE yaziliyor: sqlite3.executescript
        # calismadan once acik islemleri commit eder, bu yuzden disaridan
        # sarmalamak ise yaramaz. Kayit satiri da ayni islemde ki sema
        # ile surum numarasi asla ayrisamasin.
        script = (
            "BEGIN;\n"
            f"{sql}\n"
            "INSERT INTO schema_migrations (version, name, applied_at) "
            f"VALUES ({version}, '{name}', datetime('now'));\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            msg = f"Goc uygulanamadi ({name}): {exc}"
            raise JournalError(msg) from exc
        applied.append(name)

    return applied
