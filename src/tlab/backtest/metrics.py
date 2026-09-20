"""Backtest metrikleri.

Olcumlerin tamami R KATSAYISI uzerinden. Mutlak kar rakami
yaniltir: 1.000 $ kar, 500 $ riskle alindiysa +2R'dir, 5.000 $
riskle alindiysa +0,2R. Ikinci durum stratejinin iyi degil, sadece
buyuk oynadigini gosterir.

En onemli tek sayi BEKLENEN DEGER (islem basina ortalama R). Pozitif
degilse isabet orani ne olursa olsun strateji para kazandirmaz;
pozitifse islem sayisi arttikca kazandirir.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Metrics:
    """Bir kosunun performans ozeti."""

    trades: int
    wins: int
    losses: int
    net_pnl: float
    total_r: float
    expectancy_r: float
    """Islem basina ortalama R. Stratejinin tek gercek notu."""

    win_rate: float
    profit_factor: float
    """Brut kazancin brut kayba orani. 1'in altinda para kaybettiriyor."""

    avg_win_r: float
    avg_loss_r: float
    best_r: float
    worst_r: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_holding_minutes: float
    avg_entry_slippage_bps: float
    exit_breakdown: dict[str, int]

    @property
    def is_profitable(self) -> bool:
        return self.expectancy_r > 0

    def report(self) -> str:
        """Insan okunur ozet."""
        lines = [
            f"  islem sayisi        : {self.trades}",
            f"  isabet orani        : %{self.win_rate:.1f}  ({self.wins}K / {self.losses}Z)",
            f"  BEKLENEN DEGER      : {self.expectancy_r:+.3f} R / islem",
            f"  toplam R            : {self.total_r:+.2f}",
            f"  net kar/zarar       : {self.net_pnl:+,.2f}",
            f"  kar faktoru         : {self.profit_factor:.2f}",
            f"  ortalama kazanc     : {self.avg_win_r:+.2f} R",
            f"  ortalama kayip      : {self.avg_loss_r:+.2f} R",
            f"  en iyi / en kotu    : {self.best_r:+.2f} R / {self.worst_r:+.2f} R",
            f"  azami geri cekilme  : {self.max_drawdown:,.2f} (%{self.max_drawdown_pct:.2f})",
            f"  ortalama tutus      : {self.avg_holding_minutes:.0f} dk",
            f"  giris kaymasi       : {self.avg_entry_slippage_bps:+.2f} bps",
        ]
        if self.exit_breakdown:
            parts = ", ".join(f"{k}={v}" for k, v in sorted(self.exit_breakdown.items()))
            lines.append(f"  cikis sebepleri     : {parts}")
        return "\n".join(lines)


def max_drawdown(curve: Sequence[tuple[datetime, float]]) -> tuple[float, float]:
    """Ozsermaye egrisindeki en buyuk tepe-dip farki.

    Kar rakamindan daha onemli olabilir: bir strateji yilda %30
    kazandirsa bile arada %40 geri cekiliyorsa, o cekilmeyi
    oturarak beklemek pratikte cok zordur.
    """
    peak = float("-inf")
    worst = 0.0
    worst_pct = 0.0
    for _, equity in curve:
        peak = max(peak, equity)
        drop = peak - equity
        if drop > worst:
            worst = drop
            worst_pct = (drop / peak * 100) if peak > 0 else 0.0
    return worst, worst_pct


def compute_metrics(
    conn: sqlite3.Connection,
    run_id: str,
    curve: Sequence[tuple[datetime, float]] = (),
) -> Metrics:
    """Journal'daki islemlerden metrikleri hesaplar."""
    rows = conn.execute(
        "SELECT r_multiple, net_pnl, holding_seconds, entry_slippage_bps, exit_reason"
        " FROM trades WHERE run_id = ?",
        (run_id,),
    ).fetchall()

    drawdown, drawdown_pct = max_drawdown(curve)
    if not rows:
        return Metrics(
            trades=0,
            wins=0,
            losses=0,
            net_pnl=0.0,
            total_r=0.0,
            expectancy_r=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_win_r=0.0,
            avg_loss_r=0.0,
            best_r=0.0,
            worst_r=0.0,
            max_drawdown=drawdown,
            max_drawdown_pct=drawdown_pct,
            avg_holding_minutes=0.0,
            avg_entry_slippage_bps=0.0,
            exit_breakdown={},
        )

    r_values = [float(row["r_multiple"]) for row in rows]
    pnls = [float(row["net_pnl"]) for row in rows]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value <= 0]

    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)

    slippages = [
        float(row["entry_slippage_bps"]) for row in rows if row["entry_slippage_bps"] is not None
    ]

    breakdown: dict[str, int] = {}
    for row in rows:
        key = str(row["exit_reason"])
        breakdown[key] = breakdown.get(key, 0) + 1

    return Metrics(
        trades=len(rows),
        wins=len(wins),
        losses=len(losses),
        net_pnl=sum(pnls),
        total_r=sum(r_values),
        expectancy_r=sum(r_values) / len(r_values),
        win_rate=len(wins) / len(rows) * 100,
        # Hic kayip yoksa kar faktoru tanimsiz; sonsuz yerine
        # 0 donmek yaniltici olurdu, bu yuzden buyuk ama sonlu bir
        # deger yerine acikca sonsuz kullaniliyor.
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        avg_win_r=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss_r=(sum(losses) / len(losses)) if losses else 0.0,
        best_r=max(r_values),
        worst_r=min(r_values),
        max_drawdown=drawdown,
        max_drawdown_pct=drawdown_pct,
        avg_holding_minutes=sum(int(row["holding_seconds"]) for row in rows) / len(rows) / 60,
        avg_entry_slippage_bps=(sum(slippages) / len(slippages)) if slippages else 0.0,
        exit_breakdown=breakdown,
    )
