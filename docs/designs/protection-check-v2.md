# Koruma denetimi v2: her turda, girişten bağımsız pozisyon koruması

Durum: **taslak, Codex yanıtı bekleniyor.** Ofis Onay Kurulu ilk incelemede RET verdi (dokuz metin düzeltmesi); revizyon
yeniden incelendi: ONAY (notlarla), 2026-11-26. Yeniden incelemenin yedi notu (Y1–Y7) bu metne işlendi. Bu, Codex
incelemesinin yerine geçmez.
İş: B0 (`docs/office/backlog.md` §2 ve §4 T1). Tarih: 2026-11-26.
Bu belge **kod değiştirmez ve hiçbir yetki vermez**; emir, broker çağrısı ya da paper gözlemi başlatmaz.

Kaynak kısaltmaları (hepsi `docs/office/raporlar/` altında): **ALP** `S1-arastirma-2-alpaca-emir-davranisi.md`,
**YÇ** `S1-hata-avi-1-yurutme-cekirdegi.md`, **R63** `S1-hata-avi-pr63-05df92d.md`, **OK63** `S1-onay-kurulu-pr63-ae39a3b.md`,
**OKB0** `S1-onay-kurulu-b0-koruma-v2.md` (bu notun ilk incelemesi; bulgular B1–B7, notlar N1–N5).
Kod satırları PR #63 başına (`claude/killswitch-fix` @ `8f855cc`) göredir ve bu not için dosyadan okunarak doğrulandı.
Kısa yollar: `runner.py` = `src/tlab/engine/runner.py`; `alpaca_broker.py`, `broker.py` = `src/tlab/execution/`;
`types.py` = `src/tlab/core/types.py`; `sim_broker.py` = `src/tlab/backtest/sim_broker.py`; "§4" = `8f855cc`'deki
`docs/designs/unattended-paper.md` §4; "ALP gözlem N" = ALP'nin "İlk paper günlerinde gözlenecekler" listesinin N. maddesi.
Alpaca iddiaları ALP'nin etiketini taşır: DOĞRULANDI (birincil kaynak), İKİNCİL, DOĞRULANMADI.

## 1. Durum ve kapsam

- **Kapsar:** her açık pozisyon için her turda sorulan "çalışan, yeterli miktarda bir koruma stopu var mı?" denetimi;
  kanıtın okunma yolu; hükmün tanımı; hükme bağlı eylemler; kademeli devreye alma; B4–B10 iş kırılımı.
- **Kapsamaz:** yeni emir türü (bağımsız stop ya da OCO çıkış çifti; K10); `_pending_risk` düzeltmesi (C9b);
  dolum modeli (C10); paper seans işi (D2); `config/*.yaml`; journal göçü; Faz 4. `held` kuralını **açmaz** (K9).
- **Codex yanıtından önce B4–B10'da kod yazılmaz** (backlog §4 T1). B1, B2, B3 ve C8 bu tasarımı beklemez.
- **`unattended-paper.md`'ye dokunmaz:** o dosyayı #63 değiştiriyor (backlog B0 satırı). §4'ün "Bilinen sınırlar"
  (iv), (v), (vi) maddeleri bu tasarımı işaret eder (`unattended-paper.md:415-429`); belge güncellemesi B7–B10 ile gelir.
- Bugünkü kural (#63): koruma yalnız giriş iptali izlenirken ölçülür; kanıt düz açık emir listesindeki stoplardır
  (`runner.py:160-173`, `:849-860`, `:862-896`). v2 bu kuralı kaldırmaz; ona girişten bağımsız bir denetim ekler.

## 2. Sorun

| No | Senaryo | Bugün ne olur | Dayanak |
|---|---|---|---|
| S1 | Giriş iptal sırasında tam dolar; Alpaca stopu `held` tutar ve `status=open` listesi onu döndürmez (İKİNCİL) | `stops_cover` kanıt bulamaz, gün kapanır, korunan pozisyon piyasa emriyle kapatılır | ALP §2, K1; YÇ B6; `runner.py:787`, `:877`, `:896`; `alpaca_broker.py:182-194` |
| S2 | Giriş kısmen dolar; kısmi dolan ebeveynin etkin bacağı yoktur (DOĞRULANDI) | Pozisyonu olan sembolde bayat iptal atlanır; kalan saatlerce bekler, stop aranmaz | ALP §3, K2; YÇ B2; `runner.py:556` |
| S3 | Pozisyon geceye taşınır; emirler `DAY` | Ertesi gün döngü yalnız o sembole giriş açmaz; kapanış penceresine kadar stopsuz kalır. Borsa kapalıyken pozisyon okunmaz | YÇ B3; `types.py:369`; `runner.py:342-344`, `:485` |
| S4 | İptal izi `canceled`/sıfır dolumla kapanır, pozisyon bir sonraki turda görünür | Hiçbir yol ölçmez | R63 N4; §4 sınır (iv) |
| S5 | Önceki seansın girişi okunuyor, sıfır dolumlu, hesap düz, sembolde çıkış emri duruyor | Satır `canceled` yazılır, emir kalır | R63 Gözlem 2; OK63 N3; §4 sınır (v) |
| S6 | Kill-switch: `held` stop açık listede yok (İKİNCİL) | `blocked` kümesine girmez; kapatma, stopun iptali doğrulanmadan gidebilir. Toplu iptal hata verirse o tur hiçbir pozisyon kapatılmaz | YÇ B14; ALP K3; `runner.py:1079-1087`; `alpaca_broker.py:258-266` |
| S7 | Giriş kalıcı olarak okunamaz | Girişler süresiz engellenir ya da her yeni süreç günü kapatır; çıkış elle journal düzeltmesi | R63 O2, R2; §4 sınır (i), (ii) |
| S8 | Yeniden başlatma + kalmış `cancel_requested` + tek geçici okuma hatası | Gün kapanır; stopla kapsanan pozisyon da kapatılır (yön güvenli, bedel gereksiz gün) | OK63 PROBE-A, PROBE-D; §4 sınır (iii); `runner.py:631`, `:642` |
| S9 | Tur başında hesap ya da pozisyon okunamaz | Tur istisnayla biter; kill-switch ve gün sonu kapanışı o turda çalışmaz | R63 (c); `runner.py:346-347` |
| S10 | Stop tetiklenince hedef `replaced` olur (İKİNCİL) | `replaced` terminal sayılmıyor; bacaklar okunmaya başlayınca "sahipsiz çıkış" üretir | ALP K4; `runner.py:71`, `:899-912` |
| S11 | İzlenen giriş dolar ve iki tur arasında kendi bacağıyla kapanır | Pozisyon 0, gereken miktar dolum kadar; "korumasız" sayılıp gün kapanır | YÇ B11; `runner.py:890-896` |
| S12 | Kısmi dolup iptal edilen girişte `filled_at` boş gelebilir (DOĞRULANMADI) | Dolum mutabakata girmez, işlem `trades`'e yazılmaz | ALP K6; YÇ B13; `alpaca_broker.py:361-365` |

Ortak kök: koruma sorusu yalnız iptal izinin içinde ve yalnız düz listeye bakılarak soruluyor. İz yoksa soru sorulmuyor
(S2–S5); liste stopu göstermiyorsa cevap hep "hayır" (S1, S6).

## 3. On soru, on yanıt

Sorular backlog §4 T1 sırasıyladır.

### 3.1 Okuma yolu

- **Öneri (çalışma varsayımı; okuma yolu açık sorudur: aşağıdaki "Tartılan" maddesi ve §8 açık soru 1).** Pozisyon başına
  iç içe ebeveyn okuması. `get_order`'ın imzası (`broker.py:58-64`) değişmez; bağdaştırıcı `nested=True` gönderir ve
  bacakları yeni `OrderRef.legs` alanına taşır (`None` = okunmadı, `()` = okundu ve bacak yok).
  İkinci tanık tur başında zaten okunan düz açık listedir (`runner.py:348`), `limit=500` ile. Protokole yeni yöntem eklenmez.
  Aday ebeveyn journal'dan bulunur: sembolün `broker_order_id` taşıyan en son giriş satırı. Aday ebeveyn ancak şu üçü
  birlikteyse "biliniyor" sayılır, yoksa `bilinmiyor`dur ve B boş kabul edilir: (a) sembolde ondan yeni, kimliksiz giriş
  satırı (`submitting`, `lost`) yok; (b) adayın yönü pozisyonun yönüyle aynı; (c) L'de sembolde duran terminal olmayan her
  emir aday, B'deki bir bacak ya da bekleyen kapatmadır (L, B ve "bekleyen kapatma" §4'te tanımlıdır).
- **Üç koşulun gerekçesi (OKB0 B2).** Yanıtı kaybolup hemen dolan girişin satırı kimliksiz kalır ve süre sonunda `lost`
  olur (`runner.py:502-520`; ALP K8). Sembol daha önce işlem gördüyse "kimlik taşıyan en son satır" eski, `filled`,
  bacakları terminal bir ebeveyndir; koşullar olmadan bu bayat ebeveyn "çıkış bacağı yok" hükmü verir ve `held` iddiası
  doğruyken korunan pozisyonu kapatırdı. (b) ters yönlü pozisyonu eski ebeveyne bağlamayı önler.
