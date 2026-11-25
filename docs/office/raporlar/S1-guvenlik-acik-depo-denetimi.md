# S1 — Güvenlik: açık depo denetimi

Tarih: 2026-11-25. Birim: Güvenlik. Kapsam: `main` 47a2a7d (salt okunur kopya).
Yöntem: 10 iş akışı, `infra/shadow-starter`, sır hijyeni, log/istisna yolları,
tedarik zinciri satır satır okundu; çalışma ağacı ve git geçmişi kimlik bilgisi
biçimleri için tarandı (yalnız dosya/commit/satır basılarak). Depoya kod
yazılmadı, iş akışı tetiklenmedi, GitHub/Alpaca/Cloudflare API'si çağrılmadı.

## 1. Sonuç

1. **Açığa çıkmış kimlik bilgisi: HAYIR.** 177 izlenen dosyada ve erişilebilir
   183 commit'te (bütün ref'ler) Alpaca anahtarı, GitHub PAT, Cloudflare token,
   özel anahtar, imzalı URL yok; eşleşen 13 değerin hepsi test sahtesi.
2. Çatal (fork) PR'dan Alpaca secret'larına giden yol **yok**: secret'lı yedi iş
   akışı yalnız `workflow_dispatch`/`schedule`, `pull_request_target` hiç yok.
3. En ciddi risk kimlik bilgisi değil, **kampanya bütünlüğü**: teklik kapısı
   gizli depo varsayımıyla yazılmış; yabancı bir çatal PR planlı günü yakabilir (Y1).
4. İkinci risk: `main` korumasız ve secret'lar dala bağlı değil; yazma yetkili
   herhangi bir kimlik (ajan token'ı dahil) anahtarları dışarı çıkarabilir (Y2).
5. Sayım: **Kritik 0, Yüksek 2, Orta 3, Düşük 11.** Y1 ve Y2'nin ilk adımları
   yalnız depo ayarıdır; dondurmaya takılmaz, bugün yapılabilir.

**Doğrulanmadı:** (a) klon sığ: sınır commit'leri 2026-09-20..26 (abade7f,
6c743aa, 083cfbd, 737d6e2, 7569559); öncesindeki geçmiş taranamadı; (b) depo
ayarları, Actions logları/artefaktları, issue/PR yorumları, silinmiş dallar ve
çatallar okunmadı; (c) Cloudflare'de dağıtılan kodun depodakiyle aynılığı.

## 2. Bulgular

### Yüksek

**Y1 — Teklik kapısı ve dış başlatıcı, çatal PR koşusunu "günün koşusu" sayıyor**
- **Yer:** `src/tlab/shadow_job.py:311-314` (koşu listesi olay/dal/depo süzgeci
  olmadan), `:334-339` (kayıt işi yoksa `recorded=True`),
  `src/tlab/shadow/schedule.py:72-73`; `infra/shadow-starter/worker.js:105-121`,
  `:142-146`, `:289`. Toplam tarafı: `shadow_job.py:1528-1581` (`total` işi
  olmayan önceki koşu engel), `:1606-1615` (artefakt adı depo genelinde aranır),
  `:1048-1064` + `:343-350` (100 koşuluk tek sayfa aşılırsa hata).
- **Senaryo:** GitHub hesabı olan herkes depoyu çatallar, kendi kopyasında
  `shadow-observation.yml`'e `pull_request` tetiği ekler ve planlı günün sabahı
  (New York gece yarısı ile 12:50 UTC arası) PR açar. GitHub koşuyu aynı iş
  akışı yolu altında kaydeder; onay bekleyen koşunun iş listesi boştur. Kapı
  bunu "kayıt işi yok: sayılır" kuralıyla sayar ve `atla (gun zaten
  kaydedildi)` der; Worker `kosu-var` deyip dispatch etmez. Gün geri gelmez;
  tamlık eşiği 0,95 (`shadow/summary.py:63`), yani iki kayıp gün 20 günlük
  kampanyayı düşürür. Yan yollar: (b) koşu onaylanır ya da onay gerekmezse
  aynı `concurrency` grubunu (`shadow-observation.yml:31-33`) saatlerce tutar;
  (c) son günden sonra `shadow-aggregate.yml`'e dokunan PR toplamı "kanıtı
  yok" ile, kampanya önekli artefakt yükleyen PR "daha önce üretildi" ile
  durdurur; (d) ~30 ek koşu tek sayfa sınırını aşırır. (c) ve (d) yabancı
  koşu/artefakt silinince düzelir; (a) düzelmez.
