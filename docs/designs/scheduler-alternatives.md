# Gölge gözlemi için zamanında başlatma: Actions cron'una iki alternatif

Durum: **tasarım kararı A** (Codex #17/6196548874; kabul ölçütleri
#17/6197450956); ÖN RAPOR #17/6195400764; Codex kararı #54/6195334623
madde 3. Kanıt: #54 BULGU 6194455435 ve #17/6201038037 (15 Ekim'de iki
cron 4 saatten fazla geç tetiklendi; koşular saniyesinde başladı, yani
gecikme cron'da, runner kuyruğunda değil). Bu belge hizmet satın alma,
hesap açma, PAT üretme, dağıtım ya da tetik **izni değildir**. Mevcut
hizmette saatinde başlama ölçülmeden "sorun çözüldü" denmez.

## Sorun

GitHub `schedule` 15 Ekim'de iki cron'u 4 saat 33 dk ve 4 saat 3 dk geç
tetikledi (koşular `38776981653`, `38781115701`; `run_started_at ==
created_at`); deponun tek diğer cron'u son dört çalışmasında 6,5–9 saat
gecikti. Tasarım §5 başlangıç penceresi `[açılış − 60 dk, açılış − 1
dk]`; geç başlayan iş açılışı gözleyemez. Gereken: işin **her planlı gün
pencere içinde, kullanıcı müdahalesi olmadan, tek kez** başlaması.

## Ortak ölçütler (Codex 6195334623)

| Ölçüt | Soru |
|---|---|
| Kimlik bilgisi | Hangi gizli bilgi nerede durur, kim üretir, ne zaman döner? |
| Bakım sahibi | Bozulunca kim, nasıl fark eder ve düzeltir? |
| Teklik | Aynı gün iki tetik gelirse ne olur? |
| Son başlama saati | Hangi andan sonra "gün eksik"? |
| Çalışmama alarmı | Tetikleyici ya da iş hiç çalışmazsa nasıl görünür? |
| Maliyet | Aylık tutar ve kimin ödediği |
| Kanıt zinciri | §6 toplama işi gün özetini Actions API'siyle doğruluyor; bozuluyor mu? |

## A. Actions dışı otomatik başlatıcı + mevcut Actions işi (seçildi)

**Mekanizma.** `shadow-observation.yml`'e girdisiz `workflow_dispatch`
eklenir (PR-1); kapı işi aynen kalır (planlı gün, pencere, koşu
geçmişiyle teklik). Dışarıdaki bir zamanlayıcı her hafta içi açılıştan
40 dk önce `POST
/repos/{owner}/{repo}/actions/workflows/shadow-observation.yml/dispatches`
(`{"ref":"main"}`) çağırır. Cron satırları **kalır**: iki yol birbirini
engellemez, kapı ikincisini "gün zaten kaydedildi" ile boş geçirir.

**Zamanlayıcı adayları** (hepsi kullanıcının bir hesap açmasını ister):

| Aday | Zamanlama | Maliyet | Not |
|---|---|---|---|
| Cloudflare Workers Cron Trigger (öneri) | cron çözünürlüğü dakika; UTC; zamanında yürütme garantisi değil | ücretsiz katman (sınırlı kapasite; uygunluk provada) | Worker tek dosya; secret deposu var |
| GitHub dışı cron servisi (ör. cron-job.org) | dakika | ücretsiz katman | PAT'ı üçüncü tarafa emanet etmek daha zayıf |
| Küçük VPS cron | sunucu kadar güvenilir | ~$5/ay | bakım yükü; B ile birleşir |

**Kimlik bilgisi — kapsamın gerçeği (Codex 6196548874).** İnce taneli
GitHub PAT: yalnız bu depo, izin `Actions: write`. Bu izin **yalnız
"workflow başlat" değildir**: aynı depoda Actions'ın bütün yazma uç
noktalarını kapsar (dispatch; koşu iptali, yeniden koşturma ve silme;
artefakt ve log silme). Kod, secret ve depo ayarlarını değiştiremez
(bunlar `Contents`, `Secrets`, `Administration` izinleridir). Kaynak:
<https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens>.
Sonuçları: Worker'da depo, workflow ve `ref=main` sabittir; genel HTTP
dispatch uç noktası yoktur (yalnız cron tetikler); token ve yanıt
gövdeleri log'a yazılmaz. Kullanıcı üretir, zamanlayıcının secret
deposuna koyar, repoya girmez. Ömür 90 gün; bitiş tarihi son toplam
doğrulamasını da kapsamalı (aşağıda). Dönüş sorumluluğu kullanıcıda;
bitiş tarihi #17'ye yazılır, günlük kontrol görevi 14 gün kala hatırlatır.

**Teklik.** Üç katman, hiçbiri tek başına kanıt değil:
1. Başlatıcı, dispatch'ten önce o seans gününün koşu listesini okur;
   koşu varsa dispatch etmez (aynı gün ikinci dispatch, zaman aşımı
   sonrası tekrar ve geç cron için).
2. Kapı koşu geçmişine bakar (tasarım §5): aynı seans tarihinde kayıt
   işi atlanmamış bir koşu varsa durur. Tetik türüne bakmaz.
3. `concurrency` aynı anda iki koşuyu önler; en fazla **bir** bekleyen
   koşu tutar, üçüncü tetik bekleyeni iptal eder ve iptal edilen koşu
   durum tablosuna göre günü kapatır (gevşetilmez). Bu yüzden başlatıcı
   günde en fazla bir kez dispatch eder.

**Son başlama saati.** Değişmez: `açılış − 1 dk`. Başlatıcı yalnız
pencere içinde (`[açılış − 60 dk, açılış − 1 dk]`) dispatch eder;
pencere dışında (erken ya da geç uyanış) hiç dispatch etmez ve sabit
satır yazar. Geç uyanan Worker `scheduledTime`'a değil **gerçek saate**
bakar. Geç kayıt rolü GitHub'ın kendi (geç) cron'unda kalır: o gün hiç
koşu yoksa gün "bilinmiyor (koşu kaydı yok)" olarak toplama girer; bu
saklanmaz.

**Çalışmama alarmı.** 16:40 NY kontrolü gün sonu denetimidir, erken
alarm değildir. Erken alarm: Claude Code zamanlı görevi her hafta içi
**09:05 America/New_York** (açılıştan 25 dk önce, dispatch'ten 15 dk
sonra) o günün `shadow-observation` koşu listesini okur. Planlı günde
koşu yoksa #17'ye **BULGU** yazar: "koşu yok; manuel yedek: Actions →
Shadow observation → Run workflow (main), en geç 09:20 NY". Alıcı ve
kanal: kullanıcının #17 için GitHub bildirimi (e-posta/mobil, kullanıcının
GitHub bildirim ayarına bağlı; kurulum provasında doğrulanır; yeni bir
mesaj kanalı kurulmuş sayılmaz). Planlı olmayan günde ve koşu varken
sessizdir; ilk çalışmasında bir kez "erken kontrol çalıştı" kaydı yazar
(mekanizma kanıtı). Görev çalışmazsa Codex ya da kullanıcı aynı bilgiyi
Actions sayfasından okur. Worker'ın kendi hatası (dispatch 204 dönmedi)
Worker log'unda görünür; log saklama süresi kısa olduğundan prova günü
#17'ye kopyalanır.

