# S1 — Hata Avı: PR #63, `05b391d` (kod) + `05df92d` (yalnız test)

Tarih: 2026-11-25. İncelenen head `05df92d`, ebeveyn `a48daae`. Yalnız okuma ve çevrimdışı hedefli test yapıldı.
Sınıflar: (a) bu commit getirdi, (b) PR'da önceden var, (c) main'de var, PR kapsamı dışı.

## Sonuç

- **Push edilebilir mi: EVET-notlarla.** Codex 7154998289'un iki senaryosu iki yolda da kapanıyor; gerileme yok (beş bulgunun hepsi `a48daae` kaynağıyla da kırmızı).
- **5 DOĞRULANDI + 2 OLASI.** B1 ve B2, commit mesajındaki ve §4'teki "yeniden başlatma ve okuma hatası süreyi uzatamaz" iddiasını daraltıyor; Codex'in sıradaki bulgusu büyük olasılıkla bunlardan biri.
- **Öneri:** B1 ve B2 küçük düzeltmeler; push'tan önce kapatılmalı ya da PR'a bilinen sınır diye yazılmalı. B3–B5 ile test ve belge notları takip işi olabilir.

## Codex senaryolarının yeniden üretimi

Karalama dosyası çalışma kopyasında `tests/test_scratch_r63.py` (commit edilmedi): `05df92d` ile 26 yeşil,
15 kırmızı (kırmızıların hepsi aşağıdaki bulgular). `tests/test_entry_cancel_race.py`: 124 yeşil.

| Senaryo (iki yol: `ttl`, `blocked`) | `a48daae` | `05df92d` |
|---|---|---|
| (1) Kesinti yok: 1. tur tam dolum, tek stop `accepted`; sonra stop düşer, yalnız `get_order(parent)` hata verir, 6 tur | kırmızı | yeşil: gün 1. turda kapanır, `close_position("SPY")`, 6 tur `halted` |
| (2) Okumalar başarılı, stop hep `accepted`; 2. ve 4. tur sonunda bağlantı kapanır, yeni runner | kırmızı | yeşil: 6 turun hepsi `halted`, pozisyon 1. turda kapanır |
| (1) ve (2), kapatma brokera ulaşmazken (`fail_close`) | kırmızı | yeşil: her tur yeniden denenir, broker kabul edince kapanır |

Not: `blocked` yolda yeniden başlatmadan sonraki `halted`, `daily_state`'ten değil izlenen satırın yeniden
değerlendirilmesinden gelir. B1b ve B2 bu dayanağı kırıyor.

## Bulgular (önem sırasıyla)

Karalama testlerinin ortak başlığı (aşağıdaki testler bununla çalışır; güvenli beklenti yazılıdır, kırmızı = bulgu):
```python
from datetime import timedelta
import pytest
from test_entry_cancel_race import (PATHS, accept_without_settling, config, halt_on_an_unprotected_fill,
    hold_position, leg_ids, legs, next_session, partial_without_settling, prepare, settle, status_of,
    track_a_covered_partial_fill)
from test_runner import NOW
from tlab.core.types import Fill, Side
from tlab.journal.db import connect
def fill(s, side, qty, oid, cid, kind, after):  # brokerin bildirdigi gerceklesme
    return Fill(broker_order_id=oid, client_order_id=cid, symbol="SPY", side=side, qty=qty,
                price=s.order.stop_loss, filled_at=NOW + timedelta(seconds=after), order_type=kind)
def entry_fill(s, qty):
    return fill(s, Side.BUY, qty, s.entry.broker_order_id, s.entry.client_order_id, "limit", 0)
def reopen(s, tmp_path):  # baglanti kapanir; ayni journal ile yeni surec
    s.conn.close()
    s.conn = connect(tmp_path / "journal.db")
    s.restart()
```

