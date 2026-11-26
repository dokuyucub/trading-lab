# S1 — Onay Kurulu: B0 "Koruma denetimi v2" tasarım notu

Tarih: 2026-11-26. İncelenen: `docs/designs/protection-check-v2.md` (387 satır, commit yok; dal `claude/koruma-v2-tasarim`) ve
`raporlar/S1-b0-on-rapor-taslagi.md` (57 satır). Kod: `wt-fix` @ `8f855cc`. Salt okuma; test, ağ ve broker yok; iki belge değiştirilmedi.

## Karar: RET

İskelet sağlam: on soru yanıtlı, atıflar hatasız, aşamalar ayrık, sahip adına karar yok. Codex'e gitmeden önce dokuz metin düzeltmesi
gerekir (Z1–Z9); yeni tasarım turu gerekmez. Gerekçe: (1) uygulanan 12. satır ve B9, `held` bacak görüldükçe kapatmayı süresiz
erteleyebilir (fail-open); (2) uygulanan 9. satır `held` iddiası DOĞRUYKEN korunan pozisyonu kapatabilir; (3) tablo tam değil, B8 ile #63 iz yolu çelişiyor.

## Kontrol listesi

| No | Madde | Sonuç | Kanıt |
|---|---|---|---|
| 1 | Backlog B0 kabulü | sağlandı | T1'in on sorusu §3.1–3.10'da gerekçeli; B4–B10 için dosya, kabul testi, davranış işareti §6'da; "ölç ve logla" (B7a) ile "uygula" (B7b) ayrık |
| 2 | Atıflar | sağlandı | 86 atıf `8f855cc`'de okundu, 86 isabet (runner 47, bağdaştırıcı 9, testler 9, diğer 21). İki gevşek aralık: `runner.py:1080-1082` (pozisyon okuması `:1082`), `alpaca_stub.py:118-154` |
| 3 | Alpaca iddiaları | sağlanmadı (kısmen) | 21 iddia ALP ile karşılaştırıldı, 20'sinde etiket aynı; S6 etiketsiz (İKİNCİL). Doğrulanmamış üç bilgiye uygulanan karar bağlı: B1, B2 |
| 4 | Doğruluk tablosu | sağlanmadı | B1–B4 |
| 5 | #63 iz yolu | sağlanmadı | Sıra iddiası doğru (`:367` yalnız gün kapanınca döner: `runner.py:685-693`); sahiplik çelişkili: B5 |
| 6 | Aşamalar | sağlanmadı (kısmen) | Dört aşamada giriş, çıkış, geri alma var; "davranış aynı" yazıldığı gibi tutmuyor: B6 |
| 7 | Kısıtlar | sağlandı | §8 "bu belge karar vermez", 9 karar listeli; fiyat ve hesap bilgisi yok; aşama 0 dondurma + C0'a bağlı; `unattended-paper.md` diff'i yok; kod Codex yanıtına bağlı. Eksik: §3.7(5) karar listesinde değil (Z2) |
| 8 | Backlog sapmaları | sağlanmadı (kısmen) | 10 sapma açık ve gerekçeli; üç sessiz sapma: B7 |
| 9 | ÖN RAPOR taslağı | sağlanmadı (kısmen) | 57 satır, yasak hitap yok; iki yanlış ifade, eksik bir karar sorusu: B7 |
| 10 | "Doğrulanmadı" (§9) | sağlanmadı (kısmen) | Gövdedeki dört madde §9'da yok: B7 |

## Bulgular (önem sırasıyla) ve zorunlu değişiklikler

