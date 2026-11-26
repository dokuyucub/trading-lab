# S1 — Uygulama: B1, journal hatası kill-switch'in ve gün sonu kapanışının önüne geçmesin

Tarih: 2026-11-26 · Dal `claude/journal-hata-kapanis`, taban #63 head `8f855cc` · Çalışma kopyası `wt-s1-b1`.
Push, GitHub yazımı, iş akışı, broker ya da ağ çağrısı yok; testler sahte broker ile çevrimdışı. Sayılar sentetiktir.

## 1. Sonuç

- **B1 kapandı** (turun başındaki defter işleri için; yazma ve okuma hatası). `orders`/`fills` yazılamazken zarar sınırı turunda ve
  kapanış penceresinde pozisyon kapatılıyor, o turda yeni giriş gitmiyor, tur hata fırlatmıyor.
- Commit `ad8a415` (push edilmedi). İki dosya: `src/tlab/engine/runner.py` +37/−6, `tests/test_kill_switch_durability.py` +379/−2.
  *(Düzeltme `2d714ee`: "tek commit" artık doğru değil; dalda üstüne takip commit'i `2d714ee` var, §9. Bu bölümün sayıları `ad8a415` içindir.)*
- Hedefli üç dosya: 287 geçti (taban 266 + 21 yeni). `ruff check` temiz, `ruff format --check` 144 dosya, `mypy` 117 dosyada hata yok.
- 22 el mutantının 22'si öldürüldü. Tam süit: 1774 geçti, 6 atlandı, 1 kaldı (beklenen kampanya pin testi).
- Mevcut hiçbir testin beklentisi değişmedi. Yönetimin bilmesi gereken iki bedel (§7.1, §7.2) ve kapsam dışı sınırlar §7'de.
  *(Düzeltme `2d714ee`: §7.2 bedeli kapandı; kalan bedel §7.1.)*

## 2. Değişiklik

`run_once` başındaki iki çağrı (`_resolve_unconfirmed`, `_reconcile`) yeni `_bookkeeping` adımına taşındı (`runner.py:405`). Her biri ayrı
`try/except JournalError` içinde: hata olursa `log.exception` ve `_block_entries(result, "journal hatasi: …")`. Ardından kill-switch,
`must_flatten` ve izlenen iptaller koşulsuz çalışır; `entries_blocked` evren değerlendirmesini mevcut dönüş noktasında keser. Adım sırası
değişmedi; journal sağlamken yol aynıdır. Yakalanan tip yalnız `JournalError`: `JournalWriter` ve `journal/queries.py` her
`sqlite3.Error`'ı buna sarıyor. İki adım ayrı korunur: emir kesinleştirme yazılamazsa gerçekleşme kaydı yine yazılır.

## 3. Tasarım kararları

**Ölçüt 4 — tur hata fırlatmaz.** Hata üç yerde görünür: ERROR düzeyinde iz (`log.exception`), `LoopResult.entries_blocked` ve
`summary()` satırına düşen not. *(Düzeltme `2d714ee`: dördüncü yer `LoopResult.journal_error`.)* `run_once` çağıranlarına göre
*(düzeltme `2d714ee`: "Bu seçimle" sütunu `ad8a415` anıdır, satır numaraları da; son üç satır değişti, üstü çizili. Güncel tablo §9)*:

| Çağıran | Yeniden fırlatsaydım | Bu seçimle |
|---|---|---|
| `run_forever` (`runner.py:291`) | tur başarısız sayılır, bekleme en çok 8 kata çıkar | tur normal aralıkta koşar; not INFO özetinde, iz ERROR'da |
| `cli run --once` (`cli.py:335`) | `main` "HATA" basar, çıkış kodu 1 | ~~**çıkış kodu 0**, not özet satırında~~ → `2d714ee`: özet basılır, sonra "HATA", çıkış kodu 1 |
| `backtest/engine.py:359` | koşu durur | ~~**koşu sürer**; motor `LoopResult`'ı atıyor, iz yalnız log'da~~ → `2d714ee`: koşu durur (turun güvenlik adımlarından sonra) |
| `shadow_job.py:555` | `failed += 1` | ~~tur `called` sayılır~~ → `2d714ee`: `failed` sayılır |

Gerekçe: (1) Güvenlik adımlarından sonra fırlatmak, kalıcı journal hatasını `run_forever`'da 8 katlık beklemeye çevirir (B5): 60 sn'lik
döngüde koruma kontrolü 8 dakikada bire düşer; 10 dakikalık kapanış penceresine bir, en çok iki deneme sığar, `_flatten_all` ise iptal
kesinleşmezse ikinci tura ihtiyaç duyar. Düzeltmenin amacını geri alırdı. (2) `run_once` içindeki benzer journal hataları aynı kanalı
kullanıyor ("gun durumu okunamadi", "izlenen iptaller journal'dan okunamadi", "iptal niyeti yazilamadi", "kill-switch karari journal'a
yazilamadi"); yeni kanal icat edilmedi. *(Düzeltme `2d714ee`: yalnız iki defter işi için yeni kanal eklendi, `journal_error`; sayılan dört
hata hâlâ yalnız not ve iz kanalında.)* (3) `unattended-paper.md` §4 kuralı: girişte fail-closed, korumada fail-open.

**Ölçüt 6 — hata kill-switch ya da kapatma yolunun içindeyse.** Kod değişikliği gerekmedi; mevcut yol karşılıyor:
- `_flatten_all` journal'a hiç dokunmaz (yalnız broker). `_check_kill_switch` gün durumu okumasını `(sqlite3.Error, JournalError)` için
  korur. Karar yazımı `_record_halt` içinde korunur: yazılamazsa karar `_unpersisted_halts` belleğinde tutulur, not düşer, kapatma gider.
- Birleşik durum yeni testte (`test_a_read_only_journal_still_closes_on_a_breached_loss`): bütün journal salt okunur, defter işi ve
  `daily_state` yazımı birlikte hata verir. İlk turda iptal + kapatma; hesap toparlansa da ikinci turda gün kapalı, kapatma yeniden gider.
  Sınır (önceden yazılı): yazılamayan karar yalnız süreç belleğindedir; süreç yeniden başlarsa kaybolur.

## 4. RED ve GREEN

Kurulum (`turn_with_bookkeeping`): her tura iki defter işi bırakılır: journal'a düşmemiş, önceki seanstan bir gerçekleşme (`fills` INSERT)
ve `submitting` kalmış, brokerda görünen bir giriş (`orders` UPDATE). Hata türleri: tabloya özel `RAISE(ABORT)` tetikleyicisi (`fills`,
`orders`), `PRAGMA query_only = ON` (`salt-okunur`), `DROP TABLE orders` (`orders-okunamaz`).

**RED** (yeni testler + değişiklikten önceki `runner.py`; `red-b1.log`): `16 failed, 16 passed`. 16'sı da `runner.run_once()` satırında
`JournalError` ile düşüyor; iddia satırlarına ulaşılmıyor (`…` = `test_a_journal_failure_`):
- `…does_not_stop_the_loss_limit[fills | orders | orders-okunamaz]`, `…does_not_stop_the_end_of_day_flatten[fills | orders | salt-okunur | orders-okunamaz]`
- `…blocks_new_entries_for_the_turn[fills | orders | salt-okunur]`, `…is_logged_with_its_cause[fills | orders]`, `…cancels_the_pending_entry_like_any_blocked_turn`
- `test_a_read_only_journal_still_closes_on_a_breached_loss`, `test_a_failed_order_confirmation_does_not_skip_the_fill_record`, `test_bookkeeping_resumes_once_the_journal_recovers`
```
writer.py:275  JournalError: Gerceklesme kaydedilemedi (yazilmamis-dolum): disk dolu              6 test
writer.py:252  JournalError: Emir guncellenemedi (tlab-…): disk dolu                              5 test
writer.py:252  JournalError: Emir guncellenemedi (tlab-…): attempt to write a readonly database   3 test
queries.py:73  JournalError: Kesinlesmemis emirler okunamadi: no such table: orders               2 test
```
RED'de yeşil kalan 16: mevcut 11 test, `test_an_unexpected_error_in_bookkeeping_is_not_swallowed[confirm_order | record_fill]` ve üç kontrol
(`test_a_healthy_journal_…_as_before`: zarar sınırı, kapanış, giriş). Kontroller aynı senaryoyu sağlam journal ile kurar, önce de sonra da geçer.

**GREEN:** `test_kill_switch_durability.py` 32 geçti; üç hedef dosya 287 geçti (önce 266). Not: yeni testlerimden birinin ilk beklentisi yanlıştı
(hatalı turda bekleyen giriş `new` kalır sanmıştım; engelli tur onu iptal ediyor). Düzelttim, davranışı ayrı testle sabitledim (§7.1).

## 5. Mutantlar

Her mutant tek başına uygulandı, test dosyası koştu, dosya geri alındı (son hal amaçlanan dosyayla aynı; `mutants-b1.log`). "İki adım":
çözümleme ve mutabakat koruması için ayrı ayrı. Parantez: düşen test sayısı. Sağ kalan yok (iki koşu: önce 20, son test kümesiyle 22).

| # | Mutant | Sonuç |
|---|---|---|
| M01, M02 | hatadan sonra `_block_entries` yok (iki adım) | öldü (5, 4) |
| M03, M04 | hatadan sonra kill-switch / gün sonu kapanışı atlanır | öldü (4, 5) |
| M05, M06 | `log.exception` yok (iki adım) | öldü (1, 1) |
| M07, M08 | güvenlik adımlarından ÖNCE yeniden fırlatma (iki adım) | öldü (11, 10) |
| M21, M22 | güvenlik adımlarından SONRA yeniden fırlatma (kapanış / kill-switch turu) | öldü (7, 5) |
| M09 | tek `try`: çözümleme hatası mutabakatı atlatır | öldü (1) |
| M10, M11 | `except Exception` (iki adım) | öldü (1, 1) |
| M16 | yanlış tip: `except sqlite3.Error` | öldü (11) |
| M12, M15 | hatadan sonra erken `return` / hata `pass` ile yutulur | öldü (9, 6) |
| M13, M14 | koruma kaldırılır, eski davranış (iki adım) | öldü (10, 11) |
| M17, M18 | `trades_recorded` yazılmaz (üç hedef dosyayla) / defter işleri hiç çalışmaz | öldü (1, 20) |
| M19, M20 | not düşmez, yalnız bayrak / hatalı turda bekleyen giriş iptal edilmez | öldü (3, 2) |

## 6. Tam süit

Bir kez koştu (14:37–14:58 UTC, 21 dk 27 sn; `makecheck-b1.log`): **1781 test: 1774 geçti, 6 atlandı, 1 kaldı.** Kapsam %91,27 (eşik %80);
`engine/runner.py` %94, `_bookkeeping` satırlarında eksik yok. Tek kırmızı, yönetimin bildirdiği beklenen test:
`tests/test_shadow_job.py::test_the_campaign_identity_is_pinned_to_the_implementation_tree` (`makecheck-63n.log`'da da kırmızı).
Sayım notu: komuttaki `-q` ile `addopts`'taki `-q` birleşince pytest özet sayı satırını basmıyor; sayılar logdaki ilerleme karakterlerinden
(1774 `.`, 6 `s`, 1 `F`) ve `--collect-only` çıktısından (1781) alındı. Süit commit'ten önce koştu; iki dosyanın sha256'sı commit'tekiyle aynı.

## 7. Bilinen sınırlar ve bedeller

1. **Bekleyen girişler de iptal edilir.** `entries_blocked` mevcut kuralı taşır (`every_age`): hatalı turda, pozisyonu olmayan sembollerdeki
   kendi bekleyen girişlerimiz yaşına bakılmadan iptal edilir. Geçici tek bir kilit hatası sinyali ve bekleyen girişi kaybettirebilir. Yön güvenli; testle sabit.
2. **Çıkış kodu ve backtest.** ~~`run --once` bu hatada 0 döner; backtest motoru journal hatasında artık durmaz ve `LoopResult`'a bakmaz.
   İkisi de izinli dosyaların dışında (`cli.py`, `backtest/engine.py`); dokunmadım. Öneri: çağıranlar `entries_blocked`'ı denetlesin.~~
   *Düzeltme `2d714ee`: kapandı. `run --once` 1 döner, backtest durur, gölge işi turu `failed` sayar; üçü de `journal_error`'a bakıyor (§9).*
3. **Güvenlik adımlarından sonraki journal okuması.** `orders` okunamıyorsa normal turda `_cancel_stale_entries` (`runner.py:583`; `2d714ee`'de 598) hâlâ
   `JournalError` fırlatır (B5 beklemesi; karalama testiyle görüldü). Zarar sınırı ve kapanış turu etkilenmez; yazma hatasında tur hiç fırlatmıyor (testte).
4. **Journal dışı hatalar** turu hâlâ güvenlik adımlarından önce bitirir: `get_account`/`get_positions` `BrokerError`'ı (#63 raporu, madde
   (c)) ve programlama hataları. Defter işlerinde bu sınır bilinçlidir ve testle sabittir; genişletmek ayrı karardır.
5. **Süreç başlangıcı.** Journal süreç açılırken yazılamıyorsa `start_run` hata verir ve döngü hiç başlamaz (kod okunarak).
6. `_reconcile`'da `record_trade` yazılıp `mark_order_closed` yazılamazsa sonraki tur yeniden denemez (önceden de böyleydi; kod okunarak).
7. `docs/designs/unattended-paper.md` §4'e "Açık 3" kaydı eklenmedi (dosya izinli listede değil); ayrı doküman değişikliği gerekir.

## 8. Doğrulanmadı

- Gerçek disk dolu, salt okunur dosya sistemi ya da `database is locked`: yalnız tetikleyici, `query_only` ve `DROP TABLE` ile benzetildi.
  Kilitli veritabanında her yazmanın sqlite bekleme süresi kadar turu geciktirmesi ve kalıcı hatadaki log hacmi ölçülmedi.
- `run_forever` uçtan uca (bekleme, kadans) ve §3 tablosundaki `--once` çıkış kodu, backtest, gölge işi satırları: testi yok; kod okumasına dayanıyor.
  *(Düzeltme `2d714ee`: dördünün de testi var, §9; `run_forever` yalnız sahte `sleep` ile üç tur.)*
- `dry_run` + journal hatası: karalama ile bir kez denendi (tur döndü, giriş yok); commit'li testi yok.
- Gerçek broker davranışı (yalnız `FakeBroker`), CI (`quality` işi; push edilmedi) ve araçla tam mutasyon taraması (mutantlar elle seçildi).

## 9. Ek: çağıran sözleşmesi (`2d714ee`)

`ad8a415`'ten sonra `run_once` defter işi hatasında normal döndüğü için üç çağıran hatalı turu başarı sayıyordu (§7.2). Güvenlik kazanımı
korunarak görünürlük geri geldi. Tek yeni commit `2d714ee` (`ad8a415`'in üstünde, push edilmedi): 8 dosya, +404/−7. `runner.py` +17/−2,
`backtest/engine.py` +6/−1, `cli.py` +6/−1, `shadow_job.py` +8/−2, dört test dosyası +367/−1. `LoopResult.journal_error` eklendi; `_bookkeeping`
yakaladığı İLK `JournalError` nesnesini oraya koyar. `run_once`'ın geri kalanı ve `run_forever` değişmedi.

| Çağıran | `ad8a415` öncesi | `ad8a415`'te | Şimdi (`2d714ee`) |
|---|---|---|---|
| `run_forever` | tur başarısız; bekleme 8 kata kadar | normal aralık; güvenlik adımları çalışır | aynı; alana bakmaz (testle sabit) |
| backtest | koşu `JournalError` ile durur | koşu sürer, rapor üretir | durur, o turun güvenlik adımlarından sonra |
| `run --once` | tur özeti yok; "HATA: …", çıkış 1 | tur özeti; çıkış 0 | tur özeti, sonra "HATA: …", çıkış 1 |
| gölge işi | `failed` | `called` | `failed` |

`main` yolu (okundu, testte): hata `cmd_run`'dan çıkar; `finally` koşuyu kapatıp koşu özetini basar; `main` stderr'e `HATA: <mesaj>` basar, 1 döner.
**RED** (`red-b1b-new.log`; `ad8a415` kaynağı + 14 yeni test): `12 failed, 2 passed`. 8 runner testi `AttributeError: 'LoopResult' object has no
attribute 'journal_error'`; cli `assert 0 == 1`; iki backtest testi `Failed: DID NOT RAISE JournalError`; gölge `{'failed': 0} != {'failed': 1}`.
RED'de yeşil iki test bilinçli: `--once` sağlam journal kontrolü ve `run_forever` kadans testi (davranış `ad8a415`'te doğruydu; test sabitliyor).
**GREEN:** 14/14 (`green-b1b-new.log`); dört test dosyası + `test_runner.py`: `1 failed, 176 passed` (kalan: kampanya pin testi). `ruff check`
temiz, `ruff format --check` 144 dosya, `mypy` 117 dosyada hata yok.

| # | Mutant (`mutants-b1b.log`; tek tek, sonra geri alındı; parantez: düşen test) | Sonuç |
|---|---|---|
| N01–N03 | alan hiç / yalnız çözümlemede / yalnız mutabakatta doldurulmaz | öldü (8, 3, 5) |
| N04, N16 | ikinci hata ilkini ezer / alan süreçte kalıp sonraki tura taşınır | öldü (1, 1) |
| N05–N08 | backtest fırlatmaz / başka nesne fırlatır; cli fırlatmaz / özeti basmadan fırlatır | öldü (2, 1, 1, 1) |
| N09, N10 | gölge işi `called` sayar / hem `called` hem `failed` sayar | öldü (1, 1) |
| N11, N17 | `run_forever` alanı fırlatır (bekleme uzar) / tur alanı doldurup yeniden fırlatır | öldü (1, 17) |
| N12–N15 | kapsam: gün durumu, kill-switch kararı, iptal niyeti, izlenen iptaller de alanı doldurur | öldü (2, 1, 1, 1) |

17/17 öldü, sağ kalan yok. **Tam süit** (bir kez, 22:03–22:22 UTC, `makecheck-b1b.log`): `1 failed, 1788 passed, 6 skipped in 1154.44s (0:19:14)`;
kapsam %91,48. Tek kırmızı: `tests/test_shadow_job.py::test_the_campaign_identity_is_pinned_to_the_implementation_tree` (beklenen). Sapma: komuttaki
`-q` çıkarıldı; `addopts`'taki `-q` ile birleşince `-qq` olup özet satırını bastırıyor (denendi). Süit commit'ten önce koştu; 8 dosyanın sha256'sı aynı.
**Beklentisi değişen mevcut test:** yok; mevcut test satırlarına dokunulmadı (tek silinen satır, genişleyen bir import).
**Sonraki olası iş (bilinçli kapsam dışı):** turun not düşüp geçtiği diğer journal hataları alanı doldurmuyor, backtest ve `--once` bunlarda hâlâ başarıyla
biter: "gun durumu okunamadi", "bugunku emir kayitlari okunamadi", "izlenen iptaller journal'dan okunamadi", "iptal niyeti yazilamadi", "kill-switch
karari journal'a yazilamadi", "<sembol>: journal yazilamadi" (karar/emir kaydı), `_write_order_status` (yalnız iz). §7.3 de sürüyor.
**Doğrulanmadı:** gerçek disk dolu/kilitli veritabanı (yalnız tetikleyici, `query_only`); `run_forever` gerçek beklemeyle (sahte `sleep`, üç tur); `tlab backtest`
uçtan uca (`Backtest.run` sınandı; `main`'e düşmesi kod okuması); gölge işinde tek tur, `orders` yazımı; N02–N17 çalışma kopyasının birebir kopyalarında koştu; CI.
