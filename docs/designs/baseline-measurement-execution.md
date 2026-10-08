# Ana baseline ölçümü: yürütme sözleşmesi

Tarih: 2026-09-28. Koordinasyon: #17 (Claude ön raporu, Codex kararı ve
yedi düzeltme). Bu belge yürütme tasarımıdır. Kod, workflow veya gerçek
ölçüm teslim edildiği anlamına gelmez; `approved` kararı ve gerçek koşu
için de onay değildir.

## Kapsam

`orb-baseline-2026q3-u11` üzerinde ORB'nin ilk gerçek veri ölçümü. Yeni motor
yok. Zincir, bugün yerelde çalışan zincirin aynısı:

`build_dataset` → `verify_baseline(dir, manifest_sha256)` → `run_baseline` →
`report_bytes`

Pilot workflow'u değişmez; ana ölçüme, ona P&L eklenerek geçilmez.

## Sıra

| Adım | İçerik | Onay |
|---|---|---|
| (a) | Holdout taahhüdü + rapor şeması v2 + testler; bu belge | Kod PR'ı, bağımsız inceleme |
| (b) | Ayrı giriş modülü, workflow, sözleşme ve sızıntı testleri, süre ölçümü | Kod PR'ı, bağımsız inceleme |
| (c) | Sentetik veriyle uçtan uca kanıt | Bağımsız inceleme |
| (d) | Ana tanımı `approved` yapan ayrı commit; karar kaydı AGENTS §11.1 | Ayrı Codex kararı |
| (e) | Kullanıcıdan tek tık, tek gerçek koşu | (d)'den sonra |

## Sabitler (workflow girdi almaz)

- Tanım: kodda sabit yol, `config/datasets/orb-baseline-2026q3-u11.yaml`.
  *2026-10-08 notu:* bu IEX tanımı kalite nedeniyle kapatıldı ve aktif
  tanımlardan çıkarıldı. Aktif tanım SIP tanımıdır,
  `config/datasets/orb-baseline-2026q3-u11-sip.yaml`: taslak olarak geldi
  (AGENTS §11.4), ayrı inceleme ve kararla onaylandı (§11.5). Dondurulan
  kimlikler §11.5'te. Yürütme sözleşmesi aynıdır; gerçek koşu ayrı ve
  kayıtlı bir karardır.
- Ayarlar: repodaki `config/base.yaml` + `universe.yaml`. Rapor semantik
  ayarları ve hash'ini taşır; yerel yollar hariç.
- Strateji: `ORBParams()` varsayılanları.
- Maliyet: `DEFAULT_SCENARIOS`; temel senaryo `temel`. Hepsi raporda yazılı.
- Başlangıç özsermayesi: **sentetik** 100 000, raporda böyle etiketli.
  Hesap özsermayesi hiçbir adımda okunmaz. Hesap uç noktası yasağı testle
  sabitlenir.

## İki adım, tek job

**Adım A: indirme.** Secret'lar yalnızca bu adımın ortamında bulunur.

1. Tanımın `status == "approved"` olduğu, anahtar okumadan, SDK kurmadan
   ve dizin oluşturmadan **önce** denetlenir. `require_downloadable` yalnızca
   `draft`'ı reddeder; pilot indirmesine bilerek izin verir. Bu genel
   davranış değiştirilmez; ana job'un kendi kapısı ayrıdır.
2. `build_dataset`, ardından manifest hash'i sahip olunan geçici dizindeki
   bir dosyaya yazılır.
3. A holdout dosyalarını diske yazar; manifest onları hash'ler. **Holdout
   okuma yasağı A için değil, B içindir.**
4. A'nın yetkisi holdout'u indirmek ve manifestlemek; holdout'un kalite
   sonucunu dışarı açmak değil (Codex, #33 P2). A'nın log'unda holdout
   için yalnızca seans sayısı yer alır. Uygunsuz sayısı ya da başka bir
   kalite ölçüsü basılmaz. Bu sonuç manifestte kalır ve temizlikte silinir.
   Regresyon testi, yalnızca holdout kalitesi farklı iki veri setinde,
   opak hash'ler dışında log'ların ve raporun birebir aynı olduğunu
   denetler.

**Adım B: ölçüm.** Secret yok, SDK çağrısı yok.

1. Beklenen hash dosyası güvenli tek okumayla okunur: link ve hardlink
   reddedilir.
2. `verify_baseline`, ardından `run_baseline`.
3. B holdout dosyalarını listelemez, açmaz, hash'lemez (mevcut kod +
   denetim kancası testleri).
