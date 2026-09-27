# Alpaca ilk gerçek pilotu: kalıcı ham veri aktarımı olmadan ilerleme

Tarih: 2026-09-27. Koordinasyon: #17. Bu belge yürütme tasarımıdır;
workflow ve gerçek pilot sonuçları henüz teslim edilmemiştir.

## Sorun ve karar

Bağlantı ile veri taşıma farklı işlerdir. AGENTS §7'de paper hesabı ve
SDK'nin günlük/dakikalık veriye erişimi kayıtlıdır. Açık konu, indirilen ham
verinin kalıcı dış artefakt olarak saklanmasıydı. Bu belirsizlik bütün
projenin veya ilk veri kalitesi ölçümünün engeli olmayacak.

İlk pilot tek GitHub Actions job'ında indirme ve kalite ölçümü yapar;
ham veri aktarımına veya DATASET_KEY kurulmasına ihtiyaç duymaz. Şifreli
sentetik taşıma bağımsız geliştirilebilir ve pilotun ön şartı değildir.

## Resmi kaynak ve yorumun sınırı

[Alpaca Terms and Conditions](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf)
2026-09-27 tarihinde incelendi. Personal and Non-Commercial Usage bölümü
kişisel/ticari olmayan kullanımı öngörüyor. Content bölümündeki aktarım
kısıtı yayın, dağıtım veya ticari girişim bağlamında yazılmış. Metin ayrıca
ek hesap ve hizmet anlaşmalarının geçerli olduğunu söylüyor.

Bundan kişisel, paylaşılmayan analiz geliştirmesine devam etme yönünde bir
çalışma yorumu çıkarıyoruz. Bu, GitHub'da kalıcı ham veri saklamaya özel
sağlayıcı onayı değildir; böyle bir onay alınmadı. Şifreleme lisans vermez.
Hesaba/feed'e özgü açık bir kısıt öğrenilirse ilgili akış yeniden değerlendirilir.
Kalıcı ham veri artefaktı gerektirmeyen mimari bu tartışmayı ilk pilotun
teknik bağımlılığından çıkarır; hukuki belirsizliği yok olmuş saymaz.

## Pilot PR kabul şartları

1. Manuel tetikleme ve main denetimi; sabit incelenmiş pilot spec'i.
   Kullanıcıdan serbest sembol/tarih, kabuk komutu veya URL alınmaz.
2. İndirme salt okunur; broker emir yolu yok. Secret'lar yalnız indirme
   adımında. Ücretli plan/feed değişimi otomatik yapılmaz.
3. Tanım pilot olarak kalır. Kalite ölçülür, P&L hesaplanmaz. Eksik günler
   atılmaz, eşikler başarı görüntüsü yaratmak için gevşetilmez.
4. Ham bar/manifest/veri dizini artifact, cache ve log'a çıkmaz. İzinli çıktı
   alanları açıkça tanımlanır: run/code/spec kimlikleri, sembol başına seans
   sayıları, açılış/kapanış eksikleri ve eksik dakika oranları. Fiyat, hacim,
   hesap değerleri, API yanıt gövdesi ve sırlar çıktıda bulunmaz.
5. Hata yolu da aynı çıktı kuralına uyar; indiscriminant traceback/response
   dökümü yok. Sentetik işaretlerle başarı/hata çıktısı test edilir.
6. Geçici dosyalar always cleanup ile kaldırılır. Bu, depolama ortamında
   adli olarak geri getirilemez silme iddiası değildir.
7. Kod PR'ı, bağımsız inceleme ve quality sonrasında main'e girer. İlk gerçek
   koşunun run/job kimlikleri ve kalite sonucu #17'ye yazılır. Henüz gerçek
   pilot çalıştırıldığı veya başarılı olduğu iddia edilmez.

## Pilot sonrasında

Kalite sonucu uygunsa ana spec'in eşikleri gerekçeli ayrı commit ile
kesinleştirilir; sonra onay ve ana indirme. Uygun değilse veri feed'i/strateji
uygunluğu tartışılır. Holdout kuralı değişmez. Aynı job içinde indirme ve
baseline hesabı da kalıcı ham artefakt gerektirmeden ileride tasarlanabilir;
pilot PR'ı bu ölçümü otomatik yetkilendirmez.

Kalıcı, yeniden kullanılabilir şifreli veri taşıması ayrı iştir. Sentetik
öz-sınama tek job iki aşama olabilir: producer düz verisi kaldırılır,
consumer boş ayrı dizinden yalnız indirilen baseline paketini kullanır.
Bu test ayrı job izolasyonunun kanıtı diye sunulmaz.

## Sorumluluk ve sıra

Claude: pilot workflow'u ve testleri; Codex: bağımsız inceleme. Araştırma
katmanı paralel ilerler. Kullanıcının ajanlar arasında mesaj taşıması gerekmez.
Kaynaklı bu karar #17'de kayıtlıdır; itiraz veya yeni şart bilgisi aynı yerde
somut kaynağı ve etkilediği işlemle tartışılır.
