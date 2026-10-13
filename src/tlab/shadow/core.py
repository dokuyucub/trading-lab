"""Golge gozlemin saf cekirdegi: ayni karar yolu, ayni izgara, fiyatsiz karsilastirma.

Tasarim: docs/designs/shadow-observation.md §1, §2 ve §4. Ag yok, saat
yok, anahtar yok.

Iki taraf (canlida gorulen IEX ve ayni anlara kesilmis SIP) AYNI
fonksiyonlardan gecer:

  * `visible_bars`: dongunun bir turda gorecegi barlar. Gecmis
    `an - history_days`ten baslar; yalnizca kapanmis barlar.
  * `session_at`: dongunun seans durumu. Acilis duzenli saatten,
    kapanis takvimle kisaltilir.
  * `intent_at`: riskten ONCEKI strateji niyeti. Hesap sentetik,
    pozisyon ve bekleyen emir yok, kotasyon yok.

Karsilastirma (`compare_symbol_day`) fiyat tasimaz: aralik farki baz
puan, pencere tamligi sayi, sinyal uyumu bayraktir. Ham bar ve mutlak
fiyat bu modulden disari cikmaz.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any

from tlab.config import Config
from tlab.core.types import Account, Bar, Intent, Side, Timeframe
from tlab.features.context import (
    Context,
    SessionState,
    apply_market_close,
    build_session_state,
)
from tlab.features.indicators import opening_range, opening_window_gaps
from tlab.strategies.base import Strategy

SIGNAL_NONE = "none"
"""Iki tarafta da niyet yok. Uyum DEGILDIR; ayri sayilir."""
SIGNAL_MATCH = "match"
"""Iki tarafta da niyet var; yon ayni, ilk niyet anlari tolerans icinde."""
SIGNAL_MISMATCH = "mismatch"
"""Yalnizca bir tarafta niyet var ya da yon/an uyusmuyor."""
SIGNAL_UNKNOWN = "unknown"
"""Taraflardan birinin ilk niyeti bilinemiyor (eksik ya da okunamayan tur)."""

RANGE_COMPUTED = "hesaplandi"
"""Iki pencere de o turda tam, payda gecerli: fark hesaplandi."""
RANGE_IEX_INCOMPLETE = "iex_tamamlanmadi"
"""IEX penceresi giris penceresi bitmeden hic tamamlanmadi: olcu disi."""
RANGE_SIP_MISSING = "sip_yok"
"""O turda SIP gorunumu yok: `unknown`."""
RANGE_SIP_INCOMPLETE = "sip_eksik"
"""O turda SIP penceresi eksik: "iki pencere tamsa" sartini saglamaz; ayri sayilir."""
RANGE_INVALID = "gecersiz_payda"
"""SIP araligi pozitif ve sonlu degil: `unknown`."""

SYNTHETIC_ACCOUNT = Account(
    equity=100_000.0,
    last_equity=100_000.0,
    cash=100_000.0,
    buying_power=200_000.0,
)
"""Sentetik hesap: golge gozlem hesabi OKUMAZ. Niyet hesaba bakmadan
uretilir; bu deger yalnizca baglam alanini doldurur."""


@dataclass(frozen=True)
class Turn:
    """Ortak izgaranin bir ani ve o anda gorulen barlar.

    `bars` None ise o turda veri ALINAMADI (erisim hatasi). Bos demet
    ise veri alindi ama gorulecek kapanmis bar yoktu. Ikisi farklidir:
    birincisi `unknown`, ikincisi bir gozlemdir.
    """

    moment: datetime
    bars: tuple[Bar, ...] | None


def visible_bars(
    bars: Iterable[Bar], moment: datetime, *, timeframe: Timeframe, history_days: int
) -> tuple[Bar, ...]:
    """Dongunun `moment` aninda gorecegi barlar, zaman sirali.

    Dongu her turda gecmisi `moment - history_days`ten ister ve yalnizca
    kapanmis barlari tutar (`bar.ts + sure <= moment`). SIP tarafi ayni
    kurali sonradan indirilmis veriye uygular; boylece iki taraf her
    turda ayni pencereyi gorur. ATR butun pencere uzerinde yumusatildigi
    icin baslangicin birebir ayni olmasi gerekir.
    """
    start = moment - timedelta(days=history_days)
    duration = timeframe.duration
    return tuple(
        sorted(
            (bar for bar in bars if start <= bar.ts and bar.ts + duration <= moment),
            key=lambda bar: bar.ts,
        )
    )


def session_at(
    moment: datetime, *, config: Config, opening_range_minutes: int, market_close: datetime
) -> SessionState:
    """Dongunun `moment` anindaki seans durumu.

    Dongu acilisi duzenli saatten kurar ve kapanisi broker saatiyle
    kisaltir (`SessionRunner.run_once`). Golge gozlemde kapanis resmi
    takvimden gelir; uyarlama ayni yardimciyla yapilir.
    """
    session = config.session
    state = build_session_state(
        moment,
        exchange_timezone=config.app.exchange_timezone,
        regular_open=(session.regular_open.hour, session.regular_open.minute),
        regular_close=(session.regular_close.hour, session.regular_close.minute),
        flatten_before_close_minutes=session.flatten_before_close_minutes,
        opening_range_minutes=opening_range_minutes,
    )
    return apply_market_close(
        state, market_close, flatten_before_close_minutes=session.flatten_before_close_minutes
    )


def intent_at(
    symbol: str,
    bars: tuple[Bar, ...],
    session: SessionState,
    *,
    strategy: Strategy,
    timeframe: Timeframe,
) -> Intent | None:
    """Riskten ONCEKI strateji niyeti; dongunun degerlendirme adimiyla ayni baglam.

    Dongu yeni giris yalnizca normal seansta degerlendirir ve kapanmis
    bar yoksa baglam kurmaz; burada da oyle. Durum sentetiktir: hesap
    sabit, pozisyon ve bekleyen emir yok, kotasyon yok. Kotasyon
    yoklugu feed farki sayilmaz; iki tarafta da yoktur.
    """
    if not session.can_open_new_positions or not bars:
        return None
    ctx = Context(
        symbol=symbol,
        session=session,
        bars=bars,
        account=SYNTHETIC_ACCOUNT,
        positions={},
        quote=None,
        timeframe=timeframe,
    )
    return strategy.decide(ctx)


QUOTE_FEATURES = frozenset({"spread_bps"})
"""Kotasyondan tureyen niyet ozellikleri. Saf yolda kotasyon yoktur; canli
dongunun niyetiyle karsilastirmada bu yuzden disarida kalir."""


def normalized(intent: Intent) -> dict[str, Any]:
    """Karsilastirilan niyet alanlari: hepsi, kotasyondan tureyen ozellik haric.

    Niyette rastgele kimlik yoktur; journal'in karar kimligi niyetin
    parcasi degildir.
    """
    data = intent.model_dump(mode="json")
    data["features"] = {
        key: value for key, value in data["features"].items() if key not in QUOTE_FEATURES
    }
    return data


class RecordingStrategy:
    """Canli dongunun niyetlerini (an, sembol, niyet) kaydeden ince sarmalayici.

    Karar degistirmez: sarmaladigi stratejinin cevabini aynen dondurur.
    """

    def __init__(self, inner: Strategy) -> None:
        self.inner = inner
        self.seen: list[tuple[datetime, str, Intent]] = []

    @property
    def strategy_id(self) -> str:
        return self.inner.strategy_id

    @property
    def params_version(self) -> str:
        return self.inner.params_version

    def decide(self, ctx: Context) -> Intent | None:
        intent = self.inner.decide(ctx)
        if intent is not None:
            self.seen.append((ctx.session.now, ctx.symbol, intent))
        return intent


def live_pure_mismatches(
    live: Sequence[tuple[datetime, str, Intent]],
    pure: Sequence[tuple[datetime, str, Intent]],
) -> int:
    """Canli ve saf niyet kumelerinin farki: sembol, an ve normallestirilmis alanlar.

    Toplam sayinin esit olmasi yetmez; her niyet birebir eslesmeli.
    """

    def keyed(items: Sequence[tuple[datetime, str, Intent]]) -> dict[tuple[str, str], str]:
        return {
            (moment.isoformat(), symbol): json.dumps(normalized(intent), sort_keys=True)
            for moment, symbol, intent in items
        }

    left, right = keyed(live), keyed(pure)
    return sum(left.get(key) != right.get(key) for key in set(left) | set(right))


T_STAR_DELAY = timedelta(seconds=60)
"""Pencerenin saatle bitisinden sonra izin verilen sabit gecikme (D): son
pencere barinin kapanip gelmesi icin."""
T_STAR_SLACK = timedelta(minutes=2)
"""`t*` icin tur bu sure icinde bulunmali; yoksa tamlik `unknown`."""

_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Comparison:
    """Bir sembol-gunun iki taraf karsilastirmasi. Fiyat TASIMAZ.

    Olcum anlari (tasarim §4) SAATLE tanimlidir, verinin gelisine gore
    degil:

      * `t*`: an `acilis + pencere + D`'den sonraki ilk tur, en gec
        `T_STAR_SLACK` icinde. Baslangic tamligi burada sayilir; tur yoksa
        ya da verisi alinamadiysa `unknown` (None).
      * Gecikmeli tamlik: `t*`'da eksik pencerenin giris penceresi
        bitmeden tamamlanmasi; ayri etiketlidir.
      * Aralik farki: IEX'in pencereyi ilk tam gordugu tur; SIP ayni tura
        kesilir.
      * Niyet: her tarafin ilk niyeti. Ilk niyetten once planli bir
        dakikanin turu yoksa ya da verisi alinamadiysa o tarafin niyeti
        `unknown`dur; "niyet yok" sayilmaz.
    """

    symbol: str
    window_expected: int
    iex_present: int | None
    """`t*`'da IEX penceresindeki bar sayisi; `unknown` ise None."""
    sip_present: int | None
    iex_completed_later: bool
    """Gecikmeli tamlik: `t*`'da eksikti, sonraki bir turda tamamlandi."""
    or_high_bps: float | None
    or_low_bps: float | None
    """(IEX - SIP) / SIP x 10 000, ISARETLI; yalnizca `range_status` hesaplandiysa.
    Kabul mutlak degerle yapilir (ozet)."""
    range_status: str
    """Aralik farkinin durumu: `RANGE_*` sabitlerinden biri."""
    signal: str
    iex_first_minute: float | None
    sip_first_minute: float | None
    """Ilk niyetin turu, acilistan dakika. Niyet yoksa ya da bilinmiyorsa None."""
    iex_unknown_turns: int
    """IEX verisinin alinamadigi tur sayisi."""