4. Testte B'de herhangi bir ağ çağrısı testi düşürür.

**B için işletim sistemi düzeyinde ağ izolasyonu uygulanmıyorsa "ağ
yalıtımı" iddia edilmez.** Secret'ın ortamda bulunmaması tek başına ağ
izolasyonu değildir.

**Hash bağının sınırı.** Hash ve manifest aynı güvenilen job içinde üretilir.
Bu bağ, yalnızca manifest değişirse uyuşmazlığı yakalar. İkisi birlikte
değiştirilirse yakalamaz; kriptografik özgünlük diye sunulmaz. Sağlayıcının
doğru veriyi verdiğini de göstermez.

## Geçersiz koşu

Garanti şudur: **geçersiz bir koşuda tamamlanmış bir performans raporu
yazılmaz ve yayımlanmaz.** "Her hata P&L hesaplanmadan yakalanır" iddiası
yoktur.

- P&L hesabından önce durduranlar:
  - tanım `approved` değil;
  - politika/strateji tutarsızlığı;
  - uygunsuz baseline seansı (`measurable_sessions`).
- Simülasyon sırasında durduran: seans sınırında açık pozisyon
  (`CarriedPositionError`). O ana kadar hesaplanan sonuç yazılmaz.
- Başarısız komut nonzero döner; işi kırmızı yapan budur. Başarısız adımdan
  sonra normal upload zaten atlanır. `if-no-files-found: error` ek bir
  güvencedir, asıl mekanizma değildir.
- Rapor yalnızca tam başarıdan sonra ve atomik olarak yazılır. Eski ya da
  kısmi bir rapor dosyası geçerli çıktı olarak kalamaz. `continue-on-error`
  yok.
- Hata tanısı sabit bir kategoridir. Sağlayıcı mesajı, traceback,
  gün/sembol listesi basılmaz. Kalite hatasında yalnızca uygunsuz baseline
  seans **sayısı** basılır.

## Geçici dosyalar

