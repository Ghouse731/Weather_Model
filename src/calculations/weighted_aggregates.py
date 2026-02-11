"""
Calculate gas-weighted degree day aggregates for natural gas demand analysis.

This module provides functions to calculate:
- Gas-weighted HDD/CDD for individual locations (GWHDD)
- Regional aggregates (Northeast, Midwest, South, West)
- National aggregate across all gas consumption centers

Weights are derived from EIA 5-year average state-level gas consumption data.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from src.config import GAS_CONSUMPTION_CENTERS, REGIONS, get_region_gas_weight, get_total_gas_weight, HDD_BASE, CDD_BASE

# Alias for backward compatibility
POPULATION_CENTERS = GAS_CONSUMPTION_CENTERS


def calculate_gas_weighted_dd(
    location_data: Dict[str, Dict],
    location_type: str = 'gas_centers'
) -> Dict[str, float]:
    """
    Calculate gas-weighted HDD and CDD totals (GWHDD/GWCDD).

    Args:
        location_data: Dict of location_id -> degree day data
                      Each entry should have 'hdd_cumulative' and 'cdd_cumulative' lists
        location_type: 'gas_centers' to weight by gas consumption

    Returns:
        dict with:
        - 'weighted_hdd': Gas-weighted total HDD (GWHDD)
        - 'weighted_cdd': Gas-weighted total CDD (GWCDD)
        - 'total_weight': Total gas weight used (should be ~1.0)
    """
    total_weighted_hdd = 0.0
    total_weighted_cdd = 0.0
    total_weight = 0.0

    for location_id, data in location_data.items():
        # Only include gas consumption centers for weighted calculation
        if location_id not in GAS_CONSUMPTION_CENTERS:
            continue

        gas_weight = GAS_CONSUMPTION_CENTERS[location_id]['gas_weight']

        # Get total HDD/CDD (last value of cumulative, or sum of daily)
        if 'hdd_cumulative' in data and data['hdd_cumulative']:
            total_hdd = data['hdd_cumulative'][-1]
        elif 'hdd' in data and data['hdd']:
            total_hdd = sum(data['hdd'])
        else:
            total_hdd = 0

        if 'cdd_cumulative' in data and data['cdd_cumulative']:
            total_cdd = data['cdd_cumulative'][-1]
        elif 'cdd' in data and data['cdd']:
            total_cdd = sum(data['cdd'])
        else:
            total_cdd = 0

        # Weight by gas consumption
        total_weighted_hdd += total_hdd * gas_weight
        total_weighted_cdd += total_cdd * gas_weight
        total_weight += gas_weight

    # Normalize by total weight to get weighted average
    if total_weight > 0:
        weighted_hdd = total_weighted_hdd / total_weight
        weighted_cdd = total_weighted_cdd / total_weight
    else:
        weighted_hdd = 0.0
        weighted_cdd = 0.0

    return {
        'weighted_hdd': round(weighted_hdd, 1),
        'weighted_cdd': round(weighted_cdd, 1),
        'total_weight': round(total_weight, 3)
    }

# Alias for backward compatibility
def calculate_population_weighted_dd(location_data, location_type='population_centers'):
    """Alias for calculate_gas_weighted_dd for backward compatibility."""
    return calculate_gas_weighted_dd(location_data, location_type)


def calculate_regional_aggregates(
    location_data: Dict[str, Dict]
) -> Dict[str, Dict]:
    """
    Calculate gas-weighted aggregates for each region.

    Args:
        location_data: Dict of location_id -> degree day data

    Returns:
        dict: region_id -> {
            'name': str,
            'weighted_hdd': float,
            'weighted_cdd': float,
            'total_weight': float,
            'cities_included': list
        }
    """
    results = {}

    for region_id, region_info in REGIONS.items():
        total_weighted_hdd = 0.0
        total_weighted_cdd = 0.0
        total_weight = 0.0
        cities_included = []

        for city_id in region_info['cities']:
            if city_id not in location_data or city_id not in GAS_CONSUMPTION_CENTERS:
                continue

            data = location_data[city_id]
            gas_weight = GAS_CONSUMPTION_CENTERS[city_id]['gas_weight']

            # Get total HDD/CDD
            if 'hdd_cumulative' in data and data['hdd_cumulative']:
                total_hdd = data['hdd_cumulative'][-1]
            elif 'hdd' in data and data['hdd']:
                total_hdd = sum(data['hdd'])
            else:
                total_hdd = 0

            if 'cdd_cumulative' in data and data['cdd_cumulative']:
                total_cdd = data['cdd_cumulative'][-1]
            elif 'cdd' in data and data['cdd']:
                total_cdd = sum(data['cdd'])
            else:
                total_cdd = 0

            total_weighted_hdd += total_hdd * gas_weight
            total_weighted_cdd += total_cdd * gas_weight
            total_weight += gas_weight
            cities_included.append(city_id)

        # Normalize
        if total_weight > 0:
            weighted_hdd = total_weighted_hdd / total_weight
            weighted_cdd = total_weighted_cdd / total_weight
        else:
            weighted_hdd = 0.0
            weighted_cdd = 0.0

        results[region_id] = {
            'name': region_info['name'],
            'weighted_hdd': round(weighted_hdd, 1),
            'weighted_cdd': round(weighted_cdd, 1),
            'total_weight': round(total_weight, 3),
            'cities_included': cities_included
        }

    return results


def calculate_national_aggregate(
    location_data: Dict[str, Dict]
) -> Dict:
    """
    Calculate national gas-weighted degree days (GWHDD).

    Args:
        location_data: Dict of location_id -> degree day data

    Returns:
        dict with national gas-weighted metrics
    """
    return calculate_gas_weighted_dd(location_data, 'gas_centers')


def calculate_daily_weighted_aggregates(
    location_data: Dict[str, Dict]
) -> Dict[str, List[float]]:
    """
    Calculate daily gas-weighted HDD/CDD for time series analysis.

    Args:
        location_data: Dict of location_id -> degree day data with daily values

    Returns:
        dict with:
        - 'daily_weighted_hdd': List of daily GWHDD values
        - 'daily_weighted_cdd': List of daily GWCDD values
        - 'cumulative_weighted_hdd': Cumulative GWHDD
        - 'cumulative_weighted_cdd': Cumulative GWCDD
    """
    # Determine number of days from first available location
    num_days = 0
    for location_id, data in location_data.items():
        if location_id in GAS_CONSUMPTION_CENTERS and 'hdd' in data:
            num_days = len(data['hdd'])
            break

    if num_days == 0:
        return {
            'daily_weighted_hdd': [],
            'daily_weighted_cdd': [],
            'cumulative_weighted_hdd': [],
            'cumulative_weighted_cdd': []
        }

    daily_weighted_hdd = []
    daily_weighted_cdd = []
    total_weight = get_total_gas_weight()

    for day_idx in range(num_days):
        day_weighted_hdd = 0.0
        day_weighted_cdd = 0.0

        for location_id, data in location_data.items():
            if location_id not in GAS_CONSUMPTION_CENTERS:
                continue
            if 'hdd' not in data or day_idx >= len(data['hdd']):
                continue

            # Skip None values (from partial/merged data)
            hdd_val = data['hdd'][day_idx]
            cdd_val = data['cdd'][day_idx]
            if hdd_val is None or cdd_val is None:
                continue

            gas_weight = GAS_CONSUMPTION_CENTERS[location_id]['gas_weight']
            day_weighted_hdd += hdd_val * gas_weight
            day_weighted_cdd += cdd_val * gas_weight

        if total_weight > 0:
            daily_weighted_hdd.append(round(day_weighted_hdd / total_weight, 2))
            daily_weighted_cdd.append(round(day_weighted_cdd / total_weight, 2))
        else:
            daily_weighted_hdd.append(0.0)
            daily_weighted_cdd.append(0.0)

    # Calculate cumulative
    cumulative_hdd = []
    cumulative_cdd = []
    running_hdd = 0.0
    running_cdd = 0.0

    for hdd, cdd in zip(daily_weighted_hdd, daily_weighted_cdd):
        running_hdd += hdd
        running_cdd += cdd
        cumulative_hdd.append(round(running_hdd, 1))
        cumulative_cdd.append(round(running_cdd, 1))

    return {
        'daily_weighted_hdd': daily_weighted_hdd,
        'daily_weighted_cdd': daily_weighted_cdd,
        'cumulative_weighted_hdd': cumulative_hdd,
        'cumulative_weighted_cdd': cumulative_cdd
    }


def get_top_contributors(
    location_data: Dict[str, Dict],
    metric: str = 'hdd',
    top_n: int = 10
) -> List[Dict]:
    """
    Get the top N cities contributing to gas-weighted degree days.

    Args:
        location_data: Dict of location_id -> degree day data
        metric: 'hdd' or 'cdd'
        top_n: Number of top contributors to return

    Returns:
        List of dicts with location info and contribution
    """
    contributions = []
    total_weight = get_total_gas_weight()

    for location_id, data in location_data.items():
        if location_id not in GAS_CONSUMPTION_CENTERS:
            continue

        gas_weight = GAS_CONSUMPTION_CENTERS[location_id]['gas_weight']

        # Get total for metric
        key = f'{metric}_cumulative'
        if key in data and data[key]:
            total = data[key][-1]
        elif metric in data and data[metric]:
            total = sum(data[metric])
        else:
            total = 0

        # Calculate weighted contribution
        if total_weight > 0:
            normalized_weight = gas_weight / total_weight
            weighted_contribution = total * normalized_weight
        else:
            normalized_weight = 0
            weighted_contribution = 0

        contributions.append({
            'location_id': location_id,
            'name': GAS_CONSUMPTION_CENTERS[location_id]['name'],
            'region': GAS_CONSUMPTION_CENTERS[location_id]['region'],
            'gas_weight': gas_weight,
            'raw_value': round(total, 1),
            'weight': round(normalized_weight * 100, 1),  # As percentage
            'weighted_contribution': round(weighted_contribution, 2)
        })

    # Sort by weighted contribution descending
    contributions.sort(key=lambda x: x['weighted_contribution'], reverse=True)

    return contributions[:top_n]


def calculate_daily_normal_gwhdd(
    start_date: datetime,
    num_days: int
) -> List[float]:
    """
    Calculate daily gas-weighted normal HDDs based on climate normals.

    Args:
        start_date: First day of the forecast period
        num_days: Number of days to calculate

    Returns:
        List of daily normal GWHDD values
    """
    from src.calculations.climate_deviation import get_climate_normal_for_date

    total_weight = get_total_gas_weight()
    daily_normal_gwhdd = []

    for day_idx in range(num_days):
        date = start_date + timedelta(days=day_idx)
        day_weighted_hdd = 0.0

        for location_id in GAS_CONSUMPTION_CENTERS:
            gas_weight = GAS_CONSUMPTION_CENTERS[location_id]['gas_weight']
            normal_temp = get_climate_normal_for_date(location_id, date)

            if normal_temp is not None:
                hdd = max(0, HDD_BASE - normal_temp)
                day_weighted_hdd += hdd * gas_weight

        if total_weight > 0:
            daily_normal_gwhdd.append(round(day_weighted_hdd / total_weight, 2))
        else:
            daily_normal_gwhdd.append(0.0)

    return daily_normal_gwhdd

# Alias for backward compatibility
def calculate_daily_normal_pwhdd(start_date, num_days):
    """Alias for calculate_daily_normal_gwhdd for backward compatibility."""
    return calculate_daily_normal_gwhdd(start_date, num_days)
