# tlab

Alpaca üzerinde çalışan, gözetimsiz işlem yapan ve kendi işlemlerinden öğrenen
bir alım-satım sistemi.

> **Durum: Faz 0 — salt okunur.** Sistem şu anda hesap okur, piyasa verisi çeker
> ve karar kaydı altyapısını hazırlar. **Emir göndermez.** Emir yetkisi, risk
> kapısı tamamlandıktan sonra Faz 1'de açılacak.

---

## Tasarım ilkesi: tek beyin, üç koşum takımı

Sistemin tamamı tek bir kuralın üzerine kurulu:

```
decide(context) -> Intent
```

Aynı strateji fonksiyonu üç yerde çalışır — **backtest**, **paper**, **canlı** —
ve hangisinin altında olduğunu bilmez. Değişen tek şey veriyi kimin verdiği ve
emri kimin gerçekleştirdiğidir.

Bu neden önemli: öğrenen bir sistem, ancak öğrendiğini geriye dönük test
edebiliyorsa gerçekten öğrenir. Backtest ve canlı kod ayrı olursa öğrenilen her
şey doğrulanamaz hale gelir.

İlkenin koddaki karşılığı iki protokol: `Strategy` (saf fonksiyon — ağ yok, saat
okuması yok) ve `Broker` (canlıda Alpaca, backtest'te simülasyon). Buna bir de
`Clock` soyutlaması eşlik eder: hiçbir strateji `datetime.now()` çağıramaz,
çünkü geçmiş veri üzerinde çalışırken "şu an"ı yanlış bilmek ileriye bakma
(lookahead) hatalarının başlıca kaynağıdır.

## Katmanlar

```
veri → özellik → strateji → RİSK KAPISI → execution → journal → öğrenme
```

| Katman | Sorumluluk |
|---|---|
| `core/` | Saf alan tipleri ve zaman soyutlaması. Hiçbir dış bağımlılığı yok. |
| `data/` | Alpaca'dan bar/kotasyon, yerel parquet önbelleği. |
| `execution/` | Broker protokolü ve Alpaca uygulaması. |
| `journal/` | Karar ve işlem kaydı — öğrenmenin yakıtı. |
| `config.py` | Davranış ayarları (YAML) + anahtarlar (.env), bilerek ayrı. |

## Risk katmanı

Gözetimsiz çalışan bir sistemde tek gerçek felaket senaryosu korumasız
pozisyondur. Bu yüzden şunlar pazarlığa açık değil:

- **Her giriş bracket order ile** — stop ve hedef, girişle birlikte borsaya
  gider. Bot çökse, sunucu kapansa, ağ gitse bile koruma emirleri borsada durur.
- **Günlük zarar kill-switch** — eşiğe değince gün kapanır.
- **Earnings bloğu** — scalping stratejisi bilanço üzerinden pozisyon taşımaz.
- **PDT sayacı** — 25.000 $ altı hesapta 5 iş gününde 3 day trade sınırı.
- **Açılışta mutabakat** — broker her zaman tek doğru kaynak; sistem yeniden
  başladığında kendi hafızasına değil gerçek pozisyonlara göre hizalanır.

## Öğrenme yaklaşımı

Canlı sonuçlara bakıp kendini otomatik güncelleyen bir bot **yapmıyoruz**: az
örnek, gürültülü sinyal ve geri besleme döngüsü aşırı uyuma götürür.

Bunun yerine bir veri çarkı kuruyoruz:

1. **Karar kaydı** — her işlem, giriş anındaki tam özellik fotoğrafıyla
   saklanır. *Veto edilen kararlar da kaydedilir*: "risk kapısı engellemeseydi
   ne olurdu" sorusu, risk parametrelerini öğrenmenin tek yoludur.
2. **Gece analizi** — setup × rejim bazında beklenen değer, isabet oranı, R
   dağılımı, MAE/MFE.
3. **Terfi kapısı** — yeni bir parametre seti canlıya ancak (a) yeterli örnek,
   (b) walk-forward backtest üstünlüğü ve (c) shadow mode tutarlılığı ile geçer.
4. **Dağıtım öğrenmesi** — kanıtlanmış setup'lar arasında sermaye ağırlığını
   rejime göre kaydırmak. Asıl "öğrenen" kısım burası.

LLM'in rolü sınırlı ve nettir: haber/bilanço metnini yapılandırılmış alanlara
çevirir (katalizör var mı, yönü, önem derecesi). Kararı LLM vermez — karar
deterministik kurallar ve öğrenilmiş ağırlıklardan çıkar, çünkü LLM kararı
geriye dönük test edilemez.

## Kurulum

```bash
pip install -e ".[dev]"
cp .env.example .env     # anahtarlarını .env içine yaz
tlab doctor              # kurulumu baştan sona kontrol et
```

`.env` dosyası `.gitignore` içindedir ve repoya **asla** girmez.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `tlab doctor` | Config, anahtar, journal, broker ve veri bağlantısını sırayla denetler |
| `tlab config` | Çözümlenmiş yapılandırmayı gösterir (anahtarlar maskeli) |
| `tlab account` | Hesap özeti ve açık pozisyonlar |
| `tlab fetch SPY --days 30 --timeframe 1Min` | Geçmiş bar verisi çeker, önbelleğe yazar |
| `tlab journal init` | Journal veritabanını oluşturur/günceller |

## Yapılandırma

Gizli bilgi ile davranış ayarları bilerek ayrı tutulur:

- `config/base.yaml` — risk limitleri, seans saatleri, veri feed'i. Repoya girer
  ve versiyonlanır, böylece "hangi ayarla hangi sonucu aldık" sorusu git
  geçmişinden cevaplanır.
- `config/universe.yaml` — işlem evreni.
- `.env` — yalnızca API anahtarları.

Bilinmeyen bir YAML anahtarı **hata verir**, sessizce yok sayılmaz: yazım
hatasıyla girilmiş bir satır yüzünden risk limitinin sandığından farklı olmasını
istemiyoruz.

### Veri feed'i hakkında

Alpaca'nın ücretsiz planı yalnızca **IEX** akışını verir — toplam hacmin ~%2-3'ü.
VWAP, hacim profili ve seviye tespiti bu veriyle bozulur. Tam konsolide akış
(SIP) ücretlidir. Hangi feed ile karar verildiği her koşuda journal'a yazılır;
feed değiştiğinde eski ve yeni sonuçların neden ayrıştığı böylece bilinir.

## Geliştirme

```bash
pytest                    # testler (hiçbiri ağ erişimi gerektirmez)
ruff check . && ruff format --check .
mypy --strict src/tlab
```

Testlerin tamamının çevrimdışı çalışabilmesi tesadüf değil: katmanlar doğru
ayrıldığında çekirdek mantık brokera bağlanmadan doğrulanabilir.

## Yol haritası

| Faz | Kapsam | Durum |
|---|---|---|
| 0 | İskelet, config, veri + önbellek, journal şeması, salt okunur broker | **tamam** |
| 1 | Tek strateji (ORB), tam risk kapısı, bracket order, gözetimsiz koşu | sırada |
| 2 | Backtest motoru (aynı strateji kodu) ve dürüst metrikler | |
| 3 | Gece analizi, shadow mode, terfi kapısı | |
| 4 | Bilanço takvimi, haber/katalizör → özellik ve sert bloklar | |
| 5 | Çoklu strateji, rejim sınıflandırma, dağıtım öğrenmesi | |
| 6 | Opsiyonel: TradingView webhook, görsel grafik okuma | |

## Beklentiler üzerine dürüst not

Paper trading emirleri gerçekte olacağından daha iyi doldurur; paper sonuçları
canlıya 1:1 taşınmaz. Bu sistemin ilk hedefi para kazanmak değil, **dürüst
ölçmektir**. Kârlılık, test edilecek bir hipotezdir — verilmiş bir sonuç değil.
