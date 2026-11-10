"""Fetch open data sources for the KL Mobility Lab project.

Downloads every open file used in Phase 1 (real data discovery) so that
anyone can re-fetch the same sources. Run from anywhere:

    python scripts/fetch_sources.py

All files are saved to data_raw/ next to this script's parent folder.
Sources, licences and limitations are documented in docs/SOURCE_CATALOGUE.md.

Downloads only; no downloaded file is parsed or executed here.
"""

import sys
import zipfile
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DATA_RAW = BASE / "data_raw"
DATA_RAW.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "kl-mobility-lab-fetch/1.0 (open data research)"}
SIZE_GUARD_MB = 80  # skip single files larger than this


def head_size_mb(url):
    """Return Content-Length in MB from a HEAD request, or None."""
    try:
        r = requests.head(url, headers=HEADERS, timeout=60, allow_redirects=True)
        size = r.headers.get("Content-Length")
        return int(size) / 1_048_576 if size else None
    except requests.RequestException:
        return None


def download(url, dest, guard=True):
    """Stream url to dest. Returns (ok, note)."""
    size_mb = head_size_mb(url)
    if guard and size_mb is not None and size_mb > SIZE_GUARD_MB:
        return False, f"skipped, {size_mb:.1f} MB exceeds {SIZE_GUARD_MB} MB guard"
    try:
        with requests.get(url, headers=HEADERS, timeout=300, stream=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except requests.RequestException as exc:
        return False, f"FAILED: {exc}"
    actual_mb = dest.stat().st_size / 1_048_576
    return True, f"saved {actual_mb:.2f} MB"


SOURCES = [
    # (url, local filename)
    # 1. Monthly-audited daily public transport ridership by mode (Prasarana / MoT via data.gov.my, CC BY 4.0)
    ("https://storage.data.gov.my/transportation/ridership_headline.parquet",
     "ridership_headline.parquet"),
    # 2. Daily origin-destination ridership, Rapid Rail Klang Valley, 2026 file
    #    (yearly files exist since 2023 at .../rail/rapidrail_<year>_daily.parquet)
    ("https://storage.data.gov.my/transportation/rail/rapidrail_2026_daily.parquet",
     "rapidrail_2026_daily.parquet"),
    # 3. GTFS static, Rapid Rail KL (Prasarana via data.gov.my realtime API, CC BY 4.0)
    ("https://api.data.gov.my/gtfs-static/prasarana?category=rapid-rail-kl",
     "gtfs_rapid_rail_kl.zip"),
    # 4. Car registration transactions 2026 (JPJ via data.gov.my, CC BY 4.0).
    #    One row per registration transaction; yearly files cars_<year>.parquet.
    ("https://storage.data.gov.my/transportation/cars_2026.parquet",
     "cars_2026.parquet"),
    # 5. DOSM Migration Survey Report Malaysia 2024, published tables
    #    (release-document-log links redirect to the actual files)
    ("https://www.dosm.gov.my/portal-main/release-document-log?release_document_id=17706",
     "dosm_migration_2024_tables_1_9_internal_migration.xlsx"),
    ("https://www.dosm.gov.my/portal-main/release-document-log?release_document_id=17708",
     "dosm_migration_2024_tables_17_21_socioeconomic.xlsx"),
    ("https://www.dosm.gov.my/portal-main/release-document-log?release_document_id=17711",
     "dosm_migration_2024_press_statement.pdf"),
    # 7. Population at district level (DOSM via data.gov.my, CC BY 4.0)
    ("https://storage.dosm.gov.my/population/population_district.parquet",
     "population_district.parquet"),
    # 7b. Quarterly principal labour force statistics by state (DOSM, CC BY 4.0)
    ("https://storage.dosm.gov.my/labour/lfs_qtr_state.parquet",
     "lfs_qtr_state.parquet"),
]


def main():
    results = []
    for url, name in SOURCES:
        dest = DATA_RAW / name
        ok, note = download(url, dest)
        results.append((name, ok, note))
        print(f"{'OK ' if ok else 'ERR'} {name}: {note}")

    # Unzip the GTFS feed into its own subfolder (data files only; nothing is executed).
    gtfs_zip = DATA_RAW / "gtfs_rapid_rail_kl.zip"
    if gtfs_zip.exists():
        out = DATA_RAW / "gtfs_rapid_rail_kl"
        out.mkdir(exist_ok=True)
        with zipfile.ZipFile(gtfs_zip) as z:
            z.extractall(out)
        print(f"OK  extracted GTFS to {out}")

    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"\n{len(failed)} download(s) failed or skipped: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
