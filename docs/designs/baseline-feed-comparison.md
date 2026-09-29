# Tarihsel SIP kalite karşılaştırması: tek seferlik, P&L'siz

Karar kaydı: AGENTS §11.3. Tartışma: #17 (Claude ön raporu ve Codex kararı,
2026-09-29). Kod: `src/tlab/feed_comparison.py`.

## Neden

IEX ana ölçüm denemesi kalite kapısında kapatıldı: 50 baseline seansının
10'u uygunsuz, hepsi AMD'de (§7). Bu görev iki soruyu cevaplar:

- (a) bu hesap tarihsel SIP 1Min barı alabiliyor mu;
- (b) SIP verisi aynı kalite politikasını geçiyor mu.

IEX teşhisiyle yan yana konunca, AMD eksiklerinin IEX'e özgü olup olmadığına
dair bir **gözlem** verir, kanıt değil. Yeni bir veri kümesi değildir.

## Görev sözleşmesi

`SIP_TASK` (dondurulmuş, workflow girdi almaz):

| Alan | Değer |
|---|---|
| `comparison_id` | `feedcmp-orb-baseline-2026q3-u11-sip-1` |
| Kaynak | `config/datasets/orb-baseline-2026q3-u11.yaml`, hash `369f4e7f…c027dc505`, `approved` |
| `source_feed` → `feed` | `iex` → `sip` (görev düzeyinde override) |
| Beklenen seanslar | takvim 63, tamamlanmış 63, baseline 50, holdout 13 |
| `reference` | IEX teşhisi `diag-orb-baseline-2026q3-u11-quality-1`, run `36502365666`, artefakt `11004953510`, ZIP SHA256 `5ae3e3e0…7ea98` |

Kaynak hash'i override'ı kapsamaz. Provenance, kaynak hash'i ile görevdeki
override birliktedir. `reference` yalnızca kayıttır: araç o artefakta erişmez.

## Sıra ve kilitler

1. **Kaynak kilidi:** kimlik, hash, `approved` ve tanımdaki feed (`iex`).
   Override kaynak feed'iyle aynıysa da durur. Anahtar okunmadan, SDK
   kurulmadan, çıktı yoluna bakılmadan kontrol edilir.
2. **Çıktı yolu, anahtarlar ve saat.**
3. **İstemciler:** paper broker (takvim) ve `feed=sip` bar istemcisi.
4. **Takvim ve bölme:** mevcut fonksiyonlarla. Sayım kilidi bar isteğinden
   önce kontrol edilir.
5. **Bar:** yalnızca `[ilk baseline açılışı, son baseline kapanışı]`, `sip`,
   `raw`, sembol başına bir istek dizisi. SDK sayfaları izler; her sayfa aynı
   sınırları taşır. Gelen her bar hiçbir hesaptan önce baseline seans
   pencerelerine göre ayrılır.
6. **Kalite:** `assess_quality` ve `quality_summary`, IEX teşhisiyle aynı
   adımlar (`baseline_diagnostic.quality_fields`).

Adım 1–4 ve 6, IEX teşhisiyle ortaktır. Görev kimliği, alan listesi, notlar
ve bar hata satırı her aracın kendisindedir.

## Sonuç ve hata sınıfları

| Durum | Çıktı | Özet |
|---|---|---|
| Bar isteğinde HTTP 401/403 (ilk ya da sonraki sembol, herhangi bir sayfa) | `FAIL erisim: sip tarihsel bar istegi reddedildi (HTTP <kod>), sembol k/n; kesin neden belirlenmedi; baska feed'e donulmedi` | yok |
| 429, 5xx, diğer 4xx | `FAIL indirme: <kategori> (<sınıf>), sembol k/n` | yok |
| Ağ, TLS ya da zaman aşımı | `FAIL indirme: ag, TLS veya zaman asimi hatasi …` | yok |
| SDK yanıtı tipimize çevrilemedi | `FAIL indirme: SDK yanitini bizim tipimize cevirirken hata (DataError) …` | yok |
| Takvim hatası | `FAIL takvim: …`; SIP erişimi hakkında bir şey söylemez | yok |
| 200 ama boş | erişim reddi **değil**; "bar yok" kalite ölçüsü | var |
| Başarılı | `OK karsilastirma …`, `sonuc: all_eligible` ya da `some_ineligible` | var |

- **Kesin neden belirlenmez.** Yanıt metni basılmaz. Başarılı paper takvimi,
  data sunucusundaki bir 403'ün SIP aboneliğinden olduğunu kanıtlamaz.
- **Kısmi sonuç yok.** 11 sembolün hepsi yanıtlanmadan özet yazılmaz. Bir
  sembol ya da sayfa başarısız olursa özet yoktur.
- **Yeniden koşu otomatik değil.** Her başarısızlık önce #17'ye yazılır; her
  yeniden koşu ayrı karardır. §11.1 istisnası bu göreve devredilmez. SDK'nın
  mevcut sınırlı HTTP tekrarı dışında yeni döngü yoktur.

## Dış çıktı

Tek dosya: `baseline-feed-comparison.json`, açık alan listesiyle (testle
sabit). Kalite alanları IEX teşhisiyle aynı ad ve anlamdadır; iki özet yan
yana okunabilir. Yalnızca bu tür için:

- `source`: `dataset_id`, `spec_sha256`, `spec_feed`;
- `feed_override`: `source_feed`, `feed`;
- `reference`: IEX teşhisi kimliği, run, artefakt ve ZIP özeti;
- `access`: `symbols_requested`, `symbols_answered`,
  `symbols_with_baseline_bars`. Yalnızca alınan yanıtları söyler. Hepsi
  boşsa log satırı "kullanilabilir bar DOGRULANMADI" der.

Tarih, fiyat, hacim, istek adresi ya da holdout kalite bilgisi yoktur. Log
kapalıdır (`job_io.silenced`); çıktı yalnızca sabit satırlardır.

## Karşılaştırma

Araçta değil, incelemede yapılır. IEX tarafı §7'de birebir kayıtlıdır ve
artefaktı Codex doğruladı. IEX değerleri üretim koduna taşınmaz. İki gözlem
farklı erişim zamanlarına aittir: eş zamanlı değil, neden kanıtı değil;
sağlayıcı revizyonu mümkündür.

## Kanıtın sınırı

- Yerel testler (stub, sayfalama, CLI smoke) hosted Actions'ı, secret
  enjeksiyonunu, artefakt hizmetini ve bu hesabın gerçek SIP erişimini
  doğrulamaz.
- Tarihsel SIP'in başarısı canlı IEX/SIP eşdeğerliğini, ORB'nin canlıya
  hazırlığını ya da performansı göstermez. Kalite kapsamı işlem, dolum ya
  da P&L anlamı taşımaz.
- Abonelik ya da ücret kararı değildir. Alpaca FAQ'taki "uç en az 15 dakika
  eski" kuralı bu hesap için bu koşuyla ölçülür, önceden varsayılmaz.
