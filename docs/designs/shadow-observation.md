# Salt okunur gölge gözlem v1: tasarım sözleşmesi

Tarih: 2026-10-13. Koordinasyon: #17. Kayıtlar:
- Claude ön raporu 6151855559; Codex kararı 6152090021 (yön uygun,
  protokol revizyonu);
- Claude ön raporu 6153247091; Codex 6154024443 (revizyon doğru yönde;
  üç açıklık: `t*`, tekillik durumları, sızıntı ve tutarlılık).

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
  - `tamam`;
  - `eksik`: geç başladı, kesildi ya da SIP gelmedi;
  - `başlamadı`.

  Eksik ve başlamamış günler paydadan sessizce düşmez.
- **Payda.** Canlı pencere tamlığı için 20 × 11 = 220 planlı sembol-gün.
  Erişilemeyen gözlem `unknown` olarak ayrıca gösterilir.
- **Planlı ızgara.** Giriş penceresinin her dakikası için bir tur:
  `açılış + m dk + 7 sn`, `m = 15 … 120`. Dakikanın turu, o dakika içinde
  koşan gerçek turdur. Turlar kayda geçer; kaçan dakika telafi edilmez.
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
- **Aralık farkı:** IEX görünümünde pencerenin ilk tam olduğu tur
  (gecikmeli olabilir). SIP aynı tura kesilir.
- **Niyet:** her tarafın ilk niyeti.
  - İlk niyetten önceki planlı dakikalardan birinin turu yoksa ya da o
    turun verisi alınamadıysa o tarafın ilk niyeti `unknown` olur.
  - Bu durum "iki tarafta da niyet yok" sayılmaz.
- **Koşullu ölçüler** için pay, payda ve `unknown` ayrı yazılır:
  - aralık farkı, iki pencere tamsa;
  - niyet uyumu, en az bir tarafta niyet varsa.
- **Niyetsizlik ayrı sayılır.** İki tarafta da niyet yoksa bu "uyum
  geçti" değildir; ayrı sayaçtır.
- **Sembol bazında rapor.** Toplamın yanında sembol bazında rapor
  verilir; tek bir sembolün sürekli başarısızlığı toplamda kaybolmaz.
- **Aralık farkının formülü:**
  `bps = (OR_IEX − OR_SIP) / OR_SIP × 10 000`. Üst ve alt uç ayrı ayrı.

**Eşik önerileri (kalibre edilmiş kapı DEĞİL; yürütme kararında
sabitlenir):**

| Ölçü | Öneri | Asgari destek |
|---|---|---|
| IEX başlangıç tamlığı (`t*`) | ≥ %95 | 220 planlı sembol-gün; `unknown` ayrı |
| Aralık farkı | iki uç ≤ 5 bps, ≥ %90 | iki pencere de tam ≥ 100 sembol-gün |
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
    küçük olanlar) sayılır. Eşzamanlılık grubu workflow düzeyindedir;
    sonraki bir koşu bu koşu bitmeden başlayamaz, iki kapı yarışamaz.
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
  - **İzin maliyeti:** yalnızca kapı işinde `actions: read`. Alpaca
    secret'ları yalnızca gözlem adımında bulunur.
  - `workflow_dispatch` yok. Elle yeniden başlatma zaten geç başlangıç
    olur.
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
  - belirlenmiş son süre (giriş penceresi sonu + 45 dk) aşılmadı.

  Aşılırsa gün `eksik` (SIP gelmedi) olarak kaydedilir.
  - İlk SIP isteği son karar anından en az 15 dk sonra yapılır: ücretsiz
    plan SIP'in son 15 dakikasını vermez.
- **Günlük ve toplam özet.**
  - Her gün yalnızca o günün özetini yükler: gün durumu ve sembol-gün
    karşılaştırmaları, fiyatsız.
  - 20 günlük toplam, son planlı günden sonra secret'sız ayrı bir işte
    kurulur. İş, günlük özet artefaktlarını Actions API'sinden okur
    (`actions: read`).
  - Özeti bulunmayan gün `başlamadı (kayıt yok)` sayılır.
  - Artefakt saklama süresi 20 planlı günü kapsamalıdır.
- **Hata yolları sentetik protokol testleriyle sınanır:**
  - yarım gün (erken kapanış) ve tatil;
  - yaz/kış saati geçişi;
  - geç tetikleme; aynı gün iki cron ya da ikinci koşu;
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
| (d) | Yürütme kararı: 20 planlı tarih, eşikler, kesin commit ve o commit'in main CI'sı | Ayrı Codex kararı ve kullanıcı onayı |

Mevcut hazırlık: (b) bu belgeye göre yerel bir dalda hazırlanıyor
(ön rapor 6153247091). Bu belge incelenmeden kod PR'ı açılmaz.
