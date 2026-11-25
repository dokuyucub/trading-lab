# S1 — Hata Avı 1: yürütme çekirdeği

Tarih: 2026-11-25 · Kod: `claude/killswitch-fix` @ `a48daae` (main + #63) · Salt okuma; ağ, broker, iş akışı yok.
Kapsam: `engine/{runner,reconciler}.py`, `execution/{broker,alpaca_broker}.py`, `risk/gate.py`, `journal/*`, `core/{types,clock}.py`, `cli.py run`.
Yöntem: kod okuma + sahte broker ile karalama testleri (`tests/test_scratch_s1_*.py`, çalışma kopyasında, commit edilmedi).
Kod parçaları o dosyalardan **kısaltılmıştır**, sayılar sentetiktir. Her test doğru davranışı bekler ve bugün **KIRMIZI**dır.

## 1. Sonuç

- 12 bulgu yeniden üretildi (`DOĞRULANDI`), 2 bulgu kod okumasına dayanıyor (`OLASI`). Mükerrer emir yolu bulunmadı.
- En ağır sınıf, koruma adımının hiç çalışmaması: journal hatası, zaman aşımı olmayan HTTP ve 8 katlık bekleme kill-switch'i ve kapanışı durdurabiliyor (B1, B4, B5).
- İkinci sınıf, stopsuz pozisyonun fark edilmemesi: kısmi dolmuş giriş ve gece taşınan pozisyon saatlerce stopsuz kalıyor, döngü tepki vermiyor (B2, B3).
- #63'ün koruma kanıtı Alpaca'nın bacak görünümünde (`held`, açık listede yok) hiç sağlanamıyor (B6); backtest ile canlı pozisyon sayısında ayrışıyor (B7).
- Risk kapısı aritmetiği, seans/DST/yarım gün mantığı ve write-ahead sırası sağlam bulundu (bölüm 3).

## 2. Bulgular (önem sırasıyla; `OLASI` olanlar sonda)

Ortak: `from test_runner import NOW, FakeBroker, FakeClock, FakeMarket, breakout_bars, build_runner`;
`from test_entry_cancel_race import prepare, settle, legs, hold_position`; `config`/`conn` fixture'ları `test_runner.py`'deki gibi.
`CLOSE = SESSION_OPEN + 390 dk`, `FLATTEN_WINDOW = SESSION_OPEN + 385 dk`, `long_spy()` = 10 adetlik SPY long.

### B1 — Journal hatası kill-switch'in ve gün sonu kapanışının önüne geçiyor · YÜKSEK · DOĞRULANDI · Efor S
- **Yer:** `runner.py:348-351` (`_resolve_unconfirmed`, `_reconcile`) → `:490, :501, :507, :418, :420, :431, :434`; kontroller `:353-359`.
- **Senaryo:** journal yazılamıyor (disk dolu, salt okunur, kilitli). Açık pozisyon var, broker yeni bir dolum bildiriyor. `record_fill` `JournalError`
  fırlatır, `run_once` `:351`'de biter. Zarar sınırı ve `must_flatten` hiç değerlendirilmez; her tur aynı yerde ölür. #63 yalnız `daily_state` okumasını
  kapattı (`test_kill_switch_durability.py:57-61` yalnız o tabloyu düşürüyor); aynı sınıf hata iki satır yukarıda duruyor.
```python
@pytest.mark.parametrize("case", ["eod_flatten", "loss_limit"])
def test_f1(case, config, conn):
    account = make_account(equity=97_000, last_equity=100_000) if case == "loss_limit" else make_account()
    broker = FakeBroker(account=account, positions=[long_spy()])
    broker.fills.append(entry_fill(NOW - timedelta(minutes=10)))        # journal'da henüz olmayan dolum
    runner = build_runner(config=config, conn=conn, broker=broker, market=FakeMarket(),
                          now=FLATTEN_WINDOW if case == "eod_flatten" else NOW)
    conn.execute("PRAGMA query_only = ON")                              # bundan sonra her yazma hata verir
    with contextlib.suppress(Exception): runner.run_once()              # JournalError: Gerceklesme kaydedilemedi
    assert broker.closed == ["SPY"]                                     # KIRMIZI (iki durumda da): []
```
- **Düzeltme:** kill-switch ve `must_flatten` adımlarını journal defter işlerinden önceye al ya da `:348-351`'i `(JournalError,
  sqlite3.Error)` için sar: hata → `_block_entries`, tur sürer. Test: `orders`/`fills` yazılamazken kapanış.

### B2 — Kısmi dolmuş giriş saatlerce stopsuz kalıyor, döngü tepki vermiyor · YÜKSEK · DOĞRULANDI · Efor M
- **Yer:** `runner.py:548` (pozisyonu olan sembolde bayat iptal atlanır), `:342-385` (normal turda koruma kontrolü yok).
- **Senaryo (yarış yok):** giriş kısmen dolar. Alpaca'da kısmi dolmuş ebeveynin etkin bacağı yoktur. Sonraki turda sembol `positions`
  içindedir; kalan miktar hiç iptal edilmez, stop aranmaz, not düşülmez. Süre: kalan miktar dolana ya da 15:50 kapanışına kadar; giriş
  penceresi 11:30'da bittiği için **en kötü durumda ~6 saat**. Arada tek arka duvar hesap geneli zarar sınırıdır.
- **Hafifleten yapı:** kalan miktar limit fiyatında, piyasa ile stop arasında bekler; düzenli bir ters hareket önce onu doldurur ve bacaklar etkinleşir.
  Açık kalan: boşluk/işlem durdurma, kalan miktarın bot dışında iptali ve kalan miktarın sinyal bayatladıktan saatler sonra dolması.
```python
def test_f12(config, tmp_path):
    s = prepare("ttl", config, tmp_path); filled = s.order.qty // 2
    s.broker.open_orders = [s.entry.model_copy(update={"status": "partially_filled", "side": Side.BUY,
        "filled_qty": float(filled), "remaining_qty": float(s.order.qty - filled), "limit_price": s.order.limit_price})]
    hold_position(s.broker, s.order, filled)                            # pozisyon görünüyor, etkin bacak yok
    seen = []
    for minutes in (1, 30, 60, 120, 180, 240, 300):
        s.runner.clock.set(NOW + timedelta(minutes=minutes)); r = s.runner.run_once()
        seen += [r.summary()] if (r.halted or r.cancelled or r.flattened or r.notes) else []
    assert seen                                                         # KIRMIZI: 5 saatte iptal/kapatma/not yok
