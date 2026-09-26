"""Dogrulanmis veri kumesinin BASELINE bolumunde offline olcum.

Bu modul ag erisimi yapmaz, anahtar istemez ve holdout'a dokunmaz:
girdisi `verify_baseline`'in dondurdugu dogrulanmis bir baseline'dir
ve holdout hakkinda yalnizca kac seans oldugunu bilir.

Rapor iki seyi birlikte verir, cunku ikisi ayri ayri yaniltir:

  * Nokta tahminleri (beklenen deger, isabet, drawdown) - ne oldu.
  * Ogrenme katmaninin durust hukmu - bunun gurultuden ayirt
    edilip edilemedigi.

Pozitif bir beklenen deger tek basina kanit degil (bkz. learning/).
Rapor bunu tasarim geregi ayni sayfada gosterir.

TEKRAR URETIM: ayni veri kumesi + config + kod -> bayt bayt ayni
rapor. Bu yuzden rapora duvar saati, rastgele kosu kimligi veya
yerel dosya yolu GIRMEZ. Journal bellekte tutulur ve atilir; yalnizca
rapor kalir.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from tlab.backtest.engine import Backtest
from tlab.backtest.sim_broker import SimFillModel
from tlab.config import Config
from tlab.core.types import Timeframe
from tlab.data.cache import BarCache
from tlab.data.cached import CachedMarketData
from tlab.data.dataset import VerifiedBaseline, canonical_json
from tlab.journal.db import apply_migrations
from tlab.learning import assess
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CostScenario:
    """Bir maliyet varsayimi. Olcum her birinde ayri kosulur."""

    name: str
    slippage_bps: float
    spread_bps: float
    commission_bps: float = 0.0


DEFAULT_SCENARIOS: tuple[CostScenario, ...] = (
    CostScenario("iyimser", slippage_bps=0.5, spread_bps=1.0),
    CostScenario("temel", slippage_bps=1.0, spread_bps=2.0),
    CostScenario("kotumser", slippage_bps=3.0, spread_bps=5.0),
    CostScenario("sert", slippage_bps=5.0, spread_bps=10.0),
)
"""Maliyet duyarliligi.

