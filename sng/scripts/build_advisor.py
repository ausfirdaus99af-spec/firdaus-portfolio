"""Build data/advisor_findings.json for the SNG plant case study.

Rebuilds the model dataset, runs the deterministic rule engine in
scripts/advisor.py on the chosen scenario and writes the findings JSON.
The JSON is strict: no NaN or Infinity, missing numbers become null.

The findings are recomputed from the model on every run. Nothing in the
output is hardcoded: with a different design the findings change, including
to "no_action_justified", and cleared checks are kept in the file on purpose.

Run from anywhere:

    python scripts/build_advisor.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Standard layout, no reliance on the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import advisor  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build(out_dir: Path | str | None = None, scenario_key: str = "base") -> Path:
    """Run the advisor and return the path of the findings JSON.

    out_dir defaults to the project's data/ directory, so the advisor
    output always sits next to the dataset it was computed from.
    """
    result = advisor.run_advisor(scenario_key=scenario_key)
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
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return out_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build SNG advisor findings.")
    parser.add_argument("--out", type=str, default=None, help="Output directory (default data/).")
    parser.add_argument("--scenario", type=str, default="base",
                        help="Scenario to review as the design (default base).")
    args = parser.parse_args(argv)
    path = build(out_dir=args.out, scenario_key=args.scenario)
    print(f"Advisor complete. Wrote {path}")


if __name__ == "__main__":
    main()