- **Gerekçe.** (a) Bacakların ebeveynin altında döndüğü birincil kaynaklıdır (ALP §2: [BELGE] `orders.md:258-261`, [OAS]
  `BracketOrderResponse`; SDK 0.44.0 `trading/requests.py:222-229`, `trading/models.py:241`). Kimlikle okuma,
  `status=open` süzgecinin `held` emirleri dışarıda bıraktığı bilgisine (ALP §2, İKİNCİL) bağlı değildir. (b) Kaynak
  yanlışsa da doğru sonuç verir: stop düz listede `new` görünüyorsa ikinci tanık bugünkü kuralla korumayı kanıtlar.
  (c) İptal yolunda `get_order` zaten çağrılıyor (`runner.py:627`, `:768`); B6 ek istek getirmez.
- **İstek bütçesi.** Açık borsada bugün tur başına 5 işlem API isteği var: saat (`runner.py:324`), hesap (`:346`),
  pozisyon (`:347`), açık emirler (`:468`), gerçekleşmeler (`:415`); journal bugünü bilmiyorsa bir tane daha (`:1033`).
  v2 açık pozisyon başına bir istek ekler; üst sınır `max_concurrent_positions` (`config/base.yaml:36`, 3). 60 saniyelik
  turda (`cli.py:686`) en kötü durum dakikada yaklaşık 9 istek; işlem API sınırı 200 istek/dk (ALP §7, İKİNCİL).
  Kapalı borsada bugün tek istek var (saat; dönüş `runner.py:342-344`); v2 pozisyon okumasını ekler (§3.6). Hız sınırı
  iki okuma yolunu da dışlamıyor; ama aşağıdaki liste seçeneği hiç ek istek getirmez, bu yol pozisyon başına bir tane ekler.
- **Tartılan: tur başına `status=all` + `nested` liste (gerekçe düzeltildi: OKB0 N3).** Bu notun ilk sürümü seçeneği "tek
  istek" diye tartıp reddetti. Düzeltme: bağdaştırıcı bu listeyi (`status=all` + `nested` + `limit=500`) mutabakat için
  zaten her tur istiyor (`alpaca_broker.py:326-336`; çağrı `runner.py:415`); seçenek **ek istek getirmez**. İlk sürümün
  iki itirazı, `limit`'in bacakları sayıp saymadığının doğrulanmamış olması (ALP gözlem 10) ve `after` penceresinin
  (`runner.py:413`) gece taşınan ebeveyni dışarıda bırakması, bugünkü mutabakat için de geçerlidir; seçeneği ayırt etmez.
  Ayırt eden kalan fark: liste runner'a bugün yalnız `Fill` olarak ulaşıyor (`broker.py:66-73`); emir durumlarını taşımak
  protokol yüzeyini değiştirir (yeni yöntem ya da dönüş tipi, dört uygulamada). Karşılığında liste journal'a bağlı
  değildir ve yanıtı kaybolmuş girişi de döndürür; pozisyonun ebeveynini listeden seçme kuralı bu notta tasarlanmadı.
  **Sonuç:** kimlikle okuma önerisi ilk sürümün gerekçesinden artık çıkmıyor. Hangi okuma yolunun seçileceği (kimlikle,
  listeden, ikisi birlikte) Codex'e açık sorudur (§8 açık soru 1). Notun kalanı kimlikle okumaya göre yazılmıştır; liste
  seçilirse B4, B7a ve §7 yeniden yazılır.
- **Reddedilen.** `held`i `PROTECTIVE_STATUSES`e eklemek: liste stopu döndürmediği için tek başına çözmez (ALP Sonuç 2).
- **Doğrulanmadı.** Tam dolumdan sonra tek emir okumasının bacakları güncel durumlarıyla döndürdüğü (birincil örnek yalnız
  dolum öncesini gösterir: ALP §2(i)); bacak dönmezse hüküm 9b'dir (SDK alanının varsayılanı `None`:
  `trading/models.py:241`). Ebeveyni bilinmeyen pozisyonda (journal satırı yok ya da üç koşul tutmuyor) kanıt yalnız düz
  listedir.

### 3.2 Koruma kanıtının tanımı ve `held`

- **Öneri.** Tanım §4 tablosudur. `korunuyor` ⇔ çıkış yönünde, `stop_price` taşıyan, durumu `new`/`partially_filled` olan
  emirlerin kalan miktar toplamı ≥ pozisyon miktarı; emir düz listeden ya da `filled` ebeveynin bacaklarından gelebilir.
  Ebeveyn `filled` ve kardeş hedef `new`/`partially_filled` iken `held` stop **`belirsiz`** sayılır: loglanır, eylem yok
  (K9 varsayılanı). Ebeveyn `filled` değilse `held` hiçbir aşamada koruma değildir (ALP K1(b); ALP §2(ii), §3 DOĞRULANDI).
- **Gerekçe.** `held` stopun tetiklendiğine birincil kaynak yok, karşı kullanıcı kayıtları var (ALP §2, tetiklenme
  DOĞRULANMADI; kayıtlardan biri hedef kısmi dolduktan sonradır: §8 karar 1). Koruma sayarsak sahte güvence; her tur
  denetiminde "korumasız" sayarsak tam dolan her pozisyon kapanır (backlog İtiraz 3). `belirsiz` + log ikisinden de
  kaçınır ve bugünkünden (hiç denetim yok) kötü değildir.
- Bacak rolü alanlardan türetilir: `stop_price` dolu → stop; yalnız `limit_price` → hedef. `group_role` SDK 0.44.0
  modelinde yok (ALP §2 son madde). Her tur denetiminde gereken miktar pozisyon miktarıdır; `max(dolum, pozisyon)`
  (`runner.py:891`) iptal izinde kalır.
