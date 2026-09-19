-- tlab journal - ilk sema.
--
-- Bu sema sistemin hafizasidir. Ogrenme katmani (Faz 3) tamamen bu
-- tablolarin uzerine kurulacak; bu yuzden alanlar bastan genis
-- tutuldu. Kaydedilmeyen bir alan, ileride geri donup toplanamaz.

CREATE TABLE runs (
    run_id         TEXT PRIMARY KEY,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    -- paper | live | backtest | shadow
    mode           TEXT NOT NULL,
    -- Kodun tam hangi halinin bu kararlari urettigi
    git_sha        TEXT,
    -- iex | sip : sonuclari karsilastirirken sart
    data_feed      TEXT NOT NULL,
    params_version TEXT NOT NULL,
    config_json    TEXT NOT NULL,
    notes          TEXT
);

CREATE TABLE decisions (
    decision_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    ts              TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    strategy_id     TEXT NOT NULL,
    params_version  TEXT NOT NULL,
    side            TEXT NOT NULL,
    reference_price REAL NOT NULL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    reward_risk     REAL NOT NULL,
    confidence      REAL NOT NULL,
    reason          TEXT,
    -- Risk kapisinin karari. VETO EDILEN KARARLAR DA YAZILIR:
    -- "kapi engellemeseydi ne olurdu" sorusu risk parametrelerini
    -- ogrenmenin tek yolu.
    allowed         INTEGER NOT NULL,
    qty             INTEGER NOT NULL DEFAULT 0,
    veto_reasons    TEXT,
    -- Karar anindaki tam ozellik fotografi. Ogrenmenin yakiti.
    features_json   TEXT NOT NULL,
    broker_order_id TEXT
);

CREATE INDEX idx_decisions_ts ON decisions(ts);
CREATE INDEX idx_decisions_symbol_ts ON decisions(symbol, ts);
CREATE INDEX idx_decisions_strategy ON decisions(strategy_id, allowed);
CREATE INDEX idx_decisions_run ON decisions(run_id);

CREATE TABLE orders (
    broker_order_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL UNIQUE,
    decision_id     TEXT REFERENCES decisions(decision_id),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    entry_type      TEXT NOT NULL,
    limit_price     REAL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    status          TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    updated_at      TEXT
);

CREATE INDEX idx_orders_decision ON orders(decision_id);

CREATE TABLE fills (
    fill_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_order_id TEXT NOT NULL REFERENCES orders(broker_order_id),
    ts              TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    price           REAL NOT NULL,
    -- entry | stop | target | manual
    leg             TEXT NOT NULL
);

CREATE INDEX idx_fills_order ON fills(broker_order_id);

-- Kapanmis pozisyonlar: ogrenme katmaninin okudugu asil tablo.
CREATE TABLE trades (
    trade_id           TEXT PRIMARY KEY,
    decision_id        TEXT REFERENCES decisions(decision_id),
    run_id             TEXT NOT NULL REFERENCES runs(run_id),
    symbol             TEXT NOT NULL,
    strategy_id        TEXT NOT NULL,
    params_version     TEXT NOT NULL,
    side               TEXT NOT NULL,
    qty                INTEGER NOT NULL,
    entry_ts           TEXT NOT NULL,
    entry_price        REAL NOT NULL,
    exit_ts            TEXT NOT NULL,
    exit_price         REAL NOT NULL,
    planned_stop       REAL NOT NULL,
    planned_target     REAL NOT NULL,
    gross_pnl          REAL NOT NULL,
    fees               REAL NOT NULL DEFAULT 0,
    net_pnl            REAL NOT NULL,
    -- Kar/zararin riske orani. Farkli buyuklukteki islemleri
    -- karsilastirabilmenin tek dogru yolu.
    r_multiple         REAL NOT NULL,
    -- Pozisyon aleyhe/lehe en fazla ne kadar gitti: stop ve hedef
    -- mesafelerini ogrenmek icin gerekli.
    mae                REAL,
    mfe                REAL,
    entry_slippage_bps REAL,
    exit_slippage_bps  REAL,
    -- target | stop | eod_flatten | kill_switch | manual
    exit_reason        TEXT NOT NULL,
    holding_seconds    INTEGER NOT NULL
);

CREATE INDEX idx_trades_strategy ON trades(strategy_id, params_version);
CREATE INDEX idx_trades_entry_ts ON trades(entry_ts);
CREATE INDEX idx_trades_symbol ON trades(symbol);

-- Parametre setlerinin yasam dongusu. Faz 3'teki terfi kapisi burayi kullanir:
-- hicbir set backtest ve shadow asamasindan gecmeden 'live' olamaz.
CREATE TABLE params_versions (
    params_version TEXT PRIMARY KEY,
    strategy_id    TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    -- candidate | shadow | live | retired
    status         TEXT NOT NULL DEFAULT 'candidate',
    promoted_at    TEXT,
    evaluation_json TEXT
);
