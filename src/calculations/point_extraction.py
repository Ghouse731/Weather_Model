"""Extract temperature data at specific hub locations"""

import numpy as np
import pandas as pd
import xarray as xr
from typing import Dict, List
from src.config import HUBS


def kelvin_to_fahrenheit(temp_k: float) -> float:
    """Convert temperature from Kelvin to Fahrenheit"""
    return (temp_k - 273.15) * 9/5 + 32


def extract_hub_temperatures(gfs_data: xr.Dataset) -> Dict[str, List[float]]:
    """
    Extract temperature time series at each hub location.

    Args:
        gfs_data: xarray Dataset with GFS temperature data

    Returns:
        dict: Hub name -> list of daily average temperatures (°F)
    """
    hub_temps = {}

    # Get the temperature variable (might be named 't2m', 'TMP', or similar)
    temp_var = None
    for var in gfs_data.data_vars:
        if 'TMP' in var or 't2m' in var.lower() or 'temperature' in var.lower():
            temp_var = var
            break

    if temp_var is None:
        raise ValueError("Could not find temperature variable in GFS data")

    for hub_id, hub_info in HUBS.items():
        lat = hub_info['lat']
        lon = hub_info['lon']

        # Convert longitude to 0-360 if needed (GFS uses 0-360)
        if lon < 0:
            lon += 360

        # Select nearest grid point to hub location
        try:
            hub_data = gfs_data[temp_var].sel(
                latitude=lat,
                longitude=lon,
                method='nearest'
            )
        except Exception as e:
            print(f"Warning: Could not extract data for {hub_info['name']}: {e}")
            continue

        # Convert to Fahrenheit
        temps_f = kelvin_to_fahrenheit(hub_data.values)

        # Compute daily averages
        # Assuming data is 6-hourly, we'll take 4 points per day
        daily_temps = compute_daily_averages(temps_f, points_per_day=4)

        hub_temps[hub_id] = daily_temps

    return hub_temps


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
    # Reshape into days and compute mean
    num_complete_days = len(hourly_temps) // points_per_day
    temps_reshaped = hourly_temps[:num_complete_days * points_per_day].reshape(
        num_complete_days, points_per_day
    )

    daily_avgs = np.mean(temps_reshaped, axis=1)

    return daily_avgs.tolist()


def create_temperature_dataframe(hub_temps: Dict[str, List[float]],
                                 forecast_days: int = 14) -> pd.DataFrame:
    """
    Create a DataFrame with daily temperatures for each hub.

    Args:
        hub_temps: Dict of hub_id -> daily temperatures
        forecast_days: Number of forecast days (default: 14)

    Returns:
        pd.DataFrame: Temperatures with day index and hub columns
    """
    # Ensure we have the right number of days
    for hub_id in hub_temps:
        hub_temps[hub_id] = hub_temps[hub_id][:forecast_days]

    # Create DataFrame
    df = pd.DataFrame(hub_temps)

    # Add day index (starts at 1)
    df.index = range(1, len(df) + 1)
    df.index.name = 'Day'

    # Rename columns to hub names
    df.columns = [HUBS[hub_id]['name'] for hub_id in df.columns]

    return df
