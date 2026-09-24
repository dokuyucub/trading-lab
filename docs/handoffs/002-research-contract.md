# Research sözleşmesi — Codex → Claude

Başlangıç: cca99e8 (PR #3 birleşmiş main). Tasarım: issue #12.
Dal: codex/research-contract. İnceleyici: Claude.

İlk küçük Faz 4 adımı: core/research.py ve isteğe bağlı Context.research.
Snapshot tüm içeriğiyle hash'lenir; gelecek bilgisi, yanlış kapsam/sembol,
çifte revizyon ve stale verinin güncel gösterilmesi reddedilir. UTC
normalizasyonu DST fold karşılaştırma sorununu önler. Gün hassasiyeti gerçek
lokal günü kapsar; 25 saatlik DST günü testte bulunur.

Özellikle incelenecekler: EMPTY/UNAVAILABLE ayrımı; snapshot known_at <=
observed_at <= as_of; içerik hash'i; research uygunluk bayrağının genel
strateji terfi onayı sanılmaması; yeni Context alanının geriye uyumluluğu.

Bu PR sağlayıcı, tarihsel revizyon seçicisi, göç, journal persist etme,
öğrenme entegrasyonu veya earnings engeli eklemez. Aynı kaynağın eski
revizyonlarını tutma ve sorgu kapsamının gerçekten tamamlandığını doğrulama
gelecek sağlayıcı/depolama PR'larının sorumluluğudur. Tip düzeyindeki
kontroller sağlayıcının doğruluğunu kanıtlamaz. Göç numarası rezerve edilmedi.

Sıradaki adım: bağımsız inceleme → küçük tip PR'ının birleşmesi → göç
rezervasyonu + append-only evidence depolaması/as-of seçim testleri →
sağlayıcı sözleşme testleri → ayrı risk entegrasyonu. Claude Faz 3'te
has_verified_knowledge=False olan research destekli değerlendirmeleri
promotion_eligible=False olarak tutmalı; veri uygunluğu tek başına terfi
izni değildir.

Alpaca: bu ortamda anahtar yok. 2026-09-21 kimliksiz bağlantı denemesinde
paper-api ve data adresleri timeout verdi; bunun nedeni kesinleştirilmedi.
Gerçek doctor/hesap/backtest sonucu yok. Güvenli yerel kontrol rehberi
`docs/alpaca-paper-check.md`; kullanıcı anahtarları sohbet/GitHub'a yazmamalı.

Doğrulama: güncel main üzerine `make check` — 399 test geçti, mypy 57
kaynak dosyasında temiz, ruff/format 69 dosyada temiz. Toplam kapsama
%85.62; core/research.py satır ve dal kapsamı %100. Testler çevrimdışı.
