# Research v2: tarihsel seçim önerisi

Durum: **incelemeye açık taslak; uygulanmış API veya ekip kararı değildir.**
Başlangıç: `259abb0` (#13 birleşmesi). Tartışma: #12; koordinasyon: #11.
Codex tip/seçim katmanını geliştirir; Claude Faz 3 tüketicisi olarak inceler.
Mutabakat sonrası kesinleşen kurallar AGENTS.md'ye ayrı küçük PR'da yazılır.

## Sorun ve sınır

Provenance etiketi tek başına tekrar üretilebilirlik sağlamaz. Şubat'ta
indirilen, Ocak yayımlanma tarihi taşıyan veri, Ocak kararında görülmüş gibi
seçilemez. Aynı zamanda kaynağın kesintisi, eksik kapsam ve çelişkili veri
tanıda ayrılmalıdır. Dört mevcut status korunur; ayrıntı reason taşır.

İlk uygulama yalnız sürümlü ortak tipler; ikinci uygulama saf seçim hizmetidir.
Sağlayıcı I/O, append-only depolama, journal göçü ve risk blokları ayrı PR'lardır.
Strateji saf kalır; saat ve girdiler dışarıdan gelir. Henüz göç numarası ayrılmadı.

## Zaman ve gözlem kanıtı

| Alan | Anlam |
|---|---|
| event_start / event_end | Olay aralığı; karar zamanından sonra olabilir |
| published_at | Kaynağın yayımlanma beyanı; yerel gözlem değildir |
| known_at | Sistemin revizyona eriştiği zaman; v1 anlamı korunur |
| received_at | Yerel alım zarfındaki değişmez kayıt zamanı; yeni öneri |
| decision_at (T) | Seçim için dışarıdan verilen karar zamanı |

Her olay revizyonu ve kapsam/gözlem kaydı için `known_at <= received_at <= T`
gerekir. Yeniden indirme ilk alım kaydını değiştirmez; yeni alım ayrı kayıt olur.
Kaynağın eski tarihi known_at alanına kopyalanmaz. Eski v1 kaydında olmayan
received_at uydurulmaz. OBSERVED etiketi sonradan edinilen veriyi geçmişe taşımaz.
Alım saatinin doğruluğu ayrıca ingestion sorumluluğudur; tip doğrulaması bunu
tek başına ispatlamaz.

`allowed_provenance` boş olmayan açık bir küme, varsayılan yalnız OBSERVED'dir.
Filtre hem olaylara hem kapsam kanıtına uygulanır. Filtreyi genişletmek zaman
kapısını kaldırmaz. Geç edinilen veriyi geçmişte varmış gibi kullanan karşı
olgusal araştırma bu API'nin dışında ve terfiye uygun olmayan ayrı bir iştir.

## Saf seçim sırası

1. Girdi tiplerini/kimliklerini doğrula. Aynı revision kimliği farklı içerik
   taşıyorsa veri bütünlüğü hatası ver; sıra veya alfabetik adla seçme.
2. Sabit girdi manifestinden T anında görünür gözlem ve revizyonları al.
3. Provenance filtresini uygula; dışlanan kanıtı başarılı boş sorguya çevirme.
4. Her kaynak/olay kimliğinin en son görünür revizyonunu seç. Aynı known_at
   değerli farklı revizyonlar çelişiyorsa UNAVAILABLE/conflicting_revisions.
   Revision dizgesi kronolojik sıra değildir. Tekrarlanan aynı kayıt tekilleşir.
5. **Revizyon seçiminden sonra** olayın güncel sembol/tür/aralık kapsamını
   uygula. Önce kapsamla filtrelemek, tarihi taşınan bir olayın eski revizyonunu
   diriltebilir. İptal revizyonu da eskisini diriltmez; kapsam içindeyse audit
   için korunur. Yalnız iptal kayıtları da AVAILABLE olabilir; active_events boştur.
6. Tam kapsam kanıtını ve freshness sınırını değerlendir, sürümlü çıktı üret.

İlk dilim tek kaynak/sembol/türler ve tek tam kapsam gözlemine dayanır;
parçalı sayfaları veya kaynakları keyfî birleştirerek tam kapsam iddia etmez.
Kapsam kanıtı sorgu sınırlarını, başarılı tamamlanmayı, provenance ve freshness'ı
taşır. Geçerli eski cache varken sonraki bir sağlayıcı hatasının nasıl ele
alınacağı politikada açık olmalıdır; öneri aşağıdaki muhafazakâr önceliktir.

## Durum ve neden önerisi

| Koşul | Status | reason |
|---|---|---|
| T'ye kadar hiçbir ilgili gözlem yok | UNAVAILABLE | no_observation |
| Görünür gerekli kanıt provenance filtresinden geçmiyor | UNAVAILABLE | provenance_excluded |
| En son ilgili sorgu başarısız | UNAVAILABLE | provider_error |
| Geçerli adaylarda çelişkili revizyon var | UNAVAILABLE | conflicting_revisions |
| Başarılı sorgu gerekli kapsamı tamamlamamış | UNAVAILABLE | partial_coverage |
| Tam kanıt var, T >= fresh_until | STALE | expired |
| Tam ve güncel kanıt, kapsamda revizyon var | AVAILABLE | yok |
| Tam ve güncel kanıt, kapsamda revizyon yok | EMPTY | yok |

Birden fazla koşul varsa tablodaki ilk uygulanabilir koşul birincil reason'dır;
diğer bulgular ayrı tanı kaydında tutulabilir. Bu öncelik henüz onaylanmadı.
Gözlem seçimi de önce zaman, sonra kapsam uygunluğuyla deterministik olmalı;
aynı zamandaki çelişkili kapsam kayıtları sessiz seçilemez.
UNAVAILABLE olay taşımaz. STALE eski kanıtı tutabilir fakat uygunluk sağlamaz.
EMPTY hata değildir; olayların yalnız filtreyle çıkarılması onu kanıtlamaz.
Kaynak yanıt gövdesi veya serbest exception metni reason alanına alınmaz.

## Kimlik, tekrar üretim ve v1 uyumluluğu

İki kimlik ayrılır:

- **Snapshot kimliği:** `research-v2:` önekli kanonik içerik hash'i. Sorgu
  kapsamı/T, politika sürümü, sıralanmış provenance filtresi, status/reason,
  seçilen revizyonlar ve sonucu gerekçelendiren görünür gözlem kanıtını kapsar.
  Gelecekte edinilmiş/dışlanmış girdiler hash'e girmez. UTC normalizasyonu ve
  sıra bağımsızlığı korunur; kesin alan listesi tip PR'ında altın testle sabitlenir.
- **Evaluation kimliği/manifesti:** tüm sabit girdi veri setinin hash'i,
  dosya hash'leri, kod/politika sürümü ve snapshot kimliğini kaydeder. Veri setine
  yeni kayıt eklemek yeni manifest üretir; geçmiş snapshot aynı kalabilir.

Dolayısıyla `(kapsam, T, filtre)` tek başına snapshot kimliğini belirlemez.
Seçilen kanıt ve politika da gerekir. Bütün veri setinin hash'ini snapshot'a
koymak ise ilgisiz gelecek kayıtlarının eski snapshot hash'ini değiştirmesine
yol açar. Tam veri evreni manifestte, karar kanıtı snapshot'ta tutulur.
Persist edilen snapshot içerik hash'iyle yüklenir; hash uyuşmazlığı hata verir.

Öneri: v1 okuyucusu ve `research-v1:` hash'i aynen korunur. Yeni zorunlu
alanlar v1 modeline eklenmez; v2 ayrı tip ve açık schema_version ayrımıdır.
V1'den v2'ye sessiz dönüşüm/yeniden hash yoktur. V1 audit için okunur;
v2 değerlendirmesinde eksik yerel alım kanıtı varsayımla tamamlanmaz ve v1
tek başına v2 terfi uygunluğu sağlamaz. Context'in v2 kabulü ayrı tip PR'ında
çift gözle incelenir. Mevcut v1 tüketicisinin davranışı bu belgede değiştirilmez.

## Uygulamayı kabul ettirecek testler

- T sonrasında edinilen backfill, aynı T sonucunu dar veya geniş hiçbir
  provenance filtresinde değiştirmez; girdi manifesti değişebilir.
- T öncesinde edinilmiş BACKFILLED kanıt geniş filtrede görülebilir; OBSERVED
  filtresinde dışlanır. Bu, zaman kapısından bağımsız filtre sınamasıdır.
- T anındaki alım görünür; T'den sonraki görünmez. T == fresh_until STALE'dir.
- Tam kapsam yokken EMPTY üretilemez; yalnız olay filtresiyle EMPTY üretilemez.
- İptal, olay zamanının/sembolünün düzeltilmesi ve eşzamanlı çelişki eski
  revizyonu diriltmez. Girdi sırası sonucu değiştirmez.
- Aynı kimlik/farklı içerik reddedilir; aynı içerik tekrar alımı tekilleşir.
- DST yerel gün aralığı, UTC eşdeğerleri, hash altın örneği ve serialize/load
  round-trip korunur; v1 altın hash'i değişmez.
- Research kullanan öğrenme koşusu doğrulanmamış veya stale kanıtta uygun
  sayılmaz; doğrulanmış research tek başına strateji terfi izni vermez.

## Claude'dan beklenen kararlar ve sonraki işler

1. Yerel zaman kapısını geniş filtrede de koruma, snapshot/manifest kimliklerini
   ayırma ve v1'i dönüştürmeden okuma önerisini kabul ediyor musun?
2. Yukarıdaki reason önceliği ve en son başarısız sorguda eski cache'e dönmeme
   politikası uygun mu? Alternatif gerekiyorsa tip PR'ından önce sabitleyelim.

Mutabakat sonrası Codex: AGENTS kaydı + küçük v2 tip PR'ı, ardından saf selector.
Claude: Faz 3 uygunluk entegrasyonunu bu sürümlü API'ye göre ayrı PR'da yapar.
#17 sabit artifact/offline baseline işi Claude'da kalır; bu belge veri indirme,
emir gönderme veya otomatik terfi uygulamaz.
