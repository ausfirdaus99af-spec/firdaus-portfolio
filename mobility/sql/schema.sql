-- KL Mobility Lab: SQLite schema.
-- Loaded by scripts/build_mobility_data.py from the processed frames.
-- All values are observed public data; sources and licences are recorded
-- in docs/SOURCE_CATALOGUE.md and in data/mobility_data.json.

-- Daily public transport trips per service group.
-- Source: data.gov.my ridership_headline (CC BY 4.0).
-- Groups: rail (Rapid Rail LRT + MRT + Monorail), bus (Rapid Bus),
-- ktmb (KTMB services). Days where a group did not yet report are absent,
-- not zero (bus starts 2022-01, ktmb starts 2020-10).
CREATE TABLE ridership_daily (
    date          TEXT NOT NULL,            -- YYYY-MM-DD
    service_group TEXT NOT NULL,            -- rail | bus | ktmb
    trips         INTEGER NOT NULL,         -- trips, not unique people
    PRIMARY KEY (date, service_group)
);

-- Monthly car registration transactions by region bucket, 2026.
-- Source: data.gov.my registration_transactions_car (JPJ, CC BY 4.0).
-- Transactions, not vehicles in traffic. rakan_niaga is a JPJ partner
-- sales channel, not a geographic region.
CREATE TABLE registrations_monthly (
    month        TEXT NOT NULL,             -- YYYY-MM
    region       TEXT NOT NULL,             -- selangor | kl | rakan_niaga | other
    transactions INTEGER NOT NULL,
    PRIMARY KEY (month, region)
);

-- Total population by year and state, thousands (both sexes, all ages).
-- Source: DOSM population_district via data.gov.my (CC BY 4.0).
CREATE TABLE population (
    year      INTEGER NOT NULL,
    state     TEXT NOT NULL,
    persons_k REAL NOT NULL,                -- thousands
    PRIMARY KEY (year, state)
);

-- Employed persons by quarter and state, thousands. Counted at the
-- worker's state of residence, not the job location.
-- Source: DOSM lfs_qtr_state via data.gov.my (CC BY 4.0).
CREATE TABLE employment_qtr (
    quarter    TEXT NOT NULL,               -- YYYY-Qn
    state      TEXT NOT NULL,
    employed_k REAL NOT NULL,               -- thousands
    PRIMARY KEY (quarter, state)
);
