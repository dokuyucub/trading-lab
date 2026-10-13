"""Hesaplanmamis guven araligi sayi gibi gorunmez (#17, 2026-10-13).

2026-10-13 SIP raporunda dort satirin hepsinde `ci_low = ci_high = mean_r`
yaziyordu: `assess` 100 islemin altinda bootstrap'i calistirmiyor ve iki
alana ortalamayi koyuyordu. Bu, sifir genislikli kesin bir aralik gibi
okunabiliyordu. Artik hesaplanmayan uc `None`, raporda `null` ve
`ci_status: not_computed`; insan metni "hesaplanmadi" der.

Bu dosya iki seyi birlikte gosterir:

* KARAR MATEMATIGI AYNI. Asagidaki "once" degerleri degisiklikten once
  main `01cff5f` kodundan alindi. Karar, islem sayisi, ortalama ve
  `trades_needed` birebir ayni; hesaplanmis araliklar da ayni. Degisen
  yalnizca yer tutucu uclar.
* DURUM ESITLIKTEN CIKARILMAZ. Ozdes degerlerde bootstrap gercekten
  sifir genislikli bir aralik hesaplar; o `computed` kalir.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_baseline_job import measure, prepare
from tlab.backtest.baseline import (
    CI_COMPUTED,
    CI_NOT_COMPUTED,
    REPORT_SCHEMA_VERSION,
    evidence_payload,
)
from tlab.data.dataset import canonical_json
from tlab.learning import Evidence, PromotionPolicy, Verdict, assess, compare, decide_promotion


def series(n: int, mean: float, spread: float = 1.0) -> list[float]:
    """Rastgelesiz, belirlenimci bir R dizisi (ortalamasi tam `mean` degil)."""
    return [mean + spread * (((i * 37) % 23) - 11) / 11 for i in range(n)]


Row = tuple[str, int, float, float, float, int]
"""(karar, islem, ortalama, once ci_low, once ci_high, trades_needed)."""

ASSESS_INPUTS: dict[str, list[float]] = {
    "bos": [],
    "tek": [0.7],
    "iki": series(2, 0.2),
    "elli_pozitif": series(50, 0.15),
    "kirk_alti_kucuk_pozitif": series(46, 0.05),
    "doksan_dokuz_negatif": series(99, -0.05),
    "yuz_belirsiz": series(100, 0.02),
    "ikiyuzelli_kotu": series(250, -0.4),
    "yuz_ozdes_pozitif": [0.3] * 100,
    "yuz_ozdes_sifir": [0.0] * 100,
}

ASSESS_BEFORE: dict[str, Row] = {
    "bos": ("insufficient_data", 0, 0.0, 0.0, 0.0, 100),
    "tek": ("insufficient_data", 0, 0.0, 0.0, 0.0, 100),
    "iki": (
        "insufficient_data",
        2,
        -0.16363636363636366,
        -0.16363636363636366,
        -0.16363636363636366,
        100,
    ),
    "elli_pozitif": (
        "insufficient_data",
        50,
        0.1390909090909091,
        0.1390909090909091,
        0.1390909090909091,
        100,
    ),
    "kirk_alti_kucuk_pozitif": (
        "insufficient_data",
        46,
        0.05000000000000002,
        0.05000000000000002,
        0.05000000000000002,
        559,
    ),
    "doksan_dokuz_negatif": (
        "insufficient_data",
        99,
        -0.06193755739210286,
        -0.06193755739210286,
        -0.06193755739210286,
        100,
    ),
    "yuz_belirsiz": (
        "inconclusive",
        100,
        0.003636363636363651,
        -0.11999999999999998,
        0.12181818181818184,
        106043,
    ),
    "ikiyuzelli_kotu": (
        "worse",
        250,
        -0.39927272727272733,
        -0.47490909090909095,
        -0.32109090909090915,
        100,
    ),
    "yuz_ozdes_pozitif": ("better", 100, 0.3, 0.3, 0.3, 100),
    "yuz_ozdes_sifir": ("inconclusive", 100, 0.0, 0.0, 0.0, 100),
}
"""main `01cff5f` ile `assess` varsayilanlari (esik 0, taban 100, %95,
2000 tekrar, tohum 0). Yetersiz satirlarin `ci` degerleri o zamanin YER
TUTUCULARIDIR; artik `None` beklenir."""

COMPARE_INPUTS: dict[str, tuple[list[float], list[float]]] = {
    "aday_tek": ([0.5], series(10, 0.0)),
    "yetersiz": (series(60, 0.3), series(80, 0.1)),
    "yetersiz_tahmin": (series(46, 0.15), series(46, 0.1)),
    "yetersiz_negatif": (series(46, 0.0), series(46, 0.1)),
    "yeterli": (series(150, 0.3), series(200, 0.0)),
    "ozdes": ([0.2] * 120, [0.2] * 120),
}

COMPARE_BEFORE: dict[str, Row] = {
    "aday_tek": ("insufficient_data", 1, 0.0, 0.0, 0.0, 100),
    "yetersiz": (
        "insufficient_data",
        60,
        0.20984848484848484,
        0.20984848484848484,
        0.20984848484848484,
        100,
    ),
    "yetersiz_tahmin": ("insufficient_data", 46, 0.05, 0.05, 0.05, 559),
    "yetersiz_negatif": (
        "insufficient_data",
        46,
        -0.09999999999999999,
        -0.09999999999999999,
        -0.09999999999999999,
        100,
    ),
    "yeterli": (
        "better",
        150,
        0.2984848484848484,
        0.16818181818181815,
        0.4318181818181818,
        100,
    ),
    "ozdes": ("inconclusive", 120, 0.0, 0.0, 0.0, 100),
}
"""main `01cff5f` ile `compare` varsayilanlari (esik 0, taban 100)."""


def check_against_before(evidence: Evidence, before: Row) -> None:
    verdict, trades, mean_r, ci_low, ci_high, needed = before
    assert evidence.verdict.value == verdict
    assert evidence.trades == trades
    assert evidence.mean_r == mean_r
    assert evidence.trades_needed == needed
    if verdict == Verdict.INSUFFICIENT_DATA.value:
        # Tek degisen: yer tutucu uclar.
        assert (evidence.ci_low, evidence.ci_high) == (None, None)
        assert not evidence.interval_computed
    else:
        assert (evidence.ci_low, evidence.ci_high) == (ci_low, ci_high)
        assert evidence.interval_computed


@pytest.mark.parametrize("name", sorted(ASSESS_INPUTS))
def test_assess_decisions_are_unchanged(name: str) -> None:
    check_against_before(assess(ASSESS_INPUTS[name]), ASSESS_BEFORE[name])


@pytest.mark.parametrize("name", sorted(COMPARE_INPUTS))
def test_compare_decisions_are_unchanged(name: str) -> None:
    candidate, baseline = COMPARE_INPUTS[name]
    check_against_before(compare(candidate, baseline), COMPARE_BEFORE[name])


ALL_CASES = [f"assess:{name}" for name in ASSESS_INPUTS] + [
    f"compare:{name}" for name in COMPARE_INPUTS
]


def evidence_for(case: str) -> Evidence:
    kind, name = case.split(":")
    if kind == "assess":
        return assess(ASSESS_INPUTS[name])
    return compare(*COMPARE_INPUTS[name])


@pytest.mark.parametrize("case", ALL_CASES)
def test_status_number_and_text_agree(case: str) -> None:
    """Her vakada: rapor durumu, rapor sayilari ve insan metni ayni seyi
    soyler. Ve `insufficient_data` <=> aralik hesaplanmadi: bootstrap
    yalnizca `min_trades` tabanindan sonra calisir ve o dal yetersiz
    karar vermez. Tutarli ama yanlis bir yer tutucu da burada durur."""
    evidence = evidence_for(case)
    payload = evidence_payload(evidence)
    text = evidence.report()
    if evidence.interval_computed:
        assert evidence.verdict is not Verdict.INSUFFICIENT_DATA
        assert payload["ci_status"] == CI_COMPUTED
        assert isinstance(payload["ci_low"], float)
        assert isinstance(payload["ci_high"], float)
        assert "aralik [" in text
        assert "hesaplanmadi" not in text
    else:
        assert payload["ci_status"] == CI_NOT_COMPUTED
        assert payload["ci_low"] is None and payload["ci_high"] is None
        assert "hesaplanmadi" in text
        assert "[" not in text
        assert evidence.verdict is Verdict.INSUFFICIENT_DATA


@pytest.mark.parametrize("name", ["yuz_ozdes_pozitif", "yuz_ozdes_sifir"])
def test_a_real_zero_width_interval_stays_computed(name: str) -> None:
    """Ozdes degerlerde bootstrap gercekten sifir genislikli bir aralik
    hesaplar. Esitlik 'hesaplanmadi' demek degildir."""
    evidence = assess(ASSESS_INPUTS[name])
    assert evidence.ci_low == evidence.ci_high == evidence.mean_r
    assert evidence.interval_computed
    assert evidence_payload(evidence)["ci_status"] == CI_COMPUTED
    assert evidence.interval() == (evidence.mean_r, evidence.mean_r)


def evidence_with(ci_low: float | None, ci_high: float | None) -> Evidence:
    return Evidence(
        trades=120,
        mean_r=0.1,
        ci_low=ci_low,
        ci_high=ci_high,
        confidence=0.95,
        threshold_r=0.0,
        verdict=Verdict.INCONCLUSIVE,
        trades_needed=100,
    )


def test_an_interval_cannot_be_half_computed() -> None:
    with pytest.raises(ValueError, match="iki ucu"):
        evidence_with(None, 0.2)
    with pytest.raises(ValueError, match="iki ucu"):
        evidence_with(-0.1, None)
    assert evidence_with(-0.1, 0.2).interval() == (-0.1, 0.2)


def test_a_missing_interval_is_never_used_as_numbers() -> None:
    evidence = assess(ASSESS_INPUTS["elli_pozitif"])
    with pytest.raises(ValueError, match="hesaplanmadi"):
        evidence.interval()


def test_the_report_writes_null_not_a_placeholder() -> None:
    payload = evidence_payload(assess(ASSESS_INPUTS["doksan_dokuz_negatif"]))
    raw = canonical_json(payload)
    assert b'"ci_low":null' in raw
    assert b'"ci_high":null' in raw
    assert b'"ci_status":"not_computed"' in raw


def test_trades_needed_text_separates_floor_from_estimate() -> None:
    """Ortalama esigin altindayken `trades_needed` yalnizca tabandir; olumlu
    bir fark icin tahmin degildir ve 'N islem olunca kanitlanir' denmez."""
    floor = assess(ASSESS_INPUTS["doksan_dokuz_negatif"])
    assert floor.trades_needed == 100
    assert "taban 100" in floor.needed_text()
    assert "tahmini yok" in floor.needed_text()
    assert "kaba tahmin" not in floor.needed_text()

    estimate = assess(ASSESS_INPUTS["kirk_alti_kucuk_pozitif"])
    assert estimate.trades_needed == 559
    assert "kaba tahmin 559" in estimate.needed_text()


POLICY = PromotionPolicy(iterations=400)


def test_an_insufficient_candidate_shows_no_interval_in_the_gate() -> None:
    """Karar ayni (HOLD); gerekce artik yer tutucuyu aralik diye gostermez."""
    result = decide_promotion(series(30, 0.4), series(30, 0.0), POLICY)
    assert result.candidate.verdict is Verdict.INSUFFICIENT_DATA
    assert result.difference.verdict is Verdict.INSUFFICIENT_DATA
    assert result.decision.value == "hold"

    candidate_reason = next(r for r in result.reasons if "adayin kendi karliligi" in r)
    assert "aralik hesaplanmadi (yetersiz veri: 30 islem)" in candidate_reason
    assert "[" not in candidate_reason

    lines = result.report().splitlines()
    for label in ("aday", "fark"):
        line = next(line for line in lines if line.strip().startswith(label))
        assert "hesaplanmadi" in line
        assert "[" not in line


@pytest.mark.parametrize(
    ("candidate_mean", "expected", "forbidden"),
    [(0.4, "kaba tahmin", "gereken: taban"), (0.0, "gereken: taban", "kaba tahmin")],
)
def test_an_insufficient_difference_names_floor_or_estimate(
    candidate_mean: float, expected: str, forbidden: str
) -> None:
    result = decide_promotion(series(30, candidate_mean), series(30, 0.2), POLICY)
    reason = next(r for r in result.reasons if "islem sayisi yetersiz" in r)
    assert "aralik hesaplanmadi" in reason
    assert expected in reason
    assert forbidden not in reason


def test_the_measurement_report_marks_missing_intervals(tmp_path: Path) -> None:
    """Gercek olcum adimi, sentetik onayli veriyle: az islemli senaryolarda
    aralik `null`, durum `not_computed`, karar `insufficient_data`."""
    assert measure(tmp_path, prepare(tmp_path)) == 0
    report = json.loads((tmp_path / "report.json").read_bytes())
    assert report["report_schema"] == REPORT_SCHEMA_VERSION == 4

    statuses = set()
    for row in report["scenarios"]:
        evidence = row["evidence"]
        statuses.add(evidence["ci_status"])
        if evidence["ci_status"] == CI_NOT_COMPUTED:
            assert evidence["ci_low"] is None and evidence["ci_high"] is None
            assert evidence["verdict"] == Verdict.INSUFFICIENT_DATA.value
        else:
            assert evidence["ci_status"] == CI_COMPUTED
            assert isinstance(evidence["ci_low"], float)
    assert statuses == {CI_NOT_COMPUTED}