```
- **Düzeltme:** pozisyonu görünen ve hâlâ `partially_filled` olan kendi girişimizin kalanını kısa bir süre sonra mevcut iptal izleme yoluyla (yalnız
  giriş kimliği) iptal et; kesinleşince korumayı B6'daki gibi doğrula; yoksa yalnız o sembolü kapat (günü kilitlemeden).

### B3 — Stopsuz pozisyon normal turda aranmıyor; gece taşınan pozisyon ertesi gün korumasız · YÜKSEK · DOĞRULANDI · Efor M
- **Yer:** `types.py:369` (`time_in_force=DAY`, `from_intent` değiştirmez) → `alpaca_broker.py:220-222`; `runner.py:971-985` (`_flatten_all` önce bütün emirleri
  iptal eder, iptal kesinleşmediyse kapatmayı sonraki tura bırakır); `runner.py:338-340` (borsa kapalıyken açık pozisyon uyarısı yok).
- **Senaryo:** gün sonu kapanışı tamamlanamaz (B1/B4/B5, süreç ölümü ya da son turda iptalin asenkron kalması). DAY bacaklar kapanışta düşer ya da `_flatten_all`
  onları zaten iptal etmiştir. Ertesi gün pozisyon brokerdadır, çıkış emri yoktur. Döngü yalnız o sembole giriş açmaz; 15:50'ye kadar stop koymaz, kapatmaz, not
  düşmez, **başka sembolde yeni giriş açar**. AGENTS §3.5'in "bot çökse de koruma borsada" güvencesi gün sınırında biter.
```python
def test_f2a(config, conn):                                             # brokerda hiç çıkış emri olmayan AAPL pozisyonu
    broker = FakeBroker(positions=[Position(symbol="AAPL", side=Side.BUY, qty=10, avg_entry_price=100.0, current_price=100.0)])
    r = build_runner(config=config, conn=conn, broker=broker, market=FakeMarket(bars_by_symbol={"SPY": breakout_bars()})).run_once()
    assert r.halted or broker.closed or any("AAPL" in n for n in r.notes)   # KIRMIZI; özet: emir=1, not yok

