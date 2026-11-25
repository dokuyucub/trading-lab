# S1 — Test ve Kalite: `make check` süresi, kapsam ve test gücü

Tarih: 2026-11-25 · Kod: `main` @ `47a2a7d` (çalışma kopyası `wt-a5`) · Salt okuma: commit, push, iş akışı, ağ ve broker yok.
Yöntem: tam süit bir kez kapsamasız (`--durations`, `--junitxml`), bir kez CI komutuyla kapsamalı koşuldu; sonra yalnız hedefli deneyler yapıldı.
Ortam: 4 çekirdek, başka birimlerle paylaşımlı. İki tam koşu kısmen aynı anda çalıştı; mutlak süreler gürültülü, paylar güvenilir.
Rapordaki her sayı ölçümdür; ölçülmeyenler `tahmin` diye işaretlidir.

## 1. Sonuç

- **Ölçüm:** tam süit kapsamasız **965,96 sn (16:05)**, CI komutuyla kapsamalı **1338,96 sn (22:18)**; 1534 test, 1528 geçti, 6 atlandı. `ruff` 0,1 sn, `mypy` soğuk 9,3 sn: `make check` süresinin %99'undan fazlası pytest.
- **Yoğunlaşma:** en yavaş 10 dosya sürenin **%86,8**'i; `test_shadow_job.py` tek başına %48,3. 24 test (≥10 sn) sürenin %52,9'u.
- **Kök sebep CPU değil bekleme:** sahte HTTP sunucusunda Nagle + gecikmeli ACK (istek başına 45 ms), her test sonunda sunucu başına 0,5 sn kapanış beklemesi ve alpaca-py'nin 429'da gerçek `time.sleep(3)`'i.
- **Çözüm küçük ve yalnız `tests/` altında:** 6 dosyada +46/−5 satır. Etkilenen 15 dosya **791,0 → 133,0 sn** (ölçüm, 582 test yeşil). Tam süit kapsamasız ≈300 sn, kapsamalı ≈11 dk (`tahmin`). Hiçbir test atlanmıyor, hiçbir iddia değişmiyor.
- **Kapsam %90,65** (eşik %80), 14 modül %90'ın altında. Journal yazma hatası, `run_forever`, kapının bekleyen-emir vetosu ve gerçek adaptörün iptal/kapatma hata yolları testsiz. "Önce gönder, sonra kaydet" mutasyonu 109 testten sağ çıktı.

## 2. En yavaş dosyalar ve testler

Süreler junit kayıtlarından (kurulum + çağrı + söküm). "Sonra" sütunu §3'teki Ö1–Ö3 uygulanmış hedefli koşudur.

| # | Dosya | Test | Kapsamasız | Pay | Kapsamalı | Sonra | Sebep |
|---|---|---|---|---|---|---|---|
| 1 | `test_shadow_job.py` | 59 | 461,9 sn | %48,3 | 506,5 sn | 67,3 sn | 17 tam gün testi, her biri ≈23 sn: 106 tur × 2 sembol, sahte sunucuya ≈430 istek, istek başına 45 ms Nagle beklemesi |
| 2 | `test_shadow_collect.py` | 196 | 78,7 sn | %8,2 | 86,0 sn | 13,5 sn | Test başına iki sunucu; kapanışta 0,5 sn (ortalama 0,40 sn/test) |
| 3 | `test_baseline_run.py` | 21 | 58,5 sn | %6,1 | 162,0 sn | — | CPU: her `run_baseline` 4 maliyet senaryosu × 8 gün × 390 dakika (≈12.480 `run_once`, ≈4,6 sn). 5 test aynı girdiyi yeniden hesaplıyor. Kapsama ×2,8 |
| 4 | `test_baseline_job.py` | 34 | 48,3 sn | %5,1 | 120,9 sn | 31,3 sn | Aynı backtest (CPU) + sunucu kapanışı + iki 429 testi |
| 5 | `test_report_feed.py` | 19 | 45,3 sn | %4,7 | 115,7 sn | — | CPU: test başına 1–2 `run_baseline`. Kapsama ×2,6 |
| 6 | `test_sdk_probe.py` | 31 | 34,8 sn | %3,6 | 34,9 sn | 0,5 sn | Beş 429 testinde SDK'nın gerçek 3 sn uykusu (18,5 sn) + 31 kapanış |
| 7 | `test_backtest.py` | 21 | 29,1 sn | %3,0 | 66,0 sn | — | CPU: `test_no_edge_data_produces_no_edge_on_average` tek başına 15,4 sn |
| 8 | `test_artifact_roundtrip.py` | 39 | 28,9 sn | %3,0 | 30,6 sn | 1,6 sn | Test başına 2 sunucu × 0,5 sn kapanış |
| 9 | `test_shadow_http.py` | 8 | 22,2 sn | %2,3 | 22,2 sn | 0,2 sn | `[429]` testi 18,07 sn: sınırlanmamış istemci, varsayılan 3 deneme × 3 sn × 2 sembol |
| 10 | `test_shadow_gate.py` | 63 | 21,8 sn | %2,3 | 23,3 sn | 2,1 sn | 63 × 0,35 sn kapanış beklemesi |

