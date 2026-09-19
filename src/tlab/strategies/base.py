"""Strateji protokolu.

Bir strateji saf fonksiyondur: Context alir, Intent ya da None
dondurur. Ag cagrisi yapmaz, emir gondermez, saat okumaz, durum
tutmaz.

Bu kisitlama sistemin en onemli tasarim karari. Strateji "ne
istedigini" soyler; "ne kadar" ve "yapilsin mi" sorularinin cevabini
risk kapisi verir. Iki sorumlulugun ayri olmasi, risk kurallarini
tek yerde denetlenebilir kilar - on stratejinin her birinde ayri ayri
kontrol yazmak yerine.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from tlab.core.types import Intent
from tlab.features.context import Context


class StrategyParams(BaseModel):
    """Strateji parametrelerinin ortak tabani.

    Parametre setleri degismez ve icerigine gore parmak izi uretir.
    Bu parmak izi journal'a yazilir: aylar sonra bir islemin TAM
    olarak hangi ayarlarla acildigi tahmine degil kayda dayanir.
    Ogrenme katmanindaki terfi kapisi da setleri bu kimlikle izler.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def fingerprint(self) -> str:
        """Parametre iceriginin kisa ve kararli parmak izi."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:8]


@runtime_checkable
class Strategy(Protocol):
    """Baglamdan islem niyeti ureten her sey."""

    @property
    def strategy_id(self) -> str:
        """Stratejinin kalici kimligi (ornegin 'orb')."""
        ...

    @property
    def params_version(self) -> str:
        """Kullanilan parametre setinin kimligi (ornegin 'orb-3f2a9c11')."""
        ...

    def decide(self, ctx: Context) -> Intent | None:
        """Islem niyeti uretir; uygun kosul yoksa None.

        None donmek normaldir ve cogu cagrinin sonucudur: islem
        yapmamak da bir karardir.
        """
        ...
