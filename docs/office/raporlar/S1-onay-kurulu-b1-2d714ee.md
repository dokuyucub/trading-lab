# S1 — Onay Kurulu + Hata Avı (birleşik): B1, journal hatası kapanışı durdurmasın · `2d714ee`

Tarih: 2026-11-26 · Dal `claude/journal-hata-kapanis` (`8f855cc` üstünde `ad8a415`, `2d714ee`; 8 dosya, +818/−13).
Bu küçük işte bütçe için **Hata Avı ve Onay Kurulu tek birimde birleştirildi**: önce saldırı, sonra karar. Kodu bu birim yazmadı.
İnceleme ayrı karalama kopyasında (`wt-rb1`, `2d714ee`, ayrık HEAD); yazarın ağacına dokunulmadı. Push, GitHub yazımı, iş akışı, ağ ve broker
çağrısı yok; `.env` okunmadı; sahte broker, sentetik sayılar. Karalama (izlenmiyor): `wt-rb1/tests/test_scratch_rb1.py` (16 test), `wt-rb1/scratch_rb1_mutants.py`.

## 1. Karar: **RET** (tek zorunlu değişiklik, bir satır + bir test)

B1'in kabul ölçütleri sağlanıyor: iki defter işindeki `JournalError` aynı turun kill-switch'ini, gün sonu kapanışını ve izlenen iptal
çözümünü atlatmıyor; hatadan sonra aynı turda giriş yok; üç çağıran hatayı kaybetmiyor; mevcut hiçbir iddia zayıflamamış.
RET nedeni değişikliğin **açtığı yeni bir fail-open yol** (H1): defter işi hatasından sonra süren tur, journal'da broker kimliği
olmayan bir girişe iptal gönderebiliyor; iptal izi yeniden başlayan süreçte devralınmıyor ve o girişin koruma ölçümü hiç yapılmıyor.

- **Z1 (zorunlu) — `src/tlab/engine/runner.py:620`, `_cancel_stale_entries`.** İptal niyeti broker kimliğiyle yazılsın:
  `self.writer.update_order_status(order.client_order_id, CANCEL_REQUESTED, order.broker_order_id)`. Yazıcıdaki mevcut `COALESCE`
  dalı (`journal/writer.py:213-217`) dolu kimliği ezmez. Test: `test_istenen_d2_…` senaryosu ve `test_d0_…` kontrolü
  `tests/test_kill_switch_durability.py`'ye taşınsın (iptal turundan sonra satırda kimlik var; yeni süreç korumasız dolumda günü kapatır).
- **Z2 (önerilen, aynı turda; tek başına RET nedeni değil) — `runner.py:598`.** `ours = open_entry_orders(self.conn)` korunsun:
  `except JournalError:` → `log.exception(...)`, `self._block_entries(result, "giris emirleri okunamadi; bayat giris iptali atlandi")`,
  `return True`. Test: `orders` okunamazken normal tur fırlatmaz, `run_forever` beklemeleri `[60, 60, 60]` (`test_istenen_a3_…`).
  Yönetim bunu B5'e bırakırsa H2 sınırı TESLİM'e yazılmalı.

Karalama kopyasında Z1 ve Z2 **birlikte** uygulanıp denendi (ayrı ayrı değil), sonra geri alındı: iki `test_istenen_*` yeşile döndü, beş
hızlı hedef dosya + gölge testi 327 geçti, `ruff`/`format`/`mypy` temiz. Yeniden incelemede yalnız Z1 (ve varsa Z2) ile testleri bakılır.

## 2. Kontrol listesi

