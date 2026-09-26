# Research seçim girdileri — ilk v2 uygulama dilimi

Taban: main `831a374` (#20). Konu: #12; ön rapor: #11.

`core/research_inputs.py` iki ayrı immutable girdi taşır:

- `ReceivedResearchEvent`: mevcut v1 olay payload'ı + zorunlu yerel received_at.
  known_at <= received_at doğrulanır; eksik alım zamanı üretilmez.
- `ResearchQuery`: kaynak/sembol/tür/kapsam/as_of, zorunlu policy_version ve
  varsayılan OBSERVED provenance kümesi. Koleksiyonlar sıralı, benzersiz ve
  boş olamaz. Zamanlar UTC normalleştirilir.

`allows_knowledge` yalnız zaman/provenance ön koşuludur. Kaynak/sembol/kapsam
eşleştirmesi, son revizyon seçimi, iptal, freshness, tam kapsam kanıtı ve terfi
uygunluğu sağlamaz. Özellikle scope filtresini burada uygulamak, kapsam dışına
taşınan yeni revizyonu atıp eskisini diriltebilir. Bunlar saf selector diliminde
beraber uygulanacaktır; bu yardımcı tek başına feature üretiminde kullanılmaz.

Doğrulama tiplerin zaman tutarlılığını sınar; sisteme verilen saatin veya
provenance etiketinin gerçekliğini ispatlamaz. Ingestion bu kanıtı üretmekten
sorumludur. V1 modeli/hash'i değiştirilmedi; Context'e v2 bağlanmadı.

Regresyonlar: sonradan gelen backfill dar/geniş filtrede görünmez; önceden alınan
backfill yalnız geniş filtrede görünür; mikro-saniye sınırı; naive zaman reddi;
v1 payload round-trip; immutable zarf; koleksiyon ve UTC kanonik serileştirme.
`tests/test_research.py` v1 altın hash korumasını ayrıca çalıştırır.

Sonraki sıra: Claude bağımsız tip incelemesi → v2 kapsam kanıtı, reason/tanı ve
snapshot kimliği için küçük tip PR'ı → son revizyon seçimi. Sağlayıcı, depolama,
journal göçü ve risk blokları ayrı kalır; göç numarası ayrılmadı. Bu dilim
dataset/backtest veya emir davranışını değiştirmez.