def test_f2b(config, conn):  # AsyncCancelBroker: cancel_open_orders emirleri bir okuma boyunca pending_cancel bırakır
    broker = AsyncCancelBroker(positions=[long_spy()], open_orders=[stop_leg()])
    runner = build_runner(config=config, conn=conn, broker=broker, market=FakeMarket(), now=CLOSE - timedelta(seconds=30))
    assert runner.run_once().flattened == 0                              # 15:59:30: bacak iptal edildi, kapatma "bekliyor"
    runner.clock.set(CLOSE + timedelta(seconds=30)); broker.clock = FakeClock(is_open=False); runner.run_once()
    runner.clock.set(SESSION_OPEN + timedelta(days=1, minutes=30)); broker.clock = FakeClock(is_open=True, next_close=...)  # ertesi gün 10:00
    assert not broker.positions or runner.run_once().halted or any(o.stop_price for o in broker.open_orders)   # KIRMIZI
```
- **Düzeltme:** her turda değişmez kontrolü: her pozisyon için çalışan bir stop kanıtı (B6); yoksa o sembolü hemen kapat ya da bağımsız stop gönder ve ERROR yaz. Seans
  başında emirsiz pozisyon → 15:50 beklenmeden kapat. Kapanış sonrası ilk turda açık pozisyon varsa ERROR. Doğrulanmadı: DAY bacakların kapanışta düştüğü (Alpaca belgesi).

### B4 — Broker ve veri çağrılarında zaman aşımı yok; döngü sessizce sonsuza dek asılabilir · YÜKSEK · DOĞRULANDI · Efor S
- **Yer:** `alpaca_broker.py:54-56`; kurulu `alpaca-py 0.44.0`, `common/rest.py:195`: `session.request` çağrısına `timeout` verilmiyor.
  `run_forever` (`runner.py:294-315`) içinde bekçi yok. Veri istemcisi aynı `RESTClient` sınıfını kullanıyor.
- **Senaryo:** istek gittikten sonra bağlantı sessizce kopar. `requests` süresiz bekler; hata oluşmaz, log yazılmaz,
  sonraki tur gelmez. Kill-switch ve gün sonu kapanışı çalışmaz; pozisyon geceye taşınır (B3).
```python
def test_f4(monkeypatch):
    seen = {}
    def capture(self, method, url, **kw): seen.update(kw); return _Reply()   # _Reply: 200 + /v2/clock gövdesi
    monkeypatch.setattr(requests.Session, "request", capture)                # istek yakalanır, GÖNDERİLMEZ
    AlpacaBroker("k", "s", paper=True, base_url="http://127.0.0.1:9").get_market_clock()
    assert seen.get("timeout") is not None                                   # KIRMIZI: yalnız allow_redirects, params
