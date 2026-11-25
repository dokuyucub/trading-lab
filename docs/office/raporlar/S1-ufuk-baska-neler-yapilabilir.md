# S1 — Fikir ve Ufuk: başka neler yapılabilir?

- **Birim:** Fikir ve Ufuk. **Tarih:** 2026-11-25. **Taban:** main `47a2a7d`. Rapor yazılırken main, yalnız
  `docs/designs/event-blocks.md` ekleyen #62 ile `d77b381`'e ilerledi; o belge bu rapora girmedi.
- **Yöntem:** salt okuma. Depo dosyaları ve GitHub API'sinden salt okunur sorgular: depo görünürlüğü, dal
  koruması, etiket sayısı, CI koşu süreleri, kanarya log'u, #11 ve #17 yorumları. Emir, tetik, Alpaca
  çağrısı, commit yok.
- **Doğrulanmadı:** bu birim hiçbir testi sonuna kadar koşmadı. Fikir 6 ve 16'daki riskler kod ve log
  okumasına dayanır; çalıştırılarak gösterilmedi. Süre rakamları CI API'sinden ve ofisin mevcut ölçüm
  loglarından alındı. GitHub ve Cloudflare platform kuralları bu oturumda yeniden doğrulanmadı.

## 1. Sonuç

1. Kod tarafı disiplinli. Eksik olan, "gözetimsiz" sözünün işletme tarafı: sahibin durumu tek yerde
   görmesi, bekçiyi izleyen ikinci bir bekçi, sade Türkçe olay rehberleri ve telefondan acil durdurma.
2. Saatinde çalışan tek parça Cloudflare başlatıcısı (17/17 gün, +53–54 sn). GitHub zamanlayıcısı ve
   Claude zamanlı görevleri ~9 saat gecikebiliyor; izleme hâlâ tek oturuma bağlı ve başarıda sessiz.
3. Kod ve log okumasında paper'dan önce kapanması gereken üç sessiz risk görüldü (çalıştırılarak
   doğrulanmadı): `tlab run` yolunda HTTP zaman aşımı yok; hata beklemesi kapanış tamponunu yiyebiliyor;
   PDT sayacının okuduğu alan sağlayıcıdan kalkmış olabilir (haftalık kanarya üç haftadır kırmızı).
4. Ölçüm dürüstlüğü için üç kayıt eksik: deney sicili, "aylarca yetersiz veri kalırsa ne olur" kuralı ve
   canlıya hazırlık listesi. Üçü de sonuç görülmeden, yani şimdi yazılmalı.
5. Takvim baskısı var: gün özetleri 1 Ocak 2027'den itibaren siliniyor, başlatıcı anahtarı 20 Ocak'ta
   bitiyor, depoda hiç sürüm etiketi yok. 2 Aralık'tan önce etiket ve birleştirme sırası hazır olmalı.

## 2. Fikirler

Değer: Y yüksek, O orta, D düşük. Efor: S küçük, M orta, L büyük. Dondurma: **Şimdi** = bugün main'e
girebilir (belge, test, script, diğer iş akışları); **Dal** = 2 Aralık'a kadar dalda bekler; **Sahip** =
sahibin kararı ya da eylemi gerekir.