| Madde | Durum | Kanıt |
|---|---|---|
| Kapsam = onaylı plan + yönetimin ek şartı | Evet | Dört kaynak (`runner.py`, `backtest/engine.py`, `cli.py`, `shadow_job.py`) ve dört test dosyası; başka dosya yok. `run_forever` satırları değişmedi. |
| Değişmez kısıtlar | Evet | Eklenen satırlarda anahtar, URL, hesap değeri yok; `skip`/`xfail`/`noqa`/`type: ignore` eklenmemiş. `src/tlab/**` yalnız dalda; dondurma bitmeden (en erken 2 Aralık 2026) `main`'e giremez. |
| `ruff`, `mypy`, ilgili testler | Evet | Kendi koşum: `ruff check` temiz; `ruff format --check` 144 dosya; `mypy` 117 dosyada hata yok (118. dosya karalama testim, 13 hatanın hepsi onda). Altı hedef dosya 386 test: beş hızlı dosya `326 passed`; `test_shadow_job.py` 60 testte tek kırmızı beklenen pin testi (ilk koşuda `-qq` özet sayısını bastırdı; gölge sayısı toplama ve mutantlı tam koşudaki `1 failed, 59 passed` satırından). |
| Tam `make check` | Yazarın günlüğü | `makecheck-b1b.log`: `1 failed, 1788 passed, 6 skipped in 1154.44s`, kapsam %91,48; tek kırmızı pin testi. **Ben yeniden koşmadım**; günlükte yalnız pytest çıktısı var (ruff/mypy satırı yok). |
| Yeni davranış testle sabit; mutasyon ya da kırmızı-önce | Evet | 18 mutanttan 16'sı öldü (§5). Yazarın kırmızı-önce günlüklerini yeniden üretmedim; korumayı kaldıran Y-M14 ve Y-M07 aynı şeyi gösteriyor. Yeni testler gerçek `JournalWriter` + gerçek SQLite dosyasında tetikleyici, `query_only`, `DROP TABLE` ile hata üretiyor; sarmalayıcıyı atlayan sahte yok (tek `monkeypatch`, journal dışı hatanın yutulmadığını sınayan testte, yerinde). |
| Hata Avı bulguları kapalı ya da kayıtlı | **Hayır** | H1 açık (Z1). H2–H4 gerekçesiyle kayıtlı. |
| Mevcut iddialar | Evet | Silinen test satırı üç tane, üçü de genişleyen `import` (`git diff 8f855cc 2d714ee -- tests \| grep '^-'`); kaldırılan ya da gevşetilen iddia yok. |
| Doğrulanamayanlar yazılı | Evet | §7; yazarın §8'i de dürüst. |

## 3. Bulgular

