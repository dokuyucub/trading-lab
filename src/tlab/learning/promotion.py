"""Bir degisikligin gercek para yoluna alinip alinmayacagina karar verir.

Bu kapi risk kapisiyla ayni disiplinde yazildi: ILK OLUMSUZLUKTA
DURMAZ. Butun kontrolleri isletir ve hepsinin sonucunu doner. Sebebi
pratik - "neden terfi etmedi" sorusunun cevabi tek bir madde degil
genellikle uc madde olur, ve kisa devre yapan bir kapi her seferinde
yalnizca ilkini gosterip digerlerini sirayla kesfettirir.

Kapinin duruşu bilincli olarak muhafazakar: ILERI YON PAHALI, geri
yon ucuz. Kotu bir ayari canliya almak para kaybettirir; iyi bir
ayari birkac hafta daha beklemek yalnizca kazanci geciktirir. Bu
asimetri yuzunden varsayilan cevap HOLD - kanit yoksa hicbir sey
degismez.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from tlab.learning.evidence import DEFAULT_ITERATIONS, Evidence, Verdict, assess, compare


class PromotionDecision(StrEnum):
    PROMOTE = "promote"
    """Aday, mevcut ayarin yerini alir."""

    HOLD = "hold"
    """Yeterli kanit yok. Mevcut ayar KORUNUR, aday izlenmeye devam eder."""

    REJECT = "reject"
    """Aday kanitli sekilde kotu. Izlemeden cikarilir."""


@dataclass(frozen=True)
class PromotionPolicy:
    """Terfi esikleri.

    Varsayilanlar sikidir ve oyle olmali: bu kapinin yanlis
    "evet"inin bedeli, yanlis "hayir"inin bedelinden cok daha buyuk.
    """

    min_trades: int = 100
    confidence: float = 0.95

    min_edge_r: float = 0.10
    """Adayin temeli GECMESI gereken fark.

    Bu varsayilan tahminle degil OLCUMLE secildi. Kapiyi ilk yazdigimda
    esik 0,0 idi - yani "fark sifirdan ayirt edilebiliyor mu". Iki saf
    gurultu kumesiyle denedigim ilk ornekte kapi TERFI VERDI. 100
    bagimsiz gurultu ciftiyle olctugumde (n=300, sigma=1R):

        %95 guven, esik 0,00 R  ->  yanlis terfi %1,  0,3R avantaji %97 yakalaniyor
        %99 guven, esik 0,00 R  ->  yanlis terfi %1,  0,3R avantaji %84 yakalaniyor
        %95 guven, esik 0,10 R  ->  yanlis terfi %0,  0,3R avantaji %73 yakalaniyor
        %99 guven, esik 0,10 R  ->  yanlis terfi %0,  0,3R avantaji %51 yakalaniyor

    Tablonun soyledigi sey sezgiye aykiri: koruyan sey GUVEN SEVIYESI
    DEGIL, POZITIF ESIK. Guveni %95'ten %99'a cikarmak yanlis terfiyi
    azaltmadi, yalnizca gercek avantaji kacirma oranini ikiye katladi.
    Esigi 0,10 R'ye cekmek ise yanlis terfiyi sifirladi.

    Sebebi sade: sifir esikle, gurultunun 2 standart hatalik siradan
    bir dalgalanmasi yetiyor. 0,10 R esikle ayni sonucu uretmek icin
    gurultunun 3 standart hatayi asmasi gerekiyor ki bu cok daha nadir.

    Pratik anlami da var: 0,10 R'nin altindaki bir avantaj zaten
    komisyon ve kaymayla silinir. Kapiyi ayirt EDEBILDIGI degil,
    ISE YARADIGI seviyeye kuruyoruz.
    """

    candidates_considered: int = 1
    """Bu degerlendirme turunda kac aday sinandi.

    Tek bir adayda %5 yanilma payi kabul edilebilir; her gece yirmi
    aday sinanirsa aralarindan birinin sansla gecmesi neredeyse
    kesinlesir. Ne kadar cok bakarsan, gurultude o kadar cok desen
    gorursun. Bu sayi verilirse guven seviyesi aday basina
    sikilastirilir (Bonferroni); varsayilan 1, yani duzeltme yok.
    """

    require_absolute_edge: bool = True
    """Aday ayrica kendi basina karli olmali.

    Bu madde olmadan kapi, kaybeden bir temeli daha az kaybeden bir
    adayla degistirmeye izin verirdi - ikisi de para kaybettirirken.
    """

    min_absolute_r: float = 0.05
    """Adayin kendi basina asmasi gereken beklenen deger.

    Bu da olcumle secildi. Mutlak kontrolun esigi 0,0 iken, temel
    KANITLI SEKILDE KAYBEDEN oldugunda (-0,5 R) saf gurultuden ibaret
    bir aday 100 denemenin 2'sinde terfi aldi: fark gercekten buyuk
    oldugu icin karsilastirma kontrolu hakli olarak geciyor, ve
    gurultunun sifirin biraz ustune dustugu durumlarda mutlak kontrol
    de geciyordu.

    Kotu bir temeli birakmak dogru olabilir - ama yerine KANITI
    OLMAYAN bir sey koymak, hicbir sey yapmamaktan iyi degil. Kucuk
    bir pozitif taban bu boslugu kapatiyor; 0,05 R, islem
    maliyetlerinin altinda kalan bir avantajin zaten gercek
    olmadigini soyluyor.
    """

    iterations: int = DEFAULT_ITERATIONS
    seed: int = 0

    @property
    def effective_confidence(self) -> float:
        """Aday sayisina gore sikilastirilmis guven seviyesi."""
        if self.candidates_considered <= 1:
            return self.confidence
        return 1.0 - (1.0 - self.confidence) / self.candidates_considered


@dataclass(frozen=True)
class PromotionResult:
    decision: PromotionDecision
    candidate: Evidence
    """Adayin kendi basina karliligi (mutlak esik karsisinda)."""

    difference: Evidence
    """Aday ile temel arasindaki farkin kaniti."""

    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Kapiyi bu karara goturen TUM maddeler, ilkinde durmadan."""

    evaluation_eligible: bool = True

    @property
    def promoted(self) -> bool:
        return self.decision is PromotionDecision.PROMOTE

    def report(self) -> str:
        lines = [
            f"  karar      : {self.decision.value.upper()}",
            f"  aday       : {self.candidate.report()}",
            f"  fark       : {self.difference.report()}",
        ]
        if not self.evaluation_eligible:
            lines.append("  veri       : dogrulanmamis bilgi iceriyor")
        lines.extend(f"  - {reason}" for reason in self.reasons)
        return "\n".join(lines)


