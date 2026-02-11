"""Extract temperature data at specific city locations for demand-weighted analysis"""

import numpy as np
import pandas as pd
import xarray as xr
from typing import Dict, List, Optional
from src.config import POPULATION_CENTERS, get_all_locations


def kelvin_to_fahrenheit(temp_k: float) -> float:
    """Convert temperature from Kelvin to Fahrenheit"""
    return (temp_k - 273.15) * 9/5 + 32


def extract_all_temperatures(gfs_data: xr.Dataset) -> Dict[str, List[float]]:
    """
    Extract temperature time series at all population centers.

    Args:
        gfs_data: xarray Dataset with GFS temperature data

    Returns:
        dict: Location ID -> list of daily average temperatures (°F)
    """
    return extract_location_temperatures(gfs_data, POPULATION_CENTERS)


def extract_population_center_temperatures(gfs_data: xr.Dataset) -> Dict[str, List[float]]:
    """
    Extract temperature time series at population centers.

    Args:
        gfs_data: xarray Dataset with GFS temperature data

    Returns:
        dict: Location ID -> list of daily average temperatures (°F)
    """
    return extract_location_temperatures(gfs_data, POPULATION_CENTERS)


def extract_location_temperatures(
    gfs_data: xr.Dataset,
    locations: Dict[str, Dict]
) -> Dict[str, List[float]]:
    """
    Extract temperature time series at specified locations.

    Args:
        gfs_data: xarray Dataset with GFS temperature data
        locations: Dict of location_id -> location info (must have 'lat', 'lon')

    Returns:
        dict: Location ID -> list of daily average temperatures (°F)
    """
    location_temps = {}

    # Get the temperature variable (might be named 't2m', 'TMP', or similar)
    temp_var = None
    for var in gfs_data.data_vars:
        if 'TMP' in var or 't2m' in var.lower() or 'temperature' in var.lower():
            temp_var = var
            break

    if temp_var is None:
        raise ValueError("Could not find temperature variable in GFS data")

    # Debug: show data bounds and structure
    lats = gfs_data.latitude.values
    lons = gfs_data.longitude.values
    print(f"DEBUG: GFS data bounds - Lat: {lats.min():.1f} to {lats.max():.1f}, Lon: {lons.min():.1f} to {lons.max():.1f}", flush=True)
    print(f"DEBUG: GFS data dimensions: {dict(gfs_data.dims)}", flush=True)
    print(f"DEBUG: Temperature variable '{temp_var}' shape: {gfs_data[temp_var].shape}", flush=True)
    print(f"DEBUG: Extracting temperatures for {len(locations)} cities...", flush=True)

    for location_id, location_info in locations.items():
        lat = location_info['lat']
        lon = location_info['lon']

        # Convert longitude to 0-360 if needed (GFS uses 0-360)
        original_lon = lon
        if lon < 0:
            lon += 360

        # Select nearest grid point to location
        try:
            location_data = gfs_data[temp_var].sel(
                latitude=lat,
                longitude=lon,
                method='nearest'
            )
        except Exception as e:
            name = location_info.get('name', location_id)
            print(f"ERROR: Could not extract data for {name} (lat={lat}, lon={original_lon}->{lon}): {e}", flush=True)
            continue

        # Debug: Check shape and NaN in selected data
        raw_values = location_data.values
        name = location_info.get('name', location_id)

        # Ensure we have a 1D array (flatten if needed)
        if raw_values.ndim == 0:
            # Scalar - wrap in array
            raw_values = np.array([raw_values])
        elif raw_values.ndim > 1:
            # Multi-dimensional - flatten along time axis
            raw_values = raw_values.flatten()

        # Debug shape for first city only
        if location_id == list(locations.keys())[0]:
            print(f"DEBUG: {name} raw selection dims: {location_data.dims}", flush=True)
            print(f"DEBUG: {name} selected data shape: {raw_values.shape}, size: {raw_values.size}", flush=True)

        # Check if we got any data
        if raw_values.size == 0:
            print(f"WARNING: {name} has EMPTY data array!", flush=True)
            continue

        nan_count_raw = np.isnan(raw_values).sum() if raw_values.size > 0 else 0
        if nan_count_raw > 0:
            nan_indices = np.where(np.isnan(raw_values))[0]
            # Convert indices to forecast hours (each index is 6 hours)
            nan_hours = [idx * 6 for idx in nan_indices]
            print(f"WARNING: {name} has {nan_count_raw} NaN values at forecast hours: {nan_hours[:20]}{'...' if len(nan_hours) > 20 else ''}", flush=True)

        # Convert to Fahrenheit
        temps_f = kelvin_to_fahrenheit(raw_values)

        # Debug for first city: show array size going into daily avg
        if location_id == list(locations.keys())[0]:
            print(f"DEBUG: {name} temps_f length: {len(temps_f)}, expected days: {len(temps_f) // 4}", flush=True)

        # Compute daily averages
        # Assuming data is 6-hourly, we'll take 4 points per day
        daily_temps = compute_daily_averages(temps_f, points_per_day=4)

        name = location_info.get('name', location_id)
        print(f"  ✓ {name}: {len(daily_temps)} days extracted", flush=True)

        location_temps[location_id] = daily_temps

    print(f"DEBUG: Successfully extracted {len(location_temps)}/{len(locations)} cities", flush=True)
    return location_temps