### B1 — `_reconcile` izleme satırını `closed` ile eziyor (orta) — DOĞRULANDI, (b)
`runner.py:410` giriş ve çıkış gerçekleşmesi eşleşince `orders.status`'u koşulsuz `closed` yapar; iptal izi aynı
sütundadır (`runner.py:614`). Aynı süreçte bellek izi sürdürür, yeni süreç bulamaz. Sembolde pozisyon olduğu için
bayat iptal yolu da girişi yeniden izlemeye almaz (`runner.py:524`).
- **B1 (iki yol):** T1 iptal `pending_cancel`. T2 giriş 5 adet dolu (terminal değil), pozisyon 5, stop `new` 5: izleme sürer. Stop tetiklenir
  (broker iki gerçekleşme bildirir), giriş 3 adet daha dolar: pozisyon 3, stop yok. Yeniden başlatma. T3–T6: satır
  `closed`, `halted=False`, kapatma yok. Kontrol (yeşil): yeniden başlatma ya da gerçekleşme bildirimi yoksa gün kapanır.
- **B1b (`blocked`; 05df92d'deki yeni testin devamı):** korumasız dolum, gün yalnız bellekte kapalı, kapatma ulaşmaz.
  Stop (5 adet) iptali kesinleşmeden dolar. Yeniden başlatma: satır `closed`, 4 tur `halted=False`, kalan stopsuz.
- **Gerçekçilik:** bağdaştırıcı `filled_at` taşımayan emri gerçekleşme saymaz (`alpaca_broker.py:364`). Kısmi dolmuş
  açık emirde `filled_at`'in boş geldiği doğrulanmadı; boşsa B1 yalnız sahte brokerla oluşur. B1b gerçek
  bağdaştırıcıda da oluşur ama üç koşul ister: yazılamayan `daily_state`, yeniden başlatma, kısmi çıkış.
- **Düzeltme yönü:** `_reconcile` izlemedeki satırı ezmesin (koşullu güncelleme) ya da iptal izi ayrı sütunda dursun.
```python
@pytest.mark.parametrize("path", PATHS)
def test_b1_reconcile_overwrites_the_tracking_row(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)        # giris 5 adet dolu (`partially_filled`), pozisyon 5, stop `new` 5
    assert status_of(s.conn, s.entry) == "cancel_pending"
    # Stop tetiklenir (5 satilir); giris 3 adet daha dolar: pozisyon 3, stop yok.
    s.broker.fills = [entry_fill(s, 5.0), fill(s, Side.SELL, 5.0, "leg-stop", "alpaca-leg-stop", "stop", 30)]
    partial_without_settling(s, status="partially_filled", filled=8.0, stop_qty=None)
    hold_position(s.broker, s.order, 3.0)
    s.restart()                            # yeni surec, ayni journal
    halted = [s.runner.run_once().halted for _ in range(4)]
    assert any(halted), (halted, status_of(s.conn, s.entry), s.broker.closed)
    # KIRMIZI (iki yol): ([False]*4, 'closed', []) -- pozisyon 3 acik, stop yok, kapatma denenmedi
def test_b1b_unpersisted_halt_is_lost_once_an_exit_fill_is_reconciled(config, tmp_path):
    s = prepare("blocked", config, tmp_path)   # daily_state yazilamiyor: karar yalniz bellekte
    def short_cover(broker):                   # tam dolum; `new` stop yalniz 5 adedi kapsiyor
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)
        broker.open_orders.extend(legs(s.order, stop_qty=5.0))
    s.broker.on_cancel = short_cover
    s.broker.fail_close = True
    assert s.runner.run_once().halted          # korumasiz: gun kapanir, kapatma brokera ulasmaz
    # Stop, iptali kesinlesmeden tetiklendi ve 5 adet satti; kalan pozisyon stopsuz.
    s.broker.fills = [entry_fill(s, float(s.order.qty)),
                      fill(s, Side.SELL, 5.0, "leg-stop", "alpaca-leg-stop", "stop", 30)]
    hold_position(s.broker, s.order, s.order.qty - 5)
    s.broker.fail_close = False
    reopen(s, tmp_path)
    halted = [s.runner.run_once().halted for _ in range(4)]
    assert all(halted) and s.broker.positions == [], (halted, status_of(s.conn, s.entry), s.broker.closed)
    # KIRMIZI: ([False]*4, 'closed', []) -- fills olmadan (05df92d testi) ayni akis YESIL
```

### B2 — Tur başındaki pozisyon görüntüsü yok sayılıyor (orta-düşük) — DOĞRULANDI, (b)
Dal bu commit'te yazıldı ama sonuç ebeveynle aynı. `_outcome_without_entry` pozisyonu yeniden okur; okuma hata verirse
PENDING döner (`runner.py:728-734`). Oysa turun başında okunan `positions` (`runner.py:319`) sembolü gösteriyor.
Dizi: kapsanan kısmi dolum izleniyor; stop düşer; her turda `get_order(parent)` ve ikinci `get_positions` hata verir,
ilk `get_positions` ve emir listesi başarılıdır: 6 tur `halted=False`, `close_position` yok. Giriş okunabilseydi aynı
okuma hatası günü kapatırdı (`runner.py:765-766`). Düzeltme yönü: iç okuma hata verirse tur başı görüntüsüne düş.
```python
@pytest.mark.parametrize("path", PATHS)
def test_b2_turn_start_position_snapshot_is_ignored(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)        # pozisyon 5, stop `new` 5
    s.broker.open_orders = [o for o in s.broker.open_orders if o.broker_order_id != "leg-stop"]
    s.broker.fail_get_order = True         # stop dustu, giris okunamiyor
    halted = []
    for _ in range(6):
        s.broker.fail_positions = False                                  # tur basi okumasi basarili
        s.broker.on_list = lambda b: setattr(b, "fail_positions", True)  # sonraki okumalar hata verir
        halted.append(s.runner.run_once().halted)
    assert any(halted), (halted, s.broker.closed)
    # KIRMIZI (iki yol): ([False]*6, []) -- `positions` goruntusunde SPY var, gun kapanmiyor
```

### B3 — Ulaşmayan iptal, giriş okunamadıkça yeniden gönderilmiyor (orta-düşük) — DOĞRULANDI, (b)
`_confirm_cancel`, `get_order` hata verince hiçbir şey yapmadan döner (`runner.py:583-587`); deneme sayacı ilerlemez,
bayat iptal yolu da izlemedeki girişi atlar (`runner.py:526`). Dizi: T1 iptal brokera ulaşmaz; T2–T9 yalnız
`get_order(parent)` hata verir, giriş açık listede `accepted` görünür: 8 turda tek gönderim, gün kapanmaz, bayat giriş
canlı kalır. `MAX_CANCEL_ATTEMPTS` sınırı bir okuma hatasıyla süresiz uzuyor (7154998289 ile aynı sınıf). Düzeltme
yönü: okuma hatasında tur başı açık emir listesindeki duruma düş ya da okunamayan turu denemeye say.
```python
@pytest.mark.parametrize("path", PATHS)
def test_b3_unreached_cancel_is_not_resent_while_the_entry_is_unreadable(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1       # ilk iptal brokera ulasmaz
    assert s.runner.run_once().entries_blocked
    s.broker.fail_get_order = True         # sonra yalniz get_order(parent) hata verir
    results = [s.runner.run_once() for _ in range(8)]
    assert [o.status for o in s.broker.open_orders] == ["accepted"]      # giris acik listede, canli
    assert len(s.broker.cancelled_ids) > 1 or any(r.halted for r in results)
    # KIRMIZI (iki yol): 8 turda tek gonderim, MAX_CANCEL_ATTEMPTS sayaci ilerlemiyor, gun kapanmiyor
```

### B4 — Giriş okunuyor ama dolumu 0 ya da bilinmiyor; görünen pozisyon ölçülmüyor (düşük) — DOĞRULANDI, (b)
`runner.py:711-712` dolum 0 ise (terminal değilken `None` de) pozisyona bakmadan döner. Kural artık tutarsız: giriş
okunamazsa görünen pozisyon ölçülür, okunur ama bayatsa ölçülmez. Dizi: iptal `pending_cancel`; giriş
`partially_filled`, `filled_qty` 0 ya da `None`; pozisyon 5, stop yok: 4 tur `halted=False`. B4b: giriş `canceled`,
dolum 0, pozisyon 5: satır `canceled` yazılır ve iz kapanır.
Gerçek bağdaştırıcıda bozuk `filled_qty` 0.0'a düşer (`sdk_compat.py:29-42`); emir okumasının pozisyon okumasından
geri kaldığı bir Alpaca durumu doğrulanmadı.
```python
@pytest.mark.parametrize("filled", [0.0, None])
@pytest.mark.parametrize("path", PATHS)
def test_b4_stale_filled_qty_hides_a_visible_position(path, filled, config, tmp_path):
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    s.broker.open_orders = [o.model_copy(update={"status": "partially_filled", "filled_qty": filled,
                                                 "side": Side.BUY}) for o in s.broker.open_orders]
    hold_position(s.broker, s.order, 5.0)  # pozisyon gorunuyor, stop yok
    assert any(s.runner.run_once().halted for _ in range(4))             # KIRMIZI (iki yol, iki deger)
@pytest.mark.parametrize("path", PATHS)
def test_b4b_zero_fill_terminal_entry_with_a_visible_position(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    settle(s.broker, s.entry, "canceled", 0.0)
    hold_position(s.broker, s.order, 5.0)
    result = s.runner.run_once()
    assert result.halted or status_of(s.conn, s.entry) != "canceled"     # KIRMIZI: "canceled", iz kapandi
```

### B5 — Önceki seans, okunamayan giriş: sahipsiz çıkış emri kalıyor (düşük) — DOĞRULANDI, (b)
Giriş okunursa pozisyon yokken kalan çıkış emri günü kapatır ve iptal edilir (`runner.py:770-775`). Okunamazsa
`position is None` PENDING döner (`runner.py:735-736`). Dizi: 1. gün korumasız dolum, gün kapanır, pozisyon
kapatılır, iz kalır; sonraki seans satış stopu listede, giriş okunamıyor: 4 tur `halted=False`, stop yerinde.
Emir dolarsa oluşan ters pozisyon o turda günü kapatır.
```python
@pytest.mark.parametrize("path", PATHS)
def test_b5_orphan_exit_survives_while_the_old_entry_is_unreadable(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    halt_on_an_unprotected_fill(s)         # 1. gun: gun kapandi, pozisyon kapatildi, iz kaldi
    s.broker.open_orders.append(legs(s.order, stop_qty=s.order.qty)[0])  # onceki seanstan satis stopu
    s.broker.fail_get_order = True
    runner = next_session(s)
    halted = [runner.run_once().halted for _ in range(4)]
    assert any(halted) or leg_ids(s.broker) == [], (halted, leg_ids(s.broker))
    # KIRMIZI (iki yol): ([False]*4, ['leg-stop']) -- giris okunursa ayni durum gunu kapatiyor
```

### Olası bulgular ve kapsam dışı gözlemler
- **O1 — OLASI (tasarım bedeli), (a):** izlenen girişin sembolünde stopla kapsanan pozisyon varken `get_order` ve
  `list_open_orders` aynı turda hata verirse gün kapanır (`runner.py:739-742`); liste dönünce pozisyon tasfiye edilir.
  Ebeveynde PENDING'di. "Her gün kapanır" durumu kurulamadı: dal yalnız izlemede giriş ve görünen pozisyon varken çalışır.
- **O2 — OLASI, (b):** `get_order` kalıcı hata verirse (brokerda artık bulunmayan kimlik) satır hiç kapanmaz; her tur
  ve her seans `entries_blocked` (`runner.py:709`, `659`). Çıkış yolu elle journal düzeltmesi. Kod okunarak; test yok.
- **(c)** `_flatten_all` listede emir kaldıkça kapatma göndermez (`runner.py:971-978`): iptal kesinleşmezse gün kapalı,
  pozisyon açık kalır (yeşil karalama testi, 6 tur). `run_once` başındaki `get_account`, `get_positions`, `_reconcile`
  hataları turu kill-switch'ten önce bitirir (`runner.py:318-327`); o turda güvenli kapatma da çalışmaz. Kod okunarak.

## Denenip kırılamayanlar
- Açığa satış yönü (stop yok, yanlış yönde stop, tam alış stopu; giriş okunur ve okunamaz): 12 yeşil. Pozisyonun
  ancak sonraki turda görünmesi, giriş okunamazken: 2 yeşil. Codex senaryoları kapatma başarısızken: 8 yeşil.
- Journal yazma hataları (kod ve mevcut testler): `cancel_pending`, `filled`, `canceled` yazılamazsa satır izlemede
  kalır ve yeniden çözülür; gün kapatan turun herhangi iki adımı arasındaki kesinti satırı `cancel_*` bırakır.
- Aynı sembolde iki izlenen giriş kurulamadı (izleme sürerken giriş engelli). `dry_run` üç yolda da hemen döner.
  `canceled` + `filled_qty > 0` kapsam kontrolüne girer. Silinen adlara (`Coverage`, `_cover_waits` vb.) başvuru kalmamış.

## Test zayıflıkları
1. **Okunamayan giriş dalında stop durumu ve miktarı sabit değil.** Mutasyon: `runner.py:744` "çıkış yönünde
   `stop_price` taşıyan herhangi bir emir var mı" yapıldı; 124 test yeşil kaldı. Eksik: kapsanan kısmi dolumdan sonra
   stop `accepted`/`held` ya da eksik miktarlıyken giriş okunamaz, gün kapanır.
2. **`..._is_read_back_after_a_restart` (satır 1096) runner'ın kaydı okuduğunu göstermiyor.** Mutasyon:
   `_check_kill_switch` kalıcı kaydı yok sayar; dosyadaki 124 test yine yeşil, çünkü `again.halted` izlenen satırdan da
   çıkıyor. Düzeltme: `again.notes` içinde `gun kapali:` aranmalı. Codex 7155309564 bu yüzden yarı açık.
3. `..._rebuilt_from_the_tracked_entry...` (1122) sahte brokerın gerçekleşme bildirmemesine dayanıyor (B1b).
4. `..._unreadable_positions_stays_tracked` (1287) tek tur ve pozisyon listesi boş: "bilgi yok" ile "tur başında
   pozisyon görüldü" ayrılmıyor (B2); sonraki turda `run_once`'ın hata fırlatması sınanmıyor.
5. `..._unreadable_orders_halts...` (1255) ikinci turda tam kapsanan pozisyonun kapatılmasını istenen davranış diye
   sabitliyor (O1). `..._does_not_complete_the_cover` (1170) kapanma sebebini doğrulamıyor. Satış yönlü giriş testi yok.

## Belge uyuşmazlıkları (`docs/designs/unattended-paper.md` §4)
1. Satır 240-254: "Karar yalnız girişin kendi durumundan verilir" ve "`get_order` okunamazsa → izlemede, giriş engeli
   sürer" artık eksik; yeni madde (303-307) pozisyon ve açık emirlerle gün kapatıyor.
2. Satır 331-333: "pozisyon/emir okunamazsa gün kill-switch ile kapanır" fazla genel; giriş ve pozisyon birlikte
   okunamazsa gün kapanmıyor (306-307, B2).
3. Satır 299-300 ve commit mesajı: "Gün kararı `daily_state`'e kalıcı yazılır", "yeniden başlatma süreyi uzatamaz".
   `daily_state` yazılamayan dalda karar bellektedir; dayanak izlenen satırdır ve B1b ile B2'de kırılıyor.
4. Satır 274: `MAX_CANCEL_ATTEMPTS` sayacının giriş okunamazken ilerlemediği yazmıyor (B3). O1 bedeli de yazmıyor.
5. Satır 230-232 Codex listesinde 7154998289 ve 7155309564 yok; 335-343 test dökümü yeni grupları anmıyor.
6. Satır 300-302 bedeli "gereksiz kapanabilir" diye hafif geçiyor: `S1-arastirma-2-alpaca-emir-davranisi.md` tam
   dolumdan sonra stopun `held` kaldığını (ikincil kaynak) yazıyor; öyleyse her iptal/dolum yarışı gün kapatır.
7. `core/types.py:588` olmayan `_cancel_entry`'ye atıf yapıyor (bu commit'ten önce de vardı).

