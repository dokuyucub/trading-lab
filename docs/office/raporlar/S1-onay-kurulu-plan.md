# S1 — Onay Kurulu: Sprint 1 iş listesi ve uygulama planı

Tarih: 2026-11-25 · İncelenen: `docs/office/backlog.md` (63 iş, Sprint 1, §4–§8) · Girdi: sekiz `S1-*.md` raporu.
Kod salt okundu: `main` 47a2a7d (`wt-main`), PR #63 dalı 8fd2234 (`wt-fix`; B63 burada tamamlanmış). Test koşulmadı.

## Karar: RET (dar kapsamlı; yalnız plan metni düzeltilir)

Planın gövdesi sağlam: dondurma, izlenebilirlik ve dosya ayrıklığı doğrulandı. RET'in iki sebebi var. (1) §6 "Sahip ayarları"
teknik olmayan sahibe kampanya kanıtını geri dönüşsüz silebilecek ve kalan iki gözlem gününü düşürebilecek adımlar söylüyor;
liste bugün sahibe gidecek ve A4 panosuna taşınacak. (2) Ölçüm semantiğini değiştiren iki iş (B12, B14) kayıtlı karara bağlı
değil; D2'nin ön koşulları eksik. Z1–Z8 işlenince yeniden inceleme yalnız bu maddelere bakar. A1, A3, A2, A6a, B0 ve C0
satırlarına itiraz yok; düzeltilmiş planda değişmeden başlarlar (A3'ün son günü 1 Aralık).

## Ölçütler

**1. Dondurma güvenliği — GEÇTİ.**
- Parmak izi (`src/tlab/shadow_job.py:132-170`): paketin bütün `.py` dosyaları, `config/*.yaml`, `requirements.lock`, iki gölge
  iş akışı; pin `tests/test_shadow_job.py:723-748`. `scripts/`, `tests/`, `docs/`, `infra/`, `pyproject.toml`, `ci.yml` dışarıda.
- "Şimdi" işaretli 17 işin (A1–A10, A4b, A5a–c, A6a–b, B0, C1, C5) dosya listeleri okundu: dondurulmuş kümeden dosya yok,
  `make lock` isteyen yok. A5c yalnız `ci.yml` ve `artifact-roundtrip.yml`; A9 yalnız `worker.test.js`; gölge iş akışları
  `scripts/` çağırmıyor (A3). A1 ile #63'ün `tests/alpaca_stub.py` satırları ayrık (#63: 261, 388; A1: 25, 329, 433).
- main CI'ı kırmızıya çeviren iş yok: A2'nin sabitlediği sıra bugün doğru (`runner.py:608` kayıt, `:611` gönderim); A5a'nın
  "CI'da atlama yerine hata" kuralı `git diff HEAD` ve `git ls-files` kullanır (`test_architecture.py:286-295, 448-452`), sığ
  checkout'ta çalışır; ağaçta `.yaml` iş akışı, secret'lı işte `cache` ve `ghp_`/`github_pat_` dizgesi yok. C0 dalda kalıyor.

**2. Kısıt güvenliği — KALDI (kısmi).**
- Emir, broker çağrısı, veri indirme, holdout, terfi, iş akışı tetikleme, `research/` ve Faz 4 isteyen iş yok (D7 indirmesi
  Codex'e ya da sahibe bırakılmış). C0 kapı gevşetmesi değil: kayıtlı emsal `tests/test_measurement_freeze.py:129-139`.
- **Eksik:** backtest aynı `SessionRunner`'ı kullanır (`backtest/engine.py:201`) ve çıkış sebebini rapora sayar
  (`backtest/metrics.py:138-141`). B12 (mutabakat penceresi; kaynağı BT B10) backtest'in işlem sayısını, B14 (`kill_switch`
  etiketi) çıkış kırılımını değiştirir. İkisi de "kayıtlı karar" işareti taşımıyor; Özet 6'daki altı işlik liste eksik.

**3. İzlenebilirlik — GEÇTİ.**
- 22 iş örneklendi: Sprint 1'in dokuzu ile B1, B2, B3, B12, C8, C9a, C10, C12, C15, C16, A7, A9, D2. Hepsi gerçek bir bulguya
  dayanıyor; sayılar raporla aynı (791 → 133 sn, 1534 = 1528 + 6, 109 testten sağ çıkan mutasyon, 420 test, 14/15 sınırı).
- Kodla karşılaştırılan 13 atıf doğru: `gate.py:87, :189`; `unattended-paper.md:27-34`; `tests/test_runner.py:592`;
  `runner.py:583-615` (main); `alpaca_broker.py:73, :347` (main); `sdk_compat.py:25`; `test_architecture.py:981, :1659`;
  `runner.py:88` ve `writer.py:219` (#63); `worker.test.js:418-440`; `cli.py:283`; `ci.yml:35, 87, 123`; `AGENTS.md:1381`.
  İtiraz 9'daki rapor dışı "8 + 4 kırmızı" iddiası kanarya log'undan doğrulandı (`ufuk-dl/canary.log:1052-1066`).
- Kusurlar: B2'nin "UF 16" atfı yanlış; C8'in `:347`'si main satırı (#63'te `:369`); §6 madde 3 GÜV Y1'i daraltmış (Z1).

**4. Dosya çakışması — GEÇTİ (çelişkiler Z8'de).**
- Beş turun hiçbirinde iki iş aynı dosyaya dokunmuyor; dokuz işin dosya kümeleri turlar arasında da ayrık. Döngü yok.
- `runner.py`, `journal/writer.py`, `core/types.py` dokunan her iş #63 üstünde (B1, B3, B4, B6–B14, C9b; D9 "#63 sonrası").
  main'den açılan B2, C2, C7, C11, C12, C14, C15 #63'ün değiştirdiği 17 dosyadan hiçbirine dokunmuyor.
- Çelişkiler: "B0 gecikirse B11–B14 öne alınır" ama B11 → B5 → B4 → B0; Sprint 2'de B3, bağlı olduğu A8'den önce; C15
  `evidence.py`'ı değiştiriyor, İtiraz 11 aynı dosyaya "değişmemeli" diyor.

**5. Uygulanabilirlik — GEÇTİ (notlu).**
- A1, A2, A3, A6a, C0: kapsam tek uygulayıcıya uygun, ölçütler sınanabilir, kanıt türü doğru (mutasyon, bayt karşılaştırması,
  önce/sonra süre, kırmızı → yeşil); ortak kural tam `make check` sayılarını istiyor.
- Belirsiz: A5a (PAT ve Cloudflare desenleri tanımsız; `.pre-commit` değişikliğinin kanıtı yok; "dört ihlal" beş kuralı
  karşılamıyor), A4 ("teknik terimsiz" ölçülemez; güncelleme sorumlusu yok), B0 ("Codex yanıtı kayıtta" uygulayıcının elinde
  değil). "Oku" satırları geçici dizinlere (`wt-a5`, `wt-r63`) bağlı; dal ve SHA yazılmalı.

**6. Öncelik — KALDI.**
- **(a)** Yürütme düzeltmelerinin hepsini ertelemek doğru değil. Plan B1, B2, B3 ve C8'in tasarımı beklemediğini kendisi
  yazıyor (§4 T1); darboğaz 12 işlik seri runner zinciri ve her halkası Codex'in SHA'ya bağlı onayını bekliyor. B1 ve B2 en ağır
  doğrulanmış sınıf (YÇ B1, B4), boyları S, kırmızı testleri hazır, Sprint 1 dosyalarıyla çakışmıyor, iki boş yer var (B63
  bitti; Tur 5 tek iş). Dalda başlamak dondurmayı etkilemez. Canlı `tlab run` koşmadığı için gerekçe acil risk değil, inceleme
  süresidir. B3, A8'den sonra Sprint 2'nin ilk işi olmalı.
- **(b)** Planlamacı mekanikte haklı: düzeltme dondurulmuş `alpaca_broker.py`'da, süzgeç gevşetmek yanlış. Ama kanarya üç
  haftadır alarm değeri taşımıyor ve SDK uyarısı sayacın 2026-07-06'da yanıtlardan kalktığını söylüyor: PDT kuralı kilitli
  0.44'te de 0 okuyor olabilir. C8'in açık bağımlılığı kalmadı; Sprint 1'de dalda başlamalı. D2'nin ön koşullarında C8, D11 yok.
- **(c)** AGENTS §4a'ya uyum doğru (zorunlu onay ve Code Owners kapalı). Liste yine de güvenli değil:
  - Madde 3 "bizim zamanlanmış koşumuz dışında bir koşu görürseniz silin" diyor. Gerçek gözlem koşuları başlatıcının
    `workflow_dispatch`'idir (`shadow-observation.md:599, 602`); arayüzde "zamanlanmış" görünmez. Silinen koşunun gün özeti de
    silinir (`shadow_job.py:1617-1629`); iki bilinmeyen gün `iex_window_initial`'ı geçemez kılar (`shadow/summary.py:63, 124`).
  - Madde 8 ("kullanılmayan erişim anahtarlarını silin") ve 9 ("gereksizleri silin") tarihsiz; başlatıcı anahtarı, Alpaca paper
    anahtarı ya da geçmiş koşular kampanya bitmeden silinirse sonuç aynı.
  - Madde 2 ("bugün", planlı gün) ve tarihsiz madde 6 Actions ayar sayfasını değiştiriyor; yanlış seçim `checkout`'u engeller.
    Madde 2 kampanyayı korumaz: onay bekleyen yabancı koşu Y1 senaryosunun kendisidir.
  - Madde 4'te "Require approvals kapalı" belirsiz: ayar bir sayıdır (0 olmalı); "dal güncel olsun" seçeneği anılmamış.
- D2'nin ön koşullarında Koruma v2'nin ilk aşaması (B4–B8) yok; paper'da uygun emirlerin %10'u kısmi dolar (ALP §6).

**7. Bütünlük — GEÇTİ (notlu).** YÜKSEK bulguların hepsi planda: YÇ B1–B5, BT B1–B2, GÜV Y1–Y2, R63 R1–R2. Planda da §7'de de
olmayan düşük önemli kalemler: TK §5 `journal/db.py:96-100` (göç `ROLLBACK`'i testsiz); UF 9'un `__version__` uyumsuzluğu; GÜV
§4'ün "dağıtılan Worker kodu = depo" denetimi; ALP'nin `docs.alpaca.markets` ağ izni isteği ("en büyük risk"i daraltır).

**8. İtirazlar.**
1. Yarım SHA sabitleme yapılmaz: **planlamacı.** Tek sürüm testi (`test_architecture.py:1652-1659`) iki biçimi kabul etmez.
2. Günlük özet aracı Sprint 1 dışı: **planlamacı.** Girdisi iki gün sonra bitiyor; kalıcı karşılığı C5.
3. Koruma v2 iki aşama: **planlamacı**, şartla: ilk aşama D2'nin ön koşulu olarak yazılır (Z6).
4. P8 karardan bağımsız (C7): **planlamacı.** Modül yalnız journal okur.
5. Y1'in kalıcı düzeltmesi bu kampanyayı korumaz: **planlamacı.** `shadow_job.py` parmak izinde; koruma yalnız §6'dır.
6. Code Owners incelemesi açılmaz: **planlamacı.** AGENTS §4a açık.
7. 15 dakikalık CI sınırı konmaz: **planlamacı.** Bugün `ci.yml`'de sınır yok, testler 18 dk; önce A1, sonra ölçüm.
8. Kampanya sürerken `worker.js`'e dokunulmaz: **planlamacı.** Yalnız test dosyası (A9).
9. Kanarya main'de şimdi düzelmez: **planlamacı**; C8'in Sprint 2'ye bırakılmasında **yönetim** (6b).
10. Hatalı davranış yeşil sabitlenmez: **planlamacı.** A8'deki "8 kat sabit" ölçütü bu ilkeyle uyumlu yazılmalı.
11. `evidence.py` değişmez, yeni modül: **planlamacı** (`AGENTS.md:1381`); C15 aynı ilkeye uymalı (Z8).
12. B11–B14 aynı dosyada, seri: olguda **planlamacı**; "hepsi bekler" sonucunda **yönetim**: zincirin başı şimdi başlar (Z7).

## Zorunlu değişiklikler

- **Z1 — §6 madde 3 yeniden yazılır;** "silin" varsayılan eylem olmaz. İstenen içerik: "O sabah (TR 08:00–15:50) oluşmuş bir
  koşu görürseniz silmeden bize yazın. Yalnız yanında 'Pull request' ya da tanımadığınız bir kullanıcı adı yazan o tek koşu
  silinebilir. Önceki günlerin koşularına ('Scheduled' ya da sizin adınızla 'Manually run' dahil) dokunmayın."
- **Z2 — §6 madde 8 ve 9.** Toplam doğrulanana kadar hiçbir anahtar silinmez ya da yenilenmez; hiçbir Actions koşusu ve
  artefaktı silinmez. Korunanlar adıyla yazılır: `STARTER_GITHUB_PAT`, Alpaca paper anahtarı, ajan bağlantıları, "Shadow
  observation", "Shadow aggregate", AGENTS §7'deki ölçüm koşuları. Madde 9 toplam ve D7'den sonraya alınır; listeyi Yönetim verir.
- **Z3 — §6 madde 2 ve 6.** Actions ayar sayfası planlı günde değişmez: ya 26–27 Kasım'da (o günün "plan dışı gün" koşusu
  yeşil bittiyse ayar zararsızdır; Yönetim salt okuyarak doğrular) ya da 1 Aralık koşusu bittikten sonra. Madde 6'nın "yalnız
  GitHub'ın action'ları" adımı son koşudan sonraya yazılır. Madde 2'ye eklenir: "Yabancı PR'da 'Approve and run'a basmayın."
- **Z4 — §6 madde 4.** Kesin değerler: "Required approvals: 0", "Require review from Code Owners" kapalı, "Require branches to
  be up to date before merging" kapalı (zincirde her güncelleme yeni SHA ve yeni ONAY ister).
- **Z5 — B12 ve B14 ölçüm semantiği işareti alır** (K8'e eklenir ya da yeni karar); Özet 6 güncellenir. B6–B9 ve B12–B14'ün
  kabul ölçütüne eklenir: "sentetik baseline raporu değişiklikten önce ve sonra karşılaştırılır; fark varsa kayıtlı kararla".
- **Z6 — D2'nin ön koşulları:** B4–B8 (Koruma v2 ilk aşama), C8 ve D11/K11 eklenir.
- **Z7 — Sprint 1.** B63 "tamamlandı (8fd2234)" yazılır, yığın tabanı 8fd2234 olur; B63'ün yapılmayan iki alt maddesi (`trades`
  satır sayısı, `MAX_CANCEL_ATTEMPTS` açıklaması) B10'a taşınır ya da açıkça düşülür. **B1** Tur 2'ye (B0 ∥ B1), **B2** Tur 5'e
  (C0 ∥ B2) eklenir; dalda kalırlar, birleşme toplam ve C0'dan sonra. Özet 2: "davranış değiştiren `src/` main'e girmez".
- **Z8 — Zincir çelişkileri.** Yedek kural "B12–B14 öne alınır" olur (ya da B5'in kesin ret ayrımı ayrı iş yapılır);
  Sprint 2 sırasında A8, B3'ten önce gelir; C15'ten `evidence.py` çıkarılır ya da K13'ün bu dosyayı kapsadığı yazılır.

## Notlar (engel değil)

- "≥2 Aralık" kısaltması yanıltıcı; koşul "toplam doğrulandı ve C0 birleşti"dir. A6a'ya yazılmalı: C0'dan sonra her `src/`
  dalına main alınır, SHA değişir, Codex ONAY'ı yenilenir (#63 dahil). C0'da kaydı doldurmak kapıyı açar; #17 kararı ister.
- A3 1 Aralık'a yetişmezse eşikler değişmeden birleşir; eşiklerin sonuçtan önceki kaydı `unattended-paper.md:27-34`'tür.
- §6: madde 5 (anahtar taraması) "bugün"e alınabilir (Actions'a dokunmaz; 2026-09-20 öncesi geçmiş taranmadı); madde 1'e
  "açık yabancı PR varsa kapatın" eklenmeli; madde 11'deki "onaylayan siz" gözetimsiz paper işini her sabah bekletir (D4'te
  karara bağlanmalı); ALP'nin ağ izni isteği §6'ya seçenek olarak girmeli.
- Eksik bağımlılıklar: C16 ↔ C19 (`shadow_job.py`), B13 ↔ D11 (`gate.py`). Ölçüt 7'deki kalemler §7'ye eklenmeli. A5a'ya
  desenlerin kesin ifadesi ve kanca için çevrimdışı bir test yazılmalı.
- **Doğrulanmadı:** depo ayarlarının bugünkü durumu, açık yabancı PR, bugüne kadarki kayıp gün sayısı (GitHub okunmadı);
  arayüzdeki seçenek adları ve etkileşim sınırının ajan kimliğine etkisi (ayardan sonra deneme yorumuyla sınanmalı).

## Sprint 1'e eklenmesini/çıkarılmasını önerdiklerim

- **Ekle (zorunlu, Z7): B1.** En ağır doğrulanmış bulgu ve runner zincirinin başı; B63 bittiği için yeri ve tabanı hazır.
- **Ekle (zorunlu, Z7): B2.** #63'ten bağımsız, tek kaynak dosyası, kırmızı testi hazır; asılı çağrı kill-switch'i de durdurur.
- **Ekle (öneri): C8.** Kanarya üç haftadır kör; adaptör zincirinin başı; 2 Aralık'ta incelenmiş ve hazır olmalı.
- **Ekle (öneri): A8.** Yalnız yeni test dosyası, şimdi birleşir; B3'ün ön koşulu.
- **Ertele (öneri): A5a → Sprint 2 başı,** yer gerekirse: 2 Aralık'tan önce son tarihi yok, ölçütleri en belirsiz iş.
- **Çıkar:** B63 (tamamlandı). **Kalsın:** A1, A3, B0, A2, A6a, C0; A4 ancak Z1–Z4 işlendikten sonra yazılır (kabul ölçütü
  §6'nın ilk beş maddesini panoya taşıyor).

## Yeniden inceleme — c691e0c (Z1–Z8)

Karar: **ONAY (notlarla).** Yalnız Z1–Z8 ve düzeltmenin getirdiği çelişkiler okundu (`git diff HEAD~1 -- docs/office/backlog.md`).

- **Z1–Z4 karşılandı.** §6 madde 3 artık "silmeden bize yazın" diyor ve önceki günlerin koşularını ("Manually run" dahil) koruyor;
  genel kural ile madde 7, 8, 9 silmeyi ve anahtar yenilemeyi toplamdan sonraya alıyor; Actions sayfası madde 4 ve 6'da planlı
  günlerin dışına taşınmış; madde 5 kesin değerleri veriyor ("Required approvals: 0", Code Owners ve "up to date" kapalı).
- **Z5–Z6 karşılandı.** Özet 6 sekiz iş; K8 bekleyenlerinde B12 ve B14; B6–B9 ve B12–B14 için baseline karşılaştırması; D2 ön koşul notu.
- **Z7–Z8 karşılandı.** Tur 2 = B0 ∥ B1, Tur 5 = C0 ∥ B2, B63 tamamlandı. `MAX_CANCEL_ATTEMPTS` açıklaması 2876da0'da doğrulandı;
  `trades` sayımı B10'da. Yedek kural B12–B14; Sprint 2 sırası "C8; A8 → B3"; C15 notu `evidence.py`'ı koruyor.
- C8'in Sprint 2'nin ilk işi olması ve A5a'nın Sprint 1'de kalması engel değil.

**Sahibe iletilmeden önce düzeltilecek tek satır (yeniden inceleme gerekmez):** Özet 7 hâlâ "bugün beklenen üç ayar … dış PR iş
akışlarını onaya bağlamak" diyor; §6 madde 4 ile çelişiyor. Doğrusu: bugün madde 1 (isterse madde 2), bu hafta madde 5; Actions
ayarı 26–27 Kasım'da ya da 1 Aralık koşusundan sonra. Sahibe Özet değil §6 metni gitmeli.

Notlar (engel değil):
- Genel kural "hiçbir koşu silinmez" derken madde 3 tek yabancı koşunun silinebileceğini söylüyor; genel kurala "tek istisna madde 3"
  yazılmalı. Madde 4'e "ayardan sonra haber verin" eklenmeli (Yönetim'in doğrulaması buna bağlı). Madde 6 için "toplam doğrulandıktan
  sonra" daha güvenli: toplam koşusu da Actions'ta çalışır. Madde 2'ye: "uyarı çıkarsa bize yazın; anahtarı kendiniz yenilemeyin."
- Bayat atıflar: İtiraz 5 ("§6 madde 1–3") ve İtiraz 6 ("§6 madde 4"; kural artık madde 5); §7'deki "GÜV D9 … sahip işi (§6)" (eski
  madde 12 kalktı); C15 satırının dosya listesinde `evidence.py` duruyor; D2 satırının "Bekleyen" sütunu nota göre güncellenmemiş.
- A4'ün kabul ölçütü "ilk beş madde"nin yanında genel kuralı da taşımalı. B1 dalı, #63'te süren tur commit edildikten sonra
  açılmalı (ikisi de `runner.py`'a dokunuyor).
