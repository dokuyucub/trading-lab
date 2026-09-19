# Değişiklik Günlüğü

Bu dosyanın biçimi [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/),
sürüm numaralandırması [Semantic Versioning](https://semver.org/lang/tr/)
kurallarını izler.

Her sürüm bir git etiketine (`v0.1.0` gibi) karşılık gelir; böylece herhangi bir
sürüme geri dönmek tek komutluk iştir. Ayrıntı için `CONTRIBUTING.md`.

## [Yayınlanmamış]

### Planlanan
- Faz 1: ORB stratejisi, tam risk kapısı, bracket order ile gözetimsiz koşu.

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