**B1 — YÜKSEK, fail-open: `held` bacak kapatmayı süresiz engelleyebilir (12. satır, B9).** "Sembolü kapat" terminal olmayan bacak
varken önce `cancel_open_orders(symbol)` çağırıyor; bu çağrı düz `status=open` listesinden yürür (`alpaca_broker.py:268-278`) ve
ALP §2'ye göre (İKİNCİL) `held` bacağı görmez. 12. satır bacakları "`held` dahil" kabul ediyor; ALP §3 iptal sonrası bacak durumunu
DOĞRULANMADI bırakıyor. `held` kalırsa iptal sıfır emir bulur, kapatma hiç gitmez. §3.7(1) aynı sembolü kill-switch ve gün sonu
kapanışında da engeller, (5) sınır koymaz; bugünkü kod bu durumda kapatmayı gönderir (`runner.py:1087`). Pozisyon geceye kalır.
- **Z1 — §4 "Sembolü kapat" notu şununla değişsin:** "(1) L'de sembolde çıkış yönlü, `stop_price` taşımayan, B'de olmayan ve
  pozisyonu kapsayan emir bekleyen kapatmadır: iptal edilmez, yenisi gönderilmez. (2) L'de başka terminal olmayan emir varsa
  `cancel_open_orders(symbol)`; kapatma sonraki tura kalır. (3) Terminal olmayan bacak yalnız B'de görünüyorsa (`held`), bacak
  `cancel_order(kimlik)` ile iptal edilir (`broker.py:97`). (4) Hiçbiri yoksa `close_position(symbol)`."
- **Z2 — §8'e karar 10; §5 aşama 2 girişi "karar 3–5 ve 10":** "Kill-switch, gün sonu kapanışı ve sembol kapatma, terminal olmayan
  (`held` dahil) bacak görülen sembolde süresiz mi bekler (§3.7 önerisi), yoksa T dakika sonra kapatma yine de denenir mi (miktar
  emre bağlıysa Alpaca 403 verir: ALP §5). Bugünkü kod gönderiyor (`runner.py:1087`). Kim: Codex + sahip."

**B2 — YÜKSEK, fail-closed: 9. satır `held` iddiası doğruyken korunan pozisyonu kapatabilir.** (a) Bayat ebeveyn: §3.1 adayı
"kimlik taşıyan en son giriş satırı" diye seçiyor. Yanıtı kaybolup hemen dolan girişin satırı kimliksiz kalır ve `lost` olur
(`runner.py:502-520`; ALP K8, notta işe bağlanmamış). Sembol daha önce işlem gördüyse aday eski, `filled`, bacakları terminal
ebeveyndir: 9. satır canlı hedefi iptal edip pozisyonu kapatır (iki bacak listedeyse 1. satır kurtarır; ALP görünümünde kurtarmaz).
(b) Boş `legs`: dolumdan sonra iç içe okumanın bacak döndürdüğü notun kendi "doğrulanmadı"sı; SDK varsayılanı `None`
(`trading/models.py:241`). Boş gelirse ALP görünümünde her dolan pozisyon "bacak yok" diye kapanır; §3.3 "üçü de birincil kaynaklı"
ve risk 1 "aşama 0–2 etkilenmez" fazla güçlü. (c) Ters yönlü pozisyon: ebeveyn ve stop `filled` → 8. satır, hep yalnız not (fail-open).
- **Z3 — §3.1 "Öneri" son cümlesi ve §4 "Terimler":** "Aday ebeveyn ancak şu üçü birlikteyse 'biliniyor' sayılır, yoksa
  `bilinmiyor`dur ve B boş kabul edilir: (a) sembolde ondan yeni, kimliksiz giriş satırı (`submitting`, `lost`) yok; (b) adayın yönü
  pozisyonun yönüyle aynı; (c) L'de sembolde duran terminal olmayan her emir aday, B'deki bir bacak ya da bekleyen kapatmadır."
- **Z4 — §4 tablo, 9. satır bölünsün, 8. satırdan `filled` çıksın:** "9a: stop `canceled`/`expired`/`rejected`/`filled`, hedef
  terminal ya da yok, L'de sembolde emir yok → `korunmuyor`, aşama 2'de kapat. 9b: `legs == ()` → `belirsiz`, ERROR notu, eylem
  yok; ALP gözlem 1 kayda geçince 9a gibi." §7'ye üçüncü görünüm `alpaca-nolegs` (beklenen `belirsiz`); §3.3 ve risk 1 yumuşasın.