- **Reddedilen.** `held`i şimdi koruma saymak (ALP K1(b)'nin tamamı): ALP'nin kendi (c) şıkkı bunu ayrı karara bağlıyor.
- **Doğrulanmadı.** ALP gözlem 1 ve 2.

### 3.3 Aşamalama

- **Öneri.** §5. Paper'dan önce uygulanan küme "canlı stop yok ve yorum gerekmiyor" durumlarıdır: sembolde hiç emir yok;
  stop bacağı `canceled`/`expired`/`rejected` (9a'da `filled` de: pozisyon hâlâ görünüyorsa o stop onu artık kapsamaz);
  ebeveyn tam dolmadan bitti. Üçünün **kuralı** birincil kaynaklıdır (terminal durum tanımı ALP §1; bacakların yalnız tam
  dolumda etkinleşmesi ALP §2(ii), §3). Kuralın okunan veride nasıl göründüğü ise doğrulanmadı ve uygulanan karar buna
  bağlıdır (OKB0 B1, B2): dolumdan sonra iç içe okuma bacak döndürmezse hüküm 9b'dir ve uygulanmaz; iptalden sonra
  bacağın `held` kalıp kalmadığı (ALP §3 DOĞRULANMADI) 12. satırın kapatma adımını belirler (§4 "Sembolü kapat", §8 karar
  10); ebeveyn eşlemesi §4'teki üç koşula bağlıdır. Yalnız loglananlar: `held` + hedef `new` (K9), geçiş durumları, eksik
  miktar, okuma hatası, boş `legs` (9b), tazelik penceresi ve hiçbir satıra uymayan birleşimler (17).
- **Reddedilen.** Tek aşama (İtiraz 3). Eksik miktarı da paper'dan önce uygulamak: pozisyon ve emir okumaları atomik
  değil; hedef kısmi dolunca stop miktarı ayarlanıyor (ALP §3, `orders.md:254-255`); önce log sıklığı görülmeli.

### 3.4 `_pending_risk`

- **Öneri.** Koruma okuması ayrı yoldan; `_pending_risk`'in girdisi (düz liste, `runner.py:1117`, `:1159-1202`) değişmez.
  C9b zincir sonunda kalır.
- **Gerekçe.** Bacaklar `OrderRef.legs` içinde gelir, düz listeye eklenmez. ALP varsayımında listede yalnız hedef görünür
  ve doğru düşülür (YÇ B6 tablosu, `_pending_risk` satırı).
- **Kaynak yanlışsa.** İki bacak da düz listede görünür; `_pending_risk` pozisyon açıkken bütün girişleri veto eder ya da
  maruziyeti çift sayar (YÇ B7; `runner.py:1187-1201`). Bu bugün de böyledir, yön fail-closed'dır; v2 düzeltmez,
  kötüleştirmez. İlk paper gözleminde iki bacak listede görülürse C9b öne alınır.
- **Reddedilen.** C9b'yi öne almak (ölçüm semantiği, K7 bekliyor); bacakları düz listeye açmak (YÇ B7'yi canlıda tetikler).

### 3.5 Kısmi dolum

- **Öneri.** Kalan miktar, girişin brokerdaki `submitted_at` anından `entry_order_ttl_minutes` sonra (`config/base.yaml:29`;
  `runner.py:553`, `:561`) bayat girişteki mekanizmayla iptal edilir: yalnız giriş kimliği, niyet önce journal'a. Yeni ayar
  ve bellek sayacı yok. B8 iptali ayrı journal durumuyla yazılır (öneri: iki durum, `cancel_requested_partial` ve `cancel_pending_partial`; sütun serbest metin, göç yok: `src/tlab/journal/migrations/002_durability.sql:31`. #63'ün iki durumu okuduğu ya da yazdığı her yerde karşılıkları kullanılır: devralma sorgusu ve doğrulanmamış ayrımı `runner.py:662`, `:678`; iptal ulaşınca yazım `:607`, `:710`; mutabakatın ezmeme listesi `:441`). Bu izde `korunmuyor`
  yalnız sembolü kapatır; `belirsiz` ve iletilemeyen iptal günü kapatır. Ayrı durum olmadan iptal #63'ün izlenen iptal
  yoluna düşer; o yol dolum > 0 ve stop kapsamıyorken günü kapatır (`runner.py:787-788`, `:732`; OKB0 B5). Ayrı durum kabul
  edilmezse B8 günü kapatır ve bu §6'ya sapma olarak yazılır (§6 sapma 14). İptal kesinleşince bacaklar yeniden okunur;
  canlı stop pozisyonu kapsamıyorsa **yalnız o sembol** kapatılır, gün kilitlenmez (K10 varsayılanı). Süre dolana kadar
  her tur ERROR notu düşer. `filled_at` boşsa mutabakat B5'te `updated_at`/`canceled_at`'e düşer (YÇ B13).
- **Gerekçe.** Süre `submitted_at`'ten türediği için yeniden başlatma uzatamaz (sayaç itirazı: `runner.py:100-102`).
  Kalan miktar limit fiyatında, piyasa ile stop arasında bekler; düzenli bir ters hareket önce onu doldurur ve bacaklar
  etkinleşir (YÇ B2 "hafifleten yapı"). Açık kalan boşluk ve işlem durdurma riski bugünkü yaklaşık 6 saatten süre
  sınırına iner. Sembol düzeyi tepki mümkündür, çünkü her tur denetimi kapatmayı her tur yeniden dener; #63'te günün
  kapatılmasının gerekçesi bu yeniden denemenin yokluğuydu (`runner.py:930-932`).
- **Reddedilen.** (a) İlk görüldüğü turda iptal: en kısa korumasız süre, ama paper'da uygun emirlerin %10'u rastgele
  boyutta kısmi dolar ve kalan yeniden değerlendirilir (ALP §6 DOĞRULANDI); gözlenen her kısmi dolum zorunlu kapanışa
  döner. Codex'e soru. (b) Bağımsız OCO çifti: yeni emir türü (K10). (c) Günü kapatmak: B8 kabul ölçütüyle çelişir.
- **Doğrulanmadı.** Kısmi dolum + iptalden sonra bacakların gösterdiği durum ve miktar, `filled_at` (ALP §3; gözlem 3);
  paper'da kısmi dolum sıklığı (gözlem 7).

### 3.6 Gece taşınan pozisyon

- **Öneri.** Ayrı kural yok: denetim borsa açıkken ilk turda aynı tabloyu uygular. Gece taşınan pozisyon 9a ya da 15.
  satıra düşer (iç içe okuma bacak döndürmez ve L'de emir varsa 9b: `belirsiz`, kapatılmaz; bacak dönmez ve L boşsa 15); kapanış penceresi beklenmeden o sembol
  kapatılır ve ayrı metinli ERROR notu düşer. **Gün durdurulmaz.**
  Borsa kapalıyken pozisyonlar okunur; açık pozisyon varsa yalnız ERROR notu yazılır, emir gönderilmez.
- **Kapalı borsa notunun sıklığı (OKB0 N5).** Yazıldığı haliyle not, pozisyon açık kaldıkça kapalı borsadaki her turda
  yeniden düşer. Öneri: iki seans arasındaki kapalı dönem başına bir kez ERROR, sonraki turlarda yalnız log. Bunun için
  süreç belleğinde tek bir işaret gerekir (yeniden başlatma notu bir kez daha üretir); denetimin "durum tutmaz" ilkesinin
  tek istisnası olur. Bu not karar vermez (§8 karar 12).
- **Gerekçe.** Riski taşıyan pozisyondur; kapatılınca maruziyet biter. Döngü kapalı borsada bugün hiçbir broker yazımı
  yapmıyor (`runner.py:342-344`); v2 bunu değiştirmez. Ayrı not, "ardışık iki günde sistematik hata" durdurma kuralının
  (`unattended-paper.md:435-437`) bu olayı sayabilmesi içindir.
- **Reddedilen.** Günü de durdurmak: tek sembol için bütün günü kilitler; öte yandan dünkü kapanışın başarısız olduğunu
  gösterir, bu yüzden karar listesinde (§8 karar 3). Bağımsız stop göndermek: yeni emir türü. Kapanış penceresini
  beklemek: YÇ B3.
- **Doğrulanmadı.** `DAY` bacakların kapanışta düştüğü (YÇ B3 notu; ALP gözlem 6). Düşmüyorsa 1. ya da 2. satır
  `korunuyor` verir ve pozisyon kapatılmaz; kural iki durumda da tutarlıdır.

### 3.7 `_flatten_all`

- **Öneri.** (1) Engel kümesi iki kaynaktan kurulur: düz liste (bugünkü, `runner.py:1087`) ve ebeveyni bilinen pozisyonda
  terminal olmayan bacağı (`held` dahil) görülen semboller. İç içe okuma yalnız engel **ekler**; okunamazsa bugünkü kural
  geçerlidir. (2) Toplu iptal hata verirse tur terk edilmez (bugün `runner.py:1083-1085`): liste ve pozisyon yine okunur,
  engelsiz semboller kapatılır. (3) 207 gövdesinde 2xx olmayan satırlar bağdaştırıcıda sayılır ve loglanır; runner kararı
  gövdeye değil sonraki okumaya dayanır. (4) 403 `held_for_orders` "iptal kesinleşmedi" diye ayrı notlanır. (5) Tur sınırı
  yok: iptal kesinleşmedikçe her tur yeniden iptal ve not. Bu süresiz bekleme öneridir, karar değildir (§8 karar 10).
- **Bedel (OKB0 B1).** `held` bacak iptalden sonra da terminal görünmezse (ALP §3 ve §5: DOĞRULANMADI) (1) ile (5)
  birlikte o sembolde kapatmayı kill-switch ve gün sonu kapanışında da süresiz erteler; pozisyon geceye kalır (fail-open).
  Bugünkü kod bu durumda kapatmayı gönderir: engel kümesi yalnız düz listeden kurulur (`runner.py:1087`), kapatma `:1096`.
  Sembol düzeyindeki karşılığı §4 "Sembolü kapat" notunun (3). adımıdır.
- **Gerekçe.** Sınır sayacı bellekte durur ve yeniden başlatmayla sıfırlanır; sınır dolunca yapılacak daha güçlü bir eylem
  de yok: bacak canlıyken rakip kapatma ters pozisyon açabilir (`runner.py:1091-1092`), miktar emre bağlıyken Alpaca
  kapatmayı zaten reddeder (ALP §5 DOĞRULANDI). Tek iptal edilemeyen emir toplu iptal ucunu hataya düşürür (ALP §4, K3).
- **Reddedilen.** Belirli tur sonra koşulsuz kapatma. `close_all_positions(cancel_orders=True)` (ALP §5): yeni protokol
  yöntemi ister; `held` bacakları iptal ettiği doğrulanmadı.
- **Doğrulanmadı.** `DELETE /v2/orders` yanıtının `held` bacakları içerdiği (ALP §5); `held` bacağın miktarı kilitleyip 403
  ürettiği; hedef iptalinin `held` stopu fiilen düşürdüğü (kural birincil: ALP §4; gözlem 5).

### 3.8 #63 sınırları

- **Deneme sınırı: göçsüz, satırın yaşından.** `cancel_requested` satırının `updated_at` değeri niyetin yazıldığı andır
  (`src/tlab/journal/writer.py:202-217`; sütun `src/tlab/journal/migrations/001_initial.sql:65`). Doğrulanmamış istek sabit bir süreyi (öneri: 3
  dakika, bugünkü 3 tur × 60 sn'nin karşılığı) aşınca gün kapanır; süre dolmadan okuma hatası ya da başarısız yeniden
  gönderim yalnız giriş engeli üretir. Bellekteki sayaç (`runner.py:269`, `:596`) ve "devralınan istek tek fırsat" kuralı
  (`:631`, `:642`) bu tek kurala iner. Zaman okunamazsa süre dolmuş sayılır. Gerekçe: K18 varsayılanı; bugünkü kural
  süreyi uzatmıyor ama S8 bedelini taşıyor.
- **Kalıcı okunamayan giriş.** B5 "emir yok" yanıtını geçici hatadan ayırır (§4'ün kendi çözüm önerisi,
  `unattended-paper.md:402-403`). Satır ancak dört kanıt birlikteyse kapatılır (`lost`): kimlikle ve `client_order_id` ile
  okuma "yok" döner; giriş önceki seanstandır; güncel okumayla pozisyon yoktur; sembolde terminal olmayan emir yoktur.
- **Sahipsiz çıkış (S5).** Arama, giriş okunup sıfır dolumlu ve önceki seanstan olduğunda da çalışır; tepki bugünküyle
  aynıdır (gün kapanır, hesap genelinde iptal). Sınır (iv) B7 ile kapanır; (vi) gözlem maddesidir.
- **Reddedilen.** Kalıcı sayaç sütunu (göç; K18). Okunamayan girişi yalnız yaşla kapatmak (emir hâlâ canlı olabilir).
- **Doğrulanmadı.** Bilinmeyen kimlikte Alpaca'nın döndürdüğü hata (ALP'de yok); `pending_cancel`in etkin duruma dönüşü
  (§4 sınır (vi); OK63 N5).

### 3.9 Tur başı okuma hatası ve R63 O1

- **Öneri.** Zaman bazlı kapanış denenir. Hesap ya da pozisyon okunamazsa tur istisnayla bitmez, yeni giriş yapılmaz;
  gün journal'da kapalıysa ya da kapanış penceresi geldiyse `_flatten_all` çağrılır (pozisyonu kendi içinde yeniden okur,
  `runner.py:1080-1082`; o da okunamazsa bugünkü gibi sonraki tura kalır). Zarar sınırı hesap olmadan değerlendirilemez.
- **R63 O1 bedeli.** İptal izi yolunda **kabul**, değişmez. Her tur denetimine **taşınmaz**: okuma hatası `belirsiz` + not
  üretir, kapatma üretmez. O1 yalnız izlenen giriş, görünen pozisyon ve aynı turda iki okuma hatası birlikteyken çalışır
  (R63 O1). Aynı kural her pozisyona her tur uygulanırsa tek geçici kesinti korunan bütün pozisyonları tasfiye eder.
- **Reddedilen.** Turu bugünkü gibi bırakmak (R63 (c); koruma adımının hiç çalışmaması YÇ B1 ve B5 ile aynı sınıf).
- **Doğrulanmadı.** R63 (c) kod okumasına dayanır; testi yok.

### 3.10 Sahte brokerlar ve short yön

§7'de. Özet: yeni yöntem yok, yalnız `OrderRef.legs`; `ShadowBroker` değişmez; koruma testleri üç görünüm (ALP
varsayımı doğru / yanlış / doğru ama iç içe okuma bacak döndürmüyor) ve iki yön için parametrelenir.

## 4. Koruma kanıtının tanımı

Terimler. **Çıkış yönü:** long'da `sell`, short'ta `buy`. **Stop bacağı:** `stop_price` taşıyan emir. **Hedef bacağı:** yalnız
`limit_price` taşıyan emir. **Canlı stop:** durumu `PROTECTIVE_STATUSES` içinde (`runner.py:88`). **K:** çıkış yönündeki canlı
stopların `remaining_qty` toplamı (bilinmeyen miktar 0 sayılır, `runner.py:167`). K, L ∪ B üzerinde kimliğe göre
tekilleştirilir; `replaced` bacak K hesabında yok sayılır. **P:** pozisyon miktarı. **L:** sembolün düz
açık listesi. **B:** ebeveynin `legs` alanı. **Bekleyen kapatma:** "Sembolü kapat" notunun (1). adımında tanımlanan emir.

**Ebeveyn.** Aday ebeveyn, sembolün `broker_order_id` taşıyan en son giriş satırıdır (§3.1). Aday ebeveyn ancak şu üçü
birlikteyse "biliniyor" sayılır, yoksa `bilinmiyor`dur ve B boş kabul edilir: (a) sembolde ondan yeni, kimliksiz giriş
satırı (`submitting`, `lost`) yok; (b) adayın yönü pozisyonun yönüyle aynı; (c) L'de sembolde duran terminal olmayan her
emir aday, B'deki bir bacak ya da bekleyen kapatmadır. Aday hiç yoksa ebeveyn yine `bilinmiyor`dur. Aday ya da L
okunamadıysa (c) sınanamaz; hüküm 16. satırdır (aday okunamadı ama L okunduysa önce 1. satır denenir).

**Satır sırası.** Satırlar sırayla denenir; ilk uyan geçerlidir. Hiçbiri uymazsa **17. satır varsayılandır**; böylece her
durum birleşimi tam bir satıra düşer. Tablo 18 satırdır: 1–17, 9. satır 9a ve 9b olarak ikiye bölünmüştür.

| No | Ebeveyn | Stop bacağı | Hedef bacağı | Miktar | Hüküm | Aşama 1 (yalnız log) | Aşama 2 | Aşama 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | herhangi ya da bilinmiyor | L'de canlı stop | — | K ≥ P | `korunuyor` | log | eylem yok | eylem yok |
| 2 | `filled` | B'de `new`/`partially_filled` | herhangi | K ≥ P | `korunuyor` | log | eylem yok | eylem yok |
| 3 | `filled` ya da bilinmiyor | canlı stop var | herhangi | 0 < K < P | `korunmuyor` (eksik miktar) | ERROR notu | ERROR notu, eylem yok | sembolü kapat (§8 karar 6) |
| 4 | `filled` | `held` | `new`/`partially_filled` | bacak miktarı ≥ P | `belirsiz` (K9) | log | log, eylem yok | K9 yanıtına göre: hedef `new` iken `korunuyor`; hedef `partially_filled` iken yalnız K9 kaydı bunu açıkça kapsıyorsa `korunuyor`, yoksa `belirsiz` kalır |
| 5 | `filled` | `held` | `new`/`partially_filled` | bacak miktarı < P | `belirsiz` | ERROR notu | ERROR notu, eylem yok | 3. satır gibi |
| 6 | `filled` | `held` | `held`, geçiş ya da terminal | — | `belirsiz` | ERROR notu | ERROR notu, eylem yok | `korunmuyor`: sembolü kapat |
| 7 | `filled` | `accepted`/`pending_new`/`accepted_for_bidding` | herhangi | — | `belirsiz` (geçiş) | log | log, eylem yok | aynı |
| 8 | `filled` | `pending_cancel`/`pending_replace`/`replaced`/bilinmeyen | herhangi | — | `belirsiz` | ERROR notu | ERROR notu, eylem yok | aynı |
| 9a | `filled` | `canceled`/`expired`/`rejected`/`filled` | terminal ya da yok; L'de sembolde emir yok | — | `korunmuyor` (çıkış bacağı yok) | ERROR notu | **sembolü kapat** | aynı |
| 9b | `filled` | `legs == ()` (bacak dönmedi) ve L'de sembolde emir var | — | — | `belirsiz` (bacak yok) | ERROR notu | ERROR notu, eylem yok; ALP gözlem 1 kayda geçince 9a gibi | aynı |
| 10 | `filled` | `canceled`/`expired`/`rejected` | `new`/`partially_filled` | — | `korunmuyor` (stop bitti, hedef duruyor) | ERROR notu | sembol emirlerini iptal et, kesinleşince kapat | aynı |
| 11 | `partially_filled` (giriş açık) | herhangi | herhangi | — | `korunmuyor` (ebeveyn kısmi) | ERROR notu | süre dolunca kalanı iptal et, sonra 12 | aynı |
| 12 | `canceled`/`expired`/`rejected`, dolum > 0 ya da pozisyon var | herhangi (`held` dahil) | herhangi | — | `korunmuyor` (bacaklar etkinleşmedi) | ERROR notu | sembolü kapat | aynı |
| 13 | etkin, dolum 0 ya da bilinmiyor, ama pozisyon var | — | — | — | 11. satır gibi (dolum bilgisi bayat olabilir) | ERROR notu | 11. satır gibi | aynı |
| 14 | bilinmiyor | L'de stop yok | L'de çıkış yönlü limit emri | — | `belirsiz` (yalnız hedef görünüyor) | ERROR notu | ERROR notu, eylem yok | aynı |
| 15 | bilinmiyor, ya da `filled` ve `legs == ()` | L'de sembolde hiç emir yok | — | — | `korunmuyor` (emir yok) | ERROR notu | **sembolü kapat** | aynı |
| 16 | aday var ama okunamadı (`legs` `None` dahil), ya da L okunamadı | — | — | — | `belirsiz` (okunamadı) | ERROR notu | ERROR notu, eylem yok | aynı |
| 17 | yukarıdakilerin hiçbiri (varsayılan) | — | — | — | `belirsiz` (eşleşmedi) | ERROR notu | ERROR notu, eylem yok | aynı |

Notlar:

- **Long ve short.** Tablo yön-simetriktir; yalnız çıkış yönü değişir. Short'a özgü iki nokta: pozisyon yönü miktarın
  işaretinden gelir (`alpaca_broker.py:98`); Alpaca alış yönlü stopu stop-limit'e çevirebilir (ALP §8; bracket bacağına
  uygulandığı DOĞRULANMADI), o bacak iki fiyatı da taşır ve yine stop sayılır. Stop-limit boşlukta dolmayabilir; short'ta
  `korunuyor` hükmü long'dakinden zayıf bir güvencedir (§8 risk 5).
