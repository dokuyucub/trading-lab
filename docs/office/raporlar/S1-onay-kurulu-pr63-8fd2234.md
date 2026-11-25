# S1 — Onay Kurulu: PR #63, `8fd2234`

Tarih: 2026-11-25. İş: "bekleme kaldırma + izleme sertleştirmesi". İncelenen aralık `a48daae..8fd2234`
(05b391d, 05df92d, f654f0d, 8fd2234). Yöntem: yalnız okuma ve çevrimdışı hedefli test; commit, push, GitHub yazımı,
broker ya da API çağrısı yok. Yazarın iddiaları kanıt sayılmadı; her biri aşağıda kendi koşumla karşılaştırıldı.

## Karar

**ONAY, notlarla.** Kontrol listesinin altı maddesi de sağlanıyor. Notlar (N1–N6) push'u engellemez ama TESLİM'e
taşınmalı. Bu karar `8fd2234` içindir; ofis onayı Codex'in SHA'ya bağlı `## ONAY` kaydının yerine geçmez.

## Kontrol listesi

| # | Madde | Sonuç | Kendi kanıtım |
|---|---|---|---|
| 1 | Kapsam plan ile aynı | GEÇTİ | PR yorumları okundu: plan 7155083924, Codex plan incelemesi 7155309564, ek 7165070355. Diff 5 dosya; her değişiklik bir plan maddesine bağlandı (aşağıda). Tek plan dışı satır N5. |
| 2 | Değişmez kısıtlar | GEÇTİ | Gizli bilgi, fiyat, hesap değeri yok (diff tarandı; `tests/test_architecture.py` 114 yeşil). İş akışı, `config/`, `requirements.lock`, `pyproject.toml`, `Makefile` değişmedi. `skip`/`xfail` yok. `origin/claude/killswitch-fix` hâlâ `a48daae`; dört commit yerelde, `a48daae` atası. PR taslak ve dondurma başlıklı. |
| 3 | `ruff`, `mypy`, testler, tam `make check` | GEÇTİ | `8fd2234`: `ruff check` temiz; `ruff format --check` 144 izlenen dosya temiz; `mypy` 117 dosyada hata yok (ikisinde de tek gürültü izlenmeyen `tests/test_scratch_r63.py`). Hedefli üç dosya 218 geçti; `test_entry_cancel_race.py` 161 geçti. `f654f0d` tam süit logu: 1703 geçti, 6 atlandı, 1 kırmızı, kapsam %90,98; tek kırmızı beklenen pin testi. Logun bu koda ait olduğu iki yoldan doğrulandı: logdaki parmak izi (`6969bca0…`) `8fd2234` ağacında yeniden hesaplananla aynı; toplam 1710 = `8fd2234`'te toplanan 1712 − 2 yeni test. |
| 4 | Yeni davranış testle sabit; mutasyon ya da düzeltme öncesi kırmızı | GEÇTİ (N1) | Yazarın betiği baştan koşuldu: 47/47, yazarın loguyla satır satır aynı. Düzeltme öncesi kırmızı koşu: `8fd2234` testleri `a48daae` kaynağıyla 40 kırmızı, `05df92d` kaynağıyla 14 kırmızı (tam olarak B1–B4 grupları). Kendi 9 mutantımdan 7'si yakalandı, 2'si kaçtı (N1). |
| 5 | Hata Avı bulguları kapalı ya da kayıtlı | GEÇTİ | B1–B4 kapalı (regresyon testleri + kırmızı koşu). B5, O1, O2, R1, R2 §4 "Bilinen sınırlar"da ve backlog B0/B10'da. Kaçan `mark_order_closed` mutantı kapandı: `f654f0d` testleriyle 159 yeşil kalıyor, `8fd2234`'te 2 test kırmızı. Kalan küçük notlar backlog B63'te (N6). |
| 6 | Doğrulanamayanlar "doğrulanmadı" diye yazılı | GEÇTİ | Hata Avı raporu ve §4 doğrulanmayan Alpaca davranışlarını (`held`, kısmi dolumda bacak miktarı, `filled_at`) açık yazıyor. Benim doğrulayamadıklarım aşağıda. |

## Kapsam bulguları

- **Plan eşlemesi.** Bekleme kaldırma, `_outcome_without_entry`, üç geçiş durumunun `NOT_PROTECTIVE`'e eklenmesi:
  7155083924. Kalıcı kaydın yeniden açılan bağlantıdan `halt_reason` ile okunması, yazılamayan dalda davranış kanıtı,
  emir listesi okunamazken gün kapatma ve geri gelince yeniden kapatma: 7155309564. B1–B4 düzeltmeleri, satış yönlü
  test, stop durumu ve miktarı testleri, §4 düzeltmeleri: 7165070355. R1/R2 sınırları (8fd2234) PR'da henüz
  duyurulmadı (N3).
