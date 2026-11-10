"""KL Mobility Lab, Phase 2 pipeline.

Reads the raw files catalogued in docs/SOURCE_CATALOGUE.md and produces:

  data/mobility_data.json  (contract consumed by the dashboard)
  data/stops.json          (GTFS rail stop coordinates)
  data/mobility.db         (SQLite showcase layer, loaded from the same frames)

Every exported block states its source and licence. Observed data and
stated assumptions (simulator_defaults) are kept strictly separate.
Cleaning rules are documented in docs/METHODOLOGY.md.

Run from the mobility folder:  python -I scripts/build_mobility_data.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw"
OUT = ROOT / "data"
SQL = ROOT / "sql"

# ---------------------------------------------------------------------------
# 1. Ridership (ridership_headline.parquet, data.gov.my, CC BY 4.0)
# ---------------------------------------------------------------------------

# Service group mapping. Every non-date column of the raw file must appear
# in exactly one group (enforced by tests and by load_ridership below).
SERVICE_GROUPS: dict[str, list[str]] = {
    # Rapid Rail Klang Valley: all LRT, MRT and Monorail lines.
    "rail": [
        "rail_lrt_ampang",
        "rail_lrt_kj",
        "rail_lrt_shah_alam",
        "rail_monorail",
        "rail_mrt_kajang",
        "rail_mrt_pjy",
    ],
    # Rapid Bus (KL, Kuantan, Penang). All bus columns in the file are
    # Rapid Bus services.
    "bus": ["bus_rkl", "bus_rkn", "bus_rpn"],
    # KTMB heavy rail services.
    "ktmb": [
        "rail_ets",
        "rail_intercity",
        "rail_komuter",
        "rail_komuter_utara",
        "rail_tebrau",
    ],
}


def load_ridership() -> pd.DataFrame:
    """Daily trips per service group. Columns: date (str), rail, bus, ktmb.

    A group value is NA on days where none of its services reported
    (series start later for bus and KTMB); otherwise it is the sum of the
    services that did report.
    """
    df = pd.read_parquet(RAW / "ridership_headline.parquet")
    value_cols = [c for c in df.columns if c != "date"]
    mapped = sorted(c for cols in SERVICE_GROUPS.values() for c in cols)
    if mapped != sorted(value_cols):
        raise ValueError(
            "Service group mapping does not cover the raw columns exactly once: "
            f"mapped={mapped} raw={sorted(value_cols)}"
        )
    out = pd.DataFrame({"date": df["date"].astype(str)})
    for group, cols in SERVICE_GROUPS.items():
        block = df[cols]
        total = block.sum(axis=1, skipna=True)
        # Days where every service in the group is NA stay NA.
        total[block.isna().all(axis=1)] = pd.NA
        out[group] = total.astype("Int64")
    return out


def build_ridership_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Monthly totals per group, 2019-01 to 2026-08. NA months stay NA."""
    d = daily.copy()
    d["m"] = d["date"].str[:7]
    monthly = d.groupby("m")[["rail", "bus", "ktmb"]].sum(min_count=1)
    return monthly.reset_index()


def build_weekday_profile_2026(daily: pd.DataFrame) -> pd.DataFrame:
    """Mean daily rail trips by day of week, 2026 observed days."""
    d = daily[daily["date"].str.startswith("2026")].copy()
    dates = pd.to_datetime(d["date"])
    d["dow"] = dates.dt.day_name().str[:3]
    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    prof = d.groupby("dow")["rail"].mean().reindex(order).reset_index()
    prof.columns = ["dow", "rail_avg"]
    return prof


# ---------------------------------------------------------------------------
# 2. Rail origin-destination (rapidrail_2026_daily.parquet, CC BY 4.0)
# ---------------------------------------------------------------------------

# The raw file labels stations as "<line code><number>: <name>", for example
# "AG07: Masjid Jamek" and "KJ13: Masjid Jamek" for the two gate groups of
# the same physical interchange. Normalisation strips the code prefix, trims
# and collapses whitespace, so interchange stations merge under one name.
STATION_PREFIX_RE = re.compile(r"^[A-Z]+\d+:\s*")

# Marginal pseudo-station: rows with this origin or destination are
# published row and column totals, not station pairs.
ALL_STATIONS = "A0: All Stations"

# Manual alias table for spelling variants that the prefix rule cannot
# merge. The 2026 file needs no manual merges (all cross-line variants of
# one station share the same spelling after the prefix is stripped); the
# table is kept so later years with diverging spellings have one place to
# record corrections.
STATION_ALIASES: dict[str, str] = {}


