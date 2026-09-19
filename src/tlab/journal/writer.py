"""Journal'a yazma islemleri.

Yazma yolu bilincli olarak dar: disaridan ham SQL calistirilmaz.
Her kayit tipi icin tek bir metot var ve hepsi dogrulanmis cekirdek
tiplerini girdi alir. Boylece journal'a hicbir zaman yarim ya da
tutarsiz bir kayit dusmez.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tlab.core.types import Decision
from tlab.errors import JournalError

RunMode = str  # paper | live | backtest | shadow
_VALID_MODES = {"paper", "live", "backtest", "shadow"}


def current_git_sha(root: Path | None = None) -> str | None:
    """Calisan kodun git commit'i. Sonuclari kodun haline baglamak icin."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root or Path.cwd(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


class JournalWriter:
    """Kararlari ve kosulari journal'a yazar."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start_run(
        self,
        *,
        mode: RunMode,
        data_feed: str,
        params_version: str,
        config: dict[str, Any],
        git_sha: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Yeni bir kosu baslatir ve run_id dondurur.

        Kosu kaydi, o kosudaki tum kararlari uretilis kosullarina
        (kod surumu, veri feed'i, yapilandirma) baglar. Bu bag olmadan
        gecmis sonuclar yorumlanamaz.
        """
        if mode not in _VALID_MODES:
            msg = f"Gecersiz kosu modu: {mode!r}. Gecerli olanlar: {sorted(_VALID_MODES)}"
            raise JournalError(msg)

        run_id = uuid.uuid4().hex
        try:
            self._conn.execute(
                "INSERT INTO runs (run_id, started_at, mode, git_sha, data_feed,"
                " params_version, config_json, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    datetime.now(UTC).isoformat(),
                    mode,
                    git_sha,
                    data_feed,
                    params_version,
                    json.dumps(config, default=str, ensure_ascii=False),
                    notes,
                ),
            )
        except sqlite3.Error as exc:
            msg = f"Kosu kaydi olusturulamadi: {exc}"
            raise JournalError(msg) from exc
        return run_id

    def end_run(self, run_id: str) -> None:
        """Kosuyu kapatir."""
        try:
            self._conn.execute(
                "UPDATE runs SET ended_at = ? WHERE run_id = ?",
                (datetime.now(UTC).isoformat(), run_id),
            )
        except sqlite3.Error as exc:
            msg = f"Kosu kapatilamadi ({run_id}): {exc}"
            raise JournalError(msg) from exc

    def record_decision(self, decision: Decision) -> None:
        """Bir karari kaydeder - izin verilmis olsun ya da olmasin."""
        row = decision.to_row()
        row["features_json"] = json.dumps(decision.intent.features, ensure_ascii=False)
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        try:
            self._conn.execute(
                f"INSERT INTO decisions ({columns}) VALUES ({placeholders})",
                row,
            )
        except sqlite3.Error as exc:
            msg = f"Karar kaydedilemedi ({decision.decision_id}): {exc}"
            raise JournalError(msg) from exc