- Geçici dizin, hash dosyası ve rapor yolu için sahiplik ve çakışma denetimi
  yapılır (#27 dersi). Kullanıcıya ait eski bir dizine dokunulmaz.
- Temizlik `if: always()` ile çalışır ve silindiği doğrulanır. Mümkünse
  upload, başarılı temizlikten **sonra** yapılır. Böylece temizlik hatasına
  rağmen yayımlanmış bir başarı görüntüsü oluşmaz.
- Temizlik, fiziksel olarak geri getirilemez silme garantisi değildir.

## Dışarı çıkan tek şey

`run_baseline` raporu. Alan kümesi testle sabittir: üst düzey, iç içe
config, senaryo, kanıt ve uyarılar. Sızıntı testleri başarı ve hata
yollarında stdout, stderr ve logging'i yakalar. Ham bar, manifest ve veri
dizini yüklenmez.

**Log (PR b ile eklendi):**

- Her iki adım boyunca `logging` tamamen kapatılır ve çıkışta eski
  haline döner. Neden:
  - Oturum yürütücüsü (`tlab.runner`) her işlemi fiyat ve P&L ile INFO
    düzeyinde, günlük zarar kesicisini yüzdesiyle WARNING düzeyinde
    loglar. Bu loglayıcının `NullHandler`'ı yok: WARNING kaydı, log
    yapılandırması olmasa da stderr'e düşer.
  - urllib3 istek adresini (tarih ve sembol) DEBUG düzeyinde, bozuk
    yanıt başlığında WARNING düzeyinde kaydeder. Kendi `NullHandler`'ı
    olduğu için bunlar ancak log yapılandırılırsa görünür.
  - Varsayılan log düzeyine ya da yapılandırmanın yokluğuna güvenmek
    yapısal bir güvence değildir.
- *Düzeltme (2026-09-29, #17):* bu maddenin ilk hâli "urllib3 yeniden
  denemeleri istek adresini WARNING düzeyinde loglar" diyordu. Mevcut
  yapılandırmada urllib3 düzeyinde yeniden deneme yok (requests
  varsayılanı 0), o uyarı oluşmaz. Kapatma kararı değişmedi.
- Log'a yalnızca aracın kendi sabit satırları gider: sayımlar, hash
  önekleri ve hata kategorileri. **Performans sayısı log'a basılmaz**;
  sonuç yalnızca rapor artefaktındadır.

## Holdout taahhüdü (rapor şeması v2)

Manifest dışarı çıkmadığı için holdout'un içerik hash'leri koşu bitince
kaybolurdu. Rapor tek bir taahhüt taşır:

```
"holdout": {"sessions": <sayı>, "opened": false,
            "commitment": {"version": "tlab/holdout-commitment/v1", "sha256": "<digest>"}}
```

Digest, şu yükün kanonik JSON'unun SHA256'sıdır:

- sürüm/domain etiketi;
- `dataset_id` ve `spec_sha256`;
- holdout seanslarının sıralı listesi;
- her holdout girdisi için sıralı `(split, symbol, path, bars, content_sha256)`.

Tarih ve girdi listesi raporda **yer almaz**.

- **Dosya hash'i değil, semantik `content_sha256` kullanılır:** Parquet
  yazıcısı değişince aynı içerik başka dosya baytı üretebilir.
- **Taahhüt saf bir fonksiyondur:** doğrulanmış manifest belleğinden üretilir,
  holdout dosyası açılmaz ve listelenmez.
- **Tutarsız manifest reddedilir:**
  - tekrarlı sembol veya yol; eksik ya da fazla sembol;
  - yanlış bölüm veya yol; bozuk digest;
  - tutarsız seans listesi; `spec` ile uyuşmayan `spec_sha256`.

**İleride holdout açılırken:**

- Yeni indirmenin kendi manifest beyanına güvenilmez. Gerçek holdout
  barlarından semantik hash'ler yeniden hesaplanır ve **bu ilk koşunun**
  saklanmış taahhüdüyle karşılaştırılır.
- Uyuşmazlıkta otomatik olarak yeni taahhüt kabul edilmez. Eskisi yeniden
  denemelerle değiştirilmez.

**Taahhüdün sınırları:** sağlayıcı doğruluğunu kanıtlamaz. Aynı verinin
ileride yeniden temin edilebileceğini de kanıtlamaz. Ham baseline da
silindiği için raporun ileride birebir yeniden üretimi koşulsuz garanti
değildir.

## Ölçüm feed'i (rapor şeması v3)

*2026-10-08:* Codex kararı A (#17 6052081621). Manifest feed'i kaydeder,
ama manifest dışarı çıkmaz. Rapor bu yüzden ölçüm feed'ini ayrıca taşır:

- **`data_feed`:** yalnızca doğrulanmış manifestten. Manifest'in `feed`
  alanı spec'in beyanıyla aynı ve desteklenen bir değer olmalı. Bu denetim
  P&L'den önce yapılır: boş, bilinmeyen ya da tutarsız değer ölçümü tek
  bir backtest kurulmadan durdurur.
- **Config değişmez.** `config.data.feed` ayarlanmış paper/canlı karar
  feed'i olarak ayrı görünür; `config_sha256` aynı anlamı taşır. Bu alan,
  o feed'le çalışan bir oturumun kanıtı değildir.
- **Kalıcı uyarı.** İki feed farklıysa `caveats` listesine sabit metinli
  bir satır eklenir: sonuç ayarlanmış feed'e otomatik taşınmaz (AGENTS
  §11.4). Feed'ler eşitse liste değişmez.
- **Journal.** Her senaryonun backtest koşusu `runs.data_feed` alanına
  manifest feed'ini yazar. Açık değer verilmeyen backtest (ör. `tlab
  backtest`) config'in ayarlanmış feed'ini yazar; bu, önbellekteki
  barların gerçek feed'inin doğrulaması değildir.
- **Log.** Ölçüm adımının mevcut `rapor:` satırına yalnızca
  `feed <x> (ayar <y>)` eklenir; satır sayısı ve biçim sözleşmesi aynı.
  Fiyat, getiri ya da hesap sayısı eklenmez.
- **Eski raporlar.** Daha eski şemada `data_feed` yoktur; hangisi olduğunu
  `report_schema` söyler. Üretim kodunda rapor dosyası okuyan bir tüketici
  yok: CLI ve ölçüm adımı o koşuda ürettikleri raporu basar; testler de
  kendi ürettikleri raporu okur.

## Süre (PR b)

- 11 sembol ve hedef takvim büyüklüğünde sentetik veriyle dört senaryo
  ölçülür. Veri yalnızca sinyalsiz olmaz: emir, pozisyon ve journal yolunu
  gerçekten kullanan deterministik bir senaryo da bulunur.
- Raporlanacaklar:
  - bar, seans ve işlem sayısı;
  - süre;
  - ortam;
  - mümkünse tepe bellek.
- Yerel süre, hosted runner için üst sınır değildir. Timeout'ta pay bırakılır;
  hazırlık, ölçüm ve temizlik toplam bütçeye dahildir.
- Bu bir benchmark'tır; strateji başarısının kanıtı değildir.
