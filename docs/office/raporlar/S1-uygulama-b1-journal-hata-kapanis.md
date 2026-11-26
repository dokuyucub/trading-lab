# S1 — Uygulama: B1, journal hatası kill-switch'in ve gün sonu kapanışının önüne geçmesin

Tarih: 2026-11-26 · Dal `claude/journal-hata-kapanis`, taban #63 head `8f855cc` · Çalışma kopyası `wt-s1-b1`.
Push, GitHub yazımı, iş akışı, broker ya da ağ çağrısı yok; testler sahte broker ile çevrimdışı. Sayılar sentetiktir.

## 1. Sonuç

- **B1 kapandı** (turun başındaki defter işleri için; yazma ve okuma hatası). `orders`/`fills` yazılamazken zarar sınırı turunda ve
  kapanış penceresinde pozisyon kapatılıyor, o turda yeni giriş gitmiyor, tur hata fırlatmıyor.
- Tek commit `@@SHA@@`. İki dosya: `src/tlab/engine/runner.py` +37/−6, `tests/test_kill_switch_durability.py` +379/−2.
- Hedefli üç dosya: 287 geçti (taban 266 + 21 yeni). `ruff check` temiz, `ruff format --check` 144 dosya, `mypy` 117 dosyada hata yok.
- 22 el mutantının 22'si öldürüldü. Tam süit: @@FULL@@.
- Mevcut hiçbir testin beklentisi değişmedi. Yönetimin bilmesi gereken iki bedel (§7.1, §7.2) ve kapsam dışı sınırlar §7'de.

## 2. Değişiklik

`run_once` başındaki iki çağrı (`_resolve_unconfirmed`, `_reconcile`) yeni `_bookkeeping` adımına taşındı (`runner.py:405`). Her biri ayrı
`try/except JournalError` içinde: hata olursa `log.exception` ve `_block_entries(result, "journal hatasi: …")`. Ardından kill-switch,
`must_flatten` ve izlenen iptaller koşulsuz çalışır; `entries_blocked` evren değerlendirmesini mevcut dönüş noktasında keser. Adım sırası
değişmedi; journal sağlamken yol aynıdır. Yakalanan tip yalnız `JournalError`: `JournalWriter` ve `journal/queries.py` her
`sqlite3.Error`'ı buna sarıyor. İki adım ayrı korunur: emir kesinleştirme yazılamazsa gerçekleşme kaydı yine yazılır.

## 3. Tasarım kararları

**Ölçüt 4 — tur hata fırlatmaz.** Hata üç yerde görünür: ERROR düzeyinde iz (`log.exception`), `LoopResult.entries_blocked` ve
`summary()` satırına düşen not. `run_once` çağıranlarına göre:

| Çağıran | Yeniden fırlatsaydım | Bu seçimle |
|---|---|---|
| `run_forever` (`runner.py:291`) | tur başarısız sayılır, bekleme en çok 8 kata çıkar | tur normal aralıkta koşar; not INFO özetinde, iz ERROR'da |
| `cli run --once` (`cli.py:335`) | `main` "HATA" basar, çıkış kodu 1 | **çıkış kodu 0**, not özet satırında |
| `backtest/engine.py:359` | koşu durur | **koşu sürer**; motor `LoopResult`'ı atıyor, iz yalnız log'da |
| `shadow_job.py:555` | `failed += 1` | tur `called` sayılır |