**Bakım sahibi.** Worker kodu bu depoda (`infra/shadow-starter/`,
PR-2) Codex incelemesiyle; dağıtım kullanıcının Cloudflare hesabından
(ayrı adım). PAT dönüşü kullanıcıda; hatırlatma günlük kontrol görevinde.

**Kanıt zinciri.** Bozulmaz: gözlem yine Actions'ta, gün özeti yine
artefakt, `run_id/run_attempt/code_sha` yine API ile doğrulanır. Fark:
`event` artık `{schedule, workflow_dispatch}` allowlist'i
(`OBSERVATION_EVENTS`, PR-1); dal `main`, yol, `run_attempt = 1`, kod
SHA ve kampanya bağı aynen. **204 dispatch kabulü gözlemin başladığı
anlamına gelmez**; kanıtlar ayrı sütunlardır:

| Kanıt | Kaynak |
|---|---|
| planlanan an (cron satırı) | Worker log satırı (`scheduledTime`) |
| gerçek Worker başlangıcı | Worker log satırı (`Date.now()`) |
| dispatch HTTP sonucu (durum kodu; gövde yok) | Worker log satırı |
| koşu oluştu (`run_id`, `created_at`, `event`) | Actions API, günlük kontrol |
| kapı başlangıcı ve kararı | Actions API iş/adım kaydı |
| kayıt başlangıcı ve sonucu (gözlem / geç kayıt / atlandı) | Actions API iş/adım kaydı |