**B3 — ORTA: tablo tam değil; K çift sayabilir.** Hiçbir satıra uymayanlar: ebeveyn `partially_filled` + bacaklar `held`/`held` dışı;
ebeveyn terminal, dolum 0, pozisyon var (S4'ün kendisi); ebeveyn `pending_cancel` + dolum > 0; stop terminal + hedef `held`/geçiş;
ebeveyn bilinmiyor + L'de canlı olmayan stop ya da piyasa emri. K'nin kümesi yazılmamış: stop hem L'de hem B'de görünürse iki kez
sayılır, yarı kapsanan pozisyon `korunuyor` çıkar.
- **Z5 — §4:** (i) 17. satır: "yukarıdakilerin hiçbiri → `belirsiz` (eşleşmedi), ERROR notu, eylem yok". (ii) 11. satırda bacak
  hücreleri "herhangi". (iii) 12. satırda "dolum > 0 ya da pozisyon var". (iv) "Terimler"e: "K, L ∪ B üzerinde kimliğe göre
  tekilleştirilir; `replaced` bacak yok sayılır." (v) §5 aşama 1 çıkışı: her durum birleşimi tam bir satıra düşer (parametreli test).

**B4 — ORTA: tek tur sahte pozitif.** Ebeveyn bilinmiyorken dolum ile hedefin `new` olması arasında L boş görünebilir: 15. satır sağlıklı
bracket'i kapatır; yaş ya da iki tur koruması yok. Doğru eşlenmiş bracket'te 9. satırın geçici hali zararsız (`alpaca_broker.py:249-253`).
- **Z6 — §4 notlarına "Tazelik":** "Bu turda okunan gerçekleşmelerde (`runner.py:415`) sembolde son 2 × `poll` içinde giriş yönlü
  dolum varsa 9a ve 15 uygulanmaz; hüküm `belirsiz` (geçiş). Durum tutmaz."

**B5 — ORTA: B8 ile #63 iz yolu çelişiyor.** §3.5 kalanı "bayat girişle aynı yoldan" iptal ediyor ve "gün kilitlenmez" diyor. O yol
izlenen iptaldir; dolum > 0 ve stop kapsamıyorsa günü kapatır (`runner.py:787-788`, `:732`); §4 de "eylemi iz yolu verir" diyor.
Risk 5 bellekte bir işaret ima ediyor, §3.5 "bellek yok" diyor.
- **Z7 — §4 "İptal izi yolu" ve §3.5'e eklensin, risk 5 silinsin:** "B8 iptali ayrı journal durumuyla yazılır (öneri
  `cancel_requested_partial`; sütun serbest metin, göç yok; `runner.py:662` sorgusuna eklenir). Bu izde `korunmuyor` yalnız sembolü
  kapatır; `belirsiz` ve iletilemeyen iptal günü kapatır." Kabul edilmezse B8 günü kapatır ve bu §6'ya sapma olarak yazılır.

**B6 — ORTA: "davranış aynı" (aşama 0–1) yazıldığı gibi tutmuyor.** B4'te tek bacağın çevrilememesi (`alpaca_broker.py:291-294`)
ebeveyn okumasını düşürür; #63 yolunda devralınan istek günü kapatır (`runner.py:631`). Denetim girişlerden önce koşuyor;
yakalanmayan `JournalError` ya da kapalı borsadaki yeni pozisyon okuması turu öldürür. Bütçe kapalı borsadaki ek isteği saymıyor.
- **Z8 — §7 `AlpacaBroker`, §6 B4 ve B7a kabul testi:** "Bacak çevrilemezse ebeveyn yine döner (`legs=None`, log). Denetim ve
  kapalı borsa okuması her istisnayı kendi içinde yakalar; hata 16. satırdır, turun kalanı aynı kararları verir (istisna türü
  başına test). 'Davranış aynı' gecikmeyi kapsamaz; B2 (zaman aşımı) aşama 1'in ön koşuludur."

