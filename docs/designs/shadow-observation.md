# Salt okunur gölge gözlem v1: tasarım sözleşmesi

Tarih: 2026-10-13. Koordinasyon: #17. Kayıtlar:
- Claude ön raporu 6151855559; Codex kararı 6152090021 (yön uygun,
  protokol revizyonu);
- Claude ön raporu 6153247091; Codex 6154024443 (revizyon doğru yönde;
  üç açıklık: `t*`, tekillik durumları, sızıntı ve tutarlılık);
- Codex BULGU 6155755867 (#50, `2253025`): mutlak bps eşiği, gözlemin
  başlangıçta yeniden denetimi, gün durumunun kanıtı, izin listesi,
  normatif SIP son süresi, tam ızgarada niyetsizlik;
- Codex ONAY 6156219094 (#50, `d557ef0`) kod PR'ı ölçütleri: özeti
  olmayan günde "başladı" yalnızca gerçek adım kanıtıyla; son süreden
  sonra dönen SIP yanıtı kabul edilmez;
- Codex BULGU 6158917217 (#51, `a9c7c80`): aralık ölçüsünde bilinmeyen
  sembol-gün paydada, pencere uçları saatle kapanmış pencereden, aralık
  ilk tam turda;
- Codex BULGU 6161518682 (#52, `0a2e198`): veri alınamayan sembol-tur
  gün durumunda, dakikası geçen tur koşmaz, SIP bütünlüğü her dakika
  barıyla;
- Codex 6171961412 (toplam işi ön raporu 6162408570'e karar): teklik
  kampanyaya bağlı, eşzamanlılık, artefakt seçimi, son günün bitişi,
  digest, kaybolan koşu; somut karşılıklar Claude ÖN RAPOR eki
  6172053624;
- Codex 6172892558 ve BULGU 6175607709 (#53, `632fbee`): önceki toplam
  koşusunun adım kanıtı, kodla temsil edilen yeniden deneme yetkisi,
  gün özetinde koşu/kod kimliği, uygulama parmak izi kampanyada, sabit
  stratejiden türeyen sayaç ve pencere tutarlılığı;
- Codex BULGU 6177175728 (#53, `93fefc5`): yeniden deneme yetkisi parmak
  izinin dışında ayrı kayıt dosyasında (kampanya + kesin koşu); önceki
  toplam koşusunun kampanyası artefakt adı, zaman ve adım kanıtıyla
  bağlı.

Bu belge tasarımdır. Kod, workflow ya da gerçek koşu teslim edildiği
anlamına gelmez. Yürütme yetkisi de değildir: o, ayrı ve kayıtlı bir
karardır (aşağıda "Sıra").

## Amaç ve sınır

Gölge gözlem, emir göndermeden canlı karar yolunu gerçek veriyle
çalıştırır. Üç soruya kanıt üretir:

1. **Feed uyumu** (AGENTS §11.4, gereksinim 1). Canlıda o an görülen IEX
   barlarıyla aynı karar anına kesilmiş tarihsel SIP barları karşılaştırılır.
   Kapsam: açılış penceresi, açılış aralığı ve strateji niyeti.
2. **Eksik açılış barı kontrolü** (gereksinim 2). Kontrol kodda var
   (#49); gölge gözlem onu gerçek veride gözler.
3. **Canlı karar yolu.** `SessionRunner` hiç canlı çalışmadı (§7). Burada
   emirsiz çalışır.

**Ne değildir:**

- Kârlılık değerlendirmesi değildir. P&L, dolum ve pozisyon hesaplanmaz.
- Gözetimsiz paper onayı değildir; emir yaşam döngüsünü sınamaz.
- Sonuç salt sağlayıcı farkı diye sunulmaz. Karşılaştırılan, **feed
  farkı + erişim gecikmesi + sonradan revizyon** toplamıdır: SIP sonradan
  düzeltilmiş olabilir.
- Holdout, parametre ya da evren değişikliği içermez.

## 1. Karşılaştırmanın eşitliği

İki taraf **aynı saf karar yolundan, aynı zaman ızgarasında ve aynı
sentetik durumda** geçer (Codex 6152090021 madde 1).

- **Zaman ızgarası.** Canlı döngünün turları; her tur anı `t` kayda geçer.
- **Bağlam.** Her `t` için sembol başına `Context` kurulur:
  - barlar: o anda **kapanmış** barlar;
  - seans durumu: `t` anı;
  - hesap: sentetik ve sabit; gerçek hesap okunmaz;
  - pozisyon ve bekleyen emir: boş;
  - kotasyon ve araştırma görüntüsü (`research`): `None`;
  - periyot: `Timeframe.M1`.
- **Karar.** `strategy.decide(ctx)`: riskten önceki strateji niyeti.
  Karşılaştırılan yalnızca budur.
- **İki taraf:**
  - **IEX tarafı:** canlı turda görülen barlar.
  - **SIP tarafı:** aynı `t`'ye kesilmiş SIP barları. Kesme kuralı:
    `bar.ts + süre <= t`.
- **Dışarıda kalanlar:** SimBroker, dolum modeli ve risk geçmişi
  karşılaştırmaya girmez. Kotasyon iki tarafta da yoktur; kotasyon
  yokluğu feed farkı sayılmaz.
- **Risk kabulü ayrı tanımdır.** Canlı döngünün `--dry-run` kararları
  (risk kapısı dahil) bilgi olarak kaydedilir, karşılaştırılmaz.
- **Tutarlılık denetimi.** Canlı döngünün her niyeti, aynı turun IEX saf
  değerlendirmesiyle birebir aynı olmalı. Farklıysa bu bir kod
  bulgusudur, feed bulgusu değil. Toplam niyet sayısı yetmez;
  karşılaştırılanlar:
  - sembol, yön ve karar anı;
  - normalleştirilmiş niyet alanları: strateji, parametre sürümü,
    referans fiyat, stop, hedef, güven ve özellikler.

  Kotasyondan türeyen özellik (`spread_bps`) dışarıda kalır: saf yolda
  kotasyon yoktur. Niyette rastgele kimlik yoktur; journal'ın karar
  kimliği karşılaştırmaya girmez.

## 2. Gözlem zamanı, geçmiş ve revizyon

- **Görülen kaydı.** Her turda, o turda gerçekten görülen kapanmış barlar
  ve erişim anı geçici yerel kayda yazılır (SQLite, `RUNNER_TEMP`).
  - Bar bir kez yazılır. Değeri sonraki bir turda değişirse yeni sürüm
    satırı eklenir; eski satır silinmez.
  - Her tur için görülen kümenin özeti (SHA-256) de yazılır. Turun
    görünümü kayıttan yeniden kurulur ve bu özetle doğrulanır.
  - Sonradan indirilen IEX ile geçmiş görünüm **yeniden yazılmaz**.
  - Kayıt dışarı çıkmaz; iş sonunda silinir.
- **Isınma ve geçmiş.** Döngü her turda geçmişi `t − 3 gün`den alır
  (`history_days=3`, döngü varsayılanı). SIP tarafı her `t` için aynı
  pencereyi kullanır: `t − 3 gün <= bar.ts` ve `bar.ts + süre <= t`.
  - Niyeti etkileyen göstergeler (ORB varsayılanları, `orb-7b32942a`):
    - ATR (Wilder, 14): bütün pencere üstünde yumuşatılır; değeri
      pencerenin başlangıcına bağlıdır. Bu yüzden başlangıç iki tarafta
      birebir aynı olmalı.
    - Bağıl hacim: son 20 bar.
    - Açılış aralığı: seansın ilk 15 dakikası.
  - VWAP yalnızca kayıt özelliğidir, niyete girmez; karşılaştırılmaz.
- **Seans.** Seans durumu iki tarafta da döngünün kurduğu gibi kurulur:
  - açılış düzenli saatten (`build_session_state`, borsa saat dilimi);
  - kapanış, yarım günde takvimle kısaltılır (döngü bunu saat ucunun
    `next_close` değeriyle yapar; gölgede o değer takvimden gelir).

  Seans günü, açılış ve kapanış için kaynak resmi takvimdir
  (`TradingSession`; §3 takvim ucu). Takvimdeki açılış düzenli saatle
  uyuşmazsa gün `eksik` sayılır ve gözlem başlamaz. Alpaca saat ucu
  yalnızca tutarlılık denetimidir.
- **Sinyal zamanı.** Ortak ızgarada niyetin ilk göründüğü tur anı `t`.
  Açılıştan dakika olarak raporlanır. ±1 dk uyumu bu iki anın farkıdır.

## 3. Broker ve uçlar

Gölge gözlemin broker'ı `ShadowBroker`'dır. Hesap ya da emir adaptörüne
**delegasyon yoktur**:

| Metot | Davranış |
|---|---|
| `get_account` | sentetik hesap |
| `get_positions`, `list_open_orders`, `list_fills` | boş liste (mutabakat yolu dahil) |
| `get_market_clock` | takvimden türetilir; Alpaca saati yalnızca karşılaştırılır |
| `submit_bracket`, `close_position`, `cancel_open_orders` | hata (fail-fast) |

- **İzinli uçlar:** veri uçları ile salt okunur takvim ve saat uçları.
  Hesap, pozisyon, emir, dolum ve hesap etkinliği uçları yasak.
  - Veri: bar ve son kotasyon.
  - Kotasyonu döngünün risk kapısı ister. Karşılaştırmaya girmez.
- **Döngünün journal'ı** geçici bir veritabanıdır (`RUNNER_TEMP`). Dışarı
  çıkmaz; iş sonunda silinir.
- **Yerel HTTP sözleşme testi** (`tests/alpaca_stub.py` deseni):
  - bütün koşu boyunca yasak uçlara **hiç istek gelmediğini** gösterir;
  - 401/403/429/5xx yollarında sızıntı olmadığını gösterir.

  Kodda yalnızca ad arayan bir test yetmez.

## 4. Süre ve paydalar

- **Planlı günler.** **20 planlı işlem günü.** Tarihler yürütme kararında
  geleceğe sabitlenir ve kodda listelenir. Liste dışındaki günde iş
  hiçbir şey yapmaz.
- **Gün durumları.** Her planlı gün şu durumlardan biriyle raporlanır:
  - `tamam`: bütün planlı sembol-turlar gözlendi ve SIP tam geldi;
  - `eksik`: geç başladı, kesildi, tur kaçtı ya da hata attı, planlı bir
    sembol-turun verisi alınamadı, SIP gelmedi ya da kayıt koşusu var ama
    özeti yok;
  - `başlamadı`: hiç gözlem başlamadığı **kanıtlı**;
  - `bilinmiyor`: koşu geçmişi okunamadı ya da kanıt yetersiz.

  Dördü de paydada kalır; hiçbiri sessizce düşmez. Kanıtın kuralı §6'da.
- **Payda.** Canlı pencere tamlığı için 20 × 11 = 220 planlı sembol-gün.
  Erişilemeyen gözlem `unknown` olarak ayrıca gösterilir.
- **Planlı ızgara.** Giriş penceresinin her dakikası için bir tur:
  `açılış + m dk + 7 sn`, `m = 15 … 120`. Dakikanın turu, o dakika içinde
  koşan gerçek turdur. Turlar kayda geçer; kaçan dakika telafi edilmez.
  - Uykudan sonra gerçek saat denetlenir. Uyku ya da önceki tur bir
    dakikayı taşırsa o dakikanın turu **koşmaz**. Döngü şimdiki dakikadan
    devam eder; son planlı dakika geçtiyse biter. Pencere dışında canlı
    istek yapılmaz.
  - Çağrının dönmesi veri alındığı demek değildir; döngü sembol hatasını
    kendi içinde yakalar. Gün özeti iki sayımı ayrı taşır:
    - döngü çağrıları (`turns`): döndü / hata attı / dakikasında hiç
      yapılmadı;
    - veri gözlemi (`symbol_turns`): planlı dakikada kayıttan okunabilen
      sembol-tur.
- **`t*` saatle tanımlıdır, veriye göre değil.**
  - Pencerenin saatle bitişi `açılış + 15 dk`. İzin verilen sabit
    gecikme `D = 60 sn`: son pencere barının kapanıp gelmesi için.
  - `t*`, anı `açılış + 15 dk + D`'den sonra olan ilk gerçek turdur; en
    geç 2 dk içinde.
  - Bu aralıkta tur yoksa ya da o turun verisi alınamadıysa pencere
    tamlığı `unknown` olur ve 220'lik paydada kalır.
  - Sonraki bar hiç gelmese de `t*`'daki sayım yapılır; eksiklik görünmez
    kalmaz. (Döngünün eksik bar notu ayrı bir gözlemdir; ölçü değildir.)
- **İki tamlık ölçüsü ayrı etiketlenir:**
  - **başlangıç tamlığı:** `t*`'da pencere tam;
  - **gecikmeli tamlık:** `t*`'da eksik, giriş penceresi bitmeden tamamlandı.
- **Aralık farkı:** planlı dakikalarda IEX görünümünde pencerenin ilk
  tam olduğu tur. `t*`'dan önce de olabilir, gecikmeli de olabilir;
  `t*` yalnızca başlangıç tamlığına aittir. SIP aynı tura kesilir.
  - Pencere uçları, o turda boşluksuz pencere barlarından hesaplanır.
    Planlı turlar pencere bitiminden sonradır; pencere barlarının
    kapandığı saatle bilinir, sonraki barın gelmesi gerekmez.
    Stratejinin açılış aralığı (sonraki barı bekler) değişmez.
  - İlk tam turdan önce planlı bir dakikanın turu yoksa ya da verisi
    alınamadıysa ilk tam tur bilinemez: aralık `unknown`.
  - "IEX penceresi tamamlanmadı" yalnızca **bütün** planlı dakikalar
    gözlenip pencere hiç tam olmadıysa verilir.
- **Niyet:** her tarafın ilk niyeti.
  - İlk niyetten önceki planlı dakikalardan birinin turu yoksa ya da o
    turun verisi alınamadıysa o tarafın ilk niyeti `unknown` olur.
  - **"Niyet yok"** sonucu yalnızca **bütün planlı dakikaların** turu
    var ve verisi okunmuşsa verilir. Tek eksik tur bile sonucu `unknown`
    yapar.
  - `unknown`, "iki tarafta da niyet yok" sayılmaz.
- **Koşullu ölçüler** için pay, payda ve `unknown` ayrı yazılır:
  - aralık farkı, iki pencere tamsa;
  - niyet uyumu, en az bir tarafta niyet varsa.

  Koşulun sağlanıp sağlanmadığı **bilinmeyen** sembol-gün paydada
  `unknown`dur: özeti ya da sonucu yok, ilk tam tur bilinmiyor, SIP yok.
  Yalnızca koşulun sağlanmadığı **gözlenen** sembol-gün dışarıda kalır
  ve ayrı sayaçla gösterilir (IEX ve SIP için ayrı).
- **Niyetsizlik ayrı sayılır.** İki tarafta da niyet yoksa bu "uyum
  geçti" değildir; ayrı sayaçtır.
- **Sembol bazında rapor.** Toplamın yanında sembol bazında rapor
  verilir; tek bir sembolün sürekli başarısızlığı toplamda kaybolmaz.
- **Aralık farkının formülü:**
  `bps = (OR_IEX − OR_SIP) / OR_SIP × 10 000`. Üst ve alt uç ayrı ayrı.
  - Raporda işaretli fark kalır.
  - **Kabul mutlak değerle:** `|bps_üst| ≤ eşik` VE `|bps_alt| ≤ eşik`.
  - Payda (`OR_SIP`) pozitif ve sonlu değilse fark `unknown`.
  - Sentetik kabul örnekleri (eşik 5): `+5` ve `−5` sınırda geçer;
    `+5,01`, `−5,01`, `+100` ve `−100` kalır.

**Eşik önerileri (kalibre edilmiş kapı DEĞİL; yürütme kararında
sabitlenir):**

| Ölçü | Öneri | Asgari destek |
|---|---|---|
| IEX başlangıç tamlığı (`t*`) | ≥ %95 | 220 planlı sembol-gün; `unknown` ayrı |
| Aralık farkı | iki uç `\|bps\| ≤ 5`, ≥ %90 | iki pencere de tam ≥ 100 sembol-gün |
| Niyet uyumu (aynı yön, ±1 dk) | ≥ %80 | niyetli ≥ 30 sembol-gün, ≥ 10 farklı gün |

Asgari destek sağlanmazsa sonuç `belirsiz` olur; geçti de kaldı da
denmez.

## 5. Tetikleme ve saat

Tercih: **sınırlı schedule**. Kullanıcıya 20 günlük tıklama yüklenmez
(Codex madde 5).

- **Saat dilimi.** İki UTC cron satırı (yaz ve kış saati), açılıştan
  yaklaşık 40 dk **önceye**, tam saat ya da yarım saat olmayan bir
  dakikaya kurulur. GitHub schedule'ı gecikebilir; pay bunun için.
- **Geçerli başlangıç penceresi.** Başlangıç penceresi
  `[açılış − 60 dk, açılış − 1 dk]`'dır.
  - Kapı işinde Alpaca secret'ı yoktur, takvimi okuyamaz. Açılışı
    düzenli saatten hesaplar: 09:30 New York, saat dilimi kuralıyla.
  - Gözlem işi resmi takvimle doğrular. Takvimde gün yoksa ya da açılış
    uyuşmuyorsa gün `eksik` sayılır ve gözlem başlamaz.
- **Kapının üç kararı:**
  - **Erken** (pencereden önce): hiçbir şey yapmaz.
  - **Pencere içinde:** o gün için kayıt yazmış başka koşu yoksa gözlem
    işini başlatır. Gözlem işi açılışa kadar bekler.
  - **Geç** (pencereden sonra): o gün için kayıt yazmış başka koşu
    yoksa, günü `eksik (geç başlangıç)` diye yazan secret'sız işi
    başlatır. Varsa hiçbir şey yapmaz.
  - Yaz/kış saatinin diğer cron satırı böylece ya erken kalır ya da
    gerçek koşudan sonra boş geçer. Gerçek koşu hiç başlamamışsa geç
    satır günü `eksik` diye yazar.
  - Geç başlangıç gözlem sayılmaz. Geçmiş barla doldurulup canlı
    gözlenmiş de sayılmaz.
- **Gözlem işi pencereyi kendisi yeniden denetler.** Kapı açılıştan
  ~40 dk önce geçebilir. Kayıt işi ise runner kuyruğunda, takvim
  çağrısında ya da kurulumda açılıştan sonraya kalabilir.
  - Denetim iki kez yapılır: iş başladığında ve takvim ile kurulum
    bitip gözleme hazır olduğunda.
  - Saat `açılış − 1 dk`'yı geçmişse canlı gözlem başlamaz. Gün
    `eksik (geç başlangıç)` yazılır.
  - Geçmiş barla doldurularak açılış gözlenmiş sayılmaz.
  - Sentetik protokol testleri: iki iş arasındaki kuyruk gecikmesi ve
    zaman alan takvim çağrısı.
- **Seans kimliği.** Seans tarihi; planlı günler listesinde olmalı.
- **Günlük tekillik.**
  - `concurrency` aynı anda iki koşuyu önler, ama aynı gün ikinci
    koşuyu tek başına önlemez.
  - **Seçim: koşu geçmişi.** Workflow iki işten oluşur:
    - kapı işi: başlangıç penceresi, planlı gün ve tekillik;
    - kayıt işi: kapı "pencere içinde" derse gözlem adımı, "geç" derse
      secret'sız geç kayıt adımı çalışır. Workflow başına tek yükleme
      adımı kuralı (mimari test) böylece korunur.
  - Kapı, aynı seans tarihinde **kayıt işi atlanmamış** başka bir koşu
    olup olmadığını Actions API'sinden okur; varsa durur. Boş geçen koşu
    sayılmaz; böylece diğer cron satırı gerçek koşuyu engellemez.
  - **Durumlar.** Yalnızca bu koşudan önce oluşturulmuş koşular (kimliği
    küçük olanlar) sayılır. Eşzamanlılık grubu workflow düzeyindedir ve
    `cancel-in-progress: false` açıkça yazılır: ikinci cron etkin
    gözlemi iptal etmez, bekler. Sonraki bir koşu bu koşu bitmeden
    başlayamaz; iki kapı yarışamaz.
    Önceki koşunun kayıt işi:

    | Durum | Sayılır mı |
    |---|---|
    | tamamlandı, atlandı | hayır (boş geçen koşu) |
    | tamamlandı: başarılı, başarısız ya da iptal | evet |
    | kuyrukta, sürüyor ya da bekliyor | evet (kapalı kal) |
    | iş listesinde kayıt işi yok | evet (kapalı kal) |

  - **Sayfalama.** Koşu ya da iş listesi tek sayfayı (100 kayıt) aşarsa
    kapı kapalı kalır.
  - Kapı koşu geçmişini okuyamazsa **kapalı** kalır: gün kaybolabilir,
    iki kez koşmaz. İş kırmızı biter, görünür olur.
  - Testlerle gösterilir:
    - sayfalama;
    - bu koşunun dışlanması;
    - hatada kapalı kalma;
    - mevsim dışı cron'un gözlemi başlatmadan günü tüketmemesi;
    - yukarıdaki dört durum.
  - Yeniden deneme koşusu (aynı koşunun ikinci denemesi) hiç koşmaz.
  - **İzin maliyeti:** `actions: read` yalnızca iki secret'sız işte:
    - kapı işi (bu workflow);
    - toplam işi (§6; ayrı, secret'sız).

    Gözlem ve kayıt işleri bu izni almaz. Alpaca secret'ları yalnızca
    gözlem adımında bulunur.
  - `workflow_dispatch` (girdisiz) dış başlatıcı içindir
    (`scheduler-alternatives.md` A; Codex 6196548874). Kapı tetik türüne
    bakmaz: aynı gün cron + dispatch, iki dispatch ya da elle tıklama
    gelirse ikincisi "gün zaten kaydedildi" ile boş geçer; pencere
    dışındaki tetik geç kayıt yazar. Eşzamanlılık grubu en fazla bir
    bekleyen koşu tutar: üçüncü tetik bekleyeni iptal eder ve iptal
    edilen koşu durum tablosuna göre günü kapatır (gevşetilmez). Bu
    yüzden başlatıcı bir günde en fazla bir kez ve o günün koşusu
    varken hiç dispatch etmez; teklik kanıtı `concurrency` değil koşu
    geçmişidir.
  - Planlı gün listesi boşken her koşu kapıda "plan dışı gün" der ve
    API'ye gitmez. Schedule satırlarının merge ile hafta içi günde iki
    kez boş koşu başlatması bu yüzden zararsızdır. Yine de (c)'nin
    onayında ayrıca karara bağlanır.
- **Bitiş.** Kodda yazılı son planlı günden sonra iş kendiliğinden
  hiçbir şey yapmaz.

## 6. İş sonu ve hata yolları

- **SIP karşılaştırması zamanı.** Sabit bir saat beklenmez. Giriş
  penceresi kapandıktan sonra SIP barları istenir ve iki koşul aranır:
  - açılış penceresi ile son karar anına kadar olan aralık sağlayıcıdan
    tam döndü;
  - son süre aşılmadı.
- **Tam yanıt:** açılıştan son turun anına kadar kapanmış olması gereken
  **her dakika barı** yanıtta var (`ts + 1 dk ≤ son tur`). Son barın
  varlığı yetmez.
  - Eksik yanıt `yanıt eksik (n dakika)` olarak son süreye kadar yeniden
    istenir.
  - Son sürede hâlâ eksikse o sembolün SIP'i yoktur. Gün `eksik` (SIP
    gelmedi) olur; aralık ve niyet o sembol-gün için `unknown`dur.
  - Gerçek veri boşluğu ile henüz tamamlanmamış yanıt tek yanıttan
    ayrılamaz. İkisi de tam sayılmaz; eksik SIP feed farkı gibi
    değerlendirilmez.
  - Önceki günlerin geçmiş barları bu şartın dışındadır. Şart, seans
    gününün aralığıdır.
- **Son süre (normatif):** `açılış + giriş penceresi (120 dk) + 45 dk`.
  - Seans saatine bağlı tek bir sabittir (kodda `SIP_DEADLINE`).
  - İstek anına bağlı değildir. Yavaş ya da tekrarlanan istek son süreyi
    kaydırmaz.
  - Her istekten önce denetlenir; son süreden sonra istek yapılmaz.
  - Yanıt döndükten sonra yeniden denetlenir. Son süreden önce başlayıp
    sonra dönen yanıt, tam olsa da kabul edilmez; sebep
    `son süre doldu (yanıt geç)`.
  - Aşılırsa gün `eksik` (SIP gelmedi) olarak kaydedilir.
- **İlk SIP isteği** son karar anından en az 15 dk sonra yapılır: ücretsiz
  plan SIP'in son 15 dakikasını vermez. Bu bir bekleme kuralıdır; son
  süre değildir.
- **Günlük ve toplam özet.**
  - Her gün yalnızca o günün özetini yükler: gün durumu ve sembol-gün
    karşılaştırmaları, fiyatsız.
  - 20 günlük toplam, son planlı günden sonra secret'sız ayrı bir işte
    kurulur (`actions: read`). İki kaynağı birlikte okur:
    - günlük özet artefaktları;
    - planlı günlerin sınırlı koşu ve iş üst verisi: her koşunun
      kimliği, oluşturulma anı, kayıt işinin durumu ve sonucu, kayıt
      adımlarının (`Gozle`, `Gec kaydi yaz`) sonucu.
  - **Kampanya kimliği** (`campaign_of`): kanonik JSON'un SHA-256'sı.
    İçerik: planlı tarihler, evren sembolleri, eşikler (`Thresholds`),
    strateji `params_version`, gün ve toplam şema sürümleri ve
    **uygulama parmak izi**. Gözlem ve geç kayıt her gün özetine
    `campaign` yazar; toplam da taşır (`implementation` ayrıca). Biri
    kampanya ortasında değişirse kimlik değişir. Eski günlerin özetleri
    yeni kimlikle toplanamaz; değişiklik yeni kampanya ve yeni tarihler
    demektir.
  - **Uygulama parmak izi** (`implementation_fingerprint`): sıralı dosya
    manifestinin SHA-256'sı: paketin bütün `.py` dosyaları (dolaylı
    bağımlılıklar dahil: `core`, `features`, `engine`, `data`,
    `execution`, `sdk_compat`…), `config/*.yaml`, `requirements.lock`,
    `shadow-observation.yml`, `shadow-aggregate.yml`. Her adım kendi
    checkout'undan hesaplar; `params_version` kod kimliği değildir.
    Schedule main'in o anki commit'ini kullanır; bütün günlerin aynı
    merge SHA ile koştuğu söylenemez. Bu yüzden bağ SHA sabiti değil
    manifesttir: bu dosyalara dokunan bir merge kampanya ortasında
    kimliği değiştirir, günler karışmaz ve toplam durur. Dondurma (d)
    onayından son toplamın doğrulanmasına kadar bu dosyaları kapsar ve
    kodla zorlanır.
  - **Koşu ve kod kimliği.** Gün özeti `run_id`, `run_attempt` ve
    `code_sha` (`GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_SHA`)
    taşır; yoksa özet yazılmaz. Toplam işi bunları seçilen API
    koşusuyla eşleştirir (`run_id` = koşu, `run_attempt` = 1,
    `code_sha` = koşunun `head_sha`'sı); uyuşmazsa bütün toplama durur.
  - **Toplam işi** (`.github/workflows/shadow-aggregate.yml`, ÖN RAPOR
    #17/6162408570, eki 6172053624):
    - Tetiği yalnızca `workflow_dispatch`. Kullanıcı son planlı günden
      sonra bir kez tıklar; #17 kararıyla. Hata sonrası tekrar ayrı #17
      kararıdır; otomatik tekrar yok.
    - **Tek toplam, kampanya başına; teklik workflow ömrüne değil
      kampanyaya bağlı.** (1) Gerçek çıktı: yükleme adı
      `shadow-total-<kimliğin ilk 16 hanesi>` (ad yalnız arama anahtarı;
      gün özetlerinde tam kimlik karşılaştırılır). Depoda bu adda
      artefakt varsa (süresi dolmuş olsa da) gözlem artefaktı
      indirilmez, yeni toplam üretilmez. (2) Önceki toplam koşuları
      **kampanyaya bağlanır** ve gerekiyorsa **adım kanıtı** okunur. İş
      iki adımdır: `Indir` (`collect`) ve `Topla` (`aggregate`, yalnız
      `Indir` başarılıysa). Bu koşudan önce oluşturulmuş her toplam
      koşusu için sırayla:

      | Önceki koşu | Karar |
      |---|---|
      | koşu bitmemiş | durur (sürüyor; eşzamanlılık) |
      | kayıtlı tekrar yetkisi bu koşuyu gösteriyor | kanıt dışı (aşağıda) |
      | `shadow-total-*` artefaktı var (süresi dolmuş dahil), öneki bu kampanyanın | durur: toplam üretildi |
      | artefaktı var, öneki başka kampanyanın | engel değil: kanıtlı başka kampanya |
      | artefaktı yok, koşu bu kampanyanın son planlı gününden önce ya da o gün (New York) oluşturulmuş | engel değil: bu kampanyanın toplamı olamaz, `collect` o tarihte reddederdi |
      | artefaktı yok, son planlı günden sonra; `total` işi listede yok ya da adımları okunamıyor | durur (eksik geçmiş başarı ya da "hiç başlamadı" kanıtı değildir) |
      | … `Topla` `success` ya da `failure` | durur: toplam adımı koştu; upload hatası ve silinmiş artefakt burada yakalanır |
      | … `Topla` atlandı, `Indir` `failure`/`skipped` | engel değil: boş, erken, ret ya da indirme hatası; çıktı üretilmedi |
      | … başka birleşim (iptal, sonuçsuz) | durur (belirsiz kaynak güvenli tarafta) |

      Böylece A kampanyasının başarılı ya da yarım toplamı, tarihleri
      sonraki B kampanyasının ilk toplamını engellemez; A'nın yeni
      toplamı ve A'nın upload hatası/silinmiş çıktısı A için durur.
      Başarıyla biten ama çıktı bırakmayan koşu (boş ya da erken
      `PLANNED_DAYS`) `Indir`de durur; kanıt değildir ve geleceği
      kapatmaz.
    - **Yeniden deneme yetkisi: parmak izinin dışında, dar ve bağlı.**
      Kayıt dosyası `config/shadow-total-retry.json`: `{"campaign":
      <tam kimlik>, "failed_run": <koşu kimliği>, "decision":
      "#17/<yorum>"}`. Parmak izi `config/*.yaml` ve paket `.py`
      dosyalarını kapsar; bu JSON bilinçli olarak dışarıdadır. Yalnız bu
      dosyayı değiştiren karar PR'ı kampanya kimliğini değiştirmez,
      mevcut günlükler geçerli kalır; ölçüm kodu/ayar değişimi hâlâ
      kimliği değiştirir. Yetki yalnız o kampanyanın **o** başarısız
      koşusunu kanıt dışı bırakır. Dosya başka kampanyaya aitse ya da
      biçimsizse iş durur; eski kayıt yeni kampanyada bırakılamaz. Yeni
      dispatch, yeni `run_id` ya da `run_attempt = 1` tek başına izin
      değildir.
    - **Eşzamanlılık.** Workflow düzeyinde `concurrency:
      shadow-aggregate`, `cancel-in-progress: false`; iki dispatch
      kapıyı aynı anda geçemez.
    - **Son gün bitmeden başlamaz.** İki şart birlikte: (1) şimdiki
      New York (`America/New_York`) tarihi son planlı günden sonra;
      (2) planlı günlerin gözlem koşularının hepsi `completed`.
      Kuyrukta ya da süren koşu varsa hiçbir artefakt listelenmez. Son
      günün SIP son süresi (açılış + 165 dk) ve kayıt işi zaman aşımı
      (300 dk) seans gecesinden önce dolar.
    - Yeniden deneme koşusunda ve secret'lı ortamda iş hiçbir istek
      yapmadan kırmızı biter.
    - **Koşu seçimi.** Ad yetmez. Gün özeti yalnızca şu koşudan alınır:
      `head_branch = main`, `event` ∈ {`schedule`, `workflow_dispatch`}
      (`OBSERVATION_EVENTS`; workflow'un tetik kümesiyle aynı, mimari
      test), `path = .github/workflows/shadow-observation.yml`,
      `run_attempt = 1` (`OBSERVATION_SOURCE`); başka tetik, dal, yol ya
      da deneme seçilmez. Seans günü planlı olmalı; plan dışı günün
      koşusu listelenmez. Seçilmeyen koşu sabit satırla atlanır; o gün
      kanıt kuralıyla sınıflanır. Aynı günün iki seçilmiş özeti işi
      durdurur.
    - **Digest.** API artefaktının `digest`'i (`sha256:…`) indirilen
      ZIP'in SHA-256'sıyla eşleşmeli. Eksikse indirilmez; uyuşmazsa
      kabul edilmez; ikisinde de iş durur. CRC ve üye adı ek
      denetimdir, kaynak doğrulaması değildir.
    - **İndirme.** API isteği token'lıdır. ZIP yönlendirmesi elle ve bir
      kez izlenir. İkinci istekte Authorization yoktur. Yalnız `https`;
      ikinci yönlendirme reddedilir.
    - **ZIP denetimi.** Tek üye, adı `shadow-day.json`. Boyut sınırlı,
      biçim/CRC temiz.
    - **Gün özeti sözleşmesi** (`_parse_day`; toplam adımı da aynı
      denetimi yapar). Beklenen sayılar sabit stratejiden türer
      (`ORBParams`: tur = giriş penceresi − açılış aralığı + 1 = 106,
      pencere = 15):
      - alanlar: baş (`day_schema`, `day`, `campaign`, `run_id`,
        `run_attempt`, `code_sha`, `status`, `reason`) zorunlu; gövde
        alanları bilinen kümeden; fazla alan yok;
      - `day` ISO biçiminde, planlı ve koşunun seans günüyle aynı;
        `campaign` bu kampanya; `run_id` pozitif, `run_attempt` = 1,
        `code_sha` 40 hex;
      - `status` ∈ {`tamam`, `eksik`}; `tamam` sebepsiz, `eksik`
        boş olmayan sebepli;
      - `params_version` kampanyanın strateji sürümü;
      - `turns.expected` = 106 ve `called + failed + missed =
        expected`; `symbol_turns.expected` = 106 × evren ve `observed ≤
        expected`;
      - `symbols` öğeleri karşılaştırma alanları ve `sip_available`,
        türleriyle (bool tamsayı sayılmaz, ondalık sonlu); aralık ve
        sinyal durumu tanımlı; sayaçlar negatif değil; semboller
        kampanya evreninde ve tekil;
      - karşılaştırma tutarlılığı (`compare_symbol_day`in
        üretebildikleri): `window_expected` = 15, `iex_present` ve
        `sip_present` ≤ 15, SIP penceresi IEX'siz sayılmaz, gecikmeli
        tamlık eksik pencere ister, bilinmeyen tur ≤ 106, aralık farkı
        yalnız `hesaplandi` ile, ilk niyet dakikası `[15, 121)`, sinyal
        ilk niyet dakikalarıyla uyumlu, SIP'siz sembolde SIP'e dayanan
        alan yok; `sip_reasons` anahtarları = SIP'siz semboller;
      - `tamam` gün sayaçlarla tutarlı: bütün gövde var; kaçan ya da
        hatalı tur yok; bütün sembol-turlar gözlendi; canlı-saf
        tutarsızlığı yok; SIP sebebi yok; evrenin her sembolü SIP'li.

      Biri bozuksa **bütün toplama durur**; özet sessizce düşürülmez.
    - Beklenmeyen artefakt, sayfa ya da biçim **kısmi toplam**
      yazdırmaz.
    - Süresi dolmuş artefakt atlanır; o gün aşağıdaki kanıt kuralıyla
      sınıflanır.
    - **Sayfa.** Gözlem koşu listesi tek sayfadır (100 koşu). Hafta içi
      günde iki cron koşusuyla planlı tarihler yaklaşık 10 haftalık
      aralığa sığmalıdır; (d) tarihleri buna göre seçer.
    - Tek yükleme `shadow-total-<kimlik>`, fiyatsız, 90 gün.
  - **Özet yokluğu "başlamadı" kanıtı değildir.** Gözlem başladıktan
    sonra runner kaybı, zaman aşımı ya da yükleme hatası da özet
    bırakmaz. Gün durumu kanıtla belirlenir:

    | Kanıt | Gün durumu |
    |---|---|
    | gün özeti var | özetteki durum (`tamam` / `eksik`) |
    | özet yok; bir kayıt adımı gerçekten koştu (adım sonucu `success` ya da `failure`) | `eksik (kayıt adımı koştu, özet yok)` |
    | özet yok; kayıt işi atlanmamış bir koşu var, adım kanıtı yok (kuyruk, kurulum, iptal) | `eksik (koşu var, özet yok)` |
    | özet yok; koşu geçmişi okundu, günün koşuları var ve hepsinde kayıt işi atlandı | `başlamadı` |
    | özet yok; koşu geçmişi okundu, günün hiç koşu kaydı yok | `bilinmiyor (koşu kaydı yok)` |
    | özet yok; koşu geçmişi okunamadı, eksik ya da kayıt işi sürüyor | `bilinmiyor` |

  - Kayıt işinin atlanmamış olması günü tekillik için rezerve eder;
    gözlemin başladığına tek başına kanıt değildir. Bu yüzden "başladı"
    denmez. İptal edilmiş adım, hiç başlamamış adımı da işaretleyebildiği
    için koşma kanıtı sayılmaz. Bir günün birden çok koşusu varsa en
    güçlü kanıt geçerlidir.

  - Dördü de 220'lik paydada kalır; özeti olmayan günün sembol-günleri
    `unknown`dur.
  - Daha önce bilinen bir koşunun silinmesi ya da artefaktın kaybolması
    günü `başlamadı`ya çevirmez. Silinmiş koşu ile hiç tetiklenmemiş
    cron okunarak ayrılamaz; hiç koşu kaydı olmayan gün `bilinmiyor`
    olur. `başlamadı` yalnızca koşular okunup kayıt işlerinin hepsi
    atlandıysa verilir.
  - Artefakt saklama süresi 20 planlı günü ve toplam adımını kapsamalıdır.
- **Hata yolları sentetik protokol testleriyle sınanır:**
  - yarım gün (erken kapanış) ve tatil;
  - yaz/kış saati geçişi;
  - geç tetikleme; aynı gün iki cron ya da ikinci koşu;
  - kapı ile gözlem işi arasında kuyruk gecikmesi; zaman alan takvim
    çağrısı;
  - kayıt adımı koştu ama özet yok; koşu var, adım kanıtı yok; kayıt
    işi sürüyor; koşu geçmişi okunamadı;
  - son süreden önce başlayıp sonra dönen SIP yanıtı;
  - toplam: başka kampanyanın ya da başka günün özeti; seçilmeyen koşu
    (olay, dal, yol, deneme); bitmemiş koşu; eksik ya da uyuşmaz
    digest; sözleşmeye uymayan alan; aynı kampanyanın önceki toplamı;
    çıktısız başarılı toplam koşusu; hesaplama sonrası upload hatası;
    silinmiş toplam artefaktı ile adım kanıtı; yanlış kaynak SHA, koşu
    ya da deneme; sıfır ya da azaltılmış beklenen tur; yanlış
    `params_version`; kayıt dosyasıyla yetkili tekrar (kimlik
    değişmeden); başka kampanyanın başarılı toplamı engel değil;
    son günden önceki koşu engel değil; başka kampanyanın tekrar kaydı
    durdurur;
  - 401/403, 429 ve 5xx;
  - eksik IEX ya da eksik SIP barı;
  - sıfır niyet.
- **Temizlik ve çıktı.**
  - `always()` temizlik yapılır.
  - Yalnızca özet JSON yüklenir: sayımlar, bps farkları ve bayraklar.
    Ham bar ve mutlak fiyat çıkmaz.
  - Log fiyat basmaz. Stratejinin karar gerekçesi fiyat içerir
    (`orb.py`, `Intent.reason`); gölge iş bu metni log'a ya da özete
    yazmaz. (c)'de bir testle sınanır.
  - Erişim hatası log'a ve kayda yalnızca sabit sınıfıyla geçer
    (`classify`). SDK istisnası yanıt gövdesini taşıyabilir.
  - Yanıt gövdesi ve istisna zinciri bastırılır. Bu, bütün gerçek veri
    yolları için testle gösterilir: bar, kotasyon, takvim, saat ve SIP.
  - Sözleşme deponun görünürlüğünden bağımsızdır: loglar herkesin
    okuyabileceği varsayılır.

## Sıra

| Adım | İçerik | Onay |
|---|---|---|
| (a) | Bu tasarım belgesi | Tasarım PR'ı, bağımsız inceleme |
| (b) | Kod: karar yolu, görülen kaydı, SIP kesme, karşılaştırma, `ShadowBroker`, özet; sentetik ve yerel HTTP testleri | Kod PR'ı, bağımsız inceleme |
| (c) | Workflow ve sözleşme testleri (schedule, başlangıç penceresi, tekillik, izinler) | Kod PR'ı, bağımsız inceleme |
| (e) | Toplam işi: kampanya kimliği, koşu seçimi, digest, gün özeti sözleşmesi, indirme ve toplam | Kod PR'ı, bağımsız inceleme; (d)'den önce |
| (d) | Yürütme kararı: 20 planlı tarih, eşikler, kesin commit ve o commit'in main CI'sı | Ayrı Codex kararı ve kullanıcı onayı |

Mevcut durum: (b) #51, (c) #52 ve (e) #53 ile birleşti. (d) kararı
aşağıda, §7'de kayıtlı.

## 7. Yürütme kaydı (d)

- **Karar:** #17/6181557402 (kullanıcı yetkisiyle Claude; Codex SHA bağlı ONAY'ı (d) PR'ında); kullanıcı onayı: #17/6181470236 (bu oturumdan olduğu gibi aktarıldı; karar kullanıcı yetkisiyle 6181557402).
- **Planlı günler (20 seans):** 2 Kasım, 3 Kasım, 4 Kasım, 5 Kasım, 6 Kasım, 9 Kasım, 10 Kasım, 11 Kasım, 12 Kasım, 13 Kasım, 16 Kasım, 17 Kasım, 18 Kasım, 19 Kasım, 20 Kasım, 23 Kasım, 24 Kasım, 25 Kasım, 30 Kasım, 1 Aralık. Dışarıda: NYSE tam kapanışlar ve 13:00 erken kapanışlar (testte liste).
- **Evren:** `config/universe.yaml` (11 sembol). **Eşikler:** `Thresholds` varsayılanları. **Strateji:** `orb-7b32942a`. **Şemalar:** gün 1, toplam 1.
- **Kaynak:** gözlem koşusu `schedule` ya da dış başlatıcının `workflow_dispatch`'i (`OBSERVATION_EVENTS`, #59) ile `main`'in o anki commit'ini kullanır; her gün özeti gerçek `code_sha`, `run_id`, `run_attempt` yazar ve toplam işi bunu API koşusuyla doğrular. Bağ SHA sabiti değil uygulama parmak izidir.
- **Kampanya kimliği ve parmak izi (Codex 6181551003):** (d) dalının son uygulama ağacından hesaplandı ve parmak izinin dışındaki testte sabitlendi (`test_the_campaign_identity_is_pinned_to_the_implementation_tree`): parmak izi `40db894c91c99172ee03e7817e7009c599e26e4a43ab4b6cafa15bc6a02729c5`, kampanya kimliği `0610f86a0a8f7d13a6eddadd9e11dad2e617b00bb96646cfaabd248add2ec74d`, toplam artefaktı `shadow-total-0610f86a0a8f7d13`. Önceki değerler (`7f9f1fed…`, `4a096c7e…`) #59 (`workflow_dispatch` ve tetik allowlist'i; parmak izindeki `shadow-observation.yml` ve `shadow_job.py` değişti) birleşmeden önceki ağaçtandı; kullanılmadı. Birleştirme ağacında yeniden doğrulanır: main CI'da aynı test ve birleşmeden hemen sonra #17'ye yazılan kayıt; ilk planlı günün özetindeki `campaign` ve toplam artefaktının adı bununla karşılaştırılır. Parmak izi kapsamındaki bir dosya değişirse test kırmızıya döner.
- **Hazırlık payı:** ana dal birleşmesi ve başarılı main CI en geç **27 Ekim 2026 16:00 America/New_York**; böylece 28–30 Ekim üç tam seans kalır. Yetişmezse yedek pencere 9 Kasım – 8 Aralık, ayrı tarih/kimlik PR'ı ve aynı inceleme kapılarıyla; örtük tarih değişikliği yok.
- **Takip yöntemi:** Claude'un oturumu, Claude Code zamanlı görevi ile her planlı günün seansından sonra (en geç 21:30Z) o günün `shadow-observation` koşusunu Actions API'den okur: koşu, iş ve adım sonuçları, `Gozle` adımının sabit log satırları (gün özeti durumu, istek sayıları; fiyat yok); bulguyu #17'ye yazar. Bu zamanlı görev bir iddia değil, çalıştırılan bir mekanizmadır; çalışmazsa Codex ya da kullanıcı aynı bilgiyi Actions sayfasından (workflow `shadow-observation`, o günün koşusu) okur. Boş schedule kanıtı: ilk planlı günden önceki cron koşuları (12:50Z/13:50Z) yalnız "plan disi gun" demeli; kanıt (koşu kimlikleri) (d) PR'ında.
- **Dondurma:** bu PR'ın birleşmesinden son toplamın doğrulanmasına kadar parmak izinin kapsamı (`src/tlab/**`, `config/*.yaml`, `requirements.lock`, iki gölge workflow'u) main'e girmez; Dependabot lock PR'ları bekler. Dokunan bir merge kimliği değiştirir ve toplamı durdurur.
- **İlk gün denetimi:** ilk planlı günün seansından sonra kayıt işi log'unun sabit satırları #17'ye yazılır. Sistematik hata → #17 kararıyla durdurma; iptal edilen kampanyanın eksik günleri ve sebebi bu bölümde kayıtta kalır; yeni tarihler yeni kampanyadır.
- **Toplama:** en erken son planlı günün ertesi New York günü ve bütün koşular bitince; kullanıcının tek `workflow_dispatch` tıklaması ayrı #17 kararıyla. Tekrar yalnız `config/shadow-total-retry.json` kaydıyla.
- **Tekillik:** bu kampanya için gün özetlerinde tam kimlik, toplam artefaktında `shadow-total-<ilk 16 hane>`.