Sıradakiler: `test_pilot_quality` 20,1 → 1,1; `test_feed_comparison` 18,5 → 2,7; `test_baseline_diagnostic` 16,4 → 1,8; `test_alpaca_contract` 15,2 → 0,9; `test_holdout_commitment` 14,6 (CPU, kapsamalı 30,2); `test_paper_probe` 9,7 → 0,3; `test_baseline_cli_smoke` 9,7 → 6,7 (alt süreç başlatma). Kalan 31 dosyanın toplamı 7,2 sn.

En yavaş testler (kapsamasız, çağrı süresi):

| Süre | Test | Sebep |
|---|---|---|
| 22,7–29,8 sn (17 test) | `test_shadow_job.py`: `test_a_live_pure_mismatch_marks_the_day`, `test_no_data_path_leaks_...[quotes/clock/sip-bars]`, `test_a_turn_never_runs_after_its_minute[*]`, `test_a_full_day_is_observed_...` ve diğer tam gün testleri | Nagle beklemesi. Aynı test yalnız `TCP_NODELAY` ile 4–6 sn |
| 18,07 sn | `test_shadow_http.py::test_a_failing_data_endpoint_is_recorded_as_unknown_without_leaks[429]` | SDK yeniden deneme uykusu, 6 × 3 sn |
| 15,38 sn | `test_backtest.py::test_no_edge_data_produces_no_edge_on_average` | CPU, çok günlük backtest |
| 10,8–12,4 sn (3 test) | `test_shadow_job.py` veri hatası testleri | Nagle (bar yanıtı hata olduğu için istek sayısı yarı) |
| 9,5–10,1 sn (4 test) | `test_report_feed.py`, `test_baseline_run.py` (iki `run_baseline`) | CPU |
| 3,02–6,10 sn (12 test) | 429 yanıtı kuran testler (`sdk_probe`, `baseline_job`, `baseline_diagnostic`, `pilot_quality`, `feed_comparison`) | `alpaca/common/rest.py:133` `time.sleep(self._retry_wait)`, 3 sn |

Dağılım: 973 test 0,05 sn'nin altında (toplam 6,2 sn). 265 test 0,25–0,6 sn aralığında (138,1 sn): bu, 0,5 sn'lik kapanış beklemesinin imzası. 60 test 3 sn'nin üstünde (673,4 sn, %70,5).

### Sebeplerin kanıtı

