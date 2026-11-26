# S1 — Onay Kurulu: A2 "önce kaydet, sonra gönder" testi (0a60c97)

Tarih: 2026-11-26 · dal `claude/test-once-kaydet` · tek commit 0a60c97 (taban main d77b381) · 1 yeni dosya, +225 · kurul push, GitHub yazımı, ağ ya da broker çağrısı yapmadı

**Karar: ONAY (notlarla).** Zorunlu değişiklik yok; commit olduğu gibi yayımlanabilir. Sıra iddiası gerçek: journal, sahte brokerin `submit_bracket`'i içinde ayrı salt okunur bağlantıdan okunuyor; "önce gönder" mutantı yeni dosyada kırmızı, `test_runner.py`'de yeşil. Kurulun koştuğu 17 mutantın 17'si öldü. N1–N4 PR açıklaması içindir, hiçbiri engel değil.

## Kontrol listesi (kanıtların hepsi kurulun kendi koşumu)

| # | Madde | Sonuç | Kanıt |
|---|---|---|---|
| 1 | Kapsam | sağlandı | `git diff --stat origin/main 0a60c97`: yalnız `tests/test_write_ahead_order.py` +225; `-- src` boş. `skip`/`xfail` yok. Fiyatlar sentetik (`make_bars` 100.0 tabanı, 99.2 / 100.8), hesap `make_account` varsayılanı |
| 2 | İki ağaçta yeşil, lint, tip | sağlandı | main ağacı: `8 passed` (5 ardışık koşu). #63 ağacı (`8f855cc`, dosya `cmp` ile bayt bayt aynı): `8 passed`. `ruff check`, `ruff format --check`, `mypy` dosyada temiz. `tests/test_architecture.py` 114 yeşil |
| 3 | Sıra iddiası gerçek | sağlandı | `ObservingBroker.submit_bracket` (`:90-93`) önce `order_rows(self.observer)` okur, sonra `super()` çağırır; iddia test gövdesinde (`:165`). Gözlemci `mode=ro` ikinci bağlantı, `connect()` otomatik commit: satır ancak commit edildiyse görünür. M1'de görüntü `[[]]`: okuma gönderim anında, iddia anında değil. M1 `test_runner.py` tek başına `46 passed` |
| 4 | Journal hatası gönderimi durdurur | sağlandı | Hata gerçek SQLite'ta doğuyor (`BEFORE INSERT ON orders`, `RAISE(ABORT)`); günlükte zincir `sqlite3.IntegrityError` → `JournalError` (`writer.py:192`), yazıcı taklit edilmiyor. Test hem `broker.received == []` (`:194`) hem tur raporunu iddia ediyor: `intents == 1`, `vetoed == 0`, `submitted == 0`, not (`:198`), `allowed = 1` karar satırı (`:200`), boş `orders`. M3, K6, K9, K12, K13 kırmızı |
| 5 | Broker hatasında çözülebilir satır; tek kimlik | sağlandı | Satır: K1, M6, M4 (`:215`), K7 (`:222`), K10 (`:221`). Kimlik: M2, K2 (`:165`, `:179`, `:215`), K8 (`:179`) |
| 6 | Testlerin dürüstlüğü | sağlandı | "Gitmedi" testi boş yere geçmiyor: niyetin üretilip izin aldığı gövdede sabit; eş kontrol aynı kurulumla gönderen ilk iki test. Kurul sondası: yalnız `reject_order_inserts(conn)` satırı silinmiş kopya iki yönde `:194`'te kırmızı (aynı kurulum sağlıklı journal'da GÖNDERİYOR). İkinci turdaki "yeniden gönderilmedi" de boş değil (K10: strateji yeniden ateşliyor). K5 yalnız `[aciga_satis]` testlerini kırıyor: yön parametresi gerçek |
| 7 | Sağlamlık | sağlandı (N3, N4) | Dosyada saat, rastgelelik, ortam değişkeni, sabit yol yok; zaman `NOW` + `SimClock`, her test kendi `tmp_path`'inde. Tek test, iki testlik seçim ve `test_runner.py` ile iki sırada (54 yeşil) geçiyor. İki bağlantı fixture kapanışında kapanıyor (önce gözlemci); kod okumasıyla, bkz. Doğrulanmadı |
| 8 | Commit mesajı | sağlandı (N1) | Eski test satıra gönderimden sonra bakıyor (`test_runner.py:592-606`); M1 46 testte yeşil; 4 × 2 = 8 test toplandı; dört madde koda ve mutantlara uyuyor; altı mutasyonun altısı yeniden üretildi, kırmızı; `src/` boş |

## Mutantlar (`_handle_intent` ve çevresi; her biri tek başına, kaynak bayt bayt geri yazıldı)

