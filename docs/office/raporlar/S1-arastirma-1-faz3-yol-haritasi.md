# S1 · Araştırma 1 · Faz 3 ve gölge sonrası yol haritası

Tarih: 2026-11-25. Kaynak: `main` 47a2a7d (salt okunur kopya); #63 için `origin/claude/killswitch-fix` a48daae farkı.
Depoya kod yazılmadı; ağ, broker ve iş akışı çağrısı yapılmadı. İki ölçüm sentetik veriyle bellekte koşuldu (§2).
Satır numaraları `main` 47a2a7d'ye göredir; `src/tlab/` öneki kısaltıldı.

## 1. Sonuç

1. Faz 3'ün istatistik çekirdeği var (`assess`, `compare`, `decide_promotion`) ama journal'a bağlı değil: üretimde tek çağıran baseline ölçümü. Kapalı işlem okuma, gün-bloğu belirsizlik, dönem raporu, walk-forward ve aday shadow modu yok.
2. Gölge→paper tarafında toplam işi ve sade gölge raporu hazır. Eksikler: kabul ölçütlerinin mekanik tablosu, paper için günde tek koşu kapısı, paper iş akışı, ilk paper günleri denetimi.
3. Dokuz paket öneriyorum; dosya kümeleri ayrık. P1 ve P5 şimdi birleşebilir; yedisi dalda yazılıp en erken 2 Aralık'ta birleşir. Yalnız P9 #63'e yığılır; hiçbiri `runner.py`'a dokunmaz.
4. Üç veri bulgusu raporlamayı doğrudan etkiliyor: veto metinleri hesap değeri ve fiyat taşıyor, virgülle bölme sayımı bozuyor; kill-switch çıkışı journal'a `manual` düşüyor; MAE/MFE hiç yazılmıyor.
5. Sıra: P1 ve P4 şema belgesi (şimdi) → P5 → kampanya kapanışı → P2 ∥ P3 → P4 → P7 ∥ P8 → P6 → P9. Gerçek veride walk-forward, terfi ve ilk emir ayrı kayıtlı karar ister.

## 2. Mevcut durum

