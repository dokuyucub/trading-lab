# Onay Kurulu — A6a: çözülme planı ve takvim

Tarih: 2026-11-26 · İncelenen: `docs/ops/cozulme-plani.md` (191 satır), `docs/ops/takvim.md` (50 satır); dal `claude/ops-cozulme-takvim`, commit yok (taban `main` d77b381).

## Karar: **RET**

Neden takvimdir. Tarihlerin hepsi doğru, sıra iş listesinin bağımlılık sütununu ihlal etmiyor, geri alma komutu doğru. Ama sahip takvimi harfiyen izlerse planlı bir günü ya da bir günün kanıtını kaybedebilir (Y1–Y4). Düzeltmelerin hepsi metindir ve aşağıda yerleriyle, hazır metinle verilmiştir; Yönetim uygular, yeni yazım turu gerekmez. Kurul yalnız takvim tablosuna yeniden bakar. Plan Z8–Z11 işlenince kabul edilebilir durumdadır.

## Kontrol listesi

| # | Madde | Sonuç | Kanıt |
|---|---|---|---|
| 1 | Kaynaklar | sağlandı | 72 `dosya:satır` atfı açılıp okundu (takvim 34, plan 38; takvimin bütün tarih satırları dahil): 70 tam, 2 kısmi. Kimlikle anılan yaklaşık 75 atıf (BL satırları, §6, K kararları, UF, F3, GÜV, ofis kuralları): 2 eksik. "Kaynak yok" çıkan atıf yok. |
| 2 | Tarihler | sağlandı | 14 tarih ve hafta günü, 6 toplama `datetime` ile yeniden hesaplandı; hepsi doğru (2 Kas + 60 = 1 Oca; 1 Ara + 60 = 30 Oca; 13 Eki + 90 = 11 Oca; 2 Ara + 90 = 2 Mar Salı; 24 Ara + 90 = 24 Mar Çarşamba; 20 Oca − 14 = 6 Oca). 30 Kasım 19., 1 Aralık 20. planlı gün. |
| 3 | Bağımlılık tutarlılığı | sağlandı (iki metin kusuruyla) | 35 adımın her biri BL sütunuyla karşılaştırıldı: ihlal yok; denetim tablosunda yanlış satır yok, 35 adımın hepsi var. Kusurlar: O2, O4. |
| 4 | Geri alma | komut sağlandı; "düz geri alma olmayan adım" bildirimi sağlanmadı | Dal + `git revert -m 1` + PR, zorla itme yok; `CONTRIBUTING.md:130-140` ve `AGENTS.md:78,95` ile uyumlu. Eksik: O3. |
| 5 | Sahip güvenliği | **sağlanmadı** | Y1–Y4, O1. |
| 6 | Başkası adına karar | sağlanmadı (küçük) | O5. |
| 7 | Okunabilirlik (takvim) | sağlanmadı | O6. |
| 8 | Kısıtlar | sağlandı | İki dosyada anahtar, token, hesap değeri, fiyat araması boş. Tetikleme yalnız kayıtlı yolla: toplam ayrı #17 kararıyla, gözlem yalnız `SO:604` erken alarmında. Dondurma yolları, bitişi ("son toplam doğrulanınca") ve kaldıranın belirsizliği (§7 karar 2) doğru yazılmış. |
| 9 | "Doğrulanmadı" listeleri | sağlanmadı | D4. |

## Bulgular

**Yüksek (RET nedeni; hepsi takvim)**

