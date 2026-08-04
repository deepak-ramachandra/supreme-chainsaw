CREATE TABLE meals (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6)))),
  meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
  calories REAL,
  protein_g REAL,
  carbs_g REAL,
  fat_g REAL,
  logged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE TABLE meal_templates (
  id text PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6)))),
  name text NOT NULL,
  calories real,
  protein_g real,
  carbs_g real,
  fat_g real,
  notes text DEFAULT '' NOT NULL
);


CREATE TABLE transactions (
  transaction_id  TEXT PRIMARY KEY,
  authorized_date TEXT,
  amount          REAL NOT NULL,
  merchant_name   TEXT,
  category        TEXT
);

CREATE INDEX idx_txn_date ON transactions(authorized_date);

CREATE TABLE sync_state (id INTEGER PRIMARY KEY CHECK (id = 1), cursor TEXT);

CREATE TABLE IF NOT EXISTS sleep (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  slept_at     TEXT    NOT NULL,   -- ISO 8601 w/ offset, e.g. '2026-08-02T23:40:00-04:00'
  wake_at      TEXT    NOT NULL,
  quality      INTEGER NOT NULL CHECK (quality BETWEEN 1 AND 5),
  notes        TEXT,
  created_at   TEXT    NOT NULL DEFAULT (datetime('now')),

  -- local calendar date of waking; the night "belongs" to this date
  sleep_date   TEXT GENERATED ALWAYS AS (substr(wake_at, 1, 10)) STORED,

  duration_min INTEGER GENERATED ALWAYS AS (
    CAST(ROUND((julianday(wake_at) - julianday(slept_at)) * 1440) AS INTEGER)
  ) STORED,

  CHECK (julianday(wake_at) > julianday(slept_at)),
  CHECK (slept_at LIKE '____-__-__T__:__:__%'),
  CHECK (wake_at  LIKE '____-__-__T__:__:__%')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sleep_date ON sleep(sleep_date);
