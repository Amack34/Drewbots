-- weather.db schema export 2026-02-21T00:50:42.669901

-- forecasts: 5084 rows
CREATE TABLE forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            forecast_date TEXT NOT NULL,
            forecast_high_f REAL,
            forecast_low_f REAL,
            period_name TEXT,
            short_forecast TEXT,
            collected_at TEXT NOT NULL
        );

-- metar_daily_extremes: 12 rows
CREATE TABLE metar_daily_extremes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station TEXT NOT NULL,
            date TEXT NOT NULL,
            running_high_f REAL,
            running_low_f REAL,
            last_updated TEXT NOT NULL,
            observation_count INTEGER DEFAULT 0,
            UNIQUE(station, date)
        );

-- observations: 5282 rows
CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station TEXT NOT NULL,
            city TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            temp_f REAL,
            humidity REAL,
            wind_mph REAL,
            wind_dir INTEGER,
            pressure_mb REAL,
            cloud_cover TEXT,
            obs_time TEXT,
            collected_at TEXT NOT NULL
        );

-- orderbook_snapshots: 1263 rows
CREATE TABLE orderbook_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            snapshot_time TEXT NOT NULL,
            yes_bids TEXT,
            yes_asks TEXT,
            no_bids TEXT,
            no_asks TEXT,
            spread_cents REAL,
            yes_depth_total REAL,
            no_depth_total REAL
        );

-- paper_balance: 34 rows
CREATE TABLE paper_balance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balance_cents INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

-- paper_trades: 26 rows
CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            market_type TEXT NOT NULL,
            event_ticker TEXT NOT NULL,
            market_ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            side TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            contracts INTEGER NOT NULL,
            confidence REAL,
            edge_pct REAL,
            reason TEXT,
            current_temp_f REAL,
            forecast_temp_f REAL,
            surrounding_avg_f REAL,
            settled INTEGER DEFAULT 0,
            settlement_result TEXT,
            pnl_cents INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            settled_at TEXT
        , signal_source TEXT DEFAULT 'model');

-- prediction_log: 429 rows
CREATE TABLE prediction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    market_type TEXT NOT NULL,
    estimated_temp_f REAL NOT NULL,
    forecast_temp_f REAL,
    primary_temp_f REAL,
    surrounding_avg_f REAL,
    confidence REAL,
    std_dev REAL,
    actual_temp_f REAL,
    error_f REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    settled_at TEXT
);

-- sqlite_sequence: 9 rows
CREATE TABLE sqlite_sequence(name,seq);

-- trade_journal: 58 rows
CREATE TABLE trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT UNIQUE,
    ticker TEXT NOT NULL,
    event_ticker TEXT NOT NULL,
    city TEXT NOT NULL,
    market_type TEXT NOT NULL,
    side TEXT NOT NULL,
    contracts INTEGER NOT NULL,
    entry_price_cents INTEGER NOT NULL,
    fees_cents INTEGER DEFAULT 0,
    
    -- Our model at time of trade
    estimated_temp_f REAL,
    forecast_temp_f REAL,
    primary_temp_f REAL,
    surrounding_avg_f REAL,
    confidence REAL,
    edge_pct REAL,
    model_std_dev REAL,
    
    -- Bracket info
    floor_strike REAL,
    cap_strike REAL,
    our_probability REAL,
    market_probability REAL,
    
    -- Settlement
    settled INTEGER DEFAULT 0,
    actual_temp_f REAL,
    settlement_result TEXT,
    pnl_cents INTEGER DEFAULT 0,
    
    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    settled_at TEXT,
    
    -- Analysis
    prediction_error_f REAL,
    notes TEXT
, final_pnl_cents INTEGER, signal_source TEXT DEFAULT 'model');

-- v2_paper_trades: 532 rows
CREATE TABLE v2_paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT NOT NULL,
        ticker TEXT NOT NULL,
        city TEXT NOT NULL,
        market_type TEXT NOT NULL,
        side TEXT NOT NULL,
        suggested_price INTEGER,
        confidence REAL,
        edge_pct REAL,
        estimated_temp REAL,
        forecast_temp REAL,
        market_yes_price INTEGER,
        settled INTEGER DEFAULT 0,
        actual_temp REAL,
        pnl_cents INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