```
- **Düzeltme:** iki istemcinin oturumuna varsayılan `(bağlanma, okuma)` zaman aşımı veren bir `HTTPAdapter` tak; süreç dışında da
  bir bekçi (son başarılı tur zamanı) ekle. Asılı kalmanın kendisi üretilmedi; kanıt eksik parametredir.

### B5 — 8 katlık bekleme, 6,5 dakikalık kesintiyi kaçırılmış gün sonu kapanışına çeviriyor · YÜKSEK · DOĞRULANDI · Efor S
- **Yer:** `runner.py:67`, `:312-315`. Bekleme `poll × min(8, 2^hata)`; kapanış tamponu 10 dk (`config/base.yaml`).
- **Senaryo:** kesinti 15:46:30–15:53:00. Turlar 15:46:30, 15:48:30, 15:52:30 (üçü de hata), sonraki 16:00:30: borsa kapalı. Kesinti kapanıştan
  7 dk önce bittiği hâlde kapanış hiç çalışmaz. `--poll 120` ile bekleme 16 dk olur ve tampondan büyüktür. Aynı bekleme zarar sınırının tepki
  süresini de 1 dk'dan 8 dk'ya çıkarır. Giriş yolundaki kalıcı bir istisna (B10) da aynı beklemeyi tetikler.
```python
# OutageBroker.get_market_clock: now < outage_until iken BrokerError; sonra FakeClock(is_open=now < CLOSE, next_close=CLOSE)
@pytest.mark.parametrize("backoff", [runner_module.MAX_BACKOFF_FACTOR, 1])
def test_f5(backoff, config, conn, monkeypatch):
    broker = OutageBroker(positions=[long_spy()], outage_until=CLOSE - timedelta(minutes=7))
    runner = build_runner(config=config, conn=conn, broker=broker, market=FakeMarket(), now=CLOSE - timedelta(minutes=13, seconds=30))
    broker.now_fn = runner.clock.now
    def fake_sleep(sec):
        runner.clock.set(runner.clock.now() + timedelta(seconds=sec))
        if runner.clock.now() > CLOSE + timedelta(minutes=2): raise KeyboardInterrupt
    monkeypatch.setattr(runner_module.time, "sleep", fake_sleep); monkeypatch.setattr(runner_module, "MAX_BACKOFF_FACTOR", backoff)
    with pytest.raises(KeyboardInterrupt): runner.run_forever(poll_seconds=60)
    assert broker.closed == ["SPY"]                   # backoff=8 KIRMIZI, backoff=1 YEŞİL
```
- **Düzeltme:** beklemeyi kısalt değil, ayır: log bastırma kalsın, uyku `poll`'u geçmesin; en azından `flatten_at −
  2×azami bekleme` sonrasında çarpan 1 olsun. Config doğrulaması: `8 × poll < tampon / 2`.

### B6 — Koruma kanıtı Alpaca'da hiç sağlanamıyor: dolumlu her iptal yarışı günü kapatır · ORTA · DOĞRULANDI (kod), varsayım dış araştırma · Efor M
- **Yer:** `runner.py:768` (`_fill_coverage` stopu `list_open_orders()` içinde arar), `:88`, `:153-173`; `alpaca_broker.py:182-194` (düz `status=open`, `nested` yok).
- **Senaryo:** tam dolumdan sonra stop bacağı `held` olur ve açık listede dönmez; yalnız hedef (`new`) görünür. `stop_coverage` her zaman `NONE` verir.
  `CancelOutcome.FILLED` canlıda ulaşılamaz: bayat iptal sırasında dolan ve **tam korunan** pozisyon için gün kill-switch ile kapanır, bacaklar iptal edilir, pozisyon
  piyasa emriyle kapatılır.
```python
def test_f13(config, tmp_path):
    s = prepare("ttl", config, tmp_path)
    def full_fill(b):
        settle(b, s.entry, "filled", float(s.order.qty)); hold_position(b, s.order, s.order.qty)
        b.open_orders = [l for l in legs(s.order, stop_qty=s.order.qty) if l.stop_price is None]   # yalnız hedef; stop held, listede yok
    s.broker.on_cancel = full_fill
    r = s.runner.run_once()
    assert not r.halted and s.broker.closed == []     # KIRMIZI: DURDURULDU, toplu iptal + SPY kapatıldı
