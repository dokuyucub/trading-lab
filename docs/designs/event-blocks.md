# Olay verisi ve işlem engelleme: Faz 4 taslağı

Durum: taslak; karar, veri indirme veya yürütme yetkisi değildir.
Sahip: Codex. Bağımsız inceleme: Claude. Başlangıç: bf0b15f.
Dayanak: AGENTS §0, §10, §10.1, §11.5; #17/6642846985.

## Amaç

Karar anında bilinen bilanço ve şirket açıklamalarını yapılandırılmış
kanıt olarak sunmak; olay günlerinde işlem engellemenin değerini yeni,
önceden tanımlanmış bir değerlendirmede sınamak. Research kanıt hazırlar;
engelleme kararını risk katmanı verir. Strateji ağ erişimi almaz.
Mevcut gölge kampanyasının girdileri, eşikleri ve kodu değişmez.

## Kaynak yeterliliği: uygulamadan önce çözülmeli

SEC EDGAR şirket açıklamaları için aday kaynaktır. Kaynağın resmî olması,
bütün olayları veya önceden ilan edilmiş bilanço takvimini kapsadığını
kanıtlamaz. Bir dosyanın yayımlanma zamanı, olayın gerçekleşme zamanı ve
önceden bilinen planlı açıklama zamanı ayrı alanlardır. Geçmiş dosyalardan
sonradan çıkarılan tarih, o sabah bilinen takvim gibi kullanılamaz.

Sağlayıcı seçim PR'ında resmî API belgeleriyle şu konular doğrulanacak:
kapsam, erişim koşulları, gecikme, revizyonlar, sayfalama, zaman hassasiyeti,
şirket kimliği/sembol eşlemesi. SEC kaydında açıklama bulunamaması
"bugün bilanço yok" sonucuna yetmez. İleriye dönük takvim ayrı kaynak
veya ayrı kapsam kanıtı gerektirebilir; sağlayıcı henüz seçilmedi.
Her 8-K aynı olay sayılmaz; olay türleri ayrı sınıflanır. Yahoo verisi veya
haricî paketin broker/emir yolu bu taslağın parçası değildir.

### İlk sürümün kapsamı

Önce, önceki normal seans kapanışından karar anına kadar yayımlanan ve sistemin o anda teslim aldığı şirket açıklamaları incelenir. Bu pencere önceki kapanış sonrası ve bugünkü açılış öncesi açıklamaları kapsar. Gelecek bilanço takvimi ayrı bir sorudur. İlk çalışmanın kapsam ölçümü ileri tarih bilgisini gerekli gösterirse ayrı kaynak kararı alınır. Sağlayıcı incelemesi, kabul zamanının saat dilimini ve hassasiyetini, basın açıklaması ile belgenin sistemimize gelişi arasındaki gecikmeyi ve ilk ORB kararına yetişmeyen açıklamaları ölçer. Item 2.02 ve diğer 8-K türleri ayrı sınıflandırılır.

Politika sekiz şirket hissesine uygulanır. SPY, QQQ ve IWM için ihraççı bilanço filtresi uygulanamaz. Bu, seçimden önce belirlenen araç kapsamıdır ve EMPTY veri kaydı üretmez. Bu üç ETF, bu ölçümün olay paydasına girmez. Bileşen şirket etkileri ve makro açıklamalar ayrı araştırma sorularıdır.

## Kanıt sözleşmesi

AGENTS §10.1 ve research-v2-selection.md esas alınır; ikinci seçim
algoritması oluşturulmaz. Her olay revizyonu şu bilgileri taşır:

- Kalıcı olay/şirket kimliği, karar anında geçerli sembol eşlemesi.
- Olay türü, olay zamanı ve hassasiyeti; planlanan/gerçekleşen ayrımı.
- Kaynağın yayımlama zamanı, known_at, yerel received_at ve provenance.
- Kaynak belge kimliği/URL'si, içerik özeti, revizyon/iptal ilişkisi.
- Sorgunun kapsamı, başarı durumu, alım zamanı, güncellik ve politika sürümü.

known_at <= received_at <= decision_at korunur. Geçmişte yayımlanmış
belgeyi bugün almak geçmişte OBSERVED kanıtı üretmez; BACKFILLED ayrı
kalır ve otomatik terfiye uygun kanıt sayılmaz. Görünür son revizyon
önce seçilir; tarih değişince eski olay yeniden canlandırılmaz.
Gelecekte öğrenilen revizyon tanı alanlarına da giremez.