"temel", CLI'nin varsayilanlariyla ayni. Bir strateji yalnizca
"iyimser" satirda karliysa, karli degildir: gun ici kucuk marjlar
maliyete en duyarli seydir ve gercek kaymayi henuz hic olcmedik.
"""

PRIMARY_SCENARIO = "temel"

CAVEATS: tuple[str, ...] = (
    "Olcum yalnizca BASELINE bolumunde. Holdout acilmadi; bu rapor "
    "bagimsiz bir dogrulama degildir.",
    "Dolumlar simule. Gercek kayma, kismi dolum ve emir yasam dongusu "
    "henuz hic gozlenmedi (AGENTS §7).",
    "Guven araligi islemleri bagimsiz sayar; ayni gunun islemleri "
    "bagimsiz degil, dolayisiyla gercek belirsizlik daha buyuk.",
    "Bu rapor terfi karari DEGILDIR. Otomatik terfi yok.",
)


def _config_sha256(config: Config) -> str:
    return hashlib.sha256(canonical_json(config.model_dump(mode="json"))).hexdigest()


def _r_values(conn: sqlite3.Connection, run_id: str) -> list[float]:
    rows = conn.execute(
        "SELECT r_multiple FROM trades WHERE run_id = ? ORDER BY exit_ts, symbol, entry_ts",
        (run_id,),
    ).fetchall()
    return [float(row[0]) for row in rows]


def _run_scenario(
    verified: VerifiedBaseline,
    config: Config,
    scenario: CostScenario,
    *,
    starting_equity: float,
    timeframe: Timeframe,
) -> dict[str, Any]:
    first = min(verified.days)
    last = max(verified.days)
    start = datetime.combine(first, datetime.min.time(), UTC)
    # Son baseline gununun tamamini kapsa; holdout dosyalari zaten
    # baseline kokunde YOK, yani aralik genis olsa bile gorunmez.
    end = datetime.combine(last, datetime.min.time(), UTC) + timedelta(days=1)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        apply_migrations(conn)
        strategy = OpeningRangeBreakout(ORBParams())
        market = CachedMarketData(
            BarCache(verified.root),
            timeframe=timeframe,
            synthetic_spread_bps=scenario.spread_bps,
        )
        result = Backtest(
            config=config,
            strategy=strategy,
            market=market,
            conn=conn,
            starting_equity=starting_equity,
            fill_model=SimFillModel(
                slippage_bps=scenario.slippage_bps, commission_bps=scenario.commission_bps
            ),
            timeframe=timeframe,
            opening_range_minutes=strategy.params.opening_range_minutes,
            # Resmi seans saatleri: yarim gunde kapanis 13:00, ve seans
            # sinirinda acik pozisyon kalirsa olcum durur.
            sessions=verified.sessions,
        ).run(start, end)

        r_values = _r_values(conn, result.run_id)
        metrics = result.metrics
        evidence = assess(r_values)
        return {
            "name": scenario.name,
            "slippage_bps": scenario.slippage_bps,
            "spread_bps": scenario.spread_bps,
            "commission_bps": scenario.commission_bps,
            "trading_days": result.trading_days,
            "trades": metrics.trades if metrics else 0,
            "expectancy_r": round(metrics.expectancy_r, 6) if metrics else None,
            "win_rate_pct": round(metrics.win_rate, 4) if metrics else None,
            "profit_factor": (
                None
                if metrics is None or metrics.profit_factor == float("inf")
                else round(metrics.profit_factor, 6)
            ),
            "total_r": round(metrics.total_r, 6) if metrics else None,
            "net_pnl": round(metrics.net_pnl, 2) if metrics else None,
            "max_drawdown_pct": round(metrics.max_drawdown_pct, 4) if metrics else None,
            "total_return_pct": round(result.total_return_pct, 4),
            "strategy": strategy.params_version,
            "evidence": {
                "verdict": evidence.verdict.value,
                "mean_r": round(evidence.mean_r, 6),
                "ci_low": round(evidence.ci_low, 6),
                "ci_high": round(evidence.ci_high, 6),
                "confidence": evidence.confidence,
                "trades_needed": evidence.trades_needed,
            },
        }
    finally:
        conn.close()


def run_baseline(
    verified: VerifiedBaseline,
    config: Config,
    *,
    code_commit: str,
    scenarios: tuple[CostScenario, ...] = DEFAULT_SCENARIOS,
    starting_equity: float = 100_000.0,
) -> dict[str, Any]:
    """Baseline uzerinde her maliyet senaryosunu kosar ve raporu dondurur."""
    manifest = verified.manifest
    config = config.model_copy(update={"symbols": tuple(manifest["symbols"])})
    timeframe = Timeframe(manifest["timeframe"])

    results = [
        _run_scenario(verified, config, item, starting_equity=starting_equity, timeframe=timeframe)
        for item in scenarios
    ]
    return {
        "report_schema": REPORT_SCHEMA_VERSION,
        "dataset_id": verified.dataset_id,
        "manifest_sha256": verified.manifest_sha256,
        "baseline_sessions": {
            "first": min(verified.days).isoformat(),
            "last": max(verified.days).isoformat(),
            "count": len(verified.days),
        },
        # Holdout hakkinda YALNIZCA sayi. Tarihler bile yazilmiyor:
        # hangi gunlerin ayrildigini bilmek, o gunlere dair bir sey
        # hatirlamaya davetiyedir.
        "holdout": {"sessions": len(manifest["split"]["holdout"]), "opened": False},
        "code_commit": code_commit,
        "config_sha256": _config_sha256(config),
        "deterministic": True,
        "starting_equity": starting_equity,
        "primary_scenario": PRIMARY_SCENARIO,
        "scenarios": results,
        "caveats": list(CAVEATS),
    }


def report_bytes(report: dict[str, Any]) -> bytes:
    """Raporun kanonik baytlari - iki kosunun ayni olup olmadigini bu soyler."""
    return canonical_json(report)