Gerekçe: (1) Güvenlik adımlarından sonra fırlatmak, kalıcı journal hatasını `run_forever`'da 8 katlık beklemeye çevirir (B5): 60 sn'lik
döngüde koruma kontrolü 8 dakikada bire düşer; 10 dakikalık kapanış penceresine bir, en çok iki deneme sığar, `_flatten_all` ise iptal
kesinleşmezse ikinci tura ihtiyaç duyar. Düzeltmenin amacını geri alırdı. (2) `run_once` içindeki benzer journal hataları aynı kanalı
kullanıyor ("gun durumu okunamadi", "izlenen iptaller journal'dan okunamadi", "iptal niyeti yazilamadi", "kill-switch karari journal'a
yazilamadi"); yeni kanal icat edilmedi. (3) `unattended-paper.md` §4 kuralı: girişte fail-closed, korumada fail-open.

**Ölçüt 6 — hata kill-switch ya da kapatma yolunun içindeyse.** Kod değişikliği gerekmedi; mevcut yol karşılıyor:
- `_flatten_all` journal'a hiç dokunmaz (yalnız broker). `_check_kill_switch` gün durumu okumasını `(sqlite3.Error, JournalError)` için
  korur. Karar yazımı `_record_halt` içinde korunur: yazılamazsa karar `_unpersisted_halts` belleğinde tutulur, not düşer, kapatma gider.
- Birleşik durum yeni testte: `test_a_read_only_journal_still_closes_on_a_breached_loss`. Bütün journal salt okunur (defter işi ve
  `daily_state` yazımı birlikte hata verir): ilk turda iptal + kapatma; hesap toparlansa da ikinci turda gün kapalı, kapatma yeniden gider.
- Sınır (önceden yazılı): yazılamayan karar yalnız süreç belleğindedir; süreç yeniden başlarsa kaybolur.

## 4. RED ve GREEN

Kurulum (`turn_with_bookkeeping`): her tura iki defter işi bırakılır: journal'a düşmemiş, önceki seanstan bir gerçekleşme (`fills`
INSERT) ve `submitting` kalmış, brokerda görünen bir giriş (`orders` UPDATE). Hata türleri: tabloya özel `RAISE(ABORT)` tetikleyicisi
(`fills`, `orders`), `PRAGMA query_only = ON` (`salt-okunur`), `DROP TABLE orders` (`orders-okunamaz`).

**RED** (yeni testler + değişiklikten önceki `runner.py`; `red-b1.log`): `16 failed, 16 passed`. 16'sı da `runner.run_once()` satırında
`JournalError` ile düşüyor; iddia satırlarına ulaşılmıyor:
- `test_a_journal_failure_does_not_stop_the_loss_limit[fills | orders | orders-okunamaz]`
- `test_a_journal_failure_does_not_stop_the_end_of_day_flatten[fills | orders | salt-okunur | orders-okunamaz]`
- `test_a_journal_failure_blocks_new_entries_for_the_turn[fills | orders | salt-okunur]`
- `test_a_read_only_journal_still_closes_on_a_breached_loss`, `test_a_journal_failure_is_logged_with_its_cause[fills | orders]`
- `test_a_failed_order_confirmation_does_not_skip_the_fill_record`, `test_bookkeeping_resumes_once_the_journal_recovers`,
  `test_a_journal_failure_cancels_the_pending_entry_like_any_blocked_turn`
```
writer.py:275  JournalError: Gerceklesme kaydedilemedi (yazilmamis-dolum): disk dolu              6 test
writer.py:252  JournalError: Emir guncellenemedi (tlab-…): disk dolu                              5 test
writer.py:252  JournalError: Emir guncellenemedi (tlab-…): attempt to write a readonly database   3 test
queries.py:73  JournalError: Kesinlesmemis emirler okunamadi: no such table: orders               2 test
```
RED'de yeşil kalan 16: mevcut 11 test, üç kontrol (`test_a_healthy_journal_…_as_before`: zarar sınırı, kapanış, giriş) ve
`test_an_unexpected_error_in_bookkeeping_is_not_swallowed[confirm_order | record_fill]`. Kontroller aynı senaryoyu sağlam journal ile
kurar, değişiklikten önce de sonra da geçer: `entries_blocked` yok, fazladan not yok, gerçekleşme yazılmış, giriş kesinleşmiş, SPY emri gitmiş.

**GREEN:** `test_kill_switch_durability.py` 32 geçti; üç hedef dosya 287 geçti (değişiklikten önce 266).
Not: yeni testlerimden birinin ilk beklentisi yanlıştı (hatalı turda bekleyen girişin `new` kalacağını yazmıştım; engelli tur onu iptal
ediyor). Düzelttim ve davranışı ayrı testle sabitledim (§7.1). Mevcut testlere dokunulmadı.

