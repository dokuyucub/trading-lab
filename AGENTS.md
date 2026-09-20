# Trading Lab çalışma sözleşmesi

Bu dosya Codex, Claude ve insan katkıcılar için ortak giriş noktasıdır.
Önce CONTRIBUTING.md, ilgili issue/PR ve docs/handoffs/ altındaki ilgili devir
notunu okuyun. Kullanıcının açık talimatları önceliklidir.

## İş akışı

- Güncel uzak dalları ve açık PR'ları kontrol edin. Başkasının devam eden
  değişikliğini ezmeyin; aynı görevi iki bağımsız dalda tekrar yapmayın.
- Her işin issue'sunda problem, kapsam, kabul şartları ve işi alan taraf olsun.
- Ayrı fix/... veya feat/... dalı kullanın. Küçük Conventional Commit'ler yapın.
- PR açıklamasında davranış değişikliği, test kanıtı, sınırlamalar ve sıradaki
  inceleyicinin görevi yazsın. Sırlar, API anahtarları ve hesap dökümleri eklemeyin.
- Geliştirici ve inceleyici rollerini dönüşümlü üstlenin. İnceleyici diff'i ve
  testleri bağımsız kontrol etsin; önceki asistanın beyanını kanıt saymasın.
- Bir sonraki asistan PR dalına geçip mevcut işi inceleyerek devam etsin.
  İnceleme bulguları ve düzeltmeler aynı PR'da izlenebilir olsun.
- Test/inceleme tamamlanmadan merge etmeyin. Gerçek hesapta işlem başlatmak,
  deploy etmek veya finansal risk limitlerini değiştirmek bu iş akışının
  otomatik parçası değildir; kullanıcı talimatının kapsamına göre ilerleyin.

## Kalite kapısı

Python 3.12 ortamında `pip install -e ".[dev]"` ve `make check` kullanın.
Hata düzeltmelerinde ilgili başarısızlık senaryosunu kapsayan regresyon testi
bulunsun. Ağsız testler gerçek Alpaca davranışını veya strateji kârlılığını
kanıtlamaz. Çalıştırılmayan kontrolleri başarılı diye raporlamayın.

## Devir

Her teslimde docs/handoffs/ altında kısa not bırakın: başlangıç commit'i,
issue/PR, yapılan iş, test komutları/sonuçları, bilinen sınırlamalar ve somut
sonraki görev. Kullanıcı "devam et" dediğinde açık PR ve ilgili devir notundan
başlayın; belirsizse görevi uydurmak yerine mevcut durumu bildirin.
