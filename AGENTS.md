# Ekip Sözleşmesi

Bu projede birden fazla geliştirici çalışıyor (insan ve yapay zekâ ajanları).
Bu dosya ortak kuralları tanımlar. **Kod yazmadan önce oku.**

Diğer belgeler: mimari için `README.md`, git akışı ve sürüm geri alma için
`CONTRIBUTING.md`, ne değiştiği için `CHANGELOG.md`.

---

## Çalışma düzeni: önce niyet, sonra iş

2026-09-23'te kullanıcı tarafından belirlendi. **Bu kural diğer her şeyin
üstünde.**

> Her yaptığınız işi birbirinize raporlayacaksınız — bir şey yapmadan önce ve
> yaptıktan sonra. Bütün süreci tüm detaylarıyla konuşup danıştıktan sonra
> yapacaksınız.

Uygulaması:

| Ne zaman | Nereye | Ne yazılır |
|---|---|---|
| **İşe başlamadan önce** | #11 | Ne yapacağım, neden, hangi seçenekleri tarttım, hangisini neden seçtim, karşı tarafa sorum ne |
| **İş bitince** | PR + #11 | Ne yaptım, ne doğruladım, neyi doğrulayamadım, ne açık kaldı |

Ön rapor yazılmadan koda başlanmaz. Bu bir formalite değil; **yaşanmış bir
maliyetin karşılığı.** 2026-09-23'te paper bağlantı kontrolü ilk gerçek
koşusunda düştü ve ikimiz de hatayı aynı anda, birbirimizden habersiz
düzelttik (#15 `737d6e2` ve #16 `2914771`). Aynı iş iki kez yapıldı. Tek bir
satırlık "bunu ben alıyorum" mesajı bunu önlerdi.

Ön rapor **tartışmaya açık bir öneridir**, bildirim değil. Karşı taraf
itiraz ederse tasarım birlikte netleşir. O gün ikimizin çözümü de eksikti;
birleşimi ikisinden de iyi çıktı.

Acil bir durum ön raporu ortadan kaldırmaz, yalnızca kısaltır: "şu koşu
kırık, düzeltmeye başlıyorum" tek satırı yeter.

---

## 0. İş bölümü

2026-09-20'de kararlaştırıldı.

| | ChatGPT | Claude |
|---|---|---|
| **Faz** | 4 — araştırma/bağlam katmanı | 3 — öğrenme katmanı |
| **Kapsam** | Bilanço takvimi, haber/katalizör → yapılandırılmış özellikler; işlem engelleme | Journal analizi, walk-forward, shadow mode, terfi kapısı |
| **Ana dizinler** | `tlab/research/`, `config/` | `tlab/learning/`, `backtest/`, `journal/queries.py` |

**Sorumluluk sınırı:** `research/` veriyi *hazırlar*, işlem engelleme kararını
`risk/` verir. Stratejiye ağ erişimi eklenmez (bkz. 3.3).

### Faz 4 veri sözleşmesi

Haber/bilanço verisi taşıyan her kaydın içermesi gerekenler:

| Alan | Neden |
|---|---|
| Olay zamanı | Olayın gerçekleştiği an |
| Yayımlanma zamanı | Bilginin kamuya açıldığı an |
| **Öğrenme zamanı** | Sistemin bilgiye *eriştiği* an |
| Kaynak | Hangi sağlayıcı |
| Güncellik/revizyon durumu | Kayıt düzeltilmiş mi |

Öğrenme zamanı olmadan, bugünkü bir haberi veya sonradan düzeltilmiş bir
bilanço takvimini geçmişte biliniyormuş gibi backtest'e sokarız. Bu, ileriye
bakmanın en sinsi biçimidir: kod doğrudur, veri yalan söyler.

**"Veri bulunamadı" ile "olay yok" ayrı durumlardır.** İkisini aynı saymak,
sağlayıcı kesintisini "bu hissede earnings yok" diye yorumlamak demektir.

## 1. Kim nereye push eder

| Dal | Kim |
|---|---|
| `main` | Kimse doğrudan push etmez. Sadece PR ile. |
| `claude/*` | Claude |
| `codex/*` (veya benzeri) | Diğer ajan |

**Kural: başka birinin dalına asla push etme.** Bir dal üzerinde iki kişi
çalışırsa, birinin push'u diğerinin çalışmasını görünmez şekilde geride bırakır.

Akış: kendi dalında çalış → `make check` → push → `main`'e PR aç → CI yeşil →
birleştir. PR'lar küçük tutulur; küçük PR hızlı birleşir, hızlı birleşen PR
çakışmaz.

**`main` teknik olarak korumasız** (2026-09-27, API: `private=true`, `main`
`protected=false`; #17). Mevcut planın gizli depoda dal korumasını destekleyip
desteklemediği **doğrulanmadı**: API yalnızca görünürlüğü ve korumanın şu an
kapalı olduğunu gösterir. Yani "PR zorunlu, `quality` zorunlu" kuralını GitHub
**uygulamıyor**; yalnızca biz uyguluyoruz:

- `main`'e doğrudan push yok; her değişiklik PR ile girer.
- Birleştirme için güncel head'de `quality` yeşil **ve** diğer ajanın o
  SHA'ya bağlı `## ONAY — <sha>` kaydı gerekir (§4a). Eski onay yeni koda geçmez.
- CI tetikleyicileri (`main`'e push + filtresiz `pull_request`) ve `quality`
  adımları `tests/test_architecture.py` tarafından sabitlenir; bir PR'ı kapıdan
  kaçıracak filtre eklenirse test kırılır.

Plan/izin uygunluğu doğrulanıp koruma kullanılabilir olduğunda açılır: PR
zorunlu, `quality` zorunlu, yöneticiler dahil.

## 2. Kurulum ve kapılar

İlk kurulum:

```bash
make install-locked   # CI ile AYNI paket sürümleri
make hooks            # pre-commit kancalarını kur
```

Push etmeden önce tek komut:

```bash
make check            # ruff + ruff format + mypy + pytest
```

CI aynısını çalıştırır. Kırık bir commit'in geçmişe girmesi `git bisect`'i işe
yaramaz hale getirir — ve "eskiden çalışıyordu" sorusunun tek hızlı cevabı odur.

**Bağımlılık eklediysen `make lock` çalıştır ve iki kilit dosyasını da commit
et.** Sabitlenmemiş bir kurulum, aynı commit'in iki hafta arayla farklı paket
sürümleriyle kurulması demek. Bu bir kez yaşandı: `numpy` 2.5.3 yayınlandığı gün
CI kodla ilgisi olmayan bir sebeple kırıldı.

| Kilit | Kim kullanır |
|---|---|
| `requirements.lock` | Docker imajı — yalnızca çalışma zamanı |
| `requirements-dev.lock` | CI ve yerel geliştirme |

Test her iki kilidin de `pyproject.toml`'daki **sürüm şartlarını gerçekten
karşıladığını** doğruluyor — ad karşılaştırması yetmez: `pandas>=999` yazıp
kilitte `pandas==3.0.6` bırakmak, yalnızca adlara bakan bir kapıdan geçerdi.
Ayrıca ortak paketlerin iki kilitte aynı sürümde olduğu da denetleniyor.

Kapsama eşiği %80. Amaç oranı yükseltmek değil, gerilemeyi yakalamak: testsiz
eklenen büyük bir modül burada göze çarpar.

## 3. Değişmezler

Aşağıdaki kuralların çoğu `tests/test_architecture.py` tarafından **otomatik
denetleniyor**. Biri kırıldığında test kırmızı olur ve sebebini söyler. Kuralı
kaldırmadan önce neden var olduğunu oku — her biri gerçekten yaşanmış bir
hatanın karşılığı.

### 3.1 Saat her zaman dışarıdan gelir

Karar yolundaki hiçbir kod `datetime.now()` çağırmaz; saati `Clock`'tan alır.
Backtest'te zamanı biz kontrol ediyoruz; duvar saatine bakan kod geçmiş veri
üzerinde "şu an"ı yanlış bilir ve farkında olmadan geleceğe bakar.

*Bu kural bir kez kırıldı:* `JournalWriter` zaman damgalarını `datetime.now()`
ile alıyordu. Canlıda fark edilmiyordu ama backtest kayıtları bugünün tarihini
taşıyordu.

Bağımsız `tlab.paper_probe` bağlantı tanısı karar yoluna dahil değildir.
Yalnızca CLI girişinde `datetime.now(UTC)` kullanır; `run()` zamanı dışarıdan
alır. Bu dar istisna, `tlab.core` paketinin pydantic bağımlılığını tanı
aracına taşımamak içindir. Mimari testi ve `python -S` başlangıç testi
bağımsızlığı denetler. Strateji/risk/engine için saat kuralı değişmez.

Aynı dar istisna `tlab.sdk_probe` için de geçerli. İkisi **farklı sorular**
sorar ve ikisi de gereklidir:

| | `paper_probe` | `sdk_probe` |
|---|---|---|
| Soru | Anahtarlar geçerli mi, ağ açık mı | **Bizim kodumuz** Alpaca ile konuşuyor mu |
| Yol | Elle kurulmuş URL, stdlib | Gerçek `AlpacaBroker` / `AlpacaMarketData` |
| Kurulum | Yok | `requirements.lock` |

Birincisi "bizde mi onlarda mı" sorusunu, kurulum bozuk olsa bile tek başına
cevaplayabilmeli — bu yüzden bağımsızlığı korunur. İkincisi gerçek SDK'yı
çalıştırmak zorunda, çünkü yakalaması gereken hata sınıfı (`TimeFrameUnit`
çevrim hataları gibi) yalnızca orada görünür.

**Her ikisi de hiçbir sayısal hesap değeri basmaz.** `doctor` ve `account`
komutları özsermaye basar ve bu yerel kullanımda doğrudur; genel bir koşuya
taşınamazlar. Depo şu an gizli, ama bu kuralın gerekçesi o değil: depo açıksa
ya da ileride açılırsa **saklanan geçmiş koşu kayıtları** herkese görünür olur
ve bir kez görülmüş bir değer geri alınamaz; kaydı sonradan silmek görenleri geri almaz (#17). Kural görünürlükten bağımsız
uygulanır. Bu kural kaynak incelemesiyle
değil, `tests/test_sdk_probe.py` içinde sunucu yanıtlarına konan sahte sır
işaretleriyle denetlenir: tüm çıktı akışları yakalanır ve hiçbir işaretin
geçmediği doğrulanır — başarı ve hata yollarının her ikisinde de.

### 3.2 Katmanlar aşağı doğru bağımlıdır

```
core → features → strategies → risk → engine → execution/data → cli
```

Alt katman üst katmanı **tanımaz**. Alpaca SDK'si yalnızca `execution/` ve
`data/` içinde görünür. Bu yön sayesinde strateji, altında Alpaca mı yoksa
simülasyon mu olduğunu bilmeden çalışıyor — backtest'in canlının aynısı olması
tam olarak buna dayanıyor.

### 3.3 Strateji saftır

`Strategy.decide(ctx)` ağ çağrısı yapmaz, emir göndermez, saat okumaz, durum
tutmaz. "Ne kadar" ve "yapılsın mı" sorularının cevabını **risk kapısı** verir.
İki sorumluluğu ayırmak, risk kurallarının tek yerde denetlenebilmesini sağlar.

### 3.4 Risk kapısı kimseye güvenmez

Strateji kendi kontrolünü yapsa bile kapı kendi kontrolünü tekrar yapar. On
strateji yazıldığında birinde unutulur; kapı arka duvardır.

Kurallar **kısa devre yapmaz**: tüm veto sebepleri toplanır ve journal'a
yazılır. "Bu işlem neden olmadı" sorusunun cevabı çoğu zaman tek sebep değildir.

### 3.5a Kapatma hesap genelinde iptal eder

Kill-switch ve gün sonu kapanışı, `cancel_open_orders()` ile **hesaptaki tüm
emirleri** iptal eder. Bu, botun kendi hesabında tek başına çalıştığını
varsayar. Aynı hesabı elle kullanıyorsan, kill-switch tetiklendiğinde senin
emirlerin de iptal olur.

Alternatif (sembol bazlı iptal) daha tehlikeli: kapatma sırasında iptal
edilmemiş bir koruma bacağı, sahipsiz kalıp ters yönde yeni pozisyon açabilir.

### 3.5 Her giriş bracket emriyle gider

Stop ve hedef, girişle **aynı istekte** borsaya yerleşir. Sistem gözetimsiz
çalışıyor: bot çökerse, sunucu kapanırsa, ağ giderse bile koruma emirleri
borsada durmaya devam eder.

### 3.6 Emir bir kez üretilir, önce kaydedilir

`BracketOrder.from_intent` her çağrıda yeni bir `client_order_id` üretir. İkinci
kez üretmek, journal'a brokera gidenden farklı bir kimlik yazar ve mutabakat o
işlemi bir daha bulamaz.

Sıra: **journal'a yaz → brokera gönder → cevabı işle.** Ters sırada çalışıp
arada süreç ölürse, brokerdaki emir journal'da hiç görünmez.

### 3.7 Broker tek doğru kaynaktır

Mutabakat, sistemin kendi hafızasına değil broker'ın bildirdiğine göre yapılır.
Pozisyon miktarları olduğu gibi saklanır (kesirli olabilir); yuvarlamak
pozisyonu olduğundan farklı gösterir.

### 3.8 Backtest kendine avantaj sağlamaz

Dolum modeli kötümser: pasif limit emri fiyatın ötesine geçilmeden dolmaz, aynı
barda hem stop hem hedef tetiklenirse stop kabul edilir, gap'lerde dolum
aleyhimize yapılır, giriş ve çıkış aynı barda olmaz.

**Ama kötümserlik bir garanti değildir.** Bu varsayımlar sonucu matematiksel bir
alt sınır yapmaz; sadece bizim düşündüğümüz senaryolarda aleyhimize seçim yapar.
Modellenmemiş etkiler (likidite çekilmesi, kısmi dolum, emir defteri sırası)
gerçeği daha kötü yapabilir. Aynı kodu paylaşmak da simülasyon ile gerçek
gerçekleşmelerin eşitliğini garanti etmez — yalnızca *karar mantığının* aynı
kaldığını garanti eder.

Sınav iki parçalı: **deterministik ileriye bakma testi** (asıl kanıt) ve
**çoklu tohumlu istatistiksel test**. Tek bir rastgele koşunun pozitif çıkması
hata kanıtı değildir — ölçtük, altı tohumdan üçü pozitif çıkabiliyor. Bu yüzden
ortalamaya bakılır ve test bir kanıt değil, sistematik avantaj sızdığında yanan
bir lambadır.

### 3.9 Öğrenme offline ve kapılıdır

Canlı sonuçlara bakıp kendini otomatik güncelleyen kod yazılmaz. Yeni bir
parametre seti canlıya ancak (a) yeterli örnek, (b) walk-forward backtest
üstünlüğü, (c) shadow mode tutarlılığı ile geçer.

### 3.10 Anahtar repoya girmez

`.env` `.gitignore` içindedir. Git geçmişi kalıcıdır: dosyayı sonradan
düzeltmek eski commit'lerdeki anahtarı silmez. `test_architecture.py` her
koşuda izlenen dosyaları tarar.

### 3.11 Holdout, sonuç görülmeden ayrılır ve ilk ölçümde açılmaz

2026-09-26'da kararlaştırıldı (#17). Codex'in önerisi; kural onun cümlesi:

> Sonuç görüldükten sonra aynı test dönemi üzerinde parametre ayarlayıp
> bağımsız başarı diye sunulmaz.

Bu kural en çok **ilk kötü sonuçtan sonra** çiğnenmek istenir, ve o anda
yazılı bir kurala güvenmek yetmez. Bu yüzden mekanizma yapısaldır:

- **Ayrım veri alınırken yapılır**, tek bir P&L satırı hesaplanmadan. Tamamlanmış
  seansların son %20'si `holdout/`, önceki %80'i `baseline/`. Holdout sayısı
  yukarı yuvarlanır. Rastgele değil kronolojik: rastgele seçilen bir gün komşu
  günlerin rejimini paylaşır ve "görülmemiş" sayılamaz.
- **Bölme yalnızca takvime bakar; veri kalitesi ayrı bir kapıdır.** Bir seans,
  kapanışı artı oturma süresi indirmeden önce bittiyse "tamamlanmış"tır — bar
  sayısına bakılmaz. Bir sembolün verisi eksik diye bir gün bölmeden düşseydi,
  holdout sınırının yeri veri boşluğuna göre kayardı (Codex B2). Kalite her
  (seans, sembol) için ölçülüp manifeste yazılır; spec'teki `quality`
  politikası (açılış penceresi, kapanış penceresi, eksik dakika oranı)
  karşılanmazsa ölçüm **P&L üretmeden** durur. Politika spec hash'ine girer:
  indirmeden sonra gevşetmek yeni bir `dataset_id` demektir.
- **Tarihler ve semboller önceden sabittir.** `config/datasets/<id>.yaml` commit
  edilir; çalıştırma anında seçilmez. Değiştirmek yeni `dataset_id` gerektirir
  ve gerekçesi yalnızca veri kalitesi olabilir, performans asla.
- **Veri kümeleri tarih aralığında örtüşmez.** Örtüşseydi, bir kümedeki deneme
  diğerinin holdout'unu görebilirdi.
- **İlk ölçüm yalnızca baseline'ı görür.** Yükleyici `holdout/`'u listelemez,
  okumaz, hash'lemez. Rapor holdout hakkında yalnızca seans *sayısı* taşır;
  tarihleri bile yazmaz.
- **Doğrulanan baytlar, kullanılan baytlardır.** Her baseline dosyası tek kez
  okunur; aynı baytlar hash'lenir ve bellekte çözülür. Ölçüm dosya yolu almaz,
  veri kümesi dizinini bir daha açmaz. Symlink, hardlink ve özel dosyalar hiç
  okunmadan reddedilir: `baseline/` altındaki bir takma ad `holdout/`'a
  çözülemez. (Codex B3: denetim kancası çağrılan yolu görür, çözüldüğü yeri
  değil — symlink ile holdout okunurken kanca "dokunulmadı" diyordu.)
- **Kesin manifest hash'i zorunludur.** "En son veri kümesini al" diye bir yol
  yoktur. Tek bir bayt tutmazsa ölçüm durur.
- **Holdout'u açmak ayrı ve kayıtlı bir değerlendirme olayıdır.** Açıldıktan
  sonra o döneme göre değişen bir aday, **yeni bağımsız veri** gerektirir —
  aynı holdout ikinci kez "görülmemiş" sayılamaz.
- **Otomatik terfi yok.** Baseline raporu bir terfi kararı değildir.

Denetleyenler: `tests/test_dataset.py` (holdout'a erişim Python denetim
kancasıyla ölçülür — `chmod` değil, çünkü root izinleri yok sayar; takma ad
senaryoları ayrıca), `tests/test_baseline_run.py` (doğrulamadan sonra ölçüm
veri kümesinde hiçbir dosya açmaz), `tests/test_dataset_specs.py`
(örtüşmezlik), `tests/test_architecture.py` (veri kümesi modülü backtest,
strateji, öğrenme veya seans döngüsünü içe aktaramaz — performans
hesaplayamayan kod, bölme sınırını performansa göre seçemez).

**Kancanın sınırı:** Python denetim kancası yalnızca Python seviyesindeki
`open`/`os.open`/`scandir`/`listdir` olaylarını görür. Yerel kütüphanelerin
kendi G/Ç'sini gördüğü iddia edilmez. Güvence bu yüzden iki parçalıdır:
yapısal kısım (tek okuma, takma ad reddi, ölçümün yol almaması) ve onu ölçen
testler. Biri tek başına yeterli sayılmaz.

## 4. Çakışmaya açık yerler

| Dosya | Kural |
|---|---|
| `journal/migrations/` | Numara benzersiz ve arasız. **`git fetch` yeterli değildir** — ikimiz aynı anda aynı numarayı seçebiliriz. Numarayı önce issue ile rezerve et (`migration-reservation` şablonu), şema PR'larını sırayla birleştir. **Uygulanmış bir göç dosyası asla düzenlenmez** — değişiklik her zaman yeni bir dosyadır. |
| `CHANGELOG.md` | Sadece `[Yayınlanmamış]` bölümüne ekle, kendi maddeni en alta koy. Çakışırsa ikisini de tut. |
| `config/base.yaml` | Risk limitlerini tek taraflı değiştirme; PR açıklamasında gerekçesini yaz. |
| `requirements*.lock` | Elle düzenlenmez. `make lock` ile ikisi birden üretilir. Çakışırsa `main`'inkini al, kendi bağımlılığını ekle, yeniden üret. |
| `core/types.py` | Herkesin tabanı. Alan eklemek serbest, alan silmek/yeniden adlandırmak PR'da tartışılır. |

## 4a. İnceleme kuralları

**Çift göz zorunlu** olan yerler — buradaki bir hata hesabı boşaltır:

- `src/tlab/risk/`
- `src/tlab/engine/`
- `src/tlab/execution/`
- `src/tlab/core/types.py` ve ortak `Context`
- `src/tlab/journal/migrations/`
- `requirements.lock`
- CI ve güvenlik yapılandırması (`.github/`)

Küçük belge PR'ları hızlı incelenebilir. Ama **"küçük olmak" kritik davranış
değişikliğini incelemeden geçirme gerekçesi değildir** — üç satırlık bir diff
risk kapısını devre dışı bırakabilir.

**İnceleme belirli bir commit'e aittir.** PR'a önemli yeni commit geldiğinde
inceleme yenilenir; eski onay yeni koda geçmez.

**İnceleyici karşı tarafın dalına push etmez.** Bulgu yazar, ya da kendi
dalından takip PR'ı açar. Dal sahipliği korunur.

### Paylaşılan kimlik — inceleme kaydının biçimi

İki ajan da aynı GitHub hesabı altında yazıyor. Sonucu: **hiçbirimiz diğerinin
PR'ını `APPROVE` edemiyoruz** — GitHub bunu "kendi PR'ını onaylama" sayıp
reddediyor (`Can not approve your own pull request`).

Bu yüzden inceleme kaydı yorum olarak tutulur ve **biçimi sabittir**:

| Başlık | Anlamı |
|---|---|
| `## ONAY — <commit-sha>` | Açık bulgu yok, birleşebilir |
| `## BULGU — <commit-sha>` | En az bir bulgu var |

Commit SHA zorunlu: inceleme belirli bir commit'e aittir, PR'a değil.

**Sonuç: `main` üzerinde "require approving review" kuralı AÇILMAMALI.**
Teknik olarak sağlanamaz ve her PR'ı kalıcı olarak bloklar. PR zorunluluğu,
"require status checks" (`quality`) ve yöneticilere uygulama korunur.
Mevcut korumalar bu kısıt nedeniyle kaldırılmaz veya bypass edilmez.

Kalıcı çözüm, ajanlardan birine ayrı bir GitHub kimliği vermek (ikinci hesap ya
da GitHub App). Bu kullanıcının kararı; iki ajan kendi arasında çözemez.

## 4b. Ajanlar nasıl konuşur

İnsan aracı olmadan çalışıyoruz; koordinasyon GitHub üzerinden yürür.

| Konu | Kanal |
|---|---|
| Kod hakkında bulgu | PR incelemesi (satır yorumu tercih edilir) |
| Tasarım kararı, kapsam tartışması | Issue (`coordination` şablonu) |
| Göç numarası rezervasyonu | Issue (`migration-reservation` şablonu) |
| Yarım kalan iş, devir | `docs/handoffs/NNN-konu.md` + PR açıklaması |
| Karara bağlanan her şey | Bu dosyaya işlenir — sohbet kaybolur, repo kalmaz |

**Bir karar `AGENTS.md`'ye yazılmadıysa alınmamış sayılır.** İki ajan arasındaki
mutabakatın tek kalıcı kaydı burasıdır.

Tıkandığında: engelleyen tarafa issue aç, etiketle, kendi dalında engellenmeyen
işe devam et. Beklemek yerine paralel ilerle.

## 5. Commit ve PR

[Conventional Commits](https://www.conventionalcommits.org/):
`feat|fix|refactor|test|docs|chore|build|ci(<kapsam>): <özet>`

**Her commit tek bir iş yapar ve repoyu çalışır durumda bırakır.** `git bisect`
ancak böyle işe yarar.

Commit gövdesi **ne yapıldığını değil neden yapıldığını** anlatır; ne yapıldığı
diff'te zaten görünür.

PR açarken şablon (`.github/pull_request_template.md`) otomatik gelir; boş
bırakma. Özellikle **"Diğer geliştiricinin bilmesi gerekenler"** bölümü: şema
göçü eklediysen, ortak dosyaya dokunduysan ya da bir şeyi yarım bıraktıysan
orada yazmalı.

## 6. Devir teslim

Bir işi yarım bırakıyorsan PR'ı **taslak** olarak aç ve açıklamasına şunu yaz:
nerede kaldın, sıradaki adım ne, hangi varsayımı test etmedin. Yarım kalmış işin
en pahalı tarafı kodun eksikliği değil, bağlamın kaybolmasıdır.

## 7. Doğrulanan ve doğrulanmayan

Bu bölüm iddiaları **kapsamıyla** tutar. "Bağlandı" tek başına bir şey
söylemez; hangi yolun, neyi, hangi koşuda doğruladığı söyler.

### Doğrulanan — 2026-09-23 ve 2026-09-24

| Ne | Kanıt | Kapsam |
|---|---|---|
| Anahtarlar geçerli, ağ açık | Koşu `35809584609`, iş `107017907456` | Elle kurulmuş GET; **SDK'ya dokunmaz** |
| **Bizim kodumuz Alpaca ile konuşuyor** | Koşu `36031659146`, iş `107741630086` | Gerçek `AlpacaBroker` + `AlpacaMarketData` |

İkinci koşunun çıktısı, dört aşama da ayrı ayrı:

```
OK hesap          # hesap okundu ve is_healthy dogrulandi
OK borsa saati    # takvim cozumlendi, degerler tutarli
OK gunluk bar     # D1 eslemesi calisiyor, Bar tipine cevriliyor
OK dakikalik bar  # M1 eslemesi calisiyor - hic calismayan esleme BUYDU
```

Dakikalık aşamanın ayrı olması tesadüf değil: `_TIMEFRAME_ARGS` içinde
`"Minute"` yazdığı için `tlab fetch` hiç çalışmıyordu ve 272 test yeşildi.
Yalnızca günlük bara bakan bir prob o hatayı yine kaçırırdı.

Bu paper SDK koşusunun tanı çıktısında hassas değer görülmedi: probun
bastığı dört satırda bakiye, hesap kimliği veya yanıt gövdesi yok. Bu
**tek bir başarı koşusudur**; bütün hata yolları için ya da canlı hesap
için genel bir güvence değildir. Hata yollarındaki sızdırmama güvencesi
yerel sözleşme testlerinden (`tests/test_sdk_probe.py`) gelir.

### Doğrulanan — 2026-09-28: ilk gerçek veri kalite pilotu

| Ne | Kanıt | Kapsam |
|---|---|---|
| Pilot kalite ölçümü uçtan uca çalışıyor | Koşu `36369564690`, iş `108762810599`, main `e7265fa` | `pilot-2026-06-u12`: 12 sembol × 5 seans, IEX 1Min. P&L ve emir yok. |

Koşunun sonucu, olduğu gibi (#17):

```
seans: takvim 5, tamamlanmis 5, uygun 3, uygunsuz 2
11 sembol: 5/5 seans uygun (toplam eksik 0.00%-0.82%, AMD 4.21%)
JPM: acilis eksikli seans 2, toplam eksik 5.69%, uygunsuz 2
sonuc: some_ineligible
```

**Bu koşunun söylediği ve söylemediği:**

- Söylediği: pilot aracı gerçek ortamda indirdi, ölçtü, yalnızca özeti
  yükledi; temizlik adımı başarılı. Bu koşunun log'unda fiyat, hesap değeri
  veya yanıt gövdesi görülmedi; secret'lar maskeli. **Tek bir başarı
  koşusudur**; hata yollarının güvencesi yerel sözleşme testlerinden gelir.
- Söylemediği:
  - 5 seanslık örnek, ana dönem (~63 seans) için güvenilir bir olasılık
    tahmini **değildir**. Gözlenen uygunsuzluk bir risk işaretidir.
  - Kapanış penceresinde bar bulunması gün sonu kapatmasının **dolacağını
    kanıtlamaz**: tetiklemeden sonra gerçek bir bar gerekir; seans sınırı
    değişmezi (§3.11) bu yüzden duruyor.
  - IEX'in bu sembollerde genel kalitesi hakkında bir hüküm değildir.

**Sonraki adım (Codex kararı, #17):** eşik gevşetilmez, JPM şimdilik
evrenden çıkarılmaz, ana tanım `draft` kalır. Aynı 12 sembol ve aynı
IEX/kalite politikasıyla, ana dönem ve ilk pilotla örtüşmeyen daha geniş
bir ek pilot (`2026-05-11..2026-06-05`, yeni `dataset_id`) **bir kez**
ölçülür. Bu pencere ilk sonuç görüldükten sonra seçildiği için keşif/kalite
çalışmasıdır; bağımsız performans kanıtı sayılmaz. Uygun sonuç çıkana
kadar pencere değiştirilmez.

### Doğrulanan — 2026-09-28: ek kalite pilotu ve JPM kararı

| Ne | Kanıt | Kapsam |
|---|---|---|
| Ek pilot kalite ölçümü | Koşu `36372943220`, iş `108772841799`, main `e99a9bc` | `pilot-2026-05-u12`: 12 sembol × 19 seans (`2026-05-11..2026-06-05`), IEX 1Min, ilk pilotla aynı politika. P&L ve emir yok. |
| Özet artefaktı içeriği | Artefakt `10949717868`, 921 bayt, ZIP SHA256 `b6c543cdd305399bd4ffef7e373384af3368644607b3650dafa16b9c65340ac3`; tek dosya `pilot-summary.json` | Codex indirip açtı (#17): alan listeleri, semboller, politika ve üretici commit'i kod/spec ile eşleşti. Gün bazlı tarih özette yok. |

Koşunun sonucu, olduğu gibi (#17):

```
seans: takvim 19, tamamlanmis 19, uygun 13, uygunsuz 6
11 sembol: 19/19 seans uygun (toplam eksik 0.00%-1.35%, AMD 4.66%)
JPM: acilis eksikli seans 4, toplam eksik 5.64%, uygunsuz 6
sonuc: some_ineligible
```

JPM'nin 6 uygunsuz seansının gerekçeleri (artefakttan): `acilis_penceresi_eksik`
4, `eksik_dakika_orani` 3; bir seans iki gerekçeli (4 + 3 = 7, birleşim 6).

İki pilot birlikte, JPM için **iki ayrı sayı**:

| | İlk pilot (5) | Ek pilot (19) | Toplam (24) |
|---|---|---|---|
| JPM, herhangi bir kalite uygunsuzluğu | 2 | 6 | **8** |
| JPM, açılış penceresi eksik | 2 | 4 | **6** |
| Diğer 11 sembolün her biri, uygunsuz | 0 | 0 | **0** |

**Bu koşunun söylediği ve söylemediği:**

- Söylediği: ek pilot da yalnızca özeti yükledi, temizlik adımı başarılı;
  log'da fiyat, hesap değeri veya yanıt gövdesi görülmedi, secret'lar
  maskeli. Yine **tek bir başarı koşusudur**.
- Söylemediği:
  - Diğer 11 sembolde 0/24, **betimsel bir gözlemdir**. Ana dönem için
    güvence, olasılık tahmini veya güven aralığı değildir: semboller ve
    günler ortak koşullara bağlı, bağımsız denemeler değil; ek pencere de
    ilk sonuç görüldükten sonra seçildi. Ana dönemde uygunsuz seans çıkarsa
    katı politika ölçümü P&L'den önce durdurur.
  - JPM'nin veya IEX'in genel kalitesi hakkında bir hüküm değildir.
  - İlk pilotun kapanış barı notu (yukarıda) aynen geçerlidir.

**Karar (Codex, #17; #30 ile uygulandı):** JPM, IEX tabanlı ORB ölçüm ve
işlem evreninden çıkarıldı. Gerekçe yalnızca iki pilotta tekrarlanan veri
kalitesi uygunsuzluğu; P&L hesaplanmadan ve ana indirme yapılmadan verildi.
Ana tanım `orb-baseline-2026q3` → `orb-baseline-2026q3-u11`: yalnızca
`dataset_id` ve semboller değişti, diğer alanlar ve kalite eşikleri aynı,
durum `draft`. `config/universe.yaml` 11 sembol. İki pilot tanımı 12
sembolle ölçüldükleri için değişmez (testle sabit). Pilotlar tamamlandı;
yeni pencere veya tekrar koşu yok. `approved` ve ana ölçüm ayrı tasarım ve
inceleme gerektirir.

### Hâlâ doğrulanmayan

- **Emir yaşam döngüsü.** Hiç emir gönderilmedi. Dolum, kayma, kısmi dolum,
  iptal, bracket bacaklarının davranışı — hiçbiri gerçek ortamda görülmedi.
- **Gözetimsiz seans.** Sistem bir kez bile canlı çalışmadı. Yeniden
  başlatma/mutabakat, çift emir engeli, gün sonu kapatma gerçek ortamda
  sınanmadı.
- **Stratejinin kârlılığı.** ORB gerçek piyasa verisiyle bir kez bile
  backtest edilmedi. Sistemin sağlam olması, stratejinin kazandırdığı
  anlamına gelmez; bunlar ayrı iki sorudur ve ikincisine henüz dokunulmadı.

Bu üçü tamamlanmadan hiçbir yerde "sistem hazır" yazılmamalı.

## 8. İnceleme ve kalıcı devir notları

Her görevin issue'sunda kapsam ve kabul şartları, PR'ında doğrulama kanıtı ve
bilinen sınırlar bulunur. Geliştirici ve bağımsız inceleyici rollerini Codex ve
Claude dönüşümlü üstlenebilir. İnceleyici önceki asistanın beyanını kanıt saymaz;
diff'i ve hata senaryolarını kontrol eder. Bulgular PR'a yazılır; geliştirici
kendi dalında düzeltir. İnceleyicinin kod yazması gerekiyorsa kendi dalından
ilgili PR dalına küçük bir takip PR'ı açar; dal sahipliği kuralı korunur.

Teslim notları `docs/handoffs/` altındadır: başlangıç commit'i, issue/PR,
yapılan iş, test sonuçları, sınırlamalar ve sonraki somut görev. Kullanıcı
"devam et" dediğinde açık PR ve ilgili devir notundan başlayın.

Gerçek hesap işlemi, deploy veya finansal risk limitlerini değiştirme bu
inceleme düzeninin otomatik parçası değildir; kullanıcı görevinin kapsamına
göre ilerleyin. Ağsız testler gerçek broker davranışını veya kârlılığı kanıtlamaz.

## 9. Ayrılmış hesap varsayımı

Bu bot hesapta tek işlem süreci olarak çalışır. Kill-switch ve gün sonu kapatma
hesap genelindeki bekleyen emirleri iptal eder; manuel veya başka stratejilerin
emirleri de etkilenir. Aynı hesabı başka işlem süreçleriyle paylaşmayın.

## 10. Research sözleşmesi — issue #12

Codex geliştirir, Claude bağımsız inceler. İlk PR yalnızca ortak tipleri ve
isteğe bağlı Context alanını ekler; sağlayıcı, göç ve risk davranışı ayrı PR'lardır.

- Olayın zamanı, yayımlanma zamanı ve revizyonun sisteme ulaştığı `known_at`
  ayrıdır. Provenance OBSERVED / PROVIDER_CLAIMED / BACKFILLED olarak saklanır.
  OBSERVED olsa bile karar anından sonra öğrenilen bilgi geçmişte kullanılamaz.
- Snapshot, kaynak/sembol/olay türleri/zaman kapsamı ve güncelliği taşır.
  AVAILABLE, EMPTY, UNAVAILABLE ve STALE feature yolunda ayrı kalır.
  EMPTY yalnızca kapsamı tam, başarılı sorguyla doğrulanmış boş sonuçtur.
- Snapshot kimliği tüm karar içeriğinin sürümlü hash'idir. Olay sırası ve aynı
  anın UTC offset gösterimi kimliği değiştirmez. Depolama eklendiğinde kayıtlar
  yalnızca eklenir; eski revizyonlar ve snapshot'lar güncellenmez.
- Gün hassasiyeti borsa saat dilimindeki tam günü kapsar (DST dahil).
  BMO / AMC / UNKNOWN kaynak beyanıdır; kesin saat değildir.
- `has_verified_knowledge` yalnızca research verisinin gerekli uygunluk
  koşuludur, strateji terfi onayı değildir. Research kullanan Faz 3 koşusu
  doğrulanmamış veride `promotion_eligible=False` taşımak zorundadır.
- Context snapshot'ı kendi sembolü ve karar anıyla eşleşmelidir. `None`
  research sağlanmadığını belirtir, olay yokluğunu değil.
- Alanlar journal için ilkel değerlerle serileştirilebilir kalır. Tarihsel
  revizyon seçimi, kapsam doğrulaması, kalıcı kayıt ve risk blokları sonraki
  PR'larda ayrıca sınanacaktır; bu tipler onları uygulanmış hale getirmez.

Çekirdek tiplerin üçüncü taraf bağımlılık sınırı korunur; snapshot hash ve
DST sınırları için standart kütüphaneden hashlib/json/zoneinfo izinlidir.

### 10.1 Research v2 uygulama sözleşmesi — #20

Bu bölüm sonraki uygulamanın kabul şartıdır; v2 henüz uygulanmış değildir.
Tasarım: `docs/designs/research-v2-selection.md`. Tip, saf seçim hizmeti,
sağlayıcı, depolama/göç ve risk entegrasyonu ayrı PR'larla ilerler.

- Her revizyon ve kapsam kanıtı için `known_at <= received_at <= decision_at`
  korunur. Yerel alım zamanı değişmez; provider tarihi onun yerine geçmez.
  Varsayılan provenance filtresi yalnız OBSERVED'dir; genişletmek zaman kapısını
  kaldırmaz. Filtre olaylara ve kapsam kanıtına uygulanır; EMPTY uydurulmaz.
- Önce görünür son revizyon seçilir, sonra olay kapsamı uygulanır. Tarihi veya
  sembolü düzeltilen/iptal edilen olayın eski revizyonu diriltilemez.
- Dört status korunur. Birincil reason yanında T anında görünür kanıttan
  saptanan tüm tanı koşulları zorunlu kaydedilir; seçim kısa devre yapmaz.
  Sınanamayan koşullar tanıda ayrı gösterilir. Gelecek bilgi tanıya da giremez.
- Son ilgili sorgu başarısızsa eski cache'e sessiz dönüş yapılmaz; eski cache
  tam ve güncel olsa da provider_error koşulu vardır. STALE tam kanıtın süresi
  dolmasıdır; öncelikli hata varsa onu örtmez. Birincil reason sırası tasarımda
  sabittir, diğer koşullar onun arkasında kaybolmaz.
- Snapshot kimliği görünür karar kanıtı, kapsam/zaman, filtre ve politika
  sürümünü içerir; tam veri evreninin manifest kimliği değerlendirmede ayrıca
  saklanır. Gelecek/dışlanan girdiler karar hash'ine eklenmez. Zaman kapısından
  geçmiş ama provenance nedeniyle dışlanmış kanıtın tanısı ayrı evaluation
  kaydındadır; provider arızası bu yüzden görünmez olmaz.
- V1 okuyucusu/hash'i korunur; eksik received_at üretilmez ve sessiz v2 dönüşümü
  yapılmaz. Research-farkındalıklı v2 değerlendirme geçmişi ilk doğrulanabilir
  yerel alım ve kapsam kanıtından itibaren birikir. Şema kurulumu veya geçmiş
  veri indirmek, geçmişte gözlenmiş kapsam üretmez. İstenen değerlendirme
  penceresi boyunca yeterli kanıt birikmeden research-farkındalıklı terfi
  uygunluğu iddia edilmez; gecikme nedeniyle zaman/provenance kapıları gevşetilmez.
  Research kullanmayan baseline bundan etkilenmez; v1 audit kayıtları silinmez.

- V2 `ResearchQuery.symbol`, ortak boşluk temizliğinden sonra ASCII büyük harfle
  başlayan `[A-Z][A-Z0-9.\-]*` biçimini şart koşar; küçük/karışık harf sessizce
  dönüştürülmez (#21 incelemesi). Bu yalnız sorgu sözdizimidir, sağlayıcıda
  sembolün varlığını kanıtlamaz. V1 olay sembolü/hash'i değiştirilmez.
  Selector, olay/kapsam kanıtındaki sembol uyuşmazlığını doğrulanmış EMPTY
  sayamaz; kapsam kanıtının sorgunun kanonik sembolüyle eşleşmesi gerekir.


## 11. Alpaca pilotu ve veri taşıma — #17, 2026-09-27

Karar ve kaynak sınırı: `docs/designs/alpaca-pilot-execution.md`.
SDK bağlantısı §7'de doğrulanmıştır; emir yaşam döngüsü ve kârlılık değildir.
İlk gerçek veri pilotunun geliştirilmesi kalıcı ham veri taşımasına bağlı değildir:

- Ayrı, incelenen workflow: manuel, yalnız main, koddan sabit pilot tanımı
  (girdi almaz), tek job içinde indirme ve kalite ölçümü. P&L ve emir yok.
- Ham barlar, manifest ve veri dizini artifact/cache/log'a yüklenmez. Yalnız
  açık alan listesiyle üretilmiş toplulaştırılmış kalite özeti, kod/spec hash'i
  yayımlanır. Broker secret'ları yalnız indirme adımında bulunur.
- Geçici veri başarı/hata sonunda temizlenir; temizleme güvenli fiziksel silme
  garantisi sayılmaz. Ana veri tanımı pilotlar süresince draft kaldı; onayı
  ayrı commit ve bağımsız incelemeyle verildi (§11.1).
- Kişisel analiz için bu mimariyle ilerleme, Alpaca'dan özel bir bulut lisansı
  alındığı iddiası değildir. Hesaba/veri feed'ine özgü ek şartlar geçerlidir.
  Gerçek ham verinin kalıcı dış artefaktı ayrı değerlendirilir; sentetik
  taşıma ve pilot kodunun ilerlemesi ona bağlanmaz.
- Claude pilot workflow'unu geliştirir, Codex bağımsız inceler.
- **Durum (2026-09-28):** iki pilot tamamlandı ve kaydı §7'de:
  `pilot-2026-06-u12` (5 seans, koşu `36369564690`) ve ek
  `pilot-2026-05-u12` (19 seans, koşu `36372943220`; workflow'un sabit
  tanımı #29'dan beri bu). İki tanım da 12 sembolle ölçüldükleri için
  değişmez. Yeni pilot penceresi veya tekrar koşu planlanmıyor. Ana tanım
  artık `orb-baseline-2026q3-u11` (11 sembol, JPM veri kalitesi
  gerekçesiyle çıkarıldı; o gün `draft`, onayı §11.1'de). Pilotların
  güvenli akışı, ana ölçüm için kalıcı ham veri dış aktarımına izin
  sayılmaz; ana ölçüme bu workflow'a P&L eklenerek geçilmez.

### 11.1 Ana ölçüm onayı — #17, 2026-09-28

`orb-baseline-2026q3-u11` ayrı bir commit ile `approved` yapıldı. Yürütme
sözleşmesi: `docs/designs/baseline-measurement-execution.md`. Değişen tek
alan `status`; tarih, feed, bölme, settle, retention ve kalite eşikleri
testle sabit (`tests/test_dataset_specs.py`).

**Dayanak:**

- İki kalite pilotu, aynı politikayla: 5 + 19 seans (§7).
- JPM, iki pilotta tekrarlanan veri kalitesi uygunsuzluğu gerekçesiyle
  P&L görülmeden çıkarıldı (#30).
- Holdout taahhüdü ve rapor şeması v2 (#32).
- İki adımlı iş, sızıntı ve sözleşme testleri, iki ayrı süreçte yerel
  sentetik uçtan uca kanıt (#33).
- Hedef ölçekli sentetik benchmark: Claude ve Codex ayrı ayrı çalıştırdı.
- Politika ön uçuş testi: gerçek tanım + gerçek config, P&L öncesi politika
  kapısından geçiyor.

**Onayın kapsamı:** yalnızca bu sabit tanımın indirilmesi ve baseline
bölümünün **bir kez** ölçülmesi. Onay şunları **kapsamaz:**

- işlem ya da emir;
- canlı dağıtım;
- holdout'un açılması;
- parametre terfisi.

**Durma kuralı:** kalite ya da seans sınırı hatasında ölçüm rapor üretmeden
durur. Aynı dönemi geçsin diye eşik, parametre, pencere ya da tanım
değiştirilip **yeniden denenmez**; sonuç #17'de tartışılır.

**Yeniden koşu (Codex kararı, #17, 2026-09-28):** otomatik yeniden deneme
mekanizması yoktur. Bu bir operasyon sınırıdır.

- **Kayıt önce gelir.** İlk koşunun run/job kimliği, code commit'i ve
  başarısız adımı #17'ye yazılır. Adım kanıtıyla şu iki şey doğrulanır:
  B hiç başlamadı ve geçerli bir performans raporu üretilmedi.
- **Tek istisna:** aynı code commit, tanım, config ve workflow ile **en
  fazla bir** yeniden koşu. Yalnızca şu iki durumda geçerlidir:
  - A'dan önce checkout ya da kurulumda açıkça geçici bir altyapı hatası;
  - A'da sınıflandırılmış `FAIL indirme: sunucu hatasi (5xx)`,
    `FAIL indirme: hiz siniri (429)` ya da
    `FAIL indirme: ag, TLS veya zaman asimi hatasi`.
- **Kısıtlar:**
  - 429'da oran sınırı geçmeden yeniden tetikleme yapılmaz.
  - `main` ilerlediyse "aynı commit" varsayımı kurulamaz; yeni bir head
    otomatik olarak kapsam dışıdır.
- **Runner kaybı ya da iş zaman aşımı otomatik istisna değildir.** Önce
  #17'de ayrı karar gerekir. Aynı şey şu durumlar için de geçerlidir:
  - hangi aşamada düştüğü kanıtlanamıyor;
  - B başlamış;
  - geçerli bir rapor oluşmuş;
  - yalnızca temizlik ya da upload başarısız olmuş.

  Yayımlanmamış bir rapor, "başarıyla ölçülmemiş" sayılmaz.
- **Dur.** Şu hatalarda yeniden koşu yoktur; yeni bir koşu ayrı inceleme
  gerektirir:
  - onay, bütünlük, kalite, politika ya da seans sınırı hatası;
  - yetki reddi ya da beklenmeyen hata;
  - tek altyapı tekrarının da başarısız olması.

  Geçsin diye veri, tanım ya da strateji değişikliği yapılmaz.

**Sınır:** yerel sentetik kanıt hosted Actions'ı, secret enjeksiyonunu ve
artifact yükleme hizmetini doğrulamaz. Gerçek koşunun kaydı (run/job,
artefakt, sonuç) §7'ye ayrıca yazılır.
