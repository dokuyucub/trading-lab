# Gölge gözlem dış başlatıcısı (Cloudflare Worker)

Tasarım: `docs/designs/scheduler-alternatives.md` (A; Codex #17/6196548874,
kabul ölçütleri 6197450956). Bu dizin **kod ve kurulum belgesidir**; depoda
durması hiçbir şeyi dağıtmaz, tetiklemez. Dağıtım, hesap ve PAT kullanıcının
ayrı adımıdır (#17 kararıyla).

## Ne yapar

Hafta içi iki UTC cron satırında (`50 12 * * MON-FRI`, `50 13 * * MON-FRI`; saatler GitHub cron'larıyla
aynı) uyanır; **gerçek saate** göre New York seans gününü ve açılışı (09:30)
hesaplar; yalnız başlangıç penceresinde (`[açılış − 60 dk, açılış − 1 dk]`,
`tlab.shadow.schedule` ile aynı) çalışır. Pencere içindeyse:

1. o seans gününün `shadow-observation` koşu listesini ve her koşunun iş
   listesini okur (Codex 6225592708 P1). Kapının durum tablosuyla aynı
   kural: kayıt işi **kanıtla atlanmış** koşu (bütün denemelerde
   `completed` + `skipped`; örneğin pencereden önce koşan cron, kapı
   "erken") günü tüketmez ve dispatch'i engellemez. Kayıt işi listede
   yoksa, kuyrukta ya da sürüyorsa, ya da başarılı, başarısız veya iptal
   bittiyse **dispatch etmez** (geç cron, ikinci dispatch, zaman aşımı
   sonrası tekrar). Koşu ya da iş listesi okunamaz, biçimsiz ya da tek
   sayfayı aşarsa dispatch **yok** (fail-closed);
2. `POST /repos/dokuyucub/trading-lab/actions/workflows/shadow-observation.yml/dispatches`
   gövde `{"ref":"main"}`; girdi yok; 204 beklenir.

Hata politikası: 401/403/404/422 ve diğer 4xx → tek deneme (dispatch'te
sonuç `red`, liste ya da iş listesinde `liste-okunamadi`). 429/5xx/zaman
aşımı/ağ → en fazla 3 deneme; bekleme liste, iş listesi ve dispatch için
**aynı** hesapla: en az 30 sn, `Retry-After` (tam saniye ya da HTTP tarihi)
daha uzunsa o; anlaşılmayan `Retry-After` → `retry-after-belirsiz`, tekrar
yok (Codex 6225592708 P2). Her denemeden önce ön kontrol yinelenir;
pencerenin son dakikasını aşacak bekleme yapılmaz.

## Ne yapmaz

- HTTP ile tetiklenmez: `fetch` her isteğe 404; `workers_dev = false`.
- Planlı gün listesini bilmez: plan dışı hafta içi günde dispatch gider,
  kapı "plan dışı" der, kayıt atlanır, Alpaca secret'lı gözlem çalışmaz.
  Böyle bir prova gerçek piyasa gözleminin kanıtı sayılmaz.
- 204 kabulünü "gözlem başladı" saymaz: koşu, kapı ve kayıt kanıtı
  Actions API'sinden ayrıca okunur (altı sütun, tasarım belgesi).
- Token, yanıt gövdesi, fiyat ya da hesap bilgisi log'a yazmaz.

## Log satırı

Tek satır JSON: `scheduled` (cron'un planladığı an), `cron`, `started`
(gerçek başlangıç), `session_day`, `open`, `window` (`icinde`/`disinda`),
`existing_run` (dispatch'i engelleyen koşu), `skipped_runs` (kayıt işi
kanıtla atlanmış koşu sayısı), `attempts`, `status` (son isteğin HTTP
kodu, `timeout`, `network`), `result` (`pencere-disi`, `secret-yok`,
`liste-okunamadi`, `kosu-var`, `dispatch`, `red`, `pencere-kapandi`,
`son-dakika`, `retry-after-belirsiz`, `vazgecildi`).

## Kimlik bilgisi (PAT) — kapsamın gerçeği

İnce taneli GitHub PAT: yalnız `dokuyucub/trading-lab`, izin **Actions:
write**, ömür 90 gün (bitiş son toplam doğrulamasını, ≥ 15 Aralık 2026,
kapsamalı). Bu izin yalnız "workflow başlat" değildir: aynı depoda
Actions'ın bütün yazma uç noktalarını kapsar (koşu iptal/yeniden
koşturma/silme, artefakt ve log silme). Kod, secret ve ayar değiştiremez.
Bu yüzden Worker'da depo/workflow/ref sabittir ve HTTP uç noktası yoktur.
PAT **yalnız** Worker secret'ı olarak girilir: sohbete, koda, bu dosyaya,
`wrangler.toml`'a ya da GitHub'a yazılmaz. Dönüş kullanıcıda; bitiş tarihi
#17'ye yazılır, günlük kontrol görevi 14 gün kala hatırlatır.

## Kurulum adımları (kullanıcı; #17 kararıyla, şimdi değil)

1. Ücretsiz Cloudflare hesabı.
2. İnce taneli PAT (yukarıdaki kapsam ve süre).
3. Dağıtım: bu dizinde `npx wrangler login`, `npx wrangler deploy`, sonra
   `npx wrangler secret put STARTER_GITHUB_PAT` (değer terminalde istenir;
   komut satırına yazılmaz). Alternatif: Cloudflare panosunda Worker
   oluşturup `worker.js` içeriğini yapıştırmak, cron tetiklerini ve
   secret'ı panodan girmek.
4. Prova: plan dışı bir hafta içi günü (ayrı #17 kararı). Beklenen: Worker
   log satırı `result: dispatch`; Actions'ta `event: workflow_dispatch`
   koşusu; kapı `plan disi gun`; kayıt atlandı.
5. PAT bitiş tarihini #17'ye yazmak.

Cloudflare notları: cron UTC çalışır; cron değişikliklerinin yayılması 15 dk
sürebilir; "dakika hassasiyeti" cron çözünürlüğüdür, zamanında yürütme
garantisi değil; ücretsiz planın istek/CPU/cron sınırları provada doğrulanır
(<https://developers.cloudflare.com/workers/configuration/cron-triggers/>,
<https://developers.cloudflare.com/workers/platform/limits/>).

## Prova sonucu (#17'ye, altı sütun)

Planlanan an (`scheduled`), gerçek Worker başlangıcı (`started`), dispatch
HTTP sonucu (`status`), koşu kimliği ve `created_at` (Actions API), kapı
başlangıcı ve kararı, kayıt başlangıcı ve sonucu. Tek başarılı prova
güvenilirlik garantisi değildir; kampanya boyunca her gün aynı sütunlar.

## Testler

```
node --test infra/shadow-starter/worker.test.js
```

Node 22, bağımlılık yok, ağ yok (sahte `fetch`, sabit saat, sayılan uyku).
`tests/test_architecture.py` ayrıca `wrangler.toml` cron'larının gözlem
workflow'uyla, Worker sabitlerinin Python sözleşmesiyle aynı olduğunu
denetler.