| # | Fikir | Depodaki somut boşluk (kanıt) | Değer | Efor | Risk | Dondurma |
|---|---|---|---|---|---|---|
| 1 | Sahip panosu ve karar kuyruğu | #17'de 242, #11'de 177 yorum (API). Erken alarm ve günlük kayıt da #17'ye yazılıyor (`docs/designs/shadow-observation.md:603`). Sahibe ait karar etiketi yok. Sahibe yönelik belge yalnız `docs/github-paper-check.md` ve `docs/alpaca-paper-check.md`. | Y — durum, bekleyen karar ve risk tek yerde | S | Pano elle güncellenirse bayatlar | Şimdi |
| 2 | Günlük sade Türkçe özet aracı | `scripts/shadow_report.py` yalnız 20 günlük toplamı çevirir. Günlük `KAYIT — gölge gün` yorumu koşu kimliği, SHA ve UTC saat tablosudur (#17, 25 Kasım 06:33Z). `tlab summary` yerel journal ister (`src/tlab/cli.py`, `_print_summary`). | Y — sahip her günü 10 satırda okur | S | Özet yorum katmamalı, fiyat taşımamalı | Şimdi |
| 3 | Olumlu nabız ve oturuma bağlı olmayan bekçi | İki izleme görevi "bu oturuma bağlı" (`shadow-observation.md:603`). Erken alarm başarıda sessiz (`scheduler-alternatives.md:89`): sessizlik "yolunda" ile "bekçi çalışmadı"yı ayırmıyor. 24 Kasım günlük kontrolü ~9 saat geç geldi (#17). | Y — sessiz arıza görünür olur | S kural, M bağımsız bekçi | Kampanya sürerken başlatıcıya dokunulmaz | Şimdi (kural); başlatıcı değişikliği Dal + Sahip |
| 4 | Sade Türkçe olay rehberleri | Tek rehber `CONTRIBUTING.md` §4: git geri alma, komut satırı. "Erken alarm gelirse" adımı yalnız tasarım belgesinde tek cümle. Anahtar sızması `SECURITY.md`'de iki cümle. Başlatıcı anahtarı bitişi, kill-switch, gece açık kalan pozisyon için rehber yok. | Y — sahip ne yapacağını bilir | S | Düşük | Şimdi |
| 5 | Telefondan acil durdurma | Elle durdurma düzeneği yok: tek kill-switch günlük zarar eşiği (`engine/runner.py`, `_check_kill_switch`). `unattended-paper.md` §4 "Durdurma" bir süreçtir, düğme değil. Actions koşusunu iptal etmek pozisyonu kapatmaz. `cli.py`'de kapatma komutu yok. | Y — gözetimsiz sistemin tek elle freni | M | Emir gönderen yeni komut ve secret'lı iş akışı | Tasarım Şimdi; kod Dal; Sahip |
| 6 | Arıza tatbikatı test paketi | `run_forever` için test yok (testlerde yalnız docstring'de geçiyor). Bekleme 8 kata çıkıyor (`runner.py:60,175-177`), kapanış tamponu 10 dk (`config/base.yaml`). `tlab run` istemcileri zaman aşımı sarmalayıcısı olmadan kuruyor (`cli.py:283-294`); `shadow_job.py:483-486` uyguluyor; `sdk_compat.py:150-152` "istek süresiz asılı kalır" diyor. | Y — paper öncesi açıklar adıyla belli olur | M | Takılan test CI'ı bozar; sahte saat şart | Testler Şimdi; düzeltmeler Dal |
| 7 | Döngüde nabız kaydı, düzgün kapanış, yapılandırılmış log | Journal'da nabız yok (`journal/migrations/001_initial.sql`, `runs`). `ended_at` yalnız temiz çıkışta yazılıyor (`cli.py:341`); `src/tlab` içinde sinyal yakalama yok. Çöken, durdurulan ve takılan koşu ayırt edilemiyor. Log serbest metin. | O — bekçinin okuyacağı veri | M | Göç numarası, `engine/` çift göz | Dal |
| 8 | Değer basmayan ön uçuş ve paper gün özeti sözleşmesi | `doctor` özsermaye basar, genel koşuya taşınamaz (AGENTS §3.1). `cmd_run` başlarken hesap sağlığı, saat farkı, journal bütünlüğü, hesapta yabancı emir (AGENTS §9) denetlenmiyor. `unattended-paper.md` §4 beş günlük kontrolü sayıyor; üreten araç ve fiyatsız özet şeması yok. | Y — planlı paper işini somutlar | M | Özet hesap değeri sızdırmamalı | Tasarım Şimdi; kod Dal |
| 9 | Sürüm damgası: etiket, sürüm numarası, imajda commit | Depoda 0 etiket (API, `git tag`). `CHANGELOG.md:7` "her sürüm bir etikete karşılık gelir" diyor; `CONTRIBUTING.md` §4.2–4.6 komutları `v0.1.0` kullanıyor. `__version__` ve `pyproject.toml` 0.1.0, CHANGELOG 0.3.0. İmajda git yok: `current_git_sha()` boş döner (`journal/writer.py:46-60`). `docker/docker-compose.yml:12-13` `doctor` + `restart: unless-stopped`. | Y — geri dönüş rehberi bugün çalışmıyor | S | Geçmiş etiketin yanlış commit'e konması | Etiket, CHANGELOG, docker Şimdi; `src/` Dal |
| 10 | Dondurma sonrası birleştirme sırası | Bekleyenler: #63, Dependabot kilit PR'ları (`shadow-observation.md:612`), kampanya sabitleri (`tests/test_shadow_job.py:733`), alpaca-py 0.45 uyumu. Sıra, yeniden sabitleme ve geri dönüş noktası yazılı değil. | Y — riskli PR'lar art arda girecek | S | Düşük | Şimdi |
| 11 | `main` dal korumasını açmak | API: depo `public`, `main` `protected: false`. AGENTS §1 "kullanılabilir olduğunda açılır" diyor; `CONTRIBUTING.md` §1 üç ayarı sayıyor. Depo açık olduğu için ücretsiz planda kullanılabilir. "Onay zorunlu" kuralı açılmaz (AGENTS §4a). | Y — kural artık GitHub tarafından uygulanır | S | Yanlış ayar her PR'ı kilitler | Sahip |
| 12 | Deney sicili ve ön kayıt | Çoklu deneme düzeltmesi çağıranın verdiği sayıya bağlı (`learning/promotion.py`, `candidates_considered`, varsayılan 1). Kaç hipotez denendiğini sayan kayıt yok. Ölçüm kararları AGENTS §7 ve §11'e (900+ satır) ve #17'ye dağılmış. | Y — "kaç kez baktık" sorusu kayda bağlanır | S–M | Geriye dönük kayıt yeni iddia üretmemeli | Şimdi |
| 13 | Kanıt bütçesi ve vazgeçme kuralı | Tek ölçüm 67 işlem / 50 seans, taban 100. `unattended-paper.md` §1 paper'a geçişi tanımlar; "N seans sonra hâlâ `insufficient_data` ise" kuralı yok. AGENTS §7 "yeni tarih aralığı keyfî seçilmez" der; kurala bağlı ileri dönem tanımı yok. | Y — aylarca belirsizlikte ne yapılacağı belli olur | S | Kural sonuç görüldükten sonra yazılırsa değersiz | Şimdi + Sahip |
| 14 | Journal'ın kalıcılığı ve fiyatsız öğrenme dışa aktarımı | A seçeneğinde journal iş içinde, "gün sonunda artefakt ya da yok" (`unattended-paper.md` §3). Artefakt hesap değeri içerir, kuralla çelişir (aynı bölüm, B). Faz 3'ün girdisinin nerede duracağı kararsız. | Y — öğrenme katmanının yakıtı | M | Açık depoda işlem kaydı sızıntısı | Tasarım Şimdi; Sahip |
| 15 | Kanıt arşivi ve son kullanma takvimi | Gün özetleri 60 gün (`shadow-observation.yml:115`): 2 Kasım özeti 1 Ocak 2027'de silinir; "süresi dolmuş artefakt atlanır" (tasarım §6). Toplam 90 gün (`shadow-aggregate.yml:72`). Baseline raporu 11 Ocak 2027 (AGENTS §7). Başlatıcı anahtarı 20 Ocak 2027 (#17, 25 Ekim). Tarihler tek yerde değil. | Y — kanıt kaybolmadan saklanır | S | Düşük; dosyalar fiyatsız | Şimdi |
| 16 | Sağlayıcı sözleşmesi kayması takibi | Haftalık kanarya 9, 16, 23 Kasım'da kırmızı (API). Log: alpaca-py 0.45.0, `daytrade_count` için "2026-07-06'da yanıtlardan kaldırıldı" uyarısı. PDT kuralı bu alana bakar (`risk/gate.py:114`); alan yoksa 0 sayılır (`execution/alpaca_broker.py:73`, `sdk_compat.py:45-53`). #11'de yalnız "ayrı izleyelim" notu var (6994001323, 7115900128). | Y — risk kuralı sessizce devre dışı kalabilir | S kayıt ve test, M kod | Gerçek yanıt doğrulanmadı | Kayıt ve test Şimdi; kod Dal |
| 17 | Çoklu strateji arayüz taslağı | Strateji kodda sabit (`cli.py:301,367`). Motor ORB'ye özgü `opening_range_minutes` alıyor (`runner.py:117`). `runs.params_version` tek değer. `config.py`'de strateji bölümü yok; risk bütçesi hesap geneli (`RiskSection`). | O — Faz 5'te göç ve yeniden yazım azalır | M (yalnız tasarım) | Erken soyutlama | Tasarım Şimdi; kod Faz 3 sonrası |
| 18 | AGENTS.md'yi kural ve kayıt olarak ayırmak; belge kaymasını düzeltmek | 1483 satır; 467–938 ve 1030–1483 tarihli yürütme kayıtları. Bugün bağlayıcı olan kampanya dondurması AGENTS.md'de yok (`shadow-observation.md:612`), oysa §4b "yazılmadıysa alınmamış sayılır". "Depo gizli" dört yerde (`AGENTS.md:89-90`, `ci.yml:8`, `artifact-roundtrip.yml:14`, `SECURITY.md`). README "Durum: Faz 2". Son devir notu Eylül. | Y — her ajan her işte bu dosyayı okuyor | M | Ortak sözleşme; Codex ONAY'ı şart | Şimdi (belge) |
| 19 | Test süresi | Eylül: 338 test 18,6 sn (`docs/handoffs/001`). Bugün ~1650 test; CI `Testler` adımı 18 dk (koşu 45455157477), yerel `make check` 22–24 dk (ofis logları). En yavaş testler bu raporda ölçülmedi. | O — her inceleme turu +20 dk | M | Kapı gevşetilmemeli: aynı testler koşmalı | Şimdi (geliştirme araçları) |
| 20 | Canlıya hazırlık kanıt listesi | `unattended-paper.md` §4 "Gerçek para: ayrı belge, ayrı karar" der; belge yok. Koddaki tek engel iki bayrak (`SECURITY.md`; `cli.py:275-281`). AGENTS §7 üç doğrulanmamış başlık sayar, eşik yok. | Y — eşikler sonuçtan önce yazılır | S | Liste izin gibi okunmamalı | Şimdi + Sahip |

## 3. Şimdi yapılacak ilk 5

### 1) Sahip panosu ve günlük sade özet (fikir 1 ve 2)

- **Kapsam.** `docs/sahip/DURUM.md`: dört kutu — "Bugün ne oldu", "Sizden beklenen", "Risk durumu",
  "Yaklaşan tarihler". Düşük trafikli tek bir "Sahip panosu" başlığı ve `sahip-karari` etiketi; alarm
  ve günlük özet oraya yazılır, #17 teknik kayıt olarak kalır. `scripts/owner_digest.py`: yalnız standart
  kütüphane, `shadow_report.py` deseni; girdi günün `shadow-day.json` dosyası ve koşu üst verisi, çıktı en
  çok 10 satır sade Türkçe.
- **Dosyalar.** `docs/sahip/DURUM.md`, `scripts/owner_digest.py`, `tests/test_owner_digest.py`,
  `pyproject.toml` (mypy listesi), `.github/pull_request_template.md` ("Sahibi için tek cümle" ve
  "Dondurma etkisi" satırları), `docs/office/README.md` (kontrol listesine "pano güncellendi").
- **Kabul.** Özette koşu kimliği, SHA, UTC saat, fiyat ve hesap değeri yok (sahte işaretli test). Dört gün
  durumunun her biri için sabit metin testi. Beklenmeyen alan sabit hatayla durur. Araç yorum üretmez.
- **Neden şimdi.** Kampanyanın son günleri, toplam tıklaması ve paper kararı iki üç hafta içinde sahibin
  önüne gelecek. Bugün bunların hepsi 242 yorumluk tek başlıkta.

### 2) Arıza tatbikatı test paketi (fikir 6; fikir 16'nın testi)

- **Kapsam.** `tests/test_drills.py`, altı tatbikat:
  - T1 asılı istek: `tlab run` istemcisinde süre sınırı var mı. Gerçek asılı bağlantı kurulmaz;
    sarmalayıcının varlığı denetlenir.
  - T2 kapanış tamponunda ardışık hata: sahte saat ve sahte uyku ile `run_forever`; tampon içinde kaç
    deneme kalıyor. Kod okumasına göre 60 sn'lik döngüde bekleme 2, 4, 8, 8 dakikadır.
  - T3 saat kayması: yerel saat broker saatinden ±5 dk.
  - T4 journal: bozuk dosya, kilitli dosya, yazılamayan disk.
  - T5 yeniden başlatma fırtınası: art arda 20 taze süreç; tek emir, tek kayıt.
  - T6 eksik alan: hesap yanıtında `daytrade_count` yok; bugünkü davranış (0 sayılır) sabitlenir.
- **Dosyalar.** Yalnız `tests/` ve `docs/designs/unattended-paper.md` §4 (açık listesi). `src/` yok.
- **Kabul.** Her test bugünkü davranışı sabitler ve istenen davranışı docstring'inde yazar
  (`tests/test_kill_switch_durability.py` emsali). Gerçek uyku yok; toplam ek süre 30 sn'nin altında. Her
  test için mutasyon ya da kırmızı koşu kanıtı. Bulunan her açık `unattended-paper.md` §4'e işlenir.
- **Neden şimdi.** Düzeltmeler `src/` altında ve 2 Aralık'ı bekliyor. Tatbikatlar şimdi birleşirse hangi
  düzeltmenin hangi testi yeşile çevireceği önceden bellidir. Paper işi çıplak `tlab run` üstüne
  kurulmamalı; tasarımı bu sonuçlara bağlı.

### 3) Kanıt arşivi ve son kullanma takvimi (fikir 15)

- **Kapsam.** `docs/ops/takvim.md`: tarih, ne biter, kaçırılırsa ne olur, kim yapar. Satırlar: 2 Aralık
  (en erken toplam), 24 Aralık (önerilen son toplam tıklaması), 1 Ocak 2027 (ilk gün özeti silinir),
  11 Ocak (baseline raporu), 20 Ocak (başlatıcı anahtarı), toplam artefaktının 90. günü, zamanlı işlerin
  60 gün hareketsizlikte kapanması, 6 saatlik iş sınırı. `docs/records/evidence/`: fiyatsız kanıt
  dosyaları ve `SHA256SUMS` — baseline raporu, toplam özeti ve 20 gün özeti.
- **Dosyalar.** `docs/ops/takvim.md`, `docs/records/evidence/*`, `tests/test_evidence_archive.py`.
- **Kabul.** Her dosyanın SHA-256'sı kayıttakiyle aynı; kaynak koşu kimliği ve API digest'i yanında
  yazılı. Testte: dosyalarda fiyat alanı yok; takvimdeki tarih koddan türeyenle aynı (ilk planlı gün +
  60 gün). İndirme ayrı boş dizinde ve `python3 -I` ile. Güvenlik birimi baseline JSON'unu ayrıca onaylar
  (sentetik P&L içerir; değerler AGENTS §7'de zaten yayımlı).
- **Neden şimdi.** Tarihler sabit. Toplam geç tıklanırsa ilk günler sessizce `eksik` sayılır. Arşiv
  yapılmazsa "doğrulandı" satırlarının dayandığı dosyalar Ocak ve Mart'ta GitHub'dan silinir.
- **Not.** AGENTS §7'ye göre Claude oturumu artefakt ZIP'ini indiremedi (403); indirmeyi Codex ya da sahip
  yapabilir.

### 4) Sürüm etiketleri ve çözülme planı (fikir 9 ve 10)

- **Kapsam.** Geçmiş sürümlere açıklamalı etiket: `v0.1.0`, `v0.1.1`, `v0.2.0`, `v0.2.1`, `v0.3.0`;
  commit'ler Codex ile doğrulanır. Kampanyanın koştuğu `47a2a7d` için çözülmeden önce bir etiket.
  `CHANGELOG.md` `[Yayınlanmamış]` bölümü sürüm başlığına çevrilir ve eksik maddeler eklenir (baseline
  ölçümü, gölge kampanyası, başlatıcı). `docs/ops/surumler.md`: sürüm → commit tablosu.
  `docs/ops/cozulme-plani.md`: sıra — toplam doğrulandı kaydı; kampanya sabitlerini tarihsel yapan PR;
  #63; tatbikat düzeltmeleri; `__version__`; en son Dependabot kilidi ve alpaca-py 0.45 uyumu.
- **Dosyalar.** `CHANGELOG.md`, `docs/ops/surumler.md`, `docs/ops/cozulme-plani.md`,
  `tests/test_release_table.py`, `docker/docker-compose.yml` ve yeni `.dockerignore`.
- **Kabul.** `git tag -l` beş sürümü ve kampanya etiketini listeler; `git switch --detach v0.3.0`
  çalışır. Test, CHANGELOG'daki her sürüm başlığının tabloda olduğunu denetler (CI etiketleri çekmediği
  için test etikete değil tabloya bakar). Plan Codex ONAY'lı; her adımın geri alma komutu yazılı.
- **Neden şimdi.** 2 Aralık'tan sonra riskli PR'lar art arda girecek. Bugün geri dönülecek adlandırılmış
  tek bir nokta yok. Etiket main'in içeriğini değiştirmez, dondurmayı bozmaz.

### 5) Ön kayıt paketi: deney sicili, kanıt bütçesi, canlıya hazırlık listesi (fikir 12, 13, 20)

- **Kapsam.** `docs/experiments/`: kurallar ve iki kayıt — `E001` SIP baseline (sonuç
  `insufficient_data`), `E002` gölge kampanyası (eşikler yazılı, sonuç boş).
  `docs/designs/evidence-budget.md`: paper'da en çok kaç seans ya da işlem beklenir; hangi ölçütte ORB
  sürümü bırakılır; izinli kanıt kaynakları (kurala bağlı ileri dönem veri kümesi, paper ileri sonuçları,
  veri kullanmayan güç tablosu `scripts/power_table.py`); yasaklar. `docs/designs/live-readiness.md`:
  kanıt sınıfları — emir yaşam döngüsü, gözetimsiz gün sayısı, tatbikatların paper'da geçmesi,
  istatistik eşiği, simülasyon ile paper dolum farkı, işletme (bekçi, rehber, acil durdurma), sermaye
  tavanı.
- **Dosyalar.** Yukarıdakiler ve `tests/test_experiment_registry.py`.
- **Kabul.** Üç belge paper'ın ilk işlem gününden önce birleşmiş. Eşikler sahip ve Codex kararıyla dolu
  ya da açıkça "karar bekliyor". Sicil testi: `config/datasets/` altındaki her onaylı tanımın sicilde
  satırı var (mutasyon: tanım ekle, sicile ekleme → kırmızı).
- **Neden şimdi.** AGENTS §3.11'in gerekçesi burada da geçerli: kural sonuç görülmeden yazılır. Paper
  sonucu görüldükten sonra yazılan vazgeçme kuralı ve canlı eşiği pazarlığa dönüşür.

## 4. Yapılmaması gerekenler

- **67 işlemi 100'e tamamlamak için tarih seçmek ya da aynı dönemi yeniden ölçmek.** AGENTS §7 kararı
  bunu yasaklar; sayı dolar, kanıt değeri kalmaz.
- **Holdout'u "yalnızca bakmak için" açmak.** Bir kez görülen dönem bir daha bağımsız sayılamaz (§3.11).
- **İkinci stratejiyi şimdi yazmak.** Tek strateji bile kanıtlanmadı; her yeni aday çoklu karşılaştırma
  yükünü artırır. Önce sicil (fikir 12), sonra aday. Fikir 17 yalnız tasarımdır.
- **Paper sonucuna bakıp ayar değiştiren otomatik döngü ya da gece otomatik terfi.** AGENTS §3.9.
- **Sahip özetini bir dil modeline yorumlatmak.** Özet sayılardan sabit kalıpla üretilmeli; serbest
  yorum, olumsuz sonucu yumuşatmanın en kolay yoludur.
- **Açık depoda P&L, özsermaye ya da fiyat gösteren pano.** Kural açık; pano sayım ve durum taşır.
- **Kampanya sürerken başlatıcıyı, iki gölge iş akışını ya da `src/` altını "küçük iyileştirme" için
  değiştirmek.** Kimlik değişir, 17 günlük gözlem toplanamaz hale gelir.
- **Kırmızı kampanya testini dallarda `skip` ya da `xfail` ile yeşile çevirmek; CI'da test seçerek süre
  kısaltmak.** Fikir 19 aynı testleri koşmalı; kapı gevşemez.
- **Bildirim için yeni üçüncü taraf servis ve yeni secret.** Önce GitHub'ın kendi bildirimi denenir.
- **Yönetilen sunucuya şimdi geçmek.** A seçeneğinin kaybı ölçülmeden ücretli ortam ve ikinci anahtar
  kopyası alınmaz (`unattended-paper.md` §3).
- **`--i-understand-live` ile "küçük bir deneme".** Canlı para ayrı belge ve ayrı karardır.

## 5. Sahibin karar vermesi gerekenler

1. **Dal koruması.** GitHub ayarlarında beş dakikalık işlem: PR zorunlu, `quality` zorunlu, yöneticiler
   dahil; "onay zorunlu" kapalı kalır. İstenirse ajanlardan birine ayrı GitHub kimliği (AGENTS §4a).
2. **Toplam tıklamasının tarihi.** 2 Aralık'tan sonra; öneri en geç 24 Aralık. 1 Ocak'ta ilk gün özeti
   silinir.
3. **Alarm kanalı.** GitHub e-postası ve telefon bildirimi yeterli mi? "Planlı günde saat 09:10'a kadar
   nabız yoksa bu bir alarmdır" kuralı kabul ediliyor mu?
4. **Kanıt bütçesi.** Paper'da kaç ay ya da kaç seans beklenecek; süre dolunca strateji bırakılacak mı?
   Buna bağlı olarak IEX ile mi devam, ücretli SIP mi (bilinen karar).
5. **Paper'ın çalışacağı yer ve journal'ın saklanacağı yer.** Ücretsiz Actions (günün son 40 dakikası
   yok) ya da ücretli sunucu. İşlem kaydı açık depoya konamaz: özel depo mu, şifreli dosya mı?
6. **Acil durdurma düğmesi.** İsteniyor mu; kim basabilir; basıldığında pozisyonlar kapatılsın mı?
7. **Canlıya geçiş eşikleri.** Azami sermaye, asgari gözetimsiz paper günü, hesap büyüklüğü. Yazılması
   canlıya geçiş izni değildir.
8. **Başlatıcı anahtarı.** 20 Ocak 2027'de bitiyor. Paper da aynı başlatıcıyı kullanacaksa yenileme
   tarihi şimdiden takvime girmeli.
9. **Kanıt dosyalarının depoya kalıcı konması.** Fiyatsız özetler ve baseline raporu; onay gerekir.
10. **Geçmiş sürümlere etiket.** `v0.1.0`–`v0.3.0` ve kampanya commit'i için etiket konmasına onay.
