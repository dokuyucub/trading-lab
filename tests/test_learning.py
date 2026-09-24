"""Ogrenme katmani testleri.

Buradaki en onemli test `test_pure_noise_is_never_promoted`. Sebebi
yasanmis: bu kapinin ilk halini yazip iki saf gurultu kumesiyle
denedigimde TERFI VERDI. Kapi tam da engellemek icin yazildigi hatayi
yapti.

O yuzden gurultu testi bir "iyi olur" degil, bu katmanin varlik
sartidir. Kirilirsa, kapi ise yaramiyor demektir.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from tlab.learning import (
    PromotionDecision,
    PromotionPolicy,
    Verdict,
    assess,
    bootstrap_mean_ci,
    compare,
    decide_promotion,
    required_iterations,
    required_trades,
)
from tlab.learning.evidence import DEFAULT_ITERATIONS

FAST = PromotionPolicy(iterations=400)
"""Testlerde daha az bootstrap tekrari. Karari degistirmiyor,
yalnizca kosu suresini kisaltiyor."""


def noise(seed: int, count: int = 300, mean: float = 0.0) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(mean, 1.0) for _ in range(count)]


# --------------------------------------------------------------------------
# Kapinin varlik sebebi
# --------------------------------------------------------------------------


def test_pure_noise_is_never_promoted() -> None:
    """Iki saf gurultu kumesi arasinda terfi CIKMAMALI.

    Bu testin ilk hali kirmiziydi. Esik 0,0 R iken kapi, gurultunun
    siradan bir dalgalanmasini avantaj sanip terfi veriyordu.

    Daha genis bir olcumde oran %1 cikmisti - yani her gece calisan
    bir sistemde ayda birkac kez gurultuyu canliya alirdik. Duzeltme
    esigi 0,10 R'ye cekmekti; guven seviyesini yukseltmek ise ise
    yaramiyordu (yanlis terfiyi azaltmadan gercek avantaji
    kacirtiyordu).
    """
    promoted = [
        seed
        for seed in range(40)
        if decide_promotion(noise(10_000 + seed), noise(20_000 + seed), FAST).promoted
    ]
    assert not promoted, f"gurultu terfi aldi, tohumlar: {promoted}"


def test_noise_does_not_replace_a_losing_baseline() -> None:
    """Kotu temel, kaniti olmayan bir adayla degistirilmemeli.

    Ayri bir acik: fark gercekten buyuk oldugu icin karsilastirma
    kontrolu hakli olarak geciyor. Adayin KENDI karliligi
    kanitlanmadan terfi verilirse, kaybeden bir seyi bilinmeyen bir
    seyle degistirmis oluruz - bu bir ilerleme degil.
    """
    promoted = [
        seed
        for seed in range(30)
        if decide_promotion(noise(50_000 + seed), noise(60_000 + seed, mean=-0.5), FAST).promoted
    ]
    assert not promoted, f"gurultu, kaybeden temelin yerine gecti: {promoted}"


def test_a_real_edge_is_still_promoted() -> None:
    """Kapi her seyi reddetmemeli; yoksa ogrenme durur."""
    result = decide_promotion(noise(1, mean=0.5), noise(2), FAST)
    assert result.decision is PromotionDecision.PROMOTE
    assert result.difference.verdict is Verdict.BETTER


def test_a_proven_worse_candidate_is_rejected() -> None:
    result = decide_promotion(noise(3, mean=-0.4), noise(4, mean=0.4), FAST)
    assert result.decision is PromotionDecision.REJECT


# --------------------------------------------------------------------------
# Kararlilik ve durustluk
# --------------------------------------------------------------------------


def test_the_same_input_always_gives_the_same_answer() -> None:
    """Ayni girdi ayni cevabi vermeli.

    Her kosuda biraz farkli sonuc veren bir kapi, bir sonucun neden
    degistigini sormayi imkansiz hale getirir: kod mu degisti,
    strateji mi, yoksa zar mi belli olmaz.
    """
    candidate, baseline = noise(7, mean=0.4), noise(8)
    first = decide_promotion(candidate, baseline, FAST)
    second = decide_promotion(candidate, baseline, FAST)
    assert first == second


def test_too_few_trades_holds_however_good_the_numbers_look() -> None:
    """Az islem, rakamlar ne kadar parlaksa parlak olsun kanit degil."""
    result = decide_promotion([2.0] * 12, [-1.0] * 12, FAST)
    assert result.decision is PromotionDecision.HOLD
    assert any("islem sayisi yetersiz" in reason for reason in result.reasons)
    assert result.difference.trades_needed >= FAST.min_trades


def test_unverifiable_data_can_never_promote() -> None:
    """#12'deki as-of kurali: gecmiste dogrulanamayan veri terfi veremez.

    Avantaj ne kadar buyuk gorunurse gorunsun. Bugun indirilmis bir
    takvimle olculmus bir avantaj, gelecegi bilerek islem yapmanin
    baska bir adidir.
    """
    result = decide_promotion(noise(1, mean=1.0), noise(2), FAST, evaluation_eligible=False)
    assert result.decision is PromotionDecision.HOLD
    assert not result.evaluation_eligible
    assert any("dogrulanabilir degil" in reason for reason in result.reasons)


def test_the_gate_reports_every_failing_check_not_just_the_first() -> None:
    """Risk kapisiyla ayni disiplin: kisa devre yok.

    "Neden terfi etmedi" sorusunun cevabi genellikle tek madde
    degildir; kisa devre yapan bir kapi digerlerini sirayla
    kesfettirir ve her turda bir tanesini gosterir.
    """
    result = decide_promotion([0.001] * 150, [0.0] * 150, FAST)

    assert result.decision is not PromotionDecision.PROMOTE
    # Iki AYRI kontrol de raporlanmali: fark esigi gecmiyor VE adayin
    # kendi karliligi tabanin altinda. Kisa devre yapan bir kapi
    # yalnizca ilkini gosterirdi.
    assert any("temelden" in reason for reason in result.reasons)
    assert any("kendi basina" in reason for reason in result.reasons)


def test_considering_many_candidates_tightens_the_gate() -> None:
    """Ne kadar cok adaya bakarsan, gurultude o kadar cok desen gorursun."""
    single = PromotionPolicy(iterations=400)
    # Yirmi aday, daha dar bir kuyruk demek - ve o kuyrugu olcmek icin
    # cok daha fazla tekrar. Butce yetmezse politika kurulmuyor bile.
    budget = required_iterations(1.0 - (1.0 - single.confidence) / 20)
    twenty = PromotionPolicy(iterations=budget, candidates_considered=20)

    assert twenty.effective_confidence > single.effective_confidence
    assert single.effective_confidence == single.confidence
    assert budget > single.iterations


# --------------------------------------------------------------------------
# Olcum araclari
# --------------------------------------------------------------------------


def test_confidence_interval_brackets_the_true_mean() -> None:
    low, high = bootstrap_mean_ci(noise(11, count=500, mean=0.3), iterations=800)
    assert low < 0.3 < high


def test_interval_narrows_as_evidence_grows() -> None:
    """Daha cok islem, daha dar aralik. Ogrenmenin tek yolu bu."""
    narrow = bootstrap_mean_ci(noise(12, count=2000), iterations=600)
    wide = bootstrap_mean_ci(noise(12, count=120), iterations=600)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_halving_the_edge_quadruples_the_trades_needed() -> None:
    """Kucuk bir avantaji dogrulamanin neden aylar surdugu."""
    big = required_trades(edge_r=0.20, volatility_r=1.0)
    small = required_trades(edge_r=0.10, volatility_r=1.0)
    assert small == pytest.approx(big * 4, rel=0.05)


def test_assess_marks_a_losing_sample_as_worse() -> None:
    evidence = assess(noise(13, mean=-0.6), min_trades=100, iterations=400)
    assert evidence.verdict is Verdict.WORSE
    assert not evidence.is_proven


def test_inconclusive_is_not_treated_as_proven() -> None:
    """INCONCLUSIVE "muhtemelen iyidir" DEGILDIR; bilmiyoruz demektir."""
    evidence = assess(noise(14), min_trades=100, iterations=400)
    assert evidence.verdict is not Verdict.BETTER
    assert not evidence.is_proven


@pytest.mark.parametrize("values", [[], ()])
def test_empty_samples_are_insufficient_not_zero(values: list[float]) -> None:
    assert assess(values).verdict is Verdict.INSUFFICIENT_DATA
    assert compare(values, [1.0] * 200).verdict is Verdict.INSUFFICIENT_DATA
    with pytest.raises(ValueError, match="en az iki gozlem"):
        bootstrap_mean_ci(values)


@pytest.mark.parametrize("confidence", [0.0, 1.0, -0.1, 1.5])
def test_impossible_confidence_is_rejected(confidence: float) -> None:
    with pytest.raises(ValueError, match="guven seviyesi"):
        bootstrap_mean_ci([1.0, 2.0], confidence=confidence)


def test_report_is_readable() -> None:
    result = decide_promotion(noise(15, mean=0.5), noise(16), FAST)
    text = result.report()
    assert "PROMOTE" in text
    assert "R" in text


# --------------------------------------------------------------------------
# Kapinin kendi ayarlari da girdidir
#
# Asagidaki iki bolum Codex'in #15 incelemesindeki B1 ve B2 bulgulari.
# Ikisi de yeniden uretildi ve ikisi de gercekti.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"min_trades": 0}, "min_trades"),
        ({"min_trades": -1}, "min_trades"),
        ({"candidates_considered": 0}, "candidates_considered"),
        ({"iterations": 0}, "iterations"),
        ({"confidence": 1.0}, "confidence"),
        ({"min_edge_r": float("inf")}, "sonlu"),
        ({"min_absolute_r": float("nan")}, "sonlu"),
    ],
)
def test_a_nonsensical_policy_is_rejected_at_construction(
    changes: dict[str, Any], message: str
) -> None:
    """Dogrulanmayan bir politika kapinin amacini tersine cevirebiliyordu.

    `min_trades=0` kabul ediliyordu ve TEK BIR ISLEMLE terfi
    verilebiliyordu - bu kapinin varlik sebebinin tam tersi.
    """
    with pytest.raises(ValueError, match=message):
        PromotionPolicy(**changes)


def test_a_single_observation_can_never_promote() -> None:
    """Tek gozlemin yayilimi olculemez; kanit uretemez."""
    result = decide_promotion([1.0], [0.0], FAST)
    assert result.decision is not PromotionDecision.PROMOTE


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_rejected_not_silently_absorbed(bad: float) -> None:
    """Tek bir NaN butun olcumu sessizce bozar.

    Eskiden `assess` ham bir AttributeError ile duruyordu; sebebi
    hata mesajindan anlasilmiyordu.
    """
    with pytest.raises(ValueError, match="sonlu"):
        assess([bad] + [1.0] * 150, iterations=400)
    with pytest.raises(ValueError, match="sonlu"):
        compare([bad] + [1.0] * 150, [0.0] * 150, iterations=400)


def test_a_confidence_the_bootstrap_cannot_measure_is_refused() -> None:
    """Nominal guven seviyesi olcum cozunurlugunu asamaz.

    Bu en sinsi bulguydu. 2.000 tekrarla 1.000 ve 1.000.000 aday
    denendiginde raporlanan guven %99,995 ve %99,99999 oluyordu ama
    ARALIK IKISINDE DE AYNIYDI: istenen kuyruk yuzdeligi 2.000
    cekilisle orneklenemedigi icin indeks en uc degere sabitleniyordu.

    Yani kapi, sahip olmadigi bir hassasiyeti raporluyordu. Simdi
    kurulum aninda, sessizce degil, yuksek sesle duruyor.
    """
    with pytest.raises(ValueError, match="tekrar gerekir"):
        PromotionPolicy(candidates_considered=1000, iterations=DEFAULT_ITERATIONS)

    # Yeterli butce verilirse kabul ediliyor.
    enough = required_iterations(1.0 - (1.0 - 0.95) / 1000)
    assert PromotionPolicy(candidates_considered=1000, iterations=enough).iterations == enough


def test_required_iterations_grows_as_the_tail_gets_thinner() -> None:
    assert required_iterations(0.95) < required_iterations(0.99)
    assert required_iterations(0.99) < required_iterations(0.9999)


def test_bootstrap_refuses_a_budget_it_cannot_honour() -> None:
    with pytest.raises(ValueError, match="olculemez"):
        bootstrap_mean_ci([1.0, 2.0, 3.0], confidence=0.99, iterations=50)
