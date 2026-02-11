"""
HDD Delta Analysis Report
Calculates HDD deltas across consecutive, 12-hour, and 24-hour forecast run intervals.
Exports to Excel with multiple sheets.

Usage: python scripts/hdd_delta_report.py
Output: data/hdd_delta_report.xlsx
"""

import json
import sys
import os
from glob import glob
from datetime import datetime

import pandas as pd

# Add project root to path so we can import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import GAS_CONSUMPTION_CENTERS

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
OUTPUT_FILE = os.path.join(DATA_DIR, 'hdd_delta_report.xlsx')


def load_all_runs():
    """Load all complete GFS JSON files in chronological order."""
    pattern = os.path.join(DATA_DIR, 'gfs_*.json')
    files = sorted(glob(pattern))

    runs = []
    for filepath in files:
        # Skip partial files
        if '_partial' in filepath:
            continue

        with open(filepath, 'r') as f:
            data = json.load(f)

        run_time = datetime.fromisoformat(data['run_time'])
        runs.append({
            'run_time': run_time,
            'label': f"{run_time.month}/{run_time.day} {run_time.hour:02d}z",
            'cities': data['cities']
        })

    print(f"Loaded {len(runs)} forecast runs")
    for r in runs:
        print(f"  {r['label']}")
    return runs


def compute_total_hdds(runs):
    """Compute per-city total HDD and national GWHDD for each run."""
    rows = []
    for run in runs:
        row = {'Run': run['label']}

        # National GWHDD = sum of (city_total_hdd * gas_weight)
        national_gwhdd = 0.0

        for city_id, city_info in GAS_CONSUMPTION_CENTERS.items():
            city_data = run['cities'].get(city_id, {})
            hdd_list = city_data.get('hdd', [])
            total_hdd = sum(hdd_list)
            row[city_info['name']] = round(total_hdd, 1)
            national_gwhdd += total_hdd * city_info['gas_weight']

        row['National GWHDD'] = round(national_gwhdd, 1)
        rows.append(row)

    # Reorder columns: Run, National GWHDD, then cities
    city_names = [c['name'] for c in GAS_CONSUMPTION_CENTERS.values()]
    col_order = ['Run', 'National GWHDD'] + city_names
    return pd.DataFrame(rows)[col_order]


def compute_daily_gwhdd(runs):
    """Compute daily national GWHDD for each run (per forecast day)."""
    rows = []
    for run in runs:
        row = {'Run': run['label']}

        # Determine number of forecast days from first city
        first_city = next(iter(run['cities'].values()))
        num_days = len(first_city.get('hdd', []))

        for day in range(num_days):
            daily_gwhdd = 0.0
            for city_id, city_info in GAS_CONSUMPTION_CENTERS.items():
                city_data = run['cities'].get(city_id, {})
                hdd_list = city_data.get('hdd', [])
                if day < len(hdd_list):
                    daily_gwhdd += hdd_list[day] * city_info['gas_weight']
            row[f'Day {day + 1}'] = round(daily_gwhdd, 2)

        rows.append(row)

    return pd.DataFrame(rows)


def compute_deltas(df, offset, label):
    """
    Compute deltas between rows separated by `offset` positions.
    offset=1: consecutive (run-over-run, ~6hr)
    offset=2: 12-hour
    offset=4: 24-hour
    """
    numeric_cols = [c for c in df.columns if c != 'Run']
    delta_rows = []

    for i in range(offset, len(df)):
        current = df.iloc[i]
        previous = df.iloc[i - offset]
        row = {'Run': f"{current['Run']} vs {previous['Run']}"}

        for col in numeric_cols:
            curr_val = current[col]
            prev_val = previous[col]
            if pd.notna(curr_val) and pd.notna(prev_val):
                row[col] = round(curr_val - prev_val, 2)
            else:
                row[col] = None

        delta_rows.append(row)

    return pd.DataFrame(delta_rows)


def main():
    runs = load_all_runs()
    if len(runs) < 2:
        print("Need at least 2 runs to compute deltas. Exiting.")
        return

    print("\nComputing total HDDs...")
    total_hdd_df = compute_total_hdds(runs)

    print("Computing daily GWHDD...")
    daily_gwhdd_df = compute_daily_gwhdd(runs)

    print("Computing run-over-run deltas...")
    ror_delta_df = compute_deltas(total_hdd_df, offset=1, label="6hr")

    print("Computing 12-hour deltas...")
    delta_12h_df = compute_deltas(total_hdd_df, offset=2, label="12hr")

    print("Computing 24-hour deltas...")
    delta_24h_df = compute_deltas(total_hdd_df, offset=4, label="24hr")

    print("Computing daily GWHDD run-over-run deltas...")
    daily_delta_df = compute_deltas(daily_gwhdd_df, offset=1, label="Daily 6hr")

    # Write to Excel
    print(f"\nWriting to {OUTPUT_FILE}...")
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        total_hdd_df.to_excel(writer, sheet_name='Total HDD by Run', index=False)
        ror_delta_df.to_excel(writer, sheet_name='Run-over-Run Delta', index=False)
        delta_12h_df.to_excel(writer, sheet_name='12hr Delta', index=False)
        delta_24h_df.to_excel(writer, sheet_name='24hr Delta', index=False)
        daily_gwhdd_df.to_excel(writer, sheet_name='Daily GWHDD', index=False)
        daily_delta_df.to_excel(writer, sheet_name='Daily GWHDD Delta', index=False)

        # Auto-fit column widths
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for col_idx, col in enumerate(ws.columns, 1):
                max_len = max(len(str(cell.value or '')) for cell in col)
                header_len = len(str(col[0].value or ''))
                ws.column_dimensions[col[0].column_letter].width = max(max_len, header_len) + 3

    print(f"Done! Report saved to: {OUTPUT_FILE}")
    print(f"\nSheets:")
    print(f"  1. Total HDD by Run     - Raw totals per run")
    print(f"  2. Run-over-Run Delta   - 6hr changes (consecutive)")
    print(f"  3. 12hr Delta           - 12hr changes")
    print(f"  4. 24hr Delta           - 24hr changes")
    print(f"  5. Daily GWHDD          - Per-day national GWHDD")
    print(f"  6. Daily GWHDD Delta    - Per-day run-over-run changes")


if __name__ == '__main__':
    main()