```
- **Düzeltme:** kanıtı ebeveynden oku: `get_order_by_id(..., nested=True)`; ebeveyn `filled` ve stop bacağı `held`/`new`,
  miktar ≥ pozisyon → korunuyor. Ebeveyn kısmi → bacak yok → B2 yolu. İlk paper günlerinde gözle doğrula.

**Stop bacağını `list_open_orders`'ta görmeye dayanan yerler (koordinatör sorusu):**

| Yer | Bağımlılık | Stop görünmezse |
|---|---|---|
| `runner.py:768` `_fill_coverage` → `stop_coverage` | Stopu görmek zorunda | Her zaman `NONE` → B6 |
| `runner.py:972-985` `_flatten_all` `blocked` kümesi | Kalan bacağı görerek kapatmayı bekletir | `held` stopu göremez → B14 |
| `runner.py:792-803` `_has_orphan_exit` | Kalan çıkış emrini arar | Yalnız hedefi görür; tek kalan `held` stop kaçar (B14 ile aynı kök) |
| `runner.py:1050-1093` `_pending_risk` | Bağımlı değil | Tek bacak doğru düşülür; **iki bacak görünseydi** veto ederdi (B7) |
| `runner.py:475` `_pending_symbols`, `:548` bayat iptal | Bağımlı değil | Pozisyon sembolü zaten kapatır |
| `reconciler.py`, `alpaca_broker.py:321-345` `list_fills` | Bağımlı değil | `status=all, nested=True` ile bacaklar ebeveynin içinde gelir |

### B7 — İkinci çıkış bacağı "bilinmeyen risk" sayılıyor: backtest fiilen tek pozisyon, canlı değil · ORTA · DOĞRULANDI · Efor M (karar gerekir)
- **Yer:** `runner.py:1063, :1078-1091`; `backtest/sim_broker.py:221-231` (bacak yönsüz ve miktarsız
  listelenir); `tests/test_runner.py:934-946` bu vetoyu **istenen** davranış olarak sabitliyor.
- **Senaryo:** `reduction_budget` pozisyon miktarı kadardır; OCO bracket'in iki bacağı toplamda iki katını ister. SimBroker'ın bacağı yön/miktar taşımadığı için
  `unknown=True` olur ve pozisyon açıkken **bütün** yeni girişler "bekleyen emrin maruziyeti bilinmiyor" ile veto edilir. Canlıda yalnız hedef bacağı görünüyorsa
  (B6 varsayımı) veto yok. Sonuç: `max_concurrent_positions: 3` backtest'te 1 gibi davranır; ölçülen sistem ile paper'da koşacak sistem ayrışır.
```python
@pytest.mark.parametrize("order", [["target", "stop"], ["stop", "target"]])
def test_f3(order, config, conn):       # leg(kind): AAPL SELL 10; stop'ta stop_price, target'ta limit_price
    broker = FakeBroker(positions=[AAPL_LONG], open_orders=[leg(k) for k in order])
    runner = build_runner(config=config, conn=conn, broker=broker, market=FakeMarket(bars_by_symbol={"SPY": breakout_bars()}))
    assert runner._pending_risk(broker.open_orders, {"AAPL": AAPL_LONG}) == (0.0, frozenset(), False)
    # KIRMIZI: (0.0, {"AAPL"}, True) → SPY veto; ters sırada (bacak değeri, {"AAPL"}, False) → maruziyet çift sayılır

