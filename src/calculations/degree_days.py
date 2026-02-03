"""Calculate Heating and Cooling Degree Days"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from src.config import HDD_BASE, CDD_BASE


def calculate_hdd(daily_temp: float, base_temp: float = HDD_BASE) -> float:
    """
    Calculate Heating Degree Days for a single day.

    Args:
        daily_temp: Average temperature for the day (°F)
        base_temp: Base temperature for HDD calculation (default: 65°F)

    Returns:
        float: HDD value (0 if temp >= base)
    """
    return max(0, base_temp - daily_temp)


def calculate_cdd(daily_temp: float, base_temp: float = CDD_BASE) -> float:
    """
    Calculate Cooling Degree Days for a single day.

    Args:
        daily_temp: Average temperature for the day (°F)
        base_temp: Base temperature for CDD calculation (default: 65°F)

    Returns:
        float: CDD value (0 if temp <= base)
    """
    return max(0, daily_temp - base_temp)


def calculate_degree_days(daily_temps: List[float]) -> Tuple[List[float], List[float]]:
    """
    Calculate HDD and CDD for each day in the forecast.

    Args:
        daily_temps: List of daily average temperatures (°F)

    Returns:
        tuple: (list of daily HDD values, list of daily CDD values)
    """
    hdd_values = [calculate_hdd(temp) for temp in daily_temps]
    cdd_values = [calculate_cdd(temp) for temp in daily_temps]

    return hdd_values, cdd_values


def calculate_cumulative_degree_days(daily_temps: List[float]) -> Tuple[List[float], List[float]]:
    """
    Calculate cumulative HDD and CDD over the forecast period.

    Args:
        daily_temps: List of daily average temperatures (°F)

    Returns:
        tuple: (cumulative HDD by day, cumulative CDD by day)
    """
    hdd_daily, cdd_daily = calculate_degree_days(daily_temps)

    hdd_cumulative = np.cumsum(hdd_daily).tolist()
    cdd_cumulative = np.cumsum(cdd_daily).tolist()

    return hdd_cumulative, cdd_cumulative


def calculate_all_hubs_degree_days(hub_temps: Dict[str, List[float]]) -> Dict[str, Dict[str, List[float]]]:
    """
    Calculate HDD and CDD for all hubs.

    Args:
        hub_temps: Dict of hub_id -> daily temperatures

    Returns:
        dict: Nested dict with structure:
            {
                'hub_id': {
                    'daily_temps': [...],
                    'hdd': [...],
                    'cdd': [...],
                    'hdd_cumulative': [...],
                    'cdd_cumulative': [...]
                }
            }
    """
    results = {}

    for hub_id, temps in hub_temps.items():
        hdd_daily, cdd_daily = calculate_degree_days(temps)
        hdd_cumulative, cdd_cumulative = calculate_cumulative_degree_days(temps)

        results[hub_id] = {
            'daily_temps': temps,
            'hdd': hdd_daily,
            'cdd': cdd_daily,
            'hdd_cumulative': hdd_cumulative,
            'cdd_cumulative': cdd_cumulative
        }

    return results


def get_total_degree_days(hub_data: Dict[str, List[float]]) -> Tuple[float, float]:
    """
    Get total HDD and CDD for the entire forecast period.

    Args:
        hub_data: Hub data dict with 'hdd' and 'cdd' keys

    Returns:
        tuple: (total HDD, total CDD)
    """
    total_hdd = sum(hub_data['hdd'])
    total_cdd = sum(hub_data['cdd'])

    return total_hdd, total_cdd


def create_degree_days_dataframe(hub_results: Dict[str, Dict]) -> pd.DataFrame:
    """
    Create a summary DataFrame of degree days for all hubs.

    Args:
        hub_results: Results from calculate_all_hubs_degree_days()

    Returns:
        pd.DataFrame: Summary with total HDD/CDD for each hub
    """
    from src.config import HUBS

    summary_data = []

    for hub_id, data in hub_results.items():
        total_hdd, total_cdd = get_total_degree_days(data)

        from src.config import FORECAST_DAYS
        summary_data.append({
            'Hub': HUBS[hub_id]['name'],
            'Location': HUBS[hub_id]['location'],
            f'Total HDD ({FORECAST_DAYS}-day)': round(total_hdd, 1),
            f'Total CDD ({FORECAST_DAYS}-day)': round(total_cdd, 1),
            'Avg Daily Temp (°F)': round(np.mean(data['daily_temps']), 1)
        })

    return pd.DataFrame(summary_data)