def normalise_station(raw: str) -> str:
    name = STATION_PREFIX_RE.sub("", raw).strip()
    name = re.sub(r"\s+", " ", name)
    return STATION_ALIASES.get(name, name)


def station_mapping(values) -> dict[str, str]:
    """Full observed raw name to clean name mapping table."""
    return {v: normalise_station(v) for v in sorted(set(values))}


def load_od() -> dict:
    """Clean the OD matrix and compute the exported aggregates.

    Returns a dict with the detail frame, day count, totals and top lists.
    The published marginal rows (origin or destination "A0: All Stations")
    are excluded from analysis but verified against the station-level sum.
    """
    od = pd.read_parquet(RAW / "rapidrail_2026_daily.parquet")
    raw_total = int(od["ridership"].sum())

    o_marg = od["origin"] == ALL_STATIONS
    d_marg = od["destination"] == ALL_STATIONS
    detail = od[~o_marg & ~d_marg].copy()
    detail_total = int(detail["ridership"].sum())
    orig_marg_total = int(od.loc[o_marg, "ridership"].sum())
    dest_marg_total = int(od.loc[d_marg, "ridership"].sum())
    # Published marginals must both equal the station-level total, and the
    # file grand total is therefore three times the real OD total.
    if not (detail_total == orig_marg_total == dest_marg_total):
        raise ValueError(
            "Marginal rows do not reconcile with station-level rows: "
            f"detail={detail_total} origin_marginals={orig_marg_total} "
            f"destination_marginals={dest_marg_total}"
        )

    o_map = station_mapping(detail["origin"])
    d_map = station_mapping(detail["destination"])
    detail["o"] = detail["origin"].map(o_map)
    detail["d"] = detail["destination"].map(d_map)
    if int(detail["ridership"].sum()) != detail_total:
        raise ValueError("Normalisation changed the trip total")

    n_days = int(od["date"].nunique())
    period = {
        "start": str(od["date"].min().date()),
        "end": str(od["date"].max().date()),
        "days_observed": n_days,
    }

    # Same-station journeys (after interchange merging) are excluded from
    # the top lists; they are entry and exit at the same station name.
    cross = detail[detail["o"] != detail["d"]]
    same_total = detail_total - int(cross["ridership"].sum())

    pairs = (
        cross.groupby(["o", "d"])["ridership"].sum().sort_values(ascending=False)
    )
    top_pairs = [
        {"o": o, "d": d, "avg_daily": round(v / n_days)}
        for (o, d), v in pairs.head(20).items()
    ]
    origins = detail.groupby("o")["ridership"].sum().sort_values(ascending=False)
    top_origins = [
        {"s": s, "avg_daily": round(v / n_days)} for s, v in origins.head(10).items()
    ]
    dests = detail.groupby("d")["ridership"].sum().sort_values(ascending=False)
    top_destinations = [
        {"s": s, "avg_daily": round(v / n_days)} for s, v in dests.head(10).items()
    ]

    missing_dest_names = sorted(set(detail["o"]) - set(detail["d"]))

    return {
        "detail": detail,
        "raw_total": raw_total,
        "detail_total": detail_total,
        "same_station_total": same_total,
        "period": period,
        "n_days": n_days,
        "top_pairs": top_pairs,
        "top_origins": top_origins,
        "top_destinations": top_destinations,
        "missing_destination_names": missing_dest_names,
        "origin_map": o_map,
        "destination_map": d_map,
    }


# ---------------------------------------------------------------------------
# 3. Car registration transactions (cars_2026.parquet, JPJ via data.gov.my)
# ---------------------------------------------------------------------------

def region_bucket(state: str) -> str:
    if state == "Selangor":
        return "selangor"
    if state == "W.P. Kuala Lumpur":
        return "kl"
    if state == "Rakan Niaga":
        return "rakan_niaga"
    return "other"


