# Değişiklik Günlüğü

Bu dosyanın biçimi [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/),
sürüm numaralandırması [Semantic Versioning](https://semver.org/lang/tr/)
kurallarını izler.

Her sürüm bir git etiketine (`v0.1.0` gibi) karşılık gelir; böylece herhangi bir
sürüme geri dönmek tek komutluk iştir. Ayrıntı için `CONTRIBUTING.md`.

## [Yayınlanmamış]

### Planlanan
- Faz 1: ORB stratejisi, tam risk kapısı, bracket order ile gözetimsiz koşu.

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
