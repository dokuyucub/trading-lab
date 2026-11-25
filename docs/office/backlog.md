# İş listesi — Sprint 1 Planlama Toplantısı

Tarih: 2026-11-25 · Birim: Planlama Toplantısı · Durum: Onay Kurulu incelemesini bekliyor (kod yazılmadı).
Girdi: `docs/office/raporlar/S1-*.md` (8 rapor). Kod tabanı: `main` 47a2a7d (+1 belge birleşmesi); PR #63 `claude/killswitch-fix` @ f654f0d.
Rapor kısaltmaları: **YÇ** yürütme çekirdeği · **BT** backtest/öğrenme · **R63** PR #63 incelemesi · **F3** Faz 3 yol haritası ·
**ALP** Alpaca emir davranışı · **GÜV** güvenlik · **TK** test ve kalite · **UF** ufuk. Örnek: "YÇ B1" = o raporun B1 bulgusu.
Kırmızı karalama testleri oturumun geçici dizinindedir (`wt-a1`, `wt-a2`, `wt-r63`, `wt-a5`); kalıcı değildir, asıl kaynak
raporlardaki kod parçalarıdır. Hiçbir iş `config/*.yaml`'a, `src/tlab/research/`'e ya da Faz 4'e dokunmaz.

## 1. Özet

