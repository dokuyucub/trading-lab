# S1 — Onay Kurulu: A1 test süiti hızlandırma, `3bf552f`

Tarih: 2026-11-25. Dal `claude/test-hizlandirma`, tek commit `3bf552f`, taban `main` @ `d77b381`. Yöntem: yalnız okuma ve çevrimdışı
hedefli test (`wt-s1-a1`); commit, push, GitHub yazımı, iş akışı, broker çağrısı yok. Her sayı kendi koşumdur ya da adı verilen logdan okundu.

## Karar

**ONAY, notlarla.** Zorunlu değişiklik yok; N1–N6 PR açıklamasına taşınmalı. Karar `3bf552f` içindir; ofis onayı Codex'in SHA'ya
bağlı `## ONAY` kaydının ve güncel head'deki yeşil `quality`'nin yerine geçmez.

## Kontrol listesi

| # | Madde | Sonuç | Kanıt |
|---|---|---|---|
| 1 | Kapsam planla aynı | GEÇTİ (N2) | `git diff --name-only d77b381 3bf552f`: 7 dosya, hepsi `tests/`; +50/−5. Silinen 5 satırın hepsi `serve_forever` iş parçacığı satırı. Eklenenlerde `skip`, `xfail`, `noqa`, `type: ignore` yok. Altı dosyalık kısım TK'nın `a5-proposed.diff`'iyle satır satır aynı. |
| 2 | Değişmez kısıtlar | GEÇTİ | `src/tlab/**`, `config/`, `requirements.lock`, iş akışları değişmedi. Parmak izi (`src/tlab/shadow_job.py:150-170`) paket `.py`, `config/*.yaml` ve üç kök dosyayı kapsar; `tests/` dışındadır. Pin testi (`tests/test_shadow_job.py:733`) üç koşuda yeşil. Diff'te gizli bilgi, fiyat, hesap değeri yok. |
| 3 | `ruff`, `mypy`, testler, tam `make check` | GEÇTİ (N1) | `3bf552f`: `ruff check` temiz, `ruff format --check` 144 dosya, `mypy` 116 dosyada hata yok. Tam süit yalnız altı dosyalık ağaçta: 1528 geçti, 6 atlandı, 676,50 sn, kapsam %90,65. `3bf552f`'de koştuğum: sunucu kullanan 15 dosya (582 test) + `test_architecture` 114 + `test_paper_probe_startup` 1, hepsi yeşil. |
| 4 | Yeni davranış testle sabit, kırmızı koşu var | GEÇTİ (N3) | Kırmızı/yeşil yeniden üretildi; üç mutant denendi (aşağıda). |
| 5 | Hata Avı bulguları | GEÇTİ (kayıt) | A1 için Hata Avı raporu ve açık bulgu yok. Düşmanca okumayı bu inceleme yaptı: (a)–(d). |
| 6 | Doğrulanamayanlar yazılı | GEÇTİ | Son bölüm. |

## Test gücü: değişiklik eskiden yakalanan bir hatayı gizleyebilir mi?

- **(a) Duvar saatine dayanan test yok.** `tests/` altında `import time`, `monotonic`, `perf_counter`, `time.time` hiç geçmiyor; "son süre"
  testleri (`test_shadow_job.py:293-380`) `SimClock` ve `Sleeper(clock)` ile sanal saatte. 429 testleri istek sayar; sahte sunucunun hata kuralı
  sayaçladır (`fail(times=...)`), süreyle değil. İki logdaki modül bazlı kapsam tablosu (34 satır, eksik satırlarıyla) birebir aynı.
- **(b) Fixture'ın erişimi.** Kurulu SDK alpaca-py 0.44.0 (iki kilitle aynı). `alpaca/common/rest.py` `time` adını yalnız satır 3'te (`import time`)
  ve 133'te (`time.sleep(self._retry_wait)`) kullanıyor; pakette `time` içe aktaran başka modül yok, diğerleri `rest`'ten yalnız `RESTClient` ve
  `HTTPResult` alıyor. Yama modül niteliğinedir, `time` modülüne değil: `tlab.engine.runner.time` ve `tlab.shadow_job.time` etkilenmez. SDK
  değişirse hata gürültülüdür: ad kalkarsa `setattr` düşer, uyku taşınırsa `== [3]` kırmızı olur. **Alt süreç:** beş dosya alt süreç başlatıyor;
  sunucuya giden üç duman dosyası 500 (`test_baseline_diagnostic_smoke.py:211`), 403 (`test_feed_comparison_smoke.py:142`) ve bozuk özet
  kullanıyor. 429/504 yok: yeniden deneme yolu alt süreçte koşmuyor. İleride eklenirse gerçek 3 sn uyur; yavaş olur, yanlış olmaz.
- **(c) Üretim kodunun kendi beklemeleri dokunulmadı.** `engine/runner.py:178` (`run_forever`; bugün de testsiz, TK §6.4), `shadow_job.py:674, 728`
  (enjekte `sleep`; testler `Sleeper` ile gözlüyor), `sdk_compat.py:181-182` (`_retry`; `test_sdk_probe.py:356` sabitliyor). `src` diff'i boş.