## Yeniden inceleme — f654f0d

İncelenen head `f654f0d` (ebeveyn `05df92d`). Yalnız okuma ve çevrimdışı hedefli test.

- **Push edilebilir mi: EVET-notlarla.** B1–B4 kapanmış; normal işleyişte gerileme ya da yanlış gün kapanışı kurulamadı.
- **Notlar:** 2 DOĞRULANDI kalıntı (R1 orta-düşük, R2 düşük) ve 1 test boşluğu. R1, Codex 7154998289'un ikinci
  maddesiyle aynı sınıf (bellekteki sayaç + yeniden başlatma); §4'te sınır olarak açık yazılmalı ya da kapatılmalı.

### Karalama testlerinin `f654f0d` ile sonucu
Eski 41 testin 39'u yeşil, 2'si kırmızı. `tests/test_entry_cancel_race.py`: 159 yeşil.
- Yeşile dönenler: B1 (iki yol), B1b, B2 (iki yol), B4 (dört durum), B4b (iki yol), B5 (iki yol).
- Kırmızı kalan: B3 (iki yol), yalnız eski ön koşul satırı (`open_orders == ["accepted"]`). Beklenen: gün artık 4. turda
  kapanıyor ve hesap genelindeki iptal bayat girişi kaldırıyor. Yeni davranış doğru.
