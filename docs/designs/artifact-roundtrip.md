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
- **Yönlendirme adresi, token, yanıt gövdesi ve istisna metni basılmaz.**
  Çıktı sabit satırlardır; hata yalnızca kategori ve HTTP kodu.
- **Adres şeması:** yalnızca https; yerel test sunucusu için loopback http.
  Bu denetim istekten önce yapılır.

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

## Kanıtın sınırı

Hosted koşu yalnızca upload/download yolunu ve dosya biçimini kanıtlar.
Gerçek veri workflow'larının secret'larla koşmasını kanıtlamaz; onlara
dokunulmaz. Sürüm yükseltmesi ayrı bir PR'dır ve o PR'daki hosted
gidiş-dönüş geçmeden onay yoktur.