## 5. Mutantlar

Her mutant tek başına uygulandı, test dosyası koştu, dosya geri alındı (son hal amaçlanan dosyayla aynı; `mutants-b1.log`).
"İki adım": çözümleme ve mutabakat koruması için ayrı ayrı. Parantez: düşen test sayısı.

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

Sağ kalan olmadı (iki koşu: önce 20 mutant, son test kümesiyle 22).

## 6. Tam süit

@@FULLDETAIL@@

## 7. Bilinen sınırlar ve bedeller

1. **Bekleyen girişler de iptal edilir.** `entries_blocked` mevcut kuralı taşır (`every_age`): hatalı turda, pozisyonu olmayan
   sembollerdeki kendi bekleyen girişlerimiz yaşına bakılmadan iptal edilir (iptal niyeti yazılamıyorsa iptal gitmez). Geçici tek
   bir kilit hatası o turun sinyalini ve bekleyen girişi kaybettirebilir. Yön güvenli; iki testle sabit.
2. **Çıkış kodu ve backtest.** `run --once` bu hatada 0 döner; backtest motoru journal hatasında artık durmaz ve `LoopResult`'a
   bakmaz. İkisi de izinli dosyaların dışında (`cli.py`, `backtest/engine.py`); dokunmadım. Öneri: çağıranlar `entries_blocked`'ı denetlesin.
3. **Güvenlik adımlarından sonraki journal okuması.** `orders` okunamıyorsa normal turda `_cancel_stale_entries` (`runner.py:583`)
   hâlâ `JournalError` fırlatır; `run_forever` bunu başarısız tur sayar (B5). Zarar sınırı ve kapanış turu etkilenmez (testte).
   Karalama testiyle görüldü, commit edilmedi. Yalnız yazma hatasında (salt okunur dahil) tur hata fırlatmıyor (testte).
4. **Journal dışı hatalar** turu hâlâ güvenlik adımlarından önce bitirir: `get_account`/`get_positions` `BrokerError`'ı (#63 raporu,
   madde (c)) ve programlama hataları. Defter işlerinde bu sınır bilinçlidir ve testle sabittir; genişletmek ayrı karardır.
5. **Süreç başlangıcı.** Journal süreç açılırken yazılamıyorsa `start_run` hata verir ve döngü hiç başlamaz (kod okunarak).
6. `_reconcile` içinde `record_trade` yazılıp `mark_order_closed` yazılamazsa sonraki tur yeniden denemez; satır `closed` olmaz.
   Önceden de böyleydi; güvenlik etkisi görmedim (kod okunarak).
7. Kalıcı hatada her tur bir iki iz log'a düşer; eskiden bekleme uzadığı için daha seyrekti.
8. `docs/designs/unattended-paper.md` §4'e "Açık 3" kaydı eklenmedi (dosya izinli listede değil); ayrı doküman değişikliği gerekir.

## 8. Doğrulanmadı

- Gerçek disk dolu, salt okunur dosya sistemi ya da `database is locked`: yalnız tetikleyici, `query_only` ve `DROP TABLE` ile
  benzetildi. Kilitli veritabanında her yazmanın sqlite bekleme süresi kadar turu geciktirmesi ölçülmedi.
- `run_forever` uçtan uca (bekleme, kadans): testi yok; §3'teki gerekçe kod okumasına dayanıyor.
- §3 tablosundaki `--once` çıkış kodu, backtest ve gölge işi satırları: kod okunarak; bu senaryo için ayrı test yazılmadı.
- `dry_run` + journal hatası: karalama ile bir kez denendi (tur döndü, giriş yok); commit'li testi yok.
- Gerçek broker davranışı (yalnız `FakeBroker`) ve CI (`quality` işi; push edilmedi).
- Mutantlar elle seçildi; araçla tam mutasyon taraması yapılmadı.
