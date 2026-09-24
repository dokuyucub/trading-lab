"""Bir farkin gercek mi yoksa orneklem gurultusu mu oldugunu olcer.

Bu dosyanin varlik sebebi yasanmis bir olcum. Tamamen rastgele
yuruyusle uretilmis alti seride stratejinin beklenen degerini
olctugumde UCUNDE POZITIF cikti; en iyisi +0,061 R idi. Yani hicbir
sey bilmeyen bir uretecin ciktilari, tek bir sayiya bakan bir kapiyi
yarisindan fazlasinda gecebiliyor.

Sonuc su: "beklenen deger pozitif" bir kanit degildir. Kanit, farkin
orneklem gurultusuyle aciklanamayacak kadar buyuk olmasidir. Bu
dosya o ayrimi yapar; kapilar da yalnizca buna bakar.

BILINEN SINIR - bagimsizlik varsayimi: buradaki yeniden ornekleme
islemleri BAGIMSIZ kabul eder. Gercek islemler degildir; ayni gunun
islemleri ayni piyasa rejimini paylasir ve birlikte iyi ya da birlikte
kotu gider. Bu durumda gercek belirsizlik olculenden BUYUKTUR, yani
kapi olmasi gerektiginden biraz gevsek davranir. Journal'a baglanirken
gun/blok bazli yeniden ornekleme gerekiyor; o zamana kadar buradaki
araliklar iyimser taraftan okunmali.

Neden bootstrap, neden t-testi degil: R katsayilarinin dagilimi
simetrik degil. Asagi tarafi stop seviyesinde sinirli (kayiplar
-1R civarinda kumelenir), yukari tarafi ise acik uclu. t-testi
olmayan bir simetriyi varsayar ve kucuk orneklemde fazla dar
guven araligi uretir - yani tam da yanilmak istemedigimiz yerde
fazla guven verir. Bootstrap dagilimin seklini varsaymaz.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from statistics import NormalDist, fmean, pstdev

DEFAULT_ITERATIONS = 2_000
"""Bootstrap tekrar sayisi.

Yuzdelik guven araligi icin 2.000 tekrar yeterince kararli. Daha
yuksek deger araligi biraz daha stabil yapar ama karari degistirecek
bir fark uretmiyor; cevrimdisi calistigimiz icin hiz kritik degil,
yine de testlerin hizli kosmasi degerli.
"""


MIN_TAIL_SAMPLES = 10
"""Bir kuyruk yuzdeligini olcmek icin gereken asgari ornek sayisi.

Bootstrap'in cozunurlugu 1/tekrar ile sinirli. %99,995 guven istemek,
kuyrukta 0,00005'lik bir yuzdelik istemek demektir; 2.000 tekrarla bu
yuzdelik ORNEKLENEMEZ ve indeks en uc degere sabitlenir. Sonuc sinsi:
arac daha dar bir guven bildirir ama aslinda hala 2.000 cekilisin en
ucundaki sayiyi gosterir - yani sahip olmadigi bir hassasiyeti
raporlar.

