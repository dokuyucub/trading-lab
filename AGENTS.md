# Ekip Sözleşmesi

Bu projede birden fazla geliştirici çalışıyor (insan ve yapay zekâ ajanları).
Bu dosya ortak kuralları tanımlar. **Kod yazmadan önce oku.**

Diğer belgeler: mimari için `README.md`, git akışı ve sürüm geri alma için
`CONTRIBUTING.md`, ne değiştiği için `CHANGELOG.md`.

---

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

**Bağımlılık eklediysen `make lock` çalıştır ve `requirements.lock`'u commit'e
dahil et.** Sabitlenmemiş bir kurulum, aynı commit'in iki hafta arayla farklı
paket sürümleriyle kurulması demek. Bu bir kez yaşandı: `numpy` 2.5.3
yayınlandığı gün CI kodla ilgisi olmayan bir sebeple kırıldı.

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

`test_backtest.py` bunu rastgele yürüyüş verisiyle sınıyor: edge olmayan veride
pozitif beklenen değer üretilememeli.

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
| `journal/migrations/` | Numara benzersiz ve arasız. Yeni göç eklemeden önce `git fetch` yap ve en yüksek numarayı kontrol et. **Uygulanmış bir göç dosyası asla düzenlenmez** — değişiklik her zaman yeni bir dosyadır. |
| `CHANGELOG.md` | Sadece `[Yayınlanmamış]` bölümüne ekle, kendi maddeni en alta koy. Çakışırsa ikisini de tut. |
| `config/base.yaml` | Risk limitlerini tek taraflı değiştirme; PR açıklamasında gerekçesini yaz. |
| `requirements.lock` | Elle düzenlenmez. `make lock` ile üretilir. Çakışırsa `main`'inkini al, kendi bağımlılığını ekle, yeniden üret. |
| `core/types.py` | Herkesin tabanı. Alan eklemek serbest, alan silmek/yeniden adlandırmak PR'da tartışılır. |

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
