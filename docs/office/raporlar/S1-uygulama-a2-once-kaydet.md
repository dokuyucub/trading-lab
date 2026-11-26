# S1 — Uygulama: A2, "önce kaydet, sonra gönder" sırasını sabitleyen test

Tarih: 2026-11-26 · Dal `claude/test-once-kaydet`, taban `main` `d77b381` · Çalışma kopyası `wt-s1-a2`. Push, GitHub yazımı,
iş akışı, broker ya da ağ çağrısı yok; testler sahte broker ile çevrimdışı. Sayılar sentetiktir.

## 1. Sonuç

- **A2 kapandı.** Commit `0a60c97` (push edilmedi). Tek dosya: `tests/test_write_ahead_order.py` +225. `git diff --stat origin/main -- src` boş.
- 8 test (4 test × alış / açığa satış): `main` tabanında yeşil, #63 ağacında (`8f855cc`) **değiştirilmeden** yeşil.
- "Önce gönder, sonra kaydet" mutasyonu yeni dosyada **kırmızı** (4 test). Aynı mutasyonla `tests/test_runner.py` tek başına: 46 geçti.
- Altı el mutantının altısı öldü (üçü `test_runner.py`'den sağ çıkıyordu). İki ağaçta da aynı sonuç.
- `ruff check` temiz, `ruff format --check` 145 dosya, `mypy` 117 dosyada hata yok. Tam süit: `1536 passed, 6 skipped in 1130.50s (0:18:50)`.

## 2. Testler neyi sabitliyor

Sahte broker `ObservingBroker(FakeBroker)`, `submit_bracket` çağrıldığı anda `orders` tablosunu **ayrı, salt okunur ikinci bir
bağlantıdan** okur ve saklar; başarısız gönderimleri de `received` listesinde tutar. Hepsi gerçek `OpeningRangeBreakout` + `RiskGate` ile.

| Test (`[alis]`, `[aciga_satis]`) | Madde | İddia |
|---|---|---|
| `test_the_order_row_is_committed_before_the_broker_is_called` | 1, 4, 5 | Emir brokera ulaştığı anda journal'da tek satır: gönderilen `client_order_id`, `status='submitting'`, `broker_order_id IS NULL`; sembol, yön, miktar, fiyatlar gönderilenle aynı (`:165`) |
| `test_the_confirmed_row_is_the_order_the_broker_received` | 4 | Tur sonunda yine tek satır, aynı kimlik; `status='accepted'`, `broker_order_id` broker cevabındaki (`:179`) |
| `test_a_failed_order_record_sends_nothing` | 2 | `orders` INSERT'i `RAISE(ABORT)` ile reddedilir: `submit_bracket` hiç çağrılmaz (`:194`); tur hata fırlatmaz; not, karar satırı, boş `orders` |
| `test_a_lost_response_leaves_a_row_the_next_turn_confirms` | 3 | `BrokerError` sonrası satır `submitting` (`:215`), `unconfirmed_orders` onu döndürür; sonraki tur aynı satırı kesinleştirir, yeniden göndermez |

## 3. Bulunan davranış (olduğu gibi sabitlendi, yeni davranış tarif edilmedi)

**Madde 2 — emir kaydı yazılamazsa.** `record_order` (`runner.py:608`) `sqlite3.Error`'ı `JournalError`'a sarar (`writer.py:190-192`);
`_handle_intent` yakalamaz, `_evaluate_universe` yakalar (`runner.py:522-528`). Sonuç: **tur hata fırlatmaz**, `result.notes` içinde
`SPY: journal yazilamadi`, `intents == 1`, `vetoed == 0`, `submitted == 0`, broker çağrılmaz. İzinli karar satırı (`allowed = 1`) journal'da
**kalır** (`runner.py:598` emir kaydından önce yazıyor), `orders` boştur: emirsiz bir "izinli karar" oluşur. Hata enjeksiyonu gerçek SQLite
katmanında (`BEFORE INSERT ON orders` tetikleyicisi); `JournalWriter` taklit edilmedi.

**Madde 3 — gönderim hata verirse.** `except BrokerError` (`runner.py:612-617`) yalnız loglar ve döner: satır `status='submitting'`,
`broker_order_id NULL` kalır, `result.submitted` artmaz. `unconfirmed_orders` (`queries.py:48`) satırı bulur. Emir brokerda görünüyorsa sonraki
turda `_resolve_unconfirmed` (`runner.py:353`) aynı satırı broker durumu ve kimliğiyle kesinleştirir; sembol beklemede olduğu için ikinci emir gitmez.

**Madde 5.** Açığa satış ucuz kuruldu: `breakout_bars`'ın aynası (`close 99.2 < aralık dibi 99.5`, `quote_mid=99.2`) ORB'den `SELL` niyeti çıkarıyor.

## 4. Mutantlar (her biri tek başına uygulandı, iki dosya koştu, `git checkout -- src` ile geri alındı)
| # | Mutant | Yeni dosya | `test_runner.py` tek başına |
|---|---|---|---|
| M1 | Önce `submit_bracket`, sonra `record_order` (hata olursa da kaydet) | **öldü** (4 kırmızı) | **sağ** (46 geçti) |
| M2 | Kayıt başka `client_order_id` ile (`from_intent` ikinci kez) | öldü (6) | öldü (4) |
| M3 | `JournalError` yutulur, gönderim sürer | öldü (2) | **sağ** (46 geçti) |
| M4 | Kayıt `status="accepted"` ile yazılır | öldü (4) | öldü (3) |
| M5 | Kayıt `BEGIN` içinde, `COMMIT` gönderimden sonra | öldü (2) | **sağ** (46 geçti) |
| M6 | `BrokerError` sonrası satır `rejected` yapılır | öldü (2) | öldü (3) |

M1 RED (`main` tabanı, `4 failed, 4 passed in 1.55s`; #63 ağacında aynı 4 test):
```
FAILED test_the_order_row_is_committed_before_the_broker_is_called[alis] ve [aciga_satis]
  tests/test_write_ahead_order.py:165: AssertionError: assert [[]] == [[{'client_or... 'SPY', ...}]]
FAILED test_a_failed_order_record_sends_nothing[alis] ve [aciga_satis]
  tests/test_write_ahead_order.py:194: AssertionError: kaydedilemeyen emir brokera gitmemeli
```
Diğer kırmızı satırlar: M2 `:165`, `:179`, `:215`; M3 `:194`; M4 `:165`, `:215`; M5 `:165`; M6 `:215`.

## 5. #63 ağacı ve ölçümler

- Karalama ağacı `wt-a2-on63` (`8f855cc`), dosya izlenmeyen kopya: **`8 passed in 0.54s`**, değişiklik gerekmedi. `_handle_intent` iki ağaçta aynı
  metin (`main:583`, #63 `:1204`). Altı mutant orada da öldü; M1/M3/M5 yine sağ. `ruff`, `mypy` (118 dosya) temiz. Ağaç duruyor, `src/` diff'i boş.
- Yeni dosya 15 ardışık koşuda 15/15 yeşil; `skip`/`xfail` yok. Tam süit (`makecheck-a2.log`) kapsamı %90,78 (rapor tabanı %90,65):
  `runner.py` %89 → %91 (`522-528`, `353-355` artık koşuyor), `writer.py` %76 → %79 (`190-192`).

## 6. Tasarım notları ve görevden sapmalar

1. **`assert` sahte brokerin içinde değil.** Journal `submit_bracket` içinde okunur, iddia o görüntü üzerinde test gövdesinde; sahte içindeki
   `AssertionError` ileride araya girecek geniş bir `except` tarafından yutulabilirdi.
2. **İkinci bağlantı görev metninden sıkı.** Gözlemci `conn` yapılınca M5 sağ kaldı (`8 passed`, karalama ağacında denendi); ayrı bağlantıyla öldü.
3. Yardımcılar `test_runner.py`'den içe aktarıldı (dört dosyadaki desen; #63'ün ek broker metotları miras alınıyor). Gönderimin brokera
   **hiç ulaşmadığı** hata (`fail_submit`) yeni dosyada yok; `test_runner.py:592` ve `:609` onu zaten tutuyor.

## 7. Doğrulanmadı

- M1'in rapordaki 109 testlik geniş kümeden (soak, CLI, journal, SDK yolu) sağ çıktığı yeniden koşulmadı; yalnız `test_runner.py` (46) koşuldu.
- Tek hata türü enjekte edildi (`orders` INSERT'inde tetikleyici). Salt okunur veritabanı, dolu disk, `record_decision` hatası,
  `submit_bracket`'in `BrokerError` dışı istisnası, gerçek Alpaca adaptörü ve gerçek süreç ölümü (iki adım arasında `kill`) sınanmadı.
- CI'da koşmadı; pre-commit kancalarının bu commit'te çalışıp çalışmadığına bakılmadı. Atlanan 6 testin kimliği `-rs` ile doğrulanmadı.
