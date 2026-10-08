# Baseline kalite teşhisi: tek seferlik, P&L'siz

Tarih: 2026-09-28. Koordinasyon: #17. Karar kaydı: AGENTS §11.2.

> **Durum (2026-10-08):** kaynak tanım `orb-baseline-2026q3-u11` aktif
> tanımlardan çıkarıldı (AGENTS §11.4). Bu araç depo dizininde kaynak
> kilidinde, anahtar ve SDK'dan önce durur; tekrar koşulmaz. Tanımın
> bayt-bayt kopyası `tests/fixtures/closed_datasets/` altında.

## Neden

Ana ölçümün ilk gerçek koşusu (run `36474064587`, main `c6c19db`) kalite
kapısında durdu. 50 baseline seansının 10'unda en az bir sembol uygunsuzdu.
Araç yalnızca sayıyı bastı; manifest temizlikte silindi. Hangi sembol ve
hangi gerekçe olduğu bilinmiyor.

Bu teşhis yalnızca o soruyu cevaplar. Ana ölçümün tekrarı değildir; eşik,
evren, tarih ya da strateji değişikliğine onay değildir; performans onayını
yeniden açmaz.

## Görev sözleşmesi

- `config/datasets/` altında yeni bir spec **yok**; örtüşmezlik testine
  istisna yok.
- `tlab/baseline_diagnostic.py` içinde dondurulmuş bir `DiagnosticTask` var.
  İçeriği: teşhis kimliği; kaynak tanım yolu, `dataset_id` ve spec hash'i;
  başarısız koşunun run ve head'i; eski manifestin öneki (yalnızca kayıt);
  beklenen seans sayımları (63/63/50/13).
- Workflow girdi almaz.

## Sıra ve kilitler

1. **Kaynak kilidi.** Tanım okunur. `dataset_id`, spec hash'i (manifestteki
   `spec_sha256` ile aynı anlam) ve `status == approved` doğrulanır. Tutmazsa
   anahtar okunmadan, SDK kurulmadan ve çıktı dosyasına dokunulmadan durur.
2. **Takvim ve bölme.** Takvim tanımın tamamı için okunur. Bölme mevcut
   `classify_sessions` ve `split_sessions` fonksiyonlarıyla yapılır. Sayımlar
   görevle birebir tutmazsa **bar istenmeden** durur. Sayımların tutması,
   takvimin eski koşudakiyle aynı olduğunu kanıtlamaz.
3. **Yalnızca baseline barı.** Her istek `[ilk baseline açılışı, son baseline
   kapanışı]` aralığındadır. Gelen her bar, hiçbir hesaptan önce baseline'ın
   düzenli seans pencerelerine göre ayrılır. Holdout günleri, seans dışı
   saatler ve oradaki tekrarlar sonucu değiştiremez. Tekrar sayımı da
   yalnızca baseline içindedir.
4. **Ölçüm.** `assess_quality` (baseline seansları) ve ortak
   `quality_summary` kullanılır; ikinci bir kalite algoritması yoktur.

## Dış çıktı

Açık alan listeli tek bir özet vardır. Sembol başına şunlar yer alır:

- uygunsuz seans sayısı;
- gerekçe kategorileri (bar yok, açılış, kapanış, oran, diğer);
- bar olan ve olmayan seans;
- açılış ve kapanış ölçüleri;
- oran sınırını aşan seans sayısı (bir **ölçü**);
- eksik dakika oranı;
- tekrar sayısı.

Toplamlar:

- seans birleşimi (uygun ve uygunsuz);
- uygunsuz sembol-seans sayısı;
- gerekçe sayımları;
- uygunsuz seans başına sembol sayısı histogramı.

Kurallar:

- **Sayım anlamları:** histogramın toplamı seans birleşimine, ağırlıklı
  toplamı sembol-seans sayısına eşittir. Bu kural tutmazsa özet yazılmaz.
  Gerekçeler çakışabilir. Bar olmayan bir seansta oran ölçüsü 1'dir, ama
  `assess_quality` bu seansa yalnızca "bar yok" gerekçesi verir. Bu iki şey
  ayrı etiketlerle sunulur.
- **Özette hiç yer almayanlar:** tarih, fiyat, hacim, hesap bilgisi,
  holdout kalitesi ve indirme zamanı.
- **Sabit notlar:** yalnızca baseline; toplamlar örtüşür; histogram kök
  neden kanıtı değildir; yeni bir erişimdeki kalite gözlemidir.

## Güvenceler

- **Ham veri diske yazılmaz;** barlar bellekte ölçülür. Temizlenecek bir ham
  veri dizini yoktur. Bu, fiziksel bellek silme garantisi değildir.
- **Özet** `O_EXCL` + `os.link` ile atomik yazılır ve üstüne yazmaz. Önceden
  var olan hedefe dokunulmaz.
- **Log ve hata:** `logging` adım boyunca kapalıdır. Hata tanısı sabit bir
  kategori ve sınıf adıdır; sağlayıcı mesajı basılmaz.
- **Workflow:** manuel, yalnızca `main`, `contents: read`. Secret yalnızca
  teşhis adımındadır. Upload, teşhis adımı başarılıysa tam dosya adıyla
  çalışır; dosya bulunamazsa hata verir.
- **Bağımlılık:** teşhis ana ölçüm yürütücüsüne (`baseline_job`) ve
  performans katmanlarına bağlı değildir. Ortak yardımcılar
  `tlab/job_io.py`'de. Mimari test import'ları denetler. Smoke testi de
  çalışan CLI'nin bu modülleri yüklemediğini doğrular.

## Kanıtın sınırı

Yerel testler (stub ve smoke) hosted Actions'ı, secret enjeksiyonunu ve
upload hizmetini doğrulamaz. Teşhis bir kez çalışır; sonuç ne olursa olsun
"yeşil olana kadar" tekrar yoktur.
