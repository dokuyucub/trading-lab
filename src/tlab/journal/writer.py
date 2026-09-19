"""Journal'a yazma islemleri.

Yazma yolu bilincli olarak dar: disaridan ham SQL calistirilmaz.
Her kayit tipi icin tek bir metot var ve hepsi dogrulanmis cekirdek
tiplerini girdi alir. Boylece journal'a hicbir zaman yarim ya da
tutarsiz bir kayit dusmez.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import uuid
from collections.abc import Mapping
from datetime import UTC, date
from pathlib import Path
from typing import Any

from tlab.core.clock import Clock, LiveClock
from tlab.core.types import BracketOrder, Decision, Fill, OrderRef, Trade
from tlab.errors import JournalError

RunMode = str  # paper | live | backtest | shadow
_VALID_MODES = {"paper", "live", "backtest", "shadow"}

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _safe_columns(row: Mapping[str, Any]) -> str:
    """Kolon adlarini SQL metnine gomulmeden once dogrular.

    Adlar kod tarafindan uretiliyor (Decision.to_row gibi), yani
    disaridan gelmiyor. Yine de dogruluyoruz: bu fonksiyonlar bir
    gun disaridan beslenirse, o gun fark etmek yerine bugun
    engellemek daha ucuz.
    """
    for name in row:
        if not _IDENTIFIER.match(name):
            msg = f"Gecersiz kolon adi: {name!r}"
            raise JournalError(msg)
    return ", ".join(row)


def current_git_sha(root: Path | None = None) -> str | None:
    """Calisan kodun git commit'i. Sonuclari kodun haline baglamak icin."""
    try:
        # Sabit arguman listesi, kabuk yok: disaridan girdi almiyor.
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
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
    """Kararlari ve kosulari journal'a yazar.

    Saat DISARIDAN veriliyor, `datetime.now()` cagrilmiyor. Sebep
    sistemin geri kalaniyla ayni: backtest'te zamani biz kontrol
    ediyoruz. Journal kendi saatine bakarsa, gecmis veri uzerinde
    yapilan bir kosunun kayitlari bugunun tarihini tasir ve o
    kosudan uretilen istatistikler zaman ekseninde yerinden oynar.
    """

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None) -> None:
        self._conn = conn
        self._clock = clock or LiveClock()

    def _now(self) -> str:
        return self._clock.now().astimezone(UTC).isoformat()

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
                    self._now(),
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
                (self._now(), run_id),
            )
        except sqlite3.Error as exc:
            msg = f"Kosu kapatilamadi ({run_id}): {exc}"
            raise JournalError(msg) from exc

    def record_decision(self, decision: Decision) -> None:
        """Bir karari kaydeder - izin verilmis olsun ya da olmasin."""
        row = decision.to_row()
        row["features_json"] = json.dumps(decision.intent.features, ensure_ascii=False)
        columns = _safe_columns(row)
        placeholders = ", ".join(f":{name}" for name in row)
        try:
            self._conn.execute(
                # Kolon adlari _safe_columns tarafindan dogrulandi; degerler
                # her zaman parametre olarak baglaniyor.
                f"INSERT INTO decisions ({columns}) VALUES ({placeholders})",  # noqa: S608
                row,
            )
        except sqlite3.Error as exc:
            msg = f"Karar kaydedilemedi ({decision.decision_id}): {exc}"
            raise JournalError(msg) from exc

    def record_order(
        self,
        order: BracketOrder,
        *,
        run_id: str,
        decision_id: str | None = None,
        status: str = "submitting",
    ) -> None:
        """Emri brokera GONDERMEDEN ONCE kaydeder (write-ahead).

        Sira bilincli: client_order_id'yi biz uretiyoruz, broker'in
        verdigi kimlik ise ancak cevap geldiginde biliniyor. Once
        gonderip sonra kaydetmek, ikisinin arasinda surec olurse
        brokerdaki emri sahipsiz birakirdi - o emrin dolmasindan
        dogan pozisyon hicbir karara atfedilemez ve mutabakat onu
        goremezdi.

        Kayit `submitting` durumunda duser; broker cevap verince
        `confirm_order` ile kesinlesir.
        """
        try:
            self._conn.execute(
                "INSERT INTO orders (client_order_id, broker_order_id, decision_id,"
                " run_id, symbol, side, qty, entry_type, limit_price, stop_loss,"
                " take_profit, status, submitted_at)"
                " VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order.client_order_id,
                    decision_id,
                    run_id,
                    order.symbol,
                    order.side.value,
                    order.qty,
                    order.entry_type.value,
                    order.limit_price,
                    order.stop_loss,
                    order.take_profit,
                    status,
                    self._now(),
                ),
            )
        except sqlite3.Error as exc:
            msg = f"Emir kaydedilemedi ({order.client_order_id}): {exc}"
            raise JournalError(msg) from exc

    def confirm_order(self, client_order_id: str, ref: OrderRef) -> None:
        """Broker cevabiyla emri kesinlestirir."""
        self._update_order(
            client_order_id,
            "broker_order_id = ?, status = ?, updated_at = ?",
            (ref.broker_order_id, ref.status, self._now()),
        )

    def update_order_status(
        self, client_order_id: str, status: str, broker_order_id: str | None = None
    ) -> None:
        """Emrin son bilinen durumunu gunceller."""
        if broker_order_id is None:
            self._update_order(
                client_order_id,
                "status = ?, updated_at = ?",
                (status, self._now()),
            )
            return
        self._update_order(
            client_order_id,
            "status = ?, broker_order_id = COALESCE(broker_order_id, ?), updated_at = ?",
            (status, broker_order_id, self._now()),
        )

    def _update_order(self, client_order_id: str, assignment: str, params: tuple[Any, ...]) -> None:
        try:
            self._conn.execute(
                # `assignment` cagiran metotlarda sabit metin; degerler
                # her zaman parametre olarak baglaniyor.
                f"UPDATE orders SET {assignment} WHERE client_order_id = ?",  # noqa: S608
                (*params, client_order_id),
            )
        except sqlite3.Error as exc:
            msg = f"Emir guncellenemedi ({client_order_id}): {exc}"
            raise JournalError(msg) from exc

    def record_fill(self, fill: Fill, run_id: str) -> bool:
        """Gerceklesmeyi denetim izine yazar; zaten varsa False doner."""
        try:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO fills (broker_order_id, client_order_id, run_id,"
                " symbol, side, qty, price, filled_at, order_type)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fill.broker_order_id,
                    fill.client_order_id,
                    run_id,
                    fill.symbol,
                    fill.side.value,
                    fill.qty,
                    fill.price,
                    fill.filled_at.astimezone(UTC).isoformat(),
                    fill.order_type,
                ),
            )
        except sqlite3.Error as exc:
            msg = f"Gerceklesme kaydedilemedi ({fill.broker_order_id}): {exc}"
            raise JournalError(msg) from exc
        return cursor.rowcount > 0

    def record_halt(self, trade_date: date, reason: str, run_id: str) -> None:
        """Gunu kill-switch ile kapatir.

        Kayit veritabaninda tutuluyor cunku bellekteki bir bayrak
        sureci asmaz: systemd yeniden baslattiginda sistem, gunu
        kapatmis oldugunu unutur ve tekrar islem acardi.
        """
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO daily_state (trade_date, halted_at, halt_reason, run_id)"
                " VALUES (?, ?, ?, ?)",
                (trade_date.isoformat(), self._now(), reason, run_id),
            )
        except sqlite3.Error as exc:
            msg = f"Gun durumu kaydedilemedi ({trade_date}): {exc}"
            raise JournalError(msg) from exc

    def record_trade(self, trade: Trade) -> bool:
        """Kapanmis bir islemi kaydeder; zaten varsa False doner.

        trade_id giris ve cikis emirlerinden TURETILIR, rastgele
        degildir. Bu sayede mutabakat dongusu ayni islemi kac kez
        gorurse gorsun kayit bir kez dusuyor - yeniden baslatma
        sonrasi mukerrer islem kaydi olusmuyor.
        """
        row = trade.to_row()
        columns = _safe_columns(row)
        placeholders = ", ".join(f":{name}" for name in row)
        try:
            cursor = self._conn.execute(
                # Kolon adlari _safe_columns tarafindan dogrulandi.
                f"INSERT OR IGNORE INTO trades ({columns}) VALUES ({placeholders})",  # noqa: S608  # noqa: S608
                row,
            )
        except sqlite3.Error as exc:
            msg = f"Islem kaydedilemedi ({trade.trade_id}): {exc}"
            raise JournalError(msg) from exc
        return cursor.rowcount > 0