- **Nagle + gecikmeli ACK.** `tests/alpaca_stub.py:331` `protocol_version = "HTTP/1.1"` (keep-alive); `:341-342` başlığı ve gövdeyi iki ayrı `send` ile yazar. İkinci yazım, ilkinin ACK'ini bekler; istemci ACK'i ≈40 ms geciktirir. Aynı yazma deseniyle 150 istekli mikro ölçüm: **45,33 ms/istek → 0,65 ms/istek** (`disable_nagle_algorithm = True`). Diğer dört dosyadaki altı işleyici HTTP/1.0'dır (yanıt başına bağlantı kapanır), onlarda bekleme yok: 1,0 ms/istek.
- **Kapanış beklemesi.** `serve_forever()` varsayılan `poll_interval=0.5` ile çağrılıyor (`alpaca_stub.py:436`, `test_shadow_collect.py:115`, `test_shadow_gate.py:89`, `test_artifact_roundtrip.py:150`, `test_paper_probe.py:42`). `shutdown()` seçicinin süresi dolana kadar bekler. Ölçüm: ortalama **500,7 ms**, `poll_interval=0.01` ile 10,1 ms.
- **SDK uykusu.** `alpaca/common/constants.py:11-13`: 3 deneme, 3 sn, kodlar 429 ve 504. `sdk_compat.bound_transport` denemeyi 1'e indirir ama bekleme 3 sn kalır.
- **Kapsama yükü.** Bekleme ağırlıklı dosyalarda ×1,0–1,1; CPU ağırlıklı backtest dosyalarında ×2,3–2,8 (boşta yeniden ölçüm: `test_backtest` + `test_report_feed` 68,6 → 191,5 sn). Süit geneli ×1,40.

## 3. Hızlandırma önerileri (öncelik sırasıyla)

| # | Değişiklik | Dosyalar | Kazanç | Test gücüne risk | Dondurma | Boy |
|---|---|---|---|---|---|---|
| Ö1 | Sahte Alpaca sunucusunda `TCP_NODELAY` | `tests/alpaca_stub.py` | **Ölçüm:** `test_shadow_job.py` 461,9 → 104,2 sn (yalnız bu değişiklik, aynı yük altında) | Yok. İstek ve yanıt içeriği aynı; yalnız taşıma gecikmesi kalkar | Dokunmaz | S |
| Ö2 | `serve_forever(poll_interval=0.01)` | `tests/alpaca_stub.py`, `test_shadow_collect.py`, `test_shadow_gate.py`, `test_artifact_roundtrip.py`, `test_paper_probe.py` | **Ölçüm:** yalnız bundan etkilenen dört dosya 139,1 → 17,5 sn | Yok. Sunucu davranışı aynı | Dokunmaz | S |
| Ö3 | SDK'nın yeniden deneme uykusunu sanallaştıran `autouse` fixture | `tests/conftest.py` | **Ölçüm:** 13 testteki 58,1 sn kalkar (`test_sdk_probe` 34,8 → 0,5 sn; `test_shadow_http` 22,2 → 0,2 sn, Ö1–Ö2 ile birlikte) | Düşük. Deneme sayısı ve istek sırası aynı; `state.paths().count(...) == 2` iddiası yeşil. SDK iç adı değişirse `monkeypatch.setattr` gürültülü biçimde kırılır | Dokunmaz | S |
| Ö4 | `test_baseline_run.py`'de aynı girdili 5 `run_baseline` çağrısını modül kapsamlı tek fixture'a toplamak (`:118, :135, :182, :232, :240`) | `tests/test_baseline_run.py` | **Tahmin:** kapsamasız ≈18 sn, kapsamalı ≈50 sn (çağrı başına ölçülen 4,6 sn × 4, dosyanın ölçülen kapsama katsayısı ×2,8) | Düşük. Sonuç salt okunur kullanılmalı (derin kopya); belirlenimcilik `test_the_same_dataset_gives_a_byte_identical_report` ile ayrıca sabit. Dosya denetimli çağrılar (`:199, :217`) taze kalır | Dokunmaz | S |
| Ö5 | `pytest-xdist` (bkz. §4) | `pyproject.toml`, `requirements-dev.lock`, `Makefile`, `ci.yml` | **Tahmin:** Ö1–Ö3 sonrası kalan CPU ağırlıklı kısımda 4 çekirdekte 2,5–3 kat | Sıra bağımlılığı gizliyse ortaya çıkar (bu bir kazanç). Kapsam eşiği korunur | `make lock` `requirements.lock`'u da yeniden yazar (dondurulmuş ve kampanya parmak izinde) | M |
| Ö6 | pytest geçici kökünü tmpfs'e almak (`PYTEST_DEBUG_TEMPROOT=/dev/shm`) | `Makefile`, `ci.yml` (`env:`) | **Ölçüm:** SQLite ağırlıklı üç dosyada 110,3 → 103,3 sn (%6). CI diskinde ölçülmedi | Yok. Hiçbir test elektrik kesintisine dayanıklılık ölçmüyor | Dokunmaz | S |

