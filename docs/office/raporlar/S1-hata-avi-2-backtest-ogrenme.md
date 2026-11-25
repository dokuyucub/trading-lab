# S1 — Hata Avı 2: backtest ve öğrenme (ölçüm tarafı)

Tarih 2026-11-25 · kod `main` 47a2a7d · salt okuma, commit/push yok, ağ yok, veri indirilmedi.
Kanıtların tamamı sentetik barlarla; raporda hesap değeri ya da gerçek fiyat yok.
Kanıt dosyaları (commit edilmedi), `WT = <scratchpad>/wt-a2`:
`WT/tests/test_scratch_olcum.py` (11 kırmızı + 1 yeşil kontrol), `WT/tests/test_scratch_bagimlilik.py`
(1 kırmızı), `<scratchpad>/a2-sim/{cluster_sim,peek_sim}.py`. Her test İSTENEN davranışı iddia eder;
HEAD'de kırmızı olması bulgunun kanıtıdır. Çalıştırma: `cd WT && PYTHONPATH=src <venv>/python -m pytest -q
-p no:cacheprovider tests/test_scratch_olcum.py tests/test_scratch_bagimlilik.py` (~15 sn).

## 1. Sonuç

- **11 DOĞRULANDI, 5 OLASI.** En ağır ikisi dolum modelinde değil, backtest'i canlıdan ayıran yan etkilerde.
- **B1:** Simülasyonda bir pozisyon açıkken diğer tüm semboller veto ediliyor (canlıda edilmez); çok sembollü
  her ölçümün işlem örneklemi ve risk metrikleri canlının yapacağından farklı.
- **B2:** Kill-switch günü journal'da koşudan bağımsız; aynı journal'a ikinci backtest en kötü günleri atlıyor.
- Dolum modeli iki yerde iyimser (B3 giriş barında delinen stop, B4 dokunuşta hedef); kanıt aralığı gün içi
  bağımlılıkta nominal %5 yerine %19 yanlış hüküm veriyor (B6).
- Sağlam: sinyal→dolum hizası, kapanmamış bar süzgeci, açılış aralığı, DST, holdout bölmesi, bootstrap tohumu.

Ortak yardımcılar (scratch dosyasında): `day(offset, symbol, breakout=k, climb, crash_at, crash_to)` =
`test_backtest.breakout_day`'in parametreli hali (düz açılış, `k`. dakikada 4× hacimli +0,8 kırılım, sonra
dakikada +0,25); `backtest(config, cache, conn, **kw)` = kayma 0 ile `Backtest(...)`; `sim()` = kayma 0,
BUY limit 100,0 / stop 99,0 / hedef 101,5 emri gönderilmiş `SimBroker`; `WINDOW` = tek günlük aralık.

## 2. Bulgular (önem sırasıyla)

### B1 — Backtest'te açık pozisyon, diğer sembollerin girişini tümüyle veto ettiriyor · YÜKSEK · DOĞRULANDI
`backtest/sim_broker.py:221-242`, `engine/runner.py:552-581`, `risk/gate.py:89-90`.
`SimBroker.list_open_orders` koruma bacağını `side/remaining_qty` olmadan döndürür. `_pending_risk` meta verisi
olmayan emri "bilinmeyen risk" sayar (`unknown=True`) → kapı her niyeti "bekleyen emrin maruziyeti bilinmiyor"
diye reddeder. Alpaca adaptörü bu alanları doldurur (`alpaca_broker.py:284-291`); canlıda 3 eşzamanlı pozisyon açılır.
```python
cache.save("SPY", M1, day(0, "SPY", breakout=20)); cache.save("AAPL", M1, day(0, "AAPL", breakout=23))
result = backtest(make_config(root, ("SPY", "AAPL")), cache, conn).run(*WINDOW)
assert result.metrics.trades == 2
# E  AAPL islemi yok; vetolar: [('AAPL', 'bekleyen emrin maruziyeti bilinmiyor')]   assert 1 == 2
```
Kontrol (yeşil): bacak `side`+`remaining_qty` taşıyacak şekilde yamalanınca aynı veri 2 işlem üretir.
Yön: işlem sayısı düşer; hangi işlemin alındığı evren sırasına ve zamanlamaya bağlanır; eşzamanlı risk 1
pozisyona indiği için azami geri çekilme ve kill-switch sıklığı **olduğundan iyi** görünür. Onaylı 11 sembollü
tanım dahil çok sembollü her ölçüm bu yoldan geçer; 2026-10-13 raporunun o günkü commit'te etkilenip
etkilenmediği **doğrulanmadı**. Mevcut tüm backtest/baseline testleri tek sembollüdür (SPY).
Öneri: `SimBroker` bacak ve kapatma emirlerine `side`, `remaining_qty`, hedef için `limit_price` koysun;
iki sembollü eşzamanlı pozisyon testi eklensin. Efor: **S**.

### B2 — Kill-switch günü koşudan bağımsız saklanıyor; ikinci backtest o günü atlıyor · YÜKSEK · DOĞRULANDI
`engine/runner.py:422-428`, `journal/queries.py:56-65`, `migrations/002_durability.sql:72-73` (anahtar yalnız
`trade_date`), `cli.py:363` (`tlab backtest` varsayılanı CANLI journal).
```python
cache.save("SPY", M1, day(0, breakout=20, crash_at=22, crash_to=94.0))   # stop'un altına gap: gün −%2,5
first = backtest(config, cache, conn).run(*WINDOW); second = backtest(config, cache, conn).run(*WINDOW)
assert (second.metrics.trades, round(second.metrics.net_pnl, 2)) == (first.metrics.trades, ...)
# E  ikinci kosu, ilk kosunun kapattigi gunde hic islem acmadi   assert (0, 0.0) == (1, -2534.5)
```
Yön: aynı veri + aynı kod ikinci koşuda farklı ve **daha iyi** sonuç verir (en kötü günler baştan kapalı);
aday/temel karşılaştırması aynı journal'da yapılırsa ikinci koşan kayırılır. Ayrıca canlı journal'daki halt
backtest'i, bugünü kapsayan bir backtest'in halt'ı canlı döngüyü kapatır. `backtest/baseline.py` her senaryoda
taze bellek içi DB açtığı için resmi ölçüm ETKİLENMEZ.
Öneri: `daily_state` anahtarı `(run_id | mode, trade_date)` olsun, `halt_reason` koşu kimliği alsın; CLI
backtest varsayılanı ayrı journal olsun. Efor: **M** (migrasyon + kill-switch testleri).

### B3 — Giriş barında delinen stop yok sayılıyor · ORTA-YÜKSEK · DOĞRULANDI
`backtest/sim_broker.py:148-151, 388-392` (`skip=just_entered`).
```python
broker = sim()
broker.advance(sim_bar(0, 99.9, 100.2, 98.0, 100.1))   # açılış <= limit: dolum barın başında; dip stop'u deliyor
broker.advance(sim_bar(1, 100.2, 101.6, 100.1, 101.5))
assert broker.realized_pnl < 0        # E  stop yok sayildi, kazanc yazildi: +150.00
```
Yön: iyimser. Gerçek bracket −1R yazardı; simülasyon +1,5R yazıyor. "Giriş ve çıkış aynı barda olmaz" kuralı
README'de kötümserlik diye geçiyor ama yalnızca HEDEF için kötümser; stop için bedava ikinci şans. ORB girişi
marketable limit olduğundan (kapanış + 5 bps) dolum barın başındadır, dip kesin olarak sonradır. Mevcut test
(`test_entry_and_exit_never_happen_in_the_same_bar`) yalnızca hedef yönünü sınıyor.
Öneri: giriş barında hedef ertelensin, stop denensin (`low <= stop` → stop fiyatından çıkış). Efor: **S**.

### B4 — Hedef limiti dokunuşta doluyor · ORTA · DOĞRULANDI
`backtest/sim_broker.py:397, 406-409`; giriş için kural `377-386`'da var, çıkışta yok.
```python
broker = sim(); broker.advance(sim_bar(0, 100.5, 100.6, 99.8, 100.2))   # giriş
broker.advance(sim_bar(1, 100.5, 101.5, 100.4, 100.6))                  # tepe TAM hedefte, dönüyor
assert len(broker.get_positions()) == 1   # E  dokunusta hedef doldu: +150.00
```
Yön: iyimser; README/AGENTS §3.8 "pasif limit, fiyata değmek yetmez" der. ORB girişi marketable olduğu için
kural girişte nadiren işler, asıl pasif emir olan hedefte hiç işlemez. (Hedefe uygulanan 1 bps kayma kısmen dengeler.)
Öneri: `require_penetration` hedef bacağına da uygulansın (`high > take_profit`). Efor: **S**.

### B5 — Canlı `history_days=3`, backtest `history_days=1`: aynı barda farklı karar · ORTA · DOĞRULANDI
`backtest/engine.py:120`, `engine/runner.py:119, 640`, `cli.py:312-326` (ikisi de varsayılanda bırakılıyor).
```python
cache.save("SPY", M1, day(-3, breakout=None) + day(0, breakout=16))   # Cuma düz + Pazartesi 09:46 kırılımı
trades = {h: backtest(config, cache, conn_h, history_days=h).run(...).metrics.trades for h in (1, 3)}
assert trades[1] == trades[3]          # E  islem sayisi history_days'e gore degisti: {1: 0, 3: 1}
```
Tatil/hafta sonu ertesinde 1 günlük pencere yalnız o günün barlarını görür: RVOL(20) 21 bar ister, ATR Wilder
tohumu farklıdır. Canlı ve gölge döngü 3 gün görür. Etki veride seans öncesi bar yoksa/seyrekse büyük
(09:46-09:50 arası kararlar düşer), yoğun seans öncesi barı olan veride küçülür — gerçek veride büyüklük
**ölçülmedi**. "Aynı karar mantığı" vaadi parametre düzeyinde kırık.
Öneri: tek kaynak (config) ve mimari testte eşitlik; tatil ertesi günü içeren bir karar-eşitliği testi. Efor: **S**.

### B6 — Kanıt aralığı gün içi bağımlılıkta nominal oranın ~4 katı yanlış hüküm veriyor · ORTA · DOĞRULANDI
`learning/evidence.py:228-235, 387-395`; `backtest/baseline.py:122-127` (R değerleri gün bilgisi olmadan gider).
Sınır `evidence.py:13-19` ve rapor uyarısında yazılı; burada büyüklüğü ölçüldü. Beklenen değeri tam 0 R olan,
günde 6 işlemin aynı "trend/testere" rejimini paylaştığı (ICC ≈ 0,26) 150 işlemlik örneklem, gerçek `assess`:
```python
wrong = sum(assess(clustered(rng, days=25, per_day=6, delta=0.25)).verdict in (BETTER, WORSE) for _ in range(400))
assert wrong / 400 <= 0.08            # E  yanlis BETTER/WORSE orani %19.2
```
`cluster_sim.py` (aynı prosedür, numpy, 1500 deneme): yanlış BETTER %2,5 yerine %6-9; **gün-blok bootstrap
aynı veride %2,3-3,0'a döner.** ORB aynı sembole gün içinde yeniden girebildiği için bağımlılık tek sembolde de var.
Öneri: `assess/compare` isteğe bağlı grup (seans günü) alsın ve günleri yeniden örneklesin; baseline
`_r_values` günü de döndürsün; `min_trades` yanında `min_days` tabanı. Efor: **M**.

### B7 — Karar anındaki sentetik kotasyon henüz kapanmamış barın kapanışından · ORTA (gizli) · DOĞRULANDI
`data/cached.py:119-126` (`bisect_right(stamps, moment) - 1` → `ts == now` olan, yeni AÇILAN bar).
```python
# casus strateji ctx'i kaydeder; karar anı 09:50:00, son kapanmış bar 09:49 (kapanış 100.0)
assert quote_ts + minute <= now   # E  kotasyon 14:50:00 barindan; o bar 14:50:00'da kapanmamisti
```
O anda `quote.mid = 100.8`: kırılım barının 09:51'de oluşacak kapanışı. Bugün karar DEĞİŞMİYOR: kapı ve ORB
yalnız `spread_bps` okur, o da sabit. `quote.bid/ask/mid` kullanan ilk kural (ör. "kotasyon referanstan uzak")
doğrudan ileriye bakar. Mevcut test (`test_quote_is_taken_from_the_simulated_moment`) `quote.ts <= moment`
iddia ederek hatayı onaylıyor; deterministik ileriye bakma testi fiyat seviyesi kullanılmadığı için yakalamaz.
Öneri: `quote_at` yalnız `ts + duration <= moment` barları kullansın; testi buna çevir. Efor: **S**.

### B8 — Komisyon özsermayeden düşüyor ama işlem istatistiklerine girmiyor · ORTA-DÜŞÜK · DOĞRULANDI
`backtest/sim_broker.py:413, 453`; `engine/reconciler.py:127-153` (`fees` hiç verilmiyor); `core/types.py:497, 516-518`.
```python
... fill_model=SimFillModel(slippage_bps=0.0, commission_bps=10.0)
assert metrics.net_pnl == approx(ending_equity - starting_equity)   # E  751.10 != 675.72
```
`expectancy_r`, `total_r`, `net_pnl`, `profit_factor` ve kanıt hükmü komisyonsuz; yalnız getiri/drawdown
komisyonlu. Varsayılan 0 bps olduğu için bugün gizli; `--commission-bps` ya da `CostScenario.commission_bps`
verildiği an beklenen değer iyimser kalır. Öneri: `Fill`'e ücret alanı, `build_trade(fees=...)`. Efor: **S-M**.

### B9 — Maliyet senaryosundaki `spread_bps` hiçbir dolumu etkilemiyor · DÜŞÜK-ORTA · DOĞRULANDI
`backtest/baseline.py:76-90`, `data/cached.py:128-137`; `SimBroker` dolumları kotasyonu hiç okumaz.
```python
for spread in (1.0, 10.0): equity[spread] = backtest(config, cache, c, spread_bps=spread).run(*WINDOW).ending_equity
assert equity[10.0] < equity[1.0]     # E  spread 1 -> 10 bps sonucu degistirmedi: {1.0: 100751.1, 10.0: 100751.1}
```
Spread yalnız kapının `max_spread_bps` (15) vetosuna girer; senaryoların hepsi (1-10 bps) eşiğin altında.
Rapordaki "iyimser…sert" satırlarını ayıran tek şey `slippage_bps`. Piyasa ve stop çıkışları yarım spread
ödemez. `test_harsher_costs_never_improve_expectancy` eşitliği kabul ettiği için geçer.
Öneri: piyasa/stop dolumlarına yarım spread uygula ya da alanı rapordan çıkar/etiketle. Efor: **S**.

### B10 — Seansın son barında dolan çıkış journal'a hiç işlem olarak düşmüyor · DÜŞÜK · DOĞRULANDI
`engine/runner.py:201-203` (borsa kapalıysa `_reconcile`'dan (214) önce dönüş), `261` (`since` = açılış − 1 takvim günü).
```python
bars = [b for i, b in enumerate(day(0, breakout=100, climb=0.0)) if not 380 <= i <= 388]   # 15:50-15:58 yok
result = backtest(config, cache, conn, sessions=[official]).run(*WINDOW)
assert result.metrics.trades == 1
# E  ozsermaye -18.50 degisti, journal'da 1 dolum ve 0 islem var (cikis dolumu ve islem kaydi yok)
```
`CarriedPositionError` atılmaz (pozisyon kapandı); kalite politikası bu veriyi kabul eder (son 10 dk'da ≥1 bar).
Koşunun son günü ve hafta sonu/tatil öncesi günlerde işlem kalıcı olarak kaybolur; diğer günlerde ertesi sabah
`manual` etiketiyle yazılır. Getiri işlemi içerir, beklenen değer içermez. Seçim P&L'e göre yanlı değil.
Öneri: motor gün sınırında ve koşu sonunda bir kez mutabakat çağırsın; `since` son seansı kapsasın. Efor: **S**.

### B11 — Terfi kapısı, kanıtlı ama eşik altı İYİ adayı "kanıtlı kötü" diye REDDEDİYOR · DÜŞÜK · DOĞRULANDI
`learning/promotion.py:263-268` (`WORSE` = üst uç < `min_edge_r`, 0'ın altı değil), `40-41`.
```python
result = decide_promotion([0.2, 0.4] * 200, [0.15, 0.35] * 200)       # fark aralığı [+0.036, +0.064]
assert result.decision is PromotionDecision.HOLD
# E  reject: ('aday temelden kanitli sekilde kotu: ust sinir +0.064 R < esik +0.100 R',)
```
Yön: temkinli taraf (yanlış "hayır"), para riski yok; ama gerekçe yanlış ve aday "izlemeden çıkarılır".
Temelle özdeş bir aday da aynı metinle reddedilir. Öneri: REJECT yalnız üst uç < 0 iken; arası HOLD. Efor: **S**.

### OLASI bulgular
- **O1 — Tekrarlı bakış düzeltilmiyor** (`promotion.py:95-103, 167-172`; Bonferroni yalnız aynı turdaki aday
  sayısı için). `peek_sim.py` (aynı prosedür numpy ile, 400 deneme, n=100…600 arası 51 bakış): gürültü-gürültü
  yanlış terfi %0,2 → %1,8; tam eşikteki aday %1,5 → %7,0. Doğrulama: aynı döngü gerçek `decide_promotion` ile
  (~15 sn/deneme). Öneri: bakış takvimi önceden sabitlensin ya da bakış sayısı `candidates_considered`'a girsin. **S**.
- **O2 — R paydası planlanan değil gerçekleşen girişten** (`core/types.py:521-533`). Tip düzeyinde hesaplandı:
  limit 100,05 / stop 99,50 planlı işlem 99,51'den dolarsa aynı kâr +2,35R yerine **+129R**; giriş = stop ise
  zarar **0R** yazılır. Simülasyonda oluşmaz (dolum hep limitte); paper journal'da tek işlem ortalamayı taşıyabilir.
  Doğrulama: paper dolumlarında `|giriş − stop| / |limit − stop|` dağılımı. Öneri: payda `|limit − stop|`. **S**.
- **O3 — Çıkış sebebi etiketi** (`engine/reconciler.py:85-99`): kill-switch kapatması `manual` döner
  (`KILL_SWITCH` hiç üretilmiyor; fonksiyon çağrısıyla görüldü), ertesi gün mutabık edilen gün sonu çıkışı da
  `manual` olur. Setup × çıkış sebebi analizini kirletir. Öneri: kapatma emrine sebep taşıyan kimlik. **S**.
- **O4 — Karar gecikmesi modellenmiyor.** Backtest kararı bar kapanışında anında verir, emir bir sonraki barın
  tamamına karşı işlem görür; canlı döngü 60 sn'de bir, rastgele fazda çalışır. README "bilinen iyimserlik"
  listesinde yok. Ayrıca `SimBroker.daytrade_count=0` (PDT hiç bağlamaz) ve açığa satışta ödünç/SSR kısıtı yok.
  Doğrulama: gölge kayıtlarında (karar anı − bar kapanışı) dağılımı. **M**.
- **O5 — `assess` tek gözlemde `trades=0, mean_r=0.0` raporluyor** (`evidence.py:278-288`; çağrıyla görüldü) ve
  `required_trades` güç payı içermiyor (≈%50 güç; `compare`'de tek kümenin yayılımı) → "gereken işlem" 2-4×
  iyimser. Öneri: gerçek sayıyı yaz; z_α + z_β kullan. **S**.

## 3. İncelenip sorun bulunmayanlar

- **Sinyal → dolum hizası:** karar bar KAPANIŞINDA (`engine.py:318`), emir bir sonraki barda denenir; `_closed_bars`
  (`runner.py:704-713`) oluşan barı ayıklar; `CachedMarketData.bars` `ts == now` barını döndürse de süzülür.
- **Açılış aralığı** (`indicators.py:136-178`): eksik, yinelenen, kaymış dakika aralığı kurdurmaz; pencere
  kapanmadan aralık yok (bir bar gecikmeli, temkinli); 5 dk'lık barlar doğru sayılır.
- **Saat/DST/yarım gün:** `ZoneInfo` ile yerel saatten kurulur, sabit UTC farkı yok; gün sınırı borsa takvimiyle;
  resmi seans verildiğinde yarım gün kapanışı ve `CarriedPositionError` doğru çalışır.
- **Stop gap'i, aynı barda stop+hedef, giriş limiti aşımı, kapatmanın sonraki gerçek barda dolması:** belgelendiği gibi.
- **Holdout bölmesi** (`dataset.py:466-560`): kronolojik, yerel güne göre, P&L görmeden; `_r_values` sıralı.
- **Bootstrap:** tohum sabit ve deterministik; NaN/sonsuz reddedilir; tam eşik değeri INCONCLUSIVE (temkinli);
  `min_trades < 2` ve ölçülemeyen güven seviyesi kurulumda reddedilir; `evaluation_eligible=False` terfi vermez.
- **Metrikler:** boş kümede sıfıra bölme yok; drawdown tepe-dip doğru; kazanan yoksa/kaybeden yoksa korumalı.
- **Determinizm:** UUID'ler sıralamaya girmiyor; `test_backtest_is_deterministic` ve bayt-özdeş rapor testi yeterli.

## 4. Test boşlukları

1. Çok sembollü, eşzamanlı pozisyonlu backtest testi yok (B1'i görünmez kılan boşluk).
2. Aynı journal'da iki koşu / canlı journal'la paylaşım testi yok (B2).
3. Giriş barında stop ve tam dokunuşta hedef senaryoları yok (B3, B4).
4. Canlı ile backtest'in aynı `history_days` kullandığını ve tatil ertesi aynı kararı verdiğini sınayan test yok (B5).
5. `commission_bps > 0` ile journal ↔ özsermaye tutarlılığı ve spread'in etkisi sınanmıyor (B8, B9).
6. Kotasyon testi yanlış değişmezi (`quote.ts <= moment`) sabitliyor (B7).
7. Seansın son barında dolum / kapanış sonrası mutabakat testi yok (B10).
8. Kanıt katmanında bağımlı (gün kümeli) veri ve tekrarlı bakış için kalibrasyon testi yok (B6, O1).
9. Rastgele yürüyüş lambası zayıf: 6 tohum × 12 gün, eşik +0,10 R ortalama; B3/B4 büyüklüğündeki bir
   iyimserliği yakalayacak gücü yok. Öneri: iki yönlü (stop-önce / hedef-önce) deterministik dolum tablosu testi.
