# tlab

Alpaca üzerinde çalışan, gözetimsiz işlem yapan ve kendi işlemlerinden öğrenen
bir alım-satım sistemi.

> **Durum: Faz 2 — backtest motoru.** Sistem bir seansı başından sonuna
> kendi başına yürütür ve aynı kodu geçmiş veri üzerinde de çalıştırabilir.
> Varsayılan olarak **paper** hesapta işlem yapar.

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
| `features/` | Grafik okuma: göstergeler ve seans durumu. Saf fonksiyonlar. |
| `strategies/` | Bağlamdan işlem niyetine. Ağ yok, durum yok. |
| `risk/` | Risk kapısı: veto veya boyutlandırma. Tek koruma katmanı. |
| `execution/` | Broker protokolü ve Alpaca uygulaması. |
| `engine/` | Mutabakat ve seans döngüsü. |
| `backtest/` | Simülasyon brokeri, motor ve metrikler. |
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

## İlk çalıştırma

Sistemi ilk kez çalıştırırken emir göndertmeyin. `--dry-run` her şeyi yapar —
strateji karar verir, risk kapısı boyutlandırır, journal'a yazılır — ama emir
brokera gitmez:

```bash
tlab run --dry-run          # bir seans boyunca izle
tlab summary                # ne olurdu, hangi kararlar veto edildi
```

Veto sebepleri listesi en kıymetli çıktıdır: sistem hiç işlem açmıyorsa sebebi
orada yazılıdır. Gördüklerinizden memnunsanız `--dry-run` olmadan çalıştırın.

## Bir seans nasıl işliyor

Döngü her turda sırasıyla şunları yapar — ve **sıra tesadüfi değil**:

1. **Mutabakat** — broker'daki gerçek pozisyonlar ve gerçekleşmeler okunur,
   kapanan işlemler journal'a yazılır. Her karar gerçek duruma göre verilmeli,
   hafızadaki duruma göre değil.
2. **Kill-switch** — günlük zarar sınırı aşıldıysa gün kapanır. Gün kötüye
   gittiğinde stratejinin ne düşündüğünün önemi yoktur.
3. **Gün sonu kapanışı** — kapanış tamponuna girildiyse pozisyonlar kapatılır.
4. **Değerlendirme** — her sembol için bağlam kurulur, strateji sorulur, risk
   kapısından geçirilir, izin çıkarsa bracket emri gider.

Her karar — izin verilen de **veto edilen de** — journal'a yazılır.

## Kesintisiz çalışma

Sistem günlerce gözetimsiz dönmek üzere tasarlandı. Uzun koşuda sessizce
bozulan şeylere karşı alınmış önlemler:

| Risk | Önlem |
|---|---|
| Dolmayan emrin üstüne ikincisi | Bekleyen emirler pozisyon gibi maruziyet sayılır; strateji ve risk kapısı ikisi de engeller |
| Süreç yeniden başlayınca kill-switch unutulur | Gün kapatma kararı veritabanına yazılır, belleğe değil |
| Gönderim ile kayıt arası çökme | Emir brokera gitmeden **önce** journal'a yazılır (write-ahead) |
| Broker cevabı kaybolur | Kesinleşmemiş emir sembolü geçici olarak kapatır, süre dolunca serbest bırakılır |
| Bekleyen emirler okunamaz | Döngü "bilinmiyor" ile "boş" ayrımını yapar ve o turda giriş yapmaz |
| Bayat giriş emri gün boyu asılı kalır | Belirlenen süre sonunda iptal edilir (koruma bacakları asla) |
| Journal yazılamaz | O sembolde işlem açılmaz — kaydedilmeyen işlem öğrenilemez |
| Aynı hata dakikada bir tekrarlar | Ardışık hatalarda bekleme kademeli uzar, bir başarılı tur sıfırlar |
| Günlük dosyası diski doldurur | `--log-file` ile dönen dosya (10 MB × 5) |