10 asgari bir taban, garanti degil: daha az kuyruk orneginde yuzdelik
tahmini cok oynak olur.
"""


def _check_confidence(confidence: float) -> None:
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"guven seviyesi (0, 1) araliginda olmali: {confidence}")


def required_iterations(confidence: float) -> int:
    """Bu guven seviyesini GERCEKTEN olcebilmek icin gereken tekrar sayisi."""
    _check_confidence(confidence)
    tail = (1.0 - confidence) / 2.0
    return int(-(-MIN_TAIL_SAMPLES // tail))


def _check_budget(confidence: float, iterations: int) -> None:
    """Istenen guven seviyesi mevcut tekrar butcesiyle olculebiliyor mu."""
    needed = required_iterations(confidence)
    if iterations < needed:
        raise ValueError(
            f"%{confidence * 100:.5f} guven seviyesi {iterations} tekrarla olculemez; "
            f"en az {needed} gerekir. Daha dar bir guven bildirmek, sahip olunmayan "
            f"bir hassasiyeti raporlamak olur."
        )


def _check_finite(values: Sequence[float], label: str) -> None:
    """NaN/sonsuz bir R degeri sessizce butun olcumu bozar."""
    for index, value in enumerate(values):
        if not isfinite(value):
            raise ValueError(f"{label}[{index}] sonlu bir sayi degil: {value!r}")


def _z_for(confidence: float) -> float:
    """Iki yonlu guven seviyesinin z degeri.

    stdlib'deki NormalDist kullaniliyor: sabit bir tablo yalnizca
    birkac seviyeyi desteklerdi ve coklu karsilastirma duzeltmesi
    keyfi seviyeler uretiyor (ornegin 12 aday icin %99,58).
    """
    _check_confidence(confidence)
    return NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)


class Verdict(StrEnum):
    """Bir olcumun ne soyledigi."""

    INSUFFICIENT_DATA = "insufficient_data"
    """Islem sayisi az. Rakamlar ne kadar iyi gorunurse gorunsun
    bir sey soylemiyor."""

    INCONCLUSIVE = "inconclusive"
    """Yeterli veri var ama guven araligi esigi kapsiyor.
    Fark olabilir de olmayabilir de; kanit yok."""

    BETTER = "better"
    """Guven araliginin ALT ucu bile esigin ustunde."""

    WORSE = "worse"
    """Guven araliginin UST ucu bile esigin altinda."""


@dataclass(frozen=True)
class Evidence:
    """Bir R katsayisi kumesinin durust ozeti."""

    trades: int
    mean_r: float
    """Nokta tahmini. Tek basina asla karar dayanagi degil."""

    ci_low: float
    ci_high: float
    confidence: float
    threshold_r: float
    verdict: Verdict
    trades_needed: int
    """Bu buyuklukteki bir farki ayirt edebilmek icin gereken kaba
    islem sayisi. Elimizdekinden buyukse, beklemekten baska yapacak
    bir sey yok."""

    @property
    def is_proven(self) -> bool:
        """Yalnizca BETTER kaniti sayilir.

        INCONCLUSIVE "muhtemelen iyidir" demek DEGILDIR; bilmiyoruz
        demektir. Ikisini ayni saymak, gurultuyu ogrenmenin en kisa
        yoludur.
        """
        return self.verdict is Verdict.BETTER

    def report(self) -> str:
        return (
            f"{self.trades} islem | ortalama {self.mean_r:+.3f} R | "
            f"%{self.confidence * 100:.0f} aralik [{self.ci_low:+.3f}, {self.ci_high:+.3f}] | "
            f"esik {self.threshold_r:+.3f} R | {self.verdict.value}"
        )


def bootstrap_mean_ci(
    values: Sequence[float],
    confidence: float = 0.95,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = 0,
) -> tuple[float, float]:
    """Ortalamanin yuzdelik bootstrap guven araligi.

    TOHUM ZORUNLU ve varsayilani sabit. Ayni girdi her zaman ayni
    araligi vermeli: her kosuda biraz farkli cevap veren bir kapi,
    bir sonucun neden degistigini sormayi imkansiz hale getirir -
    kod mu degisti, strateji mi, yoksa zar mi belli olmaz.
    """
    if len(values) < 2:
        raise ValueError(
            "guven araligi icin en az iki gozlem gerekir; "
            f"verilen: {len(values)} (tek gozlemin yayilimi olculemez)"
        )
    _check_confidence(confidence)
    if iterations < 1:
        raise ValueError("bootstrap tekrar sayisi en az 1 olmali")
    _check_budget(confidence, iterations)
    _check_finite(values, "orneklem")

    # S311: kriptografik amac yok - istatistiksel yeniden orneklemede
    # TEKRARLANABILIRLIK gerekiyor, ongorulemezlik degil. Guvenli bir
    # uretec burada zarar verirdi: ayni girdi ayni cevabi vermezdi.
    rng = random.Random(seed)  # noqa: S311
    size = len(values)
    means = sorted(fmean(rng.choices(values, k=size)) for _ in range(iterations))

    tail = (1.0 - confidence) / 2.0
    low = means[int(tail * (iterations - 1))]
    high = means[int((1.0 - tail) * (iterations - 1))]
    return low, high


def required_trades(
    edge_r: float,
    volatility_r: float,
    confidence: float = 0.95,
) -> int:
    """Verilen buyuklukteki bir farki ayirt etmek icin kaba islem sayisi.

    n ~ (z * s / fark)^2. Kesin bir guc analizi DEGIL; buyukluk
    mertebesi verir. Ise yarar tarafi su: fark yariya inince gereken
    islem sayisi DORDE KATLANIR. Kucuk bir avantaji dogrulamanin neden
    aylar surdugu bu yuzden - ve neden birkac gunluk iyi sonuca
    bakarak karar vermenin gurultu kovalamak oldugu da.
    """
    _check_confidence(confidence)
    if volatility_r <= 0:
        return 0
    if edge_r <= 0:
        # Sifir ya da negatif bir avantaj hicbir orneklemle
        # "pozitif" olarak kanitlanamaz.
        return 0
    return int((_z_for(confidence) * volatility_r / edge_r) ** 2) + 1


def assess(
    values: Sequence[float],
    threshold_r: float = 0.0,
    min_trades: int = 100,
    confidence: float = 0.95,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = 0,
) -> Evidence:
    """Bir R kumesinin esigi gercekten asip asmadigini olcer.

    `min_trades` bir TABAN: altinda kalan orneklem, guven araligi ne
    soylerse soylesin INSUFFICIENT_DATA doner. Sebebi sadece
    istatistik degil; az islem cogu zaman tek bir piyasa rejimini
    gorur. Gurultuyu degil, gecmis ayin havasini ogrenmis oluruz.
    """
    _check_finite(values, "orneklem")
    trades = len(values)
    if trades < 2:
        return Evidence(
            trades=0,
            mean_r=0.0,
            ci_low=0.0,
            ci_high=0.0,
            confidence=confidence,
            threshold_r=threshold_r,
            verdict=Verdict.INSUFFICIENT_DATA,
            trades_needed=min_trades,
        )

    mean_r = fmean(values)
    spread = pstdev(values) if trades > 1 else 0.0
    needed = max(min_trades, required_trades(mean_r - threshold_r, spread, confidence))

    if trades < min_trades:
        return Evidence(
            trades=trades,
            mean_r=mean_r,
            ci_low=mean_r,
            ci_high=mean_r,
            confidence=confidence,
            threshold_r=threshold_r,
            verdict=Verdict.INSUFFICIENT_DATA,
            trades_needed=needed,
        )

    low, high = bootstrap_mean_ci(values, confidence, iterations, seed)
    if low > threshold_r:
        verdict = Verdict.BETTER
    elif high < threshold_r:
        verdict = Verdict.WORSE
    else:
        verdict = Verdict.INCONCLUSIVE

    return Evidence(
        trades=trades,
        mean_r=mean_r,
        ci_low=low,
        ci_high=high,
        confidence=confidence,
        threshold_r=threshold_r,
        verdict=verdict,
        trades_needed=needed,
    )


def compare(
    candidate: Sequence[float],
    baseline: Sequence[float],
    min_edge_r: float = 0.0,
    min_trades: int = 100,
    confidence: float = 0.95,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = 0,
) -> Evidence:
    """Adayin mevcut ayardan gercekten iyi olup olmadigini olcer.

    Iki kumenin ortalamalari AYRI AYRI yeniden orneklenir ve farkin
    dagilimi kurulur. Iki kosunun ayni islemleri icermesi gerekmiyor;
    zaten genellikle icermezler.

    Kritik nokta: "adayin ortalamasi daha yuksek" bir sey soylemez.
    Iki gurultu kumesinden biri her zaman digerinden yuksek cikar.
    Sorulan soru, FARKIN guven araliginin esigi asip asmadigi.
    """
    _check_finite(candidate, "aday")
    _check_finite(baseline, "temel")
    if len(candidate) < 2 or len(baseline) < 2:
        return Evidence(
            trades=min(len(candidate), len(baseline)),
            mean_r=0.0,
            ci_low=0.0,
            ci_high=0.0,
            confidence=confidence,
            threshold_r=min_edge_r,
            verdict=Verdict.INSUFFICIENT_DATA,
            trades_needed=min_trades,
        )
    _check_confidence(confidence)
    _check_budget(confidence, iterations)

    difference = fmean(candidate) - fmean(baseline)
    # Kucuk olan kume belirleyici: 1.000 islemlik bir temel, 12
    # islemlik bir adayi kanitlamaz.
    trades = min(len(candidate), len(baseline))
    spread = max(
        pstdev(candidate) if len(candidate) > 1 else 0.0,
        pstdev(baseline) if len(baseline) > 1 else 0.0,
    )
    needed = max(min_trades, required_trades(difference - min_edge_r, spread, confidence))

    if trades < min_trades:
        return Evidence(
            trades=trades,
            mean_r=difference,
            ci_low=difference,
            ci_high=difference,
            confidence=confidence,
            threshold_r=min_edge_r,
            verdict=Verdict.INSUFFICIENT_DATA,
            trades_needed=needed,
        )

    rng = random.Random(seed)  # noqa: S311  (bkz. bootstrap_mean_ci)
    deltas = sorted(
        fmean(rng.choices(candidate, k=len(candidate)))
        - fmean(rng.choices(baseline, k=len(baseline)))
        for _ in range(iterations)
    )
    tail = (1.0 - confidence) / 2.0
    low = deltas[int(tail * (iterations - 1))]
    high = deltas[int((1.0 - tail) * (iterations - 1))]

    if low > min_edge_r:
        verdict = Verdict.BETTER
    elif high < min_edge_r:
        verdict = Verdict.WORSE
    else:
        verdict = Verdict.INCONCLUSIVE

    return Evidence(
        trades=trades,
        mean_r=difference,
        ci_low=low,
        ci_high=high,
        confidence=confidence,
        threshold_r=min_edge_r,
        verdict=verdict,
        trades_needed=needed,
    )