1. 63 iş: **A** (şimdi birleşir) 14 · **B** (yürütme, #63 üstüne, ≥2 Aralık) 16 · **C** (dalda şimdi, ≥2 Aralık) 22 · **D** (karara bağlı) 11.
2. Sprint 1 dokuz iş: A1, A3, B0, B63, A2, A6a, A5a, A4, C0. Davranış değiştiren `src/` kodu yok; hepsi 2 Aralık'tan önce biter.
3. Sprint 1 sonunda: test süiti belirgin kısalır (ölçüm: sunucu kullanan 15 dosya 791 → 133 sn); kabul tablosu toplam sonucu
   görülmeden main'de; Koruma v2 tasarımı ve #63'ün son hali Codex'in önünde; çözülme planı ve pin dönüşümü 2 Aralık'a hazır.
4. Dondurma: 2 Aralık'a kadar main'e yalnız test, belge ve script girer. C0 birleşmeden hiçbir `src/` PR'ı main CI'da yeşil olamaz.
5. Darboğaz: `runner.py`'a dokunan 12 iş (B1, B3, B6–B14, C9b) #63 üstünde tek sıradır; adaptör (C8→B4→B5) ve sim (C9a→C10) zincirleri ayrı yürür.
6. Ölçüm semantiğini değiştiren 6 iş (C9a, C9b, C10, C11, C13, C15) dalda yazılır; kayıtlı karar olmadan hiçbir ölçümde kullanılmaz.
7. Sahipten bugün beklenen üç ayar: yabancı PR'ları geçici kapatmak, dış PR iş akışlarını onaya bağlamak, `main` kuralı (§6).
8. **En büyük risk:** Koruma v2'nin dayandığı "tam dolumdan sonra stop `held` kalır ve açık listede görünmez" bilgisi ikincil kaynaklı;
   broker çağrısı yasak olduğu için doğrulanamıyor. Yanlışsa #63 üstündeki B6–B10 yeniden yazılır. Azaltma: v2 önce yalnız okur ve loglar (İtiraz 3).

## 2. İş listesi

Boy: S ≈ 150 satırın altı, M ≈ 400'e kadar. "Zincir": aynı dosyaya dokunan işler sırayla yapılır; dal bir öncekinin ucundan açılır.
Dondurma sürerken `src/` dokunan dalda kabul edilen tek kırmızı kampanya pin testidir.

### A — şimdi birleşir (test, belge, script)

| ID | İş | Kaynak | Dosyalar | Dal | Boy | Dondurma | Kabul ölçütü | Bağımlılık |
|---|---|---|---|---|---|---|---|---|
| A1 | Test süitini hızlandır: sahte sunucuda `TCP_NODELAY`, `serve_forever(poll_interval=0.01)`, SDK yeniden deneme uykusunu sanallaştıran `autouse` fixture | TK Ö1–Ö3; UF 19 | `tests/alpaca_stub.py`, `tests/conftest.py`, `tests/test_artifact_roundtrip.py`, `tests/test_paper_probe.py`, `tests/test_shadow_collect.py`, `tests/test_shadow_gate.py` (hazır diff `wt-a5`, +46/−5) | `claude/test-hizlandirma` | S | şimdi | Toplanan test ve sonuç aynı (1534 = 1528 geçti + 6 atlandı); hiçbir test silinmez, atlanmaz, iddia değişmez; tam `make check` süresi önce/sonra raporda; en az bir 429 testi `SDK_RETRY_SLEEPS` dolu olduğunu doğrular | — (#63 de `tests/alpaca_stub.py`'a dokunur; değişen satırlar ayrık) |
| A2 | "Önce kaydet, sonra gönder" sırasını sabitleyen test; emir kaydı yazılamazsa emir gitmez | TK §6.1, §5, §6.3 | yeni `tests/test_write_ahead_order.py` | `claude/test-once-kaydet` | S | şimdi | main'de ve #63 ağacında yeşil; `_handle_intent`'te "önce gönder" mutasyonu kırmızı (bugün 109 testten sağ çıkıyor); `src/` diff'i boş | — |
| A3 | P1: gölge→paper kabul tablosu (`--kabul [--campaign]`) | F3 P1 | `scripts/shadow_report.py`, `tests/test_shadow_report.py` | `claude/golge-kabul-tablosu` | S | şimdi; **toplam sonucu görülmeden (≤1 Aralık)** | Eşikler `unattended-paper.md:27-34` ile aynı ve testte somut sayıyla (14/15 `tamam` sınırı, bir ölçü `belirsiz`, `bilinmiyor` günü, kampanya uyuşmazlığı); bayraksız çıktı bayt bayt aynı; "karar değildir" başlığı, genel "geçti" cümlesi yok | — |
| A4 | Sahip panosu: tek sayfa durum (Bugün ne oldu / Sizden beklenen / Risk durumu / Yaklaşan tarihler) | UF 1 | yeni `docs/sahip/DURUM.md` | `claude/sahip-panosu` | S | şimdi | Dört kutu dolu ve teknik terimsiz; "Sizden beklenen" §6'nın ilk beş maddesini ve K4'ü taşır; fiyat, hesap değeri, koşu kimliği yok | A6a (tarihler) |
| A4b | Günlük sade özet aracı (`shadow-day.json` → en çok 10 satır) | UF 2 | yeni `scripts/owner_digest.py`, `tests/test_owner_digest.py`; `pyproject.toml` (mypy listesi) | `claude/sahip-gunluk-ozet` | S | şimdi | Dört gün durumu için sabit metin testi; sahte işaretli fiyat, SHA, koşu kimliği çıktıda yok; bilinmeyen alan sabit hata | Sprint 1 dışı; C5 ile birleştirilmesi önerilir (İtiraz 2) |
| A5a | Mimari testleri sıkılaştır: tarayıcıya GitHub PAT ve Cloudflare token deseni; tarayıcı kancası her dosya türünde; `.yaml` uzantılı iş akışı kör noktası; secret'lı işte `cache` yasağı; CI'da git okunamazsa atlamak yerine hata | GÜV O3, D3, D4; TK §6.7 | `tests/test_architecture.py`, `.pre-commit-config.yaml` | `claude/mimari-test-sikilastirma` | S | şimdi | Her kural için ekilen ihlalle kırmızı kanıt; mevcut ağaç yeşil; var olan hiçbir kural gevşemez, yeni istisna tek tek gerekçeli | — |
| A5b | Açık depo belge düzeltmeleri: `SECURITY.md` yeniden yazımı; "depo gizli" ifadeleri; AGENTS §1'e güncel durum ve kampanya dondurması kaydı; README durum satırı ve bilinen iyimserlik listesi | GÜV D10; UF 18; BT O4 | `SECURITY.md`, `docs/github-paper-check.md`, `AGENTS.md` (§1), `README.md` | `claude/belge-acik-depo` | S | şimdi | `SECURITY.md` Actions secret'larını, başlatıcı anahtarını ve özel bildirim kanalını anlatır; "depo gizli" yalnız A5c ve C19 dosyalarında kalır; AGENTS değişikliği Codex ONAY'lı | — |
| A5c | `ci.yml`: işlere `timeout-minutes`; kanaryadan `cache` kaldır; bayat "depo gizli" yorumları | GÜV D5, D4, D10 | `.github/workflows/ci.yml`, `.github/workflows/artifact-roundtrip.yml` (yalnız yorum) | `claude/ci-zaman-asimi` | S | şimdi | Süre sınırı A1 sonrası CI'da ölçülen `quality` süresinin en az 2 katı (İtiraz 7); tetikleyiciler ve `quality` adımları aynı; `test_architecture` yeşil | A1 birleşmiş, CI süresi ölçülmüş |
| A6a | Dondurma sonrası birleştirme sırası (çözülme planı) ve son kullanma takvimi | UF 10, 15; F3 §4; GÜV D2 | yeni `docs/ops/cozulme-plani.md`, `docs/ops/takvim.md` | `claude/ops-cozulme-takvim` | S | şimdi | Sıra bu listenin bağımlılık sütunuyla çelişmez; her adımın ön koşulu ve geri alma komutu yazılı; takvim satırları (30 Kasım, 1–2 Aralık, 24 Aralık, 1 Ocak, 11 Ocak, 20 Ocak 2027, toplam artefaktının 90. günü) kaynağıyla | Codex ONAY (sıra) |
| A6b | Sürüm → commit tablosu ve CHANGELOG başlıkları (etiketleri Yönetim basar) | UF 9 | yeni `docs/ops/surumler.md`, `tests/test_release_table.py`; `CHANGELOG.md` | `claude/surum-tablosu` | S | şimdi | Test: CHANGELOG'daki her sürüm başlığı tabloda, her satırda 40 haneli commit; kampanyanın koştuğu commit'in satırı var; eşleme Codex ile doğrulanmış | K15 |
| A7 | Risk kapısının doğrudan sınanmayan vetoları (`pending_orders`, `unknown_order_risk`, sınırlar bir hisseye yetmezse) | TK §6.2, §5 | `tests/test_gate.py` | `claude/test-kapi-veto` | S | şimdi | `gate.py:87` ve `:189`'u silen mutasyonlar kırmızı (bugün hiçbir test düşmüyor); main'de yeşil | — |
| A8 | `run_forever` karakterizasyonu (sahte uyku ve saat): tek tur hatası döngüyü öldürmez, bekleme dizisi, `KeyboardInterrupt` | TK §6.4; UF 6; YÇ §4 | yeni `tests/test_run_forever.py` | `claude/test-run-forever` | S | şimdi | main ve #63 ağacında yeşil; gerçek uyku yok; çarpanı ya da hata yakalamayı bozan mutasyon kırmızı; 8 kat bekleme "bilinen açık (B3)" notuyla sabit | — |
| A9 | Başlatıcı testinin gerçek saate bağımlılığı (New York 08:30–09:29'da kırmızı) | GÜV kapsam dışı notu | `infra/shadow-starter/worker.test.js` (`worker.js` değişmez) | `claude/starter-test-saat` | S | şimdi | Sabitlenmiş 08:30–09:29 anında yeşil; `worker.js` diff'i boş (dağıtılan kod = depo) | — |
| A10 | Sade Türkçe olay rehberi (erken alarm, anahtar sızması, başlatıcı anahtarı bitişi, yabancı koşu) | UF 4; GÜV Y1 | yeni `docs/sahip/rehber.md` | `claude/sahip-rehberleri` | S | şimdi | Her olay için belirti, ilk üç adım, kime yazılır; komut satırı gerektirmez; paper'a özgü olaylar "paper tasarımıyla" notuyla açık bırakılır | A4 |

### B — yürütme çekirdeği: dalda şimdi, #63 üstüne, birleşme ≥2 Aralık

| ID | İş | Kaynak | Dosyalar | Dal | Boy | Dondurma | Kabul ölçütü | Bağımlılık |
|---|---|---|---|---|---|---|---|---|
| B0 | Tasarım notu "Koruma denetimi v2" ve Codex'e ÖN RAPOR | ALP K1–K5, K8; YÇ B2, B3, B6, B11, B13, B14; R63 B5, O1, O2, R1, R2, (c) | yeni `docs/designs/protection-check-v2.md` (`unattended-paper.md`'ye dokunmaz: #63 değiştiriyor) | `claude/koruma-v2-tasarim` | M | şimdi (belge) | §4 T1'deki on soru yanıtlı; B4–B10 için dosya listesi, kabul testi ve "davranışı değiştirir mi" işareti; "oku ve logla" ile "uygula" aşamaları ayrık; Codex yanıtı kayıtta | — |
| B63 | #63 dalında kalan test boşluğu ve belge notları: `mark_order_closed` olumlu yolu; iki B1 testine `trades` satır sayısı; §4'e R1/R2 sınırı; `MAX_CANCEL_ATTEMPTS` açıklaması | R63 yeniden inceleme (Yeni testler, Belge §4) | `tests/test_entry_cancel_race.py`, `docs/designs/unattended-paper.md`, `src/tlab/engine/runner.py` (yalnız sabit açıklaması) | `claude/killswitch-fix` (PR'ın kendi dalı) | S | ≥2 Aralık (#63 ile) | `mark_order_closed`'u boşaltan mutasyon kırmızı (bugün 420 test yeşil kalıyor); davranış diff'i yok; Codex ONAY'ı yeni başa alınır | — |
| B1 | Journal hatası kill-switch'i ve gün sonu kapanışını durdurmasın | YÇ B1; TK §5, §6.3; R63 (c) | `src/tlab/engine/runner.py`, `tests/test_kill_switch_durability.py` | `claude/journal-hata-kapanis` — **claude/killswitch-fix üstüne** | S | ≥2 Aralık | `orders`/`fills` yazılamazken zarar sınırı ve kapanış penceresi turunda pozisyon kapatılır (YÇ test_f1, iki durum; önce kırmızı); journal hatasında yeni giriş yok, tur sürer | B63 |
| B2 | Canlı `run` yolunda sonlu HTTP zaman aşımı (broker ve veri istemcisi) | YÇ B4; UF 6, 16; TK §6.5 | `src/tlab/cli.py`, `tests/test_cli_run.py` | `claude/run-zaman-asimi` (main'den; #63 dosyalarına dokunmaz) | S | ≥2 Aralık | Yakalanan `Session.request` çağrısı `timeout` taşır (YÇ test_f4 deseni; istek gönderilmez; önce kırmızı); `sdk_compat.bound_transport` yeniden kullanılır | — |
| B3 | Hata beklemesi kapanış tamponunu yemesin (uyku `poll`'u aşmaz; config doğrulaması) | YÇ B5; UF 6 | `src/tlab/engine/runner.py`, `src/tlab/config.py`, `tests/test_run_forever.py`, `tests/test_config.py` | `claude/backoff-kapanis` — **killswitch-fix üstüne** (B1'in ucundan) | S | ≥2 Aralık | YÇ test_f5: kapanıştan 7 dk önce biten kesintide pozisyon kapatılır (önce kırmızı); tampona sığmayan `poll` config hatası; A8 testi bilinçli güncellenir | B1, A8 |
| B4 | Adaptör: bracket bacaklarını iç içe oku (`OrderRef.legs`); açık emir listesinde `limit=500` | ALP K1(a), K5; YÇ B6 | `src/tlab/execution/broker.py`, `src/tlab/execution/alpaca_broker.py`, `src/tlab/core/types.py`, `src/tlab/shadow/broker.py`, `src/tlab/backtest/sim_broker.py`, `tests/alpaca_stub.py`, `tests/test_alpaca_contract.py`, `tests/test_protocols.py` | `claude/koruma-v2-ic-ice-okuma` — **killswitch-fix üstüne** (C8'in ucundan) | M | ≥2 Aralık | Sahte sunucuda ebeveyn ve iki bacak durumlarıyla `OrderRef`'e taşınır; liste isteği `limit=500` gönderir; runner kararları değişmez (yarış testleri aynı sonuç) | B0, C8 |
| B5 | Adaptör: `client_order_id` ile okuma; toplu iptalin 207 gövdesi; kısmi dolum + iptalde `filled_at` düşüşü; kesin ret ayrımı (`OrderRejected`); iptal/kapatma hata yolları sahte sunucuda | ALP K8, K3, K6; YÇ B13, B8; TK §6.5, §6.6 | `src/tlab/execution/alpaca_broker.py`, `src/tlab/execution/broker.py`, `src/tlab/errors.py`, `tests/alpaca_stub.py`, `tests/test_alpaca_contract.py` | `claude/koruma-v2-adaptor-ayrim` — B4'ün ucundan | M | ≥2 Aralık | 2xx olmayan 207 satırı sayılır; `filled_qty>0, filled_at` boş kayıt dolum üretir; 4xx (408/429 hariç) `OrderRejected` (alt sınıf: runner davranışı aynı); "pozisyon yok" eşlemesi koşar | B4 |
| B6 | Koruma kanıtını ebeveynin bacaklarından oku; `replaced` terminal; iki tur arasında biten işlem "korumasız" sayılmasın | ALP K1(b,c), K4; YÇ B6, B11 | `src/tlab/engine/runner.py`, `tests/test_entry_cancel_race.py` | `claude/koruma-v2-kanit` — runner zinciri (B3 + B5 birleşimi) | M | ≥2 Aralık | Bacak durumları her koruma kararında loglanır; `held` kuralı sabit bayrakla **kapalı** gelir (kapalıyken davranış aynı, açıkken YÇ test_f13 yeşil); YÇ test_f11 yeşil; `replaced` hedef sahipsiz çıkış saymaz; long ve short | B0, B3, B5, K9 |
| B7 | Her turda her açık pozisyon için koruma denetimi (giriş emrinden bağımsız) | YÇ B3, B2; ALP K2 | `src/tlab/engine/runner.py`, yeni `tests/test_position_protection.py` | `claude/koruma-v2-her-tur` — B6'nın ucundan | M | ≥2 Aralık | YÇ test_f2a/f2b kırmızı→yeşil: hiç çıkış bacağı olmayan pozisyon o turda kapatılır ve ERROR notu düşer; borsa kapalıyken açık pozisyon notu; yalnız `held` bacaklı pozisyon K9'a kadar loglanır | B6 |
| B8 | Kısmi dolmuş girişin kalanı: süre sonunda iptal → koruma doğrula → gerekirse yalnız o sembolü kapat | YÇ B2; ALP K2, soru 3 | `src/tlab/engine/runner.py`, `tests/test_entry_cancel_race.py` | `claude/koruma-v2-kismi-dolum` — B7'nin ucundan | M | ≥2 Aralık | YÇ test_f12: saatler yerine N tur içinde iptal ve kapatma/not; iptal yalnız giriş kimliğine gider; gün kilitlenmez | B7, K10 |
| B9 | `_flatten_all` ve sahipsiz çıkış `held` bacağı görsün; 403 `held_for_orders` ayrı loglansın | YÇ B14; ALP K3; R63 (c) | `src/tlab/engine/runner.py`, `tests/test_kill_switch_durability.py` | `claude/koruma-v2-kapatma` — B8'in ucundan | S | ≥2 Aralık | `held` stop açık listede yokken kapatma, bacaklar terminal doğrulanmadan gitmez; iptal kesinleşmezse her tur yeniden denenir ve not düşer | B8 |
| B10 | #63 bilinen sınırları: deneme sınırı yeniden başlatmayla sıfırlanmasın; kalıcı okunamayan giriş çözülsün; okunamayan eski giriş + sahipsiz çıkış | R63 R1, R2, O2, B5 | `src/tlab/engine/runner.py`, `src/tlab/journal/queries.py`, `tests/test_entry_cancel_race.py` | `claude/koruma-v2-sinirlar` — B9'un ucundan | M | ≥2 Aralık | R63 test_r1, test_r2, test_b5 kırmızı→yeşil; sınır journal'dan türetilir | B9, K18 |
| B11 | Kesin ret: satır `rejected`, sembol o gün dışarıda; evren kilitlenmez | YÇ B8 | `src/tlab/engine/runner.py`, `tests/test_runner.py` | `claude/kesin-ret` — runner zinciri | S | ≥2 Aralık | YÇ test_f7: reddedilen SPY sürerken AAPL emri gider | B5 |
| B12 | Mutabakat penceresi en eski kapanmamış emirden başlasın; kapanıştan sonra bir tur | YÇ B9; BT B10 | `src/tlab/engine/runner.py`, `tests/test_runner.py` | `claude/mutabakat-penceresi` — runner zinciri | S | ≥2 Aralık | YÇ test_f6: cuma son dakika çıkışı pazartesi `trades`'e yazılır | — |
| B13 | Kurulamayan emir veto olarak kaydedilsin; sembol başına istisna turu öldürmesin | YÇ B10 | `src/tlab/engine/runner.py`, `src/tlab/risk/gate.py`, `tests/test_runner.py`, `tests/test_gate.py` | `claude/kurulamayan-emir` — runner zinciri | S | ≥2 Aralık | YÇ test_f8: `ValidationError` çıkmaz, karar "emir kurulamadı" vetosuyla yazılır, sonraki semboller değerlendirilir | A7 |
| B14 | Kill-switch kapanışı journal'da `kill_switch` etiketi | YÇ B12; BT O3; F3 §2 | `src/tlab/engine/reconciler.py`, `src/tlab/engine/runner.py`, `tests/test_reconciler.py` | `claude/kill-switch-etiketi` — runner zinciri | S | ≥2 Aralık | YÇ test_f9: `exit_reason == "kill_switch"` | — |

Runner zinciri sırası: B63 → B1 → B3 → B6 → B7 → B8 → B9 → B10 → B11 → B12 → B13 → B14 → C9b. B0 yanıtı gecikirse B11–B14 öne alınır.

### C — dalda şimdi, birleşme ≥2 Aralık (belge işleri hariç)

| ID | İş | Kaynak | Dosyalar | Dal | Boy | Dondurma | Kabul ölçütü | Bağımlılık |
|---|---|---|---|---|---|---|---|---|
| C0 | Kampanya pin testini tarihsel kayda çevir; yürütme kaydı | F3 §4 adım 0; UF 10 | `tests/test_shadow_job.py` (723–748), `docs/designs/shadow-observation.md` §7 | `claude/kampanya-pin-tarihsel` | S | **toplam doğrulandıktan sonra**; dal şimdi hazırlanır | Desen `tests/test_measurement_freeze.py`: kayıt boşken canlı parmak izi denetimi sürer (dondurma), dolunca atlanır ve kayıt iki yerde sabit; mutasyonla gösterilir | K4 |
| C1 | Dönem özeti şema belgesi (şema 1, veto kategori tablosu) | F3 P4, soru 7, 8 | yeni `docs/designs/journal-summary.md` | `claude/journal-ozet-sema` | S | şimdi (belge) | Alanlar ve türleri; para cinsinden alan yok; ham veto metni çıkmaz; Codex incelemesi | K6 |
| C2 | P2: journal'dan kapalı pozisyon ve R (salt okunur) | F3 P2; BT O3 | yeni `src/tlab/journal/trades.py`, `tests/test_journal_trades.py` | `claude/journal-trades` | S | ≥2 Aralık | Tek bacakta R = `trades.r_multiple`; iki çıkış bacağı tek pozisyon; yaz/kış gün sınırı; stop = giriş R listesine girmez; salt okunur bağlantıda çalışır | K12 |
| C3 | P3: gün-bloğu belirsizlik ölçümü (`evidence.py` değişmez) | F3 P3; BT B6 | yeni `src/tlab/learning/blocks.py`, `tests/test_learning_blocks.py` | `claude/learning-blocks` | S | ≥2 Aralık | Tek işlemli günlerde aralık `bootstrap_mean_ci` ile birebir; gün etkili seride daha geniş; `min_days`/`min_trades` altında aralık yok; `test_evidence_interval.py` değişmeden yeşil | K5 |
| C4 | P4: journal'dan fiyatsız dönem özeti (`build`, `merge`) | F3 P4 | yeni `src/tlab/journal_summary.py`, `tests/test_journal_summary.py` | `claude/journal-summary` | M | ≥2 Aralık | Kanarya fiyat, miktar, özsermaye çıktı baytlarında yok; aynı journal aynı bayt; `merge(günlük)` = `build(dönem)`; var olan dosya ezilmez | C1, C2, C3 |
| C5 | P5: sade kullanıcı raporu | F3 P5; UF 2 | yeni `scripts/journal_report.py`, `tests/test_journal_report.py`; `pyproject.toml` | `claude/journal-report` | S | şimdi (C1 onayından sonra) | Bilinmeyen anahtar ve yanlış tür sabit hata; aralık yoksa sayı basılmaz; yalnız standart kütüphane; fiyat ve hesap değeri yok | C1 |
| C6a | P6a: kat planı (saf) | F3 P6 | yeni `src/tlab/learning/folds.py`, `tests/test_folds.py` | `claude/learning-folds` | S | ≥2 Aralık | Katlar örtüşmez, test eğitimden sonra; az gün hata; deterministik | — |
| C6b | P6b: walk-forward düzeneği (yalnız sentetik veri) | F3 P6, soru 9 | yeni `src/tlab/backtest/walkforward.py`, `tests/test_walkforward.py` | `claude/walkforward` | M | ≥2 Aralık; **gerçek veride koşu ayrı kayıtlı karar** | Test günlerinin barını değiştirmek o katın seçimini değiştirmez; dosya yolu almaz; terfi kararı üretmez; #63 ağacında da yeşil | C2, C3, C6a |
| C7 | P8: paper günü yaşam döngüsü denetimi (journal'dan) | F3 P8 | yeni `src/tlab/journal/lifecycle.py`, `tests/test_journal_lifecycle.py` | `claude/journal-lifecycle` | M | ≥2 Aralık | Temiz gün bulgusuz; her kusur tek tek ekilir ve yalnız kendi kodunu üretir; tanınmayan emir durumu çökmez; bulgu metni sembol ve fiyat taşımaz | — (İtiraz 4) |
| C8 | alpaca-py 0.45 uyumu (haftalık kanarya üç haftadır kırmızı) | UF 16; kanarya log'u (İtiraz 9) | `src/tlab/execution/alpaca_broker.py` (`:73` `daytrade_count`, `:347` `order_type`), `tests/test_alpaca_contract.py`, `tests/alpaca_stub.py` | `claude/alpaca-045-uyum` — **killswitch-fix üstüne** | S | ≥2 Aralık | Ayrı ortamda 0.44.0 ve 0.45.0 ile `test_alpaca_contract.py` ve `test_sdk_probe.py` yeşil (bugün 0.45'te 8 + 4 kırmızı); `filterwarnings` gevşetilmez; sayaç yanıtta yokken davranış açık testle sabit ve ERROR logu | B63; kapı davranışı D11 |
| C9a | SimBroker bacakları Alpaca görünümüyle (yön, kalan miktar, fiyat) listelensin | BT B1; YÇ B7 | `src/tlab/backtest/sim_broker.py`, `tests/test_sim_broker.py`, yeni `tests/test_backtest_concurrency.py` | `claude/sim-bacak-gorunumu` — **killswitch-fix üstüne** (B4'ün ucundan) | S | ≥2 Aralık; **kayıtlı karar K7** | İki sembollü sentetik backtest 2 işlem üretir (önce 1); tek sembollü mevcut testler aynı | B4, K7 |
| C9b | `_pending_risk`: aynı pozisyonun iki çıkış bacağı tek azaltma sayılsın | YÇ B7 | `src/tlab/engine/runner.py`, `tests/test_runner.py` (vetoyu sabitleyen test bilinçli değişir) | `claude/pending-risk-oco` — runner zinciri sonu | S | ≥2 Aralık; **K7** | YÇ test_f3: iki bacak iki sırada da bilinmeyen risk üretmez, maruziyet çift sayılmaz | B14, C9a, K7 |
| C10 | Dolum modeli: giriş barında stop denenir; hedef dokunuşta dolmaz; iki yönlü deterministik dolum tablosu | BT B3, B4, §4 madde 9 | `src/tlab/backtest/sim_broker.py`, `tests/test_sim_broker.py`, `README.md` | `claude/sim-dolum-modeli` — C9a'nın ucundan | M | ≥2 Aralık; **K8** | BT karalama testleri kırmızı→yeşil (giriş barında delinen stop zarar yazar; tam dokunuşta pozisyon açık kalır); "aynı barda hedef yok" testi yeşil | C9a, K8 |
| C11 | Backtest ile canlı aynı `history_days`; mimari eşitlik testi | BT B5 | `src/tlab/backtest/engine.py`, yeni `tests/test_backtest_history.py`, `tests/test_architecture.py` | `claude/backtest-history-days` | S | ≥2 Aralık; **K8** | Tatil ertesi sentetik günde 1 ve 3 günlük pencere aynı kararı verir; varsayılan tek kaynaktan | A5a |
| C12 | Sentetik kotasyon yalnız kapanmış bardan | BT B7 | `src/tlab/data/cached.py`, `tests/test_backtest.py` (`:349` testi doğru değişmeze çevrilir) | `claude/kotasyon-kapali-bar` | S | ≥2 Aralık | Kotasyonun barı karar anında kapanmış; bayt-özdeş baseline raporu testi değişmeden yeşil | — |
| C13 | Backtest gün sınırında ve koşu sonunda mutabakat (son barda dolan çıkış işlem olur) | BT B10 | `src/tlab/backtest/engine.py`, yeni `tests/test_backtest_session_end.py` | `claude/backtest-seans-sonu` | S | ≥2 Aralık; **K8** | BT karalama testi: 1 işlem; journal ile özsermaye tutarlı | C11 (aynı dosya) |
| C14 | `tlab backtest` varsayılanı canlı journal olmasın (kill-switch günü paylaşılmasın) | BT B2 (ilk adım) | `src/tlab/cli.py`, yeni `tests/test_cli_backtest.py` | `claude/backtest-ayri-journal` | S | ≥2 Aralık | Aynı veriyle art arda iki CLI backtest aynı sonucu verir; canlı journal'da `daily_state` satırı oluşmaz | B2 (aynı dosya); kalıcı çözüm D9 |
| C15 | Terfi kapısı: eşik altı ama kanıtlı iyi aday `HOLD`; tek gözlem doğru raporlanır | BT B11, O5 | `src/tlab/learning/promotion.py`, `src/tlab/learning/evidence.py`, `tests/test_learning.py` | `claude/terfi-kapisi-hold` | S | ≥2 Aralık; **K13** | BT karalama testi `HOLD`; `REJECT` yalnız üst uç 0'ın altındayken | K13 |
| C16 | Teklik kapısı süzgeci (olay, dal, depo): gölge işi ve başlatıcı | GÜV Y1 (kalıcı), D1 | `src/tlab/shadow_job.py`, `infra/shadow-starter/worker.js`, `infra/shadow-starter/worker.test.js`, `tests/test_shadow_gate.py`, `tests/test_shadow_collect.py` | `claude/teklik-suzgeci` | M | toplam doğrulandıktan sonra | `pull_request` olaylı işsiz koşu günü yakmaz; yabancı depo ve dal koşusu sayılmaz; artefakt yalnız kendi iş akışı koşularında aranır; başlatıcı yönlendirme izlemez | C0, K14 (İtiraz 5) |
| C17 | Action'ları commit SHA ile sabitle: 10 iş akışı tek PR | GÜV O2 | `.github/workflows/*.yml`, `tests/test_architecture.py` | `claude/action-sha` | S | ≥2 Aralık | Her `uses:` 40 hane ve sürüm yorumu; SHA'lar `docs/designs/workflow-actions.md` ile aynı; tek-sürüm testi SHA'yı sabitler | C0 (İtiraz 1) |
| C18 | Kilitlere hash; secret'lı işlerde `--require-hashes` | GÜV O1 | `requirements.lock`, `requirements-dev.lock`, `Makefile`, 7 iş akışı, `tests/test_architecture.py` | `claude/kilit-hash` | M | ≥2 Aralık | Secret'lı her kurulum `--require-hashes --no-deps`; kilit testleri yeşil; sürümler değişmez | C17 (aynı dosyalar) |
| C19 | Anahtarlar `SecretStr`; `tlab config` maskesi; üst düzey istisna yakalama; `sdk_probe` yorumu | GÜV D6, D7, D10 | `src/tlab/config.py`, `src/tlab/cli.py`, `src/tlab/baseline_diagnostic.py`, `src/tlab/shadow_job.py`, `src/tlab/sdk_probe.py` ve testleri | `claude/secretstr-cikti` | S | ≥2 Aralık | `repr` ve `model_dump` anahtar taşımaz; maske yalnız var/yok ve uzunluk; yakalanmayan istisnada yalnız tip adı basılır | B3, C14 (aynı dosyalar) |

### D — karara bağlı (karar gelmeden kod yok)

| ID | İş | Kaynak | Dosyalar | Boy | Bekleyen |
|---|---|---|---|---|---|
| D1 | P7: paper "günde tek koşu" kapısı; Y1 süzgeci ilk günden içinde | F3 P7; GÜV Y1 | yeni `src/tlab/paper_gate.py`, `tests/test_paper_gate.py` | M | K2, K14 |
| D2 | P9: paper seans işi ve iş akışı (tasarım, iş, iş akışı olarak üçe bölünür) | F3 P9; UF 8; ALP "ilk paper günleri" | `docs/designs/paper-session.md`, `src/tlab/paper_job.py`, `.github/workflows/paper-session.yml`, `tests/test_paper_job.py`, `tests/test_architecture.py` | 3×M | K1–K3; #63, B1–B3, C4, C7, D1 |
| D3 | Paper feed'i: IEX mi SIP mi | F3 soru 1; ALP K7 | — | — | K1 (toplam sonucu) |
| D4 | Alpaca secret'larını `paper` Environment'ına taşı | GÜV Y2 (2. adım) | 7 iş akışı, `tests/test_architecture.py` | M | Sahip Environment'ı kurar (§6 madde 11) |
| D5 | Telefondan acil durdurma | UF 5 | `docs/designs/acil-durdurma.md`; sonra `src/tlab/cli.py` ve yeni iş akışı | M | K16 |
| D6 | Ön kayıt paketi: deney sicili, kanıt bütçesi, canlıya hazırlık listesi | UF 12, 13, 20; BT O1 | `docs/experiments/`, `docs/designs/evidence-budget.md`, `docs/designs/live-readiness.md`, `tests/test_experiment_registry.py` | 3×S | K16; taslaklar "karar bekliyor" notuyla Sprint 2'de yazılabilir |
| D7 | Kanıt arşivi | UF 15 | `docs/records/evidence/`, `tests/test_evidence_archive.py` | S | K17; indirmeyi Codex ya da sahip yapar |
| D8 | Journal kalıcılığı, nabız kaydı, düzgün kapanış, süreç dışı bekçi | UF 7, 14; YÇ B4 | tasarım; yeni göç | M | K16, K18 |
| D9 | `daily_state` anahtarı koşu/mod + gün | BT B2 (kalıcı) | yeni göç, `src/tlab/journal/queries.py`, `src/tlab/journal/writer.py` | M | K18; #63 sonrası |
| D10 | Olumlu nabız kuralı ve oturumdan bağımsız bekçi | UF 3 | kural `docs/ops/`; başlatıcı değişikliği kampanya sonrası | S/M | K16 |
| D11 | PDT kuralı: sayaç yanıtta yokken kapı davranışı | UF 16; kanarya log'u | `src/tlab/risk/gate.py`, `src/tlab/core/types.py`, `tests/test_gate.py` | S | K11; C8 |

## 3. Sprint 1 uygulama planı

Her uygulayıcı soğuk başlar. Ortak kurallar:

- Önce oku: `docs/office/README.md` (değişmez kısıtlar), `AGENTS.md` §1, §4, §4a ve bu dosyadaki kendi satırı.
- Kendi dalı, kendi çalışma kopyası. Commit, push ve GitHub yazımı Yönetim'indir. Ağ, broker ve iş akışı yok; `.env` okunmaz.
- Her teslimde: (1) hedefli test çıktısı; (2) tam `make check` sayıları: toplanan, geçen, atlanan, kırmızı ve süre (taban main:
  1534 = 1528 + 6); (3) `ruff` ve `mypy` temiz; (4) mutasyon ya da önce kırmızı/sonra yeşil kanıtı; (5) "doğrulanmadı" listesi.
- Turlar uygulama sırasıdır. Dokuz işin dosya kümeleri birbirinden ayrıktır; Codex ONAY'ı gecikse de sonraki tur başlar.

**Tur 1 — A1 ∥ A3**
- **A1.** Oku: TK §2, §3, §7; `wt-a5` diff'i (`a5-proposed.diff`). Kanıt: tam süit süresi önce ve sonra; sunucu kullanan 15 dosya
  yeşil (582 test); toplanan test sayısı ve atlanan 6 testin adları aynı; `SDK_RETRY_SLEEPS` iddiası; fixture kaldırılınca sonuç aynı, süre geri gelir.
- **A3.** Oku: F3 P1; `docs/designs/unattended-paper.md:23-36`; `scripts/shadow_report.py` (`validate`, `render`);
  `tests/test_shadow_report.py:26` deseni. Kanıt: yeni testler; eşik mutasyonu (15 → 14) kırmızı; bayraksız çıktının bayt karşılaştırması; `python3 -I` ile koşu.

**Tur 2 — B0 ∥ B63** (ikisi de Codex'e gidecek paketi tamamlar)
- **B0.** Oku: ALP raporunun tamamı; YÇ B2, B3, B6, B11, B13, B14 ve "stop bacağını listede görmeye dayanan yerler" tablosu;
  R63 B5, O1, O2, R1, R2; `wt-r63` içinde `docs/designs/unattended-paper.md` §4 ve `src/tlab/engine/runner.py`. Kanıt: §4 T1'in
  her sorusuna gerekçeli yanıt; her iddia rapor kimliğine ya da dosya:satıra bağlı; "ikincil kaynak" işaretleri korunur; ÖN RAPOR taslağı ekte.
- **B63.** Oku: R63 "Yeniden inceleme — f654f0d"; `wt-r63` içinde `tests/test_entry_cancel_race.py:1352-1372`,
  `src/tlab/journal/writer.py:219`. Kanıt: `mark_order_closed`'u boşaltan mutasyon kırmızı; yarış dosyası tam yeşil (bugün 159);
  tam `make check`'te tek kırmızı kampanya pin testi; davranış diff'i yok.

**Tur 3 — A2 ∥ A6a**
- **A2.** Oku: TK §6.1, §5; `tests/test_runner.py` (`FakeBroker`, `build_runner`, `:592`); `src/tlab/engine/runner.py:583-615`.
  Kanıt: mutasyon diff'i ve kırmızı çıktı; aynı dosya `wt-r63` ağacında yeşil; diff yalnız yeni test dosyası.
- **A6a.** Oku: UF fikir 9, 10, 15; F3 §4; `docs/designs/shadow-observation.md:606-616`; bu dosyanın §2 bağımlılık sütunu ve §5.
  Kanıt: plandaki her adım bir iş kimliğine bağlı; her tarih kaynak satırıyla; tam `make check` (anahtar tarayıcı yeni dosyaları da tarar).

**Tur 4 — A5a ∥ A4**
- **A5a.** Oku: GÜV O3, D3, D4; TK §6.7; `tests/test_architecture.py:286-360, 440-456, 981-1000, 1080-1095`;
  `.pre-commit-config.yaml`. Kanıt: ekilen dört ihlal için dört kırmızı çıktı; ağaçtaki mevcut test sahteleri yeni desenlere
  takılmıyor ya da istisnası gerekçeli; tam `make check`.
- **A4.** Oku: UF fikir 1 ve "ilk 5" madde 1; bu dosyanın §5 ve §6; A6a takvimi. Kanıt: sayfada fiyat, hesap değeri ve koşu
  kimliği araması boş; her "Sizden beklenen" satırı §5 ya da §6 maddesine bağlı.

**Tur 5 — C0**
- **C0.** Oku: F3 §4 adım 0; `tests/test_shadow_job.py:700-748`; `tests/test_measurement_freeze.py:60-170`;
  `docs/designs/shadow-observation.md` §7. Kanıt: kayıt boşken parmak izi kapsamındaki bir dosyaya geçici dokunuş testi
  kırmızıya çevirir (geri alınır); kayıt doluyken atlanır ve kayıt testi yeşil. Dal birleşmez; toplam doğrulanınca koşu kimliği doldurulur.

Sprint 2 adayları, sırayla: B1 → B3; C8; B2; A7, A8; A5b; C1 → C2 ∥ C3; A6b.

## 4. Tasarım gerektirenler

**T1 — Koruma denetimi v2 (B0 → B4–B10).** Codex yanıtından önce bu işlerde kod yok. B1, B2, B3 ve C8 bu tasarımı beklemez.
1. Okuma yolu: pozisyon başına iç içe ebeveyn okuması mı, tur başına tek `status=all` + `nested` listesi mi? İstek bütçesi
   (ALP soru 7) ve `limit`'in bacakları sayıp saymadığı (ALP gözlem 10).
2. Koruma kanıtının tanımı: ebeveyn `filled`, stop bacağı `new`/`partially_filled`, miktar ≥ pozisyon. `held` stop, kardeş
   hedef `new` iken koruma sayılır mı (ALP K1 b, c; ikincil kaynak)?
3. Aşamalama: hangi durum hemen uygulanır ("hiç çıkış bacağı yok"), hangisi ilk paper gözlemine kadar yalnız loglanır (`held`)?
4. `_pending_risk`: bacaklar görünür olunca bugünkü kural bütün girişleri veto eder (YÇ B7). Koruma okuması ayrı yoldan mı, C9b önce mi?
5. Kısmi dolum: kalan kaç tur sonra iptal edilir; iptal bacakları da düşürür (ALP soru 3) — sembol kapatılır mı, bağımsız çıkış
   çifti mi (K10)? `filled_at` boşsa mutabakat (YÇ B13).
6. Gece taşınan pozisyon: seans başında emirsiz pozisyon kapatılır mı, gün durur mu; borsa kapalıyken yalnız not mu (YÇ B3)?
7. `_flatten_all`: engel kümesi iç içe okumadan; 207 gövdesi; 403 `held_for_orders`; iptal kesinleşmezse kaç tur (YÇ B14, ALP K3)?
8. #63 sınırları: deneme sınırı `cancel_requested` satırının yaşından mı (göçsüz), kalıcı sayaçtan mı (K18)? Kalıcı okunamayan
   giriş hangi kanıtla kapatılır (R63 R2, O2)? Sahipsiz çıkış (R63 B5).
9. Tur başında hesap ya da pozisyon okunamazsa zaman bazlı kapanış denenir mi (R63 (c))? R63 O1 bedeli kabul mü?
10. Sahte brokerlar (`SimBroker`, `ShadowBroker`, test `FakeBroker`) yeni okuma yolunu nasıl taşır; short yön testleri (YÇ §4).

**T2 — Dönem özeti şeması (C1 → C4, C5):** veto kategori tablosu; pozisyon başına R ve sembol herkese açık mı (K6); `merge` kuralı; şema sürümü.
**T3 — `daily_state` anahtarı (D9):** backtest, gölge ve canlı durdurma kayıtlarının ayrımı; göç numarası rezervasyonu (AGENTS §4).
**T4 — PDT sayacı (C8 → D11):** alanın yokluğu nasıl ayırt edilir; kapı yoklukta ne yapar (K11); gerçek yanıtı kim doğrular (ofise broker çağrısı yasak).
**T5 — Teklik süzgeci (C16, D1):** tek ortak süzgeç; paper kapısı API kodunu kopyalar mı (F3 soru 6).
**T6 — Paper seans işi ve acil durdurma (D2, D5):** K1–K3 ve K16'dan sonra; ALP "ilk paper günlerinde gözlenecekler" (10 madde) kabul listesine girer.

## 5. Karar gerektirenler

| No | Karar | Kim | Önerilen varsayılan | Bekleyen iş |
|---|---|---|---|---|
| K1 | Paper feed'i IEX mi SIP mi (F3 soru 1) | Sahip, toplamdan sonra | Üç ölçü de GEÇTİ ise IEX; değilse paper yok, yeni kampanya | D2, D3 |
| K2 | Paper nerede koşar: Actions (A) mı sunucu (D) mi (F3 soru 2) | Sahip + Codex | A'nın daraltılmış biçimi | D1, D2 |
| K3 | Erken kapanışın ifadesi ve ilk beş seansta "tek sembol, en küçük miktar" (F3 soru 3, 4) | Codex + sahip | Ayrı kayıtlı karar; risk sınırı değişikliği sayılır | D2 |
| K4 | Toplam tıklamasının tarihi (UF §5.2) | Sahip | 2 Aralık'tan sonra, en geç 24 Aralık (1 Ocak'ta ilk gün kaydı silinir) | C0 ve bütün `src/` birleşmeleri |
| K5 | `min_days` tabanı ve birincil hüküm (F3 soru 5) | Codex | `min_days=20`, `min_trades=100`; birincil gün-bloğu; gerçek veri görülmeden sabitlenir | C3 |
| K6 | Pozisyon başına R ve sembol herkese açık özete girer mi (F3 soru 7) | Sahip + Codex | Evet; R orandır, fiyat değildir | C1, C4 |
| K7 | Eşzamanlı pozisyon: backtest bugün fiilen tek pozisyon ölçüyor (YÇ B7, BT B1) | Codex + sahip | Kod dalda düzeltilir; 2026-10-13 ölçümüne "etkilenmiş olabilir, doğrulanmadı" notu düşülür; yeni ölçüm yalnız yeni veri kümesi kararıyla | C9a, C9b |
| K8 | Dolum modeli ve pencere değişiklikleri (BT B3, B4, B5, B9, B10) | Codex | Temkinli yöndeki B3 ve B4 kabul; görülmüş dönem yeniden ölçülmez; B9 için alan "yalnız kapı vetosu" diye etiketlenir | C10, C11, C13 |
| K9 | `held` stop koruma sayılır mı (ALP K1) | Codex + sahip | Hayır; ilk gözlenen stop tetiklenmesine kadar yalnız log | B6, B7 |
| K10 | Kısmi dolumda kalan pozisyon: kapat mı, bağımsız çıkış çifti mi (ALP K2) | Codex | Yalnız o sembolü kapat; v2'de yeni emir türü yok | B8 |
| K11 | PDT sayacı yanıtta yoksa kapı ne yapar (UF 16) | Codex + sahip | Kural açık ve özsermaye eşiğin altındayken sayaç okunamıyorsa veto; önce gerçek yanıt doğrulanır | D11 |
| K12 | R paydası gerçekleşen girişten mi, planlanandan mı (BT O2) | Codex | Şimdilik değişmez; paper dolum dağılımı görülünce yeniden | C2 |
| K13 | Terfi kapısı: `REJECT` eşiği ve tekrarlı bakış (BT B11, O1, O5) | Codex | `REJECT` yalnız üst uç 0'ın altındayken; bakış takvimi önceden sabit | C15 |
| K14 | Teklik süzgeci gölge işine de girsin mi (GÜV Y1) | Codex + sahip | Yalnız yeni kampanya kararı varsa; paper kapısı her durumda süzgeçle doğar | C16, D1 |
| K15 | Geçmiş sürümlere ve kampanya commit'ine etiket (UF §5.10) | Sahip; eşleme Codex | Evet; önce tablo, etiketi Yönetim basar | A6b |
| K16 | Acil durdurma, alarm kanalı, journal'ın yeri, kanıt bütçesi, canlı eşikleri (UF §5.3–5.7) | Sahip | Taslak belgeler "karar bekliyor" notuyla hazırlanır; varsayılan dayatılmaz | D5, D6, D8, D10 |
| K17 | Herkese açık artefaktlardaki türetilmiş sağlayıcı verisi; kanıt dosyalarının depoya konması (GÜV D11, UF §5.9) | Sahip | Bilerek onay; kampanya bitene kadar saklama süresine dokunulmaz | D7 |
| K18 | Göç numarası rezervasyonu (AGENTS §4) | Codex ile | B10 için önce göçsüz çözüm; D9 için rezervasyon | B10, D8, D9 |

## 6. Sahip ayarları

Bunları yalnız depo sahibi yapabilir; bizim iş listemize girmez. En acil olan en üstte.

1. **Bugün: yabancıların PR ve yorum açmasını geçici kapatın.** Settings → Moderation → Interaction limits → "Limit to repository
   collaborators". Neden: 30 Kasım ve 1 Aralık gözlem günlerinde bir yabancının açacağı tek PR o günün kaydını boşa çıkarabilir;
   iki kayıp gün kampanyayı düşürür. Toplam doğrulanana kadar açık kalsın; süre sorulursa en uzun seçeneği seçin.
2. **Bugün: dışarıdan gelen PR'lar onayınız olmadan iş çalıştırmasın.** Settings → Actions → General → "Fork pull request
   workflows" → "Require approval for all external contributors".
3. **30 Kasım ve 1 Aralık, Türkiye saatiyle 15:50'den önce bir bakış.** Actions sayfasında "Shadow observation" altında bizim
   zamanlanmış koşumuz dışında bir koşu görürseniz silin ya da bize yazın.
4. **Bu hafta: `main` dalını kilitleyin.** Settings → Rules → Rulesets → `main` için yeni kural: "Require a pull request" açık,
   "Require status checks" altında `quality`, "Block force pushes" ve "Restrict deletions" açık, istisna listesi boş.
   Dikkat: "Require approvals" ve "Code Owners review" **kapalı** kalsın; iki ajan aynı hesapla yazdığı için açılırsa hiçbir PR birleşemez.
5. **Bu hafta: gizli anahtar taramasını açın.** Settings → Code security → Secret scanning, Push protection, Dependabot alerts,
   Private vulnerability reporting.
6. Settings → Actions → General: "Workflow permissions" salt okuma; "Allow GitHub Actions to create and approve pull requests"
   kapalı; yalnız GitHub'ın kendi action'larına izin.
7. Yazma yetkisi olanları gözden geçirin: Collaborators, kurulu GitHub App'ler, Deploy keys, Webhooks. Ajan anahtarlarında
   "Administration" ve "Secrets" izni olmasın.
8. GitHub, Alpaca ve Cloudflare hesaplarında iki adımlı doğrulama; kullanılmayan erişim anahtarlarını silin.
9. Depo gizliyken oluşan eski Actions kayıtları artık herkese açık. Gereksizleri silin; `shadow-day` adlı dosyalara **dokunmayın**
   (kampanya kanıtı). #17'deki yorumlarda yapıştırılmış anahtar ya da hesap değeri var mı, bir göz atın.
10. Takvime yazın: toplam tıklaması 2–24 Aralık arası; 20 Ocak 2027'de başlatıcı anahtarı bitiyor.
11. 2 Aralık'tan sonra: `paper` adlı bir Environment kurun (yalnız `main`, onaylayan siz). Kampanya bitince Alpaca paper
    anahtarını yenileyin; başlatıcı kullanılmayacaksa anahtarını iptal edin. Gerçek para anahtarı bu yapılmadan GitHub'a girmesin.
12. Bir kez bakın: Insights → Dependency graph kilit dosyalarını görüyor mu; anahtar taraması açıldıktan sonra geçmiş için uyarı çıktı mı.

## 7. Kapsam dışı bırakılanlar

- **TK Ö4, Ö5, Ö6** (fixture paylaşımı, `pytest-xdist`, tmpfs): A1 sonrası yeniden ölçülmeden açılmaz; Ö5 dondurulmuş kilidi yeniden üretir.
- **TK: CI'ı işlere bölmek, `COVERAGE_CORE=sysmon`:** rapor denedi, önermiyor.
- **TK §6.8** (dolambaçlı iddia): kozmetik; B5 aynı dosyaya dokunurken düzeltilir.
- **BT B8** (komisyon istatistiklere girmiyor): varsayılan 0 bps'te etkisiz; komisyonlu ölçüm kararı gelirse açılır.
- **BT B9** (`spread_bps` dolumu etkilemiyor): K8 kararından önce kod yok.
- **BT O1** (tekrarlı bakış): OLASI; gerçek kapıyla doğrulanmadı ve bugün aday yok. Bakış sayısı D6 deney siciline girer.
- **BT O2** (R paydası): K12; simülasyonda oluşmuyor.
- **BT O4** (karar gecikmesi modeli): ölçecek veri yok; yalnız README notu (A5b).
- **F3'ün bilerek paketlemedikleri** (aday shadow modu, karşı-olgusal sonuç, `params_versions`, MAE/MFE): aday ve örneklem yok.
- **F3 soru 8** (veto metninin kalıcı biçimi): göç ve `core/types.py` ister; şimdilik okuma anında kategori (C4).
- **ALP K7** (karar IEX, dolum NBBO): hata değil; K1'e girdi.
- **ALP "ilk paper günlerinde gözlenecekler":** emir gerektirir; D2 tasarımına girdi.
- **YÇ B4'ün süreç dışı bekçisi, UF 7, UF 14:** göç ve sahip kararı ister (D8).
- **GÜV D8** (Docker hijyeni): Docker yolu bugün kullanılmıyor; K2'ye bağlı.
- **GÜV D2, D9, D11 ve tam geçmiş taraması:** sahip işi (§6) ya da karar (K17).
- **`worker.js` değişiklikleri** (GÜV D1, Y1'in başlatıcı kısmı): kampanya bitene kadar dokunulmaz (İtiraz 8); C16'da.
- **UF 17** (çoklu strateji arayüzü): erken soyutlama; Faz 3 sonrası.
- **UF 18'in AGENTS.md'yi bölme kısmı:** ortak sözleşme, Codex'le ayrı konu; yalnız bayat satırlar A5b'de.
- **UF 1'in "Sahip panosu" başlığı ve etiketi, PR şablonu satırları:** GitHub yazımı Yönetim'in; `.github/` çift göz ister.
- **UF 6'nın hatalı davranışı yeşil sabitleyen tatbikatları:** İtiraz 10; yalnız A2, A7, A8 şimdi.

## 8. İtirazlar

1. **A5'teki "gölge dışı iş akışlarında SHA sabitleme şimdi" yapılmamalı.** `tests/test_architecture.py:1659` on iş akışının hepsinde
   tek sürüm dizgesi ister; ikisi dondurulmuş. Yarım sabitleme testi bir hafta için iki biçimli yapar. Bu hafta secret'la gerçekten
   koşan tek iş akışı dondurulmuş olan; kazanç yok. GÜV O2 de "2 Aralık sonrası" diyor. → C17, tek PR.
2. **A4'ün günlük özet aracı Sprint 1'e girmedi.** Girdisi `shadow-day.json`; yalnız iki planlı gün kaldı ve Claude oturumu
   artefakt indiremiyor (UF §3.3 notu). Kalıcı karşılığı journal raporu (C5). → Sprint 1'de yalnız pano (A4); A4b, C5 ile birleşsin.
3. **"Koruma v2 tek akış, paper'dan önce bitmiş" hedefi olduğu gibi tutmaz.** ALP'ye göre tam dolumdan sonra stop `held` kalır
   (ikincil kaynak) ve `PROTECTIVE_STATUSES` `held`i saymaz (#63 ağacında `runner.py:88`). Her tur denetimi bu haliyle uygulanırsa tam dolan
   her pozisyonu kapatır; `held` kanıtsız kabul edilirse sahte güvence verir. Doğrulama emir ister. → İki aşama: oku ve logla +
   "hiç bacak yok" durumunu uygula (paper'dan önce); `held` kuralı ilk paper gözleminden sonra kayıtlı kararla (K9).
4. **P7–P9'un hepsi D değil.** F3'e göre P8 karardan bağımsız, yalnız journal okur → C7. P7 yalnız ortam kararı (K2) yüzünden D'de; P9 D'de.
5. **Y1'in kalıcı düzeltmesi bu kampanyayı korumaz.** Parmak izini değiştirdiği için toplamdan önce birleşemez (F3 §4 adım 0);
   toplamdan sonra kampanya bitmiştir. Bugünkü koruma yalnız sahip ayarıdır (§6 madde 1–3). Kalıcı değer paper kapısında: süzgeç
   D1'in kabul ölçütüne yazıldı; C16 yalnız yeni kampanya kararıyla (K14).
6. **GÜV Y2 ile AGENTS §4a çelişiyor.** GÜV ruleset'e "Code Owners incelemesi" öneriyor; AGENTS §4a ve UF 11'e göre zorunlu onay
   açılırsa paylaşılan kimlik yüzünden hiçbir PR birleşemez. → §6 madde 4 onaysız yazıldı.
7. **GÜV D5'in 15 dakikalık sınırı bugünkü CI'ı keser.** UF 19: CI `Testler` adımı 18 dk; TK: yerelde 22 dk. → A5c, A1'den sonra ölçümle.
8. **GÜV "`worker.js` dondurulmuş değil" derken UF "kampanya sürerken başlatıcıya dokunma" diyor.** Depodaki kod değişirse
   "dağıtılan kod = depo" denetimi (GÜV §4) anlamını yitirir. → Şimdi yalnız test dosyası (A9).
9. **Kanarya şimdi düzelmez.** Kontrol edildi (23 Kasım log'u): alpaca-py 0.45.0 ile 12 test kırmızı (`test_alpaca_contract.py` 8,
   `test_sdk_probe.py` 4). Sebep iki eski alan okuması: `TradeAccount.daytrade_count` (`alpaca_broker.py:73`) ve `Order.order_type`
   (`:347`). Uyarı `sdk_compat.py:25` çağrısına atfedildiği için `ignore::DeprecationWarning:alpaca.*` süzgecine girmiyor ve
   `filterwarnings = error` onu hataya çeviriyor. Düzeltme `src/tlab/execution/alpaca_broker.py`'da: dondurulmuş ve #63'ün
   dokunduğu dosya → C8, ≥2 Aralık; 30 Kasım kanaryası da kırmızı olacak. `pyproject.toml`'a süzgeç eklemek önerilmez: sayaç
   yanıtta yoksa PDT kuralının sessizce 0 okuduğunu gizler (UF 16; gerçek yanıt doğrulanmadı) → K11, D11.
10. **UF 6 hatalı davranışı yeşil testle sabitlemeyi öneriyor.** Düzeltilmemiş hatayı kanıtlayan test kırmızıdır ve tek başına
    birleşemez; hatayı "beklenen" diye yazan test de yanlış güven verir. → Şimdi yalnız doğru ama sınanmamış davranışlar (A2, A7,
    A8); hata testleri düzeltmesiyle gider (B1–B3).
11. **BT B6 ile F3 P3 çelişiyor.** BT `evidence.py`'ı değiştirmeyi öneriyor; F3'e göre ölçüm kuralı kayıtlı (`AGENTS.md:1381`) ve
    dosya değişmemeli. → C3 yeni modül; `min_days` orada.
12. **"Kalan küçük yürütme bulguları ayrı" yönü tek dosyaya çarpıyor.** B11–B14 de `runner.py`'dadır; Koruma v2 ile paralel
    yürüyemez. Zincir 12 iş ve her biri Codex'in SHA'ya bağlı onayını ister. → Sıra önem derecesine göre; #63 ONAY'ı gecikirse bütün B bekler.