**Ö1–Ö3 birlikte (ölçüm):** sunucu kullanan 15 dosya 791,0 → **133,0 sn**, 582 test yeşil. Çalışma kopyasında altı ağır dosya dışındaki 1335 test 53,65 sn'de yeşil. `ruff check`, `ruff format --check` ve `mypy` temiz; `test_architecture.py` yeşil.
**Tam süit beklentisi (`tahmin`):** kapsamasız ≈300 sn (53,7 + ağır altı dosya 246 sn); kapsamalı 1339 − 658 ≈ 680 sn (≈11 dk). CI `quality` işi için orantılı beklenti ≈9 dk; CI'da ölçülmedi.
**Sıra önerisi:** Ö1–Ö3 tek PR (yalnız `tests/`, dondurmaya takılmaz). Yeniden ölçüm. Süre hâlâ rahatsız ediyorsa Ö4, sonra Ö5.

Değişiklik çalışma kopyasında commit edilmeden duruyor (`git diff --stat`: 6 dosya, +46/−5). Özü:

```diff
# tests/alpaca_stub.py
+STUB_POLL_SECONDS = 0.01
     class Handler(BaseHTTPRequestHandler):
         protocol_version = "HTTP/1.1"
+        disable_nagle_algorithm = True
-    thread = threading.Thread(target=server.serve_forever, daemon=True)
+    thread = threading.Thread(
+        target=server.serve_forever, kwargs={"poll_interval": STUB_POLL_SECONDS}, daemon=True
+    )
# test_shadow_collect.py:115, test_shadow_gate.py:89, test_artifact_roundtrip.py:150,
# test_paper_probe.py:42: aynı `kwargs` + `from alpaca_stub import STUB_POLL_SECONDS`

# tests/conftest.py
+SDK_RETRY_SLEEPS: list[float] = []
+@pytest.fixture(autouse=True)
+def _sdk_retry_wait_is_virtual(monkeypatch: pytest.MonkeyPatch) -> None:
+    import alpaca.common.rest as sdk_rest
+    SDK_RETRY_SLEEPS.clear()
+    monkeypatch.setattr(sdk_rest, "time", SimpleNamespace(sleep=SDK_RETRY_SLEEPS.append))
```

Fixture SDK modülündeki `time` adını değiştirir, sürecin `time.sleep`'ini değil. Alt süreçle çalışan duman testleri etkilenmez.