def load_registrations() -> pd.DataFrame:
    """Monthly transaction counts by region bucket. Columns: m, selangor,
    kl, rakan_niaga, other. Counts are registration transactions, not
    vehicles in traffic; Rakan Niaga is a JPJ partner sales channel, not a
    geographic region."""
    df = pd.read_parquet(RAW / "cars_2026.parquet")
    df["m"] = df["date_reg"].dt.strftime("%Y-%m")
    df["region"] = df["state"].map(region_bucket)
    counts = df.groupby(["m", "region"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=["selangor", "kl", "rakan_niaga", "other"])
    counts.attrs["raw_rows"] = len(df)
    return counts.reset_index()


# ---------------------------------------------------------------------------
# 4. Population (population_district.parquet, DOSM via data.gov.my)
# ---------------------------------------------------------------------------

def load_population() -> pd.DataFrame:
    """Selangor and W.P. Kuala Lumpur total population by year, thousands,
    both sexes, all ages, all ethnic groups (the 'overall' rows)."""
    df = pd.read_parquet(RAW / "population_district.parquet")
    sel = df[
        (df["sex"] == "both")
        & (df["age"] == "overall")
        & (df["ethnicity"] == "overall")
        & (df["state"].isin(["Selangor", "W.P. Kuala Lumpur"]))
    ].copy()
    sel["y"] = pd.to_datetime(sel["date"]).dt.year
    out = (
        sel.groupby(["y", "state"])["population"].sum().unstack().round(1)
    )
    out.columns = ["selangor_k" if c == "Selangor" else "kl_k" for c in out.columns]
    return out.reset_index()


# ---------------------------------------------------------------------------
# 5. Employment (lfs_qtr_state.parquet, DOSM via data.gov.my)
# ---------------------------------------------------------------------------

def load_employment() -> pd.DataFrame:
    """Employed persons (thousands) by quarter for Selangor and
    W.P. Kuala Lumpur, 2017 Q1 to 2026 Q2. Employment is counted at the
    worker's state of residence, not the location of the job."""
    df = pd.read_parquet(RAW / "lfs_qtr_state.parquet")
    sel = df[df["state"].isin(["Selangor", "W.P. Kuala Lumpur"])].copy()
    dates = pd.to_datetime(sel["date"])
    sel["q"] = (
        dates.dt.year.astype(str) + "-Q" + ((dates.dt.month - 1) // 3 + 1).astype(str)
    )
    out = sel.pivot(index="q", columns="state", values="lf_employed").round(1)
    out.columns = [
        "selangor_k" if c == "Selangor" else "kl_k" for c in out.columns
    ]
    return out.reset_index()


# ---------------------------------------------------------------------------
# 6. GTFS stops (gtfs_rapid_rail_kl/stops.txt, CC BY 4.0)
# ---------------------------------------------------------------------------

def load_stops() -> list[dict]:
    df = pd.read_csv(RAW / "gtfs_rapid_rail_kl" / "stops.txt")
    return [
        {"name": r.stop_name, "lat": float(r.stop_lat), "lon": float(r.stop_lon)}
        for r in df.itertuples()
    ]


# ---------------------------------------------------------------------------
# 7. Cited figures (hard-coded from docs/SOURCE_CATALOGUE.md, not re-derived)
# ---------------------------------------------------------------------------

CITATIONS = {
    "migration": {
        "source": (
            "Department of Statistics Malaysia, Migration Survey Report "
            "Malaysia 2024, released 18 December 2025"
        ),
        "licence": (
            "Copyright DOSM, all rights reserved; figures quoted with "
            "attribution, tables not redistributed as open data"
        ),
        "figures": {
            "total_migrants_2024_thousand": 301.1,
            "migration_rate_2024_pct": 0.9,
            "internal_migration_share_pct": 63.5,
            "selangor_in_migrants_thousand": 97.6,
            "selangor_net_migration_thousand": 8.4,
            "kl_net_migration_thousand": -7.6,
            "kl_to_selangor_flow_thousand": 13.8,
            "career_reason_share_pct": 17.2,
            "selangor_intra_state_urban_to_urban_pct": 96.2,
            "age_25_34_share_of_internal_pct": 47.7,
        },
        "note": (
            "Migration is a change of usual residence, not commuting; the "
            "survey does not record workplace."
        ),
    },
    "tomtom": {
        "source": "TomTom Traffic Index 2025, Kuala Lumpur (city view)",
        "retrieved": "2026-11-10",
        "licence": (
            "Proprietary; published headline figures citable with "
            "attribution to TomTom, no bulk reuse of underlying data"
        ),
        "attribution_required": (
            "TomTom Traffic Index 2025, retrieved 10 November 2026"
        ),
        "figures": {
            "avg_travel_time_per_10km": "17 min 55 s",
            "avg_congestion_level_pct": 43.4,
            "hours_lost_in_rush_hour_per_year": 84,
            "world_rank": "172 of 492 cities",
            "morning_peak_congestion_pct": 68.4,
            "evening_peak_congestion_pct": 102.1,
            "evening_peak_time_per_10km": "26 min 12 s",
            "avg_speed_kmh": 33.5,
        },
    },
    "worldbank_2015": {
        "source": (
            "World Bank, Malaysia Economic Monitor, June 2015: Transforming "
            "Urban Transport, DOI 10.1596/22038"
        ),
        "licence": "CC BY 3.0 IGO, attribution to the World Bank",
        "figures": {
            "kl_public_transport_commuter_share_pct": 17,
            "singapore_share_pct": 62,
            "hong_kong_share_pct": 89,
        },
        "note": "Underlying surveys circa 2010 to 2014, before the MRT opened.",
    },
    "spad_mode_share": {
        "source": (
            "SPAD, Greater KL / Klang Valley Land Public Transport Master "
            "Plan and annual reports (2011 to 2013 surveys)"
        ),
        "licence": (
            "Headline figures citable from published reports; the household "
            "travel survey microdata was never published"
        ),
        "figures": {
            "am_peak_public_transport_share_2010_pct": 17,
            "am_peak_public_transport_share_2013_pct": 20.8,
            "national_master_plan_2030_target_pct": 40,
        },
    },
}

LICENCES = [
    {
        "source": "data.gov.my ridership_headline",
        "licence": "CC BY 4.0",
        "attribution": "data.gov.my / Prasarana Malaysia / Ministry of Transport",
    },
    {
        "source": "data.gov.my ridership_od_rapidrail_daily (2026)",
        "licence": "CC BY 4.0",
        "attribution": "data.gov.my / Prasarana Malaysia / Ministry of Transport",
    },
    {
        "source": "data.gov.my GTFS static, Rapid Rail KL",
        "licence": "CC BY 4.0",
        "attribution": "data.gov.my / Prasarana Malaysia",
    },
    {
        "source": "data.gov.my registration_transactions_car (2026)",
        "licence": "CC BY 4.0",
        "attribution": "data.gov.my / JPJ / Ministry of Transport",
    },
    {
        "source": "data.gov.my population_district",
        "licence": "CC BY 4.0",
        "attribution": "data.gov.my / Department of Statistics Malaysia",
    },
    {
        "source": "data.gov.my lfs_qtr_state",
        "licence": "CC BY 4.0",
        "attribution": "data.gov.my / Department of Statistics Malaysia",
    },
    {
        "source": "DOSM Migration Survey Report Malaysia 2024",
        "licence": "Copyright DOSM, all rights reserved",
        "attribution": "Department of Statistics Malaysia",
    },
    {
        "source": "TomTom Traffic Index 2025",
        "licence": "Proprietary, headline figures citable with attribution",
        "attribution": "TomTom Traffic Index 2025, retrieved 10 November 2026",
    },
    {
        "source": "World Bank Malaysia Economic Monitor, June 2015",
        "licence": "CC BY 3.0 IGO",
        "attribution": "World Bank, DOI 10.1596/22038",
    },
]

GAPS = [
    "No door-to-door commuting origin-destination matrix exists as open data; the rail OD matrix covers rail riders only, station to station, in a region where most commuting is by car.",
    "No workplace location data below state level; employment is counted at the worker's state of residence, so the work half of the live-work question cannot be mapped.",
    "No open time series of road traffic volumes or speeds for the Klang Valley; congestion outcomes exist only as TomTom's annual headline numbers and RTVM PDF reports.",
    "No maintained open series of mode shares over time; morning-peak figures are scattered across SPAD-era reports with differing definitions.",
    "No bus origin-destination matrix and no realised bus journey times; Prasarana publishes bus schedules and some ridership only.",
    "Car registration data records transactions, not vehicle use, and the Rakan Niaga channel detaches most 2026 transactions from any state.",
    "With open data alone the hypothesis can be explored but not conclusively tested; findings are descriptive evidence consistent with the hypothesis, not proof of it.",
]

SIMULATOR_DEFAULTS = {
    "note": "assumptions for a hypothetical what-if model, not observations",
    "car_commuters": 1500000,
    "share_affected_pct": 20,
    "one_way_km": 25,
    "workdays_per_week": 5,
    "remote_days_per_week": 0,
    "pt_shift_pct": 0,
    "car_occupancy": 1.2,
    "fuel_l_per_100km": 7.5,
    "co2_kg_per_l": 2.31,
    "rationale": [
        "employment in Selangor + KL is about 5.0 to 5.5 million (LFS above)",
        "SPAD surveys put private vehicle AM-peak mode share around 80%",
        "the 1.5 million default is an illustrative subset: car commuters on congested Klang Valley corridors",
        "defaults are starting points; every value is adjustable",
    ],
}


# ---------------------------------------------------------------------------
# SQLite layer
# ---------------------------------------------------------------------------

def parse_queries(sql_text: str) -> dict[str, str]:
    """Split queries.sql on '-- name:' markers."""
    queries: dict[str, str] = {}
    name = None
    buf: list[str] = []
    for line in sql_text.splitlines():
        m = re.match(r"--\s*name:\s*(\w+)", line)
        if m:
            if name and "".join(buf).strip():
                queries[name] = "\n".join(buf)
            name = m.group(1)
            buf = []
        elif name is not None:
            buf.append(line)
    if name and "".join(buf).strip():
        queries[name] = "\n".join(buf)
    return queries


def build_sqlite(
    daily: pd.DataFrame,
    registrations: pd.DataFrame,
    population: pd.DataFrame,
    employment: pd.DataFrame,
    db_path: Path,
) -> dict[str, list]:
    """Create data/mobility.db from the processed frames and run every
    query in sql/queries.sql. Analytical queries must return rows; qc_
    queries must return none."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    try:
        con.executescript((SQL / "schema.sql").read_text(encoding="utf-8"))

        rows = []
        for group in ("rail", "bus", "ktmb"):
            sub = daily[["date", group]].dropna()
            rows += [(d, group, int(t)) for d, t in sub.itertuples(index=False)]
        con.executemany("INSERT INTO ridership_daily VALUES (?,?,?)", rows)

        reg_rows = []
        for r in registrations.itertuples(index=False):
            for region in ("selangor", "kl", "rakan_niaga", "other"):
                reg_rows.append((r.m, region, int(getattr(r, region))))
        con.executemany(
            "INSERT INTO registrations_monthly VALUES (?,?,?)", reg_rows
        )

        pop_rows = []
        for r in population.itertuples(index=False):
            pop_rows.append((int(r.y), "Selangor", float(r.selangor_k)))
            pop_rows.append((int(r.y), "W.P. Kuala Lumpur", float(r.kl_k)))
        con.executemany("INSERT INTO population VALUES (?,?,?)", pop_rows)

        emp_rows = []
        for r in employment.itertuples(index=False):
            emp_rows.append((r.q, "Selangor", float(r.selangor_k)))
            emp_rows.append((r.q, "W.P. Kuala Lumpur", float(r.kl_k)))
        con.executemany("INSERT INTO employment_qtr VALUES (?,?,?)", emp_rows)
        con.commit()

        queries = parse_queries((SQL / "queries.sql").read_text(encoding="utf-8"))
        if not queries:
            raise ValueError("No named queries found in sql/queries.sql")
        results: dict[str, list] = {}
        for name, sql_text in queries.items():
            res = con.execute(sql_text).fetchall()
            results[name] = res
            if name.startswith("qc_"):
                if res:
                    raise AssertionError(f"QC query {name} returned rows: {res[:5]}")
            elif not res:
                raise AssertionError(f"Analytical query {name} returned no rows")
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
    return results


# ---------------------------------------------------------------------------
# Assemble and write
# ---------------------------------------------------------------------------

def _int_or_none(v):
    return None if pd.isna(v) else int(v)


def build_all(write: bool = True) -> dict:
    daily = load_ridership()
    monthly = build_ridership_monthly(daily)
    profile = build_weekday_profile_2026(daily)
    od = load_od()
    registrations = load_registrations()
    population = load_population()
    employment = load_employment()
    stops = load_stops()

    data = {
        "meta": {
            "project": "KL Mobility Lab",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "observed_vs_modelled": (
                "Everything in this file is observed public data except "
                "simulator_defaults, which are stated assumptions."
            ),
            "licences": LICENCES,
            "gaps": GAPS,
        },
        "ridership": {
            "source": "data.gov.my ridership_headline, CC BY 4.0",
            "period": {"start": "2019-01", "end": "2026-08"},
            "monthly": [
                {
                    "m": r.m,
                    "rail": _int_or_none(r.rail),
                    "bus": _int_or_none(r.bus),
                    "ktmb": _int_or_none(r.ktmb),
                }
                for r in monthly.itertuples(index=False)
            ],
            "weekday_profile_2026": [
                {"dow": r.dow, "rail_avg": round(float(r.rail_avg))}
                for r in profile.itertuples(index=False)
            ],
            "notes": [
                "trips not unique people; one commuter making two trips counts twice",
                "rail is all Rapid Rail LRT, MRT and Monorail lines; bus is all Rapid Bus services (KL, Kuantan, Penang); ktmb is all KTMB services",
                "bus series begins 2022-01, ktmb series begins 2020-10 (partial month); earlier months are null, not zero",
                "LRT Shah Alam Line reports from 2026-04 with a gap in May 2026 as published",
                "weekday profile covers observed 2026 days (January to August)",
                "2020 to 2021 is distorted by movement control orders",
            ],
        },
        "od": {
            "source": "data.gov.my ridership_od_rapidrail_daily 2026, CC BY 4.0",
            "period": od["period"],
            "top_pairs": od["top_pairs"],
            "top_origins": od["top_origins"],
            "top_destinations": od["top_destinations"],
            "total_avg_daily_trips": round(od["detail_total"] / od["n_days"]),
            "notes": [
                "rail users only; car and bus trips are not in this data",
                "station names normalised: line code prefixes stripped and interchange gate groups merged under one station name",
                "published 'All Stations' marginal rows excluded; they reconcile exactly with the station-level total",
                f"destination detail is missing for {len(od['missing_destination_names'])} stations (mostly the Putrajaya Line) in the published file; their boardings are complete, their alightings are not separately identified",
                "same-station journeys excluded from top lists",
                "trips, not unique passengers; directional (A to B and B to A are separate pairs)",
            ],
        },
        "registrations": {
            "source": "data.gov.my registration_transactions_car 2026 (JPJ), CC BY 4.0",
            "monthly": [
                {
                    "m": r.m,
                    "selangor": int(r.selangor),
                    "kl": int(r.kl),
                    "rakan_niaga": int(r.rakan_niaga),
                    "other": int(r.other),
                }
                for r in registrations.itertuples(index=False)
            ],
            "notes": [
                "registration transactions, not vehicles in traffic",
                "Rakan Niaga is a sales channel, not a place; it holds most 2026 transactions, so state counts understate geographic demand",
                "grain is one row per registration transaction, counted by registration date",
            ],
        },
        "population": {
            "source": "DOSM via data.gov.my, CC BY 4.0",
            "annual": [
                {
                    "y": int(r.y),
                    "selangor_k": round(float(r.selangor_k), 1),
                    "kl_k": round(float(r.kl_k), 1),
                }
                for r in population.itertuples(index=False)
            ],
        },
        "employment": {
            "source": "DOSM Labour Force Survey via data.gov.my, CC BY 4.0",
            "quarterly": [
                {
                    "q": r.q,
                    "selangor_k": round(float(r.selangor_k), 1),
                    "kl_k": round(float(r.kl_k), 1),
                }
                for r in employment.itertuples(index=False)
            ],
        },
        "citations": CITATIONS,
        "simulator_defaults": SIMULATOR_DEFAULTS,
    }
    # Employment quarters must sort correctly as strings (YYYY-Qn), but the
    # pivot above sorts lexically which is already chronological for this
    # format; enforce it anyway.
    data["employment"]["quarterly"].sort(key=lambda x: x["q"])

    query_results = None
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / "mobility_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, allow_nan=False)
        with open(OUT / "stops.json", "w", encoding="utf-8") as f:
            json.dump(stops, f, ensure_ascii=False, indent=0, allow_nan=False)
        query_results = build_sqlite(
            daily, registrations, population, employment, OUT / "mobility.db"
        )

    return {
        "data": data,
        "stops": stops,
        "daily": daily,
        "monthly": monthly,
        "od": od,
        "registrations": registrations,
        "population": population,
        "employment": employment,
        "query_results": query_results,
    }


def main() -> None:
    built = build_all(write=True)
    data = built["data"]
    od = built["od"]
    print("Wrote data/mobility_data.json, data/stops.json, data/mobility.db")
    print(f"OD detail total trips: {od['detail_total']:,} over {od['n_days']} days")
    print(f"Top pair: {od['top_pairs'][0]}")
    print(f"Monthly ridership rows: {len(data['ridership']['monthly'])}")
    qr = built["query_results"]
    print(f"SQL queries run: {len(qr)} ({sum(1 for k in qr if k.startswith('qc_'))} qc, all empty)")
    __import__("sys").path.insert(0, str(Path(__file__).resolve().parent)); print(f"Advisor: wrote {__import__('build_advisor').build(built=built)}")


if __name__ == "__main__":
    main()