- **Önceden var olan testler.** AST karşılaştırması (`a48daae` → `8fd2234`): 60 → 78 tanım. Silinen 4 test ve 2
  yardımcı yalnız kaldırılan bekleme davranışına ait; plan bunu duyurmuştu. Kalanlarda gövdesi değişen tek tanım
  `RacingBroker` (iki yeni hata bayrağı) ve bir docstring. Zayıflatılmış beklenti yok; `assert` sayısı 204 → 272.
- **Kapılar.** Tek yeni bastırma `writer.py:234` `# noqa: S608`. Aynı dosyadaki üç ve `queries.py:44`'teki mevcut
  kullanımla aynı kalıp; birleştirilen yalnız `?` yer tutucuları, değerler bağlanıyor. Gevşetme saymıyorum.
- **Commit mesajları** diff ile uyumlu. 05df92d ve 8fd2234 gerçekten yalnız test/belge (`git show --stat`). İki küçük
  eksik: f654f0d mesajı `core/types.py` docstring satırını anmıyor (N5); 05b391d'deki "yeniden başlatma süreyi
  uzatamaz" cümlesi yazılamayan `daily_state` dalını kapsamıyordu, bunu f654f0d ve §4 düzeltiyor.
- **Codex 7155309564'ün "ikinci `halted=True` yetmez" itirazı** karşılanmış: kalıcı kaydı okuyup yok sayan mutant
  (`halt_reason(...) and None`) `test_a_halt_for_an_unprotected_fill_is_read_back_after_a_restart` ile yakalanıyor.

## Mutasyon sonuçları

Elle uygulanan betik mutantları (her biri sonra `git checkout -- <dosya>` ile geri alındı):

| Mutant | Sonuç | Kırmızıya dönen test |
|---|---|---|
| U4 okunamayan tur denemeye sayılmaz | yakalandı | `..._counts_toward_the_cancel_attempt_limit` (iki yol) |
| S5a tur başı görüntüsüne düşülmez | yakalandı | `test_the_turn_start_position_is_used_when_the_reread_fails` (iki yol) |
| J1 yazıcı koşulu yok sayar | yakalandı | B1 (iki yol), B1b, `test_mark_order_closed_skips_only_the_listed_statuses` |
| U2 sıfır dolumda pozisyon ölçülmez | yakalandı | B4 (dört durum), B4b (iki yol) |
| U1 mutabakat izlenen satırı ezer | yakalandı | B1 (iki yol), B1b |

Betikte olmayan kendi mutantlarım:

| Mutant | Yer | Sonuç |
|---|---|---|
| K1 başka sembolün stopu da kapsam sayılır (sembol süzgeci yok) | `runner.py:765` | **KAÇTI** (218 yeşil) |
| K6 okunamayan girişte herhangi bir sembolün pozisyonu alınır | `runner.py:749-751` | **KAÇTI** (218 yeşil) |
| K2 mutabakat `cancel_requested` satırını ezer (`unless` yalnız `CANCEL_PENDING`) | `runner.py:412` | yakalandı (B1b) |
| K3 kör tur sınırı bir fazla (`>=` yerine `>`) | `runner.py:595` | yakalandı |
| K4 görünen pozisyonda gereken miktar bir eksik | `runner.py:770` | yakalandı (`[short]`) |
| K5 `mark_order_closed` hiçbir şey yazmaz | `writer.py:230` | yakalandı (2 test) |
| L1b kalıcı gün kaydı okunur ama yok sayılır | `_check_kill_switch` | yakalandı |
| L3 okunamayan girişte pozisyon yeniden okunmaz | `runner.py:748-751` | yakalandı |
| L4 sıfır dolum dalı yalnız terminal olmayan girişte çalışır | `runner.py:729` | yakalandı (B4b) |

**N1'in ölçüsü.** K1 fail-open yönünde, K6 fail-closed yönünde. Teslim edilen kod ikisinde de doğru: karalama
testlerim gerçek kodla yeşil, mutantla kırmızı. Boşluk bu teslimin getirdiği bir şey değil: `a48daae`'de de bulunan
kardeş süzgeç (`_fill_is_protected`, `runner.py:787`) aynı mutasyonla 218 testte yeşil kalıyor. Dosyadaki evren tek
sembol (`SPY`); sembol yalıtımı hiçbir dalda sınanmıyor. Eklenmesi gereken testin özü (iki yol, iki dal):

```python
def other_symbol_stop(s, qty):
    stop = legs(s.order, stop_qty=qty)[0]
    return stop.model_copy(update={"symbol": "QQQ", "broker_order_id": "other-stop",
                                   "client_order_id": "alpaca-other-stop"})

@pytest.mark.parametrize("path", PATHS)
def test_other_symbol_stop_is_not_cover_when_the_entry_is_unreadable(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)            # SPY pozisyon 5, SPY stop `new` 5
    s.broker.open_orders = [o for o in s.broker.open_orders if o.broker_order_id != "leg-stop"]
    s.broker.open_orders.append(other_symbol_stop(s, 5.0))
    s.broker.fail_get_order = True
    assert s.runner.run_once().halted          # K1 ile kırmızı
```