**Kod değişikliği.** PR-1: `workflow_dispatch` + event allowlist +
testler; parmak izi değişir → (d) kimliği #54'te yeniden hesaplanır.
PR-2: Worker kodu, kurulum belgesi, Node testleri.

**Risk.** Dispatch koşusu da runner kuyruğuna girer; bugüne kadarki 11
`workflow_dispatch` koşusu ve 15 Ekim'in iki geç cron koşusu saniyesinde
başladı (`run_started_at == created_at`), ama bu garanti değil; prova
ve kampanya boyunca ölçülür. Tek başarılı provadan güvenilirlik garantisi
çıkarılmaz.

## A'nın somut tasarımı: başlatıcı (PR-2)

- **Tetik.** İki UTC cron satırı, GitHub'dakilerle aynı: `50 12 * * 1-5`
  ve `50 13 * * 1-5` (yaz/kış). Cloudflare cron UTC çalışır; cron
  değişikliklerinin yayılması 15 dk sürebilir. Kaynak:
  <https://developers.cloudflare.com/workers/configuration/cron-triggers/>.
- **Pencere.** Worker gerçek saatten New York seans gününü ve açılışı
  (09:30 America/New_York, `Intl` saat dilimi kuralıyla) hesaplar; yalnız
  `[açılış − 60 dk, açılış − 1 dk]` içinde çalışır. Mevsim dışı satır
  "pencere dışı" der ve hiçbir istek yapmaz. Planlı gün listesi
  Worker'da **yoktur** (tek doğruluk kaynağı kod): plan dışı hafta içi
  günde dispatch gider, kapı "plan dışı" der, kayıt atlanır; secret'lı
  gözlem çalışmaz. Böyle bir prova gerçek piyasa gözleminin kanıtı
  sayılmaz.
- **Teklik ön kontrolü.** `GET .../workflows/shadow-observation.yml/runs?created=>=<gün−1>`
  (tek sayfa); seans günü bugün olan koşu varsa dispatch yok, sabit satır.
  Liste okunamazsa dispatch **yok** (fail-closed; gün erken alarma düşer).
- **Dispatch.** `POST .../dispatches` gövde `{"ref":"main"}`; sabit
  `Authorization: Bearer <secret>`, `User-Agent`, `X-GitHub-Api-Version`.
  Beklenen 204.
- **Hata politikası.** 401/403/404: tekrar yok, sabit neden satırı
  (token/izin/yol sorunu; alarm erken kontrolde görünür). 429/5xx/ağ
  zaman aşımı: en fazla 3 deneme, 30 sn aralıkla; `Retry-After` varsa
  uyulur ama pencerenin son dakikasını aşan deneme yapılmaz. Her
  denemeden önce teklik ön kontrolü yinelenir (zaman aşımına uğrayan
  istek koşuyu oluşturmuş olabilir). Yanıt gövdesi ve token hiçbir log
  satırına girmez.
- **Yüzey.** Yalnız `scheduled` işleyicisi; `fetch` işleyicisi her
  isteğe 404 döner (genel HTTP tetik uç noktası yok). Ortam: tek secret
  `GITHUB_TOKEN`; depo/workflow/ref kodda sabit.
- **Log satırı.** Tek satır JSON: `scheduled`, `started`, `window`
  (`icinde`/`disinda`), `existing_run` (varsa kimlik), `attempts`,
  `status` (HTTP kodu ya da `timeout`), `result`. Fiyat, hesap, token,
  gövde yok. Ücretsiz planda log saklama kısadır (belgede: günlük olay
  sınırı ve birkaç gün); prova günü satır #17'ye kopyalanır.
- **Cloudflare sınırları.** Ücretsiz plan: istek/gün ve çağrı başına
  CPU süresi sınırlı; Worker iki kısa `fetch` yapar, CPU süresi G/Ç'yi
  saymaz. Worker başına cron tetik sayısı sınırlı (bize iki satır). Bu
  küçük başlatıcı için uygunluk kurulum provasında doğrulanır; kaynak
  <https://developers.cloudflare.com/workers/platform/limits/>.
- **Testler (Node, `node --test`).** Saf karar fonksiyonu: pencere
  hesabı (yaz/kış, DST geçiş haftaları), teklik ön kontrolü, hata
  sınıfları, deneme sınırı ve son dakika kuralı; sahte `fetch` ile token
  ve gövdenin log'a girmediği. CI'da Python `quality` işi değişmez; Node
  testleri ayrı iş olarak eklenirse Codex kararıyla.