def compare_symbol_day(
    symbol: str,
    iex: Sequence[Turn],
    sip: Sequence[Turn],
    *,
    session_for: Callable[[datetime], SessionState],
    strategy: Strategy,
    opening_range_minutes: int,
    entry_window_minutes: int,
    timeframe: Timeframe,
    minute_tolerance: float = 1.0,
) -> Comparison:
    """Ayni izgaradaki iki tarafi karsilastirir.

    Iki taraf ayni anlari tasimali: izgara canli dongunun turlaridir ve
    SIP her ana ayri kesilir. Farkli izgara, farkli soruyu cevaplar.
    """
    if [turn.moment for turn in iex] != [turn.moment for turn in sip]:
        raise ValueError("iki taraf ayni izgarada karsilastirilir")
    window = timedelta(minutes=opening_range_minutes)
    if window % timeframe.duration:
        raise ValueError("acilis penceresi bar suresine tam bolunmeli")
    expected = window // timeframe.duration
    unknown_turns = sum(1 for turn in iex if turn.bars is None)
    if not iex:
        # Hic tur yok: olculecek an yok, her sey bilinmiyor.
        return Comparison(
            symbol=symbol,
            window_expected=expected,
            iex_present=None,
            sip_present=None,
            iex_completed_later=False,
            or_high_bps=None,
            or_low_bps=None,
            range_status=RANGE_IEX_INCOMPLETE,
            signal=SIGNAL_UNKNOWN,
            iex_first_minute=None,
            sip_first_minute=None,
            iex_unknown_turns=0,
        )

    session_open = session_for(iex[0].moment).session_open
    star_from = session_open + window + T_STAR_DELAY
    star = next(
        (
            index
            for index, turn in enumerate(iex)
            if star_from <= turn.moment <= star_from + T_STAR_SLACK
        ),
        None,
    )
    iex_present: int | None = None
    sip_present: int | None = None
    if star is not None and iex[star].bars is not None:
        iex_present = _window(iex[star].bars or (), session_open, opening_range_minutes, timeframe)
        sip_bars = sip[star].bars
        if sip_bars is not None:
            sip_present = _window(sip_bars, session_open, opening_range_minutes, timeframe)

    completed_later = False
    high_bps: float | None = None
    low_bps: float | None = None
    range_status = RANGE_IEX_INCOMPLETE
    for iex_turn, sip_turn in zip(iex, sip, strict=True):
        if iex_turn.moment < star_from or iex_turn.bars is None:
            continue
        if _window(iex_turn.bars, session_open, opening_range_minutes, timeframe) == expected:
            completed_later = iex_present is not None and iex_present < expected
            high_bps, low_bps, range_status = _range_bps(
                iex_turn.bars, sip_turn.bars, session_open, opening_range_minutes, timeframe
            )
            break

    minutes = range(opening_range_minutes, entry_window_minutes + 1)
    iex_first = _first_intent(symbol, iex, minutes, session_open, session_for, strategy, timeframe)
    sip_first = _first_intent(symbol, sip, minutes, session_open, session_for, strategy, timeframe)
    return Comparison(
        symbol=symbol,
        window_expected=expected,
        iex_present=iex_present,
        sip_present=sip_present,
        iex_completed_later=completed_later,
        or_high_bps=high_bps,
        or_low_bps=low_bps,
        range_status=range_status,
        signal=_signal(iex_first, sip_first, minute_tolerance),
        iex_first_minute=iex_first[1] if isinstance(iex_first, tuple) else None,
        sip_first_minute=sip_first[1] if isinstance(sip_first, tuple) else None,
        iex_unknown_turns=unknown_turns,
    )


