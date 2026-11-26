# S1 — Onay Kurulu: A3 gölge→paper kabul tablosu (b4a4b78)

Tarih: 2026-11-26 · dal `claude/golge-kabul-tablosu` · tek commit b4a4b78 (taban main d77b381) · 2 dosya, +405/−4

**Karar: ONAY (notlarla).** Tablo tasarımın altı ölçütünü olduğu gibi okuyor, hüküm vermiyor, bayraksız çıktı main ile bayt bayt aynı. PR açılabilir. Tek açık testte: gün eşiğinin **yalnız** `tamam` saydığı kilitli değil (kod doğru, mutant M1 kaçtı). **N1 birleştirme koşuludur**; yalnız test ekler, betik baytları b4a4b78 ile aynı kalır.

## Kontrol listesi

| Madde | Sonuç | Kanıt |
|---|---|---|
| Kapsam = onaylı plan (F3 P1, backlog A3) | sağlandı | `git show --stat b4a4b78`: yalnız `scripts/shadow_report.py` +117 ve `tests/test_shadow_report.py` +292/−4. Arayüz planla aynı: `acceptance(summary, *, expected_campaign=None)`, `--kabul [--campaign]` |
| Değişmez kısıtlar, dondurma | sağlandı | `src/tlab/**`, `config/`, kilit dosyası, iş akışı yok. Parmak izi yalnız paket `.py`, `config/*.yaml` ve kök dosyalarını sayar (`src/tlab/shadow_job.py:150-170`); pin testi b4a4b78'de yeşil (kendi koşum). Çıktıda fiyat, hesap değeri, ham veri yok |
| `ruff`, `mypy`, ilgili testler | sağlandı | Kendi koşum: `ruff check` ve `ruff format --check` iki dosyada temiz; `mypy` 116 dosyada temiz; `tests/test_shadow_report.py` 70 test toplandı, hepsi yeşil |
| Tam süit sayıları | sağlandı (logdan) | `makecheck-a3.log:66-67`: 1555 passed, 6 skipped, kapsam %90,65. 1528 + 27 = 1555; 27 yeni test elle sayımla tutuyor. Tam süit yeniden koşulmadı; logun b4a4b78'e ait olduğu Yönetim beyanıdır (**doğrulanmadı**) |
| Test silme, atlama, zayıflatma | yok | Silinen 4 satır: docstring sonu, `datetime` içe aktarımı, `total()` imzası ve `summarize` çağrısı (yeni parametrelerin varsayılanı eski sabitler). `skip`/`xfail` yok |
| Bayraksız çıktı bayt bayt aynı | sağlandı | Diff parçaları `@@ -8`, `@@ -68`, `@@ -315`, `@@ -329`: docstring, sabitler, `_short` sonrasına iki yeni fonksiyon, `main`; `validate` (161-222) ve `render` (250-334) değişmedi. Test (560) altın metni aynı koşuda `report.render(summary)` ile üretiyor, elle yazılmış değil; bu tek başına `render`in değişmediğini göstermez. Bağımsız kontrol: d77b381 betiği ile b4a4b78 betiği beş özette `render` çıktısında ve `python -I` bayraksız stdout'ta bayt bayt aynı |
| `python3 -I` | sağlandı | İçe aktarımlar yalnız standart kütüphane, diff yenisini eklemiyor; `-I` ve `-I -S` altında alt süreç testi (585) yeşil |
| Yeni davranış testle sabit, mutasyonla gösterilmiş | kısmen | 6 mutanttan 5'i yakalandı, 1'i kaçtı (N1) |
| Hata Avı bulguları | **yok** | A3 için Hata Avı ve uygulayıcı raporu yok. Düşmanca okumayı bu inceleme yaptı; ayrı tur **yapılmadı** |

## Tasarıma sadakat (`docs/designs/unattended-paper.md` §1, tablo ve izleyen iki paragraf)