**H1 · ORTA · yeni · fail-open · DOĞRULANDI — iptal izi broker kimliği olmadan yazılıyor (`runner.py:620`, okuyan `:715`).**
`8f855cc`'de `_resolve_unconfirmed` yazılamazsa tur orada ölürdü; `_cancel_stale_entries` hiçbir zaman journal'da kimliği boş bir
girişi görmezdi. Şimdi: `confirm_order` yazılamaz (`:438` yakalar) → tur sürer → `entries_blocked` yüzünden her yaştaki giriş iptale
girer (`:384`, `every_age`) → aynı turda `cancel_requested` yazımı başarırsa (ifade başına gelip geçen kilit) iptal gider, satır
`cancel_pending` + `broker_order_id NULL` kalır. Aynı süreç bellekten izler; **yeniden başlayan süreç** `:715`'te kimliği boş satırı atlar.
Yeniden üretme: `test_d1_gecici_hatada_iptal_izi_broker_kimligi_olmadan_yazilir` (yeşil = hata var): koşullu tetikleyici
(kesinleştirme yazılamaz, iptal niyeti yazılır) + iptali `pending_cancel` bırakan broker + yeni `SessionRunner` + girişin stop bacağı
olmadan dolması → yeni süreç `halted=False`, pozisyon açık kalır ve **başka sembolde yeni giriş gönderir**. Kontrol `test_d0_…`
(kimlik yazılıyken) günü kapatıp pozisyonu kapatıyor. İstenen davranış `test_istenen_d2_…` (`2d714ee`'de kırmızı).
Sınır: geçici yazma hatası + asenkron iptal + o arada yeniden başlatma + iptal sırasında korumasız dolum; olasılık düşük, düzeltme tek satır.

**H2 · ORTA · yazar beyan etmiş (§7.3) · gecikme — `orders` okunamazsa normal tur hâlâ fırlatıyor (`runner.py:598`).**
`test_a1_…`: sıra `_check_kill_switch` → `_resolve_pending_cancels` → `_cancel_stale_entries`; hata yalnız sonuncuda, `open_entry_orders`
içinde. Güvenlik adımlarından **önce** fırlayan journal okuması/yazması yok (§4). Sonuç `test_a2_…`: `run_forever` beklemeleri
`[120, 240, 480, 480]`; yönetimin "normal kadans" şartı yazma hatasında tutuyor, okuma hatasında tutmuyor. Zarar sınırı kontrolü en çok
8 × `poll` aralığa düşer; kapanış turu fırlatmadığı için sayaç sıfırlanır ve 10 dakikalık pencereye (varsayılan `poll=60`) en az bir tur düşer.

**H3 · DÜŞÜK · test boşluğu — iki mutant sağ kaldı.** K6: gölge işi `journal_error` yerine `entries_blocked`'a baksa hiçbir test görmüyor
(tek test ve tam `test_shadow_job.py`: `59 passed`, tek kırmızı pin). K8: iki adımda `except TradingLabError`; bugünkü kodda eşdeğer
(bu iki adım içeride yakalanmayan başka `TradingLabError` üretmiyor), ama "journal dışı proje hatası yutulmaz" yalnız `RuntimeError` ile
sabit. Öneri: `test_an_unexpected_error_in_bookkeeping_is_not_swallowed`'a `BrokerError` parametresi; gölgede engelli ama hatasız bir tur.

**H4 · BİLGİ — yazar raporunda fazla genelleme.** "`queries.py` her `sqlite3.Error`'ı sarıyor" değil: `halt_reason` (`queries.py:95`) ham bırakır; çağıran ikisini de yakaladığı için (`runner.py:1027`) sonuç değişmiyor.

Saldırıp kıramadıklarım: (a) hatadan sonra aynı turda giriş: `submit_bracket` tek yerde (`:1278`), yalnız `:392` engelinden sonra;
`test_f1_…` kalıcı hatada üç turun üçü de engelli. (b) Yarım kayıt: `test_e1_…`/`test_e2_…` N. yazmada bozulan mutabakat sağlam turda
bir kez tamamlanıyor, çift kayıt yok. (c) Gerçek kilit (`BEGIN IMMEDIATE` tutan ikinci bağlantı): `OperationalError: database is locked`
`JournalError`'a sarılıyor; zarar sınırı ve kapanış turu kapatıyor, normal tur fırlatmıyor, kadans `[60, 60, 60]` (`test_b1_…`, `test_b2_…`).
(d) İptal journal izi olmadan gitmiyor: niyet yazılamazsa iptal gönderilmiyor (`:620-626`); kill/kapanış turları `:598`'e hiç varmıyor.

## 4. `run_once` izi (`2d714ee`): güvenlik adımlarına kadar her journal erişimi

| Satır | Adım | Journal erişimi | Hatası güvenlik adımından önce fırlar mı |
|---|---|---|---|
| `:336-361` | saat, hesap, pozisyon, açık emirler | yok (broker) | `BrokerError` evet; journal değil, bilinen sınır |
| `:438` | `_resolve_unconfirmed` | okuma `unconfirmed_orders`; yazma `confirm_order`, `update_order_status` | hayır (`JournalError` yakalanır) |
| `:445` | `_reconcile` | yazma `record_fill` (her dolum), okuma `open_entry_orders`, yazma `record_trade`, `mark_order_closed` | hayır; journal dışı hata evet (S1) |
| `:365` | `_check_kill_switch` | okuma `halt_reason` `:1027`, `orders_submitted_since` `:1072`; yazma `record_halt` `:1098` | hayır (üçü de korunuyor) |
| `:368` | gün sonu `_flatten_all` | yok | — |
| `:375` | `_resolve_pending_cancels` | okuma `orders_with_status` `:708`; yazma `_write_order_status` | hayır |
| `:384` | `_cancel_stale_entries` | okuma `open_entry_orders` `:598` **korumasız**; yazma `:620` korunuyor | güvenlik adımlarından SONRA fırlar (H2) |

Sağlam journal'da yol aynı: iki çağrı aynı sıra ve koşulla `_bookkeeping`'e taşınmış; `LoopResult`'a varsayılanı `None` bir alan eklenmiş.

## 5. Mutantlar (her biri tek başına; `-x`; öldüren ilk test)

| Mutant | Sonuç | Öldüren test |
|---|---|---|
| Y-M02 mutabakat hatasında `_block_entries` yok · Y-M14 yalnız ilk adım korunur | öldü | `…does_not_stop_the_loss_limit[fills]` |
| Y-M07 çözümleme hatası güvenlikten önce yeniden fırlar · K9 not var, bayrak yok | öldü | `…does_not_stop_the_loss_limit[orders]` |
| Y-M10 çözümlemede `except Exception` | öldü | `test_an_unexpected_error_in_bookkeeping_is_not_swallowed[confirm_order]` |
| Y-N04 ikinci hata ilkini ezer | öldü | `test_the_first_bookkeeping_failure_is_the_one_carried` |
| K7 alan yeni bir hata nesnesi taşır | öldü | `test_a_bookkeeping_failure_is_carried_on_the_turn_result[cozumleme]` |
| Y-N05 backtest fırlatmaz · K1 başka tip (`RuntimeError`) fırlatır | öldü | `test_a_journal_that_cannot_record_fills_aborts_the_backtest` |
| K2 backtest kapatma turunda hatayı yutar | öldü | `test_the_failing_turn_still_flattens_before_the_backtest_stops` |
| Y-N07 cli fırlatmaz · K3 "HATA" basar ama fırlatmaz · K4 doğrudan `return 1` | öldü | `test_a_bookkeeping_failure_exits_non_zero_after_the_turn_summary` |
| Y-N09 gölge `called` sayar · Y-N10 hem `called` hem `failed` · K5 ikisi de değil | öldü | `test_a_turn_with_a_bookkeeping_failure_is_counted_as_failed` |
| K6 gölge `entries_blocked`'a bakar | **sağ kaldı** | — (H3) |
| K8 iki adımda `except TradingLabError` | **sağ kaldı** | — (bugün eşdeğer; H3) |

Y = yazarın mutantı, yeniden koşuldu (9/9 öldü). K = kurulun mutantı (7/9 öldü). Günlük: karalama dizininde `rb1-mutants.log`, `rb1-k6-full.log`.

## 6. Çağıranlar ve ertelenebilir sınırlar

Çağıranlar (`grep "run_once("`: `src`'de üç yer, `scripts`'te yok): backtest tek çağrı yeri `engine.py:359`, eğri eklenmeden önce
fırlatıyor (koşu durduğu için fark etmez; önceden de `run_once` içinden aynı yerde fırlardı). `run --once`: özet, sonra `finally`
(koşu kapanır, koşu özeti), sonra `main` "HATA: …" ve çıkış 1 (testte `main` üzerinden). `run` (`--once`'sız): `run_forever` alana bakmaz;
her tur `_bookkeeping` ERROR düzeyinde iz (`:440`, `:447`) ve INFO özetinde not yazar, sessiz değil. Gölge işi: sayım `ad8a415` öncesiyle
aynı (`failed`); hatalı tur eskisi gibi veri gözlemiyor (`test_g1_…`; yazarın testi `symbol_turns` 210/212), gün yine `eksik`, gerekçe metni aynı.

| # | Sınır | Yön | Bağ |
|---|---|---|---|
| S1 | Defter işindeki journal DIŞI hata turu hâlâ güvenlik adımlarından önce bitirir. `test_c1_…`: saklanan `orders.stop_loss` sayı değilse `reconciler.py:118` `ValueError`, pozisyon kapanmaz. Yönetimin bilinçli sınırı (yalnız `JournalError`). | fail-open | Sınırsız: hatalı kayıt mutabakat penceresinde kaldıkça. Kalıcı çözüm güvenlik adımlarını defter işinden öne almak (ayrı karar). |
| S2 | Kilitli veritabanında her başarısız yazma sqlite varsayılanı 5 sn bekler. Ölçüm: zarar sınırı turunda kapatmadan önce 15,0 sn (üç yazma). | gecikme | ≤ 3 × 5 sn kapatmadan önce; engelli normal turda bekleyen giriş başına +5 sn (güvenlik adımlarından sonra). |
| S3 | Tek geçici hata, pozisyonsuz sembollerdeki bütün taze girişleri iptal eder (yazar §7.1). `orders` yazılamıyorsa iptal gitmez, giriş brokerda açık kalır (`test_b2_…`, `test_f2_…`). | fail-closed / giriş açık kalır | Sinyal kaybı; açık kalan giriş bracket ile korunur. |
| S4 | Defter işi yokken yalnız `orders` güncellemesi bozuksa bir giriş gider (`record_order` yazılır, `confirm_order` `:1286` yazılamaz); o tur `journal_error=None`, `--once` 0 döner. Önceden de böyle (`test_f2_…`). | fail-open (giriş) | Bir giriş: sonraki her tur `:438`'de engellenir. |
| S5 | `record_trade` yazılıp `mark_order_closed` yazılamazsa bir daha denenmez, `trades_recorded` o işlemi hiç saymaz (`test_e3_…`; yazar §7.6). `closed` durumunu `src`'de okuyan yok. | zararsız | Bir emir satırı, bir sayaç. |
| S6 | Diğer journal hataları (gün durumu, iptal niyeti, izlenen iptaller, kill-switch kaydı, karar/emir yazımı) alanı doldurmaz; backtest ve `--once` başarıyla biter (testle sabit, N12–N15). | görünürlük | Not ve ERROR izi var. |
| S7 | Bütün journal yazılamıyorsa `--once`'ta `finally` içindeki `end_run` kendi `JournalError`'ını fırlatıp asıl hatayı örter; çıkış yine 1, koşu özeti basılmaz. `ad8a415` öncesiyle aynı (kod okuması). | zararsız | Mesaj farkı. |
| S8 | Dal `src/tlab/**` değiştiriyor: pin testi kırmızı, dondurma bitmeden `main`'e giremez; `unattended-paper.md` §4 "Açık 3" kaydı ayrı belge işi. | — | Yönetim kararı. |

## 7. Doğrulanmadı

- Tam süit `2d714ee`'de koşulmadı (sayılar yazarın günlüğünden, ağaç eşleşmesi yazarın sha256 beyanından); yazarın kırmızı-önce günlükleri ve 39 mutantından 30'u yeniden koşulmadı.
- Gerçek disk dolu ve salt okunur dosya sistemi (yalnız tetikleyici, `query_only`, `DROP TABLE`, gerçek yazma kilidi denendi); H1'in gerçek
  Alpaca'daki karşılığı (iptalin `pending_cancel` kalması, o sırada dolum): yalnız sahte broker.
- `tlab backtest` ve `--once`'sız `tlab run` uçtan uca; S7; gölge işinin gerçek iş akışında bir günü; CI.
- Z1 ve Z2 ayrı ayrı uygulanmadı; birlikte denendi. Önerilen kalıcı testler yazılmadı, yalnız karalama testleri var.
