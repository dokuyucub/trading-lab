# Gözetimsiz paper kabulü ve yürütme ortamı (gölge sonrası faz)

Durum: **taslak, karar değil**; ÖN RAPOR #17/6182224516, Codex görüşü 6182905717 işlendi. Bu belge **kod değiştirmez ve hiçbir
yetki vermez**: emir, tetik, holdout, ücretli abonelik ya da canlı para bu
belgenin kapsamı dışındadır. Gölge gözlem kampanyası (tasarım
`shadow-observation.md`; kampanya kimliği taslaktır, nihai kimlik #54'te
yeniden hesaplanır) bitip toplam doğrulanmadan
burada yazılan hiçbir adım başlamaz.

## Amaç ve sınır

Gölge kampanyası üç soruya kanıt üretir (feed uyumu, eksik açılış barı
kontrolü, canlı karar yolu). Bu belge o kanıt **olumlu** çıkarsa sonraki
adımın ne olduğunu, hangi şartla başlayabileceğini ve nerede çalışacağını
önceden yazar; **olumsuz** çıkarsa paper'a geçilmeyeceğini de yazar. Karar
sonuç görülmeden yazılır (AGENTS §3.11 ruhu): sonuçtan sonra ölçüt
gevşetilmez.

**Ne değildir:** kârlılık iddiası değildir; canlı para planı değildir;
holdout açma ya da parametre terfisi değildir; gölge toplamını
yorumlamaz.

## 1. Kabul ölçütleri — gölge sonucuna bağlı

Paper'a geçiş için hepsi birlikte gerekir:

| Ölçüt | Kaynak | Eşik |
|---|---|---|
| `iex_window_initial` | toplam özeti | **GEÇTİ** (`Thresholds` varsayılanı) |
| `range_within_bps` | toplam özeti | **GEÇTİ** |
| `intent_agreement` | toplam özeti | **GEÇTİ** |
| Gün kapsaması | `days` | en az 15/20 `tamam`; eksik günlerin sebebi kayıtta ve sistematik değil |
| İlk gün denetimi | #17 KAYIT | sistematik hata yok, durdurma kararı verilmemiş |
| Kayıt işi | günlük KAYIT'lar | hiç koşu olmayan planlı gün yok ya da sebebi açıklanmış |

**Gölge testlerinin geçmesi neyi göstermez (Codex 6182905717):** kârlılığı
ve emir yaşam döngüsünü (gönderim, dolum, koruma bacakları, iptal,
mutabakat) **göstermez**. Gölge emirsizdir. Paper kabulü bu yüzden iki
ayrı kapıdan geçer: (i) yukarıdaki veri/karar yolu kanıtı; (ii) emir
yaşam döngüsünün gerçek paper hesapta **ayrıca** gözlenmesi (bölüm 4,
"ilk paper günleri"). (i) geçti diye (ii) atlanmaz.

**KALDI ya da BELİRSİZ** (herhangi biri): paper'a geçilmez. Sonraki
seçenek (ücretli SIP feed, farklı pencere, sembol değişikliği) **ayrı
kararla ve yeni kampanyayla** değerlendirilir; aynı kampanyanın sayılarına
bakıp eşik değiştirilmez.

## 2. Doğrulanmamış kalan noktalar

| Nokta | Durum | Kapatma yolu |
|---|---|---|
| Canlı yolun journal'a yazdığı feed | testle kapanıyor (`tests/test_cli_run.py`, ÖN RAPOR 6182121005) | — |
| Paper dolumlarının hangi veriye göre simüle edildiği | **doğrulanmadı** | sağlayıcı belgesi + küçük, kayıtlı gözlem (tek sembol, tek gün, emirli paper); gözlem bu belgenin **kapsamı dışında**, ayrı karar |
| Gerçek broker karşısında kill-switch ve gün sonu kapanışı | sentetik testlerde var; gerçek paper hesapta görülmedi | ilk paper günlerinde özel kontrol (bölüm 4) |

## 3. Yürütme ortamı — açık soru

Kullanıcı kod çalıştırmıyor; sistem şu ana kadar GitHub Actions'ta
koştu. Mevcut araç olduğu için Actions'a peşinen bağlanılmaz (Codex
6182905717); dört seçenek aynı ölçütlerle karşılaştırılır:

