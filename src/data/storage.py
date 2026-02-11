"""Data storage and retrieval for GFS model runs"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List
from src.config import DATA_DIR, MAX_STORED_RUNS, FORECAST_DAYS, POPULATION_CENTERS


def ensure_data_directory():
    """Create data directory if it doesn't exist"""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def get_run_filename(run_time: datetime, partial: bool = False) -> str:
    """
    Generate filename for a model run.

    Args:
        run_time: GFS run timestamp
        partial: If True, generate filename for partial/in-progress run

    Returns:
        str: Filename in format gfs_YYYYMMDD_HH.json or gfs_YYYYMMDD_HH_partial.json
    """
    base = f"gfs_{run_time.strftime('%Y%m%d_%H')}"
    return f"{base}_partial.json" if partial else f"{base}.json"


def save_model_run(run_time: datetime, city_data: Dict[str, Dict],
                   aggregates: Optional[Dict] = None,
                   vs_normal: Optional[Dict] = None):
    """
    Save model run data to JSON file.

    Args:
        run_time: GFS run timestamp
        city_data: Dict with city results from calculate_all_hubs_degree_days()
        aggregates: Optional dict with national/regional aggregates
        vs_normal: Optional dict with deviation from normal data

    Raises:
        ValueError: If data has fewer than FORECAST_DAYS days
    """
    ensure_data_directory()

    # Check all cities have enough days (not just the first one)
    print(f"DEBUG save_model_run: Checking {len(city_data)} cities...", flush=True)
    min_days = None
    min_city = None
    for city_id, city_data_item in city_data.items():
        days = len(city_data_item.get('daily_temps', []))
        print(f"  - {city_id}: {days} days", flush=True)
        if min_days is None or days < min_days:
            min_days = days
            min_city = city_id

    forecast_days = min_days if min_days is not None else 0
    print(f"DEBUG: min_days={forecast_days} (from {min_city}), FORECAST_DAYS={FORECAST_DAYS}", flush=True)

    # Don't save incomplete runs
    if forecast_days < FORECAST_DAYS:
        print(f"ERROR: Incomplete run - {min_city} has only {forecast_days} days (expected {FORECAST_DAYS})", flush=True)
        raise ValueError(
            f"Refusing to save incomplete run: {min_city} has only {forecast_days} days "
            f"(expected {FORECAST_DAYS}). Data may not be fully published yet."
        )

    print(f"DEBUG: All cities have >= {FORECAST_DAYS} days, proceeding to save...", flush=True)

    data = {
        'run_time': run_time.isoformat(),
        'fetch_completed_at': datetime.now(timezone(timedelta(hours=-6))).strftime('%Y-%m-%d %I:%M %p CT'),
        'model': 'GFS',
        'forecast_days': forecast_days,
        'cities': city_data
    }

    # Add aggregates if available
    if aggregates:
        data['aggregates'] = aggregates

    # Add vs-normal data if available
    if vs_normal:
        data['vs_normal'] = vs_normal

    filepath = os.path.join(DATA_DIR, get_run_filename(run_time))

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    # Clean up old runs
    cleanup_old_runs()


def load_model_run(run_time: datetime) -> Optional[Dict]:
    """
    Load model run data from JSON file.

    Args:
        run_time: GFS run timestamp

    Returns:
        dict: Model run data, or None if file doesn't exist
    """
    filepath = os.path.join(DATA_DIR, get_run_filename(run_time))

    if not os.path.exists(filepath):
        return None

    with open(filepath, 'r') as f:
        data = json.load(f)

    return data


def get_city_data(run_data: Dict) -> Dict[str, Dict]:
    """
    Get city data from a run, handling both old and new formats.

    Args:
        run_data: Run data from load_model_run()

    Returns:
        dict: City location data
    """
    # New format uses 'cities' key
    if 'cities' in run_data:
        return run_data['cities']

    # Old format compatibility: check for 'hubs' or 'population_centers'
    all_data = {}
    if 'hubs' in run_data:
        all_data.update(run_data['hubs'])
    if 'population_centers' in run_data:
        all_data.update(run_data['population_centers'])

    # Filter to only population centers
    return {k: v for k, v in all_data.items() if k in POPULATION_CENTERS}


