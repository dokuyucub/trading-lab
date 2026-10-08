"""Ilk SIP olcumunun dondurma kaydi (AGENTS §11.5, #17).

Onayla birlikte, P&L gorulmeden sabitlenenler burada. Olcum raporu
`code_commit`, `config`, `config_sha256` ve her senaryoda strateji
surumunu tasir; inceleme bunlari onaydakilerle karsilastirir (§11.4
karar kurali). Bu test o kurali kirmiziya donen bir denetime baglar:
onaydan olcume kadar bunlardan biri KAZARA degisirse test durur.

Beklenen degerler SOMUT ve onay incelemesinde bildirilen degerlerdir;
uretim sabitlerinden turetilmez. Bu degerleri degistirmek yeni ve
kayitli bir degerlendirme karari gerektirir (Codex, #17 6067588608).

Genel bir gelistirme kilidi DEGILDIR. Dondurma yalnizca BU degerlendirme
beklerken gecerlidir: aktif ana tanim bu kayittaki tanim ve yurutme
kaydi henuz yok (`freeze_applies`). Yurutme kaydedildiginde (§7) ya da
aktif ana tanim degistiginde kayit tarihsel kalir; baska veri kumesi ya
da strateji gelistirmesini kilitlemez. Bu gecis kendiliginden olmaz:
`executed` alani ve asagidaki "bugun bekliyor" iddiasi ayni kayitli
degisiklikte guncellenir.

KAYIT (testle dogrulanmaz): onayin dayandigi main `544c371` (#44
birlesmesi). Onay commit'i kendi kimligini tasimaz; PR head ve merge
kimligi inceleme ve devir kaydindan baglanir (Codex, #17 6067241410).

TESTLE DOGRULANAN: olculecek tanimin onayli hash'i; olcum evrenine
normalize config'in semantik hash'i; strateji parametreleri ve surumu;
dort maliyet senaryosu ve birincil senaryo; kanit kuralinin varsayilanlari;
sentetik baslangic ozsermayesi; rapor semasi.

GERCEK olcum yolunda (`baseline_job.measure` -> `run_baseline`) sentetik
veriyle ayrica olculenler: strateji surumu, dort senaryo, birincil
senaryo, ozsermaye, sema ve kanit kurali cagrisinin degismedigi. Iki
hash bu yoldan gecmez: tanim hash'i olculecek dosyadan, config hash'i
`run_baseline` ile ayni bicimde hesaplanir (test_report_feed bu bicimin
rapordakine esit oldugunu gosterir).
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from test_baseline_job import prepare
from test_dataset_specs import APPROVED_MAIN_SHA256
from tlab import baseline_job
from tlab.backtest import baseline as baseline_module
from tlab.backtest.baseline import PRIMARY_SCENARIO, REPORT_SCHEMA_VERSION, run_baseline
from tlab.config import load_config
from tlab.data.dataset import DatasetSpec, canonical_json
from tlab.learning import assess
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

REPO = Path(__file__).resolve().parents[1]

FREEZE: dict[str, Any] = {
    "source_main": "544c37143c89eb79ca22de88e9be2725b8d45e6f",
    "dataset_id": "orb-baseline-2026q3-u11-sip",
    "spec_sha256": APPROVED_MAIN_SHA256,
    "config_sha256": "14c5141e46e3496ca9cd9cc65e61cd53e4981934ced2cca2aa794fb3436396c8",
    "strategy": "orb-7b32942a",
    "primary_scenario": "temel",
    "starting_equity": 100_000.0,
    "report_schema": 3,
    "executed": None,
}
"""Onay incelemesinde bildirilen kimlikler (#17 6067224557, Codex
6067588608). `source_main` KAYITTIR; `executed` yurutme kaydidir (henuz
yok: gercek kosu ayri ve kayitli bir karar). Geri kalani asagidaki
testlerle dogrulanir."""

STRATEGY_PARAMS: dict[str, Any] = {
    "opening_range_minutes": 15,
    "entry_window_minutes": 120,
    "atr_period": 14,
    "rvol_lookback": 20,
    "min_rvol": 1.2,
    "target_r": 1.5,
    "max_extension_atr": 1.0,
    "min_stop_atr_frac": 0.25,
    "min_stop_bps": 10.0,
    "entry_offset_bps": 5.0,
    "allow_short": True,
}
"""`orb-7b32942a`: olcumun kullandigi `ORBParams()` varsayilanlari."""

SCENARIOS: tuple[tuple[str, float, float, float], ...] = (
    ("iyimser", 0.5, 1.0, 0.0),
    ("temel", 1.0, 2.0, 0.0),
    ("kotumser", 3.0, 5.0, 0.0),
    ("sert", 5.0, 10.0, 0.0),
)
"""(ad, kayma bps, spread bps, komisyon bps) - rapordaki sirayla."""

EVIDENCE: dict[str, Any] = {
    "threshold_r": 0.0,
    "min_trades": 100,
    "confidence": 0.95,
    "iterations": 2000,
    "seed": 0,
}
"""Her senaryonun karari bu kuralla verilir; olcum varsayilani degistirmez."""


def freeze_applies(record: dict[str, Any], main_spec: Path) -> bool:
    """Dondurma YALNIZCA bu degerlendirme bekliyorken gecerli: aktif ana
    tanim kayittaki tanim ve yurutme kaydi henuz yok. Aksi halde kayit
    tarihseldir ve gelistirmeyi kilitlemez."""
    return record["executed"] is None and main_spec.stem == record["dataset_id"]


PENDING = freeze_applies(FREEZE, baseline_job.MAIN_SPEC)
pending = pytest.mark.skipif(
    not PENDING, reason="degerlendirme yurutuldu ya da aktif degil; kayit tarihsel"
)
"""Canli esitlik denetimleri. Bugun hepsi KOSAR: bkz.
`test_the_freeze_binds_only_the_pending_evaluation`."""


def test_the_freeze_binds_only_the_pending_evaluation() -> None:
    """Dondurma bir yasam dongusudur, genel bir kilit degil (Codex
    6067588608). BUGUN degerlendirme bekliyor: asagidaki canli denetimler
    sessizce atlanamaz. Yurutme kaydedilince bu iddia ayni kayitli
    degisiklikte guncellenir."""
    main_spec = baseline_job.MAIN_SPEC
    assert PENDING, "canli dondurma denetimleri atlaniyor; yurutme kaydi yok"
    assert freeze_applies(FREEZE, main_spec)
    assert not freeze_applies({**FREEZE, "executed": {"run_id": "1"}}, main_spec)
    assert not freeze_applies(FREEZE, main_spec.with_name("baska-tanim.yaml"))


def scenario_rows(report: dict[str, Any]) -> list[tuple[str, float, float, float]]:
    return [
        (row["name"], row["slippage_bps"], row["spread_bps"], row["commission_bps"])
        for row in report["scenarios"]
    ]


@pending
def test_the_measured_definition_is_the_approved_one() -> None:
    """Olcum isinin sabit yolu, onaylanan tanimi gosterir."""
    spec = DatasetSpec.from_yaml(REPO / baseline_job.MAIN_SPEC)
    digest = hashlib.sha256(canonical_json(spec.model_dump(mode="json"))).hexdigest()
    assert (spec.dataset_id, spec.status) == (FREEZE["dataset_id"], "approved")
    assert digest == FREEZE["spec_sha256"]


@pending
def test_the_measured_config_is_frozen() -> None:
    """Olcum evrenine normalize semantik config, `run_baseline` ile ayni
    bicimde (test_report_feed bu bicimin rapordakine esit oldugunu
    gosterir): semboller tanimdan, yerel yollar haric."""
    spec = DatasetSpec.from_yaml(REPO / baseline_job.MAIN_SPEC)
    config = load_config(REPO).model_copy(update={"symbols": spec.symbols})
    digest = hashlib.sha256(canonical_json(config.semantic_dump())).hexdigest()
    assert digest == FREEZE["config_sha256"]


@pending
def test_the_measured_strategy_is_frozen() -> None:
    params = ORBParams()
    assert params.model_dump() == STRATEGY_PARAMS
    assert OpeningRangeBreakout(params).params_version == FREEZE["strategy"]


@pending
def test_the_evidence_rule_is_frozen() -> None:
    defaults = {
        name: parameter.default
        for name, parameter in inspect.signature(assess).parameters.items()
        if parameter.default is not inspect.Parameter.empty
    }
    assert defaults == EVIDENCE


@pending
def test_the_report_constants_are_frozen() -> None:
    equity = inspect.signature(run_baseline).parameters["starting_equity"].default
    assert equity == FREEZE["starting_equity"]
    assert FREEZE["primary_scenario"] == PRIMARY_SCENARIO
    assert FREEZE["report_schema"] == REPORT_SCHEMA_VERSION


@pending
def test_the_real_measurement_path_uses_the_frozen_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gercek olcum adimi (`baseline_job.measure`), sentetik onayli veriyle:
    rapor dondurulan strateji surumunu, senaryolari, ozsermayeyi ve semayi
    tasir; ne `run_baseline` ne `assess` varsayilan disi bir degerle
    cagrilir. Sentetik islem sonuclari burada OLCULMEZ."""
    run_calls: list[dict[str, Any]] = []
    assess_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def recording_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        run_calls.append(kwargs)
        return run_baseline(*args, **kwargs)

    def recording_assess(*args: Any, **kwargs: Any) -> Any:
        assess_calls.append((args, kwargs))
        return assess(*args, **kwargs)

    # Olcum adimi fonksiyonu cagri aninda modulden alir.
    monkeypatch.setattr(baseline_module, "run_baseline", recording_run)
    monkeypatch.setattr(baseline_module, "assess", recording_assess)
    workdir = prepare(tmp_path)
    out = tmp_path / "report.json"
    code = baseline_job.measure({"GITHUB_SHA": "b" * 40}, workdir=workdir, out=out, root=REPO)
    assert code == 0, capsys.readouterr().out

    assert [set(kwargs) for kwargs in run_calls] == [{"code_commit"}]
    assert assess_calls and all(len(args) == 1 and kwargs == {} for args, kwargs in assess_calls)

    report = json.loads(out.read_bytes())
    assert report["report_schema"] == FREEZE["report_schema"]
    assert report["starting_equity"] == FREEZE["starting_equity"]
    assert report["primary_scenario"] == FREEZE["primary_scenario"]
    assert scenario_rows(report) == list(SCENARIOS)
    assert {row["strategy"] for row in report["scenarios"]} == {FREEZE["strategy"]}
    assert {row["evidence"]["confidence"] for row in report["scenarios"]} == {
        EVIDENCE["confidence"]
    }
