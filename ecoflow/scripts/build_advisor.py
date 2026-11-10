"""Build data/advisor_findings.json for the EcoFlow portfolio project.

Loads the hourly CSV, selects the baseline scenario, runs the deterministic
rule engine in scripts/advisor.py and writes data/advisor_findings.json.
The JSON is strict: no NaN or Infinity, missing numbers become null.

The findings are recomputed from the data on every run. Nothing in the
output is hardcoded: with different data the findings change, including to
"no_action_justified", and cleared checks are kept in the file on purpose.

Run from anywhere:

    python scripts/build_advisor.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Standard layout, no reliance on the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import advisor  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build(out_dir: Path | str | None = None, csv_path: Path | str | None = None) -> Path:
    """Run the advisor on the hourly CSV; return the path of the findings JSON.

    out_dir defaults to the project's data/ directory and is used both to
    locate ecoflow_hourly.csv (unless csv_path overrides it) and to place
    advisor_findings.json, so the advisor output always sits next to the
    dataset it was computed from.
    """
    data_dir = Path(out_dir) if out_dir else PROJECT_ROOT / "data"
    csv = Path(csv_path) if csv_path else data_dir / "ecoflow_hourly.csv"
    df = pd.read_csv(csv)

    result = advisor.run_advisor(df)
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **result["meta"],
        },
        "findings": result["findings"],
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "advisor_findings.json"
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
    return out_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build EcoFlow advisor findings.")
    parser.add_argument("--csv", type=str, default=None, help="Input CSV path (default data/ecoflow_hourly.csv).")
    parser.add_argument("--out", type=str, default=None, help="Output directory (default data/).")
    args = parser.parse_args(argv)
    path = build(out_dir=args.out, csv_path=args.csv)
    print(f"Advisor complete. Wrote {path}")


if __name__ == "__main__":
    main()