def get_latest_saved_run() -> Optional[Dict]:
    """
    Get the most recently saved model run with complete data.

    Returns:
        dict: Latest model run data, or None if no complete runs saved
    """
    ensure_data_directory()

    # Get all non-partial files
    files = sorted([f for f in os.listdir(DATA_DIR)
                    if f.startswith('gfs_') and f.endswith('.json') and '_partial' not in f])

    if not files:
        return None

    # Check files from newest to oldest, return first complete one
    for filename in reversed(files):
        filepath = os.path.join(DATA_DIR, filename)
        with open(filepath, 'r') as f:
            data = json.load(f)

        # Skip incomplete runs
        if data.get('forecast_days', 0) >= FORECAST_DAYS:
            return data

    return None


def get_all_saved_runs() -> List[Dict]:
    """
    Get all saved model runs sorted by run time.

    Returns:
        list: List of model run data dicts
    """
    ensure_data_directory()

    # Get all non-partial files
    files = sorted([f for f in os.listdir(DATA_DIR)
                    if f.startswith('gfs_') and f.endswith('.json') and '_partial' not in f])

    runs = []
    for filename in files:
        filepath = os.path.join(DATA_DIR, filename)
        with open(filepath, 'r') as f:
            data = json.load(f)
            runs.append(data)

    return runs


def cleanup_old_runs():
    """
    Remove old model run files, keeping only MAX_STORED_RUNS most recent.
    """
    ensure_data_directory()

    # Only clean up complete runs (not partial)
    files = sorted([f for f in os.listdir(DATA_DIR)
                    if f.startswith('gfs_') and f.endswith('.json') and '_partial' not in f])

    if len(files) > MAX_STORED_RUNS:
        files_to_delete = files[:-MAX_STORED_RUNS]

        for filename in files_to_delete:
            filepath = os.path.join(DATA_DIR, filename)
            os.remove(filepath)


def get_previous_run_data(current_run_time: datetime) -> Optional[Dict]:
    """
    Get the data for the previous model run.

    Args:
        current_run_time: Current run timestamp

    Returns:
        dict: Previous run data, or None if not available
    """
    from src.data.gfs_fetcher import get_previous_gfs_run

    prev_run_time = get_previous_gfs_run(current_run_time)
    return load_model_run(prev_run_time)


def save_partial_run(run_time: datetime, city_data: Dict[str, Dict],
                     percent_complete: float, hours_fetched: int, hours_expected: int,
                     last_fetched_hour: int = 0):
    """
    Save a partial/in-progress model run.

    Args:
        run_time: GFS run timestamp
        city_data: Dict with city results (may be partial)
        percent_complete: Percentage of data fetched (0-100)
        hours_fetched: Number of forecast hours fetched
        hours_expected: Total expected forecast hours
        last_fetched_hour: Last forecast hour that was successfully fetched (for resume)
    """
    ensure_data_directory()

    forecast_days = len(next(iter(city_data.values()))['daily_temps'])

    data = {
        'run_time': run_time.isoformat(),
        'model': 'GFS',
        'forecast_days': forecast_days,
        'is_complete': False,
        'percent_complete': percent_complete,
        'hours_fetched': hours_fetched,
        'hours_expected': hours_expected,
        'last_fetched_hour': last_fetched_hour,
        'cities': city_data
    }

    filepath = os.path.join(DATA_DIR, get_run_filename(run_time, partial=True))

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def load_partial_run(run_time: datetime) -> Optional[Dict]:
    """
    Load a partial/in-progress model run.

    Args:
        run_time: GFS run timestamp

    Returns:
        dict: Partial run data, or None if not found
    """
    filepath = os.path.join(DATA_DIR, get_run_filename(run_time, partial=True))

    if not os.path.exists(filepath):
        return None

    with open(filepath, 'r') as f:
        return json.load(f)


def delete_partial_run(run_time: datetime):
    """
    Delete a partial run file (called when run is complete).

    Args:
        run_time: GFS run timestamp
    """
    filepath = os.path.join(DATA_DIR, get_run_filename(run_time, partial=True))

    if os.path.exists(filepath):
        os.remove(filepath)


def promote_partial_to_complete(run_time: datetime, city_data: Dict[str, Dict],
                                aggregates: Optional[Dict] = None,
                                vs_normal: Optional[Dict] = None):
    """
    Promote a partial run to a complete run.
    Saves the complete data and removes the partial file.

    Args:
        run_time: GFS run timestamp
        city_data: Complete city data
        aggregates: Optional aggregates data
        vs_normal: Optional vs-normal data
    """
    # Save as complete
    save_model_run(run_time, city_data, aggregates, vs_normal)

    # Remove partial file
    delete_partial_run(run_time)


def get_latest_complete_run() -> Optional[Dict]:
    """
    Get the most recent complete (not partial) model run.

    Returns:
        dict: Latest complete run data, or None if none found
    """
    return get_latest_saved_run()
