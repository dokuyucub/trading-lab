# Devir 001 — seans ve portföy risk düzeltmeleri

- Görev: https://github.com/dokuyucub/trading-lab/issues/1
- Başlangıç: `109594d5aedacda84f002f633261c2b7735745f2`
- Dal: `fix/session-risk-hardening`
- PR hedefi: `claude/alpaca-trading-bot-design-t7zhp0` (mevcut varsayılan dal)
- Geliştiren: Codex. Sıradaki rol: Claude, bağımsız inceleyici.

## Değişiklikler

1. Kaydedilmiş günlük halt yeni girişleri engellerken kapatmayı yeniden dener;
   yeniden başlayan süreç de aynı yolu izler.
2. Kapatma bütün bekleyen emirleri iptal eder. İptal sonrası açık emirler ve
   pozisyonlar tekrar okunur; iptali henüz bitmeyen sembole rakip kapatma emri
   gönderilmez. Pozisyonsuz girişler ve iptal sırasında dolan girişler kapsanır.
3. Broker'ın erken kapanışı, yapılandırılmış kapanıştan erken ise esas alınır.
4. Emir referansına yön, kalan miktar ve limit fiyatı eklendi. Bekleyen girişler
   maruziyet bütçesi ve benzersiz pozisyon kapasitesini tüketir. Eski adapter
   metadata vermiyorsa kendi emirlerimiz için journal'daki tam miktar ayrılır.
   Boyutu/fiyatı bilinmeyen risk yeni girişleri veto eder.
5. Her broker görüntüsünde en fazla bir gönderim girişimi: sonraki sembol için
   yeni tur ve mutabakat beklenir. Kaybolan yanıt da bu sınırı tüketir.
6. AGENTS.md/CLAUDE.md ve CONTRIBUTING.md ortak çalışma düzenini tanımlar.

## Bilinçli sınırlar ve inceleme odağı

- Testler çevrimdışı ve yerel HTTP stub'ıyla çalışır. Gerçek Alpaca paper/live
  oturumuna bağlanılmadı; emir gönderilmedi, dağıtım yapılmadı.
- Aynı hesap üzerinde tek bot süreci varsayılır. Eşzamanlı süreç veya dışarıdan
  yeni emir verme ile snapshot yarışlarını çözmek ayrı iş gerektirir.
- Kapatmada hesap kapsamındaki bütün emirler iptal edilir. Bu bot için ayrılmış
  hesap kullanımı varsayılır; manuel/başka strateji emirleri de etkilenir.
- Pozisyonu azaltan emirler toplam mevcut miktara kadar riskten düşülür.
  OCO/bracket bacaklarının grup kimliği modellenmediği için birden fazla çıkış
  muhafazakâr biçimde ek risk sayılabilir; stop fiyatı yerine limit fiyatı
  bulunamıyorsa yeni girişler durur. Güvenli OCO grup modeli ayrı geliştirmedir.
- Eski adapter/journal fallback kısmi dolumda fazla bütçe ayırabilir.
- Limit fiyatı üzerinden tahmini nominal maruziyet kullanılır; fiyat hareketi,
  özellikle short işlemler, gerçekleşen maruziyeti değiştirebilir.
- Bir turda tek gönderim, çok sembollü sinyallerde sıralama ve gecikmeyi değiştirir.
- İptal/kapatma ağ kesintisinde anında tamamlanma garantisi yoktur. İptalden
  sonra kapatma reddedilirse pozisyon sonraki başarılı denemeye kadar korumasız
  kalabilir. İnceleyici bu aralığı ve kapatma emirlerinin yaşam döngüsünü özellikle
  değerlendirmeli; yeşil test gerçek hesapta gözetimsiz çalışmaya onay değildir.

## Claude'un sonraki görevi

1. Uzak dalları güncelle; bu PR'ın diff'ini ve AGENTS.md'yi oku.
2. Dört hata senaryosunu ve yeni regresyon testlerini bağımsız değerlendir.
   Özellikle kısmi dolum, iptal gecikmesi, restart ve OCO sınırlamasını incele.
3. `make check` çalıştır; bulgu varsa aynı PR dalında küçük commit'le düzelt.
4. Bulguları ve test sonuçlarını PR'a yaz. Açık sorun/CI hatası varken merge etme.
5. Sonraki iş önerisini somut issue olarak kaydet: broker tarafında iptal/kapatma
   yaşam döngüsü ve OCO grup metadata'sı. Yeni strateji/öğrenme katmanından önce
   bu operasyonel doğrulamayı tamamla. Gerçek hesap testi ayrı kullanıcı görevidir.

## Doğrulama

Kod/test commit'i: `e8cf22de5f82b1ffdee58ba814d4ddc5cd9b5ff5`.

Python 3.12 ortamında:
- `pytest`: **321 passed** (18.58 saniye).
- `mypy`: 53 kaynak dosyada hata yok.
- `ruff check .`: başarılı.
- `ruff format --check .`: 59 dosya biçimi doğrulandı.
- `git diff --check`: başarılı.

Yerel mypy önbelleğinde bozuk SQLite dosyası nedeniyle bir araç hatası oldu;
yalnızca geçici `.mypy_cache` temizlenip tekrar çalıştırıldı ve kontrol geçti.
Kodda veya kalite kurallarında bu hatayı gizlemek için değişiklik yapılmadı.
GitHub CI sonucu PR üzerinden ayrıca kontrol edilmelidir.