- **(d) Kararsızlık riski düşük.** `poll_interval=0.01` meşgul döngü değil, 10 ms zaman aşımlı `select`. `shutdown()` döngünün çıkışını olayla
  bekler, sıra aralıktan bağımsızdır. Beş sunucu da `("127.0.0.1", 0)` ile geçici port alıyor. `TCP_NODELAY` yalnız HTTP/1.1 işleyicisinde;
  yalnız parça zamanlaması değişir, istemci `Content-Length` kadar okur.

## Kanıt doğrulaması

- **Loglar:** `makecheck-a1.log` "1528 passed, 6 skipped in 676.50s", %90,65; `a5-cov.log` "… in 1338.96s". `47a2a7d` → `d77b381` farkı yalnız `docs/`.
- **Toplama ve atlananlar:** `--collect-only` iki ağaçta 1534 test, kimlik listeleri `diff` ile aynı. Atlanan altı test iki ağaçta da
  `tests/test_measurement_freeze.py:188, 197, 208, 215, 225, 233`, aynı gerekçeyle.
- **Kırmızı/yeşil:** `test_sdk_probe.py` olduğu gibi 31 geçti, 1,01 sn. `monkeypatch` satırı kapatılınca `assert [] == [3]`: 1 kırmızı,
  30 geçti, 19,08 sn ("fixture kaldırılınca sonuç aynı, süre geri gelir" kanıtı da budur).
- **Kararsızlık (`3bf552f`):** `test_shadow_job`, `test_shadow_collect`, `test_shadow_gate`, `test_sdk_probe` üç ardışık koşu, her biri
  **349 geçti, 0 kırmızı**, 89 / 88 / 89 sn. Kalan 11 sunucu dosyası + `test_architecture` + `test_paper_probe_startup` bir kez: 348 geçti, 51,32 sn.

## Mutantlar (`tests/conftest.py`; her biri `git checkout --` ile geri alındı, çalışma kopyası temiz)

| Mutant | Sonuç |
|---|---|
| M1: uyku yutulur ama kaydedilmez (`sleep=lambda _s: None`) | **Yakalandı:** `assert [] == [3]`, 1 kırmızı |
| M2: kaydedilir ama gerçekten de uyur | **Sağ kaldı:** 31 geçti, 19,05 sn; hiçbir test yavaşlamayı fark etmiyor (N3) |
| M3: liste testler arasında sıfırlanmaz | **Yakalandı:** `assert [3, 3, 3, 3, 3, 3] == [3]`, 1 kırmızı |

## Tek iddiadan sonra tam süitin yeniden koşulmaması, commit mesajı

- **Kabul edilebilir: evet.** Fark tek dosyada bir içe aktarma ve bir `assert`; o dosya burada dört kez yeşil, üç kez bilinçli kırmızı koşuldu,
  başka test dosyası onu içe aktarmıyor. Birleştirme zaten güncel head'de yeşil `quality` ister (`AGENTS.md` §4a). Emsal: #63 (`8fd2234`).
- **Commit mesajı doğru.** Conventional Commits (`test:`), gövde nedeni anlatıyor, tek iş. "~40 ms" ölçümde 45 ms/istek; "yarısı"
  1338,96 → 676,50 sn (−%49,5) ile uyumlu (N4). "Test silinmedi, atlanmadı, iddia değişmedi" ve "yalnız `tests/`" doğrulandı.

## Notlar (PR açıklamasına)

- **N1.** Tam süit sayıları altı dosyalık ağaca aittir; `3bf552f` için tam koşu PR'daki `quality`'dir. CI süresi yazılsın (A5c bunu bekliyor).
- **N2.** Backlog satırı altı dosya sayıyor; yedinci dosya (`tests/test_sdk_probe.py`, +4) aynı satırın kabul ölçütünden geliyor.
- **N3.** İddia uykunun *istendiğini* sabitliyor, *sanallaştırıldığını* değil (M2). Doğruluk riski yok, belirti yalnız süre olur; engel değil.
- **N4.** Önce/sonra süreleri farklı yük altında ölçüldü (TK §1, §7); "yaklaşık yarı" diye sunulmalı.
- **N5.** Ortak dosyalar "Diğer geliştiricinin bilmesi gerekenler"e yazılsın: `tests/conftest.py` (süreç içi bütün testlere `autouse`
  fixture; alt süreçleri kapsamaz) ve `tests/alpaca_stub.py` (#63 de dokunuyor; `3bf552f` ile `8fd2234` deneme birleştirmesi çakışmasız).
- **N6.** Fixture SDK'nın iç yapısına (`alpaca.common.rest.time`) bağlı; SDK yükseltmesinde gürültülü biçimde kırılır, sessizce değil.

## Doğrulanmadı

- `3bf552f` üzerinde tam süit ve kapsam; CI `quality` süresi.
- `makecheck-a1.log` SHA damgası taşımıyor. Dolaylı tutarlılık: `a1.patch` (15:05) commit'in altı dosyalık kısmıyla aynı; log 15:17'de bitmiş.
- Kararsızlık yalnız bu makinede (4 çekirdek) ardışık üç koşuyla sınandı; CI runner'ı, paralel koşu ve rastgele sıra denenmedi.
