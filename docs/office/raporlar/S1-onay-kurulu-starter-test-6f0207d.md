# Onay Kurulu — Starter testi: saat sabitleme (`6f0207d`)

**Karar: ONAY (notlarla).** Yayından önce değişmesi gereken bir şey yok. Tarih: 2026-11-26.

İncelenen: `claude/starter-test-saat`, tek commit `6f0207d` (ebeveyn `d77b381` = `origin/main`); yalnız
`infra/shadow-starter/worker.test.js` (+31/−8). Kök neden gerçek ve belirlenimli olarak yeniden üretildi.
Yeni test saatten bağımsız ve eskisinden zayıf değil: 14 tek satırlık mutanttan 12'si yakalandı, 12'sinde de
test 24 kırılanlar arasında (eski test aynı sette 10–11 yakalıyor, test 24 yalnız 7'sinde kırılıyor).
Kaçan iki mutant eski testte de kaçıyor (N1).

## Kontrol listesi

| # | Madde | Sonuç | Kurulun ürettiği kanıt |
|---|---|---|---|
| 1 | Kapsam | sağlandı | `git diff origin/main 6f0207d --stat`: 1 dosya, +31/−8. `worker.js` sha256 main ile aynı (`8069e988…`), `git diff` boş. |
| 2 | Kök neden gerçek | sağlandı | Koddan: `scheduled` `start`'a `now` vermez (s. 335), varsayılan `Date.now` (s. 261). Pencere içinde `runsOfDay` 5 Ocak koşusunu eler (s. 118), ön kontrol `ok`, dispatch'e sahte fetch 200 döner, `classify(200)` = `fatal`, sonuç `red` (s. 326). Gösterim: main'deki test dosyası worktree dışı kopyada, saati kaydıran ön yüklemeyle (`Date.now` ve argümansız `new Date()`). 26 Kas 13:30:00Z, 14:23:00Z, 14:28:30Z; Cmt 28 Kas 14:00Z; 6 Tem 13:00Z → 29/30, `not ok 24`, `error: 'red'`. 13:29:00Z, 14:29:30Z, 16:00Z, 5 Oca 13:50:03Z → 30/30. |
| 3 | Yeni test belirlenimli | sağlandı | Aynı 12 sahte saatte (pencere içi, hafta sonu, yaz, 8 Mar ve 1 Kas yaz saati anları, yıl sonu) yeni dosya 30/30. `worker.js`'te argümansız `new Date()` yok; saat yalnız `now()` ile okunur (s. 266, 295, 297, 316). Varsayılan parametre çağrı anında değerlenir, sahte `Date.now` alınır: kanıt iki ayrı an için `started` eşitliği ve M06. |
| 4 | Zayıflama yok | sağlandı | Korunan: tek log kaydı, JSON ayrıştırma, `cron`, token yokluğu, `fetch` 404. Sıkılaşan: `result` kümesi yerine yol başına kesin değer. Yeni: `started`, `window`. Düşen iddia yok. |
| 5 | Mutasyon | sağlandı | Aşağıdaki tablo: 12/14 yakalandı; yakalananların hepsinde test 24 kırıldı. |
| 6 | Sahte küresel hijyeni | sağlandı | `try/finally` üçünü de geri yükler. Kopyaya eklenen 31. test (dosya sonunda üçü de orijinal mi): normalde 31/31; `scheduled` fırlatırken test 24 kırmızı, 31. test yeşil. Worktree'de gerçek saatle 3 × 30/30. |
| 7 | Saate bağlı başka test | sağlandı (bulgu yok) | Dosyada `worker.scheduled` tek yerde, `start(` tek yerde (`go`, sabit `h.now`); `Date.now` yalnız `scheduledAt` içinde. `tests/test_architecture.py` starter testi durağan dosya okur, saat çağrısı yok (grep; koşulmadı). |
| 8 | Düşmanca itirazlar | sağlandı (notlarla) | Commit mesajının olgu cümleleri kodla uyumlu; N2–N4. CI gözlemi cümlesi doğrulanmadı. |

## Mutantlar (`worker.js`, tek satır; worktree dışı bayt-aynı kopyada)

| Mutant | Yeni test | Kırılan | Eski test: 16:00Z (dış) / 5 Oca 13:50Z (iç) |
|---|---|---|---|
| M01 pencere dışı sonucu `secret-yok` | yakalandı | 7, 24 | 7, 24 / 7 |
| M02 pencere dışı denetimi yok (`if (false)`) | yakalandı | 7, 24 | 7, 24 / 7 |
| M03 engel yolu sonucu `liste-okunamadi` | yakalandı | 10, 12, 20, 24 | 10, 12, 20 / 10, 12, 20, 24 |
| M04 `scheduled` log yazmaz | yakalandı | 24 | 24 / 24 |
| M05 `scheduled` `cron`'u düşürür | yakalandı | 24 | 24 / 24 |
| M06 varsayılan saat `new Date().getTime()` | yakalandı | 24 | kaçtı / kaçtı |
| M07 token log satırına sızar | yakalandı | 24 | 24 / 24 |
| M08 saat yerine `scheduledTime` | yakalandı | 7, 24 | 7 / 7 |
| M09 `scheduled` iki satır yazar | yakalandı | 24 | 24 / 24 |
| M10 `fetch` işleyicisi 200 | yakalandı | 24 | 24 / 24 |
| M11 `scheduled` `env` geçirmez | yakalandı | 24 | kaçtı / 24 |
| M12 `window` alanı hep `icinde` | yakalandı | 7, 24 | 7 / 7 |
| M13 `scheduled` `scheduledTime`'ı düşürür | **kaçtı** | — | kaçtı / kaçtı |
| M14 log girintili, çok satırlı JSON | **kaçtı** | — | kaçtı / kaçtı |

## Notlar (hiçbiri engel değil)

- **N1.** M13 ve M14 eskiden beri kaçıyor: `line.scheduled` sınanmıyor; test adı "tek satir JSON" diyor ama
  satır sonu iddiası yok. Takip işinde iki iddia yeter (`!logged[0].includes("\n")`, `line.scheduled`).
- **N2.** Yorumdaki "Pencere disi …: hic istek yok" bu testte doğrudan sayılmıyor (sahte fetch çağrı saymaz).
  Dolaylı korunuyor: M02 test 24'te sonuçla, test 7'de çağrı sayısıyla kırılıyor.
- **N3.** Commit mesajındaki "bir saat" kesin olarak 59 dakika: kışın 13:30:00–14:29:00Z (dahil), yazın
  12:30–13:29Z. Hafta sonu ve tatiller dahil (`start` hafta gününe bakmaz; cumartesi sahte saatinde üretildi).
  `starter` işi `schedule` olayında koşmadığı için kırmızı yalnız o aralıkta koşan push/PR işlerinde görülür.
- **N4.** `scheduledAt(nowMs)` adındaki "At" duvar saatidir, `scheduledTime` değil (o hep `WINTER`; pencere
  dışı örnekte planlanan an saatten iki saat ileride). Zararsız; M08'i test 24'te yakalatan da bu.
- **N5.** PR açıklaması için: pencere dışında yeniden koşmak düzeltme olmadan da yeşil verir; "yeniden koştum,
  geçti" kanıt sayılmaz. Bu commit main'e girince açık PR'lar (yazara göre #63) main'i almalı.

## Doğrulanmadı

- PR #63 CI koşusunun kendisi (`8f855cc`, 14:23Z) ve yazarın 14:26Z yerel koşusu: ağa ve GitHub'a bakılmadı.
  Yerel tutarlılık: `8f855cc` 14:22:23Z'de atılmış ve `origin/claude/killswitch-fix` üzerinde; sahte
  14:23:00Z'de aynı kırmızı üretildi.
- Eski testin GERÇEK saatle kırıldığı: kurul koşusu 14:30:10Z'ye kaldı (pencere 14:29:00Z'de kapandı), eski
  test 30/30 verdi. Kanıt yalnız sahte saatle.
- `make check` ve `tests/test_architecture.py` koşulmadı (ortamda pytest bulunamadı). Python dosyası
  değişmedi; testin okuduğu `worker.js` ve `ci.yml` main ile aynı.
- CI runner'ındaki Node sürümü (yerelde v22.23.5).

Worktree'ye dokunulmadı: sonda `git status --short` boş, `HEAD` = `6f0207d772a7…`.
