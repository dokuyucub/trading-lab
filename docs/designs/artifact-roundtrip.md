# Artefakt gidiş-dönüş doğrulaması

Karar: #17 (Claude ön raporu 6050368670) ve #39 (Codex kabulü 6050448316).
Kod: `.github/workflows/artifact-roundtrip.yml`,
`scripts/artifact_roundtrip/verify.py`.

## Neden

Gerçek veri workflow'larının tek dış çıktısı bir JSON artefaktıdır. CI'ın
`quality` kapısı hosted upload/download yolunu çalıştırmaz. Bu yüzden
`actions/upload-artifact` yükseltmesinin (#39) kanıtı, gerçek bir Alpaca
koşusu olamaz. Kanıt, secret'sız ve sentetik bir gidiş-dönüş olmalıdır.

## Ne yapar

1. **Yükleme işi:** depodaki sabit `payload.json`, gerçek veri
   workflow'larıyla **aynı sürüm** ve **aynı girdi anahtarlarıyla**
   (`name`, `path`, `if-no-files-found`, `retention-days`) yüklenir. Tek
   fark saklama süresi: 1 gün.
2. **Doğrulama işi:** `verify.py` aşağıdaki zinciri doğrular.

| Halka | Denetim |
|---|---|
| API listesi | Beklenen adla tek artefakt; kimlik upload çıktısıyla aynı; süresi dolmamış |
| Digest | API `digest` = upload adımının `artifact-digest` çıktısı |
| ZIP | İndirilen baytların SHA256'sı = digest; boyut API'yle aynı; CRC temiz |
| Üye | Tek üye, adı `artifact-roundtrip.json` |
| İçerik | Üyenin SHA256'sı = `EXPECTED_PAYLOAD_SHA256` sabiti; JSON geçerli |

Beklenen içerik hash'i **bağımsız bir sabittir**: yüklenen dosyadan yeniden
hesaplanmaz. Bir test, depodaki `payload.json`'un bu sabite eşit olduğunu
denetler.

## Güvenlik sınırları

- **Secret yok, gerçek veri yok, Alpaca yok.** Tetikleyici `pull_request`
  (yalnızca workflow ya da bu doğrulamanın dosyaları değişince) ve elle.
  `pull_request_target` kullanılmaz.
- **İzinler:** workflow düzeyinde `contents: read`. Yalnızca doğrulama işi
  ek olarak `actions: read` alır. `GITHUB_TOKEN` yalnızca doğrulama
  adımının ortamındadır; komut satırına yazılmaz.
- **Token yalnızca GitHub API'sine gider.** ZIP adresine yönlendirme elle
  izlenir ve o isteğe `Authorization` başlığı eklenmez. Python'un yerleşik
  yönlendirme izleyicisi başlıkları yeni host'a taşırdı.
- **Tek yönlendirme.** Hiçbir istek yönlendirmeyi kendiliğinden izlemez.
  İndirme host'u yeniden yönlendirirse ikinci adres okunmaz, istenmez ve
  basılmaz; şeması https olsa bile. Hata sabit:
  `FAIL indirme: ikinci yonlendirme reddedildi (HTTP <kod>)` (Codex P2,
  #41). Bu yüzden yeşil bir hosted koşu, o koşudaki indirme yolunda en
  fazla bir yönlendirme olduğunu da gösterir: ikinci bir hop sessizce
  izlenmez, kırmızı olur.
- **Yönlendirme adresi, token, yanıt gövdesi ve istisna metni basılmaz.**
  Çıktı sabit satırlardır; hata yalnızca kategori ve HTTP kodu.
- **Adres şeması:** yalnızca https; yerel test sunucusu için loopback http.
  Bu denetim, izlenen tek yönlendirme için istekten önce yapılır.

## Sözleşme testleri

- **Upload sözleşmesi (`tests/test_architecture.py`):** depodaki bütün
  upload adımları aynı sürümde ve aynı girdi kümesinde. Saklama süreleri
  mevcut değerleriyle sabit: pilot 30, üç gerçek rapor 90, sentetik 1.
  Bir yükseltme kullanımlardan birini atlarsa kırmızı olur.
- **Workflow sözleşmesi:** tetikleyiciler, izinler, token'ın tek adımda
  olması, `persist-credentials: false` ve secret yokluğu.
- **Doğrulayıcı testleri (`tests/test_artifact_roundtrip.py`):** iki yerel
  sahte sunucu (API ve indirme host'u). Zincirin her halkası bozulunca
  kırmızı. Token indirme host'una gitmez; token ve imzalı adres hiçbir
  çıktıda yok.
- **Bağlantı koruması:** testler doğrulayıcının denediği her TCP
  bağlantısını kaydeder. İki test sunucusunun tam adres-port çifti
  dışındaki her hedef, bağlanılmadan durdurulur. "Loopback'e izin" yetmez:
  vekil sunucu da loopback'te olabilir. Güvensiz ilk adres ve ikinci
  yönlendirme bu düzeyde sınanır.

## Sürüm: v7 (bakım PR-2)

Beş upload kullanımı da `actions/upload-artifact@v7`. Beklenen sürüm
`tests/test_architecture.py` içinde açıkça sabit (`UPLOAD_VERSION`).
Yükseltme ancak o satırın bilinçli değişikliğiyle ve gidiş-dönüşün hosted
koşusuyla olur.

Kaynak kanıtı, `actions/upload-artifact` salt okunur klonundan (2026-10-08):

| Etiket | Commit | Sürüm | Çalışma ortamı | `@actions/artifact` | Modül |
|---|---|---|---|---|---|
| v4 | `ea165f8d65b6e75b540449e92b4886f43607fa02` | 4.6.2 | node20 | ^2.3.2 | CommonJS |
| v7 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | 7.0.2 | node24 | ^6.3.1 | ESM |

- **v7'de yeni girdi `archive`, `default: 'true'`.** Bizim upload'lar bu
  girdiyi kullanmıyor; zip davranışı varsayılanla korunuyor. Sözleşme
  testi `archive` eklenirse kırmızı olur.
- **Diğer girdiler ve çıktılar v4 ile aynı.** Çıktılar `artifact-id`,
  `artifact-url` ve `artifact-digest`.
- **Etiketler kayan.** `v7` bugün 7.0.2'yi gösteriyor. Depo konvansiyonu
  ana etiket; commit SHA'sıyla sabitleme ayrı bir karar.
- **Okunamayan (Claude, 2026-10-08):** kesilmemiş sürüm notları. Releases
  API bu oturumda 403 verdi; README releases sayfasına yönlendiriyor. Ara
  sürümlerin davranış notları kaynaktan çıkarıldı, belgeden değil.
- **Ek inceleme (Codex, #44 ONAY [6067227404](https://github.com/dokuyucub/trading-lab/pull/44#issuecomment-6067227404)):**
  resmî sürüm notları okundu.
  - v7.0.0: doğrudan tek dosya seçeneği ve ESM.
  - v6.0.0: Node24; runner en az 2.327.1. Hosted 2.337.0 karşılıyor.
  - v7.0.2: 429/Retry-After iyileştirmesi; `@actions/artifact` 6.3.1.

  Yukarıdaki sınır o oturumun sınırı olarak kalır.

## Kanıtın sınırı

Hosted koşu yalnızca upload/download yolunu ve dosya biçimini kanıtlar.
Gerçek veri workflow'larının secret'larla koşmasını kanıtlamaz; onlara
dokunulmaz. Sürüm yükseltmesi ayrı bir PR'dır ve o PR'daki hosted
gidiş-dönüş geçmeden onay yoktur.
