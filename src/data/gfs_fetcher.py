"""Fetch GFS weather model data from NOMADS/AWS using Herbie"""

import warnings
from datetime import datetime, timedelta
from typing import Optional, Tuple
from dataclasses import dataclass
import xarray as xr
from herbie import Herbie
from src.config import GFS_BOUNDS

# Suppress cfgrib/xarray FutureWarnings about compat defaults
warnings.filterwarnings('ignore', category=FutureWarning, module='cfgrib')

# Data source priority: NOMADS is often faster than AWS
HERBIE_PRIORITY = ['nomads', 'aws']

# GFS run schedule
GFS_RUN_HOURS = [0, 6, 12, 18]
# GFS data typically starts appearing ~2.5 hours after init
GFS_PUBLISH_DELAY_HOURS = 2.5


@dataclass
class FetchResult:
    """Result of a GFS data fetch operation"""
    data: Optional[xr.Dataset]
    run_time: datetime
    hours_fetched: int
    hours_expected: int
    is_complete: bool
    percent_complete: float
    available_days: int

    @property
    def is_partial(self) -> bool:
        return not self.is_complete and self.hours_fetched > 0


def get_next_expected_run() -> Tuple[datetime, datetime]:
    """
    Get the next expected GFS run and when it should start publishing.

    Returns:
        tuple: (run_time, expected_publish_time)
    """
    now = datetime.utcnow()
    current_hour = now.hour

    # Find the next run hour
    for run_hour in GFS_RUN_HOURS:
        if run_hour > current_hour:
            next_run = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
            publish_time = next_run + timedelta(hours=GFS_PUBLISH_DELAY_HOURS)
            return next_run, publish_time

    # Next run is tomorrow's 00z
    next_run = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    publish_time = next_run + timedelta(hours=GFS_PUBLISH_DELAY_HOURS)
    return next_run, publish_time


def is_in_publishing_window(run_time: datetime) -> bool:
    """
    Check if we're in the publishing window for a GFS run.
    Publishing window: from expected publish time until 6 hours after run init.

    Args:
        run_time: GFS run timestamp

    Returns:
        bool: True if currently in publishing window
    """
    now = datetime.utcnow()
    publish_start = run_time + timedelta(hours=GFS_PUBLISH_DELAY_HOURS)
    publish_end = run_time + timedelta(hours=6)  # Next run starts

    return publish_start <= now <= publish_end


