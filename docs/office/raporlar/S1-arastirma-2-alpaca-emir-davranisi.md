# S1 — Araştırma 2: Alpaca emir davranışı (dış kaynak) ve kodla karşılaştırma

Tarih: 2026-11-25. Birim: Araştırma 2. Salt okuma; Alpaca'ya ya da başka brokera/veri API'sine
istek atılmadı, emir gönderilmedi, depo değiştirilmedi (bu rapor dışında), `.env` okunmadı.
İncelenen kod: `wt-a1` çalışma kopyası (PR #63 dalı, HEAD `a48daae`). SDK: `alpaca-py` 0.44.0.

## Sonuç

1. **Soru 2'nin cevabı kodun varsayımını bozuyor (etiket: İKİNCİL).** Tam dolumdan sonra Alpaca
   hedef bacağını `new`, stop bacağını `held` gösteriyor; `held` emir `status=open` listesine
   girmiyor. Dört bağımsız kaynak aynı şeyi söylüyor (Alpaca forum yanıtları, Alpaca depolarındaki
   iki kullanıcı kaydı, Ekim 2026 tarihli üçüncü taraf paper ölçümü). Birincil belge bunu yazmıyor.
2. **Sonuç:** `list_open_orders` (düz, `status=open`) stop bacağını hiç göremez. İptal/dolum
   yarışında giriş tam dolarsa `stop_coverage` her seferinde `NONE` döner ve gün kapanır.
   `held`i `PROTECTIVE_STATUSES`e eklemek tek başına yetmez; önce bacakların okunma yolu değişmeli.
3. **Kısmi dolan girişte çalışan stop yok (DOĞRULANDI).** Bacaklar ancak ebeveyn *tamamen* dolunca
   etkinleşir; gruptaki bir emir iptal olursa kalanlar da iptal olur. Kod bu durumu yalnız iptal
   yarışında denetliyor; iptalsiz kısmi dolumda denetim yok.
4. Paper dolumları, hesap türünden bağımsız NBBO'ya göre simüle edilir; kararlarımız IEX'ten.
   Uygun emirlerin %10'u rastgele boyutta kısmi dolar: madde 3 paper'da düzenli görülecek.
5. `held` stopun gerçekten tetiklendiğine dair birincil kaynak yok; ilk paper günlerinde gözlenmeli.

Etiket özeti (soru düzeyi): **DOĞRULANDI 7** (1, 3, 4, 5, 6, 7, 8), **İKİNCİL 1** (2),
**DOĞRULANMADI 0**. Alt noktalarda doğrulanamayanlar ilgili soruda ve son bölümde yazılı.

## Kaynak anahtarı ve erişim sınırı

- **[SDK]** kurulu paket: `…/scratchpad/verify-venv/lib/python3.12/site-packages/alpaca/`.
- **[OAS]** Alpaca'nın güncel OpenAPI tanımı: `github.com/alpacahq/alpaca-mcp-server` @ `9daa38c`
  (2026-11-13), `src/alpaca_mcp_server/specs/trading-api.json` ve `market-data-api.json`.
  `scripts/sync-specs.sh` bunları `docs.alpaca.markets/openapi/*.json` adresinden çekiyor.
- **[BELGE]** Alpaca'nın resmî belge deposu: `github.com/alpacahq/alpaca-docs` @ `2080c5e`
  (2025-04-10), `content/…`. Eski belge sitesinin kaynağıdır; güncel sayfa bu ortamdan
  açılamadı. Bracket ve yaşam döngüsü cümlelerinin güncel sayfada da durduğu arama
  sonuçlarından görüldü, birebir karşılaştırma yapılamadı.
- **[KAYIT]** `github.com/alpacahq/alpaca-py` @ `d63ecab` (2026-11-23), `consumer_checks/`:
  SDK ekibinin paper API'den kaydettiği gerçek istek/yanıtlar (kayıt tarihi 2026-11-09).
- **[C#]** `github.com/alpacahq/alpaca-trade-api-csharp` (`develop`), `Alpaca.Markets/Enums/OrderStatus.cs`.
- **[FORUM]** `forum.alpaca.markets`. Sayfalar açılamadı; alıntılar web arama sonucunun aktardığı
  parçalardır. Birebirliği doğrulanamadı, bu yüzden hepsi İKİNCİL.
- **[KAYIT-KULLANICI]** Alpaca depolarındaki issue gövdeleri (kullanıcı raporu; yorumlar okunamadı).
- **[3T]** `github.com/dd-jp/samurai-trading-system` PR #2088 (2026-10-07): üçüncü taraf, paper
  hesapta salt okuma GET ile ölçüm.

`docs.alpaca.markets` ve `forum.alpaca.markets` bu oturumda DNS hatası verdi (ENOTFOUND; ağ izin
listesi dışında). Tekrar denenmedi. Birincil kaynakları doğrudan okumak için bu iki alan adının
oturum ağ ayarlarında izinli olması gerekir.

## 1. Emir durumları — DOĞRULANDI

**Cevap.** Terminal: `filled`, `canceled`, `expired`, `rejected` (dördü için "no further updates").
`replaced` eski emir kimliği için fiilen terminal: yerine yeni kimlikli emir geçer (çıkarım:
[SDK] `Order.replaced_by`). Terminal değil: `done_for_day`, `calculated`, `stopped`, `suspended`,
`pending_cancel`, `pending_replace`, `accepted`, `pending_new`, `accepted_for_bidding`, `held`.
Borsada çalışan: `new`, `partially_filled`. Borsaya ulaşmış ama henüz çalışmayan: `pending_new`,
`accepted_for_bidding`. Alpaca'da bekleyen: `accepted`, `held`.

**Kanıt.** [OAS] `components.schemas.OrderStatus.description` (aynı metin [BELGE]
`content/trading/orders.md:442-498`):
- "`new` The order has been received by Alpaca, and routed to exchanges for execution."
- "`filled` The order has been filled, and no further updates will occur for the order."
- "`done_for_day` The order is done executing for the day, and will not receive further updates until the next trading day."
- "`accepted` The order has been received by Alpaca, but hasn't yet been routed to the execution venue."
- "`pending_new` The order has been received by Alpaca, and routed to the exchanges, but has not yet been accepted for execution."
- "An order may be canceled through the API up until the point it reaches a state of either filled, canceled, or expired."

**`held`.** Enum üyesi ([OAS] `OrderStatus.enum[16]`; [SDK] `trading/enums.py:172`) ama yaşam
döngüsü metninde tanımı **yok**. Tek resmî tanım SDK yorumu: "Order held pending trigger event." [C#].
**Ek.** [SDK] 0.44.0'da `PENDING_REVIEW = "pending_review"` de var (`enums.py:164`); güncel [OAS]
listesinde yok, `alpaca-py` master'da "no longer a valid order status" diye kaldırılıyor.
**Gözlem.** Belge `pending_new` için "rare" diyor; [KAYIT] `recordings/trading.limit_order_lifecycle.json`
paper'da POST yanıtının `"status": "pending_new"`, hemen sonraki GET'in `"new"` olduğunu gösteriyor.

## 2. Bracket bacaklarının durumu — İKİNCİL (alt nokta (i) DOĞRULANDI)

**(i) Ebeveyn dolmadan önce: iki bacak da `held`. DOĞRULANDI.** [OAS]
`components.examples.BracketOrderResponse`: ebeveyn `"status": "accepted"`, `"filled_qty": "0"`;
`legs[0]` `"group_role": "take_profit"`, `"status": "held"`; `legs[1]` `"group_role": "stop_loss"`,
`"status": "held"`. [BELGE] `orders.md:242-243`: "The second and third orders won't be active until
the first order is completely filled."

**(ii) Ebeveyn kısmi dolmuşken: bacaklar etkin değil. DOĞRULANDI (etkin olmadığı); durum adı
`held` kalıyor — İKİNCİL.** [BELGE] `orders.md:190-191`: "once it is completely filled, two
conditional exit orders are activated." [FORUM] `t/…/11938` ya da `t/…/11641` (arama parçası):
"Once the parent order completely fills (ie not a partial fill) the typical state would be the take
profit limit order leg is set to new and the stop loss leg remains held."

**(iii) Tam dolumdan sonra: hedef `new`, stop `held`; aynı anda yalnız biri borsada. İKİNCİL.**
- [FORUM] `t/half-of-bracket-order-held/2727`, `t/…/11938` (arama parçaları): "The stop loss order
  remains held, but in the background, the stop loss price for that order is being monitored." /
  "Technically only the take profit limit order has been sent to an execution venue for execution.
  There can only be one open order waiting for execution at any given time".
- [KAYIT-KULLANICI] `alpacahq/alpaca-py#198` (2022): "the main long or short order has a "Filled"
  status, the stop loss has a "Held" status, and the take profit has a "New" status (all as
  expected). If the stop loss price is hit, the take profit order status changes to "Replaced" and
  the stop loss order status changes to "Filled"."
- [3T]: "After a bracket's entry fills, Alpaca keeps the stop-loss leg `held` and moves the
  take-profit to `new`."
- Birincil belgedeki gerekçe bununla uyumlu ([BELGE] `orders.md:201-205`): "you would not be able
  to submit two conditional closing orders since Alpaca's system would view one of the two orders
  as exceeding the available position quantity. … Alpaca's system recognizes the entry and exit
  orders as a group and queues them for execution appropriately."

**`held` stop fiilen kurulu mu? İKİNCİL; tetiklendiği DOĞRULANMADI.** Forum açıklamasına göre
stop fiyatı Alpaca tarafında izlenir; fiyat gelince hedef iptal edilir, stop `held`→`new` olur.
Karşı kayıtlar var: tetiklenmeyen `held` bacak raporları (`t/…/3697`, `t/…/11097`; ikincisi hedef
kısmi dolduktan sonra). [3T] da açık bırakıyor: "The one unproven part: no stop has triggered on
paper yet." Stop borsada duran bir emir değildir; koruma Alpaca'nın iç izlemesine dayanır.

**Bacaklar API'de nasıl döner?**
- İç içe: [BELGE] `orders.md:258-261`: "Each order of the group is reported as an independent order
  in GET /v2/orders endpoint. But if you specify additional parameter nested=true, the order
  response will nest the result to include child orders under the parent order with an array field
  legs". [SDK] `trading/requests.py:207`, `222-229` (`GetOrdersRequest.nested`, `GetOrderByIdRequest.nested`).
- **`held` emir `status=open` listesinde yok — İKİNCİL.** [3T]: "Alpaca's `GET /v2/orders?status=open`
  leaves out orders whose status is `held`." (ölçüm: `status=open`, nested açık ya da kapalı,
  yalnız hedefi döndürdü; `status=all` `held` stopu içerdi). [KAYIT-KULLANICI]
  `alpaca-trade-api-python#322` (2020): "only the limit sell order is seen as an open order, while
  sell stop limit order is seen as a closed order with 'Held' status." `alpaca-trade-api-js#87`
  (2020): "I **cannot see the stop_loss order** whether I use `nested: true` or not."
- Yeni alanlar: [OAS] `Order.group_id`, `group_role` (`entry`/`take_profit`/`stop_loss`). [SDK]
  0.44.0 `Order` modelinde bu alanlar yok; master'da var.

## 3. Bracket + ebeveynin kısmi dolumu — DOĞRULANDI (kural); fiilî durum gözlenmeli

**Cevap.** Bacaklar kısmi miktar için etkinleşmez; yalnız tam dolumda. Ebeveyn kısmi dolumdan sonra
iptal edilirse grup kuralı gereği bacaklar da iptal olur; dolan miktar stopsuz kalır. Belgede
bacak miktarının dolan miktara indirildiğine dair hiçbir ifade yok.
**Kanıt.** [BELGE] `orders.md:245`: "If any one of the orders is canceled, any remaining open order
in the group is canceled." `orders.md:254-255` yalnız çıkış tarafını anlatıyor: "If the take-profit
order is partially filled, the stop-loss order will be adjusted to the remaining quantity."
**İKİNCİL.** [FORUM] `t/…/19417` (2026; arama özeti, birebir değil): giriş hâlâ açıkken dolan miktar
için ayrı bir stop konamıyor; giriş tamamlanana kadar dolan hisseler korumasız.
**DOĞRULANMADI.** Kısmi dolum + iptal sonrası bacakların gösterdiği durum (`canceled` mi, `held`
mi kalıyor) ve bu emirde `filled_at` alanının dolup dolmadığı. Denenen: [OAS], [BELGE], forum araması.

## 4. İptal semantiği — DOĞRULANDI

**Cevap.** İptal bir *istektir*, asenkron kesinleşir; reddedilebilir. 204 "iptal edildi" demek
değildir. Gruptaki bir emrin iptali kalan açık emirleri de iptal eder.
**Kanıt.**
- [OAS] `DELETE /v2/orders/{order_id}`: "Attempts to cancel an Open Order. If the order is no longer
  cancelable, the request will be rejected with status 422; otherwise accepted with return status 204."
- [OAS] `OrderStatus`: "`pending_cancel` The order is waiting to be canceled." /
  "`pending_replace` … The order will reject cancel request while in this state."
- [BELGE] `content/api-references/trading-api/streaming.md:175,180`: "`pending_cancel`: Sent when the
  order is awaiting cancelation. Most cancelations will occur without the order entering this
  state." / "`order_cancel_rejected`: Sent when the order cancel has been rejected."
- [OAS] `DELETE /v2/orders`: 207, emir başına durum; "If an order is no longer cancelable, the
  server will respond with status 500 and reject the request."
- [KAYIT] `consumer_checks/scenarios/trading.py:127-135`: SDK ekibi iptalden sonra durumu 10 kez
  1 sn arayla okuyup `canceled` bekliyor. `trading_positions.py:153`: "It may fill between the last
  poll and the cancel: read it again." Kayıtta paper'da ilk okuma zaten `canceled`.
**Sınır.** "204'ten sonra emir dolabilir" cümlesi belgede birebir yok; `pending_cancel` ve
`order_cancel_rejected` olaylarının varlığından çıkarılıyor. Kodun bugünkü varsayımıyla uyumlu.

## 5. `close_position` / `close_all_positions(cancel_orders=True)` — DOĞRULANDI

**Cevap.** `close_position` pozisyonu kapatan tek bir emir yaratır; açık emirleri iptal etmez.
Hisseler açık emirlerce tutuluyorsa 403 döner. `cancel_orders=true` yalnız "hepsini kapat" ucunda var.
**Kanıt.**
- [OAS] `DELETE /v2/positions/{symbol_or_asset_id}`: "Closes (liquidates) the account's open position
  for the given symbol. Works for both long and short positions."
- [OAS] `DELETE /v2/positions`, `cancel_orders`: "If true is specified, cancel all open orders before
  liquidating all positions." Yanıt 207: "`body` is the closing Order when `status` is 200,
  otherwise the error describing why that position was not closed."
- [OAS] aynı ucun "Partially Closed" örneği: `status` 403, `code` 40310000, "insufficient qty
  available for order (requested: 10, available: 2)". `ClosePositionError.held_for_orders`:
  "Position quantity held by open orders. Present only on insufficient-quantity rejections."
- [SDK] `trading/models.py:269-286` (`FailedClosePositionDetails.held_for_orders`),
  `trading/client.py:271-294`.
- "Pozisyon yok" metni: `alpaca-trade-api-go` @ `6d5cd54`, `examples/mean-reversion/mean-reversion.go:190`:
  `apiErr.Message != "position does not exist"`.
**DOĞRULANMADI.** `DELETE /v2/orders` yanıtının `held` bacakları ayrı satır olarak içerip içermediği.

## 6. Paper simülasyonu — DOĞRULANDI ([BELGE] sürümüyle; güncel sayfa açılamadı)

**Cevap.** Dolumlar gerçek zamanlı kotasyona göre, hesap türünden bağımsız NBBO'ya göre simüle
edilir. Emir yalnız pazarlanabilir olunca dolar; miktar NBBO boyutuyla sınanmaz; uygun emirlerin
%10'u rastgele boyutta kısmi dolar.
**Kanıt.** [BELGE] `content/trading/paper-trading.md`:
- `:14-15` "the system simulates the order filling based on the real-time quotes."
- `:99-100` "When orders are eligible to be filled, they will receive partial fills for a random
  size 10% of the time. If the order price is still marketable, the remaining quantity would be
  re-evaluated for a subsequent fill."
- `:97` "Your order quantity is not checked against the NBBO quantities."
- `:101-102` "Regardless of whether you have a Paper Trading Only account or a real money brokerage
  account, all orders submitted in paper trading will be matched against the best available current
  market price (NBBO)."
- `:31-39` paper şunları hesaba katmaz: "Market impact of your orders", "Information leakage of your
  orders", "Price slippage due to latency", "Order queue position (for non-marketable limit orders)",
  "Price improvement received", "Regulatory fees", "Dividends".
**Ücretsiz plan dolum verisini değiştirir mi?** Hayır (yukarıdaki `:101-102`; ayrıca İKİNCİL,
[FORUM] `t/…/14303` arama özeti: veri aboneliği dolumu etkilemez). Değişen bizim *gördüğümüz*
veridir: [BELGE] `content/trading/account-plans.md:17-18`: "you are only entitled to receive and
make use of IEX market data."
**DOĞRULANMADI.** Paper'da stopun kotasyonla mı işlemle mi tetiklendiği. Canlı için [BELGE]
`orders.md:514`: "Stop orders and trailing stops are elected on the consolidated print."

## 7. Piyasa verisi planları — DOĞRULANDI (işlem API sınırı İKİNCİL)

**Cevap.** Ücretsiz planda gerçek zamanlı yalnız IEX. SIP ücretsiz planda 15 dakika gecikmeli
(`delayed_sip`) ve son 15 dakika hariç geçmiş veri olarak alınabilir.
**Kanıt.** [OAS] `market-data-api.json`:
- `components.parameters.stock_latest_feed`: "`delayed_sip`: SIP with a 15 minute delay" /
  "Default: `sip` if the user has the unlimited subscription, otherwise `iex`."
- `components.parameters.end`: "Default: the current time if the user has a real-time access for
  the feed, otherwise 15 minutes before the current time."
- `components.responses.429`: "Too many requests. You hit the rate limit. Use the X-RateLimit-...
  response headers".
- [BELGE] `content/market-data/_index.md:40-48` (Free sütunu): "Real-time market coverage | IEX",
  "Websocket subscriptions | 30 symbols", "Historical data delay | 15 minutes", "Historical API
  calls | 200/min". Güncel sayfa için arama özeti aynı sayıları veriyor (plan adı artık "Basic").
- [KAYIT] `consumer_checks/README.md:265`: "the feeds every paper account has: IEX for stocks".
**İKİNCİL.** İşlem API'si sınırı ayrı ve 200 istek/dk (`alpaca.markets/support/usage-limit-api-calls`
ve forum; arama özeti). Birincil metin okunamadı.

## 8. Bracket kısıtları: TIF, uzatılmış seans, fiyat adımı, kesirli hisse — DOĞRULANDI

- **TIF ve uzatılmış seans.** [BELGE] `orders.md:248-249`: "Extended hours are not supported.
  `extended_hours` must be "false" or omitted." / "`time_in_force` must be "day" or "gtc"."
- **Bacak geometrisi.** `orders.md:246`: "`take_profit.limit_price` must be higher than
  `stop_loss.stop_price` for a buy bracket order, and vice versa for a sell."
- **Stop eşiği (ret sebebi).** `orders.md:339-344`: "The stop price input has to be at least $0.01
  below (for stop-loss sell, above for buy) than the "base price"." Taban fiyat: limit girişte giriş
  limiti; ayrıca "the current market price".
- **Kuruş altı adım.** `orders.md:124-126`, `154-156`: "Limit price >=$1.00: Max Decimals= 2",
  "Limit price <$1.00: Max Decimals = 4" (stop için aynı). Gerçek yanıt, [KAYIT]
  `recordings/errors.rejected_orders_raise_api_error.json`: 422, `code` 42210000, "invalid
  limit_price 1.0001. sub-penny increment does not fulfill minimum pricing criteria".
- **Kesirli hisse.** [OAS] `CreateOrderRequest.qty`: "Can be fractionable for only market and day
  order types." Bracket ile kesirli miktar reddi İKİNCİL ([FORUM] `t/…/14600`: "fractional orders
  must be simple orders").
- **Alış yönlü stop (açığa satışın stopu).** `orders.md:141-143`: "Alpaca converts buy stop orders
  into stop limit orders with a limit price that is 4% higher than a stop price < $50 (or 2.5%
  higher than a stop price >= $50)." Bracket bacağına uygulandığı DOĞRULANMADI.
- **Çift dolum.** `orders.md:195-197`: "in extremely volatile and fast market conditions, both
  orders may fill before the cancellation occurs."

## Kodla karşılaştırma

Yollar `wt-a1` köküne göre. Önem sırasıyla.

**K1 — Tam dolum yarışında stop görünmüyor; gün her seferinde kapanır.**
`src/tlab/execution/alpaca_broker.py:182-194` (`status=OPEN`, `nested` yok),
`src/tlab/engine/runner.py:768` (`_fill_coverage` bu listeyi kullanıyor), `:88`, `:153-173`.
Soru 2'ye göre liste yalnız hedef bacağını (`new`, `stop_price` yok) döndürür; `held` stop listede
yoktur. `stop_coverage` → `NONE` → `_halt_unprotected` → gün kapanır ve pozisyon piyasa emriyle
kapatılır. Güvenli ama her yarışta bir gün kaybı. `held`i pozitif listeye eklemek bunu çözmez.
*Öneri:* (a) Koruma kontrolünde ebeveyni `get_order_by_id(id, GetOrderByIdRequest(nested=True))`
ile oku, `legs`'i `OrderRef`e taşı (ya da `status=ALL, nested=True, symbols=[…], limit=500`).
(b) Stop bacağını koruma say ⇔ ebeveyn `filled` **ve** bacak `stop_price` taşıyor **ve** durumu
`new`/`partially_filled`, ya da `held` iken kardeş hedef bacağı `new`/`partially_filled`.
Ebeveyn `filled` değilse `held` asla koruma değil. (c) Kanıt ikincil olduğu için (b) ayrı kararla
ve ilk gözlenen stop tetiklenmesinden sonra açılsın; (a) şimdiden yapılıp durumlar loglanabilir.

**K2 — İptalsiz kısmi dolumda çalışan stop yok ve hiçbir denetim yok.**
`runner.py:548` (pozisyonu olan sembol atlanıyor), `docs/designs/unattended-paper.md:141`
("job yoksa koruma bacakları borsada"), `:227-229`, `:301-302`. Soru 3'e göre kısmi dolan girişin
bacakları etkin değildir; süreç ölürse dolan miktarın hiçbir stopu olmaz. Gün sonunda `day` giriş
iptal olunca bacaklar da iptal olur. Paper'da uygun emirlerin %10'u kısmi dolar (soru 6).
*Öneri:* her turda her pozisyon için koruma kontrolü; ebeveyn `partially_filled` ise kalan miktarı
iptal et, iptal kesinleşince dolan miktar için `order_class=oco` çıkış çifti gönder ya da kapat.
Tasarım belgesindeki cümle "tam dolan girişte" diye daraltılmalı.

**K3 — `_flatten_all` `held` bacağı göremez; toplu iptal yanıtı denetlenmiyor.**
`runner.py:971-978`, `alpaca_broker.py:258-266`. `remaining` `status=open`'dan geldiği için `held`
stop `blocked` kümesine girmez; kapatma, stopun iptali doğrulanmadan gidebilir. Güvence yalnız
grup kuralıdır (soru 4). `cancel_open_orders` 207 gövdesindeki emir başına durumu saymıyor,
`len()` döndürüyor; tek emir iptal edilemezse uç 500 döner ve tur boşa geçer.
*Öneri:* 207 satırlarında 2xx olmayanları ayır; kapatmadan önce pozisyonu olan sembollerde
bacakların terminal olduğunu iç içe okumayla doğrula; 403 `held_for_orders` yanıtını "iptal
kesinleşmedi" olarak ayrı logla.

**K4 — `replaced` terminal sayılmıyor.** `runner.py:71`, `:144-150`. Stop tetiklenince hedef
bacağının `replaced` olduğu bildiriliyor (soru 2, İKİNCİL). K1 düzeltmesi `status=all` okursa bu
emir listeye girer; `may_still_execute` onu "gerçekleşebilir" sayar ve `_has_orphan_exit` günü
gereksiz kapatır. *Öneri:* `replaced`i `TERMINAL_ORDER_STATUSES`e ekle.

**K5 — Açık emir listesinde sayfa sınırı.** `alpaca_broker.py:187-189` `limit` vermiyor; [OAS]:
"Defaults to 50 and max is 500." 50'den fazla açık emirde liste sessizce kesilir. *Öneri:* `limit=500`.

**K6 — Kısmi dolup iptal olan giriş gerçekleşme listesinden düşebilir (DOĞRULANMADI).**
`alpaca_broker.py:361-365` `filled_at` boşsa emri atlıyor. Kısmi dolup iptal edilen emirde bu alanın
dolduğu doğrulanamadı; boşsa dolum journal'a ve `_unexplained_day` kontrolüne girmez.

**K7 — Karar verisi IEX, dolum NBBO.** `config/base.yaml:14` (`feed: iex`). Limit giriş fiyatı IEX
barından türüyor; paper dolumu NBBO'ya göre. Fark hata değil, beklenen sapma; ölçümde ayrı tutulmalı.

**K8 — Kayıp yanıtlı emir yalnız açık listede aranıyor.** `runner.py:494-499`. Yanıtı kaybolan giriş
bir sonraki turdan önce tam dolarsa açık listede olmaz ve süre sonunda `lost` yazılır. [OAS]
`GET /v2/orders:by_client_order_id` var. *Öneri:* çözümlemede `get_order_by_client_id` kullan.

**Uyumlu bulunanlar.** TIF yalnız `day`/`gtc`, `extended_hours` gönderilmiyor
(`alpaca_broker.py:220-222`); miktar tam sayı (`core/types.py:364`); fiyat yuvarlama kuruş altı
kuralıyla aynı (`core/types.py:90-97`); iptalin asenkron sayılması ve sonucun girişin kendi
durumundan çıkarılması (`runner.py:707-751`); `accepted`/`pending_new`/`accepted_for_bidding`
geçiş sayılması; "position does not exist" eşlemesi (`alpaca_broker.py:383-386`).

## İlk paper günlerinde gözlenecekler

Belge bunları çözemiyor. Hepsi kayıtlı yürütme kararıyla, tek sembol ve en küçük miktarla.

1. Tam dolumdan sonra `GET /v2/orders/{ebeveyn}?nested=true`: hedef ve stop bacağının durumu.
   Aynı anda düz `status=open` ve `status=all` listelerinde stop bacağı var mı.
2. Bir stop tetiklenmesi: `held` stop doluyor mu; durum sırası (`held`→`new`→`filled`), hedefin son
   durumu (`canceled` mi `replaced` mi), fiyatın stopu geçmesi ile dolum arasındaki süre.
3. Kısmi dolan giriş: o sıradaki bacak durumları. Ardından giriş iptal edilince bacakların durumu
   ve miktarı, pozisyonun stopsuz kalıp kalmadığı, ebeveynde `filled_at`.
4. İptal: 204'ten sonra `pending_cancel` görülüyor mu, ne kadar sürüyor; dolmuş emre iptalde 422.
5. Dolmuş bracket varken `DELETE /v2/orders`: 207 gövdesinde hangi kimlikler var; hemen ardından
   `close_position` 403 `held_for_orders` veriyor mu, kaç tur sürüyor.
6. Seans kapanışında `day` bacakların ve kısmi dolmuş girişin son durumu (`expired`/`canceled`).
7. Dolum fiyatı ile aynı andaki IEX kotasyonu arasındaki fark; kısmi dolum sıklığı.
8. POST yanıtındaki ilk durum ve `new`e geçiş süresi (`MAX_COVER_WAIT_TURNS` için).
9. İşlem API yanıtlarındaki `X-RateLimit-*` başlıkları ve tur başına istek sayısı.
10. `nested=true` listede `limit` bacakları da sayıyor mu ([3T] öyle ölçmüş).

## Doğrulanamayanlar

- `held` stopun tetiklenip dolduğu (birincil kaynak yok; forum "evet", karşı kullanıcı raporları var).
- `status=open` listesinin `held` emirleri bugün de dışarıda bıraktığı (en yeni kanıt [3T], Ekim 2026).
- Kısmi dolum + ebeveyn iptalinden sonra bacakların durumu ve `filled_at`.
- Paper'da stop tetikleme verisi (kotasyon mu işlem mi); alış yönlü stop bacağının limit'e çevrilmesi.
- İşlem API hız sınırının güncel resmî metni; forum alıntılarının birebirliği.