- B5 yalnız iptal doğrulanmamışken (`cancel_requested`) yeşil: 4. turda "iptal iletilemedi" ile gün kapanıyor.
  `cancel_pending` satırında sahipsiz emir kalmaya devam ediyor (§4 bilinen sınır (i) ile uyumlu).

### R1 — Deneme sınırı süreç belleğinde; yeniden başlatma sınırı uzatıyor (orta-düşük) — DOĞRULANDI, (b)
`_cancel_attempts` süreç belleğinde (`runner.py:241`, `594-597`). Dizi: T1 iptal brokera ulaşmaz; sonra yalnız
`get_order(parent)` hata verir; iki turda bir bağlantı kapanıp yeni runner kurulur. Sonuç: 12 turda gün kapanmaz, iptal
yeniden gönderilmez, giriş açık listede `accepted` kalır. Yeniden başlatma yoksa gün 4. turda kapanıyor. Codex'in
ölçüsüyle ("2. ve 4. tur sonunda yeniden başlatma, 6. turda hâlâ açık") aynı düzende yeniden üretilir. Uzayan şey korumasız
pozisyon değil, bayat girişin canlı kalma süresi; dolarsa koruması ölçülür. §4 "süreç başına" diyor ama commit mesajı
ve satır 281 "sınır okuma hatasıyla uzamaz" diye genel yazıyor. Düzeltme yönü: sınırı journal'dan türet
(`cancel_requested` satırının `updated_at` yaşı ya da kalıcı sayaç).
```python
@pytest.mark.parametrize("path", PATHS)
def test_r1_restarts_reset_the_cancel_attempt_limit(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1       # ilk iptal brokera ulasmaz
    assert s.runner.run_once().entries_blocked
    s.broker.fail_get_order = True         # sonra yalniz get_order(parent) hata verir
    halted = []
    for turn in range(1, 13):
        halted.append(s.runner.run_once().halted)
        if turn % 2 == 0:
            reopen(s, tmp_path)            # iki turda bir yeniden baslatma, ayni journal
    live = [o.status for o in s.broker.open_orders]
    assert any(halted) or len(s.broker.cancelled_ids) > 1, (halted, live, len(s.broker.cancelled_ids))
    # KIRMIZI (iki yol): ([False]*12, ['accepted'], 1) -- sayac surec belleginde, her surecte sifirdan
```

