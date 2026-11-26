# Onay Kurulu — PR #63, teslim `ae39a3b` (7db8bea, f017e88, ae39a3b)

Tarih: 2026-11-26. İncelenen: `git diff 2876da0 ae39a3b` (4 dosya, +552/−52), ayrı çalışma kopyasında, ağsız.
Yazardan bağımsız; aşağıdaki her satır kurulun kendi koşusu ya da okumasıdır.

## Karar: ONAY, notlarla

Kod değişikliği istenmiyor. f017e88'de fail-open bir yol bulunmadı; yeni davranışların hepsi daha fazla gün
kapatma yönünde. Push'tan önce tek koşul süreçle ilgili (N1): f017e88 açıklanan plandan sapıyor, bu #63'e yazılmalı.

## Kontrol listesi

| Madde | Sonuç | Kanıt (kurul koştu / okudu) |
|---|---|---|
| Kapsam planla aynı | GEÇTİ, notla | ÖN RAPOR 7175465803 GitHub'dan okundu. 7db8bea üç maddeyle örtüşüyor. f017e88 plan dışı üç ek taşıyor (aşağıda "Kapsam"); kaynağı ofisin Hata Avı notları N2/N3. |
| Değişmez kısıtlar | GEÇTİ | Yalnız 4 dosya; iş akışı, config, kilit dosyası yok. Diff'te anahtar, URL, bakiye, fiyat taraması boş. `skip`/`xfail` yok; tek `noqa` (S608) önceden vardı. Protokole yeni broker çağrısı eklenmedi. |
| ruff / mypy / ilgili testler | GEÇTİ | ae39a3b'de: `ruff check` temiz; izlenen dosyalarda `ruff format --check` ve `mypy` temiz (tek uyarı kaynağı izlenmeyen `tests/test_scratch_r63.py`). Dört dosya **380 geçti** (`test_entry_cancel_race.py` 209). |
| Tam `make check` sayılarıyla | GEÇTİ, notla | Günlük: ruff/format(144)/mypy(117) temiz; **1751 geçti, 6 atlandı, 1 kırmızı**, kapsama %91,01. Tek kırmızı pin testi; kurul tek başına koştu, neden ağaç özeti farkı. Günlük SHA taşımıyor; ae39a3b'de 1760 test toplanıyor = 1758 + ae39a3b'nin 2 testi (tutarlı). ae39a3b'de tam süit koşulmadı (yalnız test eklendi). |
| Yeni davranış testle sabit, mutasyonla gösterilmiş | GEÇTİ | Günlükte 61 satır: 60 yakalandı, X12 kaçtı. Kurul ae39a3b'de X12, Y1, Y2, X9'u elle koştu: dördü de kırmızı (X12 artık `..._for_a_row_adopted_from_the_journal[ttl]`). Kendi 8 mutantı: 7 yakalandı (aşağıda). |
| Hata Avı bulguları kapalı ya da kayıtlı | GEÇTİ, notla | N3: `runner.py:772-778` + test; N2: `runner.py:631,642` + test; N4: §4 sınır (iv); Gözlem 1: okunamayan an fail-closed + test. **Gözlem 2 kayıtsız** (N3). |
| Doğrulanamayanlar yazılı | GEÇTİ | Bu raporda "Doğrulanmadı" başlığı. |

## Kapsam

- **Plan dışı (f017e88), TESLİM'de ve #63'te açıkça söylenmeli:**
  1. Plan (iii): "giriş okunabiliyorsa bugünkü akış sürer ... yeniden gönderilir". Teslim: devralınan istekte **tek**
     yeniden gönderim; o da hata verirse gün o turda kapanır.
  2. Giriş `pending_cancel`/terminal okununca istek aynı turda doğrulanır (`_cancel_outcome`); iki eski testin beklentisi değişti.
  3. Okunamayan journal anı önceki seans sayılır.
  Ayrıca 7db8bea'da (i) kontrolü plandaki "yok (kanıtlı)" yerine "yok ya da bilinmiyor"da da çalışıyor (commit mesajında var).