**Kurulum adımları (kullanıcıya paket hazır olunca tek liste; şimdi
istenmiyor):** (1) ücretsiz Cloudflare hesabı; (2) ince taneli PAT:
yalnız `trading-lab`, `Actions: write`, 90 gün — bitiş en az 15 Aralık
2026'yı (son toplam doğrulaması) kapsamalı; (3) Worker'ı dağıtma
(`wrangler deploy` ya da panodan yapıştırma) ve secret olarak PAT;
(4) plan dışı bir hafta içi gününde prova; (5) PAT bitiş tarihini #17'ye
yazma. PAT ne sohbete, ne koda, ne GitHub'a yazılır.

**Prova sonucu (Codex 6197450956):** beklenen zaman, gerçek Worker
zamanı, dispatch HTTP sonucu, `run_id`, kapı başlangıcı ve kararı,
kayıt sonucu — altı sütun #17'ye. Tek başarılı prova güvenilirlik
garantisi değildir; kampanya boyunca her gün aynı sütunlar günlük
kontrol görevinde.

## B. Yönetilen sürekli süreç (seçilmedi; yedek)

**Mekanizma.** Küçük bir konteyner/VM (Fly.io, Railway, Hetzner vb.)
sürekli çalışır; içindeki zamanlayıcı her planlı gün 13:50Z'de
`tlab.shadow_job observe`'ü çalıştırır.

**Kimlik bilgisi.** Alpaca paper anahtarları hizmetin secret deposuna
taşınır (ikinci kopya); GitHub'a kayıt için ayrıca PAT. İki yerde secret.

**Teklik.** Yerel kilit + gün dosyası; Actions koşu geçmişi yok.

**Son başlama saati.** Aynı kural, kodda.

**Çalışmama alarmı.** Hizmetin sağlık kontrolü + günlük Claude kontrolü;
kontrol artık Actions API'sini değil hizmetin çıktısını okumalı.

**Kanıt zinciri.** **Bozulur:** §6 toplama işi gün özetlerini Actions
koşularından indirip `run_id/code_sha`'yı API ile doğruluyor. B'de gün
özetleri hizmetten GitHub'a taşınmalı (artefakt yüklemek için bir
workflow'u dispatch etmek ya da bir dala commit etmek); kaynak doğrulaması
yeniden tasarlanır. Kampanya tasarımının (e) bölümü yeniden açılır.

**Maliyet ve bakım.** ~$5–7/ay; dağıtım, güncelleme, secret dönüşü ve
izleme sahibi gerekir; kullanıcı kod işletmez ama hesap/ödeme onun.

**Kod değişikliği.** Konteyner tanımı, zamanlayıcı, gün özeti taşıma,
toplama sözleşmesi, testler. Büyük.

## Karşılaştırma ve karar

| | A | B |
|---|---|---|
| Kanıt zinciri | korunur | yeniden tasarım |
| Kod değişikliği | küçük (`workflow_dispatch` + event allowlist) + Worker | büyük |
| Yeni secret | 1 PAT (`Actions: write`; dispatch'ten geniş, yukarıda) | Alpaca anahtarları ikinci yerde + PAT |
| Runner kuyruğu riski | kalır, ölçülür | yok (kendi süreci) |
| Maliyet | 0 (Workers ücretsiz katman; uygunluk provada) | ~$5–7/ay |
| Kullanıcı eylemi | hesap + PAT + bir dağıtım | hesap + ödeme + dağıtım |

**Karar (Codex 6196548874):** A, düzeltmelerle; B yalnız A'nın dispatch
koşuları da kuyrukta pencereyi kaçırırsa. Hesap, PAT ve dağıtım ayrı
kullanıcı adımıdır; bu belge izin vermez.

## Sıra

1. 16–23 Ekim zamanlama ölçümü (cron) sürer; 15 Ekim kaydı #17'de.
2. PR-1: `workflow_dispatch` + event allowlist + testler + tasarım
   §5/§6 (ÖN RAPOR #17/6201038037).
3. PR-2: Worker kodu, Node testleri, kurulum belgesi; erken alarm
   görevi (09:05 NY) kurulur ve ilk çalışması #17'ye yazılır.
4. (d) kimliği #54'te yeniden hesaplanır (parmak izi değişti).
5. Kurulum adımları kullanıcıya tek liste; prova plan dışı bir günde,
   ayrı #17 kararıyla; altı sütun #17'ye.