**B7 — DÜŞÜK: sessiz sapmalar, §9 eksikleri, taslak.**
- **Z9.** §6'ya üç sapma: B5'ten "'pozisyon yok' eşlemesi koşar" ölçütü düşmüş (risk 4 ona dayanıyor; geri konsun); B9 başlığındaki
  "sahipsiz çıkış `held` bacağı görsün" için kabul testi yok; ALP K8'in runner tarafı hiçbir işte yok. S6'ya "(İKİNCİL)". §9'a
  gövdeden: hedef iptalinin `held` stopu düşürdüğü (§3.7); `replaced` emrin açık listede dönmediği (çıkarım, B6); R63 (c)'nin testsiz
  olduğu (§3.9); kısmi dolum sıklığı (§3.5). Yeni: dolumdan sonra boş `legs`; `held` bacağın kimlikle iptali; "pozisyon yok" metni.
  Taslak: soru 7 tek cümleye insin, yerine Z2 sorusu gelsin; soru 3'te "stop bacağı terminal" → "`canceled`/`expired`/`rejected`";
  madde 4 "paper seans işi B4–B8'den sonra (backlog Z6)"; tablo satır sayısı güncellensin; 60 satırın altında kalsın.

## Notlar (engel değil)

- **N1.** Aşama 3'te 4. satır hedef `partially_filled` iken de `held`i koruma sayıyor; ALP §2'deki karşı kayıt tam bu durum. K9
  sorusuna "yalnız hedef `new` iken" seçeneği eklensin.
- **N2.** `belirsiz` satırların (4–8, 14, 16) tek üst sınırı aynı seansın gün sonu kapanışı ve zarar sınırı; 7. satır INFO düzeyinde,
  yaş sınırı yok (öneri: ebeveynin `filled_at` anından T dakika sonra ERROR). 11 ve 13'ün sınırı 15 dakika (`config/base.yaml:29`) +
  iptal kesinleşmesi; 3 ve 5 aşama 3'e kadar yalnız not.
- **N3.** Bağdaştırıcı `status=all` + `nested` + `limit=500` listesini mutabakat için zaten her tur istiyor
  (`alpaca_broker.py:326-336`). §3.1'in reddettiği seçenek ek istek getirmez; iki itirazı bugünkü mutabakat için de geçerli.
- **N4.** `held` iddiası YANLIŞSA (iki bacak `new` ve listede) aşama 2'de korunan pozisyonu kapatan yol bulunmadı: 1. satır önce uyar.
- **N5.** Kapalı borsadaki pozisyon notu her tur ERROR üretir; sıklığı yazılsın. Z3(c) için `SimBroker` bacak kimlikleri düz listedekilerle aynı olmalı (`sim_broker.py:222-231`).

## Doğrulanmadı

- Hiçbir test ve `make check` koşulmadı (belge işi). Ağa, brokera ve GitHub'a bakılmadı; ALP'nin dış kaynakları açılmadı.
- B1, B2, B4 "yanlışsa güvensiz" çözümlemeleridir; Alpaca'nın gerçek davranışı (iptal sonrası bacak durumu, dolum sonrası `legs`,
  bacak etkinleşme gecikmesi, `held` bacağın kimlikle iptali) gözlenmedi. Z1(3) ve Z6 öneri metnidir.
- YÇ, R63, OK63 atıflarında kimliklerin varlığı ve dört alıntı doğrulandı; her iddianın içeriği tek tek değil.
- `main` ile `8f855cc` farkı karşılaştırılmadı. Z7'deki yeni journal durumunun C7'ye ve mutabakat sorgularına etkisi incelenmedi.