- **"Sembolü kapat".** Dört adım, sırayla: (1) L'de sembolde çıkış yönlü, `stop_price` taşımayan, B'de olmayan ve
  pozisyonu kapsayan emir bekleyen kapatmadır: iptal edilmez, yenisi gönderilmez. Bekleyen kapatma varsa o tur başka adım
  atılmaz. (2) L'de başka terminal olmayan emir
  varsa `cancel_open_orders(symbol)` (`broker.py:93-95`); kapatma sonraki tura kalır. (3) Terminal olmayan bacak yalnız
  B'de görünüyorsa (`held`), bacak `cancel_order(kimlik)` ile iptal edilir (`broker.py:97`). (4) Hiçbiri yoksa
  `close_position(symbol)`. (2) ve (3)'te kapatma o tur gitmez. (3)'ün gerekçesi (OKB0 B1): `cancel_open_orders(symbol)`
  düz `status=open` listesinden yürür (`alpaca_broker.py:268-278`) ve o liste `held` bacağı döndürmez (ALP §2, İKİNCİL);
  yalnız (2) olsaydı iptal sıfır emir bulur, kapatma hiç gitmezdi. `held` bacağın kimlikle iptal edilebildiği ve iptalden
  sonra terminal göründüğü doğrulanmadı (§9); terminal olmazsa (3) her tur yinelenir ve kapatma yine gitmez: sınır §8
  karar 10'dadır. (1)'in tanımı B'de olmayan bir hedefi ya da elle konmuş limit emrini de kapsar (§8 açık soru 7). Durum
  tutulmaz: her tur hüküm yeniden verilir. Gün kilitlenmez; not ERROR'dır. `dry_run`'da ölçülür ve loglanır, yazım
  yapılmaz (bugünkü desen `runner.py:1072`).
