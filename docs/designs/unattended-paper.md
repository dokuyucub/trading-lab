# Gözetimsiz paper kabulü ve yürütme ortamı (gölge sonrası faz)

Durum: **taslak, karar değil**; ÖN RAPOR #17/6182224516, Codex görüşü 6182905717 işlendi. Bu belge **kod değiştirmez ve hiçbir
yetki vermez**: emir, tetik, holdout, ücretli abonelik ya da canlı para bu
belgenin kapsamı dışındadır. Gölge gözlem kampanyası (tasarım
`shadow-observation.md`, kimlik `4a096c7e…`) bitip toplam doğrulanmadan
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
  tutma" fırsatıdır. Bu bir **strateji davranışı değişikliği** değildir;
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
  bir daha açma" kararı job içinde yaşar; Actions'ta kalıcı değildir — A
  seçeneğinde zaten gün tek job'dır.
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
