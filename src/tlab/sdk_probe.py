"""Projenin KENDI kodunun Alpaca ile konustugunu dogrular; salt okunur.

`paper_probe` ile arasindaki fark bu modulun butun varlik sebebi.
`paper_probe` URL'i elle kurar ve yalnizca "anahtarlar gecerli mi, ag
acik mi" sorusunu cevaplar. Bu modul ise GERCEK adaptorlerimizi
(`AlpacaBroker`, `AlpacaMarketData`) calistirir.

Ayrim teorik degil: `_TIMEFRAME_ARGS` icinde `"Minute"` yazdigi icin
`tlab fetch` hic calismiyordu ve 272 test yesildi. Elle kurulmus bir
URL o hatayi goremez, cunku SDK'ya hic dokunmaz. Bu prob gorur.

CIKTI DISIPLINI - bu dosyanin en kati kurali:
Depo herkese acik, Actions kayitlari da herkese acik. Bu yuzden
BURADA HICBIR SAYISAL HESAP DEGERI BASILMAZ. Ozsermaye, bakiye, hesap
kimligi, pozisyon buyuklugu - hicbiri. `doctor` bunlari basar ve
YERELDE dogru davranistir; genel bir kosuya tasinamamasinin sebebi
tam olarak budur.

Ayni sekilde uzak yanit govdesi, istisna metni veya `repr` de
basilmaz: bunlar anahtari veya hesap bilgisini tasiyabilir. Yalnizca
sabit, yerel uretilmis tani metinleri cikar.

Emir gonderilmez, iptal edilmez. Yalnizca okuma.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from tlab.core.types import Timeframe
from tlab.errors import TradingLabError

PROBE_SYMBOL = "SPY"
"""Tek sembol yeterli: sorulan sey "veri geliyor mu", "hangi hisse iyi" degil."""

LOOKBACK_DAYS = 10
"""Gunluk barda 10 takvim gunu en az bes seans icerir - tatil haftasinda bile."""


@dataclass(frozen=True)
class StageResult:
    """Tek bir asamanin sonucu.

    Asamalar AYRI raporlanir: hesap gecip veri dusuyorsa bu, anahtar
    sorunu degil feed sorunu demektir ve ikisi farkli seyler yapmayi
    gerektirir.
    """

    label: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        return f"OK {self.label}" if self.ok else f"FAIL {self.label}: {self.detail}"


def classify(error: Exception) -> str:
    """Hatayi SABIT bir tani metnine cevirir.

    Istisna metni asla disari verilmez. Alpaca'nin hata govdeleri
    istegin kendisini yankilayabiliyor ve orada anahtar bulunabilir;
    ayrica hesap kimligi tasiyabiliyorlar.

    Siniflandirma kaba ama ISE YARAR: bu dort durum dort farkli
    mudahale gerektirir - anahtar yenile, plan/feed degistir, bekle,
    kodu duzelt.
    """
    text = str(error).lower()
    if "401" in text or "unauthorized" in text or "forbidden" in text or "403" in text:
        return "kimlik dogrulama veya yetki reddi (401/403)"
    if "429" in text or "rate limit" in text or "too many requests" in text:
        return "hiz siniri (429)"
    if any(word in text for word in ("timeout", "connection", "network", "dns", "ssl", "tls")):
        return "ag veya TLS hatasi"
    if isinstance(error, TradingLabError):
        return "SDK yanitini bizim tipimize cevirirken hata"
    return "beklenmeyen hata"


def check_account(broker: object) -> StageResult:
    """Hesap okunabiliyor ve islem yapmaya uygun mu.

    `is_healthy` DOGRULANIR ama hicbir sayi basilmaz.
    """
    try:
        account = broker.get_account()  # type: ignore[attr-defined]
    # Genis yakalama bilincli: her istisna SABIT bir taniya cevrilip
    # yutulur, cunku metni disari vermek sizinti riski.
    except Exception as exc:
        return StageResult("hesap", ok=False, detail=classify(exc))
    if not account.is_healthy:
        return StageResult("hesap", ok=False, detail="hesap islem yapmaya kapali")
    return StageResult("hesap", ok=True)


def check_clock(broker: object, now: datetime) -> StageResult:
    """Borsa saati okunabiliyor ve degerler tutarli mi.

    DIKKAT - kolay yapilan bir hata: `next_open < next_close` KOSULSUZ
    dogru degildir. Borsa ACIKKEN bir sonraki kapanis bugun, bir
    sonraki acilis yarindir; yani `next_close < next_open` olur ve bu
    normaldir. Kosulsuz bir siralama kurali, seans acikken her koşuyu
    kirardi. (Codex'in #17'deki uyarisi.)

    Dogrulanabilir olan: iki deger de zaman dilimi bilgisi tasimali ve
    gelecekte olmali.
    """
    try:
        clock = broker.get_market_clock()  # type: ignore[attr-defined]
    except Exception as exc:
        return StageResult("borsa saati", ok=False, detail=classify(exc))

    if not isinstance(clock.is_open, bool):
        return StageResult("borsa saati", ok=False, detail="is_open bool degil")
    for name, moment in (("next_open", clock.next_open), ("next_close", clock.next_close)):
        if moment.tzinfo is None or moment.utcoffset() is None:
            return StageResult("borsa saati", ok=False, detail=f"{name} zaman dilimsiz")
        if moment <= now:
            return StageResult("borsa saati", ok=False, detail=f"{name} gecmiste")
    return StageResult("borsa saati", ok=True)


def check_bars(market: object, now: datetime) -> StageResult:
    """Asil kiymetli asama: SDK cevrimi.

    Bar donmesi yetmez - bizim `Bar` tipimize DONUSMESI gerekiyor.
    `TimeFrameUnit("Minute")` sinifi hatalar tam burada cikar ve elle
    kurulmus bir URL'le gorulemezler.

    `Bar` tipinin kendi dogrulamasi (OHLC tutarliligi, zaman dilimi
    zorunlulugu) zaten calisiyor; buraya saglam varmasi basli basina
    kanittir. Sayi basilmaz.
    """
    try:
        bars = market.bars(  # type: ignore[attr-defined]
            PROBE_SYMBOL,
            Timeframe.D1,
            start=now - timedelta(days=LOOKBACK_DAYS),
            end=None,
        )
    except Exception as exc:
        return StageResult("bar verisi", ok=False, detail=classify(exc))

    if not bars:
        # Bos veri bir HATA DEGIL, ayri bir durum: feed, plan veya
        # tarih araligi sorunu olabilir. Ag/kimlik hatasiyla
        # karistirmamak icin ayri metin.
        return StageResult("bar verisi", ok=False, detail="bar donmedi (feed, plan veya aralik)")
    # Burada ayrica alan dogrulamasi YAPILMIYOR ve bu bilincli: `Bar`
    # tipi zaten zaman dilimi ve OHLC tutarliligini kendi kuruluşunda
    # zorunlu kiliyor. Bozuk bir yanit buraya saglam varamaz - liste
    # dolu donduyse cevrim gercekten calismistir. Burada tekrar kontrol
    # etmek, hicbir zaman kirmiziya donmeyecek olu bir dal olurdu.
    return StageResult("bar verisi", ok=True)


def run(
    key: str,
    secret: str,
    now: datetime,
    *,
    feed: str = "iex",
    base_url: str | None = None,
) -> int:
    """Uc asamayi sirayla calistirir; her biri ayri satir basar.

    Bir asamanin dusmesi digerlerini durdurmaz - risk kapisiyla ayni
    disiplin. "Neden calismiyor" sorusunun cevabi genellikle tek madde
    degildir, ve her turda bir tanesini kesfetmek zaman kaybi.

    `base_url` YALNIZCA sozlesme testi icin var: gercek SDK'yi yerel
    bir taklit sunucuya yonlendirir. `main()` bunu hicbir zaman
    gecirmez ve bir ortam degiskeninden de okumaz, dolayisiyla
    workflow'dan erisilemez.
    """
    key, secret = key.strip(), secret.strip()
    if not key or not secret:
        print("FAIL yapilandirma: paper anahtar ve secret gerekli")
        return 1
    if any(not 33 <= ord(char) <= 126 for value in (key, secret) for char in value):
        print("FAIL yapilandirma: anahtar gecersiz karakter iceriyor")
        return 1
    if now.tzinfo is None or now.utcoffset() is None:
        print("FAIL yapilandirma: zaman dilimi gerekli")
        return 1

    from tlab.data.market import AlpacaMarketData
    from tlab.execution.alpaca_broker import AlpacaBroker

    try:
        # paper=True SABIT. Bu arac canli hesaba hicbir kosulda
        # baglanmaz; bir bayrakla degistirilebilir olsaydi, o bayragin
        # yanlis gecirilmesi canli hesaba baglanmak demek olurdu.
        broker = AlpacaBroker(key, secret, paper=True, base_url=base_url)
        market = AlpacaMarketData(key, secret, feed=feed, base_url=base_url)
    except Exception as exc:
        print(f"FAIL istemci kurulumu: {classify(exc)}")
        return 1

    results = [check_account(broker), check_clock(broker, now), check_bars(market, now)]
    for result in results:
        print(result.line())
    return int(any(not result.ok for result in results))


def main() -> int:
    return run(
        os.environ.get("ALPACA_PAPER_API_KEY", ""),
        os.environ.get("ALPACA_PAPER_SECRET_KEY", ""),
        # Duvar saati bilincli ve karar yolu disi: bu bir tani araci.
        # `run()` zamani disaridan alir, testler enjekte edebilir.
        datetime.now(UTC),
    )


if __name__ == "__main__":
    raise SystemExit(main())
