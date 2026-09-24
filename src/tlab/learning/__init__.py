"""Ogrenme katmani: sistemin kendi islemlerinden ders cikardigi yer.

Bu katman KARAR YOLUNDA DEGIL. Cevrimdisi calisir, journal'i okur ve
"bu degisiklik gercekten daha iyi mi" sorusuna cevap uretir. Islem
sirasinda hicbir sey burayi cagirmaz.

Katmanin tek isi durust olmak. Bir ogrenme dongusunun en tehlikeli
hatasi yanlis ogrenmek degil, GURULTUYU ogrenip ona guvenmektir.
"""

from tlab.learning.evidence import (
    Evidence,
    Verdict,
    assess,
    bootstrap_mean_ci,
    compare,
    required_iterations,
    required_trades,
)
from tlab.learning.promotion import (
    PromotionDecision,
    PromotionPolicy,
    PromotionResult,
    decide_promotion,
)

__all__ = [
    "Evidence",
    "PromotionDecision",
    "PromotionPolicy",
    "PromotionResult",
    "Verdict",
    "assess",
    "bootstrap_mean_ci",
    "compare",
    "decide_promotion",
    "required_iterations",
    "required_trades",
]