def compute_daily_averages(hourly_temps: np.ndarray,
                          points_per_day: int = 4) -> List[float]:
    """
    Compute daily average temperatures from sub-daily data.

    Args:
        hourly_temps: Array of temperature values
        points_per_day: Number of data points per day (4 for 6-hourly, 8 for 3-hourly)

    Returns:
        list: Daily average temperatures
    """
    # Check for NaN values in raw data
    nan_count = np.isnan(hourly_temps).sum()
    if nan_count > 0:
        nan_indices = np.where(np.isnan(hourly_temps))[0]
        print(f"WARNING: {nan_count} NaN values in hourly temps at indices: {nan_indices.tolist()[:20]}{'...' if len(nan_indices) > 20 else ''}", flush=True)

    # Reshape into days and compute mean
    num_complete_days = len(hourly_temps) // points_per_day
    temps_reshaped = hourly_temps[:num_complete_days * points_per_day].reshape(
        num_complete_days, points_per_day
    )

    # Use nanmean to handle NaN values gracefully (average of non-NaN values)
    daily_avgs = np.nanmean(temps_reshaped, axis=1)

    # Check if any days still have NaN (all 4 values were NaN)
    nan_days = np.where(np.isnan(daily_avgs))[0]
    if len(nan_days) > 0:
        print(f"WARNING: Days with all-NaN temps: {nan_days.tolist()}", flush=True)

    return daily_avgs.tolist()


def create_temperature_dataframe(
    location_temps: Dict[str, List[float]],
    forecast_days: int = 14
) -> pd.DataFrame:
    """
    Create a DataFrame with daily temperatures for each location.

    Args:
        location_temps: Dict of location_id -> daily temperatures
        forecast_days: Number of forecast days (default: 14)

    Returns:
        pd.DataFrame: Temperatures with day index and location columns
    """
    locations = POPULATION_CENTERS

    # Ensure we have the right number of days
    trimmed_temps = {}
    for loc_id in location_temps:
        trimmed_temps[loc_id] = location_temps[loc_id][:forecast_days]

    # Create DataFrame
    df = pd.DataFrame(trimmed_temps)

    # Add day index (starts at 1)
    df.index = range(1, len(df) + 1)
    df.index.name = 'Day'

    # Rename columns to location names
    col_names = {}
    for loc_id in df.columns:
        if loc_id in locations:
            col_names[loc_id] = locations[loc_id]['name']
        else:
            col_names[loc_id] = loc_id
    df = df.rename(columns=col_names)

    return df