| # | Tasarım | Betik (`scripts/shadow_report.py`) | Hüküm |
|---|---|---|---|
| 1 | `iex_window_initial` GEÇTİ (`Thresholds` varsayılanı) | `verdict == "gecti"` ve özet eşikleri `ACCEPT_THRESHOLDS` ile eşit (359-366) | aynı |
| 2 | `range_within_bps` GEÇTİ | aynı kural | aynı |
| 3 | `intent_agreement` GEÇTİ | aynı kural | aynı |
| 4 | en az 15/20 `tamam`; eksik günlerin sebebi kayıtta ve sistematik değil | iki satır: `days.tamam >= 15` ve `planned_days == 20` (368-376); ikinci yarı her zaman `elle doğrulanacak` | aynı; ne sıkı ne gevşek |
| 5 | İlk gün denetimi (#17 KAYIT) | her zaman `elle doğrulanacak` | aynı |
| 6 | Kayıt işi: koşusuz planlı gün yok ya da sebebi açıklanmış (günlük KAYIT'lar) | `baslamadi` + `bilinmiyor` 0 ise `sağlandı`; değilse günler adıyla listelenir, `elle doğrulanacak` (388-400) | savunulabilir; kaynak farkı N3 |

Sabitler: 20 ve 15 tasarımdaki sayılar. `ACCEPT_THRESHOLDS` yedi alanıyla `Thresholds()` varsayılanı (`src/tlab/shadow/summary.py:63-69`); test `asdict(Thresholds()) == ACCEPT_THRESHOLDS` ile bağlıyor. Hüküm ve gün durumu yazımları `summary.py:46-56` ile aynı. Uydurulmuş ölçüt yok; yedi satır altı ölçütün açılımı (4. ölçüt ikiye bölünmüş). BELİRSİZ ve KALDI `sağlanmadı`: tasarımın "KALDI ya da BELİRSİZ: paper'a geçilmez" paragrafıyla uyumlu.

Üç kenar durum yeni politika değil, betik insana bırakılmış bir kararı almıyor:
- **Gevşetilmiş eşik.** "(`Thresholds` varsayılanı)" ve "eşik değiştirilmez" cümlelerinin doğrudan okuması. Tek özet tek eşik kümesi taşıdığı için üç satıra birden uygulanması tutarlı. Daha sıkı eşikli özet de `sağlanmadı` görünür; yön temkinli, kanıt hücresi sebebi yazıyor.
- **20 günlük olmayan plan.** Betik 15/20'yi orantılamıyor, sebebi yazıyor. Bu ve önceki durum gerçek kampanyada tetiklenmez: toplam işi `Thresholds()` ile hesaplar (`shadow_job.py:996`), plan 20 seans (`shadow_job.py:79`).
- **`baslamadi` / `bilinmiyor`.** `shadow_job.py:926-935` eşlemesine göre kayıt işinin koştuğu gösterilemeyen günler bunlar; `eksik` günlerin hepsinde özet ya da atlanmamış bir koşu var. Açıklamanın yeterliliği insana bırakılmış.

## Sahibin gözüyle okuma (yalnız sentetik veri, test yardımcılarıyla üretildi)

> **Paper kabul ölçütleri (karar değildir).** Bu tablo karar değildir. Sonuç görülmeden önce yazılmış kabul ölçütlerini (`docs/designs/unattended-paper.md`, bölüm 1) bu özetten mekanik olarak okur; eşikler tasarımdan gelir, burada değiştirilmez ve genel bir hüküm verilmez. "elle doğrulanacak" satırlarını betik bilemez; onlara #17 kayıtlarından bir kişi bakar. Paper kararı #17'de ayrıca verilir. Gölge gözlem emir göndermez; emirlerin nasıl işlediği ilk paper günlerinde ayrıca gözlenir.

Temiz kampanya (20/20 `tamam`, üç ölçü GEÇTİ):

| Ölçüt | Durum | Kanıt |
|---|---|---|
| Ücretsiz canlı veri açılış penceresini tam veriyor mu? (`iex_window_initial`) | sağlandı | sonuç GEÇTİ; gereken GEÇTİ |
| Açılış aralığı SIP referans verisiyle aynı çıkıyor mu? (`range_within_bps`) | sağlandı | sonuç GEÇTİ; gereken GEÇTİ |
| Strateji iki veriyle aynı kararı veriyor mu? (`intent_agreement`) | sağlandı | sonuç GEÇTİ; gereken GEÇTİ |
| Gün kapsaması: en az 15 / 20 gün tamam | sağlandı | tamam 20 / planlı 20; gereken en az 15 / 20 |
| Tamam olmayan günlerin sebebi kayıtta ve sistematik değil | elle doğrulanacak | tamam olmayan gün 0; sebepler gün tablosunda, sistematik olup olmadığını betik bilemez |
| İlk gün denetimi: sistematik hata yok, durdurma kararı verilmemiş | elle doğrulanacak | kaynak #17 kayıtları; betik onları göremez |
| Kayıt işi: koşusuz planlı gün yok ya da sebebi açıklanmış | sağlandı | koşusuz gün yok (başlamadı 0, bilinmiyor 0) |

Sorunlu kampanyada (12 `tamam`, 6 `eksik`, 1 `baslamadi`, 1 `bilinmiyor`; iki ölçü BELİRSİZ) giriş metni aynı kaldı, dört satır değişti: iki ölçü "sağlanmadı | sonuç BELİRSİZ; gereken GEÇTİ"; gün kapsaması "sağlanmadı | tamam 12 / planlı 20; gereken en az 15 / 20"; kayıt işi "elle doğrulanacak | koşusuz ya da koşusu bilinmeyen gün 2: 2026-11-03 (başlamadı), 2026-11-04 (bilinmiyor); açıklaması günlük kayıtlardan doğrulanır".

Genel hüküm cümlesi, toplam satırı, simge ya da kalın vurgu yok; sıra tasarımın sırası. Sorunlu özetle `python -I -S ... --kabul` 0 döndü; yanlış `--campaign` 1 döndü, stdout boş. Fiyat ve hesap değeri yok: yalnız sayım, tarih, durum. Dil sade; açıklanmayan terimler N4'te.

## Mutasyonlar (her biri tek değişiklik; dosya `git checkout` ile geri alındı, çalışma kopyası temiz)

| Mutant | Sonuç |
|---|---|
| M0 (yazarın): `ACCEPT_MIN_COMPLETE` 15 → 14 | yakalandı, 5 test kırmızı |
| M1: `complete = planned_days − eksik` (`baslamadi`/`bilinmiyor` sessizce `tamam`) | **KAÇTI**, 70/70 yeşil; 12 `tamam` + 8 `bilinmiyor` için "sağlandı, tamam 20 / planlı 20" üretiyor |
| M2: kampanya uyuşmazlığı yok sayılır | yakalandı, 5 test |
| M3: eksik gün yokken "sistematik değil" satırı `sağlandı` | yakalandı, 13 test |
| M4: çıkış kodu `sağlanmadı` varsa 2 | yakalandı, 1 test |
| M5: `bilinmiyor` koşusuz gün sayılmaz | yakalandı, 1 test |

## Notlar

- **N1 (birleştirme koşulu, yalnız test).** Sınır testi (440) eksik günleri hep `eksik` yapıyor. Aşağıdaki durum eklenmeli; b4a4b78'de geçtiği, M1'de kırmızı olduğu denendi. `scripts/shadow_report.py` değişmediği sürece bu ek için Kurul'a dönmek gerekmez; yeni test sayısı TESLİM'e yazılır.
  ```python
  @pytest.mark.parametrize(("complete", "durum"), [(15, MET), (14, UNMET)], ids=["15", "14"])
  def test_only_complete_days_count_toward_the_fifteen(complete: int, durum: str, report: ModuleType) -> None:
      rest = PLAN20[complete:]
      summary = campaign(marked=[Day(rest[0], "baslamadi", "gozlem baslamadi")], absent=rest[1:])
      assert summary["days"] == {"tamam": complete, "eksik": 0, "baslamadi": 1, "bilinmiyor": 19 - complete}
      rows = report.acceptance(summary)
      assert rows[COVERAGE]["durum"] == durum
      assert rows[COVERAGE]["kanit"] == f"tamam {complete} / planlı 20; gereken en az 15 / 20"
      assert rows[SYSTEMATIC]["kanit"].startswith(f"tamam olmayan gün {20 - complete};")
  ```
- **N2 (commit mesajı).** Conventional Commits biçimi ve "neden" gövdesi `AGENTS.md` §5'e uygun; iddiaların hepsi doğrulandı. Tek pürüz: "Tasarimin acik birakmadigi ... uc durum" iki türlü okunuyor; PR metninde "tasarımın açıkça yazmadığı üç durum" denmeli. Commit yeniden yazılmasın.
- **N3 (PR açıklamasına).** (i) "Kayıt işi" satırındaki `sağlandı` günlük KAYIT'lardan değil, toplamın `day_list` alanından (koşu geçmişi kanıtı) okunur; insan KAYIT'larla karşılaştırır. (ii) Tasarım "hepsi birlikte gerekir" der; tablo bunu bilerek tekrarlamaz, satır sayarak okunmamalı. (iii) Gerçek koşuda `--campaign <kampanya kimliği>` verilmeli; bayrak isteğe bağlı olduğu için verilmezse kimlik denetlenmez. (iv) Üç kenar durumdan ilk ikisi gerçek kampanyada tetiklenmez (`shadow_job.py:79`, `:996`). (v) Sayılar: 1555 passed, 6 skipped, %90,65; N1 sonrası güncel sayı.
- **N4 (dil, engel değil).** "Kayıt işi", "koşusuz", "betik" ve ters tırnaklı ölçü adları tabloda açıklanmıyor; rapor gövdesi "Eşik (öneri)" derken bu bölüm "eşikler tasarımdan gelir" diyor; son cümle "paper'a geçilirse" koşulunu söylemiyor. Betik metni toplamdan önce donacağı için açıklama TESLİM'de yapılmalı.

**Doğrulanmadı:** tam süit logunun SHA'sı; yazarın diğer iki mutantı (`belirsiz` sağlandı sayılır; eşik denetimi kaldırılır) yeniden üretilmedi; gerçek toplam ve gerçek kampanya kimliği (bilerek görülmedi); raporun sahibe hangi adımla ulaştırılacağı.