### R2 — Kalıcı okunamayan, iptali doğrulanmamış giriş her seansı kapatıyor (düşük) — DOĞRULANDI, (a)
B3 düzeltmesinin yan etkisi. Brokerda artık bulunmayan kimlik `cancel_requested` satırında kalırsa her seansta
(ve her süreçte) üç tur giriş engellenir, dördüncü turda gün kapanır; satır hiç çözülmez. `05df92d`'de aynı durum
süresiz giriş engeliydi (O2); ikisinde de bot işlem açamaz, fark her gün `KILL-SWITCH` kaydı düşmesi. §4 "Bilinen
sınırlar (ii)" yalnız iptali doğrulanmış satırı anlatıyor; bu hâl yazılmamış.
```python
@pytest.mark.parametrize("path", PATHS)
def test_r2_a_permanently_unreadable_unconfirmed_entry_halts_every_session(path, config, tmp_path):
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1
    s.runner.run_once()
    s.broker.fail_get_order = True         # kimlik brokerda artik yok: kalici okuma hatasi
    day1 = [s.runner.run_once().halted for _ in range(MAX_CANCEL_ATTEMPTS)]
    s.broker.open_orders = []
    day2 = [r.halted for r in [next_session(s).run_once()] + [s.runner.run_once() for _ in range(3)]]
    day3 = [r.halted for r in [session_after(s, 1).run_once()] + [s.runner.run_once() for _ in range(3)]]
    print("R2", path, day1, day2, day3, status_of(s.conn, s.entry), len(s.broker.submitted))
    assert not (any(day2) and any(day3)), (day1, day2, day3)
    # KIRMIZI (iki yol): her seans 3 tur engelli, 4. turda gun kapanir; satir `cancel_requested` kalir
```

