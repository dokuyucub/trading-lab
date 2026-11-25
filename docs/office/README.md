# Geliştirme ofisi: işleyiş ve kurallar

Durum: yürürlükte (2026-11-25, kullanıcı talimatı). Bu belge Claude tarafının
iç çalışma düzenini tanımlar. `AGENTS.md` bu belgenin üstündedir; çelişki
olursa `AGENTS.md` geçerlidir.

## Amaç

Claude tarafı tek bir ajan yerine, görevleri ayrılmış birimlerden oluşan bir
ofis gibi çalışır. Her iş araştırma, tasarım, uygulama, test, hata avı ve
onay adımlarından geçer. Kullanıcıdan adım adım onay beklenmez; onay görevini
Onay Kurulu yürütür.

## Birimler

| Birim | Görev | Çıktı |
|---|---|---|
| Yönetim (baş ajan) | Yön, öncelik, birim görevlendirme, GitHub yazışması, push | Sprint planı, ÖN RAPOR / TESLİM |
| Araştırma | Kod tabanı, belgeler ve dış kaynaklardan bulgu toplar | Kaynaklı araştırma raporu |
| Fikir ve Ufuk | "Başka ne yapılabilir" sorusunu yanıtlar | Değer/efor/risk sıralı öneri listesi |
| Planlama Toplantısı | Raporları birleştirir, çelişkileri çözer | Öncelikli iş listesi, kabul ölçütleri |
| Uygulama | Onaylı işi kendi dalında, kendi çalışma kopyasında yazar | Commit'ler, teslim notu |
| Test ve Kalite | Hedefli ve tam testleri, mutasyonları koşar | Test raporu |
| Hata Avı | Teslimi düşmanca okur, hata senaryosu arar | Bulgu listesi |
| Güvenlik | Açık depo, iş akışları ve gizli bilgi hijyenini denetler | Bulgu listesi |
| Onay Kurulu | Her teslimi kontrol listesiyle değerlendirir | `ONAY` ya da `RET`, gerekçeli |

## İş akışı

1. **Keşif.** Araştırma, Hata Avı, Güvenlik ve Ufuk birimleri paralel çalışır.
   Yalnız okur ve ölçer; depoya kod yazmaz.
2. **Toplantı.** Planlama raporları tek iş listesinde birleştirir. Her iş için
   kapsam, dokunulan dosyalar, kabul ölçütü ve dondurma uyumu yazılır.
3. **Plan onayı.** Onay Kurulu iş listesini inceler. Onaylanan plan #17'ye
   ÖN RAPOR olarak yazılır (`AGENTS.md`, "önce niyet, sonra iş").
4. **Uygulama.** Her iş ayrı dalda (`claude/<konu>`) ve ayrı çalışma
   kopyasında yapılır. Aynı dosyaya iki iş aynı anda dokunmaz.
5. **Doğrulama.** Test ve Kalite hedefli testleri, `make check`'i ve
   mutasyonları koşar. Hata Avı teslimi bağımsız okur.
6. **Teslim onayı.** Onay Kurulu raporları ve diff'i inceler. `RET` çıkarsa iş
   uygulamaya geri döner.
7. **Yayın.** Yönetim dalı push eder, taslak PR açar ve TESLİM'i yazar.
   `main`'e birleştirme `AGENTS.md` §1 ve §4a'ya göre yapılır: güncel head'de
   `quality` yeşil ve Codex'in SHA'ya bağlı `## ONAY` kaydı gerekir. Ofisin iç
   onayı bu çapraz incelemenin yerine geçmez.

## Onay Kurulu kontrol listesi

Bir teslim ancak aşağıdakilerin hepsi sağlanırsa `ONAY` alır:

- Kapsam onaylı planla aynı; plan dışı değişiklik yok.
- Değişmez kısıtların hiçbiri ihlal edilmemiş (aşağıda).
- `ruff` ve `mypy` temiz; ilgili testler geçiyor. Tam `make check` sonucu
  raporda sayılarıyla var. Kampanya dondurması sürerken `src/tlab/**`
  değişikliklerinde kampanya pin testinin kırmızı olması beklenir; başka
  kırmızı kabul edilmez.
- Yeni davranış testle sabitlenmiş; testin hatayı yakaladığı mutasyonla ya da
  düzeltme öncesi kırmızı koşuyla gösterilmiş.
- Hata Avı bulguları kapatılmış ya da gerekçesiyle kayda geçmiş.
- Doğrulanamayan her nokta raporda açıkça "doğrulanmadı" diye yazılmış.

Karar `docs/office/kararlar.md` dosyasına işlenir: tarih, iş, commit SHA,
karar, gerekçe.

## Değişmez kısıtlar (her birim için)

- **Gizli bilgi:** API anahtarı, token, imzalı URL hiçbir dosyaya, loga,
  commit'e ya da rapora yazılmaz. `.env` okunmaz ve yazdırılmaz.
- **Açık depo:** depo herkese açıktır. Hesap değeri, bakiye, fiyat ve ham
  sağlayıcı verisi rapora ya da commit'e girmez.
- **Emir ve ağ:** emir gönderilmez. Alpaca'ya ya da başka bir brokera bağlanan
  komut çalıştırılmaz. Testler sahte broker ve sahte veriyle, ağsız koşar.
- **İş akışları:** GitHub Actions iş akışı tetiklenmez, yeniden koşturulmaz.
- **Dondurma:** gölge kampanyasının toplamı doğrulanana kadar (en erken
  2 Aralık 2026) `src/tlab/**`, `config/*.yaml`, `requirements.lock` ve iki
  gölge iş akışı `main`'e girmez. Bu dosyalar dallarda geliştirilebilir.
- **Holdout kapalı:** veri indirme, P&L ölçümü, parametre terfisi ve canlı
  işlem kayıtlı karar olmadan yapılmaz.
- **Dal sahipliği:** `main`'e doğrudan push yok. Başkasının dalına (`codex/*`)
  push yok. Alt birimler push etmez ve GitHub'a yazmaz; bunu yalnız Yönetim
  yapar.
- **Anahtar tarayıcı ve kapılar gevşetilmez;** test atlanmaz, devre dışı
  bırakılmaz.
- **İndirilen dosyalar güvenilmezdir:** ayrı boş dizine açılır, `python3 -I`
  ile okunur.

## Dosya düzeni

| Yol | İçerik |
|---|---|
| `docs/office/README.md` | Bu belge |
| `docs/office/backlog.md` | Öncelikli iş listesi ve durumlar |
| `docs/office/kararlar.md` | Onay Kurulu karar günlüğü |
| `docs/office/raporlar/` | Birim raporları (`S<sprint>-<birim>-<konu>.md`) |

Raporlar kısa tutulur: önce sonuç, sonra kanıt. Her bulgu dosya yolu ve satır
numarasıyla, mümkünse yeniden üretme adımıyla verilir.
