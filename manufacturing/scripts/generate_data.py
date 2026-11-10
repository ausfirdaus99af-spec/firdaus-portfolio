"""Synthetic manufacturing data generator.

Project 03 - Manufacturing Performance Analytics.

All data produced here is 100 percent synthetic. It describes an imaginary
speciality chemicals packing plant with three packing lines and two product
categories. No real plant, company, product or measurement is represented.

The generator is fully deterministic: the same seed always produces the same
dataset, row for row. The default seed is 42.

Dataset shape: one row per date x line x shift.
365 days (2025-11-01 to 2026-10-31) x 3 lines x 2 shifts = 2,190 rows.
"""

import calendar
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 42
START_DATE = date(2025, 11, 1)
END_DATE = date(2026, 10, 31)
DAYS = 365

LINES = ["Line A", "Line B", "Line C"]
SHIFTS = ["Day", "Night"]
CATEGORIES = ["Standard", "Premium"]

# Ideal (nameplate) rates in units per hour, per line and product category.
IDEAL_RATES_UPH = {
    "Line A": {"Standard": 1200, "Premium": 1000},
    "Line B": {"Standard": 1100, "Premium": 900},
    "Line C": {"Standard": 1150, "Premium": 950},
}

# Line commissioning years. Line B is the oldest line, which is why it
# carries more breakdown downtime in the generated data.
COMMISSIONED_YEAR = {"Line A": 2015, "Line B": 2008, "Line C": 2019}

# Shift and time model. Each shift is 8 hours with a 0.5 hour planned break.
# Planned production time is therefore 7.5 hours. The planned break is
# excluded from every OEE denominator.
SHIFT_H = 8.0
PLANNED_TIME_H = 7.5

DOWNTIME_REASONS = [
    "Changeover",
    "Equipment breakdown",
    "Material shortage",
    "Cleaning",
    "Quality stop",
]
REASON_WEIGHTS = [0.30, 0.20, 0.15, 0.20, 0.15]

# Story arcs planted in the data.
# 1. A major Line B breakdown week: availability crashes on Line B.
CRASH_START = date(2026, 3, 9)
CRASH_END = date(2026, 3, 15)
# 2. A plant maintenance programme from this date cuts breakdown downtime
#    by about 35 percent on all lines.
MAINTENANCE_FROM = date(2026, 7, 1)
MAINTENANCE_BREAKDOWN_FACTOR = 0.65
# 3. A mild month end push: higher planned units in the last three days of
#    each month.

# Energy and material model.
ENERGY_BASE_KWH = 150.0           # base load per shift
ENERGY_PER_UNIT_KWH = 0.35        # per actual unit produced
ENERGY_IDLE_KWH_PER_H = 90.0      # idle draw per hour of downtime
ENERGY_IDLE_FACTOR = 0.4          # applied when status is degraded or breakdown
MATERIAL_KG_PER_UNIT = 0.8        # per actual unit, with 2 percent seeded noise

COLUMNS = [
    "date", "line", "shift", "category",
    "planned_units", "actual_units", "good_units", "rejected_units",
    "planned_time_h", "run_time_h", "downtime_h",
    "downtime_reason", "equipment_status",
    "energy_kwh", "material_kg", "ideal_rate",
]