### Arandı, bulunamadı
- **Tur başı görüntüsünün bayatlığı:** yanlış kapanış için pozisyonun tur içinde kapanması ve aynı anda stopun da
  listeden düşmesi gerekir; B2 dalında buna ek olarak giriş ve ikinci pozisyon okuması da hata vermeli. Yön fail-closed.
- **Sıfır dolum dalı normal işleyişte tetiklenmiyor:** bayat iptal yalnız aynı görüntüde pozisyonu olmayan sembole
  gider (`runner.py:528`), izleme sürerken yeni giriş yoktur. Dal ancak dışarıdan açılmış pozisyonda ya da bayat dolum
  bilgisinde çalışır; stopla kapsanıyorsa gün kapanmaz (commit'teki karşılaştırma testi).
- **`mark_order_closed`:** `src/` içinde `orders.status` okuyan iki sorgu var (`queries.py:45` izleme, `queries.py:64`
  `submitting`); hiçbiri `closed`'a bakmıyor. İzlenmeyen işlemde satır yine `closed` oluyor (karalama testi yeşil).
  İzlemesi sonradan kapanan satır bir daha `closed` olmaz, `filled`/`canceled` kalır: bugün okuyanı yok, kozmetik.
- **Deneme sayacı:** T1 gönderim (1), T2 ve T3 okunamayan tur (2, 3), T4 gün kapanır; okunabilir akışla aynı tur
  sayısı. Yeni süreçte satır journal'dan devralınırsa üç kör tur, dördüncüde kapanış. Bilinçli sonuç: iki kör turdan
  sonra giriş yeniden okunur ve hâlâ aktifse yeniden gönderim yapılmadan gün kapanır (tek gönderim; karalama R3).

### Yeni testler
- Mutasyonlar (`tests/test_entry_cancel_race.py`): durum ve miktarı yok sayan `_position_is_covered` 6 kırmızı;
  kalıcı kaydı yok sayan `_check_kill_switch` 1 kırmızı; B4 dalı kaldırılınca 6; B2 geri düşüşü kaldırılınca 2; B3
  sayacı ilerlemeyince 2 kırmızı. Önceki zayıflık 1 ve 2 kapanmış.
- **Boşluk:** `mark_order_closed` hiçbir şey yazmayacak biçimde bozuldu; ilgili 9 test dosyasında 420 test yeşil kaldı
  (`test_shadow_http.py` hataları mutasyonsuz koşuda da var, ortam kaynaklı). Hiçbir test izlenmeyen işlemin satırının
  `closed` olduğunu doğrulamıyor; yeni yöntemin olumlu yolu sabit değil.
- İki B1 testi (satır 1352, 1372) işlemin kaydedildiğini doğrulamıyor; eşleşme bozulursa `!= "closed"` boş yere geçer.
  `trades` satır sayısı eklenmeli. Satır 1357'deki "giris 5/10" yorumu yanlış (miktar 10 değil); kozmetik.

### Belge (§4) yeniden kontrol
- Yeni maddeler kodla uyumlu: sıfır dolum + tur başı pozisyonu, okunamayan giriş + görüntüye düşüş, koşullu `closed`,
  okunamayan turun denemeye sayılması, bilinen sınırlar (i) ve (ii), `held` notu.
- Eksik: satır 280-281 yeniden başlatmanın sayacı sıfırladığını (R1) ve gönderim sayısının üçten az kalabildiğini
  söylemiyor; satır 376'daki sınır (ii) doğrulanmamış iptal hâlini (R2) içermiyor. `runner.py:105` sabitinin
  açıklaması da okunamayan turun sayıldığını yazmıyor.