def get_latest_gfs_run(conservative: bool = True) -> datetime:
    """
    Get the timestamp of the latest GFS run.
    GFS runs 4 times daily at 00, 06, 12, 18 UTC.

    Args:
        conservative: If True, use 3-hour delay to check for data availability.
                     If False, return the most recent run time (may not be available yet).

    Returns:
        datetime: Timestamp of latest GFS run
    """
    now = datetime.utcnow()

    # GFS runs at 00, 06, 12, 18 UTC
    run_hours = [0, 6, 12, 18]

    if conservative:
        # GFS data typically starts appearing on NOMADS ~2.5-3 hours after init
        # Use 3-hour delay for checking (we still require full data before displaying)
        DATA_DELAY_HOURS = 3
        check_time = now - timedelta(hours=DATA_DELAY_HOURS)
    else:
        # Return the most recent run time (caller will handle if not available)
        check_time = now

    # Find the most recent run time
    current_hour = check_time.hour
    latest_run_hour = max([h for h in run_hours if h <= current_hour], default=18)

    # If current hour is before first run, go back to previous day's last run
    if current_hour < run_hours[0]:
        run_time = check_time.replace(hour=18, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        run_time = check_time.replace(hour=latest_run_hour, minute=0, second=0, microsecond=0)

    return run_time


def get_newest_possible_run() -> datetime:
    """
    Get the timestamp of the newest possible GFS run (may not be available yet).
    This is the most recent run time based on current UTC time.

    Returns:
        datetime: Timestamp of newest possible GFS run
    """
    return get_latest_gfs_run(conservative=False)


def check_run_available(run_time: datetime) -> bool:
    """
    Quick check if a GFS run is available by testing forecast hour 0.

    Args:
        run_time: GFS run timestamp to check

    Returns:
        bool: True if run appears to be available
    """
    try:
        H = Herbie(
            date=run_time,
            model='gfs',
            product='pgrb2.0p50',
            fxx=0,
            priority=HERBIE_PRIORITY,
            verbose=False
        )
        # Try to get the index - this is fast and tells us if data exists
        H.xarray(searchString='TMP:2 m', remove_grib=True)
        return True
    except Exception:
        return False


def fetch_gfs_temperature(run_time: Optional[datetime] = None,
                         forecast_hours: int = 336,
                         _retry_count: int = 0) -> xr.Dataset:
    """
    Fetch GFS 2m temperature data from AWS using 0.5 degree resolution product.

    Args:
        run_time: GFS model run time (default: latest available)
        forecast_hours: Number of forecast hours to fetch (default: 336 for 14 days)
        _retry_count: Internal counter to prevent infinite recursion

    Returns:
        xarray.Dataset: Temperature data with lat, lon, and time dimensions

    Note:
        Uses pgrb2.0p50 (0.5 degree resolution) which has forecasts out to 384 hours (16 days)
        Default set to 336 hours (14 days) for reliability
    """
    if run_time is None:
        run_time = get_latest_gfs_run()

    # Quick check: is this run available at all?
    print(f"\nChecking availability of {run_time.strftime('%Y-%m-%d %H:%M')} UTC run...")
    if not check_run_available(run_time):
        if _retry_count < 4:  # Try up to 4 previous runs (24 hours back)
            prev_run = get_previous_gfs_run(run_time)
            print(f"  ✗ {run_time.strftime('%Y-%m-%d %H:%M')} UTC not available, trying {prev_run.strftime('%Y-%m-%d %H:%M')} UTC...")
            return fetch_gfs_temperature(prev_run, forecast_hours, _retry_count + 1)
        else:
            raise RuntimeError(f"No GFS data available for the last 24 hours. Please try again later.")

    print(f"  ✓ Run available, fetching data...")

    # Create list to store data from each forecast hour
    datasets = []

    # GFS outputs are typically every 3 hours for first 120 hours, then 6 hours
    # For simplicity, we'll fetch every 6 hours
    forecast_range = range(0, forecast_hours + 1, 6)

    print(f"\nFetching GFS data for run: {run_time.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Forecast range: 0 to {forecast_hours} hours ({len(list(forecast_range))} data points)")

    successful_fetches = 0
    failed_fetches = 0

    for fxx in forecast_range:
        try:
            # Create Herbie object for this forecast hour
            # Use NOMADS as primary source (often faster than AWS)
            H = Herbie(
                date=run_time,
                model='gfs',
                product='pgrb2.0p50',  # 0.5 degree resolution (supports up to 384 hours)
                fxx=fxx,
                priority=HERBIE_PRIORITY,
                verbose=False  # Suppress verbose output (fixes Windows Unicode issues)
            )

            # Download temperature at 2 meters
            # Use subset to only download our region of interest
            ds = H.xarray(
                searchString='TMP:2 m',
                remove_grib=True
            )

            # Handle case where xarray returns a list (multiple matches)
            if isinstance(ds, list):
                ds = ds[0]  # Take first dataset

            # Subset to our geographic bounds
            lat_min, lat_max = GFS_BOUNDS['lat']
            lon_min, lon_max = GFS_BOUNDS['lon']

            # Handle longitude conversion (GFS uses 0-360, we use -180 to 180)
            if lon_min < 0:
                lon_min += 360
            if lon_max < 0:
                lon_max += 360

            ds = ds.sel(
                latitude=slice(lat_max, lat_min),  # GFS latitude is descending
                longitude=slice(lon_min, lon_max)
            )

            # Drop problematic scalar coordinates that cause conflicts during concat
            # These vary between forecast hours and cause NaN values when merged
            coords_to_drop = ['step', 'heightAboveGround', 'valid_time', 'surface', 'gribfile_projection']
            for coord in coords_to_drop:
                if coord in ds.coords:
                    ds = ds.drop_vars(coord)

            datasets.append(ds)
            successful_fetches += 1

            # Show progress every 20 hours
            if fxx % 24 == 0:
                print(f"  ✓ Fetched forecast hour {fxx} ({len(datasets)} points so far)")

        except Exception as e:
            failed_fetches += 1
            if failed_fetches <= 3:  # Only print first few errors to avoid spam
                print(f"  ✗ Warning: Could not fetch forecast hour {fxx}: {e}")
            elif failed_fetches == 4:
                print(f"  ... (suppressing further error messages)")
            continue

    print(f"\nFetch complete: {successful_fetches} successful, {failed_fetches} failed", flush=True)

    expected_points = len(list(range(0, forecast_hours + 1, 6)))
    # Require 95% of data points to ensure complete 14-day forecast
    min_required = int(expected_points * 0.95)

    if len(datasets) < min_required:
        raise RuntimeError(
            f"Incomplete GFS data for {run_time.strftime('%Y-%m-%d %H:%M')} UTC run. "
            f"Only {len(datasets)} of {expected_points} forecast hours available (need {min_required}+). "
            f"The GFS run is still being published. Please try again in a few minutes."
        )

    # Debug: Check coordinate consistency before concat
    print(f"DEBUG: Checking coordinate consistency across {len(datasets)} datasets...", flush=True)
    lat_shapes = set()
    lon_shapes = set()
    for i, ds in enumerate(datasets):
        lat_shapes.add(ds.latitude.shape)
        lon_shapes.add(ds.longitude.shape)
    if len(lat_shapes) > 1 or len(lon_shapes) > 1:
        print(f"WARNING: Inconsistent coordinate shapes! lat_shapes={lat_shapes}, lon_shapes={lon_shapes}", flush=True)
    else:
        print(f"DEBUG: All datasets have consistent shapes: lat={lat_shapes}, lon={lon_shapes}", flush=True)

    # Combine all forecast hours into single dataset
    # Use coords='minimal' and compat='override' to handle datasets with different coordinate variables
    combined = xr.concat(datasets, dim='time', coords='minimal', compat='override')

    # Debug: Check for NaN in combined data
    temp_var = None
    for var in combined.data_vars:
        if 'TMP' in var or 't2m' in var.lower():
            temp_var = var
            break
    if temp_var:
        total_values = combined[temp_var].size
        nan_count = int(combined[temp_var].isnull().sum())
        if nan_count > 0:
            print(f"WARNING: Combined data has {nan_count}/{total_values} NaN values ({100*nan_count/total_values:.1f}%)", flush=True)
        else:
            print(f"DEBUG: Combined data has NO NaN values", flush=True)

    # Add run time as attribute
    combined.attrs['run_time'] = run_time.isoformat()

    return combined


def get_previous_gfs_run(current_run: datetime) -> datetime:
    """
    Get the timestamp of the previous GFS run (6 hours before current).

    Args:
        current_run: Current GFS run timestamp

    Returns:
        datetime: Previous GFS run timestamp
    """
    return current_run - timedelta(hours=6)


def fetch_gfs_partial(run_time: datetime,
                      forecast_hours: int = 336,
                      progress_callback: Optional[callable] = None,
                      start_hour: int = 0,
                      existing_data: Optional[xr.Dataset] = None) -> FetchResult:
    """
    Fetch whatever GFS data is currently available for a run (partial fetch allowed).

    Unlike fetch_gfs_temperature, this function:
    - Does NOT fall back to previous runs
    - Does NOT raise errors for incomplete data
    - Returns whatever is available along with progress info
    - Can RESUME from a previous fetch by specifying start_hour and existing_data

    Args:
        run_time: GFS model run time to fetch
        forecast_hours: Target forecast hours (default: 336 for 14 days)
        progress_callback: Optional callback(hours_fetched, hours_expected) for progress updates
        start_hour: Forecast hour to start fetching from (default: 0, use for resume)
        existing_data: Previously fetched xarray Dataset to merge with new data

    Returns:
        FetchResult: Contains data, completeness info, and progress
    """
    expected_points = len(list(range(0, forecast_hours + 1, 6)))

    # Quick check: is this run available at all?
    if not check_run_available(run_time):
        return FetchResult(
            data=None,
            run_time=run_time,
            hours_fetched=0,
            hours_expected=expected_points,
            is_complete=False,
            percent_complete=0.0,
            available_days=0
        )

    # Create list to store data from each forecast hour
    datasets = []

    # If resuming, start from specified hour instead of 0
    forecast_range = list(range(start_hour, forecast_hours + 1, 6))

    # Calculate how many points we already have from existing data
    existing_points = start_hour // 6 if start_hour > 0 else 0

    if start_hour > 0:
        print(f"\nResuming GFS fetch for run: {run_time.strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"Starting from hour {start_hour} (already have {existing_points} points)")
    else:
        print(f"\nFetching GFS data for run: {run_time.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Target: {forecast_hours} hours ({expected_points} data points)")

    for idx, fxx in enumerate(forecast_range):
        try:
            H = Herbie(
                date=run_time,
                model='gfs',
                product='pgrb2.0p50',
                fxx=fxx,
                priority=HERBIE_PRIORITY,
                verbose=False
            )

            ds = H.xarray(
                searchString='TMP:2 m',
                remove_grib=True
            )

            if isinstance(ds, list):
                ds = ds[0]

            # Subset to our geographic bounds
            lat_min, lat_max = GFS_BOUNDS['lat']
            lon_min, lon_max = GFS_BOUNDS['lon']

            if lon_min < 0:
                lon_min += 360
            if lon_max < 0:
                lon_max += 360

            ds = ds.sel(
                latitude=slice(lat_max, lat_min),
                longitude=slice(lon_min, lon_max)
            )

            # Drop problematic scalar coordinates that cause conflicts during concat
            # These vary between forecast hours and cause NaN values when merged
            coords_to_drop = ['step', 'heightAboveGround', 'valid_time', 'surface', 'gribfile_projection']
            for coord in coords_to_drop:
                if coord in ds.coords:
                    ds = ds.drop_vars(coord)

            datasets.append(ds)

            # Progress callback (include existing points in count)
            total_fetched = existing_points + len(datasets)
            if progress_callback:
                progress_callback(total_fetched, expected_points)

            # Show progress every 24 hours
            if fxx % 24 == 0:
                pct = (total_fetched / expected_points) * 100
                print(f"  ✓ Hour {fxx}: {total_fetched}/{expected_points} ({pct:.0f}%)")

        except Exception as e:
            # Stop at first failure - this is where publishing has stopped
            print(f"  ○ Hour {fxx} not yet available (stopping here)")
            break

    new_points = len(datasets)
    total_hours_fetched = existing_points + new_points
    percent = (total_hours_fetched / expected_points) * 100
    # Each day needs 4 data points (every 6 hours)
    available_days = total_hours_fetched // 4

    print(f"\nFetch result: {total_hours_fetched}/{expected_points} hours ({percent:.1f}%), {available_days} days")

    if total_hours_fetched == 0:
        return FetchResult(
            data=None,
            run_time=run_time,
            hours_fetched=0,
            hours_expected=expected_points,
            is_complete=False,
            percent_complete=0.0,
            available_days=0
        )

    # Combine new data (if any)
    if new_points > 0:
        # Debug: Check coordinate consistency before concat
        print(f"DEBUG partial: Checking coordinate consistency across {len(datasets)} new datasets...", flush=True)
        lat_shapes = set()
        lon_shapes = set()
        for i, ds in enumerate(datasets):
            lat_shapes.add(ds.latitude.shape)
            lon_shapes.add(ds.longitude.shape)
        if len(lat_shapes) > 1 or len(lon_shapes) > 1:
            print(f"WARNING partial: Inconsistent coordinate shapes! lat_shapes={lat_shapes}, lon_shapes={lon_shapes}", flush=True)
        else:
            print(f"DEBUG partial: All new datasets have consistent shapes: lat={lat_shapes}, lon={lon_shapes}", flush=True)

        # Debug: Show first dataset structure
        print(f"DEBUG partial: First dataset dims: {dict(datasets[0].dims)}", flush=True)
        print(f"DEBUG partial: First dataset data_vars: {list(datasets[0].data_vars)}", flush=True)

        # Use coords='minimal' and compat='override' to handle datasets with different coordinate variables
        new_combined = xr.concat(datasets, dim='time', coords='minimal', compat='override')
        print(f"DEBUG partial: After concat dims: {dict(new_combined.dims)}", flush=True)

        # Merge with existing data if provided
        if existing_data is not None:
            print(f"DEBUG partial: Existing data dims: {dict(existing_data.dims)}", flush=True)
            combined = xr.concat([existing_data, new_combined], dim='time', coords='minimal', compat='override')
            print(f"DEBUG partial: After merge with existing, combined dims: {dict(combined.dims)}", flush=True)
        else:
            combined = new_combined

        # Debug: Check for NaN in combined data
        temp_var = None
        for var in combined.data_vars:
            if 'TMP' in var or 't2m' in var.lower():
                temp_var = var
                break
        if temp_var:
            total_values = combined[temp_var].size
            nan_count = int(combined[temp_var].isnull().sum())
            if nan_count > 0:
                print(f"WARNING partial: Combined data has {nan_count}/{total_values} NaN values ({100*nan_count/total_values:.1f}%)", flush=True)
            else:
                print(f"DEBUG partial: Combined data has NO NaN values", flush=True)
    elif existing_data is not None:
        # No new data, just return existing
        print(f"DEBUG partial: No new data, using existing_data with dims: {dict(existing_data.dims)}", flush=True)
        combined = existing_data
    else:
        # No data at all
        return FetchResult(
            data=None,
            run_time=run_time,
            hours_fetched=0,
            hours_expected=expected_points,
            is_complete=False,
            percent_complete=0.0,
            available_days=0
        )

    combined.attrs['run_time'] = run_time.isoformat()
    # Store last fetched hour for resume capability
    # Only update if we actually fetched new data; otherwise preserve existing attr
    if new_points > 0:
        # Last fetched hour is start_hour + (new_points - 1) * 6
        # e.g., if we fetched hours 0,6,12 (3 points), last fetched = 0 + 2*6 = 12
        last_fetched_hour = start_hour + (new_points - 1) * 6
        combined.attrs['last_fetched_hour'] = last_fetched_hour
    # If no new data, keep the existing last_fetched_hour attr unchanged

    is_complete = total_hours_fetched >= int(expected_points * 0.95)

    return FetchResult(
        data=combined,
        run_time=run_time,
        hours_fetched=total_hours_fetched,
        hours_expected=expected_points,
        is_complete=is_complete,
        percent_complete=percent,
        available_days=available_days
    )
