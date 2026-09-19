"""Risk kapisi.

Sistemdeki en onemli katman. Stratejiler "ne istedigini" soyler;
bu kapi "yapilsin mi ve ne kadar" sorularina karar verir.

Iki sorumlulugun ayri olmasinin sebebi: risk kurallari tek yerde
toplanmali. On farkli strateji yazildiginda her birine ayri ayri
limit kontrolu koymak, er ya da gec birinde unutulur - ve gozetimsiz
calisan bir sistemde bu unutma geceyi hesabi bosaltarak bitirir.

Kapi saf bir fonksiyondur: ag cagrisi yapmaz, emir gondermez, saat
okumaz. Bu sayede tum kurallari cevrimdisi test edilebilir.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from tlab.config import RiskSection
from tlab.core.types import Account, GateVerdict, Intent, Position
from tlab.features.context import Context


def gross_exposure(positions: Mapping[str, Position]) -> float:
    """Acik pozisyonlarin toplam piyasa degeri."""
    return sum(position.market_value for position in positions.values())


def daily_loss_breached(account: Account, config: RiskSection) -> bool:
    """Gunluk zarar siniri asildi mi (kill-switch).

    Runner bunu her dongude kontrol eder: asilmissa yeni islem
    acilmaz ve acik pozisyonlar kapatilir. Gunu erken bitirmek,
    kotu bir gunu felakete cevirmekten iyidir.
    """
    return account.daily_pl_pct <= -config.max_daily_loss_pct


class RiskGate:
    """Bir Intent'i degerlendirir: reddeder ya da boyutlandirir."""

    def __init__(self, config: RiskSection) -> None:
        self.config = config

    def evaluate(self, intent: Intent, ctx: Context) -> GateVerdict:
        """Niyeti tum risk kurallarindan gecirir.

        Kurallar KISA DEVRE YAPMAZ: ilk redde durmak yerine gecerli
        tum sebepler toplanir. Journal'a hepsi yazilir, cunku "bu
        islem neden olmadi" sorusunun cevabi cogu zaman tek sebep
        degil birkac sebebin birlesimidir ve ogrenme katmani bunu
        gormek zorunda.
        """
        vetoes = self._blocking_reasons(intent, ctx)
        if vetoes:
            return GateVerdict.veto(*vetoes)
        return self._size(intent, ctx)

    # ------------------------------------------------------------------
    # Engeller
    # ------------------------------------------------------------------

    def _blocking_reasons(self, intent: Intent, ctx: Context) -> list[str]:
        config = self.config
        account = ctx.account
        reasons: list[str] = []

        if not account.is_healthy:
            reasons.append("hesap islem yapmaya kapali (broker kisitlamasi)")

        if daily_loss_breached(account, config):
            reasons.append(
                f"gunluk zarar siniri asildi (%{account.daily_pl_pct:.2f} / "
                f"sinir %{config.max_daily_loss_pct})"
            )

        if not ctx.session.can_open_new_positions:
            reasons.append(f"seans asamasi uygun degil ({ctx.session.phase.value})")

        if ctx.position is not None:
            reasons.append(f"{intent.symbol} icin zaten acik pozisyon var")

        if len(ctx.positions) >= config.max_concurrent_positions:
            reasons.append(
                f"es zamanli pozisyon siniri dolu ({len(ctx.positions)}/"
                f"{config.max_concurrent_positions})"
            )

        reasons.extend(self._pdt_reasons(account))
        reasons.extend(self._instrument_reasons(intent, ctx))
        return reasons

    def _pdt_reasons(self, account: Account) -> list[str]:
        """Pattern Day Trader kurali.

        25.000 $ altindaki hesaplarda 5 is gununde en fazla 3 gun ici
        islem yapilabilir. Asilirsa hesap 90 gun boyunca kisitlanir;
        bu yuzden sinir broker'a birakilmaz, burada sayilir.
        """
        config = self.config
        if not config.enforce_pdt:
            return []
        if account.equity >= config.pdt_equity_threshold:
            return []
        if account.daytrade_count < config.max_day_trades_per_window:
            return []
        return [
            f"PDT siniri: {account.daytrade_count}/{config.max_day_trades_per_window} "
            f"gun ici islem kullanildi (ozsermaye {account.equity:,.0f} < "
            f"{config.pdt_equity_threshold:,.0f})"
        ]

    def _instrument_reasons(self, intent: Intent, ctx: Context) -> list[str]:
        """Enstrumanin islem yapmaya uygun olup olmadigi."""
        config = self.config
        reasons: list[str] = []
        price = intent.reference_price

        if price < config.min_price:
            reasons.append(f"fiyat cok dusuk ({price:.2f} < {config.min_price})")

        # Kotasyon yoksa spread bilinmiyor demektir. Bilinmeyen maliyetle
        # islem acmaktansa islem acmamak tercih edilir.
        quote = ctx.quote
        if quote is None:
            reasons.append("kotasyon yok, spread dogrulanamiyor")
        elif quote.is_crossed:
            reasons.append(f"capraz piyasa (alis {quote.bid} > satis {quote.ask})")
        elif quote.spread_bps > config.max_spread_bps:
            reasons.append(
                f"spread cok genis ({quote.spread_bps:.1f} bps > {config.max_spread_bps} bps)"
            )

        # Stratejinin kendi asgari stop kurali olsa da kapi ona guvenmez.
        stop_bps = intent.risk_per_share / price * 10_000 if price > 0 else 0.0
        if stop_bps < config.min_stop_bps:
            reasons.append(
                f"stop mesafesi cok dar ({stop_bps:.1f} bps < {config.min_stop_bps} bps)"
            )

        return reasons

    # ------------------------------------------------------------------
    # Boyutlandirma
    # ------------------------------------------------------------------

    def _size(self, intent: Intent, ctx: Context) -> GateVerdict:
        """Pozisyon buyuklugunu risk butcesine gore hesaplar.

        Boyut, "ne kadar hisse alabilirim"den degil "stop'a
        gidilirse ne kadar kaybederim"den turetilir. Risk bazli
        boyutlandirma farkli oynakliktaki enstrumanlari ayni riske
        getirir - bir islemin digerinden bes kat buyuk zarar
        yazmasini engelleyen sey budur.
        """
        config = self.config
        account = ctx.account
        price = intent.reference_price

        risk_budget = account.equity * config.max_risk_per_trade_pct / 100
        qty = math.floor(risk_budget / intent.risk_per_share)
        if qty < 1:
            return GateVerdict.veto(
                f"risk butcesi bir hisseye yetmiyor (butce {risk_budget:,.2f}, "
                f"hisse basi risk {intent.risk_per_share:.4f})"
            )

        # Toplam maruziyet siniri. Tek islemin riski kucuk olsa da, ayni
        # anda cok sayida pozisyon toplami tehlikeli seviyeye tasiyabilir.
        exposure_cap = account.equity * config.max_gross_exposure_pct / 100
        current = gross_exposure(ctx.positions)
        available = exposure_cap - current
        if available <= 0:
            return GateVerdict.veto(
                f"toplam maruziyet siniri dolu ({current:,.0f} / {exposure_cap:,.0f})"
            )

        qty = min(qty, math.floor(available / price), math.floor(account.buying_power / price))
        if qty < 1:
            return GateVerdict.veto(
                "maruziyet ve alim gucu sinirlari bir hisseye yetmiyor "
                f"(kalan maruziyet {available:,.0f}, alim gucu {account.buying_power:,.0f})"
            )

        return GateVerdict.allow(qty)