def generate(seed: int = SEED) -> pd.DataFrame:
    """Return the full synthetic dataset as a DataFrame.

    The ideal_rate column is a convenience column carrying the nameplate
    rate for the row's line and category. It is derived data and is not
    exported in the JSON rows.
    """
    rng = np.random.default_rng(seed)
    records = []

    for offset in range(DAYS):
        d = START_DATE + timedelta(days=offset)
        last_day = calendar.monthrange(d.year, d.month)[1]
        month_end_push = (last_day - d.day) < 3

        for line in LINES:
            for shift in SHIFTS:
                # Category: each line runs one category per shift.
                # Lines A and B mostly run Standard, Line C mostly Premium.
                p_standard = 0.85 if line in ("Line A", "Line B") else 0.15
                category = "Standard" if rng.random() < p_standard else "Premium"
                ideal = IDEAL_RATES_UPH[line][category]

                # Planned units: ideal rate x planned time x planning factor
                # of about 0.92, lifted to about 0.95 at month end.
                base_factor = 0.95 if month_end_push else 0.92
                plan_factor = rng.normal(base_factor, 0.01)
                planned_units = int(round(ideal * PLANNED_TIME_H * plan_factor))

                # Downtime: one dominant reason per row, hours drawn from a
                # lognormal distribution clipped to 0 to 2.5 hours.
                crash = (line == "Line B") and (CRASH_START <= d <= CRASH_END)
                if crash:
                    reason = "Equipment breakdown"
                    downtime_h = float(rng.uniform(3.5, 6.5))
                else:
                    reason = str(rng.choice(DOWNTIME_REASONS, p=REASON_WEIGHTS))
                    downtime_h = float(np.clip(rng.lognormal(-1.1, 0.9), 0.0, 2.5))
                    if reason == "Equipment breakdown":
                        if line == "Line B":
                            # Line B is older: about 1.5x breakdown downtime.
                            downtime_h = min(downtime_h * 1.5, 2.5)
                        if d >= MAINTENANCE_FROM:
                            downtime_h *= MAINTENANCE_BREAKDOWN_FACTOR
                    if downtime_h < 0.1:
                        reason = "None"

                run_time_h = PLANNED_TIME_H - downtime_h

                # Performance factor 0.85 to 0.98, Night shift about two
                # percentage points lower.
                perf = rng.uniform(0.85, 0.98)
                if shift == "Night":
                    perf -= 0.02
                actual_units = int(round(ideal * run_time_h * perf))

                # Quality 0.95 to 0.995, Premium slightly lower.
                quality = rng.uniform(0.95, 0.995)
                if category == "Premium":
                    quality -= 0.004
                good_units = int(round(actual_units * quality))
                good_units = min(good_units, actual_units)
                rejected_units = actual_units - good_units

                # Equipment status.
                if reason == "Equipment breakdown":
                    status = "breakdown"
                elif downtime_h >= 0.1 and rng.random() < 0.10:
                    status = "degraded"
                else:
                    status = "running"

                # Energy: base load + per unit energy + idle draw during
                # downtime when the equipment is degraded or broken down.
                idle_kwh = 0.0
                if status in ("degraded", "breakdown"):
                    idle_kwh = ENERGY_IDLE_KWH_PER_H * downtime_h * ENERGY_IDLE_FACTOR
                energy_kwh = (
                    ENERGY_BASE_KWH
                    + ENERGY_PER_UNIT_KWH * actual_units
                    + idle_kwh
                    + rng.normal(0.0, 5.0)
                )
                energy_kwh = max(float(energy_kwh), 0.0)

                # Material: 0.8 kg per actual unit with 2 percent noise.
                material_kg = MATERIAL_KG_PER_UNIT * actual_units * (
                    1.0 + rng.normal(0.0, 0.02)
                )
                material_kg = max(float(material_kg), 0.0)

                records.append({
                    "date": d.isoformat(),
                    "line": line,
                    "shift": shift,
                    "category": category,
                    "planned_units": planned_units,
                    "actual_units": actual_units,
                    "good_units": good_units,
                    "rejected_units": rejected_units,
                    "planned_time_h": PLANNED_TIME_H,
                    "run_time_h": run_time_h,
                    "downtime_h": downtime_h,
                    "downtime_reason": reason,
                    "equipment_status": status,
                    "energy_kwh": energy_kwh,
                    "material_kg": material_kg,
                    "ideal_rate": ideal,
                })

    df = pd.DataFrame.from_records(records, columns=COLUMNS)
    return df


if __name__ == "__main__":
    frame = generate()
    print(f"Rows: {len(frame)}")
    print(f"Date range: {frame['date'].min()} to {frame['date'].max()}")
    print(frame.head())
