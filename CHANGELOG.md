# Değişiklik Günlüğü

Bu dosyanın biçimi [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/),
sürüm numaralandırması [Semantic Versioning](https://semver.org/lang/tr/)
kurallarını izler.

Her sürüm bir git etiketine (`v0.1.0` gibi) karşılık gelir; böylece herhangi bir
sürüme geri dönmek tek komutluk iştir. Ayrıntı için `CONTRIBUTING.md`.

## [Yayınlanmamış]

### Planlanan
- Faz 2: Backtest motoru (aynı strateji kodu) ve dürüst metrikler.

## [0.2.0] - 2026-09-19

Faz 1 — gözetimsiz paper trading. Sistem artık bir seansı baştan sona kendi
başına yürütüyor. 100 → 209 test.

### Eklendi
- **Göstergeler** (`features/indicators.py`): ATR (Wilder), EMA, seans VWAP,
  bağıl hacim, açılış aralığı. Hepsi saf fonksiyon; veri yetmiyorsa `None`
  döner, tahmin üretmez.
- **Seans durumu** (`features/context.py`): gün içindeki aşama (açılış öncesi /
  açılış aralığı / normal / kapanış tamponu / kapalı). Yaz saati geçişleri
  zaman dilimi veritabanına bırakıldı, sabit saat farkı varsayılmıyor.
- **Strateji protokolü ve ORB stratejisi**: parametre setleri içeriğine göre
  parmak izi üretiyor (`orb-3f2a9c11`), böylece bir işlemin hangi ayarlarla
  açıldığı tahmine değil kayda dayanıyor.
- **Risk kapısı** (`risk/gate.py`): hesap sağlığı, günlük zarar kill-switch'i,
  seans aşaması, sembol başına tek pozisyon, eşzamanlı pozisyon sınırı, PDT
  sayacı, asgari fiyat, spread ve çapraz piyasa kontrolü, asgari stop mesafesi,
  risk bazlı boyutlandırma, brüt maruziyet ve alım gücü tavanı. Kurallar kısa
  devre yapmaz: tüm veto sebepleri toplanır ve kaydedilir.
- **Bracket emir gönderimi**: giriş, stop ve hedef tek paket. Bot çökse bile
  koruma emirleri borsada durmaya devam eder.
- **Mutabakat** (`engine/reconciler.py`): broker gerçekleşmelerinden kapanan
  işlemler üretilir. İşlem kimliği giriş/çıkış emirlerinden türetildiği için
  yeniden başlatma mükerrer kayıt oluşturmaz. Slippage ölçülüyor.
- **Seans döngüsü** (`engine/runner.py`): mutabakat → kill-switch → gün sonu
  kapanışı → değerlendirme. Tek turun hatası döngüyü öldürmez.
- **CLI**: `tlab run` (+ `--dry-run`, `--once`), `tlab summary`.
- Ruff'ın `S` (bandit) güvenlik kural seti açıldı.

### Güvenlik
- Canlı para modunda çalışmak için `--i-understand-live` bayrağı gerekiyor.
- Journal'a yazılan kolon adları SQL metnine gömülmeden önce doğrulanıyor.

### Değişti
- **Desteklenen Python sürümü 3.12'ye sabitlendi** (önceden 3.11 + 3.12). CI,
  Docker imajının kullandığı sürümün aynısını denetliyor. İki sürüm
  desteklemek, bağımlılık çözümlemeleri ayrıştığında CI'yı kodla ilgisi
  olmayan sebeplerle kırıyordu: numpy 2.5.3 yalnızca 3.12+ için yayınlanıyor
  ve PEP 695 sözdizimi içeriyor; mypy'ye hedef olarak 3.11 verildiğinde bu
  stub'ı ayrıştıramıyordu.


## [0.1.1] - 2026-09-19

Faz 0 denetimi. Kod düşman gözüyle yeniden okundu; yedi kusur bulundu ve
düzeltildi. Hepsi için regresyon testi eklendi (88 → 100 test).

### Düzeltildi
- **`BracketOrder` ters geometriyi kabul ediyordu.** `Intent` bu kuralı
  doğruluyordu ama brokera giden nesne `BracketOrder` ve doğrudan da
  oluşturulabiliyor. Stop'un hedefin yanlış tarafında olduğu bir emir
  girişle birlikte stop'u tetikler.
- **Yuvarlama bracket'i çökertebiliyordu.** Çok dar bir stop, iki ondalığa
  yuvarlandıktan sonra girişle aynı fiyata düşüyordu (giriş = stop = hedef).
  Geometri kontrolü artık yuvarlama sonrasında da çalışıyor.
- **Kesirli pozisyonlar kayboluyordu.** `int()` ile yuvarlama yüzünden 0,5
  hisselik bir pozisyon sıfıra düşüyor ve sistem onu hiç görmüyordu. Gözetimsiz
  çalışan bir sistemde pozisyonu görmemek, yanlış görmekten tehlikeli.
  `Position.qty` artık float; tam hisse şartı emir tarafında uygulanıyor.
- **SDK uyum katmanı kendi varlık sebebini ihlal ediyordu.** Değeri `None`
  olan bir alan, sözlükte `None`, nesnede varsayılan dönüyordu; `currency`
  alanı `"None"` string'ine dönüşebiliyordu.
- **Naive tarihle önbellek filtresi** pandas'ın anlaşılmaz bir `TypeError`'ı
  ile patlıyordu; artık ne yapılması gerektiğini söyleyen `DataError` veriyor.
- **Göç dosya adı** doğrulanmadan SQL metnine gömülüyordu. Ad artık
  `NNN_kucuk_harfli_ad` biçimiyle sınırlı.
- Kullanılmayan yapılandırma yüklemesi CLI'dan kaldırıldı.

## [0.1.0] - 2026-09-19

Faz 0 — salt okunur iskelet. Sistem hesap okur, veri çeker, karar kaydı
altyapısını kurar. **Emir göndermez.**

### Eklendi
- Çekirdek alan tipleri (`Bar`, `Quote`, `Intent`, `BracketOrder`, `Decision`):
  değişmez ve kendi kendini doğrular. Ters bracket, bozuk OHLC ve naive
  zaman damgası nesne oluşurken reddedilir.
- `Clock` soyutlaması — stratejilerin `datetime.now()` çağırmasını engelleyerek
  ileriye bakma (lookahead) hatalarını yapısal olarak önler.
- Yapılandırma katmanı: davranış ayarları YAML'da, anahtarlar `.env`'de.
  Bilinmeyen YAML anahtarı sessizce yok sayılmaz, hata verir.
- Alpaca bar/kotasyon erişimi ve parquet önbelleği (atomik yazma, mükerrer
  kayıt birleştirme).
- SDK uyum katmanı: alpaca-py'nin model/sözlük ikiliğini tek yerde kapatır.
- Journal şeması: koşu, karar, emir, gerçekleşme, işlem ve parametre sürümü
  tabloları. Veto edilen kararlar da kaydedilir.
- Göç (migration) altyapısı — şema sürümü her an belli, göçler idempotent.
- Salt okunur Alpaca broker bağlantısı (hesap, pozisyon, borsa saati).
- CLI: `doctor`, `config`, `account`, `fetch`, `journal init`.
- 88 test, tamamı çevrimdışı çalışır.
- CI: her push'ta lint, biçim, strict tip denetimi ve testler.

### Güvenlik
- `.env` `.gitignore` içinde; anahtarlar repoya girmez.
- Anahtarlar log ve hata çıktılarında maskelenir.
- Paper modu varsayılan; canlı para açıkça `ALPACA_PAPER=false` gerektirir.
