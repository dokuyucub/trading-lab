# Telefondan Alpaca paper bağlantı kontrolü

Bilgisayar kurulumu gerekmez. Bu workflow GitHub sunucusunda yalnızca üç
GET isteği yapar: paper hesap, borsa saati, SPY için IEX günlük barlar.
Emir göndermez/iptal etmez, bakiye ve hesap kimliğini loglamaz. Başarılı
sonuç, trading motorunun veya emir yaşam döngüsünün doğrulandığı anlamına gelmez.

## Kullanıcının bir kez yapacağı işlem

1. https://github.com/dokuyucub/trading-lab/settings/secrets/actions adresini aç.
2. **New repository secret** seç. Name: `ALPACA_PAPER_API_KEY`.
   Secret alanına Alpaca **Paper Trading** hesabının key değerini yapıştır.
   **Add secret** seç.
3. Aynı işlemi Name: `ALPACA_PAPER_SECRET_KEY` ve paper secret değeriyle tekrarla.

Anahtarları issue, PR veya sohbete yazmaya gerek yok. Live hesap anahtarı
kullanma. Asistan bağlantısının secret yönetim yetkisi olmadığı için bu iki
alanın girilmesi kullanıcıya ait tek zorunlu adımdır. GitHub secrets değerleri
sonradan okunamaz; workflow bunları yalnızca çalışma anında alır.

Kaynak: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

## Çalıştırma

Bu değişiklik bağımsız incelemeden geçip main'e birleşince:
**Actions → Alpaca paper connection check → Run workflow → main**.
Yalnızca elle başlatılır; PR/push olayı anahtarlarla ağ isteği yapmaz.
Workflow başka dalda seçilirse kontrol işi atlanır.

Anahtarlar eklendiğinde asistana yalnızca "ekledim" yaz. Asistan, bağlı
aracın workflow başlatma yetkisi varsa çalıştırır; yoksa yukarıdaki Run workflow
adımı gerekir. Sonuç GitHub koşusunda görülebilir; anahtarları paylaşma.

## Sonuç

`OK paper account`, `OK market clock`, `OK IEX daily bars` üçü de beklenir.
Kapalı borsa bağlantı hatası değildir. 401 kimlik doğrulama; 403 yetki/feed
veya ağ engeli; 429 hız sınırı; network/TLS/response error bağlantı veya yanıt
sorunudur. Bunlar sabit tanı mesajlarıdır; uzak yanıt ve hata gövdeleri basılmaz.

Kontrol hiçbir paket kurmaz: prob yalnızca standart kütüphaneyi kullanır ve
`tlab` paketinin kökünde durur, böylece proje bağımlılıkları yüklenmez. Bu
bilinçli — araç tam da başka şeyler bozukken cevap verebilmeli. CI, komutun
hiçbir kurulum yapılmadan başlayabildiğini her koşuda doğrular.

Kontrol en fazla üç dakika çalışır; her isteğin timeout'u 15 saniyedir.
Yönlendirmeler takip edilmez. Yerel testler gerçek HTTP istemcisini yerel
sunucuya karşı çalıştırır; gerçek Alpaca anahtarlarıyla test henüz yapılmadı.