Bunların her biri gözlemlenmiş bir kusurun karşılığı ve her biri için regresyon
testi var. Ayrıca `tests/test_soak.py` tam bir seansı dakika dakika (400 tur)
işletip değişmezleri doğruluyor: tek emir, tek işlem kaydı, kopuk referans yok,
gün sonunda açık pozisyon yok.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `tlab doctor` | Config, anahtar, journal, broker ve veri bağlantısını sırayla denetler |
| `tlab config` | Çözümlenmiş yapılandırmayı gösterir (anahtarlar maskeli) |
| `tlab account` | Hesap özeti ve açık pozisyonlar |
| `tlab fetch SPY --days 30 --timeframe 1Min` | Geçmiş bar verisi çeker, önbelleğe yazar |
| `tlab journal init` | Journal veritabanını oluşturur/günceller |
| `tlab run --dry-run` | Seansı yürütür ama **emir göndermez** — ilk çalıştırma için |
| `tlab run` | Seans döngüsünü başlatır (paper hesap) |
| `tlab run --once` | Tek tur çalıştırıp çıkar |
| `tlab summary` | Son koşunun özeti: kararlar, işlemler, veto sebepleri |
| `tlab backtest --days 60` | Stratejiyi geçmiş veri üzerinde çalıştırır ve ölçer |

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

## Backtest

Motorun en dikkat çekici özelliği **ne kadar az şey yaptığı**. Strateji, risk
kapısı, emir üretimi, mutabakat ve journal kaydı — hepsi canlıda çalışan kodun
aynısı. Değişen sadece üç parça:

```
canlı                  backtest
------------------     --------------------
AlpacaBroker      ->   SimBroker
AlpacaMarketData  ->   CachedMarketData
LiveClock         ->   SimClock
```

Üstteki hiçbir katman bu değişimi görmez. Ayrı bir backtest motoru yazılsaydı,
ölçülen ile çalışan arasındaki fark zamanla açılır ve öğrenilen her şey
doğrulanamaz hale gelirdi.

```bash
tlab fetch --days 90 --timeframe 1Min   # önce veriyi indir (ağ gerekir)
tlab backtest --days 60                 # sonra ölç (ağ gerekmez)
```

### Dolum modeli bilerek kötümser

Backtest'in işi güzel rakamlar üretmek değil, gerçekte olabileceğin **alt
sınırını** vermektir. İyimser bir simülasyon, canlıya geçince kaybolan bir
kârlılık gösterir — ve bu, hiç backtest yapmamaktan zararlıdır çünkü yanlış bir
güven verir.

- Pasif limit emri, fiyata değmek yetmez, **ötesine geçilmeli**.
- Aynı barda hem stop hem hedef tetiklenirse **stop** kabul edilir.
- Stop'tan aşağı gap'te çıkış **açılıştan** yapılır; stop bir garanti değil,
  tetikleyicidir.
- Hedef lehimize gap yapsa bile hedef fiyatı kullanılır.
- Giriş ve çıkış **aynı barda olmaz**.
- Her dolumda kayma aleyhimize uygulanır.

Bunun sınavı `test_backtest.py` içinde: rastgele yürüyüş verisinde motor pozitif
beklenen değer üretemiyor. Üretebilseydi, kendine bir yerden avantaj sağlıyor
demekti.

### Bilinen iyimserlik kaynakları

Dürüstlük gereği: geçmiş bar verisi kotasyon içermediği için **spread sentetik**
üretiliyor (sabit genişlikte). Gerçekte spread gün içinde değişir, açılışta ve
haber anında açılır. Bu yüzden backtest sonuçları gerçeğin **üst sınırı**
sayılmalı — özellikle "ufak marj" kovalayan stratejilerde.

## Yol haritası

| Faz | Kapsam | Durum |
|---|---|---|
| 0 | İskelet, config, veri + önbellek, journal şeması, salt okunur broker | **tamam** |
| 1 | ORB stratejisi, tam risk kapısı, bracket order, mutabakat, gözetimsiz koşu | **tamam** |
| 2 | Backtest motoru (aynı strateji kodu) ve dürüst metrikler | **tamam** |
| 3 | Gece analizi, walk-forward, shadow mode, terfi kapısı | sırada |
| 4 | Bilanço takvimi, haber/katalizör → özellik ve sert bloklar | |
| 5 | Çoklu strateji, rejim sınıflandırma, dağıtım öğrenmesi | |
| 6 | Opsiyonel: TradingView webhook, görsel grafik okuma | |

## Beklentiler üzerine dürüst not

Paper trading emirleri gerçekte olacağından daha iyi doldurur; paper sonuçları
canlıya 1:1 taşınmaz. Bu sistemin ilk hedefi para kazanmak değil, **dürüst
ölçmektir**. Kârlılık, test edilecek bir hipotezdir — verilmiş bir sonuç değil.