- **Uygulanan satırlar (9a, 10, 12, 15) yalnız L okunmuşsa geçerlidir.** L okunamadıysa hüküm 16. satırdır: elle konmuş bir
  stop dışlanamaz; ebeveynin (c) koşulu da L olmadan sınanamadığı için bu, o turda bütün satırlar için geçerlidir. Bugün
  de liste okunamayan turda yeni giriş yapılmıyor (`runner.py:370-374`).
- **Tazelik.** Bu turda okunan gerçekleşmelerde (`runner.py:415`) sembolde son 2 × `poll` içinde giriş yönlü dolum varsa
  9a ve 15 uygulanmaz; hüküm `belirsiz` (geçiş). Durum tutmaz. Gerekçe (OKB0 B4): dolum ile hedefin `new` görünmesi
  arasında L bir tur boş görünebilir; ebeveyn bilinmiyorken 15. satır sağlıklı bracket'i kapatırdı. `poll` tur aralığıdır
  (`cli.py:686`); pencere genişliği ölçüme dayanmaz. Gerçekleşmeler o turda okunamadıysa (`runner.py:416-418`) 9a ve 15
  uygulanmaz; hüküm `belirsiz` (§3.9 ile aynı yön).
- **Satır 9b.** Tam dolumdan sonra iç içe okumanın bacak döndürdüğü doğrulanmadı (§3.1); SDK alanının varsayılanı
  `None`dır (`trading/models.py:241`). Okuma dolumdan sonra bacak döndürmüyorsa ve `legs == ()` "bacak yok" diye
  uygulansaydı, ALP görünümünde dolan her pozisyon kapanırdı (OKB0 B2); bu yüzden hüküm `belirsiz`tir. ALP gözlem 1
  (dolmuş ebeveynin iç içe okumasında bacakların durumlarıyla döndüğü) kayda geçince 9b, 9a gibi uygulanır.
- **Satır 4–6, aşama 3.** `held` yalnız kardeş hedef çalışırken koruma sayılır (ALP K1(b), İKİNCİL). 4. satırın aşama 3
  hücresi K9 yanıtına bağlıdır: hedef `partially_filled` iken `held`i koruma saymak ALP'nin kendi karşı kaydıyla çelişir
  (ALP §2: tetiklenmeyen `held` bacak raporlarından biri hedef kısmi dolduktan sonradır; OKB0 N1). K9 "yalnız hedef `new`
  iken" derse o durumda hüküm `belirsiz` kalır. K9 kararı farklı bir kural yazarsa bu üç hücre ona göre değişir.
- **Satır 14.** ALP varsayımında korunan bir bracket düz listede tam böyle görünür; ebeveyn bilinmediği için kanıtlanamaz.
  Journal gün içinde yenilendiyse `_unexplained_day` günü zaten kapatır (`runner.py:1014-1043`).
- **Satır 17.** Bilinen örnekleri (OKB0 B3): ebeveyn `pending_cancel` + dolum > 0; stop terminal + hedef `held` ya da
  geçişte; ebeveyn bilinmiyor + L'de canlı olmayan stop ya da piyasa emri. Bekleyen kapatma görülen turda 9a ve 15 uymaz
  (L boş değil); hüküm yine 17. satırdır.
- **Belirsiz satırların üst sınırı (OKB0 N2).** Hiçbir satır kendi başına süre saymaz. Pozisyonun eylemsiz kalabileceği
  süreyi sınırlayanlar, satır grubuna göre:
  - 4–8, 9b, 14, 16, 17: yalnız aynı seansın gün sonu kapanışı ve zarar sınırı (kill-switch). İkisi de `_flatten_all`'dan
    geçer; `held` bacak görülen sembolde o kapatmanın bekleyip beklemeyeceği §8 karar 10'dur.
  - 7. satır ayrıca INFO düzeyindedir ve yaş sınırı yoktur. Öneri: ebeveynin `filled_at` anından T dakika sonra ERROR.
    T burada seçilmedi (§8 karar 11). `OrderRef` bugün `filled_at` taşımıyor (`types.py:569-589`).
  - Tazelik hükmü kendi penceresiyle (2 × `poll`) sınırlıdır; sonra 9a ya da 15 uygulanır.
  - 11 ve 13: `entry_order_ttl_minutes` (15 dakika, `config/base.yaml:29`) + iptalin kesinleşmesi.
  - 3 ve 5: aşama 3'e kadar yalnız not (§8 karar 6).
