# Güvenlik

## Sır yönetimi

API anahtarları **yalnızca** `.env` dosyasında tutulur. Bu dosya `.gitignore`
içindedir ve `tests/test_architecture.py` her koşuda izlenen dosyaları tarar.

Git geçmişi kalıcıdır: bir anahtar yanlışlıkla commit edilirse dosyayı
düzeltmek yetmez — anahtarı **Alpaca panelinden iptal edip yenisini üretmek**
gerekir. Geçmişi temizlemek ikincil iştir.

## Canlı para

Sistem varsayılan olarak paper hesapta çalışır. Gerçek parayla çalışmak iki
ayrı bilinçli adım gerektirir:

1. `.env` içinde `ALPACA_PAPER=false`
2. Komut satırında `--i-understand-live` bayrağı

Bir bayrağı yanlışlıkla değiştirmek ile gerçek parayı riske atmak arasında en
az bir bilinçli adım olmalı.

## Bağımlılıklar

Sürümler `requirements.lock` ile sabitlenir. Dependabot haftalık güncelleme
PR'ı açar; güncellemeler CI'dan geçmeden birleşmez. Haftalık "canary" koşusu
bağımlılıkları sabitlemeden kurar, böylece üst akıştaki bir kırılma rastgele
bir PR'ı kırmadan önce bizim seçtiğimiz anda ortaya çıkar.

## Açık bulduysan

Bu özel bir depo. Bir güvenlik sorunu görürsen depo sahibine doğrudan bildir,
issue açma.