| # | Mutant | Kaynak | Sonuç | Öldüren test (satır) |
|---|---|---|---|---|
| M1 | Önce gönder, sonra kaydet (hata olsa da kaydet) | yazar | öldü, 4 | `test_the_order_row_is_committed_before_the_broker_is_called` (`:165`), `test_a_failed_order_record_sends_nothing` (`:194`); #63'te aynı 4 |
| M1b | Önce gönder, yalnız başarıda kaydet | kurul | öldü, 6 | üsttekiler + `test_a_lost_response_leaves_a_row_the_next_turn_confirms` (`:215`) |
| M2 | Kayıt ikinci `from_intent` kimliğiyle | yazar | öldü, 6 | `:165`, `:179`, `:215` |
| M3 | `JournalError` yutulur, gönderim sürer | yazar | öldü, 2 | `test_a_failed_order_record_sends_nothing` (`:194`); #63'te aynı |
| M4 | Kayıt baştan `accepted` yazılır | yazar | öldü, 4 | `:165`, `:215` |
| M5 | `BEGIN`, gönderim, sonra `COMMIT` | yazar | öldü, 2 | `test_the_order_row_is_committed_...` (`:165`) |
| M6 | `BrokerError` sonrası satır `rejected` | yazar | öldü, 2 | `test_a_lost_response_...` (`:215`) |
| K1 | `BrokerError` sonrası satır silinir | kurul | öldü, 2 | `test_a_lost_response_...` (`:215`); #63'te aynı |
| K2 | Kaydedilenden farklı kimlikli emir gönderilir | kurul | öldü, 6 | `:165`, `test_the_confirmed_row_is_the_order_the_broker_received` (`:179`), `:215` |
| K5 | Yalnız açığa satışta önce gönder | kurul | öldü, 2 | yalnız `[aciga_satis]`: `:165`, `:194` |
| K6 | `record_order` sqlite hatasını yazıcıda yutar | kurul | öldü, 2 | `test_a_failed_order_record_sends_nothing` (`:194`) |
| K7 | Sonraki tur brokerdaki satırı kesinleştirmez | kurul | öldü, 2 | `test_a_lost_response_...` (`:222`) |
| K8 | Başarılı gönderimden sonra `confirm_order` yok | kurul | öldü, 2 | `test_the_confirmed_row_...` (`:179`) |
| K9 | "journal yazilamadi" notu düşülmez | kurul | öldü, 2 | `test_a_failed_order_record_sends_nothing` (`:198`) |
| K10 | Bekleyen sembol koruması kapalı (ikinci turda yeniden gönderim) | kurul | öldü, 2 | `test_a_lost_response_...` (`:221`, iki açık emir) |
| K12 | Journal hatası turdan dışarı fırlar | kurul | öldü, 2 | `test_a_failed_order_record_sends_nothing` (`JournalError`) |
| K13 | Emir kaydı yazılamayınca karar satırı da silinir | kurul | öldü, 2 | `test_a_failed_order_record_sends_nothing` (`:200`) |

`test_runner.py` tek başına M1, M3 ve M5 altında `46 passed`: yazarın "eski testlerden sağ çıkıyor" iddiası doğrulandı.

## PR açıklaması için notlar (zorunlu değil)

- **N1 — ifade.** Commit mesajı altıncı mutasyonu "hata sonrasi izi sil" diye anıyor, yazarın raporunda M6 "satır `rejected` yapılır". İkisi ayrı mutant, ikisi de kırmızı (M6, K1). PR açıklamasında "satır `rejected` yapılır ya da silinir" yazılsın; commit değişmesin.
- **N2 — sabitlenen, onaylanan değil.** Emir kaydı yazılamayınca journal'da emirsiz bir `allowed = 1` karar satırı kalıyor (`:200`). Bugünkü davranış bu; karar ile emir ileride tek işlemde yazılırsa bu satır bilinçli güncellenmeli.
- **N3 — isteğe bağlı, takip işi.** `:225`'teki mesajlı iddia yeniden gönderimde hiç çalışmıyor: K10 `:221`'deki `(ref,) = broker.open_orders` açmasında `ValueError` ile ölüyor. `:225` satırı `:221`'in önüne alınırsa hata mesajı niyeti söyler. `:177` sahte brokerle totolojik (ref emirden kuruluyor); asıl iddia `:179`.
- **N4 — sınırlar.** Tek hata türü enjekte edildi (INSERT tetikleyicisi). Emrin brokera hiç ulaşmadığı yol (`fail_submit`) bu dosyada yok, `test_runner.py:592` ve `:609` tutuyor. Salt okunur veritabanı, dolu disk, `BrokerError` dışı istisna ve gerçek süreç ölümü sınanmadı. Dört yardımcı `tests/test_runner.py`'den geliyor (üç mevcut dosyadaki desen); `FakeBroker.submit_bracket` `open_orders`'a eklemeyi ya da `accepted` dönmeyi bırakırsa testler sessizce değil gürültüyle kırılır.

## Doğrulanmadı

- Tam süit koşulmadı. `1536 passed, 6 skipped`, kapsam %90,78 yalnız yazarın `makecheck-a2.log` kuyruğundan okundu; logun 0a60c97'ye ait olduğu yazar beyanıdır (1528 + 8 = 1536, A3 raporundaki taban sayısıyla tutarlı).
- Depo geneli `make check` koşulmadı; `ruff` ve `mypy` yalnız bu dosyada koştu. CI ve pre-commit kancalarına bakılmadı.
- Yazarın tasarım notu 2 (gözlemci `conn` olunca M5 sağ kalır), kapsam yüzdeleri, 15 ardışık koşu ve M1'in 109 testlik geniş kümedeki sonucu yeniden üretilmedi.
- Kapatılmayan bağlantı uyarısı gözlenemedi: Python 3.12.3 sqlite bağlantısı için `ResourceWarning` üretmez (3.13 ve sonrası üretir). Kapanış kod okumasıyla doğrulandı.
- #63 ağacında yalnız M1, M3, K1 koştu; `ruff format --check` orada ayrıca koşmadı (dosya bayt bayt aynı).

Son durum: `wt-s1-a2`'de `git status --short` boş, HEAD `0a60c97`; `wt-a2-on63`'te yalnız izlenmeyen test kopyası, HEAD `8f855cc`. Mutant koşucusu: `/tmp/claude-0/-home-user-trading-lab/27d6a727-f8fd-55d8-bd5f-345e7067b5e2/scratchpad/onay-a2/mutants.py`.
