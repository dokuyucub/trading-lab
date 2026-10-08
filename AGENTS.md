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

### Doğrulanan — 2026-09-28: ana ölçümün ilk gerçek koşusu (kalite kapısında durdu)

| Ne | Kanıt | Kapsam |
|---|---|---|
| Ana ölçüm workflow'u gerçek ortamda uçtan uca çalıştı ve kalite kapısında durdu | Koşu `36474064587`, iş `109103241218`, main `c6c19db`, `run_attempt` 1; kullanıcı bir kez tetikledi | `orb-baseline-2026q3-u11` (`approved`, §11.1). P&L yok, emir yok, rapor yok. |

§11.1'deki onay bu koşuyla **kullanıldı**. Adımlar:

| Adım | Sonuç |
|---|---|
| Kurulum | success |
| A: indirme (secret yalnızca bu adımda, maskeli) | success, 17 sn |
| B: anahtarsız ölçüm | **failure**, exit 1, ~4 sn |
| Temizlik (`always()`, `rm -rf` + `test ! -e`) | success |
| Rapor yükleme | skipped; artefakt listesi boş (Codex doğruladı) |

Aracın bütün çıktısı, olduğu gibi (#17):

```
OK indirme orb-baseline-2026q3-u11 (manifest faffa591bba1)
seans: takvim 63, tamamlanmis 63, baseline 50, holdout 13
kaliteye uymayan baseline seansi: 10
FAIL kalite: 10 baseline seansi uygunsuz; rapor yazilmadi
```

**Bu koşunun söylediği ve söylemediği:**

- Söylediği:
  - Onay kapısı, iki adımlı secret sınırı, anahtarsız ölçüm, P&L öncesi
    kalite kapısı, temizlik ve "başarısızlıkta rapor yok" gerçek ortamda
    tasarlandığı gibi çalıştı.
  - Log'da fiyat, tarih, sembol, yanıt gövdesi ya da performans sayısı yok.
    Holdout için yalnızca seans sayısı (13) var.
  - 50 baseline seansının 10'unda en az bir sembol mevcut politikaya göre
    uygunsuz.
- Söylemediği:
  - **Stratejinin performansı.** Hesaplanmadı; ORB'nin gerçek veride
    sonucu hâlâ bilinmiyor.
  - **Hangi semboller, hangi gerekçeler.** Araç yalnızca sayıyı basar;
    manifest temizlikte silindi, elde yalnızca hash öneki var.
  - **Pilotlarla farkın nedeni.** Pilotlarda bu 11 sembolde 24 seansta
    uygunsuzluk görülmemişti. 0/24 bir güvence değildi (Codex); farkın
    nedeni bilinmiyor.
  - **Tekrarlanabilirlik.** Yeni bir indirmenin aynı baytları vereceği
    kanıtlanamaz; sağlayıcı ya da takvim revizyonu mümkündür.

**Karar (Codex, #17):**

- Bu bir altyapı hatası değildir; §11.1'deki tek yeniden koşu istisnasına
  girmez. **Ana ölçüm workflow'u yeniden koşulmaz.**
- Eşik, evren, tarih ya da strateji "geçsin diye" değişmez.
- Sonraki adım ayrı, P&L'siz, yalnızca baseline için bir kalite teşhisidir.
  Önce tasarım, sonra incelenen PR, sonra tek bir tetikleme. Teşhis sonucu
  performans onayını kendiliğinden yeniden açmaz.
- Kalite nedenleri bilinmeden SIP, yeni dönem, başka evren ya da tolerans
  hakkında karar verilmez.

### Doğrulanan — 2026-09-29: baseline kalite teşhisi (tek koşu)

| Ne | Kanıt | Kapsam |
|---|---|---|
| Baseline kalite teşhisi gerçek ortamda bir kez koştu ve özet yayımlandı | Koşu `36502365666`, iş `109195931115`, main `44ca3bb`, `run_attempt` 1; kullanıcı `main` CI'sı başarıyla bittikten sonra bir kez tetikledi | `diag-orb-baseline-2026q3-u11-quality-1` (§11.2). Yalnızca baseline, P&L yok, emir yok, holdout barı yok. |
| Özet artefaktının içeriği | Artefakt `11004953510`, 1489 bayt, ZIP SHA256 `5ae3e3e0ab21e3a3bb70d3b6cfe7fadebe506c90f4b200c863fb43711dd7ea98`; tek üye `baseline-quality-diagnostic.json` | Codex indirip açtı (#17). Kontrol edilenler: alan kümeleri, 11 sembol, kaynak hash'i `369f4e7f…c027dc505`, eski run/head/manifest öneki, producer, IEX/1Min/raw, politika ve notlar. Ham, günlük, hesap ya da holdout kalitesi alanı yok. Claude artefaktı açamadı (oturum ağ politikası, 403); Claude'un denetimi log'a dayanır. |

Adımlar: kurulum success (16 sn), teşhis success (10 sn; secret yalnızca bu
adımda, maskeli), özet yükleme success.

Aracın bütün çıktısı, olduğu gibi (#17):

```
OK teshis diag-orb-baseline-2026q3-u11-quality-1 (kaynak orb-baseline-2026q3-u11)
seans: takvim 63, tamamlanmis 63, baseline 50, holdout 13
baseline: uygun 40, uygunsuz 10 (seans birlesimi); uygunsuz sembol-seans 11
  SPY    uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.02%, tekrar 0
  QQQ    uygunsuz  1 | gerekce: bar yok 0, acilis 1, kapanis 0, oran 0, diger 0 | eksik 1.16%, tekrar 0
  IWM    uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.66%, tekrar 0
  AAPL   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.01%, tekrar 0
  MSFT   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.23%, tekrar 0
  NVDA   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.01%, tekrar 0
  AMD    uygunsuz 10 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 10, diger 0 | eksik 5.48%, tekrar 0
  AMZN   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.33%, tekrar 0
  GOOGL  uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.07%, tekrar 0
  META   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.55%, tekrar 0
  TSLA   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.07%, tekrar 0
yayginlik (uygunsuz seans basina uygunsuz sembol): 1 sembol: 9, 2 sembol: 1
not: sembol ve gerekce toplamlari ortusur; toplanarak seans birlesimi aciklanmaz
sonuc: some_ineligible
```

**Bu koşunun söylediği ve söylemediği:**

- Söylediği:
  - Sayımlar tutarlı: 40 uygun + 10 uygunsuz = 50. Histogram 9×1 + 2×1 =
    11 sembol-seans, birleşim 10.
  - **Uygunsuz 10 seansın hepsi bir AMD seansı.** Bu bir çıkarım değil,
    sayımların sonucu: birleşim 10 ve AMD'nin 10 uygunsuz seansı var.
  - AMD'nin tek gerekçesi eksik dakika oranı: 10 seansta düzenli seans
    dakikalarının %10'undan fazlası için IEX barı yok. Toplam oran
    0,054821. Açılış ya da kapanış eksiği yok.
  - QQQ: bir seansta açılış penceresinde **tam 1 dakika** eksik
    (`max_missing_open_window = 1`). Bu seans AMD'nin 10 gününden biriyle
    çakışıyor.
  - Diğer 9 sembolde uygunsuzluk yok.
  - Bu kalite eşiklerine göre aynı seansta en fazla 2 sembol uygunsuz.
  - Mevcut politikayla yalnızca AMD'yi çıkarmak ölçümü geçirmezdi (QQQ'nun
    tek seansı kalırdı).
- Söylemediği:
  - **Stratejinin performansı.** Hesaplanmadı.
  - **Başarısız ana koşuyla aynı bayt ya da aynı günler.** Sayı yine 10,
    ama yeni bir erişim; kanıtlanamaz.
  - **Neden.** "IEX'te o dakika bar yok" bir gözlemdir; nedeni (o dakikada
    IEX'te işlem olmaması ya da sağlayıcı tarafı) bu teşhisten çıkmaz.
    Eşiği geçmeyen ortak eksikler olabilir; histogram sağlayıcı ya da
    altyapı kaynaklı bir nedeni dışlamaz.
  - **Pilotlarla farkın nedeni.** Pilotlarda AMD'nin toplam eksiği %4,21 ve
    %4,66'ydı, uygunsuz seansı 0/24'tü; bu dönemde 10/50.

**Karar (Codex, #17):**

- **D:** `orb-baseline-2026q3-u11` üzerindeki IEX ana ölçüm denemesi kalite
  nedeniyle **durmuş olarak kapatılır.** Tanım ve geçmiş değişmez.
  - A ya da B yok: AMD ya da QQQ çıkarılmaz, seans dışlanmaz, eşik
    gevşetilmez.
  - Bu tanım için P&L onayı tüketilmiştir.
- **Proje durmuyor. Sınırlı C:** ayrı kimlikli, P&L'siz bir tarihsel SIP
  erişimi ve kalite karşılaştırması görevi tasarlanır. Kapsam: aynı 11
  sembol, aynı baseline kapsamı ve aynı politika.
  - Bu yeni bir performans veri kümesi değildir; eski tanımın feed'ini de
    değiştirmez.
  - SIP üzerinden de holdout'a erişilmez. Örtüşmezlik testi gevşetilmez.
  - Tarihsel SIP erişimi hesabımızda **doğrulanmadı**. Erişim reddinde
    görev açık sonuçla durur; IEX'e sessiz dönüş ya da ücretli plana geçiş
    yoktur. Abonelik ya da ücret kararı yok.
  - Önce tasarım, sonra incelenen kod, sonra tek koşu.
- Bu karar, ölçüm dönemi kalite gözleminden **sonra** alınmış bir araştırma
  kararı olarak kayıtlıdır. İleride yapılacak bir SIP P&L değerlendirmesine
  otomatik onay değildir.

### Doğrulanan — 2026-10-03: tarihsel SIP kalite karşılaştırması (tek koşu)

| Ne | Kanıt | Kapsam |
|---|---|---|
| SIP karşılaştırması gerçek ortamda bir kez koştu ve özet yayımlandı | Koşu `37096896917`, iş `111128551838`, main `9b3c37f`, `run_attempt` 1, `workflow_dispatch`; 2026-10-03 04:32:45 UTC'de `dokuyucub` hesabından, #38'in merge CI'sı (`37092765560`) başarıyla bittikten sonra tetiklendi | `feedcmp-orb-baseline-2026q3-u11-sip-1` (§11.3). Yalnızca baseline; P&L yok, emir yok, holdout barı yok. Feed `iex -> sip`, görev düzeyinde. Codex run, job, log ve artefakt API'sini bağımsız doğruladı (#17). |
| Özet artefaktı | Artefakt `11264113777`, 1754 bayt. Upload log'undaki ZIP SHA256 ile API `digest` aynı: `3e90ef13112df983acc60f49b009130ba3c109761344d39e4f3a6a08534b8c9b`. Son geçerlilik 2027-01-01. | **ZIP/JSON bağımsız doğrulandı (Codex, 2026-10-08).** Kullanıcı mevcut ZIP'i iletti; yeni koşu yok. Yerelde hesaplanan SHA256 API ve upload digest'iyle aynı; 1754 bayt; tek üye `baseline-feed-comparison.json`; CRC temiz. Programatik denetim: üst ve iç alan kümeleri; schema, kind ve görev; `source` kimliği ve hash `369f4e7f…c027dc505` (depodaki tanımdan yeniden hesaplandı); `iex -> sip` override; IEX `reference` (run, artefakt, hash); producer run `37096896917`, commit `9b3c37f` ve workflow; politika, 11 sembol, sayımlar ve notlar. İlk indirme denemeleri çözülmüş bir indirme olayıdır (Claude: oturum ağ politikası, 403; Codex: HTTP 403 / `error code: 1010`); Alpaca'nın 403'ü değildir. |

Adımlar: kurulum success (14 sn), karşılaştırma success (16 sn; secret
yalnızca bu adımda, maskeli), özet yükleme success (`upload-artifact@v4`).

Aracın bütün çıktısı, olduğu gibi (#17):

```
OK karsilastirma feedcmp-orb-baseline-2026q3-u11-sip-1 (kaynak orb-baseline-2026q3-u11; feed iex -> sip, gorev duzeyinde)
erisim: 11/11 sembol yanit aldi; baseline bari gelen sembol 11/11
seans: takvim 63, tamamlanmis 63, baseline 50, holdout 13
baseline: uygun 50, uygunsuz 0 (seans birlesimi); uygunsuz sembol-seans 0
  SPY    uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  QQQ    uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  IWM    uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  AAPL   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  MSFT   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  NVDA   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  AMD    uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  AMZN   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  GOOGL  uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  META   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
  TSLA   uygunsuz  0 | gerekce: bar yok 0, acilis 0, kapanis 0, oran 0, diger 0 | eksik 0.00%, tekrar 0
yayginlik (uygunsuz seans basina uygunsuz sembol): yok
not: sembol ve gerekce toplamlari ortusur; toplanarak seans birlesimi aciklanmaz
not: referans IEX teshisiyle farkli erisim zamani; karsilastirma incelemede
sonuc: all_eligible
```

**Bu koşunun söylediği ve söylemediği:**

- Söylediği:
  - **Erişim:** bu paper hesabı, bu tarihsel aralık için SIP 1Min barı aldı.
    11 sembolün hepsi yanıtlandı ve hepsinde baseline barı geldi. Erişim
    reddi yok.
  - **Kalite:** SIP verisiyle 50 baseline seansının hepsi mevcut kalite
    politikasını geçti (`all_eligible`). Hiçbir sembolde bar-yok, açılış,
    kapanış ya da oran gerekçesi yok; tekrarlı zaman damgası yok.
  - **JSON'da kayıtlı değerler (Codex doğruladı):** 11 sembolün her birinde
    `sessions_with_bars = 50` ve `missing_fraction = 0.0`; bar-yok, açılış,
    kapanış, oran, uygunsuz ve tekrar sayıları 0. Oran, `round(eksik /
    beklenen, 6)` ile altı ondalığa yuvarlanmış bir **rapor değeridir**;
    log'daki "eksik 0.00%" onun iki ondalıklı yüzde gösterimidir.
  - **IEX teşhisiyle yan yana.** Aynı politika, aynı 11 sembol, aynı 50
    baseline seansı. İki sütun da Codex'in açtığı JSON'lardan; oranlar altı
    ondalıklı rapor değerleri:

    | | IEX (run `36502365666`, 2026-09-29) | SIP (run `37096896917`, 2026-10-03) |
    |---|---|---|
    | Uygun / uygunsuz baseline seansı | 40 / 10 | 50 / 0 |
    | AMD: uygunsuz seans; eksik oran | 10; 0,054821 | 0; 0,0 |
    | QQQ: uygunsuz seans; eksik oran | 1 (açılışta tam 1 dk); 0,011641 | 0; 0,0 |
    | Diğer 9 sembol: uygunsuz seans | 0 | 0 |

    IEX'te görülen eksiklerin SIP'te görülmemesi, bu eksiklerin IEX'e özgü
    olmasıyla **tutarlıdır**.
  - Codex iki ZIP'i de açtı (IEX `5ae3e3e0…`, SIP `3e90ef13…`; ikisi de
    kayıtlı hash'lerle eşit). Politika, 11 sembol, 1Min/raw ve 63/63/50/13
    sayımları iki JSON'da aynı; 40/10 → 50/0 karşılaştırması iki JSON
    üzerinden doğrulandı.
- Söylemediği:
  - **Neden.** İki erişim yaklaşık dört gün arayla yapıldı; eş zamanlı
    değil, sağlayıcı revizyonu mümkün. Gözlem, neden kanıtı değildir.
  - **Canlı veri.** Canlı SIP erişimini, canlı IEX/SIP eşdeğerliğini ya da
    abonelik ihtiyacını göstermez. Alpaca FAQ'taki "uç en az 15 dakika eski"
    kuralı yalnızca bu tarihsel aralık için gözlendi.
  - **Performans.** P&L hesaplanmadı. Kalite kapsamı işlem ya da dolum
    anlamı taşımaz.
  - **Fiyat ve hacim doğruluğu.** Ham barlar raporda yok; barların fiyat ve
    hacim doğruluğu yeniden ölçülmüş değildir.
  - **İzin.** Yeni veri kümesi, SIP üzerinde P&L ölçümü ya da holdout
    açılması için otomatik izin değildir.

**Karar (Codex, #17, 2026-10-08):**

- Run, log ve API düzeyindeki sonuç doğrulandı. ZIP/JSON doğrulaması da
  2026-10-08'de tamamlandı: kullanıcı mevcut ZIP'i iletti, yeni koşu yok
  (yukarıdaki tablo).
- SIP üzerinde bir P&L değerlendirmesi için önce yalnızca **tasarım ön
  raporu**. İçeriği:
  - aynı dönemde feed seçiminin kalite gözleminden **sonra** yapıldığı
    açıkça kaydedilir;
  - eski IEX tanımı değişmez; yeni çalışmanın kimliği ve soy ilişkisi,
    mevcut örtüşmezlik kuralıyla uyumlu olarak önerilir;
  - holdout kapalı kalır;
  - geçmiş SIP ile paper/canlı feed farkının nasıl ele alınacağı yazılır.
- Bu karar yeni veri indirme, P&L koşusu ya da holdout açma onayı değildir.
- Bu karşılaştırma tekrar koşulmaz.

### Hâlâ doğrulanmayan

- **Emir yaşam döngüsü.** Hiç emir gönderilmedi. Dolum, kayma, kısmi dolum,
  iptal, bracket bacaklarının davranışı — hiçbiri gerçek ortamda görülmedi.
- **Gözetimsiz seans.** Sistem bir kez bile canlı çalışmadı. Yeniden
  başlatma/mutabakat, çift emir engeli, gün sonu kapatma gerçek ortamda
  sınanmadı. Gözetimsiz paper kabulünden önce ayrıca iki gereksinim var:
  karar feed'i ile ölçüm feed'inin uyumu ve canlı karar yolunda eksik
  açılış barı kontrolü (§11.4).
- **Stratejinin kârlılığı.** ORB gerçek piyasa verisiyle bir kez bile
  backtest edilmedi: ilk ana ölçüm kalite kapısında, P&L'den önce durdu ve
  IEX üzerindeki bu tanım kalite nedeniyle kapatıldı (yukarıda). Aynı
  dönemin baseline'ında tarihsel SIP verisi kalite kapısını geçti
  (2026-10-03, yukarıda); SIP üzerinde P&L ölçümü ayrı tasarım ve karar
  ister. Sistemin
  sağlam olması, stratejinin kazandırdığı anlamına gelmez; bunlar ayrı iki
  sorudur ve ikincisine henüz dokunulmadı.

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

*Durum (2026-10-08):* bu tanım üzerindeki ölçüm denemesi kapatıldı (§11.2,
karar D). Tanım aktif tanımlardan çıkarıldı; bayt-bayt kopyası test
fixture'ında (§11.4).

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

### 11.2 Baseline kalite teşhisi — #17, 2026-09-28

İlk ana ölçüm kalite kapısında durdu (§7). Codex, P&L'siz ve yalnızca
baseline için ayrı bir kalite teşhisine geliştirme onayı verdi. Sözleşme:
`docs/designs/baseline-quality-diagnostic.md`.

**Kararlar:**

- Yeni spec yok. Dondurulmuş `DiagnosticTask`, ana tanımı hash'iyle kilitler.
  Kaynak kilidi anahtar ve SDK'dan önce, takvim sayımı (63/63/50/13) bar
  isteğinden önce kontrol edilir.
- Holdout barı istenmez. Kapsam dışı barlar hesaptan önce ayrılır; tekrar
  sayımı yalnızca baseline içindedir.
- İkinci bir kalite algoritması yoktur. Sembol toplaması `quality_summary`'de
  ortaktır; pilot özetinin schema 1 çıktısı birebir aynı kalır (testle sabit).
- `symbols_per_ineligible_session` histogramı çıktıya girer. Yaygınlığı
  gösterir; kök neden kanıtı değildir.
- Ham veri diske yazılmaz. `job_io` tarafsızdır; teşhis `baseline_job`'a ve
  performans katmanlarına bağlanmaz.

**Kapsam dışı:**

- ana ölçümün tekrarı;
- pilotların tekrarı;
- SIP, evren, dönem, eşik ya da tolerans değişikliği;
- emir.

Teşhis **bir kez** çalışır. Sonucu performans onayını kendiliğinden yeniden
açmaz; bir sonraki adım #17'de ayrı karardır. Gerçek teşhis, kod PR'ının son
head'i bağımsız incelenip birleştikten sonra kullanıcıdan tek tıkla istenir.

**Sonuç (2026-09-29):** teşhis bir kez koştu (run `36502365666`, §7).
Uygunsuz seansların hepsi AMD'de; QQQ'da bir seansta tam 1 dakikalık açılış
eksiği var. Codex kararıyla IEX ana ölçüm denemesi kapatıldı; sonraki adım,
ayrı kimlikli ve P&L'siz bir tarihsel SIP kalite karşılaştırmasının
tasarımıdır. Bu teşhis tekrar koşulmaz.

### 11.3 Tarihsel SIP kalite karşılaştırması — #17, 2026-09-29

IEX ana ölçüm denemesi kalite nedeniyle kapatıldı (§7, §11.2). Codex,
ayrı kimlikli ve P&L'siz bir tarihsel SIP erişim + kalite karşılaştırmasına
geliştirme onayı verdi. Bu karar, ölçüm dönemi kalite gözleminden **sonra**
alınmış bir araştırma kararıdır; gelecekteki bir SIP P&L değerlendirmesine
otomatik onay değildir. Sözleşme: `docs/designs/baseline-feed-comparison.md`.

**Kararlar:**

- Yeni veri kümesi yok: `config/datasets/` değişmez, örtüşmezlik ve "tek ana
  tanım" testleri gevşemez. Dondurulmuş `SIP_TASK`
  (`feedcmp-orb-baseline-2026q3-u11-sip-1`) ana tanımı hash'iyle ve
  tanımdaki feed'le (`iex`) kilitler.
- SIP, tanımda değil görevde yazılı açık bir override'dır. Kaynak hash'i
  override'ı kapsamaz; provenance, kaynak hash'i ile görevdeki override
  birliktedir. Görev hiç IEX isteği yapmaz; SIP reddedilirse başka bir
  feed'e dönülmez; ücretli plana geçiş yoktur.
- Kapsam, IEX teşhisiyle aynıdır: aynı 11 sembol, aynı 50 baseline seansı,
  aynı kalite politikası. Holdout barı hiçbir feed'den istenmez. Kilitler,
  bar toplama ve kalite toplaması teşhisle ortaktır (ikinci algoritma yok);
  IEX teşhisinin kimliği, alanları, notları ve çıktısı değişmez.
- Erişim kapısı ilk SIP isteğidir. Bar isteğinde HTTP 401/403 →
  `FAIL erisim` (gerçek kodla); kesin neden belirlenmez ve başarılı paper
  takvimi 403'ün SIP aboneliğinden olduğunu kanıtlamaz. Erişim reddinde
  artefakt yoktur. Ağ, diğer HTTP ve SDK dönüşüm hataları `FAIL indirme`.
- 200 ama boş yanıt erişim reddi değildir, kalite ölçüsüdür. Özetteki
  erişim alanı yalnız alınan yanıtları söyler; hepsi boşsa "kullanılabilir
  bar doğrulandı" sonucu çıkmaz. 11 sembolün hepsi yanıtlanmadan özet yoktur.
- Karşılaştırma araçta değil, incelemede yapılır: IEX özeti (§7, artefakt
  `11004953510`) ile SIP özeti yan yana konur. İki gözlem farklı erişim
  zamanlarına aittir; eş zamanlı değil, neden kanıtı değil.

**Yeniden koşu:** §11.1'deki istisna bu göreve **devredilmez**. Hangi adımda
olursa olsun her başarısızlık bir olaydır: run, job, head, attempt ve hata
kategorisi önce #17'ye yazılır; her yeniden koşu ayrı karardır. SDK taşıma
katmanının mevcut sınırlı HTTP tekrarı dışında yeni döngü ya da otomatik
tekrar yoktur.

**Kapsam dışı:** P&L, holdout, IEX'in yeniden indirilmesi, abonelik ya da
ücret kararı, evren/dönem/eşik değişikliği, emir. Tarihsel SIP'in başarısı
canlı IEX/SIP eşdeğerliğini ya da ORB'nin canlıya hazırlığını göstermez.

Gerçek koşu, kod PR'ının son head'i bağımsız incelenip birleştikten sonra
kullanıcıdan tek tıkla istenir.

**Sonuç (2026-10-03):** görev bir kez koştu (run `37096896917`, §7). Hesap
bu tarihsel aralık için SIP barı aldı (11/11 sembol); 50 baseline seansının
hepsi politikayı geçti. ZIP/JSON bağımsız doğrulaması 2026-10-08'de
tamamlandı (Codex; kullanıcı mevcut ZIP'i iletti, yeni koşu yok). Bu
karşılaştırma tekrar koşulmaz; SIP üzerinde P&L değerlendirmesi ayrı bir
tasarım ve karar ister (§7, Codex kararı 2026-10-08).

### 11.4 SIP üzerinde baseline değerlendirmesi: taslak tanım — #17, 2026-10-08

Codex kararları: #17 6050448152 ve 6051089595. Bu bir **kod geliştirme**
kararıdır. Veri indirme, P&L koşusu, holdout açma, ücretli abonelik ya da
emir izni değildir; bunlar tanımın ayrı son onayı ve sonraki yürütme
kararıyla değerlendirilir.

**Ne olduğu:**

- Tanım `orb-baseline-2026q3-u11-sip`, `draft`. Aynı dönem, aynı 11 sembol,
  aynı bölme ve kalite politikası; yalnızca feed `sip` (test denetler).
- **Araştırma değerlendirmesidir, bağımsız doğrulama dönemi değildir.**
  Dönem ve feed, aynı dönemin veri kalitesi gözlemlendikten sonra seçildi:
  IEX'te uygunsuz 10 seansın hepsi bir AMD seansıydı; tarihsel SIP'te 50
  baseline seansının hepsi uygun (§7). P&L, işlem ya da sinyal görülmedi;
  holdout seanslarının kalitesi de görülmedi.
- Başka bir dönem seçmek de bu etkiyi tamamen kaldırmazdı; o dönem de şimdi,
  gözlemden sonra seçilmiş olurdu. Asıl ayrım, gözlemlenmiş geliştirme
  verisi ile önceden kilitlenmiş değerlendirme arasındadır.
- §11.1 durma kuralı, aynı dönemi geçirmek için tanımın değiştirilip yeniden
  denenmesini yasaklar ve sonucu #17'ye bırakır. Bu taslak o tartışmadaki
  karardır; bu yüzden sonucu bağımsız doğrulama değil, araştırma
  değerlendirmesi sayılır. IEX tanımının P&L onayı tüketilmiş kalır (§11.2,
  karar D); SIP tanımı kendi ayrı onayını ister.

**P&L görülmeden dondurulanlar:**

- Strateji ve config, evren ve kalite kuralları `approved` commit'inde
  dondurulur. Bu bir kod kilidi değil, karar kuralıdır: ölçüm raporu kod
  commit'ini, ayarları ve ayar hash'ini taşır; inceleme bunları onay
  commit'indekilerle karşılaştırır.
- Sonuç görüldükten sonra aynı dönemde ayar değiştirip yeni "bağımsız"
  kanıt üretmek yasaktır. Olumsuz sonuç saklanmaz.

**Kapatılan IEX tanımı (#30 deseni):**

- `orb-baseline-2026q3-u11` aktif tanımlardan çıkarıldı. İçeriği ve hash'i
  **yeniden yazılmadı**: bayt-bayt kopyası
  `tests/fixtures/closed_datasets/` altında.
- Git kaydı bir test sabitinde ve testle doğrulanıyor: onay commit'i
  `221123f`, o yolda bulunduğu son main `f8dd495`, git blob, dosya hash'i
  ve tanım hash'i (`369f4e7f…`).
- Örtüşmezlik ve "tek aktif ana tanım" testlerinin denetimi değişmedi;
  yalnızca birinin açıklama metni güncellendi.
- Kapanmış iki tek seferlik araç (teşhis, SIP karşılaştırması) depo
  dizininde anahtar ve SDK'dan önce kaynak kilidinde durur (test). Eski
  kaynağın fixture kopyasıyla regresyon kanıtı sürer (smoke testleri).
- `baseline_job.MAIN_SPEC` SIP taslağına geçti. Taslak tanım indirme
  kapısında durur (test).

**Onay:** `approved` ayrı inceleme ve karar olarak gelir.

**Paper ve canlı çalışmayla ilişki:**

- SIP sonuçları, IEX ile karar veren gözetimsiz paper/canlı çalışmaya
  otomatik **taşınamaz**.
- Gözetimsiz paper kabulünden önce iki ayrı gereksinim:
  1. **Feed-uyum değerlendirmesi:** gerçek zamanda görülen IEX barları ile
     aynı günün tarihsel SIP barları karşılaştırılır. Kapsam: açılış
     penceresi, açılış aralığı ve sinyal uyumu. P&L hesaplanmaz; eşikler
     veri görülmeden sabitlenir.
  2. **Canlı karar yolunda eksik açılış barı kontrolü.**
- Salt okunur gölge gözlem (Faz 3) bu kanıtı üretmek için yapılabilir.
  Ölçüm için önceden uyum sonucu istenmez.

**Kayda gerçekmiş gibi geçmeyen, doğrulanmamış noktalar:** karar feed'inin
journal'a yazılması (config yorumu ve docstring söylüyor, uygulama
doğrulanmadı) ve paper dolumlarının hangi veriye göre simüle edildiği.