- **Durum:** `DOĞRULANDI` (kod). Sahte API ile yerelde yeniden üretildi:
  `pull_request` olaylı, işsiz bir önceki koşuyla `decide` → `atla`, Worker →
  `kosu-var`; koşu yokken `gozle`. `OLASI` kısım: GitHub'ın çatal PR koşusunu
  aynı iş akışı altında listelemesi (belgelenen davranış; kural gereği denenmedi).
  Gün özeti zehirlenemez: `_download_days` olay ve kaynak süzer (`:1646-1654`).
- **Öneri (şimdi, ayar):** Settings → Moderation → Interaction limits →
  "Limit to repository collaborators", toplam doğrulanana kadar. Kalan planlı
  günlerde (30 Kasım, 1 Aralık) 12:50 UTC'den önce "Shadow observation"
  altında `schedule`/`workflow_dispatch` dışı koşu varsa sahibi siler.
- **Öneri (kalıcı):** kapı, kanıt ve toplam adımlarında tek ortak süzgeç:
  `event ∈ OBSERVATION_EVENTS`, `head_branch == main`,
  `head_repository.full_name == GITHUB_REPOSITORY`; Worker'da aynısı; artefakt
  adı yalnız kendi iş akışımızın koşularında aranır.
- **Dondurma / boyut:** kalıcı düzeltme `src/tlab/**`'e dokunur (parmak izine
  girer) → 2 Aralık sonrası; `worker.js` dondurulmuş değil ama tek başına
  yetmez. **M**.

**Y2 — `main` korumasız; secret'lar dala bağlı değil**
- **Yer:** `AGENTS.md:89-92` ("`main` teknik olarak korumasız", kayıt
  2026-09-27). Secret'lı işlerde tek engel bir `if` satırı:
  `alpaca-paper-check.yml:11`, `alpaca-sdk-check.yml:21`,
  `alpaca-pilot-quality.yml:20`, `alpaca-baseline-measure.yml:21`,
  `alpaca-baseline-feed-comparison.yml:23`,
  `alpaca-baseline-quality-diagnostic.yml:23`, `shadow-observation.yml:37`.