- **Değişen üç beklenti — hiçbiri zayıflatma değil:**
  - `halt_on_an_unprotected_fill`: `in ("cancel_requested","cancel_pending")` → `== "cancel_pending"`. Daraltma; reddedilen
    iptalde giriş `filled` okununca doğrulama yapılmasının doğrudan sonucu.
  - `test_a_cancel_whose_reply_was_lost_is_not_sent_again`: ilk tur `cancel_requested` → `cancel_pending`. Testin özü
    (ikinci iptal gitmez, `cancelled_ids` tek) aynen duruyor. "Ulaşmayan istek kabul sayılmaz" iddiası
    `test_an_unreached_cancel_is_sent_again`de sabit (kurulun O1 mutantı orada kırmızı). `_confirm_cancel`in ACK dalı
    hâlâ sınanıyor (P1d ve kurulun O5'i `..._crash_around_the_cancel...[after_broker]`de kırmızı).
  - `test_an_adopted_unconfirmed_old_cancel_takes_the_safe_close_path`: 7db8bea'da eklenmiş, f017e88'de kurulumu
    değişmiş (yardımcı artık `cancel_requested` bırakmıyor). Eski çıkış emri iddiası `cancel_pending` varyantlarında sürüyor.
- Silinen test yok (diff'te testlerden çıkan yalnız iki `assert` satırı, ikisi de yukarıda).

## f017e88 derinlemesine

- **(a) Okunan `pending_cancel`/terminal isteği doğrular — iptal ulaşmamışken giriş canlı kalabilir mi?** Bu yoldan hayır.
  Terminal okunan giriş artık dolamaz; `pending_cancel` ancak bir iptal brokera ulaştıysa görünür. O1 (her okunan durum
  doğrular) yakalanıyor. Kalan tek açık önceden vardı, bu commit'le büyümedi: `pending_cancel` sonradan aktife dönerse
  satır `cancel_pending` kalır, ikinci iptal gitmez; sonda (PROBE-B) 4 tur `halted=False`, `entries_blocked=True`,
  tek iptal, giriş `new`. Sınırı: giriş engeli, her tur koruma ölçümü, gün sonu kapanışı, `DAY` emir.
- **(b) Olağan yeniden başlatma hatasız günde günü kapatır mı?** İptali broker kabul ettiyse (`cancel_pending`) hayır.
  Kapanması için iki koşul birlikte gerekir:
  1. Journal'da `cancel_requested` kalmış olmalı: önceki süreç iptal çağrısının içinde kesildi, ya da çağrı hata verdi
     ve giriş o turda ACK okunmadı, ya da `cancel_pending` yazımı başarısız oldu.
  2. Yeni sürecin ilk turunda `get_order` bir kez hata verir **ya da** giriş aktif okunur ve tek yeniden gönderim hata
     verir. Bağdaştırıcı her istisnayı `BrokerError` yapar (`alpaca_broker.py:196-203, 280-286`); "emir zaten doldu"
     reddi de buna dahil.
  Sondalar: (PROBE-D) hesap düz, giriş brokerda zaten `canceled`, tek okuma hatası → gün kapanır. (PROBE-A) giriş
  okuma ile yeniden gönderim arasında **stopla tam kapsanarak** dolar → yeni süreçte gün kapanır, kapsanan pozisyon
  kapatılır, satır `cancel_requested` kalır; aynı süreçte aynı dizi `filled` yazar, gün açık kalır. Yön fail-closed.
  Belgede kural yazılı (§4, sınır ii–iii); **bedeli yazılı değil** (N2).
- **(c) Sağlıklı satır `None` verir mi?** Hayır. `submitted_at TEXT NOT NULL` (001:64, 002:32); tek yazan
  `JournalWriter._now()` = `clock.now().astimezone(UTC).isoformat()` (`writer.py:77-78, 171`); 3.12 `fromisoformat` bunu
  her zaman çözer. `None` yalnız bozuk metinde. Bellekteki satır broker zamanını taşır; O7 bunu sabitliyor.

## Mutantlar (ae39a3b, üç dosya, `-x`)

| Mutant | Sonuç |
|---|---|
| X12, Y1, Y2, X9 (betikten) | 4/4 yakalandı |
| O1 her okunan durum isteği doğrular | yakalandı |
| O2 yalnız terminal doğrular / O3 yalnız `pending_cancel` doğrular | yakalandı / yakalandı |
| O4 devralınan istek yeniden gönderim ulaşsa da kapatır | yakalandı |
| O5 devralınan istek ACK okunsa da kapatır | yakalandı |
| O6 pozisyon bilinmiyorsa eski çıkış emri aranmaz | yakalandı |
| O7 bellekteki izde gönderim anı taşınmaz | yakalandı |
| O8 bellekteki izde journal yönü taşınmaz (`side=None`) | **KAÇTI** (266 yeşil) |

O8 yalnız süreç içinde izlenip seans değiştiren satırda fark eder ve `None` daha geniş sahipsiz tanımı demektir
(fail-closed yön). Test boşluğu, engel değil.

## Bilinen sınırlar (§4)

| Sınır | Dürüst mü | Yön / sınır | Ertelenebilir mi |
|---|---|---|---|
| (i) doğrulanmış + kalıcı okunamayan giriş girişleri engeller | Evet | fail-closed | Evet |
| (ii) doğrulanmamış + kalıcı okunamayan giriş günü kapatır | Evet; aynı süreçte her yeni seansta da olur | fail-closed | Evet |
| (iii) süreç içi sınır 3; yeniden başlatmada devralma kuralı | Evet | en çok 3 tur + yeni sürecin ilk turu | Evet |
| (iv) iz kapandıktan sonraki turda görünen pozisyon ölçülmez | Evet (N4 ile aynı) | fail-open, dar: `canceled`/0 **ve** güncel boş okuma sonrası; gün sonu kapanışı ve zarar sınırı sınırlar | Evet; v2 işi |

Push'tan önce düzeltilmesi gereken sınır yok.

## Belge ve commit mesajları

§4 metni üç commit'in koduyla uyumlu; commit mesajları diff'i doğru anlatıyor, ae39a3b yalnız test. Eksikler N2–N4.

## Doğrulanmadı

- Tam süit ae39a3b'de koşulmadı. Günlüklerin hangi SHA'da üretildiği dosyadan kanıtlanamıyor (yalnız test sayısı tutarlı).
- 61 mutantın 57'si yeniden koşulmadı; günlükten okundu.
- Alpaca'da `pending_cancel`in aktife dönüp dönmediği ve reddedilen iptalin hangi hata koduyla geldiği (canlı çağrı yok).

## TESLİM'e taşınacak notlar

- **N1 (push öncesi, süreç):** f017e88'in üç eki ve (iii)'teki sapma #63'e kısa bir ek ÖN RAPOR olarak yazılsın
  (`AGENTS.md` "önce niyet"); TESLİM aynı listeyi taşısın.
- **N2:** devralma kuralının bedeli açık yazılsın: yeniden başlatma + kalmış `cancel_requested` + tek geçici okuma
  hatası, ya da okuma ile yeniden gönderim arasında dolan (kapsansa bile) giriş günü kapatır ve pozisyonu kapatır.
  §4'e bir "Bedeli" cümlesi sonraki commit'te. İyileştirme yönü: başarısız yeniden gönderimden sonra girişi bir kez
  okuyup ACK ise doğrulamak.
- **N3:** Hata Avı Gözlem 2 kayda geçsin: okunan, önceki seanstan, sıfır dolumlu giriş + düz hesap + tek çıkış emri →
  satır `canceled`, emir kalır. v2 denetiminin kapsamı.
- **N4 (kozmetik):** devralınan istekte not "(3 deneme)" diyor, deneme bir; `runner.py:261-268`de
  `_unconfirmed_cancels` açıklaması `_adopted_cancels`in altında kalmış; `journal_instant` `_parse_ts` ile aynı işi
  yapıyor; §4 "journal'dan bakılır" diyor, bellekteki satır broker zamanını kullanıyor.
- **N5:** O8 test boşluğu; `pending_cancel` → aktif dönüşü (PROBE-B) "Doğrulanmadı" listesine.