| Ölçüt | A. Actions tek job | B. Actions iki dilim | C. Kullanıcının makinesi | D. Yönetilen barındırma |
|---|---|---|---|---|
| Kullanıcının kod işletmesi gerekmez | evet | evet | **hayır** (kurulum, güncelleme, yeniden başlatma kullanıcıda) | evet, kurulum bir kez (Claude/Codex PR'ıyla) |
| Kalıcı journal | job içinde; gün sonunda artefakt ya da yok | dilimler arası taşıma sorunu | diskte, kalıcı | kalıcı disk/volume; yedek sorumluluğu belirlenmeli |
| Yeniden başlatma | her gün temiz başlar; broker'dan kurulum | dilim başında kurulum | süreç yöneticisi (systemd) | platform yeniden başlatır; kill-switch kaydı DB'de (README) |
| Tek aktif bot | job eşzamanlılık kilidi (`concurrency`) | aynı | tek süreç | tek örnek; ölçeklendirme kapalı |
| Kapanış / kill-switch | job yaşarken; **6 saat sınırı** nedeniyle 15:20'de erken kapanış | ikinci dilim kapanışı yapar | tam seans | tam seans |
| Alarm | Actions bildirimi + zamanlı kontrol (gölge deseni) | aynı | kullanıcının kurması gerekir | platform sağlık kontrolü + zamanlı kontrol |
| Secret'lar | Actions secrets | aynı | makinede dosya | platform secret deposu |
| Aylık maliyet ve sorumluluk | 0 (public repo dakika sınırı içinde; doğrulanmalı) | aynı | donanım/elektrik + kullanıcının zamanı | ücretli (küçük VM/konteyner); **satın alma ayrı kullanıcı kararı** |
| Kod değişikliği | erken kapanış + günlük temiz başlangıç | durum taşıma (yeni) | yok | konteyner tanımı + sağlık ucu (küçük) |

Seçeneklerin ayrıntısı:

### A. GitHub Actions, planlı gün başına tek job

- Secret'lar yalnız Actions'ta; koruma bacakları borsada (AGENTS §3.5);
  mutabakat her koşuda broker'dan (§3.7).
- **Sınır:** hosted job üst sınırı **6 saat** (GitHub belgesi; Codex
  doğrulasın), seans 09:30–16:00 = 6,5 saat. Gün sonu kapanışı (§3.5a)
  job yaşarken olmalı. Tek job seansı kapsayamaz.
- Daraltılmış biçim: job 09:25–15:20 çalışır, 15:10'da **kendi** kapanışını
  yapar (pozisyon kapat, emir iptal). ORB stratejisi için seansın son 40
  dakikası zaten işlem açılmayan bölüm; kayıp yalnızca "15:50'ye kadar
  tutma" fırsatıdır. Strateji fonksiyonu aynı kalabilir, ama bu **ölçülen
  davranışın değişmesidir** (Codex #57/6225592912): pozisyon taşıma süresi,
  gerçekleşmeler ve sonuç değişir. Bu yüzden 15:10 kapanışı ayrı bir
  config/yürütme kararı ister ve değerlendirme aynı kapanış ayarıyla
  yapılmış bir baseline ile karşılaştırılır; mevcut SIP baseline'ı (16:00
  kapanış) doğrudan karşılaştırma ölçütü değildir.
  `flatten_before_close_minutes` ayarıyla ifade edilebilir mi, kodda
  bakılır (Aralık'ta).

### B. GitHub Actions, iki dilim

- Sabah/öğleden sonra iki job; aradaki durum (kill-switch kaydı, bekleyen
  emir kimlikleri, günlük zarar sayacı) **nerede durur?**
- Artefakt olarak taşımak hesap değeri ve işlem kaydı içerir; "hesap değeri
  dışarı çıkmaz" kuralıyla çelişir, ayrı karar ister.
- Broker'dan yeniden kurulum (§3.7) neyi karşılar: pozisyon, açık emir,
  dolumlar — evet; günlük zarar sayacı (hesap `last_equity` ile
  hesaplanabilir), kesinleşmemiş emir karantinası (süre bazlı, yeniden
  kurulamaz → ikinci dilim başında bekleyen emirleri okuyup "bilinmiyor"
  saymak gerekir). Belgede madde madde.

### C. Kullanıcının sürekli çalışan makinesi

- README "Kesintisiz çalışma" bu varsayımla yazıldı; tam seans, kalıcı
  journal, yeniden başlatma süreç yöneticisiyle.
- Kullanıcının kurulum, güncelleme, secret ve izleme sorumluluğu; kullanıcı
  şu ana kadar kod çalıştırmadı. Bu bir eleme değil, **maliyetin kimde
  olduğu** sorusudur; kullanıcı isterse geçerli seçenektir.

### D. Yönetilen barındırma (küçük VM ya da konteyner hizmeti)

- Kullanıcı kod işletmez: konteyner tanımı ve dağıtım PR ile gelir, hizmet
  süreci yeniden başlatır, secret'lar hizmetin deposunda, journal kalıcı
  diskte.
- Tam seans ve gün sonu kapanışı job sınırı olmadan; tek örnek.
- Ücretli: **hizmet satın alma ayrı kullanıcı kararıdır**; bu belge satın
  alma izni değildir. Hangi hizmet, hangi bölge, aylık tutar ve kimin
  ödediği karar kaydında yazılır.
- Yeni gereksinim: sağlık ucu ve dışarıdan izleme (zamanlı kontrol aynı
  desenle, hizmet log'u ya da journal özeti üzerinden; hesap değeri
  dışarı çıkmaz).

**Öneri (gerekçeli, karar #17'de):** paper'ın ilk dönemi için **A'nın
daraltılmış biçimi** (sıfır ek maliyet, mevcut secret ve inceleme düzeni;
bedeli günün son 40 dakikası ve her gün temiz başlangıç), D'nin maliyet ve
sorumluluk hesabı aynı anda kullanıcıya sunulur; D'ye geçiş paper'da tam
seans ihtiyacı gösterildiğinde. B yalnız A'nın kaybı ölçülüp kabul
edilemez bulunursa ve durum taşıma kuralı ayrıca kararlaştırılırsa. C
kullanıcı isterse.

## 4. Sahiplik ve kapılar

- **Tetik:** `schedule` (gölge deneyimine göre) ya da kullanıcının günlük
  tek tıklaması; gölge kampanyası schedule'ın güvenilirliğini gösterecek.
- **Kill-switch:** günlük zarar sınırı aşıldığında hesap genelinde iptal ve
  kapatma (§3.5a) job içinde; job yoksa koruma bacakları borsada. "Bugün
  bir daha açma" kararının **gün içi kalıcılığı çözülmüş değildir**
  (Codex #57/6225592912): job'un yeniden denenmesi, elle yeniden
  başlatılması ya da süreç çökmesinde karar kaybolursa ikinci süreç aynı
  gün yeniden işlem açabilir. "Gün zaten tek job" bu riski kapatmaz. Bu
  çözülmeden hiçbir seçenek gözetimsiz paper için kabul edilmez.
  **Gereksinim (tasarım, kod yok):**
  - Kalıcı journal: kill-switch kaydı (seans günü, sebep, zaman) süreç
    dışında, yeniden başlatmada okunabilir bir yerde; A/B için Actions
    dışında ya da broker'dan türetilebilir bir kanıt (ör. o gün kill-switch
    sonrası açılmış emir yok ve günlük zarar sınırı aşılmış).
  - Gün içi kilit: başlangıçta önce kilit/kayıt okunur; kayıt okunamıyorsa
    ya da belirsizse yeni giriş **yok** (fail-closed), yalnız koruma ve
    kapanış.
  - Testler: kill-switch sonrası yeniden başlatma, ikinci deneme, elle
    başlatma ve okunamayan kayıt senaryoları sentetik olarak.
  - **Durum (3 Kasım 2026, #17 ÖN RAPOR 6605979484):**
    - **Süreç düzeyi çözülü.** Karar `daily_state`'e yazılır; aynı
      journal'la yeniden başlayan süreç günü kapalı bilir
      (`test_runner.py::test_kill_switch_survives_a_process_restart`).
    - **Ortam düzeyi kısmen çözülü** (`tests/test_kill_switch_durability.py`):
      - Journal'ı olmayan taze süreç, zarar hesapta hâlâ sınırın
        altındaysa ilk turda yeniden durur: bekleyen emirleri iptal
        eder, pozisyonu kapatır, kararı yazar.
      - Gün durumu okunamazsa tur hata fırlatır, emir gitmez. Bu
        "iş kırmızı biter" demek değildir: `run_forever` hatayı
        yakalar ve sonraki turu dener.
    - **Açık 1:** kapanış sınırın hemen üstünde gerçekleşirse (örnek:
      %−2,1'de tetiklenip %−1,95'te kapanmak) taze süreç zararı sınırın
      üstünde görür ve aynı gün yeniden işlem açar. Sentetik denemeyle
      gösterildi.
    - **Açık 2** (Codex #61/6694382019; karakterizasyon testiyle
      sabitlendi): gün durumu okunamazsa hata gün sonu kapanışının da
      önüne geçer. Sebebi `run_once` sırası: kill-switch kontrolü
      `must_flatten`'dan önce geliyor. `run_forever` her turu aynı
      hatayla bitirir; açık pozisyon kapanmaz, bekleyen emir iptal
      edilmez, koruma yalnız borsadaki bracket bacaklarıyla sürer.
      Doğru davranış: okuma hatasında yeni giriş yok, ama iptal,
      kapanış ve gün sonu kapanışı sürer (fail-closed giriş, fail-open
      koruma).
    - Düzeltme yönü:
      - Açık 1 için broker'dan türeyen, fail-closed bir kural: bu güne
        ait journal kaydı yokken broker'da bugün dolum varsa gün
        "belirsiz" sayılır; yeni giriş yok, yalnız koruma ve kapanış.
        Bunun üstüne A için gölgedeki gibi "günde tek koşu" kapısı gelir.
      - Açık 2 için gün durumu okuma hatası "gün kapalı" gibi işlenir
        (giriş yok); iptal, kapanış ve `must_flatten` yolu buna rağmen
        çalışır. Karakterizasyon testi o zaman yeni beklentiyle değişir.
    - Kod `src/` altında olduğu için kampanya dondurması bitince ayrı PR
      ile gelir. Dondurulmuş main'e üretim düzeltmesi girmez.
    - Bu iki açık kapanmadan ortam güvenliği tamamlanmış sayılmaz.
    - **Düzeltme (dal `claude/killswitch-fix`, #17 ÖN RAPOR 6753982638;
      kampanya dondurması bitmeden main'e girmez):**
      - Açık 2: `_check_kill_switch` gün durumu okuma hatasını yakalar ve
        turu bitirmez. `LoopResult.entries_blocked` yeni girişi engeller;
        iptal, `must_flatten` ve zarar sınırı kapatması sürer. Karar
        yazılamazsa kapatma yine yapılır ve not düşülür.
      - Açık 1: zarar sınırı aşılmamışsa ve bu seans için journal'da
        gönderilmiş emir yoksa (`orders_submitted_since`), broker'da
        bugün gerçekleşme varsa gün "belirsiz" sayılır. Karar
        `daily_state`'e yazılır ve pozisyonlar kapatılır.
        - Gerçekleşmeler okunamazsa yalnız giriş engellenir.
        - Süreç kendi emrini göndermeden önce yazdığı için normal gün
          etkilenmez.
      - Testler `tests/test_kill_switch_durability.py`'de; eski
        karakterizasyon testi ters beklentiye çevrildi.
      - Yazılamayan karar (Codex #63/6772282247 P1): `_record_halt`
        hata alırsa karar süreç belleğinde (`_unpersisted_halts`) tutulur.
        Sonraki her turda gün kapalı sayılır, kapanış sürer ve kalıcı yazma
        yeniden denenir; başarılı olunca bellekten düşer.
        - **Yeniden başlatma için kabul sınırı:** süreç, yazma başarılı
          olmadan yeniden başlarsa bellek kaybolur. O durumda koruma şunlara
          dayanır:
          - zarar hâlâ sınırın altındaysa zarar kuralı;
          - journal taze ise belirsiz gün kuralı;
          - journal hâlâ yazılamıyorsa write-ahead: karar ya da emir
            yazılamazsa emir gönderilmez (`_evaluate_universe`).
        - Kabul edilen açık dar: geçici yazma hatası, bir sonraki turdan
          önce yeniden başlatma, yazmanın düzelmiş olması, zararın sınırın
          üstüne dönmesi ve journal'da bugünün emri bulunması aynı anda
          olmalı. Hata ERROR log'u ve tur notuyla görünür kalır. Paper
          öncesi "günde tek koşu" kapısı bu durumda ikinci süreci zaten
          başlatmaz.
      - Gün durumu bilinmiyorken bekleyen giriş (P2): `entries_blocked`
        iken bizim, pozisyonu olmayan sembollerdeki bütün bekleyen girişler
        yaşına bakılmadan iptal edilir.
        - Turun başında pozisyonu görünen sembolde iptal yapılmaz.
          Kısmen dolmuş girişin kalan miktarı bekler; bu miktar risk
          kapısından geçmiş ilk emrin parçasıdır.
      - İptal/dolum yarışı (Codex #63/6777889127, 6840456161, 6844629736,
        6863854867, 6993997992, 7115896065,
        7116120239, 7139373707, 7154998289, 7155309564):
        bayat giriş
        iptali (hem TTL hem `entries_blocked` yolu) yalnız girişin
        `broker_order_id`'sine gider (`Broker.cancel_order`). Sembol bazlı
        iptal bu yoldan çıktı; koruma bacaklarının kimliği iptal çağrısına
        hiçbir senaryoda girmez.
        - Sonuç iptal isteğinin kabulünden ya da girişin açık listeden
          kaybolmasından çıkarılmaz. İptal asenkron kesinleşir; giriş iki
          okuma arasında dolabilir. İptalin sonucu girişin kendi durumundan
          (`Broker.get_order`: `status`, `filled_qty`) çıkarılır; sembolde
          görünen pozisyonun koruması ayrıca ölçülür:
          - terminal değil (`pending_cancel`, `new`, `partially_filled` …)
            → izlemede: journal'da `cancel_pending`, süreçte bellek; o
            turda yeni giriş yok (`entries_blocked`). İzlemedeki girişe
            ikinci iptal gitmez. Dolum varsa (`filled_qty > 0`) koruma
            kontrolü iptal kesinleşmeden HEMEN ve her turda yeniden
            yapılır: kapsam yoksa gün kapanır, varsa izleme sürer. İptalin
            yaşam döngüsü ile dolan miktarın koruması ayrı sorulardır;
          - terminal (`canceled`/`expired`/`rejected`) ve dolum sıfır →
            "canceled";
          - dolum sıfır ya da bilinmiyor ama tur başında sembolde pozisyon
            görünüyor → brokerın dolum bilgisi bayat olabilir; pozisyonun
            koruması ölçülür, kanıtlanamazsa gün kapanır ve iz kapanmaz;
          - terminal ve dolum var (`filled` dahil) ya da dolum bilinmiyor
            → koruma kontrolü; kapsıyorsa "filled". Korumasız dolumda
            durum değiştirilmez, gün kararı kalıcıdır;
          - `get_order` okunamazsa → aşağıdaki "Giriş okunamıyorsa" maddesi.
        - İzlemedeki iptaller her turda, kill-switch ve gün sonu
          kontrollerinden sonra, sembolde pozisyon görünse de çözülür.
          Yeniden başlayan süreç izlemeyi journal'dan devralır. Geç görünen
          dolum böylece koruma kontrolünden düşmez. Mutabakat izlenen satırı
          `closed` ile ezmez (yazıcıda koşullu güncelleme): iz aynı sütunda
          durur ve ezilirse yeni süreç onu bulamaz.
        - **İptal niyeti write-ahead:** iptal çağrısından ÖNCE journal'a
          `cancel_requested` yazılır, çağrıdan sonra `cancel_pending`.
          Niyet yazılamazsa iptal gönderilmez; tur `entries_blocked` olur
          ve not düşülür. Giriş ve bacakları brokerda kalır; gün sonu
          kapanışı ve zarar sınırı yolu sürer. Yeniden başlayan süreç
          bellekte olmayan `cancel_requested` satırının iptalini yeniden
          gönderir (ilk istek hiç gitmemiş ya da sonucu yazılmamış olabilir;
          ikinci istek yalnız girişin kimliğine gider ve zararsızdır), sonra
          sonucu çözer. `cancel_pending` satırına ikinci iptal gitmez.
        - **Ulaşamayan iptal (Codex #63/6993997992 P1):** `cancel_pending`
          yalnız brokerın iptali ALDIĞI doğrulanınca yazılır: çağrı hatasız
          döndü ya da emir `pending_cancel`/terminal görüldü. Çağrı hata
          verirse satır `cancel_requested` kalır; PENDING çözümü bu ayrımı
          silmez. Sonraki tur önce emri okur: ulaşmışsa yeni istek gitmez
          (cevabı kaybolan istek), hâlâ aktifse aynı giriş kimliğine yeniden
          gönderilir. Süreç başına en fazla `MAX_CANCEL_ATTEMPTS` (3) deneme;
          girişin okunamadığı tur da denemeye sayılır, sınır okuma hatasıyla
          uzamaz. Aşılırsa gün kill-switch ile kapanır ("iptal iletilemedi") ve
          `_flatten_all` bütün emirleri iptal edip kapatmayı her turda
          yeniden dener.
        - **Önceki seanstan kalan iz (P2):** koruma kontrolünde `filled_qty`
          yalnız aynı seansta kullanılır (pozisyon okuması dolumu henüz
          göstermeyebilir). Giriş önceki bir seanstansa tutulan miktar
          brokerdaki pozisyondur: pozisyon yoksa hesap düz doğrulanmıştır ve
          takip kapanır; pozisyon varsa normal kapsam kontrolü yapılır.
          Yalnız tarihe bakıp satırı atlamak açık kalan pozisyonu
          kaçırırdı.
        - **Koruma kanıtı ile gerçekleşme ihtimali ayrı sorular (Codex
          #63/7115896065, 7116120239):**
          - *Koruma kanıtı* pozitif listedir: kapsam yalnız `new` ve
            `partially_filled` durumundaki stoplardan hesaplanır.
            `pending_cancel`, `pending_replace`, `held` ve listede olmayan
            her durum koruma sayılmaz.
          - *Geçiş durumu* (Codex #63/7139373707, 7154998289): `accepted`
            (henüz borsaya iletilmedi), `pending_new` (borsa henüz kabul
            etmedi) ve `accepted_for_bidding` durumundaki stop sonradan
            `rejected` olabilir ([Alpaca Order Lifecycle](https://docs.alpaca.markets/us/docs/orders-at-alpaca#order-lifecycle)).
            Bu yüzden koruma sayılmaz ve **bekleme tanınmaz**: kapsam yalnız
            koruma kanıtı olan stoplarla sağlanmıyorsa gün o turda kapanır.
            Bekleme sayacı bilerek yok. Böyle bir sayaç süreç belleğinde
            tutulursa yeniden başlatmada sıfırlanır, girişin okuma hatasında
            da ilerlemez; koruma süresi sınırsız uzayabilir. Gün kararı ise
            `daily_state`'e kalıcı yazılır. Yazılamazsa karar süreç
            belleğindedir; yeniden başlayan süreç aynı sonuca izlenen satırı
            yeniden değerlendirerek varır. Bedeli: yarış anında stop hâlâ
            geçiş durumundaysa gün gereksiz kapanabilir; `held` ile birlikte
            ilk paper günlerinde gözlenir.
          - *Giriş okunamıyorsa* (Codex #63/7154998289): dolum miktarı
            bilinmez, ama sembolde görünen pozisyonun koruması yine ölçülür.
            Pozisyon yeniden okunur; bu okuma hata verirse tur başındaki
            görüntü kullanılır. Pozisyon görünüyor ve stoplarla kapsanmıyorsa
            ya da açık emirler okunamıyorsa gün kapanır. İki kaynakta da
            pozisyon yoksa ya da pozisyon kapsanıyorsa takip ve giriş engeli
            sürer. Bedeli: giriş ve emir listesi aynı turda okunamazsa
            stopla kapsanan pozisyon da kapatılır.
          - **`held` doğrulanmadı.** Alpaca bracket bacakları ebeveyn
            tamamen dolunca etkinleşir. Ebeveyn kısmi dolumdayken `held`
            stop kesinlikle korumaz. Tam dolumdan sonra `held` gösterilen
            bir stopun çalıştığına dair bu repoda doğrulanmış bir belge
            yok; bu yüzden fail-closed olarak o da koruma sayılmaz. Bedeli:
            Alpaca bu durumu gösteriyorsa, nadir iptal/dolum yarışında gün
            gereksiz kapanabilir. İlk paper günlerinde bacak durumları
            gözlenir; gevşetme ayrı karar gerektirir.
          - *Gerçekleşme ihtimali* terminal olmayan her çıkış emri içindir:
            iptali süren, `held` ya da bilinmeyen durumdaki emir koruma
            sayılmasa da dolabilir.
          - Önceki seansın girişinde pozisyon sıfırsa hesap ancak sembolde
            gerçekleşebilecek bir çıkış emri (stop ya da hedef) da kalmadıysa
            düz sayılır. Kalmışsa gün kapanır, `_flatten_all` bütün emirleri
            iptal eder ve takip korunur. Sonraki seansta iptal kesinleşmiş,
            pozisyon ve emir yoksa takip kapanır. Emir iptalden önce dolup
            ters pozisyon açtıysa o pozisyon korumasız sayılır, gün kapanır
            ve pozisyon kapatılır.
        - **Koruma kuralı:** sembolde çıkış yönünde, `stop_price` taşıyan
          ve koruma kanıtı durumundaki açık emirlerin kalan miktar toplamı ≥ `max(filled_qty, pozisyon
          miktarı)`. Gereken miktar emrin kendi dolumundan gelir; pozisyon
          okuması dolumu henüz göstermese de kontrol yapılır. Kalan
          miktarı bilinmeyen emir kapsam sayılmaz.
        - Kural sağlanırsa bacaklara dokunulmaz. Sağlanmazsa ya da giriş
          okunabiliyorken pozisyon/emir okunamazsa gün kill-switch ile
          kapanır (fail-closed). Giriş de okunamıyorsa "Giriş okunamıyorsa"
          maddesi geçerlidir. Gün kararı her turda kapatmayı yeniden dener;
          yazılamazsa bellekteki kilit geçerlidir.
        - Testler `tests/test_entry_cancel_race.py`'de, iki yolda:
          dolum iptal çağrısının içinde (kısmi, tam, bacaksız, eksik
          bacak, okunamayan broker) ve iptal kabul edilip `pending_cancel`
          kalırken dolumun sonraki turda pozisyon okumasından sonra, açık
          emirler okunurken olması (tam kapsam, bacaksız, eksik bacak,
          pozisyonu henüz görünmeyen dolum, dolumsuz kesinleşme, izlemenin
          sürmesi, yeniden başlatma, okunamayan giriş) ve iptal kesinleşmeden
          kısmi dolum (`pending_cancel`/`partially_filled`: kapsam yok,
          eksik, tam; artan dolumda kapsamın yeniden ölçülmesi; yeniden
          başlatma). Ek gruplar: koruma sayılmayan stop durumları; önceki
          seanstan kalan iz ve sahipsiz çıkış emri; kalıcı gün kararının
          yeniden açılan bağlantıdan okunması ve yazılamayan kararın izlenen
          satırdan yeniden kurulması; okunamayan giriş (pozisyon var/yok,
          emirler okunamıyor, tur başı görüntüsü, deneme sınırı); mutabakatın
          izlenen satırı ezmemesi; bayat dolum bilgisi; satış yönlü giriş.
        - **Doğrulanmadı:** Alpaca'da kısmi dolum + ebeveyn iptalinden
          sonra bacak miktarının dolan miktara inip inmediği ve bacakların
          düz `status=open` listesinde görünüp görünmediği. İlk paper
          günlerinde (§4, emir yaşam döngüsü kabulü) gösterilmeli. Kural
          iki durumda da güvenli: bacaklar görünür ve kapsıyorsa dokunulmaz,
          görünmüyorsa gün kapanır. `done_for_day` gibi terminal sayılmayan
          bir durum izlemeyi gün sonuna kadar uzatır; o sürede yeni giriş
          yoktur. Yarış nadir olduğu için bedeli nadir bir kapalı gündür.
          Dış araştırma (ikincil kaynaklar; ayrıntı #63 TESLİM) tam dolumdan
          sonra stop bacağının `held` kaldığını ve `status=open` listesinde
          dönmediğini bildiriyor. Doğruysa dolumlu her iptal yarışı günü
          kapatır. Bacakların iç içe (`nested`) okunması ve her turda koruma
          denetimi ayrı tasarım işidir.
        - **Bilinen sınırlar:** (i) önceki seans + okunamayan giriş +
          pozisyon yokken kalan çıkış emri, iptal brokerca doğrulanmışsa
          fark edilmez; emir dolarsa oluşan ters pozisyon o turda günü
          kapatır. (ii) İptali doğrulanmış ama kalıcı olarak okunamayan
          giriş yeni girişleri süresiz engeller; çıkışı elle journal
          düzeltmesidir. (iii) İptal deneme sayacı süreç belleğindedir:
          giriş okunamazken süreç sınır dolmadan yeniden başlarsa sayaç
          sıfırlanır; bayat giriş o sürede canlı kalır, dolarsa koruması
          ölçülür. (iv) İptali doğrulanmamış ve kalıcı olarak okunamayan
          giriş her seansı sınır dolunca kapatır; çıkışı yine elle journal
          düzeltmesidir. (iii) ve (iv) için kalıcı çözüm, sınırı journal
          zaman damgasından türetmek ve her turda pozisyon korumasını
          girişten bağımsız denetlemektir; ayrı tasarım işi.
      - Kalan iş, "günde tek koşu" kapısı. Paper workflow'uyla birlikte
        gelir.
- **Başlangıç yetkisi:** Codex SHA bağlı ONAY + kullanıcı onayı + kayıtlı
  yürütme kararı (kesin commit, main CI, yöntem, tarih aralığı). Gölge
  (d) deseniyle aynı.
- **Durdurma:** ardışık iki günde sistematik hata (emir reddi, mutabakat
  uyuşmazlığı, journal yazılamadı) → #17 kararıyla durdurma; iptal edilen
  dönemin günleri kayıtta kalır.
- **İlk paper günleri (emir yaşam döngüsü kabulü):** ilk 5 seans tek
  sembol ve en küçük miktarla; her gün kontrol edilen: emir gönderildi mi,
  bracket bacakları borsada mı, dolum journal'a yazıldı mı, mutabakat
  broker ile uyuştu mu, kapanış/kill-switch çalıştı mı. Bunlar gölge
  sonucundan bağımsız, ayrı kabul ölçütleridir.
- **Gerçek para:** bu belgenin kapsamı dışında; ayrı belge, ayrı karar.

## 5. Ölçüm ve öğrenme

- Paper journal'ı gece analizinin girdisidir (`learning/evidence`,
  `promotion`); **otomatik terfi yok** (AGENTS §3.9, §3.11).
- Paper sonuçlarının sınırı (README "Beklentiler üzerine dürüst not"):
  dolumlar iyimser; canlıya 1:1 taşınmaz. Rapor bunu her seferinde söyler.
- Kullanıcıya rapor: gölge rapor aracı deseniyle (`scripts/`), sayılar
  journal'dan, yorum yok, fiyat ve hesap değeri yok; "kaç işlem, kaç
  veto, R dağılımı, hata sayısı".

## 6. Sıra

1. Gölge kampanyası biter, toplam doğrulanır, rapor kullanıcıya gider.
2. Bölüm 1 ölçütleri #17'de değerlendirilir (Codex + Claude; kullanıcı
   onayı).
3. Olumluysa: yürütme ortamı kararı (bölüm 3), kod değişiklikleri ayrı
   PR'larla (Aralık), yürütme kararı (bölüm 4).
4. Olumsuzsa: sonraki seçenek ayrı kararla.