# test_f3_backtest: iki sembollü Backtest; AAPL kırılımı SPY pozisyonu açıkken gelir (maruziyet sınırı gevşetildi).
#   decisions: AAPL veto "bekleyen emrin maruziyeti bilinmiyor" sayısı 0 beklenir → KIRMIZI: 1; trades yalnız SPY
```
- **Düzeltme:** pozisyonu azaltan emirlerde toplam değil **en büyük** miktarı pozisyonla karşılaştır (OCO kardeşleri tek azaltmadır); SimBroker bacaklarını Alpaca
  görünümüyle (yön, miktar, fiyat) listele. Dondurulmuş ölçümün anlamını değiştirir: ya `max_concurrent_positions: 1` açıkça yazılır ya da yeni, kayıtlı bir ölçüm gerekir.

### B8 — Kesin emir reddi "belirsiz" sayılıyor; tek sembol bütün evreni 5 dakikalık döngülerle kilitliyor · ORTA · DOĞRULANDI · Efor S
- **Yer:** `alpaca_broker.py:235-239` (her hata aynı `BrokerError`), `runner.py:1122-1129, :505-512, :1043-1044, :1062`.
- **Senaryo:** broker emri HTTP 4xx ile reddeder (açığa satılamaz, alım gücü, PDT). Satır `submitting` kalır; 5 dk boyunca `unknown_order_risk` bütün sembolleri veto eder.
  Sonra satır `lost` olur, strateji aynı niyeti yeniden üretir, yine ret. Sinyal sürdükçe (giriş penceresi 120 dk) başka hiçbir sembol emir alamaz. Fail-closed.
```python
def test_f7(config, conn):              # RejectingBroker.submit_bracket: SPY için BrokerError, diğerleri normal
    config = config.model_copy(update={"symbols": ("SPY", "AAPL")}); broker = RejectingBroker()
    runner = build_runner(config=config, conn=conn, broker=broker, market=FakeMarket(bars_by_symbol={s: breakout_bars(s) for s in config.symbols}))
    for minute in range(12):
        runner.clock.set(NOW + timedelta(minutes=minute)); broker.submitted_at = runner.clock.now(); runner.run_once()
    assert [o.symbol for o in broker.submitted] == ["AAPL"]   # KIRMIZI: []; orders: SPY lost×1 + submitting×1; AAPL 10 veto
```
- **Düzeltme:** `sdk_compat.http_status_of` ile 4xx (408/429 hariç) için ayrı `OrderRejected` fırlat; runner
  satırı hemen `rejected` yazar ve o sembolü o gün için (ya da N dakika) dışarıda tutar.

### B9 — Mutabakat penceresi bir takvim günü; hafta sonu/tatil öncesi geç çıkış journal'a hiç düşmüyor · ORTA-DÜŞÜK · DOĞRULANDI · Efor S
- **Yer:** `runner.py:409` (`session_open − 1 gün`), `:338-340` (borsa kapalıyken mutabakat yok); `alpaca_broker.py:330` (`after` gönderim zamanına bakar).
- **Senaryo:** cuma son dakikada ya da süreç kapalıyken oluşan çıkış. Pazartesi pencere pazar 09:30'dan başlar; işlem `trades`'e yazılmaz,
  emir satırı açık kalır. `_reconcile` docstring'indeki "kapalıyken olanlar sonraki açılışta düşer" vaadi tutmuyor.
```python
def test_f6(config, conn):
    friday_open = SESSION_OPEN - timedelta(days=3); broker = FakeBroker()
    runner = build_runner(config=config, conn=conn, broker=broker, market=FakeMarket())     # pazartesi 10:00
    order = BracketOrder(symbol="SPY", side=Side.BUY, qty=10, limit_price=100.0, stop_loss=99.0, take_profit=101.5)
    runner.writer.record_order(order, run_id=runner.run_id)
    broker.fills = [fill(order.client_order_id, Side.BUY, friday_open + timedelta(minutes=40), "limit"),   # cuma 10:10 giriş
                    fill("leg", Side.SELL, friday_open + timedelta(minutes=389, seconds=40), "stop")]      # cuma 15:59:40 çıkış
    assert runner.run_once().trades_recorded == 1     # KIRMIZI: 0
