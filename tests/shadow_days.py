"""Golge gozlem testleri icin sozlesmeye uyan gun ozetleri (tasarim §6).

Gozlem isinin yazdigi bicim: bas (`DAY_HEAD`) ve tamamlanan gunde butun
govde (`DAY_BODY`). Testler buradan baslayip tek alani bozar.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from tlab import shadow_job
from tlab.config import load_config
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

TURNS = 106
"""Varsayilan ORB: acilis araligi 15. dakikadan giris penceresi 120. dakikaya."""
PARAMS_VERSION = OpeningRangeBreakout(ORBParams()).params_version
RUN_ID = 11
CODE_SHA = "a" * 40
SOURCE_ENV = {"GITHUB_RUN_ID": str(RUN_ID), "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": CODE_SHA}
"""Gozlem ve gec kayit adimlarinin gun ozetine yazdigi kaynak kimligi."""


def symbols_of(root: Path) -> tuple[str, ...]:
    return tuple(load_config(root).symbols)


def campaign(root: Path, planned: Sequence[date]) -> str:
    return shadow_job.campaign_of(planned, symbols_of(root), root)


def no_sip(symbol: str, **overrides: Any) -> dict[str, Any]:
    """SIP'i gelmemis sembol: SIP'e dayanan hicbir alan yok, sinyal bilinmiyor."""
    fields: dict[str, Any] = {
        "sip_present": None,
        "or_high_bps": None,
        "or_low_bps": None,
        "range_status": "sip_yok",
        "signal": "unknown",
        "sip_first_minute": None,
        "sip_available": False,
    }
    return comparison(symbol, **{**fields, **overrides})


def comparison(symbol: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "symbol": symbol,
        "window_expected": 15,
        "iex_present": 15,
        "sip_present": 15,
        "iex_completed_later": False,
        "or_high_bps": 0.5,
        "or_low_bps": -0.5,
        "range_status": "hesaplandi",
        "signal": "none",
        "iex_first_minute": None,
        "sip_first_minute": None,
        "iex_unknown_turns": 0,
        "sip_available": True,
    }
    item.update(overrides)
    return item


def day_payload(
    root: Path,
    planned: Sequence[date],
    day: date,
    status: str = "tamam",
    reason: str | None = None,
    /,
    **overrides: Any,
) -> dict[str, Any]:
    """Tamamlanan gun butun govdeyle; eksik gun yalnizca basla (gec kayit gibi).

    Konumsal parametreler yalnizca konumla verilir: `overrides` her alani,
    `day`, `status`, `reason` ve `run_id` dahil, oldugu gibi uzerine yazar.
    Kaynak kimligi varsayilan olarak `RUN_ID` / 1 / `CODE_SHA`.
    """
    symbols = symbols_of(root)
    payload: dict[str, Any] = {
        "day_schema": shadow_job.DAY_SCHEMA,
        "day": day.isoformat(),
        "campaign": campaign(root, planned),
        "run_id": RUN_ID,
        "run_attempt": 1,
        "code_sha": CODE_SHA,
        "status": status,
        "reason": reason,
    }
    if status == "tamam":
        payload.update(
            {
                "params_version": PARAMS_VERSION,
                "clock_consistent": True,
                "turns": {"expected": TURNS, "called": TURNS, "failed": 0, "missed": 0},
                "symbol_turns": {
                    "expected": TURNS * len(symbols),
                    "observed": TURNS * len(symbols),
                },
                "sip_reasons": {},
                "live_pure_mismatches": 0,
                "symbols": [comparison(symbol) for symbol in symbols],
            }
        )
    payload.update(overrides)
    return payload


def write_day(directory: Path, payload: dict[str, Any], name: str | None = None) -> Path:
    path = directory / (name or f"{payload['day']}.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