def _window(
    bars: tuple[Bar, ...], session_open: datetime, opening_range_minutes: int, timeframe: Timeframe
) -> int:
    """Gorulen kapanmis barlarda pencerenin kac beklenen baslangici var.

    Sonraki barin gelip gelmedigine BAKILMAZ: olcum ani saatle secilir.
    """
    window_end = session_open + timedelta(minutes=opening_range_minutes)
    inside = [bar for bar in bars if session_open <= bar.ts < window_end]
    gaps = opening_window_gaps(inside, session_open, opening_range_minutes, timeframe.duration)
    if gaps is None:  # pragma: no cover - compare_symbol_day bolunmeyi once denetler
        raise ValueError("acilis penceresi bar suresine tam bolunmeli")
    return timedelta(minutes=opening_range_minutes) // timeframe.duration - len(gaps)


def _range_bps(
    iex: tuple[Bar, ...],
    sip: tuple[Bar, ...] | None,
    session_open: datetime,
    opening_range_minutes: int,
    timeframe: Timeframe,
) -> tuple[float | None, float | None, str]:
    """IEX penceresi o turda tam. SIP'in durumuna gore fark ya da sebep."""
    if sip is None:
        return None, None, RANGE_SIP_MISSING
    left = opening_range(list(iex), session_open, opening_range_minutes, timeframe.duration)
    right = opening_range(list(sip), session_open, opening_range_minutes, timeframe.duration)
    if left is None:  # pragma: no cover - cagiran IEX penceresinin tamligini denetler
        return None, None, RANGE_IEX_INCOMPLETE
    if right is None:
        return None, None, RANGE_SIP_INCOMPLETE
    high, low = _bps(left[0], right[0]), _bps(left[1], right[1])
    if high is None or low is None:
        return None, None, RANGE_INVALID
    return high, low, RANGE_COMPUTED