| Yetenek | Var mı (dosya:satır) | Eksik |
|---|---|---|
| Kapalı işlem ve R (journal) | Kısmen. Yazma: `engine/reconciler.py:102 build_trade`, `core/types.py:525 r_multiple`, tablo `journal/migrations/001_initial.sql:83-113`. Okuma: koşu başına toplam (`journal/queries.py:79 session_summary`) ve `backtest/baseline.py:122 _r_values`. | Koşular arası; gün, mod, feed ve parametre süzgeçli okuma yok. Bir giriş birden çok çıkış emriyle kapanırsa birden çok satır oluşur (`reconciler.py:76-77`, kimlik `:40`): sayım birimi pozisyon değil. `kill_switch` sebebi hiç yazılmıyor: `engine/runner.py:427,439` sebebi yalnız log'a taşır (`:453,477`), kayıt `reconciler.py:85-99`'dan `manual` çıkar. MAE/MFE doldurulmuyor (`reconciler.py:127-153`). Risk sıfırsa R sessizce 0 (`types.py:532-533`). |
| Belirsizlik ölçümü | Var, bağımsızlık varsayımıyla: `learning/evidence.py:201 bootstrap_mean_ci`, `:261 assess`, `:329 compare`. | Gün-bloğu yok; eksikliği kodda ve sözleşmede yazılı (`evidence.py:13-19`, `AGENTS.md:1432-1435`, `baseline.py:105-106`). **Sentetik ölçüm** (ortalama 0 R, 40 gün × 5 işlem, 200 tohum, `assess` varsayılanları; nominal 10/200): gün etkisi σ=0,5 R iken bağımsız okuma 27/200 kez kesin hüküm verdi, gün-bloğu 14/200; σ=1 R iken 53/200'e karşı 13/200; gün etkisi yokken 12/200'e karşı 16/200. |
| Gece/dönem raporu | Yok. En yakını `tlab summary` (`cli.py:451-487`): tek koşu; para cinsinden net sonucu basar (`:480`). | R dağılımı, çıkış kırılımı, kanıt hükmü, dönem birleştirme yok. Veto sebepleri güvenle sayılamıyor: metinler özsermaye, alım gücü ve fiyat içerir (`risk/gate.py:117-119,129,137,173,184,191`); virgülle birleştirilir (`types.py:629`) ve virgülle bölünür (`queries.py:114`). **Sentetik deneme:** iki sebep beş parçaya bölündü. Tur hataları journal'da yok (`runner.py:164-169` yalnız log). |
| Walk-forward | Yok. Yapı taşları: `backtest/engine.py:106 Backtest` (resmi seans listesi `:146-156`), `strategies/orb.py:27 ORBParams`, `strategies/base.py:37 fingerprint`. | Kat planı, aday seçimi, örneklem dışı birleştirme yok; CLI yalnız not düşer (`cli.py:435`). |
| Shadow mode (aday parametre) | Yok. Journal modu tanımlı, üreten yok (`journal/writer.py:26`); gölge işi geçici journal'a `paper` yazar ve siler (`shadow_job.py:512-514`). Kampanya feed uyumunu ölçer, aday parametreyi değil (`shadow-observation.md:39-57`). | Aday kararlarının emirsiz kaydı ve karşı-olgusal sonucu yok (veto edilenler dahil, `README.md:75-77`). |
| Terfi kapısı | Kütüphane var: `learning/promotion.py:205 decide_promotion`, politika `:45`. Üretimde çağıran yok (`learning`'i içe aktaran tek yer `baseline.py:38`). | (b) walk-forward ve (c) shadow girdisi almıyor (`:205-210`); `params_versions` tablosu kullanılmıyor (`001_initial.sql:121-130`); eşiklerin gerçek R dağılımıyla yeniden ölçümü açık (`promotion.py:83-92`). |
| Gölge toplam işi | Var: `shadow_job.py:1378 collect`, `:914 aggregate`, `shadow-aggregate.yml`; kampanya başına bir kez, tekrar yalnız kayıtla (`:1462`). | Kod eksiği yok. Koşu kullanıcının tek tıklaması ve ayrı #17 kararı (`shadow-observation.md:614`). |
| Gölge→paper kabul tablosu | Kısmen: `scripts/shadow_report.py:227 render` üç ölçünün hükmünü ve gün sayımını yazar. | `unattended-paper.md:27-34` ölçütleri (üçü birlikte GEÇTİ, en az 15/20 `tamam`, koşusuz gün) mekanik değerlendirilmiyor. |
| Günde tek koşu kapısı | Yalnız gölge: `shadow/schedule.py:67 decide`, `shadow_job.py:253 gate`, `:293 _prior_runs`. | İş akışı ve iş adı sabit (`shadow_job.py:231-232`), günler sabit (`:79-100`); geç başlangıç gölgede kayıt, paper'da atlama olmalı. Gereksinim: `unattended-paper.md:185`. |
| Paper iş akışı | Yok. `alpaca-paper-check.yml` yalnız bağlantı okur. `tlab run` sürekli kipte sonsuz döngü (`runner.py:146-178`); log ve çıktı para değeri taşır (`runner.py:288`, `cli.py:480`). | Sınırlı döngü, susturulmuş çıktı, fiyatsız gün özeti, temizlik, iş akışı sözleşme testi. Kill-switch'in iki açığı main'de duruyor (`unattended-paper.md:168-191`); düzeltme #63'te. |
| İlk paper günleri denetimi | Yok; kontrol listesi yalnız metin (`unattended-paper.md:198-202`). | Journal'dan türeyen tutarlılık denetimi yok. "Bacaklar borsada mı" ve "gün sonunda pozisyon yok" journal'dan doğrulanamaz; broker okuması ister. |
| Kullanıcıya sade rapor | Gölge için var (`scripts/shadow_report.py`, `tests/test_shadow_report.py`). | Paper/journal için yok (istek: `unattended-paper.md:211-213`). |

Yeniden üretme: ölçüm betiği oturumun geçici dizininde (`s1-arastirma-1/blok_olcum.py`), depoda değil; parametreler yukarıda. Veto denemesi: bellekte journal, `GateVerdict.veto` ile `gate.py:117` ve `:135` kalıbında iki sebep, ardından `top_veto_reasons`.

## 3. İş paketleri

Ortak kurallar: her paket ağsız ve sentetik veriyle test edilir; holdout, gerçek veri ve P&L ölçümü yok; çıktılarda fiyat, miktar, özsermaye ve para cinsinden sonuç yok. Yeni `src/` modülü kapsama eşiğini (`pyproject.toml:103`) kendi testiyle taşır.

### P1 — Gölge→paper kabul tablosu · S · şimdi birleşebilir
- **Amaç:** `unattended-paper.md:27-34` ölçütlerini toplam özetinden mekanik çıkarmak; karar vermez, #17 kararına girdi üretir.
- **Dosyalar:** değişen `scripts/shadow_report.py`, `tests/test_shadow_report.py`. Betik `python3 -I` ile koştuğu için ikinci betik doğrulamayı içe aktaramaz; aynı dosyaya eklenir.
- **Arayüz:** `acceptance(summary, *, expected_campaign=None) -> list[dict[str, str]]`; satır: `olcut`, `durum` (`sağlandı` / `sağlanmadı` / `elle doğrulanacak`), `kanit`. CLI: `--kabul [--campaign <64 hane>]` raporun sonuna "Paper kabul ölçütleri" tablosu ekler.
- **Test:** gerçek `summarize` çıktısından (mevcut desen, `tests/test_shadow_report.py:26`): hepsi geçti; bir ölçü `belirsiz`; 14 ve 15 `tamam` gün (sınır); `bilinmiyor` günü "koşusuz gün" satırında görünür; kampanya uyuşmazlığı sabit hata; bayraksız çıktı bugünküyle bayt bayt aynı.
- **Kabul:** eşikler belgedekiyle aynı ve testte somut sayıyla; ilk gün denetimi ve "sistematik değil" satırları her zaman `elle doğrulanacak`; genel "geçti" cümlesi yok.
- **Bağımlılık:** yok. **Risk:** tablonun karar gibi okunması; başlıkta "karar değildir" yazar. Sonuç görülmeden birleşmeli (`unattended-paper.md:15-17`).

### P2 — Journal'dan kapalı pozisyon ve R · S · ≥2 Aralık
- **Amaç:** öğrenme katmanının tek okuma kapısı: pozisyon başına R ve borsa günü.
- **Dosyalar:** yeni `src/tlab/journal/trades.py`, `tests/test_journal_trades.py`. `queries.py`'a dokunulmaz (#63 aynı dosyayı değiştiriyor).
- **Arayüz:**
  ```python
  @dataclass(frozen=True)
  class ClosedPosition:
      key: str            # decision_id; yoksa trade_id
      session_day: date   # girişin borsa günü
      symbol: str; params_version: str; mode: str; data_feed: str
      r: float            # Σ net / (|giriş − planlı stop| × Σ miktar)
      legs: int; exit_reason: str; risk_defined: bool; carried: bool
  def closed_positions(conn, *, exchange_timezone: str, modes=("paper",), params_version=None,
                       first_day=None, last_day=None) -> list[ClosedPosition]
  def r_by_day(positions) -> dict[date, list[float]]
  ```
- **Test:** `JournalWriter` ile sentetik journal (`tests/test_queries.py:48-125` deseni): tek bacak; iki çıkış bacağı tek pozisyon; mod süzgeci; yaz/kış saatinde gün sınırı; stop = giriş (`risk_defined=False`, R listesine girmez); durdurma anından sonraki `manual` çıkış `kill_switch` okunur (`daily_state.halted_at`); `decision_id` boş; aynı gün iki koşu; boş journal.
- **Kabul:** tek bacaklı pozisyonda R, `trades.r_multiple` ile eşit; fonksiyon journal'a yazmaz (testte salt okunur bağlantı); sıra deterministik.
- **Bağımlılık:** yok. **Risk:** birim farkı: baseline raporu satır sayar (`baseline.py:122-127`), bu paket pozisyon sayar; fark belgelenir, baseline raporu değişmez.

### P3 — Gün-bloğu belirsizlik ölçümü · S · ≥2 Aralık
- **Amaç:** aynı günün işlemlerini bağımsız saymayan aralık ve hüküm.
- **Dosyalar:** yeni `src/tlab/learning/blocks.py`, `tests/test_learning_blocks.py`. `evidence.py` değişmez (ölçüm kuralı kayıtlı, `AGENTS.md:1381`).
- **Arayüz:**
  ```python
  @dataclass(frozen=True)
  class BlockEvidence:
      days: int; trades: int; mean_r: float
      ci_low: float | None; ci_high: float | None
      confidence: float; threshold_r: float; verdict: Verdict
      iid: Evidence       # aynı verinin bağımsız okuması, yan yana raporlanır
  def day_block_mean_ci(blocks, confidence=0.95, iterations=DEFAULT_ITERATIONS, seed=0) -> tuple[float, float]
  def assess_blocks(blocks, *, threshold_r=0.0, min_trades=100, min_days=20, ...) -> BlockEvidence
  def compare_blocks(candidate: Mapping[date, Sequence[float]], baseline: Mapping[date, Sequence[float]],
                     *, min_edge_r=0.0, ...) -> BlockEvidence   # günler birlikte yeniden örneklenir
  ```
  İstatistik: yeniden örneklenen günlerde Σ R / Σ işlem.
- **Test:** tek işlemli günlerde aralık `bootstrap_mean_ci` ile birebir aynı (denendi: eşit); gün etkili sentetik seride blok aralığı daha geniş; §2'deki yanlış hüküm ölçümü küçültülmüş tohumla regresyon; `min_days` ya da `min_trades` altında aralık `None`; boş blok ve sonlu olmayan değer hata; güven bütçesi (`required_iterations`); aynı girdi aynı çıktı.
- **Kabul:** katman kuralı geçer (`tests/test_architecture.py:147-156`: yalnız `core`, `errors`); `tests/test_evidence_interval.py` değişmeden yeşil.
- **Bağımlılık:** yok. **Risk:** az günde blok bootstrap de nominalin üstünde kalabilir (ölçüm: 13–16/200); modül bunu sınır olarak yazar, garanti demez.

### P4 — Dönem özeti: journal'dan fiyatsız JSON · M · ≥2 Aralık (şema belgesi şimdi)
- **Amaç:** "gece analizi"nin ilk hali: sayılar, R dağılımı, kanıt; günlük özetlerden dönem özeti.
- **Dosyalar:** yeni `src/tlab/journal_summary.py`, `tests/test_journal_summary.py`, `docs/designs/journal-summary.md` (şema sözleşmesi).
- **Arayüz:** `build(conn, *, exchange_timezone, modes=("paper",), first_day=None, last_day=None) -> dict`; `merge(parts) -> dict` (aynı gün iki kez hata); `python -m tlab.journal_summary build --journal F --out F` ve `merge --parts DIR --out F`. Şema 1: `window`, `source` (mod, feed, parametre sürümü, koşu ve kapanmamış koşu sayısı), `decisions` (`allowed`, `vetoed`, `veto_categories`, `veto_unclassified`), `orders.by_status`, `positions[]` (`day`, `symbol`, `params_version`, `r`, `exit_reason`, `legs`), `r` (ortalama, ortanca, uçlar, isabet, 0,5 R'lik histogram), `exits`, `evidence.iid`, `evidence.day_block`, `halts`, `caveats`.
- **Veto:** ham metin çıkmaz; sabit önek tablosuyla kategoriye çevrilir, tanınmayan yalnız sayılır.
- **Test:** sentetik journal; kanarya: journal'a konan işaret fiyat, miktar ve özsermaye değerleri çıktı baytlarında yok; aynı journal aynı bayt (`baseline.py:285-287` deseni); boş journal geçerli özet ve `insufficient_data`; karışık feed uyarısı (`AGENTS.md:1277-1283`); `merge(günlük parçalar)` = `build(bütün dönem)`; var olan dosya ezilmez (`job_io.py:33`).
- **Kabul:** `evidence` blokları P2+P3'ün doğrudan çağrısıyla eşit; para cinsinden alan yok; her özet "paper dolumları iyimser" uyarısını taşır (`unattended-paper.md:209-210`).
- **Bağımlılık:** P2, P3. **Risk:** şema oynarsa P5 kırılır; şema belgesi önce incelenir.

### P5 — Sade kullanıcı raporu · S · şimdi birleşebilir (P4 şema belgesinden sonra)
- **Amaç:** P4 özetinden kullanıcının okuyacağı Türkçe Markdown; yorum yok.
- **Dosyalar:** yeni `scripts/journal_report.py`, `tests/test_journal_report.py`; değişen `pyproject.toml` (mypy dosya listesi, `:86`; parmak izi dışında, `shadow_job.py:132-138`).
- **Arayüz:** `validate(summary) -> dict`, `render(summary) -> str`; `python3 -I scripts/journal_report.py --summary F [--out rapor.md]`.
- **Test:** şema 1'e göre elle yazılmış örnekler; bilinmeyen anahtar ve yanlış tür sabit hata (`shadow_report.py:73-74` deseni); aralık hesaplanmadıysa sayı basılmaz; yalnız standart kütüphane; `--out` ezmez.
- **Kabul:** rapor işlem, veto, R dağılımı ve hata sayılarını taşır (`unattended-paper.md:211-213`); fiyat ve hesap değeri yok.
- **Bağımlılık:** P4 şeması. **Risk:** şema kayması; P4 testine "gerçek `build` çıktısı `validate`'ten geçer" sözleşme testi eklenir.

### P6 — Walk-forward düzeneği · M/L · ≥2 Aralık
- **Amaç:** aday parametreyi yalnız geçmiş katta seçip sonraki katta ölçmek; çıktı kanıttır, karar değil.
- **Dosyalar:** yeni `src/tlab/learning/folds.py` (saf), `src/tlab/backtest/walkforward.py`, `tests/test_folds.py`, `tests/test_walkforward.py`.
- **Arayüz:**
  ```python
  @dataclass(frozen=True)
  class Fold: index: int; train: tuple[date, ...]; test: tuple[date, ...]
  def plan_folds(days, *, train_days: int, test_days: int, step_days=None, anchored=False) -> list[Fold]
  def walk_forward(*, config, market_factory, sessions, incumbent: ORBParams,
                   candidates: Sequence[ORBParams], folds, fill_model, data_feed) -> dict[str, Any]
  ```
  Çıktı: kat başına seçilen aday ve işlem sayıları; örneklem dışı günlerde aday ve mevcut ayarın gün-bloklu R'si; `compare_blocks` sonucu; sınanan aday sayısı (güven düzeltmesi, `promotion.py:167-172`).
- **Test:** `tests/test_backtest.py:42,76` üreteçleri: katlar örtüşmez, test eğitimden sonra; az gün hata; test günlerinin barlarını değiştirmek o katın seçimini değiştirmez (`:265` deseni); deterministik; rastgele yürüyüşte çok tohumda `better` beklenmez (lamba, kanıt değil: `AGENTS.md:297-301`); kurgulanmış avantajlı seride aday seçilir.
- **Kabul:** düzenek dosya yolu almaz, yalnız yüklenmiş bar deposu ve seans listesi (holdout açılamaz, `AGENTS.md:342-344`); terfi kararı üretmez.
- **Bağımlılık:** P2, P3; `Backtest`'i değiştirmeden kullanır. #63 birleşince döngü davranışı değişebilir; testler iki ağaçta koşulur.
- **Risk:** görülmüş 2026q3 baseline'ında koşmak görülmüş veriye ayar çekmektir (`AGENTS.md:913-914`); gerçek veride koşu ayrı kayıtlı karar ister.

### P7 — Paper "günde tek koşu" kapısı · M · ≥2 Aralık
- **Amaç:** aynı seans gününde ikinci işlem sürecini hiçbir tetikle başlatmamak (`unattended-paper.md:142-146,185`).
- **Dosyalar:** yeni `src/tlab/paper_gate.py`, `tests/test_paper_gate.py`.
- **Arayüz:** `decide(now, planned, prior) -> GateDecision` (`atla` / `islem`; geç başlangıç atlar); `gate(env, *, clock, output, planned, workflow_file, trade_job) -> int`; `python -m tlab.paper_gate --output "$GITHUB_OUTPUT"`. Varsayılan `PLANNED_DAYS = ()`: yürütme kararına kadar her gün atlar.
- **Test:** yerel sahte Actions API (`tests/test_shadow_gate.py` deseni): durum tablosu (atlanmış, bitmiş, süren, iş yok); yeniden deneme koşmaz; sonraki koşu sayılmaz; tek sayfayı aşan liste ve API hatası kapıyı kapalı tutar; yönlendirme izlenmez, token başka yere gitmez; secret'lı ortamda başlamaz; yaz ve kış açılışı; plan dışı günde API çağrısı yok.
- **Kabul:** kapı Alpaca modülü içe aktarmaz (AST testi); okunamayan geçmiş hiçbir durumda `islem` üretmez.
- **Bağımlılık:** kod olarak yok. **Risk:** Actions API yardımcıları `shadow_job.py:293-390`'dan kopyalanır, zamanla ayrışabilir (soru 6).

### P8 — Paper günü yaşam döngüsü denetimi · M · ≥2 Aralık
- **Amaç:** "ilk paper günleri" kontrol listesinin journal'dan doğrulanabilen kısmını sabit kodlu bulgulara çevirmek.
- **Dosyalar:** yeni `src/tlab/journal/lifecycle.py`, `tests/test_journal_lifecycle.py`.
- **Arayüz:** `Finding(code, severity, count)`; `day_findings(conn, *, session_day, exchange_timezone, session_close=None) -> list[Finding]`; `UNVERIFIABLE: tuple[str, ...]` (journal'dan doğrulanamayan maddeler). Kodlar: `izinli_karar_emirsiz`, `emir_kesinlesmedi`, `iptal_askida`, `dolan_giris_islemsiz`, `islem_dolumsuz`, `cikis_sebebi_bilinmiyor`, `kapanis_sonrasi_cikis`, `durdurma_sonrasi_emir`, `kosu_kapanmadi`, `bilinmeyen_emir_durumu`.
- **Test:** temiz gün bulgusuz; her kusur tek tek ekilir ve yalnız kendi kodunu üretir; dry-run günü (`cli.py:309`) emirsiz karar yüzünden kusur sayılmaz; bulgu metni sembol ve fiyat taşımaz.
- **Kabul:** her kod `unattended-paper.md:198-202` maddesine belgede eşlenir; durdurma kuralı için hangi kodların "sistematik hata" sayıldığı sabit (`:195-197`).
- **Bağımlılık:** P2 gerekmez. `cancel_requested` ve `cancel_pending` durumları yalnız #63'te; modül tanımadığı durumu çökmek yerine `bilinmeyen_emir_durumu` sayar. **Risk:** ilk günlerde yanlış alarm.

### P9 — Paper seans işi ve iş akışı · L · ≥2 Aralık, #63 üstüne, kararlardan sonra
- **Amaç:** bir seansı sınırlı döngüyle işletmek, yalnız fiyatsız gün özeti yüklemek.
- **Dosyalar:** yeni `src/tlab/paper_job.py`, `.github/workflows/paper-session.yml`, `tests/test_paper_job.py`, `docs/designs/paper-session.md`; değişen `tests/test_architecture.py` (iş izni istisnası `:983-993`, yükleme süresi `:1513`, iş akışı sözleşme testi).
- **Arayüz:** `python -m tlab.paper_job trade --workdir DIR --out paper-day.json`: `run_once` döngüsü (`shadow_job.py:545-559` deseni), bütün log kapalı (`job_io.py:19`), tur sayaçları (çağrılan, hatalı), kapanıştan sonra salt okunur "açık pozisyon ve emir sayısı 0" denetimi. Gün özeti: P4 `build` + P8 bulguları + tur sayaçları.
- **Test:** `tests/test_runner.py:63,171` sahte broker ve veri, sahte saat: kanarya fiyat ve özsermaye stdout'ta ve özette yok; kill-switch günü; hatalı turlar sayılır; iş 6 saat sınırından önce biter; temizlik her yolda. İş akışı: secret yalnız işlem adımında, kapı secret'sız, tek eşzamanlılık grubu, yalnız `main`.
- **Kabul:** `cmd_run` kullanılmaz (çıktısı para değeri taşır, `cli.py:480`); `PLANNED_DAYS` boşken iş hiçbir şey yapmaz; ilk koşu ayrı yürütme kararıyla (`unattended-paper.md:192-194`).
- **Bağımlılık:** P4, P7, P8; #63 (kill-switch açıkları kapanmadan kabul yok, `:191`); feed, ortam, erken kapanış ve miktar kararları (sorular 1–4).
- **Risk:** ilk gerçek emir yolu; paper dolum kaynağı doğrulanmamış (`unattended-paper.md:53`).

**Bilerek paket yapılmayanlar:** aday shadow modu, karşı-olgusal sonuç hesabı, terfi kapısına walk-forward/shadow girdisi ve `params_versions` yaşam döngüsü. Aday ve yeterli örneklem yokken kapı yalnız `HOLD` der (son ölçüm 67 < 100, `AGENTS.md:859-860`). MAE/MFE ve `kill_switch` yazımı `runner.py`/`reconciler.py` ister; #63 sonrasına kalır.

## 4. Önerilen sıra

0. **Ön koşul (Yönetim):** toplam koşusu ve doğrulaması; ardından kampanya pin testinin tarihsel kayda çevrilmesi (`tests/test_shadow_job.py:723-748`; desen `tests/test_measurement_freeze.py:75,137-166`) ve `shadow-observation.md` §7 kaydı. Bu yapılmadan `src/` PR'ları main CI'da kırmızı kalır. Tekrar toplama ihtimali kapanmadan `src/` birleşmez: toplam işi kimliği ağaçtan hesaplar (`shadow_job.py:1431-1434`).
1. **Şimdi:** P1. Gerekçe: ölçütler sonuç görülmeden sabitlenmeli; 2 Aralık'ta hazır olmalı. Aynı anda P4'ün şema belgesi; onaylanınca P5.
2. **Dalda şimdi, birleşme ≥2 Aralık:** P2 ∥ P3. Gerekçe: küçük, bağımsız, bütün öğrenme zinciri bunlara dayanıyor.
3. P4. Gerekçe: P9'un gün özeti ve kullanıcı raporu buna bağlı.
4. P7 ∥ P8. Gerekçe: paper kararını beklemeden yazılabilir; kararlar gecikirse boşa gitmez (kapı varsayılanı kapalı).
5. P6. Gerekçe: kullanıcıya etkisi en geç olan iş; gerçek veride koşusu zaten ayrı karar.
6. P9. Gerekçe: #63 ve dört karar olmadan başlayamaz.

Birleşme sırası (≥2 Aralık): ön koşul → #63 → P2, P3 → P4 → P7, P8 → P6 → P9.
Paralellik: dokuz paketin dosya kümeleri kesişmiyor. Ortak dosyaya dokunan yalnız ikisi var: `pyproject.toml` (P5) ve `tests/test_architecture.py` (P9). `runner.py`, `queries.py`, `core/types.py`, `sim_broker.py` (hepsi #63'te) hiçbir pakette yok.

## 5. Açık sorular

| # | Soru | Kimin | Önerilen varsayılan |
|---|---|---|---|
| 1 | Paper feed'i IEX mi SIP mi? | Kullanıcı, toplamdan sonra | Üç ölçü de GEÇTİ ise IEX; değilse paper yok, yeni kampanya (`unattended-paper.md:43-46`). |
| 2 | Yürütme ortamı A mı D mi? | Kullanıcı + Codex | A'nın daraltılmış biçimi (`unattended-paper.md:128-134`). |
| 3 | 15:10 kapanışı nasıl ifade edilir? | Codex + kullanıcı | `config/base.yaml:23` değeri 50; sınır buna izin veriyor (`config.py:136`). Ölçülen davranışı değiştirir; ayrı kayıtlı karar (`unattended-paper.md:83-93`). |
| 4 | İlk beş seansta "tek sembol, en küçük miktar" nasıl zorlanır? | Kullanıcı + Codex | Kapı miktarı riskten hesaplar (`risk/gate.py:169-170`), tavan yok. Kayıtlı kararla ayrı paper-kabul ayarı; risk sınırı değişikliği sayılır (`AGENTS.md:952-953`). |
| 5 | `min_days` tabanı ve birincil hüküm hangisi? | Codex | `min_days=20`, `min_trades=100` aynı; raporda birincil gün-bloğu, bağımsız okuma yanında. Gerçek veri görülmeden sabitlenir. |
| 6 | Paper kapısı API kodunu kopyalasın mı, `shadow_job`'dan mı ayrıştırılsın? | Claude + Codex | Kopyala; doğrulanmış gölge koduna dokunma. Ortak modül ayrı ve sonraki iş. |
| 7 | Gün özetinde pozisyon başına R ve sembol herkese açık artefakta girer mi? | Kullanıcı + Codex | Evet; R oran, fiyat değil (`unattended-paper.md:211-213`). Journal günlük silinirse dönem kanıtı yalnız böyle kurulur (`:65`). |
| 8 | Veto sebeplerinin yazım biçimi düzeltilsin mi? | Claude, #63 sonrası | Şimdilik okuma anında kategori (P4). Kalıcı çözüm yeni göç ve `core/types.py` ister. `tlab summary` herkese açık log'da kullanılmaz. |
| 9 | Walk-forward hangi gerçek veride koşar? Faz 4'ün `evaluation_eligible` bayrağı kapıya nasıl gelir? | Codex | Şimdi yalnız sentetik. Gerçek koşu yeni veri kümesi ve kayıtlı kararla. Bayrak `research/` çıktısından, arayüzü Codex belirler (`promotion.py:209-219`). |

**Doğrulanmadı:** #63'ün koruma kontrolü sonucunu journal'a yazıp yazmadığı (yalnız fark istatistiği ve belge değişikliği okundu); Alpaca paper dolumlarının hangi veriden simüle edildiği; hiçbir paketin gerçek ortam davranışı.
