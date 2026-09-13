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
  category        TEXT,
  account_name    TEXT
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


CREATE TABLE IF NOT EXISTS exercise_templates (
  exercise_template_id TEXT PRIMARY KEY,
  title                 TEXT NOT NULL,
  type                  TEXT NOT NULL,
  primary_muscle_group  TEXT NOT NULL,
  equipment             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workouts (
  workout_id   TEXT PRIMARY KEY,
  title        TEXT NOT NULL,
  routine_id   TEXT,
  description  TEXT,
  start_time   TEXT NOT NULL,   -- ISO 8601 UTC, e.g. '2026-08-31T22:20:06+00:00'
  end_time     TEXT NOT NULL,
  workout_date TEXT NOT NULL,   -- NYC calendar date (YYYY-MM-DD) of start_time
  duration_min INTEGER,
  updated_at   TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(workout_date);

CREATE TABLE IF NOT EXISTS workout_sets (
  workout_id           TEXT NOT NULL REFERENCES workouts(workout_id),
  exercise_index       INTEGER NOT NULL,
  exercise_title       TEXT NOT NULL,
  exercise_template_id TEXT,
  superset_id          INTEGER,
  set_index            INTEGER NOT NULL,
  set_type             TEXT,
  weight_kg            REAL,
  reps                 INTEGER,
  distance_meters      REAL,
  duration_seconds     INTEGER,
  rpe                  REAL,
  custom_metric        REAL,
  PRIMARY KEY (workout_id, exercise_index, set_index)
);

CREATE TABLE IF NOT EXISTS workout_sync_state (
  id           INTEGER PRIMARY KEY CHECK (id = 1),
  since_cursor TEXT
);