AVAILABLE, EMPTY, UNAVAILABLE, STALE ayrı kalır. EMPTY yalnız başarılı,
tam kapsamlı sorgudan çıkar; bulunamayan veri veya eksik sayfa değildir.
BMO/AMC/UNKNOWN kesin saat sayılmaz. Gün hassasiyeti borsa saat dilimindeki
tam günü kapsar. Kararın kanıtı snapshot kimliğiyle journal'a bağlanır;
saklama ve şema göçü ayrı PR'dır.

## Risk politikası: henüz etkin değil

İlk uygulama yalnız kanıt ve gözlem üretir. Blok penceresi, olay sınıfları,
veri yokluğu politikası ve geçerlilik süresi ayrı risk PR'ında sabitlenir.
Gerekli olay kapsamı doğrulanamıyorsa bunu olay yokmuş gibi geçirmek yok;
öneri yeni girişleri engellemek, mevcut pozisyonların koruma/kapanışını
sürdürmektir. Bu davranış hata senaryolarıyla ayrıca doğrulanmalıdır.
Olay bloku günlük zarar kapısını, bracket veya gün sonu kapanışını kaldırmaz.

## Değerlendirme planı

Mevcut 67 işlemli SIP baseline yeniden filtrelenmez; kapalı holdout açılmaz.
Gölge kampanyası P&L veya bu filtre için bağımsız başarı kanıtı değildir.
Yeni çalışma başlamadan aday, feed, evren, tarih aralığı, maliyetler,
blok penceresi, birincil ölçü ve asgari destek kayıtlı kararla sabitlenir.
Dönem ileriye dönüktür. Başlangıç, sağlayıcı ve kalıcı depolamanın ilk doğrulanabilir yerel alımından önce olamaz. Karar anları ilerledikçe OBSERVED kanıt birikir. Veri görülmeden dönem ve bitiş kuralı kaydedilir.

Süre için duyarlılık örneği: yılda 15–25 engellenen işlem gözlenirse 30 örnek yaklaşık 1,2–2 yıl sürer. Her iki sayı da planlama varsayımıdır. Gerçek sıklık, gerekli destek ve tahmin hassasiyeti henüz ölçülmedi. Tarihsel 67 işlem bu sayımı başlatmaz. Salt maruziyet azaltma politikası ve performans üstünlüğü ayrı karar gerektirir. İlkinde kaçırılabilecek kazanç da maliyettir. İkincisi ileri dönemde eşleştirilmiş ölçüm gerektirir.

Aynı yeni dönemde önceden sabitlenmiş filtresiz aday ve olay filtreli aday
aynı maliyetlerle eşleştirilir. Net R farkı, işlem sayısı, maruziyet,
engellenen niyetler ve bilinmeyen veri kapsamı birlikte raporlanır.
Aynı gün/sembol bağımlılığı dikkate alınır; gün bloklarıyla belirsizlik
ölçümü önceden tanımlanır. Çoklu olay sınıfı denemeleri keşif olarak
etiketlenir; en iyi satır sonradan birincil sonuç yapılmaz.
Destek yetersizse belirsiz sonuç verilir. Otomatik parametre terfisi yoktur.

## Kabul senaryoları ve teslim sırası

1. Kaynak/kapsam kararı: planlı takvim ile gerçekleşmiş açıklama ayrımı.
2. Saf seçim testleri: geç alım, gelecekteki revizyon, iptal, sembol değişimi,
   gün hassasiyeti/DST, başarısız sorgu, eksik sayfa, bayat önbellek,
   doğrulanmış boş sonuç. Yalnız karar anında görünür kanıt kullanılır.
3. Append-only depolama, snapshot/journal bağı ve gerekli göç rezervasyonu.
4. Ayrı risk entegrasyonu; eksik olay verisinde giriş engeli ve devam eden
   pozisyonların koruma/kapanışı birlikte sınanır.
5. Yeni veri ve değerlendirme için ayrı yürütme kararı.

Kampanya sırasında yalnız belge/test çalışması main'e önerilir; üretim
kodu ayrı dalda geliştirilebilir, dondurma bitmeden birleştirilmez.
Bu taslak henüz uygulanmış haber motoru veya kârlılık kanıtı değildir.
