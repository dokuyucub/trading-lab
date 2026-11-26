# S1 — B0: ÖN RAPOR taslağı (Koruma denetimi v2)

Taslak, 2026-11-26. Yönetim #17'ye yorum olarak gönderir; Tasarım birimi GitHub'a yazmadı. Çizginin altı gönderilecek metindir.

---

## ÖN RAPOR — Koruma denetimi v2 (tasarım notu; kod yok)

**Belge:** `docs/designs/protection-check-v2.md`, dal `claude/koruma-v2-tasarim`. Kod satırları #63 başına (`8f855cc`) göredir.

**Neden.** Bugün "bu pozisyon korunuyor mu?" sorusu yalnız giriş iptali izlenirken ve yalnız düz açık emir listesine
bakılarak soruluyor. Keşif dört açık buldu: (1) Alpaca tam dolumdan sonra stop bacağını `held` tutuyor ve `status=open`
listesinde döndürmüyor (ikincil kaynak, canlı doğrulanmadı); (2) kısmi dolan ebeveynin etkin bacağı yok (birincil
kaynak); (3) iz kapandıktan sonra görünen ya da geceye taşınan pozisyon hiç ölçülmüyor; (4) #63'ün §4 sınırları (iv),
(v), (vi) bu tasarımı işaret ediyor.

**Ne öneriyoruz.**

1. **Okuma yolu:** `get_order` iç içe (`nested`) okur, bacaklar yeni `OrderRef.legs` alanına gelir. Protokole yeni yöntem
   yok. İkinci tanık bugünkü düz liste. Tur başına ek istek: açık pozisyon başına bir.
2. **Her tur denetimi:** girişten bağımsız, her açık pozisyon için üç hükümden biri: `korunuyor`, `korunmuyor`,
   `belirsiz`. Tanım 16 satırlık bir doğruluk tablosu (belge §4), long ve short için aynı.
3. **`held` stop** (ebeveyn `filled`, hedef `new`) `belirsiz` sayılır: loglanır, eylem yok. K9 kararına ve ilk paper
   gözlemine kadar koruma sayılmaz.
4. **Dört aşama:** 0 okuma yolu (davranış aynı) → 1 her tur ölç ve logla (davranış aynı) → 2 yorum gerektirmeyen
   "canlı stop yok" durumlarını uygula → 3 `held` kuralı (paper gözlemi + K9). Paper seans işi aşama 2'den sonra.
5. **Tepki sembol düzeyinde:** korumasız bulunan pozisyonda yalnız o sembol kapatılır, gün kilitlenmez. Her tur denetimi
   kapatmayı her tur yeniden dener; durum tutmaz.
6. **Kısmi dolum:** kalan miktar mevcut giriş süresi dolunca yalnız giriş kimliğiyle iptal edilir, sonra sembol kapatılır.
7. **Kaynak yanlışsa güvenli:** her koruma testi iki görünümde koşar (stop `held` ve listede yok / stop `new` ve listede).

**Tarttığımız ve seçmediğimiz:** tur başına tek `status=all` + `nested` liste (`limit`'in bacakları sayıp saymadığı
doğrulanmadı; yeni protokol yöntemi); `held`i şimdi koruma saymak (kanıt ikincil); `held`i korumasız sayıp uygulamak
(tam dolan her pozisyon kapanır); bağımsız OCO çıkış çifti (yeni emir türü).

**Görüşünü özellikle istediğimiz kararlar** (her biri tek satırla yanıtlanabilir):

1. Okuma yolu `get_order` + `OrderRef.legs` olsun mu, yoksa tur başına tek `status=all` + `nested` liste mi?
2. `held` stop her tur denetiminde yalnız loglanıyor, iptal yarışı yolunda ise bugünkü gibi günü kapatıyor. Bu fark
   K9'a kadar kalsın mı?
3. Aşama 2'de uygulanan küme şu üç durum olsun mu: sembolde hiç emir yok; stop bacağı terminal (hedef dursa bile);
   ebeveyn tam dolmadan bitti? Eksik miktar yalnız log kalsın mı?
4. Kısmi dolan girişin kalanı mevcut `entry_order_ttl_minutes` süresi dolunca mı iptal edilsin, ilk görüldüğü turda mı?
5. Gece taşınan pozisyon ilk açık turda yalnız sembol olarak mı kapatılsın, gün de durdurulsun mu?
6. B10'da deneme sınırı `cancel_requested` satırının `updated_at` yaşından (göçsüz) türetilsin ve "devralınan istek tek
   fırsat" kuralının yerini alsın mı?
7. Backlog'dan şu sapmalar kabul mü: B7 ikiye bölünür (ölç ve logla / uygula); B5'e "emir yok" ve 403
   `held_for_orders` ayrımı eklenir; tur başında hesap okunamazken güvenli kapatma (R63 (c)) B9'a girer?

**Yanıtından önce yapılmayacaklar.** B4–B10'da kod yok. `unattended-paper.md`'ye dokunulmaz (#63 değiştiriyor). `held`
kuralı açılmaz. `config/*.yaml`, journal göçü, yeni emir türü ve yeni `ExitReason` yok. Broker çağrısı ve paper gözlemi yok.

**Yanıtını beklemeyenler:** B1, B2, B3, C8 (backlog §4 T1).

**Doğrulanmayan.** Bu not için test koşulmadı; satır numaraları `8f855cc`'de okunarak doğrulandı. Alpaca'nın `held`
davranışı, `held` stopun tetiklendiği ve kısmi dolum + iptal sonrası bacak durumları doğrulanmadı; tam liste belgenin
§9'unda. Sahip ve Codex kararı bekleyen dokuz madde §8'de; hiçbiri verilmiş sayılmıyor.
