-- Uzun sureli, gozetimsiz calisma icin dayaniklilik duzeltmeleri.
--
-- 1) orders tablosunun birincil anahtari client_order_id oluyor.
--    Sebep: client_order_id'yi BIZ uretiyoruz, emir gonderilmeden ONCE.
--    broker_order_id ise ancak broker cevap verdikten sonra biliniyor.
--    Emri once kaydedip sonra gondermek (write-ahead), gonderim ile
--    kayit arasinda surec olurse emrin sahipsiz kalmasini engelliyor.
--
-- 2) fills tablosu artik gercekten yaziliyor ve broker_order_id ile
--    tekil: mutabakat ayni gerceklesmeyi kac kez gorurse gorsun bir
--    kez duser.
--
-- 3) daily_state, kill-switch'in surec yeniden baslasa bile
--    hatirlanmasini sagliyor. Bellekte tutulan bir bayrak, systemd
--    restart sonrasi kill-switch tetiklenen gunde sistemin yeniden
--    islem acmasina yol aciyordu.

CREATE TABLE orders_v2 (
    client_order_id TEXT PRIMARY KEY,
    broker_order_id TEXT UNIQUE,
    decision_id     TEXT REFERENCES decisions(decision_id),
    run_id          TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    entry_type      TEXT NOT NULL,
    limit_price     REAL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    -- submitting | accepted | filled | canceled | rejected | expired | unknown
    status          TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    updated_at      TEXT
);

INSERT INTO orders_v2 (
    client_order_id, broker_order_id, decision_id, run_id, symbol, side, qty,
    entry_type, limit_price, stop_loss, take_profit, status, submitted_at, updated_at
)
SELECT
    client_order_id, broker_order_id, decision_id, NULL, symbol, side, qty,
    entry_type, limit_price, stop_loss, take_profit, status, submitted_at, updated_at
FROM orders;

DROP TABLE fills;
DROP TABLE orders;
ALTER TABLE orders_v2 RENAME TO orders;

CREATE INDEX idx_orders_decision ON orders(decision_id);
CREATE INDEX idx_orders_symbol_status ON orders(symbol, status);

-- Gerceklesmeler: denetim izi. Yabanci anahtar YOK, cunku bracket
-- bacaklarinin client_order_id'sini broker uretiyor; bizim emir
-- tablomuzda karsiliklari bulunmuyor.
CREATE TABLE fills (
    broker_order_id TEXT PRIMARY KEY,
    client_order_id TEXT,
    run_id          TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             REAL NOT NULL,
    price           REAL NOT NULL,
    filled_at       TEXT NOT NULL,
    order_type      TEXT NOT NULL
);

CREATE INDEX idx_fills_symbol_time ON fills(symbol, filled_at);

-- Gun bazli durum. Kill-switch tetiklendiginde buraya yazilir ve
-- gunun geri kalaninda surec kac kez yeniden baslarsa baslasin
-- sistem islem acmaz.
CREATE TABLE daily_state (
    trade_date  TEXT PRIMARY KEY,
    halted_at   TEXT NOT NULL,
    halt_reason TEXT NOT NULL,
    run_id      TEXT
);