```
- **Düzeltme:** pencereyi journal'daki en eski kapanmamış emrin `submitted_at`'inden (yoksa önceki işlem seansından) başlat; kapanıştan sonra bir tur daha mutabakat yap.

### B10 — Kurulamayan emir turu öldürüyor; karar yazılmıyor · DÜŞÜK · DOĞRULANDI · Efor S
- **Yer:** `runner.py:1109` (`from_intent`, `record_decision`'dan önce), `:1034` (yalnız `JournalError` yakalanır).
- **Senaryo:** stop mesafesi kapıdan geçer (`min_stop_bps: 5`) ama bir fiyat adımından dardır; yuvarlama stop ile girişi eşitler,
  `ValidationError` `run_once`'tan çıkar. Sinyal sürdükçe her tur ölür, sonraki semboller hiç değerlendirilmez, B5 beklemesi başlar.
  Bugünkü evrende (yüksek fiyatlı hisseler) ulaşılamaz; fiyatı ~20'nin altındaki sembolde ulaşılır.
```python
def test_f8(config, conn):   # TightStop.decide(): SPY BUY, giriş ile stop arası 8 bps ve bir fiyat adımından dar
    runner = build_runner(config=config, conn=conn, broker=FakeBroker(), strategies=[TightStop()], market=FakeMarket(..., quote_mid=10.0))
    runner.run_once()        # KIRMIZI: pydantic ValidationError run_once'tan çıkar; decisions tablosu boş
```
- **Düzeltme:** `from_intent` hatasını veto olarak kaydet ("emir kurulamadı"); `_evaluate_universe`'te sembol
  başına beklenmeyen istisnayı yakala. Kapı stop mesafesini yuvarlanmış fiyatlarla ölçsün.

### B11 — İki tur arasında bitmiş işlem "korumasız dolum" sayılıp günü kapatıyor · DÜŞÜK · DOĞRULANDI · Efor S
- **Yer:** `runner.py:783-787` (`required = max(dolum, pozisyon)`; pozisyon 0 iken "henüz görünmüyor" ile "kapandı" ayırt edilmez).
```python
def test_f11(config, tmp_path):
    s = prepare("ttl", config, tmp_path); s.broker.hold_cancel = True
    assert s.runner.run_once().entries_blocked                   # iptal istendi, pending_cancel
    settle(s.broker, s.entry, "filled", float(s.order.qty)); s.broker.positions = []   # doldu ve aynı dakikada bacağıyla kapandı
    assert not s.runner.run_once().halted                        # KIRMIZI: "koruma dogrulanamadi"
