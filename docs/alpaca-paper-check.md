# İlk Alpaca paper bağlantısı

Anahtarları sohbet, issue, PR, ekran görüntüsü veya commit içine koymayın.
Paper ve live hesapların anahtarları farklıdır. Bu adımlarda yalnızca
**Paper Trading** hesabında üretilen anahtarları kullanın.
Kaynak: https://docs.alpaca.markets/us/docs/paper-trading

## Anahtarları yerleştirme

Projeyi çalıştıran bilgisayarda `.env.example` dosyasını `.env` adıyla
kopyalayın; mevcut `.env` dosyanızı üzerine yazarak kaybetmeyin.
Yerel metin editöründe şu alanları doldurun:

```dotenv
ALPACA_API_KEY=<paper key>
ALPACA_SECRET_KEY=<paper secret>
ALPACA_PAPER=true
ALPACA_BASE_URL=
```

`ALPACA_BASE_URL` boş kalmalı: SDK, broker ve piyasa verisi için farklı
varsayılan adresleri seçer. Buraya paper broker adresini yazmak piyasa
verisi çağrılarını da yanlış sunucuya yönlendirebilir. Ortam değişkenleri
`.env` değerlerini geçersiz kılabilir; özellikle eski `ALPACA_PAPER=false`
ve `ALPACA_BASE_URL` değişkenlerini kontrol edin. Anahtar değerlerini
terminal geçmişine yazmayın. Linux/macOS'ta dosya iznini `chmod 600 .env`
ile sınırlayabilirsiniz. `.env` git tarafından dışlanır; force-add yapmayın.

## Kontrol sırası

Aktif Python 3.12 sanal ortamında, proje kökünde:

```bash
make install-locked
python -c 'from tlab.config import load_secrets; s=load_secrets(); assert s.is_configured and s.alpaca_paper and s.base_url is None, "Paper/default endpoint ayarlarini kontrol edin"; print("Paper yapilandirmasi hazir")'
tlab doctor
```

Ön kontrol başarısızsa sonraki komuta geçmeyin. `doctor` hesap ve piyasa
verisini okur, emir göndermez veya iptal etmez. Yerel journal'ı oluşturabilir
ve göçleri uygular. Çıktıda PAPER, broker bağlantısı ve bar verisi görülmeli.
Anahtar varlığı, doğrulandığı anlamına gelmez; doğrulama ağ isteğinde olur.

- 401: kimlik doğrulama sorunu; doğru paper hesabına ait key/secret çiftini kontrol edin.
- 403: yetki, feed veya ağ geçidi engeli olabilir; tek başına yanlış anahtar kanıtı değildir.
- Timeout/DNS: bağlantı sorunudur; anahtarın geçerliliği hakkında sonuç vermez.
- Broker başarılı, veri başarısız: veri erişimi ayrıca araştırılmalı.

Bağlantı geçince küçük veri örneğiyle başlayın:

```bash
tlab fetch SPY --days 5 --timeframe 1Min
```

Daha sonra veri kapsamını büyütüp ölçün:

```bash
tlab fetch --days 90 --timeframe 1Min
tlab backtest --days 60
```

Bu komutlar hesapta emir oluşturmaz. İlk bağlantı kontrolünde `tlab run`
başlatmayın. Backtest sonucu kârlılık veya gerçek emir yaşam döngüsü garantisi
değildir; paper emir denemeleri ayrı adımdır.

## Asistanla paylaşım

Bu sohbetin GitHub bağlantısı, bilgisayarınızdaki `.env` dosyasını veya GitHub
Actions secrets değerlerini okuyamaz. Anahtarları buraya yapıştırmayın.
Bu ortam için güvenli secret enjeksiyonu sağlanmadıysa komutları yerelde
çalıştırın; anahtarları ve hesap bilgilerini çıkardığınız sonuçları paylaşın.
GitHub secrets eklemek tek başına bu oturuma erişim sağlamaz.

Başarılı kontrolün tarihini, commit'ini, PAPER modunu, feed'i ve anonim kontrol
sonucunu AGENTS.md'ye kaydedin. Şu ana kadar gerçek hesapla doğrulama yapılmış
sayılmıyor; anahtarlar olmadan elde edilen test sonuçları çevrimdışı sonuçlardır.