- **Y1 — 1 Aralık hücresi planlı günde Actions ayar sayfasına izin veriyor.** "Dünküyle aynı. Koşu bittikten sonra Actions ayarı yapılabilir." Sahip koşunun bittiğini ayırt edemez (kayıt işi 300 dakikaya kadar sürebilir: `shadow-observation.yml:73`; Türkiye saatiyle akşama kalır). BL §6 madde 4'ün ikinci cümlesi ve yönetimin kuralı: 30 Kasım ve 1 Aralık'ta bu sayfaya dokunulmaz. Son planlı günde yanlış bir seçim günü düşürebilir.
- **Y2 — Erken alarm tıklaması yalnız New York ve UTC saatiyle; bakış penceresi alarmdan önce bitiyor.** Satır sahibe 08:00–15:50 (Türkiye) arasında "bir kez" bakmasını söylüyor; alarm en erken 09:05 New York = 17:05 Türkiye'de düşer, son tıklama 17:20'dir (`SO:604`). Harfiyen izleyen sahip alarmı görmez ya da saati yanlış çevirir; gün "eksik" kalır. "Doğrulanmadı" bunu bilerek boş bırakmış; sahibe giden sayfada boş kalamaz.
- **Y3 — "Re-run" yasağı yalnız toplam için yazılmış.** Toplam işi gün özetini yalnız `run_attempt = 1` olan koşudan alır (`SO:460-465`; `src/tlab/shadow_job.py:1358,1647-1650,1700`). Geçmiş bir gözlem koşusunda "Re-run"a basılırsa o günün özeti seçilmez, gün kanıt kuralıyla "eksik" sınıflanır (koddan okundu, gözlenmedi). Genel kural yalnız "silinmez" diyor; BL §6 madde 3'teki "önceki günlerin koşularına dokunmayın" takvime alınmamış. 30 Kasım'da kırmızı bitecek "canary" bu tıklamayı davet eder.
- **Y4 — BL §6 madde 1 ve "Approve and run" uyarısı takvimde talimat olarak yok.** Madde 1 (yabancı PR'ları kapatma) iki planlı günün asıl korumasıdır (BL §6 madde 4 son cümle; GÜV Y1: onay bekleyen tek çatal PR koşusu günü yakar). Takvim onu yalnız kaynak sütununda ve "Doğrulanmadı"da anıyor; madde 2 ve 5'i de "isterse" yapıyor (§6: "bu hafta"). "Approve and run" hiç geçmiyor.

**Orta**

- **O1 (takvim, 2 Aralık).** "Önce #17'ye karar yazılır" edilgen: kimin yazacağı ve sahibin neyi bekleyeceği belli değil. "İkinci kez tıklamaz" yok. "İlk saatleri" saatsiz (New York gece yarısı = Türkiye 08:00).
- **O2 (plan §4).** Ortak koşul (a) "önceki adım birleşmiş" sırayı tam doğrusal yapıyor; hemen alttaki "Serbest sıralar" maddesi ve §7 karar 7 tersini söylüyor. Harfiyen okunursa B2, C2, C3, C7 bütün Koruma v2 zincirini ve K9, K10, K18 kararlarını bekler.
- **O3 (plan §4 geri alma).** (i) Zincir listesi eksik: 7→8, 7→13, 3→20→21→22, 4→22, 3→29→30, 3→31, 3→35, 23/24→25 ve 28, 27→28, 33→34 bağları yok. (ii) Adım 35: `worker.js` dağıtıldıysa geri alma Cloudflare'deki kodu geri almaz; yazılmamış. (iii) Adım 12: göç eklendiyse geri alma olmadığı açık yazılmamış, yalnız "dosya düzenlenmez" deniyor. (iv) `git revert`in journal satırlarını ve karar kayıtlarını geri almadığı yok.
- **O4 (plan §4 "Sıra dışı").** "D2'nin ön koşulu adım 5–10 ve D11" eksik: BL D2 satırı ayrıca K1–K3, #63, B1–B3, C4, C7, D1 ister.
- **O5 (karar sahipliği).** Plan §7 madde 6'da karar veren yalnız "Yönetim", madde 8'de "Yönetim + Onay Kurulu"; 5–13'te kayıt yeri yazılı değil. Madde 8 ayrıca bayat: B1 kapsamı yönetimin ek şartıyla genişledi (`kararlar.md`, 2026-11-26 B1 satırı). Takvim: "Codex: #66 için ONAY" sonucu önceden yazıyor; 1 Aralık'ta #66 birleştirmesi plan §7 karar 11 açıkken koşulsuz.
- **O6 (okunabilirlik).** "Nasıl okunur" şunları açıklamıyor: Codex, ONAY, dondurma, başlatıcı, canary, UTC ve New York saati. Somut olmayan hücreler: "dünküyle aynı", "yazar" (nereye), "karar verir" (6 Ocak), 1, 11 ve 30 Ocak ile "+90 gün" satırlarında sahibin ne yazacağı. Öneri olup talimat gibi okunan: 24 Aralık hücresi (BL §6 madde 10 ile uyumlu; kalabilir).

**Düşük**

- **D1 (plan §2).** "Kodda kapsam aynıdır" tam değil: parmak izi paketin `.py` dosyalarını sayar (`shadow_job.py:153`), kural `src/tlab/**` der (`SO:612`); kural daha geniş.
- **D2 (plan §7 madde 2).** "Dosyayı Codex indirip açtı" kısmi: `AGENTS.md:729`'da ZIP'i sahip iletti, Codex doğruladı.
- **D3 (plan §7 madde 13).** "UF 10 bunları sona koyar" kısmi: UF 10'da `__version__` sondan öncedir; en sonda Dependabot kilidi ve alpaca-py 0.45 var. Plan C8'i öne alarak UF 10'dan ayrılıyor ama yazmıyor (BL üstündür; sorun değil).
- **D4 ("Doğrulanmadı" eksikleri).** Takvim: erken alarm görevinin 30 Kasım ve 1 Aralık'ta çalışacağı; bugünkü "eksik" gün sayısı; 30 Ocak'taki çıkarım. Plan: adım 20–35 dosya çakışmalarının yalnız BL dosya listelerine dayandığı; Yönetim'in birleştirme yetkisinin dayanağı.
- **D5 (takvim).** "1 Ocak'a bir hafta kalır": 8 gün. 6 Ocak hücresinde "işlem toplam doğrulandıktan sonra" notu yok (genel kural kapsıyor).

## Yazarın bildirdiği sapmalar

- **C0, #63'ten önce:** kabul. BL §1 madde 4 ve §3 ("birleşmeleri toplam ve C0'dan sonradır") ile aynı; sütunla çelişmez.
- **C8, B4'ten önce:** sapma değil; BL B4 bağımlılığı "B0, C8".
- **B2, B1'den sonra:** kabul, açıkça yazılmış. Kurul yerel git ile doğruladı: B1 dalı (2d714ee, #63 başı 8f855cc üstünde) sekiz dosyaya dokunuyor, `cli.py` ve `tests/test_cli_run.py` dahil. Ancak B1 bugün RET aldı; B2'nin B1'i beklemesi zorunlu olmamalı (N2).
- **A8, A7, A5a, C1 PR'sız ön koşul:** kabul; §3'te ve adım 4, 15, 29, 25 satırlarında açık ön koşul olarak işaretli.

## Zorunlu değişiklikler

**`docs/ops/takvim.md`**

- **Z1 — satır 7, "Genel kural" paragrafı, tamamı:** `**Genel kural (toplam doğrulanana kadar):** hiçbir anahtar silinmez ya da yenilenmez; hiçbir Actions koşusu ve hiçbir dosya silinmez; hiçbir koşuda "Re-run" düğmesine basılmaz (yeniden çalıştırılan gözlem koşusunun günü toplamda sayılmaz); yabancı bir PR'da "Approve and run" düğmesine basılmaz; bu sayfada yazmayan hiçbir "Run workflow" tıklaması yapılmaz. Emin olunmayan her şey önce sorulur (BL §6 genel kural ve madde 3; `SO:460-465`; `src/tlab/shadow_job.py:1358`).`
- **Z2 — "2026-11-26 – 2026-11-27" satırı.** "Kimden ne beklenir": `**Sahip:** (1) Henüz yapmadıysa bugün yabancıların PR ve yorum açmasını kapatır: Settings → Moderation options → Interaction limits → "Limit to repository collaborators", en uzun süre; açık yabancı PR varsa kapatır (BL §6 madde 1). Yaptıysa aynı sayfada bitişin 2 Aralık'tan sonra olduğuna bakar; değilse aynı ayarı en uzun süreyle yeniden seçer. (2) Bu hafta: gizli anahtar taraması (madde 2) ve `main` kilidi (madde 5), BL §6'daki adımlarla aynen. (3) Actions ayarı (madde 4) yalnız bu iki günde; o sayfada başka hiçbir seçenek değiştirilmez. Her birinden sonra Yönetim'e yazar.` "Yapılmazsa ne olur": `Madde 1 kapalı değilse 30 Kasım ya da 1 Aralık sabahı açılan tek yabancı PR o günün kaydını boşa çıkarabilir. Actions ayarı bu iki güne yetişmezse 30 Kasım ve 1 Aralık'ta **yapılmaz**; en erken 2 Aralık'a kalır.` "Kaynak" hücresine eklenir: `BL §6 madde 1; GÜV Y1`.
- **Z3 — "2026-11-30" satırı, "Kimden ne beklenir":** `**Sahip:** (1) Actions ayar sayfasına dokunmaz. (2) Türkiye saatiyle 08:00–15:50 arasında bir kez Actions → "Shadow observation" listesine bakar; o sabah oluşmuş bir koşu varsa **silmeden ve hiçbir düğmeye basmadan** Yönetim'e yazar. (3) Türkiye saatiyle 17:05–17:20 arasında #17'ye bakar. O güne ait "BULGU — erken alarm" yazısı varsa en geç 17:20'ye kadar (New York 09:20, 14:20 UTC) bir kez: Actions → Shadow observation → Run workflow → dal `main` → Run workflow. Alarm yoksa hiçbir şeye tıklamaz; 17:20 geçtiyse tıklamaz, yazar. **Codex:** #66'yı inceler (ONAY ya da BULGU).`
- **Z4 — "2026-12-01" satırı, "Kimden ne beklenir":** 30 Kasım hücresinin (1)–(3) maddeleri atıfla değil metin olarak aynen yazılır; ardından: `Bugün de Actions ayar sayfasına **dokunmaz**; koşu bitmiş görünse bile. **Yönetim:** #66'ya ONAY gelirse birleştirir (gözlem saatlerinde birleştirme: çözülme planı §7 karar 11).`
- **Z5 — "2026-12-02" satırı.** "Kimden ne beklenir": `**Sahip:** (1) Toplam için günü seçer ve yazar (BL K4). (2) #17'de toplam için karar kaydının yazıldığını Yönetim bildirmeden tıklamaz. (3) Bildirimden sonra, Türkiye saatiyle 2 Aralık 08:00'den önce olmamak üzere **bir kez**: Actions → Shadow aggregate → Run workflow → dal `main` → Run workflow. (4) Sonuç yeşil de kırmızı da olsa ikinci kez tıklamaz, "Re-run"a basmaz; yazar. (5) Actions ayarı (BL §6 madde 4) 26–27 Kasım'da yapılmadıysa en erken bugün, Yönetim "1 Aralık koşusu bitti" yazdıktan sonra; o sayfada başka seçenek değiştirilmez.` "Yapılmazsa ne olur" içinde `Türkiye'de 2 Aralık'ın ilk saatleri New York'ta hâlâ 1 Aralık'tır.` → `Türkiye saatiyle 2 Aralık 08:00'e kadar New York'ta hâlâ 1 Aralık'tır.`
- **Z6 — satır 5, "Nasıl okunur" sonuna eklenir:** `"Codex" diğer geliştirici ajandır; "ONAY" onun bir değişikliğe verdiği yazılı onaydır. "Dondurma": kampanya bitene kadar bot kodunun `main`'e girmemesi. "Başlatıcı": gözlemi her sabah başlatan, Cloudflare'de duran küçük program. "Canary": gözlemle ilgisi olmayan haftalık deneme koşusu. Saatler: Türkiye = UTC + 3; New York (30 Kasım–2 Aralık) = UTC − 5, yani Türkiye'den 8 saat geri. "Yazar": bu oturumda Yönetim'e ya da #17'ye yazar.`
- **Z7 — "Doğrulanmadı".** 2. madde yerine: `Türkiye saati çevrimleri depodaki bir kaynağa değil, BL §6 madde 3 ile GÜV Y1'in aynı pencereyi iki saatle vermesine (Türkiye 08:00–15:50 = New York gece yarısı–12:50 UTC) ve `.github/workflows/shadow-observation.yml:14-15`'e dayanır.` Eklenir: `Erken alarm görevinin 30 Kasım ve 1 Aralık'ta çalışacağı doğrulanmadı (`SO:603`); alarm gelmezse sahip tıklamaz, durumu Codex ya da Yönetim Actions sayfasından okur (`SO:606`).` ve `Bugüne kadarki "eksik" gün sayısı okunmadı; "iki kayıp gün" cümlesi BL §6 madde 1'dendir. 30 Ocak satırındaki "kurulamaz" çıkarımdır.`

**`docs/ops/cozulme-plani.md`**

- **Z8 — §4, "Her adımın ortak ön koşulu", (a):** `(a) satırın "Ön koşul" sütununda yazan adımlar birleşmiş ve `main`'in son commit'inde `quality` yeşil (sıra numarası tek başına bağ değildir; bkz. "Serbest sıralar")`.
- **Z9 — §4 geri alma.** Satır 67'de "sim 6→17→19." cümlesinden sonra eklenir: `Zincir dışı bağlar da aynı kurala girer: 7→8 ve 7→13; 3→20→21→22 ve 4→22; 3→29→30; 3→31; 3→35; 23 ve 24→25 ve 28; 27→28; 33→34. `git revert` yalnız depodaki dosyaları geri alır: journal'a yazılmış satırları, uygulanmış göçü, dağıtılmış Worker'ı ve #17 ile `AGENTS.md`'deki karar kayıtlarını geri almaz.` Adım 12 "Geri alma": `` `git revert -m 1 <M12>` yalnız göç eklenmediyse. Göç eklendiyse geri alma yoktur: uygulanmış göç dosyası düzenlenmez ve silinmez (`AGENTS.md:376`); düzeltme yeni göçle, ileri yönde. `` Adım 35 "Geri alma": `` `git revert -m 1 <M35>`. `worker.js` değişip dağıtıldıysa bu yetmez: Cloudflare'deki kod ancak sahibin yeniden dağıtımıyla eski haline döner (ayrı #17 kararı: `infra/shadow-starter/README.md:67`); o zamana kadar "dağıtılan kod = depo" tutmaz (BL İtiraz 8). ``
- **Z10 — §4, "Sıra dışı" maddesi, ikinci cümle:** `D2'nin ön koşulları: K1–K3; adım 2, 3, 4 ve 20 (#63, B1–B3), 25 (C4), 26 (C7) ve D1 (BL D2 satırı); ayrıca adım 5–10 ve D11 (BL Z6 notu).`
- **Z11 — §7.** Başlığın altına: `Her kararın kaydı #17'dir. Yönetim hiçbirini tek başına kesinleştirmez: önerir; kararı satırda adı geçen sahip ya da Codex verir.` Madde 2 son cümle: `Önceki iki ölçümde ZIP'i Codex doğruladı; ilkinde dosyayı sahip iletti (`AGENTS.md:729,823`).` Madde 6 sonu: `**Codex** (Yönetim önerir).` Madde 8, tamamı: `B1 dalı iş listesindeki iki dosyadan geniş (§5): kapsam Yönetim'in ek şartıyla genişledi (`docs/office/kararlar.md`, 2026-11-26 B1 satırı). BL B1 ve B2 satırlarını Yönetim günceller; yeni kapsam Codex'in SHA'ya bağlı incelemesine girer.`

## Öneriler (zorunlu değil)

- **N1.** Geri alma bloğunda `git switch -c claude/geri-al-adim-<n> --no-track origin/main`: dal `origin/main`'i izlemez, parametresiz bir `git push` yanlışlıkla `main`'i hedefleyemez (`main` kilidinin açık olduğu bilinmiyor).
- **N2.** §4 "Serbest sıralar"a: `Adım 3 ile 20 yer değiştirebilir: hangisi önce ONAY alırsa o birleşir, diğeri `main`'i alır.` B1 bugün RET aldı; B2 onu beklemesin.
- **N3.** §3'e bir satır: sıraya girmeyen "şimdi" işleri (A4, A4b, A5b, A5c, A6b, A10, C5) ve bağları (A5c → A1; A4 → A6a; A10 → A4; A6b → K15; C5 → C1).
- **N4.** D1–D3 ve D5 düzeltilir; takvimde 1, 11, 30 Ocak ve "+90 gün" hücrelerine `Sahip "saklansın" ya da "saklanmasın" diye yazar` eklenir.

## Doğrulanmadı

- GitHub tarafı okunmadı (ağ yok): PR'ların taslak, ONAY ve CI durumu; `main` kuralı; Interaction limits ayarı ve bitişi; #17 kayıtları. #64–#68'in içeriği okunmadı.
- Geri alma komutları çalıştırılmadı; doğruluk git davranışına ve `CONTRIBUTING.md:136-140`'a dayanır.
- Y3 koddan ve tasarımdan okundu; GitHub'da "Re-run"ın koşu kaydını nasıl değiştirdiği gözlenmedi.
- Türkiye saati (UTC + 3) sistemin saat dilimi verisinden ve BL §6 madde 3 ile GÜV Y1'in örtüşmesinden hesaplandı; depoda kaynağı yok.
- `make check` ve `tests/test_architecture.py` koşulmadı (ortamda pytest yok); yeni dosyalar izlenmeyen dosyadır, anahtar tarayıcının onları gördüğü doğrulanmadı. Kurul kendi desen aramasını yaptı: sonuç boş.
- Adım 4–35'in dalları yok; dosya çakışmaları BL dosya listelerinden ve yerel B1 ile #63 dallarından denetlendi.
- Yönetim'in `main`'e birleştirme yetkisinin dayandığı sahip talimatı okunmadı.