- **İptal izi yolu (#63).** Aynı tablo okunur; farklar: gereken miktar `max(dolum, pozisyon)`; `belirsiz` ve `korunmuyor`
  bugünkü gibi günü kapatır. Aşama 3'te yalnız 4. satır değişir (K9 yanıtına göre `CancelOutcome.FILLED`). **B8 izi
  ayrıdır:** B8 iptali ayrı journal durumuyla yazılır (öneri: iki durum, `cancel_requested_partial` ve `cancel_pending_partial`; sütun serbest metin, göç yok. #63'ün iki durumu okuduğu ya da yazdığı her yerde karşılıkları kullanılır: devralma sorgusu ve doğrulanmamış ayrımı `runner.py:662`, `:678`; iptal ulaşınca yazım `:607`, `:710`; mutabakatın ezmeme listesi `:441`). Bu izde `korunmuyor` yalnız sembolü kapatır; `belirsiz` ve iletilemeyen iptal günü
  kapatır. Öneri kabul edilmezse B8 iptali #63 izine düşer ve günü kapatır (`runner.py:787-788`, `:732`); bu §6'ya sapma
  olarak yazılır (§6 sapma 14).
- **Sıra.** Denetim `_resolve_pending_cancels`'tan sonra (`runner.py:367`), `open_orders is None` dönüşünden (`:370`) ve
  giriş penceresi dönüşünden (`:381`) önce koşar; böylece giriş penceresi kapandıktan sonra da her tur çalışır. İptal izi
  süren sembolde hüküm loglanır, eylemi iz yolu verir.
- **Log.** Satır: sembol, yön, hüküm, tablo satırı, ebeveyn ve bacak durumları, kapsam (`tam`/`eksik`/`yok`). Fiyat yazılmaz.

## 5. Aşamalar

| Aşama | İşler | Giriş koşulu | Çıkış koşulu | Geri alma |
|---|---|---|---|---|
| 0 — okuma yolu, davranış aynı | B4, B5 | Codex'in bu nota yanıtı kayıtta; C8 tabanda; birleşme için dondurma kalkmış ve C0 birleşmiş (backlog §1 madde 4) | Sözleşme testleri yeşil; `tests/test_entry_cancel_race.py` sonuçları aynı; sentetik baseline raporu bayt-özdeş | PR geri alınır. `legs` varsayılanı `None` ve runner okumuyor; başka iş kırılmaz |
| 1 — her tur ölç ve logla | B6 (bayrak kapalı, davranışsız kısmı), B7a | Aşama 0 zincirde altta; B2 (zaman aşımı) birleşmiş | §4'ün her satırı için hüküm testi (üç görünüm × iki yön); her durum birleşimi tam bir satıra düşer (parametreli test); denetimin ve kapalı borsa okumasının her istisna türünde turun kalanı aynı kararları verir; hiçbir testte yeni broker yazımı yok; baseline bayt-özdeş; log biçimi Codex'çe kabul | PR geri alınır. Denetim bellekte ya da journal'da durum tutmaz; kalıntı bırakmaz |
| 2 — kesin durumları uygula | B6 (test_f11), B7b, B8, B9, B10 | Aşama 1 ONAY'lı; Codex §4 tablosunu ONAY'lamış; K10 kayıtlı; §8 karar 3–5 ve 10 yanıtlı | YÇ test_f2a, test_f2b, test_f12 ve R63 test_r2 kırmızı → yeşil; uygulanan her satır için "kapatmayı kaldır" mutantı kırmızı; baseline farkı varsa kayıtlı karar (backlog Z5) | Her uygulama modül düzeyinde sabit bayrakla kapatılır (tek satırlık PR; `config/*.yaml` ya da ortam değişkeni değil); kapalıyken aşama 1 davranışı. Tam geri alma zincirin ucundan |
| 3 — `held` kuralı | bayrağı açan ayrı iş (backlog kimliği yok) | İlk paper gözlemi kayıtta: ALP gözlem 1 (iç içe okumada stop `held`, hedef `new`) **ve** gözlem 2 (en az bir tetiklenmede `held` stop doldu); K9 kayıtlı karar | Bayrak açık; YÇ test_f13 yeşil; 4. satır K9 yanıtının kapsadığı hedef durumlarında `korunuyor`; 5–6 uygulanıyor | Bayrak kapatılır; kapalıyken aşama 2 davranışı |

- **"Davranış aynı" (aşama 0–1) kararların aynı kalması demektir; gecikmeyi kapsamaz (OKB0 B6).** v2 tur başına pozisyon
  sayısı kadar okuma ekler; B2 (zaman aşımı) bu yüzden aşama 1'in ön koşuludur. Aşama 0'da bacak çevrilemezse ebeveyn yine
  döner (`legs=None`, log): yoksa B4 ile tek bacağın çevrilememesi (`alpaca_broker.py:291-294`) ebeveyn okumasını düşürür
  ve #63 yolunda devralınan istek günü kapatır (`runner.py:631`). Aşama 1'de denetim ve kapalı borsa okuması her istisnayı kendi
  içinde yakalar; hata 16. satırdır, turun kalanı aynı kararları verir (istisna türü başına test).
- Aşama 1 ile 2 arasında paper gözlemi **yoktur**: paper seans işinin ön koşulu B4–B8'dir (backlog Z6). Ayrımın değeri
  inceleme (davranışsız PR ile davranış değiştiren PR ayrı) ve geri alma tanesidir.
- Gözlem ALP varsayımını çürütürse (stop `new` ve listede): aşama 3 açılmaz; 1. ve 2. satır zaten doğru çalışır.
- Gözlem "`held` stop tetiklenmedi" gösterirse bracket'in kendisi koruma sağlamıyor demektir; bu v2'nin değil emir türü
  seçiminin sorunudur ve K10'un OCO seçeneği ayrı tasarımla yeniden açılır.

## 6. İş kırılımı

Dosya ve dal bilgileri backlog §2 ile aynıdır; farklar "Backlog'dan sapma" listesindedir. "Önce kırmızı" yeni testin
değişiklikten önce düştüğünü, "aynı" var olan testlerin sonucunun değişmediğini anlatır.

| İş | Dosyalar | Kabul testi | Davranışı değiştirir mi | Bağımlılık |
|---|---|---|---|---|
| B4 | `broker.py` (yalnız belge dizgisi), `alpaca_broker.py`, `types.py`, `sim_broker.py`, `tests/alpaca_stub.py`, `tests/test_alpaca_contract.py`, `tests/test_protocols.py` | Önce kırmızı: tek emir isteği `nested` taşır; ebeveyn ve iki bacak durumlarıyla `OrderRef.legs`'e gelir; basit emirde `legs == ()`; bacak çevrilemezse ebeveyn yine döner (`legs=None`, log); liste isteği `limit=500` taşır; `SimBroker` dolmuş ebeveynde iki bacak döndürür ve bacak kimlikleri düz listedekilerle aynıdır. Aynı: yarış testleri, baseline | Hayır | B0, C8 |
| B5 | `alpaca_broker.py`, `broker.py`, `src/tlab/errors.py`, `tests/alpaca_stub.py`, `tests/test_alpaca_contract.py` | Önce kırmızı: 207'de 2xx olmayan satır sayılır; `filled_qty > 0` ve boş `filled_at` dolum üretir; 4xx (408/429 hariç) `OrderRejected`; `client_order_id` ile okuma; "emir yok" ve 403 `held_for_orders` ayrı alt sınıf; "pozisyon yok" eşlemesi koşar. Aynı: runner testleri (alt sınıflar `BrokerError`) | Runner kararı: hayır. Mutabakat çıktısı: evet, yalnız boş `filled_at` kayıtlarında | B4 |
| B6 | `runner.py`, `tests/test_entry_cancel_race.py` | Önce kırmızı: koruma kararında bacak durumları loglanır; `replaced` hedef sahipsiz çıkış saymaz; YÇ test_f11. Bayrak kapalı: YÇ test_f13 bugünkü gibi günü kapatır (sabitlenir); bayrak açık: yeşil. Long ve short | Evet: test_f11 (bugün kapanan gün açık kalır). Loglama ve `replaced` bugün etkisiz (`replaced` emir açık listede dönmez; çıkarım, ALP §1) | B0, B3, B5, K9 |
| B7a | `runner.py`, `src/tlab/journal/queries.py`, yeni `tests/test_position_protection.py` | Önce kırmızı: §4'ün her satırında beklenen hüküm ve not (üç görünüm × iki yön); her durum birleşimi tam bir satıra düşer (parametreli); borsa kapalıyken açık pozisyon notu. Denetim ve kapalı borsa okuması her istisnayı kendi içinde yakalar; hata 16. satırdır, turun kalanı aynı kararları verir (istisna türü başına test). Aynı: `closed`, `cancelled`, `cancelled_ids`, `halted` | Hayır (emir yok; tur başına pozisyon sayısı kadar ek okuma ve not var; "davranış aynı" gecikmeyi kapsamaz) | B6; B2 (zaman aşımı) |
| B7b | `runner.py`, `tests/test_position_protection.py`, etkilenen kurulumlar | YÇ test_f2a ve test_f2b kırmızı → yeşil: 9a ve 15. satır o turda kapatılır, ERROR notu düşer, `halted` yanlış. 9b, 17 ve tazelik penceresi kapatmaz; 4. satır yalnız loglanır. "Sembolü kapat"ın dört adımı ayrı testlenir (bekleyen kapatma yinelenmez; yalnız B'de görünen `held` bacak kimlikle iptal edilir) | Evet | B7a; §8 karar 3–5 ve 10 |
| B8 | `runner.py`, `tests/test_entry_cancel_race.py` | YÇ test_f12 kırmızı → yeşil: süre dolunca iptal yalnız giriş kimliğine gider; kesinleşince sembol kapatılır; gün kilitlenmez. 10. ve 12. satır testleri. `cancel_requested_partial` izi: `korunmuyor` yalnız sembolü kapatır; `belirsiz` ve iletilemeyen iptal günü kapatır; akışın ortasındaki yeniden başlatmada da aynı, iki durum da yeniden başlatmada devralınır (sapma 14) | Evet | B7b, K10 |
| B9 | `runner.py`, `tests/test_kill_switch_durability.py` | Önce kırmızı: `held` stop listede yokken kapatma, bacaklar terminal görülmeden gitmez (süresiz mi: §8 karar 10); toplu iptal hata verince engelsiz semboller yine kapatılır; 403 `held_for_orders` ayrı not; tur başında hesap okunamazken kapanış penceresinde kapatma denenir. "Sahipsiz çıkış `held` bacağı görsün" testi yok (sapma 12) | Evet | B8, B5; §8 karar 10 |
| B10 | `runner.py`, `src/tlab/journal/queries.py`, `tests/test_entry_cancel_race.py` | Önce kırmızı: R63 test_r2; OK63 PROBE-A ve PROBE-D dizileri günü kapatmaz; R63 Gözlem 2 dizisinde sahipsiz emir kalmaz. Aynı: yeniden başlatma süreyi uzatmaz (R63 test_r1, N2). B63'ten taşınan `trades` satır sayısı | Evet | B9, K18 |

B6–B9 için Z5 geçerlidir: sentetik baseline önce ve sonra karşılaştırılır. Bu tasarımda fark **beklenmiyor** (`SimBroker`
dolmuş ebeveynde canlı stop bildirir, §7), ama bu bir ölçüm değil beklentidir.

**Backlog'dan sapma**

1. **B7 ikiye bölünmeli** (B7a ölç ve logla; B7b uygula). Backlog satırı aşama 1 ile 2'yi tek işte topluyor.
2. **B7 dosya listesine `src/tlab/journal/queries.py` eklenmeli:** pozisyondan ebeveyne giden sorgu gerekir;
   `open_entry_orders` durum ve gönderim anı döndürmüyor (aynı dosya, `:26-31`).
3. **B4 dosya listesinden `src/tlab/shadow/broker.py` çıkabilir:** protokole yöntem eklenmiyor; `ShadowBroker` pozisyon ve
   emir döndürmüyor (`src/tlab/shadow/broker.py:54-63`).
4. **B5'e iki hata ayrımı eklenmeli:** "emir yok" (B10 için) ve 403 `held_for_orders` (B9 için). B9 ve B10 yalnız runner'a
   dokunuyor; bağdaştırıcı bugün her istisnayı aynı `BrokerError`e çeviriyor (`alpaca_broker.py:198-202`, `:249-255`).
5. **B5 "runner davranışı aynı" doğru ama eksik:** boş `filled_at` düşüşü paper'da `fills` ve `trades` içeriğini
   değiştirir; Z5/K8 notuna eklenmeli.
6. **B6 tümüyle davranışsız değil:** test_f11 düzeltmesi davranış değiştirir ve aşama 2'ye aittir; ayrı commit olmalı.
7. **B10 kabul ölçütü bayat görünüyor:** R63'ün 7db8bea yeniden incelemesine göre test_r1 ve test_b5 zaten yeşil;
   kırmızı kalan test_r2. Önerilen ölçüt tablodadır. Bu not testleri yeniden koşmadı.
8. **R63 (c)'nin ikinci yarısı hiçbir satırda yok** (tur başında hesap ya da pozisyon okunamazsa güvenli kapatma). B9'a
   eklenmesi önerilir: aynı işlev, aynı test dosyası. B1 yalnız journal hatasını kapsıyor.
9. **10. satır B7'nin "hiç çıkış bacağı olmayan" ifadesinden geniştir** (stop bitmiş, hedef duruyor). İptal-sonra-kapat
   mekanizması gerektirdiği için B8'e konuldu.
10. **Aşama 3'ün backlog kimliği yok.** `held` bayrağını açan iş ayrı bir satır olmalı (K9'a bağlı).
11. **B5'in "'pozisyon yok' eşlemesi koşar" ölçütü bu notun ilk sürümünde sessizce düşmüştü; geri kondu** (OKB0 B7).
    §8 risk 4 ona dayanır (`alpaca_broker.py:249-253`, eşleme `:383-386`).
12. **B9 başlığındaki "sahipsiz çıkış `held` bacağı görsün" için kabul testi yok.** `_has_orphan_exit` yalnız düz listeye
    bakar (`runner.py:877`, `:899-912`); bu not o yolu tasarlamadı. Test B9 satırına eklenmeli.
13. **ALP K8'in runner tarafı hiçbir işte yok.** B5 bağdaştırıcıya `client_order_id` ile okumayı ekler; ama
    `_resolve_unconfirmed` yanıtı kaybolan girişi yine yalnız açık listede arar ve giriş dolmuşsa `lost` yazar
    (`runner.py:502-520`). §4'teki (a) koşulu bu satırın yanlış ebeveyne yol açmasını önler, satırı çözmez.
14. **B8'in ayrı journal durumu (koşullu sapma).** `cancel_requested_partial` kabul edilmezse B8 iptali #63 izinden geçer
    ve günü kapatır (`runner.py:787-788`, `:732`); bu, backlog B8 ölçütündeki "gün kilitlenmez"den sapma olur (§3.5, §4).

## 7. Sahte brokerlar ve testler

- **`OrderRef.legs`.** `tuple[OrderRef, ...] | None = None`. Varsayılan `None` olduğu için var olan bütün kurulumlar
  geçerli kalır (`types.py:569-589`). `OrderRef` journal'a bütün olarak yazılmıyor: `confirm_order` yalnız kimlik ve durum
  yazar (`src/tlab/journal/writer.py:194-200`), `Decision.to_row` yalnız `broker_order_id` alır (`types.py:640`).
- **`AlpacaBroker`.** `get_order` `nested` gönderir (bugün göndermiyor, `alpaca_broker.py:199`); `_to_order_ref` bacakları
  `_collect_fills`'teki özyinelemeyle taşır (`:347-356`). `list_open_orders` `limit=500` alır (bugün yok, `:187-189`).
  Bacak çevrilemezse ebeveyn yine döner (`legs=None`, log): `_to_order_ref` zaman damgası bulamayınca `BrokerError` atar
  (`:291-294`) ve tek bacak yüzünden ebeveyn okuması düşmemelidir (OKB0 B6).
- **`SimBroker`.** `get_order` bekleyen girişte iki `held` bacak döndürür (ALP §2(i), DOĞRULANDI); dolmuş girişte yön,
  kalan miktar ve fiyat taşıyan bir stop ve bir hedef, ikisi de `new`; iptal edilmişte `()`. Bugün bacak taşımıyor
  (`sim_broker.py:343-367`). Düz liste değişmez (`:222-231`; o C9a'nın işi). Simülatör kendi defterini söyler: simde stop
  gerçekten bekliyor. Sonuç: backtest'te her pozisyon 2. satıra düşer. Bunun koşulu (OKB0 N5): `get_order`'ın döndürdüğü
  bacak kimlikleri düz listedekilerle aynı olmalıdır. Düz liste bugün dolmuş giriş başına tek `<ebeveyn kimliği>-leg`
  referansı döndürür (`:222-231`); bu kimlik B'de yoksa §4'teki (c) koşulu düşer, ebeveyn `bilinmiyor` sayılır ve
  pozisyon 2. satır yerine 17. satıra düşer.
- **`ShadowBroker`.** Değişmez. Pozisyon listesi boş olduğu için denetim okuma yapmaz; gölge döngüsü `--dry-run` koşar
  (`src/tlab/shadow/broker.py:9-10`).
- **`FakeBroker`.** `get_order` saklanan `OrderRef`i döndürür (`tests/test_runner.py:159-169`); testler `legs`i
  `model_copy` ile kurar. Yeni yardımcı beş görünüm üretir: `alpaca` (ALP varsayımı: düz listede yalnız hedef; ebeveyn
  altında stop `held`, hedef `new`), `visible` (kaynak yanlışsa: iki bacak da `new` ve listede; aynı bacak L'de ve B'de
  aynı kimlikle kurulur, K'nin tekilleştirmesi sınanır), `alpaca-nolegs` (ALP varsayımı doğru ama dolmuş ebeveynin iç içe
  okuması `legs == ()` döndürüyor; beklenen hüküm `belirsiz`, kapatma yok), `partial`, `dead`. Her koruma testi `alpaca`,
  `visible` ve `alpaca-nolegs` görünümünde koşar: "kaynak yanlışsa da güvenli" ve "bacak dönmezse kapatma yok" iddiaları
  testle sabitlenir.
- **HTTP sahtesi.** `tests/alpaca_stub.py` `legs` alanını zaten taşıyor (`:118-154`). Tek emir ucunda `nested` sorgusu
  yakalanıp doğrulanır (desen `tests/test_alpaca_contract.py:224-229`); `status=open` listesi `held` bacağı dışarıda
  bırakan ve bırakmayan iki biçimde sunulur.
- **Protokol testleri.** Yüzey listesi (`tests/test_protocols.py:145-163`) ve imza eşleşmesi (`:118`, `:169-177`) değişmez.
- **Short yön.** Mevcut `legs()` yardımcısı yönü `Side.SELL` sabitliyor (`tests/test_entry_cancel_race.py:184`, `:194`);
  short'u kuran tek test `:1597`. Yeni yardımcı çıkış yönünü `order.side`'dan türetir; tablo testleri iki yönle
  parametrelenir. Short'a özgü iki test: iki fiyat taşıyan stop-limit bacak stop sayılır; negatif miktarlı pozisyonun yönü.
- **Çıplak pozisyon kuran mevcut testler.** B7b ile bir kısmı haklı olarak kırmızıya döner (kurulum satırı sayısı:
  `tests/test_runner.py` 13, `tests/test_entry_cancel_race.py` 34, `tests/test_kill_switch_durability.py` 4; hangilerinin
  etkilendiği sayılmadı). Kural: iddia zayıflatılmaz; kurulum görünür bir stop eklenerek düzeltilir ya da yeni kapanış
  açıkça beklenir. Değişen testlerin listesi TESLİM'e girer.

## 8. Riskler ve açık sorular

**Riskler**

1. **İkincil kaynak.** "Stop `held` kalır ve açık listede görünmez" bilgisi yanlışsa (iki bacak `new` ve listede) aşama
   0–2'nin hükmü 1. ve 2. satırdan doğru çıkar (`visible` görünümü testi) ve aşama 3 açılmaz. Kurulun incelemesi de bu
   durumda aşama 2'nin korunan pozisyonu kapattığı bir yol bulmadı: 1. satır önce uyar (OKB0 N4). Bu, aşama 0–2'nin
   hiçbir doğrulanmamış bilgiye bağlı olmadığı anlamına gelmez; uygulanan kararın bağlı olduğu ayrı varsayımlar var: dolumdan
   sonra iç içe okumanın bacak döndürmesi (9b, `alpaca-nolegs`), iptalden sonra `held` bacağın terminal görünmesi (karar 10)
   ve ebeveyn eşlemesi (§4 "Ebeveyn"). Bilgi doğruysa ama `held` stop tetiklenmiyorsa hiçbir sürüm koruma sağlamaz (§5 son madde).
2. **İstek bütçesi ve hız sınırı.** Normal turda en çok 3 ek istek (§3.1). B8 ve B9'un iki adımlı yolları yalnız istisna
   durumda istek ekler. Sınırın birincil metni ve `X-RateLimit-*` başlıkları görülmedi (ALP §7 İKİNCİL; gözlem 9). 429
   ya da başka okuma hatasında hüküm `belirsiz`tir; kapatma yoktur.
3. **Log gürültüsü.** ALP varsayımında her pozisyon her tur 4. satıra düşer. Bu satır ERROR olursa "ardışık iki günde
   sistematik hata" kuralını kirletir; bu yüzden INFO'dur.
4. **Atomik olmayan okumalar.** Pozisyon, liste ve ebeveyn farklı anlarda okunur. Uygulanan satırlar (9a, 12, 15) bir
   emrin *yokluğuna* değil terminal durumuna ya da sembolde hiç emir olmamasına dayanır. Tur içinde kendi bacağıyla kapanan
   pozisyon 9a'ya düşer (stop `filled` artık 8. satırda değil) ve kapatma çağrısı gider; var olmayan pozisyonu kapatma
   çağrısı zararsızdır (`alpaca_broker.py:249-253`). Bu, B5'in "pozisyon yok" eşlemesi ölçütüne dayanır (§6 sapma 11);
   eşlenen hata metni doğrulanmadı (§9). Dolumun hemen ardındaki tur için ayrıca §4 "Tazelik" kuralı vardır.
5. **Short'ta stop-limit.** Boşlukta dolmayabilir; denetim bunu göremez.
6. **Sembol kapatmasının etiketi.** Piyasa emriyle çıkış journal'da `manual` görünür (YÇ B12; B14 yalnız kill-switch'i
   düzeltir). Öğrenme katmanı koruma kapatmasını elle müdahaleden ayıramaz.
7. **Zincir.** Altı iş aynı dosyada sıralı ilerler ve her biri Codex'in SHA'ya bağlı onayını ister (backlog İtiraz 12).

**Açık sorular (Codex ile)**

1. **Okuma yolu (§3.1).** Kimlikle iç içe okuma mı (bu notun çalışma varsayımı; pozisyon başına bir ek istek, protokol
   değişmez), mutabakatın zaten her tur istediği `status=all` + `nested` listeden mi (ek istek yok; protokol yüzeyi değişir,
   ebeveyni listeden seçme kuralı tasarlanmadı), ikisi birlikte mi? Kimlikle okuma kalırsa ebeveyni bilinmeyen pozisyon
   için 14. ve 15. satır yeterli mi?
2. İptal izi yolunda `belirsiz` günü kapatırken her tur denetiminde yalnız loglanıyor. Bu fark K9'a kadar kalsın mı?
3. B8'de kalan miktarın süresi: mevcut `entry_order_ttl_minutes` mı, ilk görüldüğü turda iptal mi?
4. B7 varken `_halt_unprotected`'ın gün kapatması (`runner.py:921-935`) sembol kapatmaya indirilsin mi? Öneri: v2'de hayır.
5. Aşama 3'te `SimBroker` Alpaca görünümüne (`held` + `new`) çevrilsin mi (backtest ile paper aynı satırı koşsun)?
6. Tazelik kuralı (§4): pencere 2 × `poll` yeterli mi? (Gerçekleşmeler okunamadıysa 9a ve 15 uygulanmaz.)
7. Bekleyen kapatma tanımı (§4 "Sembolü kapat" (1)) B'de olmayan bir hedefi ya da elle konmuş limit emrini de kapsıyor;
   o emir dolmazsa kapatma hiç gitmez. Tanım `limit_price` da taşımayan emre daraltılsın mı?

**Karar gerektirenler** (bu belge karar vermez)

1. **K9:** `held` kuralı hangi kanıtla açılır (kaç gözlenen tetiklenme, kaydı kim tutar) ve hangi hedef durumunu kapsar:
   hedef `new`/`partially_filled` iken mi, **yalnız hedef `new` iken** mi. Aşama 3'te 4. satır hedef `partially_filled`
   iken de `held`i koruma sayarsa ALP'nin kendi karşı kaydıyla çelişir (ALP §2: hedef kısmi dolduktan sonra tetiklenmeyen
   `held` bacak raporu; OKB0 N1); tabloda o hücre bu yanıta bağlıdır. Kim: Codex + sahip.
2. **K10:** kısmi dolumda kalan pozisyon kapatılır mı, bağımsız çıkış çifti mi. Kim: Codex.
3. Gece taşınan pozisyon görülünce yalnız sembol mü kapatılır, gün de durur mu. Kim: Codex + sahip.
4. Hesapta bot dışı (elle açılmış) pozisyon olabilir mi. Aşama 2 emirsiz pozisyonu ilk turda kapatır. Kim: sahip.
5. Koruma kapatması journal'da ayrı etiket alır mı (yeni `ExitReason`; ölçüm semantiği, K8 kapsamı). Kim: Codex.
6. Eksik miktar (3. ve 5. satır) aşama 3'te mi uygulanır, daha erken mi. Kim: Codex.
7. **K18:** B10 göçsüz mü (satır yaşı) yoksa kalıcı sayaç mı. Kim: Codex.
8. **K7:** `SimBroker` bacak görünümü (açık soru 5). Kim: Codex + sahip.
9. İlk paper gözleminin biçimi (tek sembol, en küçük miktar: K3) ve `docs.alpaca.markets` ağ izni (backlog §6 madde 12).
   Kim: sahip.
10. Kill-switch, gün sonu kapanışı ve sembol kapatma, terminal olmayan (`held` dahil) bacak görülen sembolde süresiz mi
    bekler (§3.7 önerisi), yoksa T dakika sonra kapatma yine de denenir mi (miktar emre bağlıysa Alpaca 403 verir: ALP §5).
    Bugünkü kod gönderiyor (engel kümesi yalnız düz listeden: `runner.py:1087`; kapatma `:1096`). Kim: Codex + sahip.
11. 7. satırın yaş sınırı: ebeveynin `filled_at` anından T dakika sonra not ERROR'a yükselsin mi, T kaç (§4 "Belirsiz
    satırların üst sınırı"). Bu not T seçmedi. Kim: Codex + sahip.
12. Kapalı borsadaki pozisyon notu her turda mı düşer, kapalı dönem başına bir kez mi (öneri; §3.6). Kim: Codex.

## 9. Doğrulanmadı

Alpaca davranışı (hiçbiri canlı ya da paper çağrıyla sınanmadı; broker çağrısı yasak):

- Tam dolumdan sonra stopun `held` kaldığı ve `status=open` listesinde dönmediği (ALP §2, İKİNCİL).
- `held` stopun tetiklenip dolduğu (ALP §2, DOĞRULANMADI).
- Tek emir iç içe okumasının tam dolumdan sonra bacakları güncel durumlarıyla döndürdüğü (birincil örnek dolum öncesi).
- Aynı okumanın dolumdan sonra `legs`i boş döndürüp döndürmediği (9b ve `alpaca-nolegs` görünümü bu olasılık içindir;
  ALP gözlem 1).
- `nested` listede `limit`'in bacakları sayıp saymadığı (ALP gözlem 10).
- Kısmi dolum + ebeveyn iptalinden sonra bacakların durumu ve miktarı; o emirde `filled_at` (ALP §3, K6).
- `held` bacağın kimlikle (`cancel_order`) iptal edilebildiği ve iptalden sonra terminal göründüğü (§4 "Sembolü kapat" (3)).
- Hedef iptalinin `held` stopu fiilen düşürdüğü (§3.7; kural birincil: ALP §4; gözlem 5).
- `replaced` emrin açık listede dönmediği (çıkarım, ALP §1; §6 B6 satırı buna dayanır).
- Dolum ile hedef bacağın `new` görünmesi arasındaki gecikme (§4 "Tazelik").
- Pozisyon yokken `close_position`ın döndürdüğü hata metni: eşleme `alpaca_broker.py:383-386`; ALP §5 metni bir örnek
  koddan alır, API yanıtından değil.
- Paper'da kısmi dolumun gözlenen sıklığı (§3.5; ALP gözlem 7).
- `DELETE /v2/orders` yanıtının `held` bacakları içerdiği; `held` bacağın miktarı kilitleyip 403 ürettiği (ALP §5).
- `DAY` bacakların ve kısmi dolmuş girişin seans kapanışındaki son durumu (ALP gözlem 6; YÇ B3 notu).
- `pending_cancel`in etkin duruma dönüp dönmediği (§4 sınır (vi)); bilinmeyen kimlikte dönen hata.
- Alış yönlü stop bacağının stop-limit'e çevrildiği; paper'da stopun kotasyonla mı işlemle mi tetiklendiği (ALP §6, §8).
- İşlem API hız sınırının güncel resmî metni (ALP §7, İKİNCİL).

Kod ve süreç:

- Bu not için hiçbir test koşulmadı. Satır numaraları `8f855cc`'de okunarak doğrulandı; `main` ile fark karşılaştırılmadı.
- Raporlardaki test sonuçları (R63 test_r1 ve test_b5'in yeşil olduğu; YÇ karalama testlerinin kırmızı olduğu) yeniden
  üretilmedi; karalama testleri kalıcı değil (backlog girişi).
- Tur başına istek sayısı kod okumasından sayıldı, ölçülmedi. SDK'nın 429'da tur içinde yeniden deneme yapıp yapmadığına
  bakılmadı.
- "Baseline bayt-özdeş kalır" bir beklentidir. B7b'nin kıracağı mevcut test sayısı bilinmiyor.
- Önerilen 3 dakikalık iptal süresi ve log düzeyleri gerekçeli tahmindir; ölçüme dayanmaz.
- R63 (c) (tur başı okuma hatasında turun istisnayla bitmesi) kod okumasına dayanır; testi yok (§3.9).
- Kurul incelemesinden sonra eklenen kurallar öneri metnidir, hiçbiri sınanmadı; kurul yeniden incelemede yalnız metni okudu:
  ebeveynin üç koşulu, "Sembolü kapat"ın dört adımı, tazelik penceresi (2 × `poll`), 9a/9b ayrımı, 17. satır.
  "Her durum birleşimi tam bir satıra düşer" iddiası tablo okumasına dayanır; parametreli test henüz yok.
- `cancel_requested_partial` ve `cancel_pending_partial` durumlarının C7'ye (yaşam döngüsü denetimi) ve mutabakat
  sorgularına etkisi incelenmedi.
- Liste okuma yolu (§3.1 "Tartılan") tasarlanmadı; iki yolun doğruluk karşılaştırması yapılmadı.
- 7. satırın yaş sınırı için T ve karar 10'daki T seçilmedi. Kapalı borsa notunun "kapalı dönem başına bir kez" önerisi
  bellekte bir işaret gerektirir; ayrıntısı yazılmadı.
- Codex'in ve sahibin bu konulardaki görüşü henüz alınmadı; §8'deki kararların hiçbiri verilmiş değil.