def decide_promotion(
    candidate_r: Sequence[float],
    baseline_r: Sequence[float],
    policy: PromotionPolicy | None = None,
    evaluation_eligible: bool = True,
) -> PromotionResult:
    """Aday mevcut ayarin yerini alabilir mi.

    `evaluation_eligible`, degerlendirmeyi besleyen verinin gecmiste
    gercekten bilinebilir oldugunu soyler (#12'deki as-of kurali).
    False ise kapi hicbir kosulda terfi vermez: bugun indirilmis bir
    takvimle olculmus bir avantaj, gelecegi bilerek islem yapmanin
    baska bir adidir. Bayrak disaridan gelir - bu katman verinin
    kaynagini bilmez, yalnizca kurali uygular.
    """
    policy = policy or PromotionPolicy()

    candidate = assess(
        candidate_r,
        threshold_r=policy.min_absolute_r,
        min_trades=policy.min_trades,
        confidence=policy.effective_confidence,
        iterations=policy.iterations,
        seed=policy.seed,
    )
    difference = compare(
        candidate_r,
        baseline_r,
        min_edge_r=policy.min_edge_r,
        min_trades=policy.min_trades,
        confidence=policy.effective_confidence,
        iterations=policy.iterations,
        seed=policy.seed,
    )

    reasons: list[str] = []
    blocking = False
    rejecting = False

    if not evaluation_eligible:
        reasons.append(
            "degerlendirme verisi gecmiste dogrulanabilir degil; terfi hicbir kosulda verilmez"
        )
        blocking = True

    if difference.verdict is Verdict.INSUFFICIENT_DATA:
        reasons.append(
            f"karsilastirma icin islem sayisi yetersiz: {difference.trades} < "
            f"{policy.min_trades} (tahmini gereken: {difference.trades_needed})"
        )
        blocking = True
    elif difference.verdict is Verdict.INCONCLUSIVE:
        reasons.append(
            f"fark gurultuden ayirt edilemiyor: aralik "
            f"[{difference.ci_low:+.3f}, {difference.ci_high:+.3f}] "
            f"esigi ({policy.min_edge_r:+.3f} R) kapsiyor"
        )
        blocking = True
    elif difference.verdict is Verdict.WORSE:
        reasons.append(
            f"aday temelden kanitli sekilde kotu: ust sinir "
            f"{difference.ci_high:+.3f} R < esik {policy.min_edge_r:+.3f} R"
        )
        rejecting = True

    if policy.require_absolute_edge:
        if candidate.verdict is Verdict.WORSE:
            reasons.append(
                f"aday kendi basina kanitli sekilde yetersiz: ust sinir "
                f"{candidate.ci_high:+.3f} R < taban {policy.min_absolute_r:+.3f} R"
            )
            rejecting = True
        elif candidate.verdict is not Verdict.BETTER:
            reasons.append(
                f"adayin kendi karliligi kanitlanmadi: aralik "
                f"[{candidate.ci_low:+.3f}, {candidate.ci_high:+.3f}] ({candidate.verdict.value})"
            )
            blocking = True

    if rejecting:
        decision = PromotionDecision.REJECT
    elif blocking:
        decision = PromotionDecision.HOLD
    else:
        decision = PromotionDecision.PROMOTE
        reasons.append(
            f"aday {difference.trades} islemde temeli {difference.ci_low:+.3f} R alt siniriyla "
            f"geciyor ve kendi basina karli"
        )

    return PromotionResult(
        decision=decision,
        candidate=candidate,
        difference=difference,
        reasons=tuple(reasons),
        evaluation_eligible=evaluation_eligible,
    )
