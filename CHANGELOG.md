# Değişiklik Günlüğü

Bu dosyanın biçimi [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/),
sürüm numaralandırması [Semantic Versioning](https://semver.org/lang/tr/)
kurallarını izler.

Her sürüm bir git etiketine (`v0.1.0` gibi) karşılık gelir; böylece herhangi bir
sürüme geri dönmek tek komutluk iştir. Ayrıntı için `CONTRIBUTING.md`.

## [Yayınlanmamış]

### Düzeltildi
- **Backtest hakkındaki iddialar fazla güçlüydü.** Kötümser dolum varsayımları
  sonucu matematiksel bir *alt sınır* yapmaz; sadece düşünülen senaryolarda
  aleyhe seçim yapar. Aynı kodu paylaşmak da simülasyon ile gerçek
  gerçekleşmelerin eşitliğini garanti etmez — yalnızca karar mantığının aynı
  kaldığını garanti eder. `README.md`, `sim_broker.py` ve `cached.py`
  düzeltildi. (ChatGPT'nin PR #2 incelemesindeki tespiti.)
- **Rastgele yürüyüş testi tek tohumluydu.** Tek bir koşunun pozitif çıkması
  hata kanıtı değildir — ölçüldü: altı tohumdan üçü pozitif çıkabiliyor
  (+0.061'e kadar), ortalama −0.173 R. Test artık çoklu tohumun ortalamasına
  bakıyor ve docstring'i neyi kanıtlayıp neyi kanıtlamadığını açıkça yazıyor.
  İleriye bakmanın asıl kanıtı deterministik test olarak kalıyor.

### Eklendi
- **`requirements.lock` — bağımlılık kilidi.** Tüm sürümler tam olarak
  sabitlendi (Python 3.12 hedefiyle üretildi, CI'ın kullandığı sürüm). CI'ı
  kıran `numpy` 2.5.3 dahil 46 paket kilitli. Bir bağımlılık eklendiğinde
  `make lock` ile tazelenir; kilit ile `pyproject.toml`'un uyumunu test
  denetliyor.
- **CI yeniden düzenlendi**: kilitli kurulum, eşzamanlılık grubu (eski koşular
  iptal edilir), kapsama raporu ve %80 eşiği, haftalık "canary" koşusu —
  bağımlılıkları sabitlemeden kurar, böylece üst akıştaki bir kırılma rastgele
  bir PR'ı kırmadan önce bizim seçtiğimiz anda ortaya çıkar.
- **PR şablonu, CODEOWNERS, Dependabot, pre-commit yapılandırması ve
  `SECURITY.md`.** pre-commit kancaları CI ile aynı kapıları çalıştırır: farklı
  olurlarsa yerelde geçen bir değişiklik CI'da kırılır ve döngüyü uzatır.
- **İş bölümü, inceleme kuralları ve ajanlar arası koordinasyon protokolü**
  `AGENTS.md`'ye işlendi: Faz 3 Claude'da, Faz 4 ChatGPT'de; çift göz zorunlu
  dosyalar; incelemenin belirli bir commit'e ait olması; göç numarası
  rezervasyonunun issue ile yapılması (`git fetch` tek başına yarışı
  engellemiyor); Faz 4 veri sözleşmesinde öğrenme zamanı zorunluluğu ve
  "veri bulunamadı" ile "olay yok" ayrımı.
- **Issue şablonları**: koordinasyon, göç rezervasyonu, hata.
- **`AGENTS.md` — ekip sözleşmesi.** Projede birden fazla geliştirici (insan ve
  yapay zekâ ajanı) çalıştığı için dal modeli, push kuralları, değişmezler,
  çakışmaya açık dosyalar ve devir teslim protokolü yazıya döküldü.
  `CLAUDE.md` buraya yönlendiriyor.
- **`tests/test_architecture.py` — mimari değişmezleri denetleyen testler.**
  Yazılı bir kural, onu okumayan birine hiçbir şey yapmaz; çalıştırılabilir
  bir kural herkese aynı şeyi söyler ve CI'da durur. Denetlenenler: karar
  yolunda duvar saati çağrısı olmaması, katman bağımlılık yönü, iş
  katmanlarında satıcı SDK'sı bulunmaması, göç numaralarının benzersiz ve
  arasız olması, uygulanmış göç dosyalarının düzenlenmemesi ve izlenen hiçbir
  dosyada API anahtarı bulunmaması. Kontroller metin araması değil AST
  üzerinden yapılıyor; dördü de kasıtlı ihlallerle sınandı.

### Düzeltildi
- **Bar verisi çekme hiç çalışmıyordu.** `TimeFrameUnit("Minute")` geçersiz —
  enum'un *adı* `Minute`, *değeri* `Min` ve enum değerle kuruluyor. Yani
  `tlab fetch` ve canlı veri akışı ilk çağrıda patlardı. 272 testin hiçbiri
  yakalamamıştı: hepsi çevrimdışıydı ve sahte nesneler bizim *varsaydığımız*
  şekli döndürüyordu.

### Eklendi
- **Alpaca sözleşme testleri** (`tests/test_alpaca_contract.py`): gerçek
  alpaca-py istemcisi, Alpaca'nın yanıt şekillerini taklit eden yerel bir
  sunucuya karşı çalıştırılıyor. Ağ erişimi yok; doğrulanan şey bizim
  kodumuzun HTTP yüzeyi — istek kurulumu (özellikle bracket emrinin JSON
  gövdesi), yanıt ayrıştırması ve hata sarmalama.
- **Uçtan uca canlı yol testi**: grafik okumadan emir gövdesine kadar tüm
  zincir gerçek istemciyle koşuyor. Risk kapısının gerçek zincirde de emri
  engellediği ayrıca doğrulanıyor.
- **CLI testleri**: `doctor`, `account` ve `fetch` komutları sahte sunucuya
  karşı çalıştırılıyor. Birim testleri modülleri ayrı ayrı doğruluyor ama
  komutun onları doğru bağlayıp bağlamadığını görmüyordu.
- `ALPACA_BASE_URL` ile Alpaca adresi değiştirilebiliyor (sandbox, vekil
  sunucu veya yerel sahte sunucu için).
- Her `Timeframe` değerinin gerçek SDK tipine çevrilebildiğini doğrulayan test.

### Planlanan
- Faz 3: Gece analizi, walk-forward değerlendirme, shadow mode, terfi kapısı.

## [0.3.0] - 2026-09-20

Faz 2 — backtest motoru. Aynı strateji ve risk kodu geçmiş veri üzerinde
çalışıyor. 237 → 272 test.

### Eklendi
- **`SimBroker`**: Broker protokolünü uygulayan simülasyon brokeri. Dolum
  modeli bilerek kötümser — pasif limit emri fiyatın ötesine geçilmeden
  dolmaz, aynı barda hem stop hem hedef tetiklenirse stop kabul edilir,
  gap'lerde dolum aleyhimize yapılır, giriş ve çıkış aynı barda olmaz.
- **`CachedMarketData`**: parquet önbelleğinden beslenen veri kaynağı.
  Dilimleme ikili aramayla; kotasyon simülasyon anına bağlı üretiliyor.
- **`Backtest` motoru**: canlıdaki `SessionRunner`'ı simülasyon brokeri,
  önbellek verisi ve simülasyon saatiyle sürüyor. Ayrı bir backtest döngüsü
  yazılmadı — ölçülen şey canlıda çalışacak olanın ta kendisi.
- **Metrikler**: R katsayısı üzerinden beklenen değer, kâr faktörü, isabet
  oranı, azami geri çekilme, ortalama tutuş, kayma. Az işlemli sonuçlar için
  istatistiksel anlamlılık uyarısı.
- **`tlab backtest`** komutu.
- Motorun hile yapmadığını sınayan testler: rastgele yürüyüşte pozitif beklenen
  değer üretememe, geleceğe bakmama (aynı geçmiş + farklı gelecek = aynı
  kararlar), determinizm, kayma arttıkça sonucun kötüleşmesi.

### Düzeltildi
- **Giriş emri ters seçime yol açıyordu.** Emir tam kırılım fiyatına konuyordu;
  güçlü kırılımlarda fiyat geri gelmediği için emir hiç dolmuyor, dolanlar ise
  fiyatın geri geldiği — yani kırılımın başarısız olduğu — durumlar oluyordu.
  Sistem sistematik olarak yalnızca çalışmayan kırılımlara giriyordu. Giriş
  artık kırılımın biraz ötesine konan marketable limit emri
  (`entry_offset_bps`, varsayılan 5). Sentetik veride dolum oranı %72 → %83.

## [0.2.1] - 2026-09-19

Faz 1 dayanıklılık denetimi. Sistem uzun süreli, gözetimsiz çalışma gözüyle
yeniden okundu. İki kritik hata, bir mimari ihlal ve dört boşluk bulundu.
209 → 237 test.

### Düzeltildi
- **Dolmayan emrin üstüne ikinci emir gönderiliyordu.** Limit emri dolana kadar
  ortada pozisyon yoktur; yalnızca pozisyon listesine bakan döngü her turda
  yenisini gönderiyordu. Bir saat dolmayan bir emir 60 kat pozisyon demek.
  Bekleyen emirler artık pozisyon gibi maruziyet sayılıyor.
- **Kill-switch süreç yeniden başlayınca unutuluyordu.** Bellekteki bayrak
  süreci aşmaz: systemd yeniden başlattığında sistem günü kapattığını unutup
  tekrar işlem açıyordu. Karar artık veritabanında.
- **`JournalWriter` enjekte edilen saati atlıyordu.** `datetime.now()`
  çağırıyordu; canlıda fark etmez ama backtest'te (Faz 2) kayıtlar bugünün
  tarihini taşır ve istatistikler zaman ekseninde yerinden oynardı. Saat artık
  dışarıdan veriliyor.

### Eklendi
- **Write-ahead emir kaydı**: emir brokera gitmeden önce journal'a yazılıyor.
  `orders` tablosunun birincil anahtarı `client_order_id` oldu — onu biz
  üretiyoruz, broker'ın verdiği kimlik ise ancak cevap gelince biliniyor.
- **Kesinleşmemiş emir çözümlemesi**: gönderim ile kayıt arasında süreç ölürse
  kalan satır her turda broker'a karşı çözümleniyor; bulunursa kesinleşiyor,
  bulunmazsa süre sonunda kayıp sayılıp sembolün önü açılıyor.
- **Bayat giriş emri iptali**: dolmayan giriş emirleri yapılandırılabilir süre
  sonunda iptal ediliyor. Koruma bacakları bu kuralın dışında.
- **Gerçekleşme denetim izi**: `fills` tablosu artık gerçekten yazılıyor.
- **Protokol uyum testleri**: Faz 0 ile Faz 1 arasındaki sözleşmeler hem statik
  (mypy) hem çalışma anında doğrulanıyor. Testler de tip denetimine dahil
  edildi — sahte broker ve veri kaynağı, protokollerden ayrışırsa mypy duruyor.
- **Soak testi**: tam bir seans dakika dakika (400 tur) işletiliyor ve
  değişmezler doğrulanıyor.
- Ardışık hatalarda kademeli bekleme, `--log-file` ile dönen günlük dosyası,
  pytest'te uyarıların hata sayılması.

### Güvenlik
- Journal yazılamadığında o sembolde işlem açılmıyor: kaydedilmeyen bir işlem
  öğrenilemez ve mutabakatı bozar.
- Bekleyen emirler okunamadığında yeni giriş yapılmıyor — "boş liste" ile
  "bilinmiyor" ayrımı açıkça yapılıyor.

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