def _first_intent(
    symbol: str,
    turns: Sequence[Turn],
    minutes: range,
    session_open: datetime,
    session_for: Callable[[datetime], SessionState],
    strategy: Strategy,
    timeframe: Timeframe,
) -> tuple[Side, float] | str | None:
    """Planli dakikalari sirayla gezer; ilk niyet, `None` ya da `unknown`.

    Dakikanin turu o dakika icinde kosan ilk turdur. Ilk niyetten once bir
    dakikanin turu yoksa ya da verisi alinamadiysa sonuc bilinemez.
    """
    for minute in minutes:
        start = session_open + timedelta(minutes=minute)
        turn = next(
            (item for item in turns if start <= item.moment < start + timedelta(minutes=1)),
            None,
        )
        if turn is None or turn.bars is None:
            return _UNKNOWN
        session = session_for(turn.moment)
        intent = intent_at(symbol, turn.bars, session, strategy=strategy, timeframe=timeframe)
        if intent is not None:
            offset = (turn.moment - session_open) / timedelta(minutes=1)
            return intent.side, round(offset, 4)
    return None


def _signal(
    left: tuple[Side, float] | str | None,
    right: tuple[Side, float] | str | None,
    tolerance: float,
) -> str:
    if left == _UNKNOWN or right == _UNKNOWN:
        return SIGNAL_UNKNOWN
    if not isinstance(left, tuple) and not isinstance(right, tuple):
        return SIGNAL_NONE
    if not isinstance(left, tuple) or not isinstance(right, tuple):
        return SIGNAL_MISMATCH
    same_side = left[0] is right[0]
    return SIGNAL_MATCH if same_side and abs(left[1] - right[1]) <= tolerance else SIGNAL_MISMATCH


def _bps(value: float, reference: float) -> float | None:
    """(deger - referans) / referans x 10 000, dort basamak; payda gecersizse None."""
    if not (isfinite(reference) and reference > 0 and isfinite(value)):
        return None
    return round((value - reference) / reference * 10_000, 4)