Aynı kalıp sıfır dolum dalı (B4 kurulumu + QQQ stopu) ve okunan dolum dalı (tam dolum + yalnız QQQ stopu) için de
geçerli. K6 için: SPY girişi okunamıyor, SPY'de pozisyon yok, QQQ'da kendi stopuyla korunan pozisyon var → gün kapanmamalı.

## Bilinen sınırların değerlendirmesi

| Sınır | Belgede | Yön | Erteleme |
|---|---|---|---|
| B5 (i): önceki seans + okunamayan giriş + sahipsiz çıkış emri | Dürüst | Sınırlı: emir dolarsa ters pozisyon o turda günü kapatır (satış yönlü testle sabit). Emir varsayılanı `DAY` (`types.py:369`); bacakların seans sonunda düştüğü brokerda doğrulanmadı. | Makul. Giriş okunmadan yön ve seans bilinmiyor; düzeltme tasarım işi (B0/B10). |
| O1: giriş + emir listesi aynı turda okunamazsa kapsanan pozisyon kapatılır | Dürüst ("Bedeli…") | Fail-closed | Makul; Codex 7155309564 madde 1 tam bunu istedi. |
| O2 (ii): iptali doğrulanmış, kalıcı okunamayan giriş girişleri süresiz engeller | Dürüst | Fail-closed (işlem yok) | Makul. |
| R1 (iii): deneme sayacı süreç belleğinde, yeniden başlatma sıfırlar | Dürüst | Sınırlı. Karalama testimle doğrulandı: 12 tur, iki turda bir yeniden başlatma; her tur `entries_blocked`, yeni emir yok; bayat giriş dolunca o turda gün kapanıyor. Kod okunarak: giriş varsayılanı `DAY`, gün sonu kapanışı hesap genelinde iptal ediyor (`runner.py:333`). | Makul. Uzayan şey korumasız pozisyon değil, bayat girişin canlı kalma süresi. Codex 7154998289'un kabul koşulu (dolum + eksik koruma) bunu kapsamıyor; yine de aynı sınıftan sayılabilir, TESLİM'de açık yazılmalı (N3). |
| R2 (iv): iptali doğrulanmamış, kalıcı okunamayan giriş her seansı kapatır | Dürüst | Fail-closed | Makul. |

Push'tan önce düzeltilmesi gereken bir sınır görmüyorum.

## TESLİM'e taşınacak notlar

- **N1.** Sembol yalıtımı testi yok (K1, K6 kaçıyor); kod doğru. Yukarıdaki testler B63'e ya da bu dala yalnız test
  içeren bir commit olarak eklenmeli. Eklenirse yeni head için hedefli koşu yeter; `src/` değişmez.
- **N2.** Tam `make check` `8fd2234`'te koşulmadı. Fark yalnız test ve belge; `src/` parmak izi aynı. Sayılar
  `f654f0d` içindir; push sonrası hosted `quality` beklenen sonucu vermeli: 1705 geçti, 6 atlandı, 1 kırmızı (pin).
- **N3.** R1 ve R2 PR'da henüz duyurulmadı; TESLİM'de sınır olarak, R1 için yukarıdaki üç dayanakla yazılmalı.
- **N4.** §4 satır 371 `held` araştırması için "ayrıntı #63 TESLİM" diyor; TESLİM bu ayrıntıyı gerçekten içermeli.
- **N5.** `core/types.py:588` docstring düzeltmesi (`_cancel_entry` → `stops_cover`) ek planda "§4'teki altı
  uyuşmazlık" dışında kalıyor (rapordaki 7. madde). Davranışsız tek satır; TESLİM'de anılmalı.
- **N6.** Açık kalan küçükler (B63): iki B1 testi `trades` satırını doğrulamıyor (bugün boş geçmiyor: U1 ve J1
  mutantları bu testlerle yakalanıyor); `test_entry_cancel_race.py:1357` yorumu "giris 5/10" yanlış;
  `runner.py:105` sabit açıklaması okunamayan turun sayıldığını yazmıyor; "iptal iletilemedi (3 deneme)" notu kör
  turlarda tek gönderimle de çıkıyor.

## Doğrulanmadı

- Tam süitin `8fd2234`'teki sonucu (N2). Tam süit logunun koştuğu ağaçtaki test dosyalarının `f654f0d` ile bayt
  düzeyinde aynı olduğu (log commit'ten yaklaşık bir dakika önce başlamış; `src/` parmak izi ve test sayısı örtüşüyor).
- K1, K6 ve kardeş mutantın kaçışı yalnız üç hedefli dosyada ölçüldü; tam süitte ölçülmedi.
- Alpaca'nın gerçek davranışı (`held` bacak, kısmi dolumda bacak miktarı): broker çağrısı yasak, ölçülmedi.
- 8fd2234 mesajındaki "420 test yeşil" sayısı; yalnız `f654f0d` yarış dosyasında 159 yeşil kaldığını ölçtüm.

Çalışma kopyası (`wt-r63`) `8fd2234`'te; `git status` yalnız izlenmeyen `tests/test_scratch_r63.py` gösteriyor.
