"""Build data/advisor_findings.json for the manufacturing portfolio project.

Loads the exported rows from data/mfg_data.json, rebuilds the KPI-ready
dataframe, runs the deterministic rule engine in scripts/advisor.py and
writes data/advisor_findings.json. The JSON is strict: no NaN or Infinity,
missing numbers become null.

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

# Standard layout, no reliance on the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import advisor  # noqa: E402
import build_mfg_data  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build(out_dir: Path | str | None = None, json_path: Path | str | None = None) -> Path:
    """Run the advisor on the exported rows; return the findings JSON path.

    out_dir defaults to the project's data/ directory. It is used both to
    locate mfg_data.json (unless json_path overrides it) and to place
    advisor_findings.json, so the advisor output always sits next to the
    dataset it was computed from.
    """
    data_dir = Path(out_dir) if out_dir else PROJECT_ROOT / "data"
    src = Path(json_path) if json_path else data_dir / "mfg_data.json"
    payload = json.loads(src.read_text(encoding="utf-8"))
    df = build_mfg_data.rows_to_df(payload["rows"])

    result = advisor.run_advisor(df)
    out = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **result["meta"],
        },
        "findings": result["findings"],
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "advisor_findings.json"
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, allow_nan=False)
    return out_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build manufacturing advisor findings.")
    parser.add_argument("--json", type=str, default=None, help="Input JSON path (default data/mfg_data.json).")
    parser.add_argument("--out", type=str, default=None, help="Output directory (default data/).")
    args = parser.parse_args(argv)
    path = build(out_dir=args.out, json_path=args.json)
    print(f"Advisor complete. Wrote {path}")


if __name__ == "__main__":
    main()
