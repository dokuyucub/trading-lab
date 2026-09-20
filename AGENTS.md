# Ekip Sözleşmesi

Bu projede birden fazla geliştirici çalışıyor (insan ve yapay zekâ ajanları).
Bu dosya ortak kuralları tanımlar. **Kod yazmadan önce oku.**

Diğer belgeler: mimari için `README.md`, git akışı ve sürüm geri alma için
`CONTRIBUTING.md`, ne değiştiği için `CHANGELOG.md`.

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

`main` üzerinde branch protection açık olmalı (Settings → Branches):
PR zorunlu, `quality` status check zorunlu, yöneticiler dahil.

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

## 7. Doğrulanmamış olan

Sistem **hiç gerçek Alpaca hesabına bağlanmadı**. Tüm testler çevrimdışı.
Sözleşme testleri (`test_alpaca_contract.py`) gerçek `alpaca-py` istemcisini
yerel bir sahte sunucuya karşı çalıştırıyor — yani Alpaca'nın kapısına kadar
her şey doğrulandı, Alpaca'nın kendi davranışı doğrulanmadı.

İlk gerçek bağlantıyı kuran kişi `tlab doctor` çıktısını bu dosyaya not düşsün.
