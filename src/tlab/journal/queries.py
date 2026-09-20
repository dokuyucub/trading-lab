"""Journal okuma islemleri.

Yazma ve okuma bilincli olarak ayri modullerde: yazma yolu dar ve
dogrulanmis kalmali, okuma yolu ise serbestce genisleyecek (Faz 3'te
ogrenme katmani buraya bir suru sorgu ekleyecek).
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from tlab.errors import JournalError


def open_entry_orders(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Sistemin gonderdigi giris emirlerini client_order_id ile indeksler.

    Mutabakat, broker'dan gelen gerceklesmelerin hangilerinin BIZE
    ait oldugunu bu tablodan ogrenir. Elle acilmis ya da baska bir
    araciyla girilmis pozisyonlar boylece kendi istatistiklerimizi
    kirletmez.
    """
    try:
        rows = conn.execute(
            "SELECT o.client_order_id, o.broker_order_id, o.decision_id, o.symbol,"
            " o.side, o.qty, o.stop_loss, o.take_profit, o.limit_price,"
            " d.strategy_id, d.params_version"
            " FROM orders o LEFT JOIN decisions d ON d.decision_id = o.decision_id"
        ).fetchall()
    except sqlite3.Error as exc:
        msg = f"Giris emirleri okunamadi: {exc}"
        raise JournalError(msg) from exc
    return {str(row["client_order_id"]): dict(row) for row in rows}


def unconfirmed_orders(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Gonderildigi yazilmis ama broker cevabi kaydedilmemis emirler.

    Bu satirlar, emri kaydetmekle gondermek arasinda surecin oldugu
    pencerenin izidir. Her turda broker'a karsi cozumlenirler: emir
    brokerda varsa kesinlesir, yoksa ve uzerinden yeterli sure
    gectiyse 'kayip' olarak isaretlenip sembolun onu acilir.
    """
    try:
        rows = conn.execute(
            "SELECT client_order_id, symbol, submitted_at FROM orders WHERE status = 'submitting'"
        ).fetchall()
    except sqlite3.Error as exc:
        msg = f"Kesinlesmemis emirler okunamadi: {exc}"
        raise JournalError(msg) from exc
    return [dict(row) for row in rows]


def halt_reason(conn: sqlite3.Connection, trade_date: date) -> str | None:
    """Gun kill-switch ile kapatildiysa sebebi, degilse None.

    Surec yeniden baslasa bile okunabildigi icin kill-switch karari
    gun boyunca gecerli kaliyor.
    """
    row = conn.execute(
        "SELECT halt_reason FROM daily_state WHERE trade_date = ?", (trade_date.isoformat(),)
    ).fetchone()
    return None if row is None else str(row["halt_reason"])


def decision_count(conn: sqlite3.Connection, run_id: str) -> tuple[int, int]:
    """Bir kosudaki (izin verilen, veto edilen) karar sayilari."""
    row = conn.execute(
        "SELECT SUM(allowed) AS allowed, COUNT(*) AS total FROM decisions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    allowed = int(row["allowed"] or 0)
    total = int(row["total"] or 0)
    return allowed, total - allowed


def session_summary(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """Bir kosunun ozeti: sabah kalkinca bakilacak rakamlar."""
    allowed, vetoed = decision_count(conn, run_id)
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(net_pnl), 0) AS pnl,"
        " COALESCE(SUM(r_multiple), 0) AS r,"
        " COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END), 0) AS wins"
        " FROM trades WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    trades = int(row["n"])
    return {
        "decisions_allowed": allowed,
        "decisions_vetoed": vetoed,
        "trades": trades,
        "wins": int(row["wins"]),
        "win_rate": (int(row["wins"]) / trades * 100) if trades else 0.0,
        "net_pnl": float(row["pnl"]),
        "total_r": float(row["r"]),
    }


def top_veto_reasons(
    conn: sqlite3.Connection, run_id: str, limit: int = 5
) -> list[tuple[str, int]]:
    """En sik veto sebepleri.

    Risk kapisinin neyi engelledigini gormek, stratejiyi ayarlamanin
    en hizli yolu: sistem hic islem acmiyorsa sebebi burada yazili.
    """
    rows = conn.execute(
        "SELECT veto_reasons FROM decisions WHERE run_id = ? AND allowed = 0", (run_id,)
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        for reason in str(row["veto_reasons"] or "").split(","):
            key = reason.strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