**Denendi, önerilmiyor:**
- `COVERAGE_CORE=sysmon`: Python 3.12'de dal ölçümünü desteklemiyor (`CoverageWarning: sys.monitoring can't measure branches in this version`); uyarı `filterwarnings = error` yüzünden hataya dönüyor. `branch = true`'yu kapatmak kapıyı zayıflatır, önerilmez. Python 3.14 sözleşmesi gündeme gelirse yeniden bakılır.
- `test_soak.py` için fixture paylaşımı: dosya toplam 2,4 sn'nin altında, uğraşa değmez.

## 4. Paralellik değerlendirmesi

**xdist'e uygunluk (kod okuması):**
- Port: beş dosyadaki sunucuların hepsi `("127.0.0.1", 0)` ile geçici port alıyor; sabit port yok.
- Dosya: yazımların hepsi `tmp_path` altında; depo ağacına yazan test bulunmadı. Depodan okuma (parmak izi, `git ls-files`) salt okunur.
- Ortam: `os.environ` yalnız `monkeypatch.setenv/delenv` ile değişiyor; `chdir` yalnız `monkeypatch.chdir` (2 test).
- Süreç geneli durum: `tests/fs_audit.py` denetim kancası, `sys.modules["shadow_report"]` ve `logging.disable` çağrıları süreç içinde kalır; xdist işçileri ayrı süreçtir. `logging.disable` çağıran üç test çıkışta `NOTSET`'e dönüyor ya da `NOTSET` ile başlıyor.
- Çapraz içe aktarma (`from test_runner import ...`) üst düzeydedir, işçi başına sorunsuz yüklenir.

**Kanıt:** iki tam süit aynı çalışma kopyasında aynı anda koştu, ikisi de 1528 geçti / 6 atlandı. Hedefli koşularda dosyalar farklı sırada ve alt kümeler hâlinde yeşil kaldı.
**Doğrulanmadı:** `pytest-xdist` kurulu değil (`requirements-dev.lock`'ta yok); `-n` ile koşu yapılmadı, paylaşılan ortama paket kurulmadı. Dosya içi rastgele sıra da denenmedi. İlk denemede `--dist loadfile` önerilir: dosya içi sırayı korur.

**xdist eklemenin gerektirdikleri:**
1. `pyproject.toml` `dev` listesine `pytest-xdist`, ardından `make lock`. Bu hedef **iki kilidi de** yeniden üretir. `requirements.lock` 2 Aralık'a kadar dondurulmuş ve `IMPLEMENTATION_ROOT_FILES` üzerinden kampanya parmak izine giriyor: dosyanın bayt bayt aynı kaldığı `git diff --exit-code requirements.lock` ile gösterilmeli ya da iş dondurma sonrasına bırakılmalı.
2. Kilit testleri (`test_architecture.py:584-700`) yeni paketi kilitte arar; kilit `make lock` ile üretildiyse yeşil kalması beklenir (doğrulanmadı).
3. `Makefile` `cov` hedefi ve `ci.yml` `-n auto` alır. `test_architecture.py:973` komut metninde `pytest --cov` alt dizgesini arıyor: `pytest --cov=tlab ... -n auto` yeşil, `pytest -n auto --cov=...` kırmızı.
4. Kapsam: `pytest-cov` işçi verisini birleştirir; %80 eşiği aynı çalışır.

**Yeni bağımlılıksız seçenek, CI'ı işlere bölmek — önerilmiyor.** `test_architecture.py` şunları sabitliyor:
- `:953-974`: `quality` adlı tek iş dört kapıyı (`ruff check`, `ruff format --check`, `mypy`, `pytest --cov`) birlikte taşır. Testleri başka işe taşımak bu testi ve `main` koruma kuralındaki zorunlu denetimi değiştirir.
- `:1625-1662`: yalnız `checkout@v7` ve `setup-python@v7`, bilinen girdilerle. Parçalar arası kapsam birleştirmek artefakt indirme action'ı ister; bunun sözleşmesi yok.
- `:1507-1565` yükleme sözleşmesi (sürüm, girdiler, saklama süresi tablosu), `:1758-1765` her iş `ubuntu-24.04`, `:1002-1038` salt okunur token. Yeni iş bunların hepsine uymak zorunda.
Lint ve mypy toplam 10 sn olduğu için onları ayırmanın kazancı yok. Ö1–Ö3 sözleşmeye dokunmadan sürenin yarısını alıyor; bölme bu aşamada maliyetine değmez.

## 5. Önemli kapsam boşlukları

Tablo bu raporun kendi kapsamalı koşusundan (`main` @ `47a2a7d`; toplam %90,65). `makecheck-63j.log` başka bir daldandır (#63), satır numaraları `main` ile uyuşmaz.

| Modül | Kapsam | Güvenlik açısından önemli eksik satırlar | Zararsız olanlar |
|---|---|---|---|
| `execution/alpaca_broker.py` | %75 | `190-192` bekleyen emirler okunamazsa `BrokerError`; `242-246` + `363-364` `close_position` hata eşlemesi ve "pozisyon yok" metin eşleşmesi; `259-269` sembole göre iptal (bayat giriş iptalinin gerçek adaptör yolu, hiç koşmuyor); `254-256` toplu iptal hatası; `315-317` gerçekleşmeler okunamazsa | `91`, `140-155` takvim biçim dalları, `169-170`, `276-277` |
| `journal/writer.py` | %76 | `190-192` emir kaydı yazılamazsa (write-ahead'in hata yolu); `268-270` kill-switch kaydı yazılamazsa; `250-252` gerçekleşme kaydı; `289-291` işlem kaydı | `41-42`, `58-59` (git), `116-118`, `128-130`, `213` |
| `engine/runner.py` | %89 | `155-178` `run_forever` tamamı (hata sonrası ayakta kalma, geri çekilme, `KeyboardInterrupt`); `522-528` journal hatasında emir gönderilmemesi; `462-464` kapatma öncesi iptal/mutabakat hatası; `353-355` kesinleşmemiş emrin brokerda bulunup onaylanması; `264-266` gerçekleşmeler alınamazsa | `92-98` özet metni, `453`, `562`, `725-726` |
| `risk/gate.py` | %97 | `87` bekleyen emir vetosu (kapının kendi savunması; bugün yalnız strateji `has_exposure` ile koruyor); `189` sınırlar bir hisseye yetmezse veto | — |
| `journal/db.py` | %83 | `96-100` göç hatasında `ROLLBACK` ("yarım şema bırakmaz" iddiası testsiz) | `34-36` |
| `journal/queries.py` | %85 | `32-34`, `50-52` okuma hatasının `JournalError`'a sarılması | — |
| `data/market.py` | %86 | `175-176`, `187-189` bozuk kotasyon → `DataError` (kapı vetosuna giden yol) | `83-90` |
| `cli.py` | %67 | `337-339` `run` komutunun `run_forever` dalı ve kapanışta `end_run` | `53-80` `config`, `354-467` `backtest`/`summary` çıktıları |

%90 altındaki diğer modüller karar yolunda değil; eksikleri sabit hata satırları ve `main()` giriş noktaları: `baseline_job` %81, `data/cached` %82, `pilot_quality` %83, `core/calendar` %84, `sdk_probe` %86, `baseline_diagnostic` %87, `data/cache` %89.

Üç yolun bugünkü davranışı süitin kendi sahteleriyle yoklandı (karalama testi, commit edilmedi):
- **Kill-switch kaydı yazılamazsa** (`daily_state`'e `INSERT`'i engelleyen tetikleyici): `run_once` `JournalError` fırlatır, `closed == []`, `cancelled == []`. Pozisyon kapanmaz, emir iptal edilmez. Kök sebep Hata Avı 1 B1 ile aynı; `test_kill_switch_durability.py` yalnız okuma hatasını sabitliyor, yazma hatasını değil.
- **Emir kaydı yazılamazsa:** emir gönderilmez, not `SPY: journal yazilamadi`. Davranış doğru ama testsiz.
- **Kapı, bekleyen emir ve 50 birimlik alım gücüyle:** ikisinde de veto. Davranış doğru ama testsiz.

## 6. Zayıf testler ve eksik negatif yollar

AST taraması: 904 üst düzey test fonksiyonunun hepsinde `assert`, `pytest.raises` ya da iddialı yardımcı var; iddiasız test bulunmadı. Süit genel olarak güçlü. Bulgular:

1. **`test_runner.py:592` `test_order_is_journaled_before_it_is_sent` sırayı sabitlemiyor.** Test, gönderim başarısız olduktan sonra `submitting` satırının varlığına bakıyor. Mutasyon: `_handle_intent`'te önce `submit_bracket`, hata olursa ve sonrasında `record_order`. `test_runner`, `test_soak`, `test_kill_switch_durability`, `test_cli_run`, `test_queries`, `test_journal`, `test_shadow_broker` ve gerçek SDK yolu testi: **109 geçti, 0 kaldı.** Öneri: `submit_bracket` çağrıldığı anda journal'da o `client_order_id` için `submitting` satırını arayan sahte broker.
2. **`test_gate.py`'de kapının iki vetosu yok** (`gate.py:87`, `:189`). `pending_orders`, `reserved_exposure`, `reserved_symbols`, `unknown_order_risk` alanları testlerde hiç adıyla geçmiyor; yalnız runner üzerinden dolaylı kullanılıyor. Satır 87 hiç çalışmadığı için silinse hiçbir test düşmez.
3. **Journal yazma hatası yolları testsiz** (`runner.py:522-528`, `writer.py:190-192`, `:268-270`). §5'teki üç yoklama doğrudan karakterizasyon testine çevrilebilir. Yazma hatasında kapanışın sürmesi `src/` düzeltmesidir, dondurma sonrasına kalır.
4. **`run_forever` hiç test edilmiyor** (`runner.py:155-178`). "Tek turun hatası döngüyü öldürmez" ve kademeli bekleme iddiaları korumasız. `time.sleep` enjekte edilemediği için test `monkeypatch` ister.
5. **`test_alpaca_contract.py:313` `test_timeouts_and_retries_do_not_leak_raw_exceptions` adını karşılamıyor:** tek atımlık 503 kullanıyor; 503 SDK'nın yeniden deneme kodlarında (429, 504) yok, zaman aşımı da üretilmiyor. `cli.py:283` canlı `run` yolundaki istemciye `bound_transport` uygulanmıyor (Hata Avı 1'de kayıtlı); asılı kalan broker çağrısı için test yok.
6. **Gerçek adaptörün iptal ve kapatma yolları** (`alpaca_broker.py:242-246`, `:259-269`, `:363-364`): `cancel_open_orders(symbol)` ve "pozisyon yok" eşlemesi sahte sunucuda hiç koşmuyor. `_is_position_missing` hata metnine dayanıyor; metin değişirse kapanış `BrokerError` verir ve bunu yakalayacak test yok.
7. **Git okunamazsa iki kapı sessizce atlanıyor:** `test_architecture.py:295` (uygulanmış göçler) ve `:452` (anahtar tarayıcı) `pytest.skip` çağırıyor. CI'da git her zaman var, ama atlanan bir güvenlik kapısı yeşil görünür. Öneri: `CI` ortam değişkeni varken atlamak yerine başarısız olmak (kapıyı sıkılaştırır).
8. **`test_alpaca_contract.py:485-487`** iddiası gereksiz dolambaçlı: ilk terim her zaman yanlış, sonuç fiilen "hiç POST yok". Doğru çalışıyor; tek satıra indirilmeli.

Sağlam bulunan: kapatma sırası. "Önce pozisyonu kapat, sonra emirleri iptal et" mutasyonu `test_shutdown_waits_for_cancel_confirmation` ve `test_shutdown_refreshes_positions_after_cancel` tarafından yakalandı (2 kırmızı).
Atlanan 6 test `test_measurement_freeze.py`'nin tarihsel denetimleridir; gerekçesi dosyada kayıtlı, sorun değil.

## 7. Doğrulanmayanlar ve kanıt

- Tam süit Ö1–Ö3 ile baştan sona koşulmadı (yönetim talimatı). Değişiklikle koşulan: 1428/1534 test. Koşulmayan 106 test (`test_baseline_run`, `test_report_feed`, `test_backtest`, `test_holdout_commitment`) sunucu ve SDK kullanmıyor; onlara yalnız `autouse` fixture dokunuyor.
- "Önce" süreleri yük altında, "sonra" süreleri boş makinede ölçüldü. Beklemeler yükten bağımsızdır; CPU ağırlıklı iki dosyada yük etkisi %8 ölçüldü (74,4 → 68,6 sn).
- CI süreleri ve GitHub runner diski bu raporda ölçülmedi; CI rakamları orantılı tahmindir.
- Ö4, Ö5 denenmedi; kazançları tahmindir.
- Ham ölçümler oturum scratchpad'inde: `a5-durations.log`, `a5-junit.xml`, `a5-cov.log`, `a5-cov-junit.xml`, `a5-exp-after.log`, `a5-exp-shadowjob-nodelay.log`, `a5-covcore.log`, `a5-proposed.diff`, `a5-scripts/`.
