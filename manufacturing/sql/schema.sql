-- Project 03 - Manufacturing Performance Analytics
-- Relational schema for the synthetic plant database (SQLite).
-- All data loaded into these tables is synthetic.
--
-- Design notes:
-- - Ideal rates are normalised into line_products because a rate belongs
--   to a line and product pair, not to either one alone.
-- - production_runs holds one row per date x line x shift, enforced by a
--   UNIQUE constraint.
-- - Downtime is held in downtime_events (one dominant event per run in the
--   generated data, but the table allows several).

PRAGMA foreign_keys = ON;

CREATE TABLE lines (
    line_id           INTEGER PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    commissioned_year INTEGER NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    category   TEXT NOT NULL UNIQUE
);

CREATE TABLE line_products (
    line_id        INTEGER NOT NULL REFERENCES lines (line_id),
    product_id     INTEGER NOT NULL REFERENCES products (product_id),
    ideal_rate_uph REAL NOT NULL CHECK (ideal_rate_uph > 0),
    PRIMARY KEY (line_id, product_id)
);

CREATE TABLE production_runs (
    run_id           INTEGER PRIMARY KEY,
    date             TEXT NOT NULL,
    line_id          INTEGER NOT NULL REFERENCES lines (line_id),
    product_id       INTEGER NOT NULL REFERENCES products (product_id),
    shift            TEXT NOT NULL CHECK (shift IN ('Day', 'Night')),
    planned_units    INTEGER NOT NULL,
    actual_units     INTEGER NOT NULL,
    good_units       INTEGER NOT NULL,
    rejected_units   INTEGER NOT NULL,
    planned_time_h   REAL NOT NULL,
    run_time_h       REAL NOT NULL,
    energy_kwh       REAL NOT NULL,
    material_kg      REAL NOT NULL,
    equipment_status TEXT NOT NULL
        CHECK (equipment_status IN ('running', 'degraded', 'breakdown')),
    UNIQUE (date, line_id, shift)
);

CREATE TABLE downtime_events (
    event_id INTEGER PRIMARY KEY,
    run_id   INTEGER NOT NULL REFERENCES production_runs (run_id),
    reason   TEXT NOT NULL,
    hours    REAL NOT NULL CHECK (hours >= 0)
);

CREATE INDEX idx_runs_date ON production_runs (date);
CREATE INDEX idx_runs_line ON production_runs (line_id);
CREATE INDEX idx_events_run ON downtime_events (run_id);