- **Senaryo:** `workflow_dispatch` seçilen daldaki iş akışı dosyasını koşar ve
  depo secret'ları her dala verilir. Yazma yetkili bir kimlik (1) bir dalda
  `if` satırını silip anahtarı dışarı gönderen adım ekler ve o dalı tetikler;
  ya da (2) `main`'e doğrudan push eder, ertesi sabahki zamanlanmış gözlem
  değiştirilmiş kodu anahtarlarla koşar. Mimari testler bunu durdurmaz: yalnız
  PR'da koşarlar. Depo açık olduğu için ajanlar yabancıların yazdığı PR/issue
  metnini okuyor (`CLAUDE.md` açık PR'ları kontrol etmeyi söyler); bu, yazma
  yetkili ajan token'ları için bir yönlendirme (prompt injection) yüzeyidir.
  `docs/github-paper-check.md:28` ("başka dalda seçilirse iş atlanır") yalnız
  kazaya karşı doğrudur.
- **Durum:** `DOĞRULANDI` (kodda başka engel yok). `main`'in bugünkü koruma
  durumu `OLASI`: ayar okunamadı.
- **Öneri:** (şimdi, ayar) `main` için ruleset: PR zorunlu, `quality` zorunlu
  durum denetimi, Code Owners incelemesi, force-push ve silme kapalı, bypass
  yok. (sonra) Alpaca secret'larını `paper` adlı Environment'a taşı: dağıtım
  dalı yalnız `main`, zorunlu onaylayıcı depo sahibi; yedi işe
  `environment: paper`. Canlı anahtar bu yapılmadan GitHub'a girmemeli.
- **Dondurma / boyut:** ruleset dondurmaya dokunmaz, **S**. Environment geçişi
  `shadow-observation.yml`'i değiştirir ve depo düzeyindeki secret'lar o
  zamana kadar kalmak zorunda → 2 Aralık sonrası, **M**.

### Orta

**O1 — Kilitler hash'siz; secret'lı işlerde `--require-hashes` yok**
- **Yer:** `requirements.lock:1-58`, `requirements-dev.lock`; kurulum
  satırları `shadow-observation.yml:54,83`, `alpaca-sdk-check.yml:51`,
  `alpaca-pilot-quality.yml:34`, `alpaca-baseline-measure.yml:38`,
  `alpaca-baseline-feed-comparison.yml:37`,
  `alpaca-baseline-quality-diagnostic.yml:35`.
- **Senaryo:** sürüm sabit ama dosya sabit değil. Bakımcı hesabı ele
  geçirilirse sabitlenmiş sürüme yeni bir wheel eklenebilir; pip onu kurar ve
  kod Alpaca anahtarlarının bulunduğu işte çalışır. "Secret'lar yalnızca bu
  adımda" adım düzeyinde bir düzen kuralıdır, güvenlik sınırı değil: aynı
  işteki kötü niyetli kod runner belleğinden işin bütün secret'larını okuyabilir.
  Gerçek sınır iş düzeyidir (kapı/kayıt ayrımı doğru).
- **Durum:** `DOĞRULANDI` (hash yok); istismar `OLASI`.
- **Öneri:** `uv pip compile --generate-hashes`; kurulum
  `pip install --require-hashes --no-deps --only-binary :all: -r requirements.lock`.
- **Dondurma / boyut:** `requirements.lock` ve iki gölge iş akışı dondurulmuş
  → 2 Aralık sonrası. **S**.

**O2 — Action'lar commit SHA ile değil, taşınabilir etiketle sabit**
- **Yer:** `actions/checkout@v7` (14 kullanım), `actions/setup-python@v7`
  (11), `actions/upload-artifact@v7` (7); `tests/test_architecture.py:1625`, `:1508`.
- **Senaryo:** etiket başka commit'e taşınırsa secret'lı işte, secret adımından
  önce yabancı kod çalışır (ör. `PATH`'e sahte `python`). Üçü de GitHub'ın
  kendi action'ı olduğu için olasılık düşük, etki O1 ile aynı.
- **Durum:** `DOĞRULANDI`.
- **Öneri:** `uses: actions/checkout@<40 hane> # v7.0.1`; SHA'lar zaten
  `docs/designs/workflow-actions.md:28-29`'da kayıtlı. Testteki sürüm sabiti
  SHA olur; ardından ayarda "SHA ile sabitleme zorunlu" açılır.
- **Dondurma / boyut:** tek sürüm testi bütün iş akışlarını birlikte ister →
  2 Aralık sonrası. **S**.

**O3 — Anahtar tarayıcı önleyici değil ve kapsamı dar**
- **Yer:** `tests/test_architecture.py:309-333` (yalnız Alpaca biçimleri;
  `ghp_`/`github_pat_` ve Cloudflare token deseni yok, oysa sistemde artık PAT
  var), `:336` (geçmiş taranmaz), `.pre-commit-config.yaml:48-53` (pytest
  kancası yalnız Python dosyası değişince koşar), `:23` (tek hazır kanca
  `detect-private-key`).
- **Senaryo:** anahtar bir `.md`, `.yml`, `.toml` ya da `.js` dosyasına
  yapıştırılıp push edilir. Yerel kanca çalışmaz; CI kırmızı olur ama açık
  depoda push anında anahtar sızmıştır.
- **Durum:** `DOĞRULANDI`.
- **Öneri:** (ayar, şimdi) secret scanning + push protection. (kod)
  pre-commit'e gitleaks ya da her commit'te koşan yerel tarayıcı kancası;
  `TOKEN_PATTERNS`'a GitHub PAT ve Cloudflare desenleri. Bu sıkılaştırmadır.
- **Dondurma / boyut:** dokunmaz. **S**.

### Düşük

| No | Yer | Sorun / senaryo | Durum | Öneri | Dondurma | Boyut |
|---|---|---|---|---|---|---|
| D1 | `infra/shadow-starter/worker.js:185-192` | `fetch` yönlendirmeyi kendisi izler; Python tarafı (`shadow_job.py:246-250`) izlemez. Beklenmeyen bir 3xx'te `Authorization` başka adrese taşınabilir | `OLASI` | `redirect: "manual"`, 3xx → `red` | Hayır | S |
| D2 | `infra/shadow-starter/README.md:55-65`, `:71-72` | PAT `Actions: write`: sızarsa koşu/artefakt/log siler, iş akışlarını `main`'de tetikler; anahtar okuyamaz. Belge bunu doğru anlatıyor. `npx wrangler` sürümsüz | `DOĞRULANDI` | Cloudflare 2FA; kampanya bitince PAT iptal, Worker sil; `npx wrangler@<sürüm>` | Hayır | S |
| D3 | `tests/test_architecture.py:981` | İş akışı listesi yalnız `*.yml`; `.yaml` uzantılı yeni iş akışı izin, tetik ve runner testlerinin dışında kalır | `DOĞRULANDI` | `*.yaml`'ı da tara ya da yasakla | Hayır | S |
| D4 | `.github/workflows/ci.yml:56,102`; `tests/test_architecture.py:1631-1634` | Kilitsiz kanarya ile `quality` aynı pip önbelleğini paylaşır; kötü bir üst akış sürümü önbelleği kirletebilir (etki: CI sonucu, secret yok). Secret'lı işte `cache` yasağı testte yok | `OLASI` | Kanaryadan `cache` kaldır; secret'lı işte `cache` yasağını teste ekle | Hayır | S |
| D5 | `.github/workflows/ci.yml:35,87,123` | Üç işte `timeout-minutes` yok; onaylı çatal PR'lar 6 saatlik işlerle eşzamanlı runner kotasını doldurup gözlemi geciktirebilir | `OLASI` | `timeout-minutes: 15` | Hayır | S |
| D6 | `src/tlab/config.py:43-44,76-79`; `src/tlab/cli.py:77-79` | Anahtarlar düz `str` (`repr`/`model_dump` tam değeri verir); `tlab config` gizli anahtarın ilk 4 + son 2 karakterini ve uzunluğunu basar. Yerel komut; çıktı açık issue'ya yapıştırılırsa kısmi sızıntı | `DOĞRULANDI` | `SecretStr`; maske yalnız "var/yok" ve uzunluk | Evet | S |
| D7 | `src/tlab/baseline_diagnostic.py:299`; `src/tlab/shadow_job.py:371-374` | Yakalanmayan istisna (ör. `IncompleteRead`) açık log'a traceback basar. Anahtar taşımaz; sabit satır sözleşmesini deler | `OLASI` | Her `main()`'de yalnız tip adı basan üst düzey yakalama | Evet | S |
| D8 | `docker/Dockerfile:5`; `docker/docker-compose.yml:3-5` | Taban imaj digest'siz, konteyner root, `.dockerignore` yok (bağlam depo kökü: `.env` ve `data/` daemon'a gider; imaja kopyalanmaz) | `DOĞRULANDI` | `@sha256:` pin, `USER`, `.dockerignore` | Hayır | S |
| D9 | `.github/dependabot.yml:6-16`; `SECURITY.md:25-28` | Dependabot `requirements*.lock` adını tanımayabilir; erişilebilir geçmişte tek `chore(deps)` commit'i yok. Docker ekosistemi tanımsız | `OLASI` | Insights → Dependency graph'tan doğrula; gerekirse yeniden adlandır | Kilit adı değişirse evet | S |
| D10 | `SECURITY.md:5,32`; `ci.yml:8`; `artifact-roundtrip.yml:14`; `AGENTS.md:89-92`; `src/tlab/sdk_probe.py:13-16`; `docs/github-paper-check.md:28` | Bayat belge: "özel depo, issue açma", "anahtarlar yalnızca `.env`'de", "depo gizli", Actions dakika kotası, `private=true`. Açık depoda güvenlik bildirimi için kanal yok | `DOĞRULANDI` | SECURITY.md'yi yeniden yaz (Actions secret'ları, Worker PAT'ı, özel bildirim kanalı); yorumları düzelt | Yalnız `sdk_probe.py` | S |
| D11 | `shadow-observation.yml:109-115` (60 gün); baseline iş akışları (90 gün); `alpaca-pilot-quality.yml:48-63` | Artefaktlar ve iş özeti herkese açık. İçerik sabit alan listeli; mutlak fiyat, hesap değeri, anahtar yok (`shadow/core.py:263-281`). Ama sembol-gün düzeyinde türetilmiş sağlayıcı verisi (IEX−SIP farkı, bps), sinyal dakikaları ve sentetik özsermayeli backtest sonucu yayımlanıyor | `DOĞRULANDI` | Sahibi lisans ve tercih açısından bilerek onaylasın; gerekirse saklama süresini kısalt | Gölge iş akışı evet | S |

Kapsam dışı not (Hata Avı için): `infra/shadow-starter/worker.test.js:418-440`
gerçek saate bağlı. New York 08:30-09:29 arasında koşarsa sonuç `red` olur ve
test düşer (yerelde sabit saatle yeniden üretildi); o saatte açılan PR'da
`starter` işi kırmızı görünür.

## 3. Sağlam bulunanlar

- **Tetikler:** hiçbir iş akışında `pull_request_target`, `workflow_run`,
  `issue_comment` yok; erişilebilir geçmişte de hiç olmamış; test sabitliyor
  (`tests/test_architecture.py:1665-1675`). `pull_request` tetikli iki iş
  akışı (`ci.yml`, `artifact-roundtrip.yml`) secret'sız.
- **Token:** on iş akışında üst düzey `permissions: contents: read`; üç iş
  yalnız `actions: read` ekler; 14 checkout'un hepsinde
  `persist-credentials: false` (test `:1003-1034`).
- **Script enjeksiyonu yok:** hiçbir `run:` bloğunda `${{ github.event.* }}`
  yok; iş akışları girdi almaz; adım çıktıları kabuğa `env` ile geçer.
- **Secret yerleşimi:** yalnız adım `env`'inde, iş/iş akışı düzeyinde değil;
  kapı ayrı ve secret'sız iş; secret'sız adımlar ortamda `ALPACA_`/`APCA_`
  görürse başlamaz (`shadow_job.py:270,866,950,1414`; `baseline_job.py:273-276`).
- **Çıktı disiplini:** veri işlerinin hepsi `job_io.silenced()` altında; hata
  yalnız tipten türetilen sabit sınıfla basılır (`sdk_probe.py:67-110`); yanıt
  gövdesi ve istisna metni basılmaz; sahte sır işaretli testler var
  (`tests/test_sdk_probe.py:214,244`). SDK ve `requests` hata metinleri
  kimlik başlıklarını taşımaz; anahtar URL'de değil başlıkta.
- **Artefakt zinciri:** token'lı istekler yönlendirme izlemez, ZIP adresine
  `Authorization` gitmez, yalnız https, boyut sınırı, tek üyeli ZIP, digest,
  koşu kimliği ve kampanya eşleşmesi (`shadow_job.py:1617-1711,1714-1753`).
- **Problar:** `paper=True` sabit; `base_url` ortamdan okunmaz
  (`sdk_probe.py:210-213`); `paper_probe` yalnız stdlib, yönlendirme izlemez.
- **Worker:** `fetch` her isteğe 404, `workers_dev = false`, rota/değişken/hesap
  kimliği yok; depo, iş akışı ve ref sabit, girdi yok; log tek satır JSON
  (durum kodları), token ve gövde yok (test: `worker.test.js:408-416`);
  okunamayan listede dispatch yok. PAT kapsamı belgede dürüstçe yazılı.
- **Depo hijyeni:** `.gitignore` `.env`, `.env.*`, `/data/`, `/logs/`, `*.db`,
  `*.parquet`'i dışlar; `.env.example` değerleri boş; tarayıcı eşleşen değeri
  asla basmaz (`tests/test_architecture.py:347-360`).
- **Tedarik:** kilitler tam geçişli kapanış ve `==` sabit; `pip check` her
  kurulumda; secret'lı işlerde `cache` ve `pip install -e .` yok; runner
  `ubuntu-24.04` sabit; Docker'da build arg ya da katmanda secret yok.
- **Canlı para:** iki bilinçli adım (`ALPACA_PAPER=false` +
  `--i-understand-live`, `cli.py:275`).

## 4. Depo sahibi için ayar kontrol listesi

Buradan okunamadı; sahibinin elle doğrulaması gerekir.

- [ ] **Ruleset (`main`):** PR zorunlu; `quality` zorunlu; Code Owners
      incelemesi; force-push ve silme kapalı; bypass listesi boş (Y2).
- [ ] **Interaction limits:** toplam doğrulanana kadar "collaborators only" (Y1).
- [ ] **Actions → General → Fork pull request workflows:** "Require approval
      for all external contributors".
- [ ] **Actions → General → Workflow permissions:** varsayılan salt okuma;
      "Allow GitHub Actions to create and approve pull requests" kapalı.
- [ ] **Actions → General → Actions permissions:** yalnız GitHub'ın kendi
      action'ları; O2'den sonra SHA ile sabitleme zorunluluğu.
- [ ] **Code security:** Secret scanning, Push protection (hesap düzeyinde de),
      Dependabot alerts + security updates, Private vulnerability reporting.
- [ ] **Secrets:** depo düzeyinde yalnız iki Alpaca paper secret'ı var mı;
      2 Aralık sonrası `paper` Environment'ına taşı (yalnız `main`, onaylı).
- [ ] **Yazma yetkisi:** collaborator listesi, kurulu GitHub App'ler, deploy
      key'ler, webhook'lar; ajan token'larında `Administration`/`Secrets` yok.
- [ ] **Gizli dönemden kalanlar:** eski Actions logları ve artefaktları artık
      herkese açık; gereksizleri sil (`shadow-day` artefaktlarına dokunma).
      Issue/PR yorumlarında (özellikle #17) yapıştırılmış değer var mı bak.
- [ ] **Tam geçmiş taraması:** sığ olmayan klonda gitleaks ya da GitHub secret
      scanning sonucu (bu denetim 2026-09-20 öncesini göremedi).
- [ ] **Alpaca:** kampanya bitince paper anahtarını yenile; hesapta 2FA;
      canlı anahtar Y2 kapanmadan GitHub'a girmesin.
- [ ] **Cloudflare:** hesapta 2FA; `wrangler secret list` yalnız
      `STARTER_GITHUB_PAT` adını göstersin; dağıtılan kod depodakiyle aynı mı;
      panoda `workers.dev` ve önizleme adresleri kapalı mı; PAT bitiş tarihi
      kayıtlı mı; kampanya sonunda PAT iptal, Worker sil.
- [ ] **GitHub hesabı:** 2FA/passkey; kullanılmayan PAT ve oturumları kapat.
- [ ] **Çatallar:** açık depoda çatal geçmişi geri alınamaz; sızan anahtar
      geçmiş temizlenerek değil, iptal edilerek kapatılır.
