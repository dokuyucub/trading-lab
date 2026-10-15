# Gölge gözlemi için zamanında başlatma: Actions cron'una iki alternatif

Durum: **taslak, karar değil**; Codex kararı #54/6195334623 madde 3; ÖN RAPOR #17/6195400764. Kanıt: #54 BULGU 6194455435 (15 Ekim cron koşuları oluşmadı; CI kanaryası 6,5–9 saat gecikmeli). Yalnız belge: hizmet
satın alma, kurulum, kimlik bilgisi üretme ya da tetik **yok**.

## Sorun

GitHub `schedule` 15 Ekim'de iki cron için hiç koşu üretmedi; deponun tek
diğer cron'u son dört çalışmasında 6,5–9 saat gecikti. Tasarım §5 başlangıç
penceresi `[açılış − 60 dk, açılış − 1 dk]`; geç başlayan iş açılışı
gözleyemez. Gereken: işin **her planlı gün pencere içinde, kullanıcı
müdahalesi olmadan, tek kez** başlaması.

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

## A. Actions dışı otomatik başlatıcı + mevcut Actions işi

**Mekanizma.** `shadow-observation.yml`'e `workflow_dispatch` eklenir;
kapı işi aynen kalır (planlı gün, pencere, koşu geçmişiyle teklik).
Dışarıdaki bir zamanlayıcı her hafta içi açılıştan ~40 dk önce (kışın
13:50Z) `POST /repos/{owner}/{repo}/actions/workflows/shadow-observation.yml/dispatches`
çağırır. Cron satırları **kalır**: iki yol birbirini engellemez, kapı
ikincisini "gün zaten kaydedildi" ile boş geçirir.

**Zamanlayıcı adayları** (hepsi kullanıcının bir hesap açmasını ister;
seçim ayrı karar):

| Aday | Zamanlama güvenilirliği | Maliyet | Not |
|---|---|---|---|
| Cloudflare Workers Cron Trigger | dakika hassasiyeti, belgelenmiş | ücretsiz katman yeterli | Worker 10 satır; secret deposu var |
| GitHub dışı cron servisi (ör. cron-job.org) | dakika hassasiyeti | ücretsiz katman | PAT'ı üçüncü tarafa emanet etmek daha zayıf |
| Küçük VPS cron | sunucu kadar güvenilir | ~$5/ay | bakım yükü; B ile birleşir |

**Kimlik bilgisi.** İnce taneli GitHub PAT: yalnız bu depo, yalnız
`Actions: write` (dispatch için gereken izin), 90 gün ömür; kullanıcı
üretir, zamanlayıcının secret deposuna koyar, repoya girmez. PAT yalnız
"workflow başlat" yetkisi verir; kod, secret ya da ayar değiştiremez.
Dönüş takvimi #17'ye yazılır.

**Teklik.** Kapı koşu geçmişine bakar (tasarım §5): aynı seans tarihinde
kayıt işi atlanmamış bir koşu varsa durur. Zamanlayıcı iki kez tetiklese
ya da cron da gelse ikinci koşu boş geçer. `concurrency` grubu aynı anda
iki koşuyu önler.

**Son başlama saati.** Değişmez: `açılış − 1 dk` geçildiyse kayıt işi
"eksik (geç başlangıç)" yazar. Dispatch açılıştan 40 dk önce; runner
kuyruğu için 39 dk pay. Kuyruk gecikmesi garanti edilmez (Codex); ölçülür.

**Çalışmama alarmı.** (i) Günlük Claude kontrolü (16:40 NY) "hiç koşu yok"
→ BULGU; (ii) zamanlayıcının kendi hata log'u (Worker log'u; dispatch 204
dönmezse); (iii) isteğe bağlı: Worker, tetikten 15 dk sonra koşu
listesini okuyup koşu yoksa #17'ye yorum yazar — bu `issues: write`
ister, PAT kapsamını büyütür; önermiyorum.

**Bakım sahibi.** Worker kodu bu depoda PR ile (`scripts/` ya da
`infra/`), Codex incelemesiyle; dağıtım kullanıcının hesabından tek
tıklama ya da CLI (ayrı karar). PAT dönüşü kullanıcıda; hatırlatma günlük
kontrol görevinde.

**Kanıt zinciri.** Bozulmaz: gözlem yine Actions'ta, gün özeti yine
artefakt, `run_id/run_attempt/code_sha` yine API ile doğrulanır. Tek fark
`event: workflow_dispatch`; toplama işi `event`'i kısıtlıyorsa sözleşme
güncellenir (test).

**Kod değişikliği.** `on: workflow_dispatch` (girdisiz) + varsa event
kısıtı. Parmak izi değişir → (d) kimliği yeniden hesaplanır (#54 güncellenir).

**Risk.** Dispatch edilen koşu da runner kuyruğuna girer; 15 Ekim'deki
"hiç koşu oluşmadı" durumu cron zamanlayıcısına özgü görünüyor (dispatch
koşuları bugüne kadar saniyeler içinde oluştu: 9 `workflow_dispatch`
koşusu), ama bu kanıt değil; 16–23 Ekim ölçümü ve ilk dispatch
provaları (ayrı karar) gerekir.

## B. Yönetilen sürekli süreç

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

## Karşılaştırma ve öneri

| | A | B |
|---|---|---|
| Kanıt zinciri | korunur | yeniden tasarım |
| Kod değişikliği | küçük (`workflow_dispatch` + event sözleşmesi) | büyük |
| Yeni secret | 1 PAT (yalnız dispatch) | Alpaca anahtarları ikinci yerde + PAT |
| Runner kuyruğu riski | kalır, ölçülür | yok (kendi süreci) |
| Maliyet | 0 (Workers ücretsiz katman) | ~$5–7/ay |
| Kullanıcı eylemi | hesap + PAT + bir dağıtım tıklaması | hesap + ödeme + dağıtım |

**Öneri:** A, Cloudflare Workers Cron Trigger ile; B yalnız A'nın
dispatch koşuları da kuyrukta pencereyi kaçırırsa. İkisi de #17 kararı ve
kullanıcı onayı ister; bu belge izin vermez.

## Sıra

1. 16–23 Ekim zamanlama ölçümü (cron) sürer.
2. Codex: A/B üzerine görüş; kullanıcı: A için hesap ve PAT kararı.
3. Karar A ise: PR-1 `workflow_dispatch` + toplama sözleşmesi + testler;
   PR-2 Worker kodu ve kurulum belgesi; (d) kimliği yeniden hesaplanır.
4. Dispatch provası (plan dışı günde kapı "plan disi gun" demeli; zamanlama
   ölçülür) ayrı #17 kararıyla, kullanıcı tıklamasıyla.
