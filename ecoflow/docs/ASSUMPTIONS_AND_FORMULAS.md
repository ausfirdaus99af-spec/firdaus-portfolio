# EcoFlow - Assumptions and Formulas

All data in this project is synthetic. Nothing here is operational, design or dosing guidance for any real plant.

## Formulas

All formulas are implemented as pure, NaN-safe functions in `scripts/analytics.py`. Invalid inputs (missing values, zero or negative denominators, physically impossible values) return NaN rather than raising, and nothing ever divides by zero.

### Removal efficiency (concentration based)

    removal (%) = (C_in - C_out) / C_in x 100

- C_in: influent concentration, mg/L
- C_out: effluent concentration, mg/L
- Returns NaN when C_in <= 0 or either value is missing.
- The result is not clipped. A negative efficiency is possible when the effluent reading exceeds the influent reading (severe upset or sensor fault) and is deliberately kept visible rather than hidden.

### Pollutant load

    load (kg/h) = flow (m3/h) x concentration (mg/L) / 1000

1 mg/L equals 1 g/m3, so flow times concentration gives g/h, and dividing by 1000 gives kg/h. Daily loads (kg/day) are the sum of hourly loads over the clean hours available that day.

### Specific energy

    specific energy (kWh/m3) = energy (kWh) / volume treated (m3)

Returns NaN when volume <= 0.

### Specific chemical dose

    dose (g/m3) = chemical (kg) x 1000 / volume treated (m3)

Returns NaN when volume <= 0.

### Daily aggregation

- Total volume (m3) = sum of hourly influent flow (m3/h) x 1 h.
- Daily mean concentrations are flow weighted: sum(flow x concentration) / sum(flow).
- Daily removal efficiencies are computed from the flow-weighted mean concentrations, not from averaging hourly efficiencies.
- Whole-period KPI averages are volume weighted where appropriate (specific energy = total energy / total volume, and so on).

## Data cleaning order

Cleaning happens BEFORE any KPI aggregation. A row is excluded when it is tagged with an `anomaly_type`, or when any monitored reading is missing or falls outside a plausibility range (for example pH outside 3 to 12, zero or negative flow or concentration, COD above 2,000 mg/L influent). Counts of anomalies, upset hours and maintenance hours are reported from the raw record, because they describe the record itself.

## The effluent-flow assumption

This model ASSUMES effluent flow equals influent flow: no evaporation, no sludge wasting, no side streams, no storage. This is an explicit simplification. In a real plant the inlet and outlet flows differ, and concentration-based removal efficiency is then NOT the same as mass-based removal. An honest mass balance would need measured outlet flow:

    mass removal (%) = (Q_in x C_in - Q_out x C_out) / (Q_in x C_in) x 100

Under the equal-flow assumption the two definitions coincide, which is why this project reports concentration-based removal throughout and says so.

## Modelling assumptions (summary)

1. 100 percent synthetic data, deterministic for a given seed (default 42).
2. Effluent flow equals influent flow (see above).
3. Influent BOD is 0.45 to 0.55 times influent COD; BOD never exceeds COD on either side of the plant.
4. Baseline specific energy about 0.8 kWh/m3; the optimised scenario models VFD aeration control at about 12 percent lower energy.
5. Baseline coagulant dose about 60 g/m3; the optimised scenario models dose control at about 15 percent lower dose with about 1 percentage point better TSS removal.
6. Upsets and maintenance occur at identical times in both scenarios for comparability.
7. Sensor artefacts are recording faults, not process changes, and are removed before aggregation.
8. Each record is a one hour average; sub-hourly dynamics are not modelled.

## Limitations

- No regulatory limits, compliance status or discharge permits are modelled.
- Temperature, nutrient loads, sludge production and aeration chemistry are not modelled.
- The optimised scenario's savings are stated model inputs, not results of a process simulation; the project demonstrates the analytics, not the engineering of the saving.
- Removal efficiency bands and cost factors are illustrative, not calibrated to any technology or vendor.
- Daily loads are computed from the clean hours available in a day, so a day with removed anomalies is a slight undercount of the true total.
- No value anywhere in this project constitutes operational, design or dosing guidance.