```
- **Düzeltme:** `UNPROTECTED` demeden önce `list_fills(session_open)` içinde girişten sonra, dolum kadar ters
  yönlü gerçekleşme ara; varsa takip kapanır. Fail-closed; bedeli gereksiz kapalı gün.

### B12 — Kill-switch kapanışı journal'da `manual` · DÜŞÜK · DOĞRULANDI · Efor S
- **Yer:** `reconciler.py:85-99`; `runner.py:427` yalnız `flatten_at` verir. `ExitReason.KILL_SWITCH` hiçbir işleme yazılmaz.
- **Test (`test_f9`):** zarar sınırı → runner kapatır; brokera market SELL dolumu eklenir; sonraki tur mutabakat
  yapar; `SELECT exit_reason FROM trades` `"kill_switch"` beklenir → KIRMIZI: `"manual"`.
- **Düzeltme:** `daily_state.halted_at` sonrasındaki piyasa emri çıkışını `KILL_SWITCH` etiketle. Öğrenme katmanı elle müdahale ile zorunlu kapanışı ayıramıyor.

### B13 — Kısmi dolup iptal edilen giriş mutabakatta görünmeyebilir · ORTA · OLASI · Efor S
- **Yer:** `alpaca_broker.py:359-365` (`_to_fill` `filled_at` ister). Adaptör düzeyinde üretildi: `filled_at=None`, `filled_qty>0`, `status=canceled` ham kaydı `None`
  döner. Alpaca bu alanı yalnız tam dolumda dolduruyorsa B2/B6 yollarında kapatılan kısmi pozisyonun girişi görünmez; çıkış eşleşmez, işlem `trades`'e yazılmaz.
- **Doğrulama:** paper'da kısmi dolup iptal edilen bir emrin `filled_at` değerini oku. **Düzeltme:** `filled_qty>0` iken `updated_at`/`canceled_at`'e düş.

### B14 — `_flatten_all` `held` stopu göremez · DÜŞÜK · OLASI · Efor S
- **Yer:** `runner.py:972-985`. Toplu iptalden sonra `remaining` yalnız açık listeyi görür; kapatma sırası güvencesi "hedef iptali kardeş
  stopu da iptal eder" ve "miktar emre bağlıyken Alpaca kapatmayı reddeder" varsayımlarına dayanır. **Doğrulama:** paper'da kill-switch
  sonrası `nested=True` ile bacak durumlarını oku. **Düzeltme:** `blocked` kümesini iç içe listeden kur.

## 3. İncelenip sorun bulunmayanlar

- **Mükerrer emir:** kaydet → gönder → kesinleştir sırası; cevabı kaybolan gönderim `submitting` kalır ve sonraki tur brokera karşı
  çözülür; tur başına tek gönderim; `open_orders is None` iken giriş yok. Çökme pencerelerinde çift emir yolu bulunmadı.
- **İptal/dolum yarışı (#63):** iptal yalnız giriş kimliğine gider, bacak kimliği hiçbir yolda iptale girmez; niyet write-ahead; yeniden
  başlatma devralır. Kalan kusurlar B6 ve B11 (ikisi de fail-closed). Bekleme mantığına bakılmadı (kaldırılıyor).
- **Risk kapısı:** risk bütçesi, aşağı yuvarlama, maruziyet ve alım gücü sınırı, ayrılmış semboller dahil pozisyon
  sayısı, kısa devre yapmayan vetolar, `<=` ile zarar eşiği; short maruziyeti pozitif.
- **Seans sınırları:** `ZoneInfo` ile DST, yarım günde broker saati, geçmişte kalan `next_close`, UTC gün anahtarı (normal seansta NY günüyle aynı).
- **Fiyat/miktar ve adaptör:** `round_price`, yuvarlama sonrası bracket geometrisi, tamsayı emir miktarı,
  yuvarlanmayan pozisyon miktarı; SDK çağrıları `BrokerError`'a sarılı; takvim saatleri borsa diliminde.
- **Kalıcılık:** gün kararı `daily_state`'te; yazılamayan karar bellekte tutulup yeniden deneniyor; ISO metin karşılaştırması doğru sıralıyor.
- Belgelenmiş kabul sınırları (tek koşu kapısı, yazılamayan karar + yeniden başlatma, `done_for_day`) yeniden raporlanmadı.

## 4. Test boşlukları

- `daily_state` dışındaki journal hatalarında (okuma ve yazma) kill-switch ve gün sonu kapanışı (B1).
- Çıkış emri olmayan pozisyon; kısmi dolmuş girişin yarışsız yolu; kapanışı aşan kapatma ve ertesi gün (B2, B3).
- `run_forever` hiçbir testte saatle sürülmüyor: bekleme süresi ile kapanış tamponu ilişkisi, asılı çağrı (B4, B5).
- Alpaca'nın gerçek bacak görünümü (`held` stop listede yok, yalnız hedef) ile koruma kanıtı ve `_flatten_all` (B6, B14).
- Aynı pozisyonun iki bacağıyla `_pending_risk`; birden çok sembollü backtest'te eş zamanlı pozisyon (B7).
- Kesin ret ile belirsiz gönderim ayrımı; `from_intent` hatası ve strateji istisnası (B8, B10).
- Hafta sonu/tatil aşan mutabakat; kill-switch çıkış etiketi; kısmi dolum + iptal için `_to_fill` sözleşme testi (B9, B12, B13).
- Short giriş için iptal yarışı ve koruma kapsamı (testler yalnız long kuruyor).
