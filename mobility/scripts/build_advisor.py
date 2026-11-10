"""Build data/advisor_findings.json for the KL Mobility Lab.

Runs the full pipeline (or reuses an already built result), assembles the
advisor inputs and runs the deterministic rule engine in scripts/advisor.py.
The JSON is strict: no NaN or Infinity, missing numbers become null.

The findings are recomputed from the data on every run. Nothing in the
output is hardcoded: with different data the findings change, including to
"no_action_justified", and cleared checks are kept in the file on purpose.

Run from the mobility folder:  python -I scripts/build_advisor.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Standard layout, no reliance on the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import advisor  # noqa: E402
import build_mobility_data as bm  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def assemble_inputs(built: dict) -> dict:
    """Advisor inputs from a build_mobility_data.build_all result.

    The LRT Shah Alam daily column is read from the raw parquet because
    the processed frames only keep service-group sums.
    """
    raw = pd.read_parquet(bm.RAW / "ridership_headline.parquet")
    shah_alam = pd.DataFrame(
        {"date": raw["date"].astype(str), "trips": raw["rail_lrt_shah_alam"]}
    )
    return {
        "profile": bm.build_weekday_profile_2026(built["daily"]),
        "od": built["od"],
        "monthly": built["monthly"],
        "registrations": built["registrations"],
        "shah_alam": shah_alam,
        "gaps": built["data"]["meta"]["gaps"],
    }


def build(out_dir: Path | str | None = None, built: dict | None = None) -> Path:
    """Run the advisor; return the path of the findings JSON.

    `built` lets the pipeline pass its already computed result so the raw
    files are not reprocessed twice; without it the pipeline is run here
    (nothing is rewritten).
    """
    if built is None:
        built = bm.build_all(write=False)
    inputs = assemble_inputs(built)
    result = advisor.run_advisor(**inputs)
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **result["meta"],
        },
        "findings": result["findings"],
    }

    data_dir = Path(out_dir) if out_dir else PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "advisor_findings.json"
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return out_path


def main() -> None:
    path = build()
    print(f"Advisor complete. Wrote {path}")


if __name__ == "__main__":
    main()
