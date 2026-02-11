"""
Calculate deviation from climate normals for weather forecast analysis.

This module provides functions to compare forecasted temperatures and degree days
against 30-year climate normals, which is key for identifying market-moving weather.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import calendar

from src.config import CLIMATE_NORMALS, HDD_BASE, CDD_BASE, GAS_CONSUMPTION_CENTERS, get_total_gas_weight

# Alias for backward compatibility
POPULATION_CENTERS = GAS_CONSUMPTION_CENTERS


# Month name to number mapping
MONTH_NAMES = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
               'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


def get_climate_normal_for_date(
    location_id: str,
    date: datetime
) -> Optional[float]:
    """
    Get the expected normal temperature for a location on a given date.
    Interpolates between monthly normals for smooth daily values.

    Args:
        location_id: The location identifier (e.g., 'new_york', 'chicago')
        date: The date to get the normal for

    Returns:
        Normal temperature in °F, or None if location not found
    """
    if location_id not in CLIMATE_NORMALS:
        return None

    normals = CLIMATE_NORMALS[location_id]

    # Get current month and next month
    current_month_idx = date.month - 1  # 0-indexed
    next_month_idx = (current_month_idx + 1) % 12

    current_month = MONTH_NAMES[current_month_idx]
    next_month = MONTH_NAMES[next_month_idx]

    # Get day of month and days in current month
    day = date.day
    days_in_month = calendar.monthrange(date.year, date.month)[1]

    # Linear interpolation between monthly normals
    # At day 15 (middle of month), use current month's normal
    # Interpolate toward next/prev month at beginning/end
    current_temp = normals[current_month]
    next_temp = normals[next_month]

    # Progress through month (0.0 at start, 1.0 at end)
    progress = (day - 1) / (days_in_month - 1) if days_in_month > 1 else 0.5

    # Weight shifts from current to next month as we progress
    # At day 1: ~25% next month influence
    # At day 15: ~50% each
    # At day 30: ~75% next month influence
    weight_next = progress * 0.5 + 0.25
    weight_current = 1 - weight_next

    interpolated = current_temp * weight_current + next_temp * weight_next

    return round(interpolated, 1)


def get_normal_temps_for_period(
    location_id: str,
    start_date: datetime,
    num_days: int
) -> List[float]:
    """
    Get normal temperatures for a range of dates.

    Args:
        location_id: The location identifier
        start_date: First day of the period
        num_days: Number of days to get normals for

    Returns:
        List of normal temperatures (°F) for each day
    """
    normals = []
    for i in range(num_days):
        date = start_date + timedelta(days=i)
        temp = get_climate_normal_for_date(location_id, date)
        normals.append(temp if temp is not None else 65.0)  # Default to base temp
    return normals


def calculate_expected_degree_days(
    location_id: str,
    start_date: datetime,
    num_days: int
) -> Dict[str, float]:
    """
    Calculate expected HDD/CDD based on climate normals.

    Args:
        location_id: The location identifier
        start_date: First day of the forecast period
        num_days: Number of days in the period

    Returns:
        dict with 'expected_hdd', 'expected_cdd', 'normal_temps'
    """
    normal_temps = get_normal_temps_for_period(location_id, start_date, num_days)

    expected_hdd = 0.0
    expected_cdd = 0.0

    for temp in normal_temps:
        expected_hdd += max(0, HDD_BASE - temp)
        expected_cdd += max(0, temp - CDD_BASE)

    return {
        'expected_hdd': round(expected_hdd, 1),
        'expected_cdd': round(expected_cdd, 1),
        'normal_temps': normal_temps
    }


def calculate_forecast_vs_normal(
    location_id: str,
    forecast_temps: List[float],
    forecast_start_date: datetime
) -> Dict:
    """
    Compare forecast temperatures to climate normals.

    Args:
        location_id: The location identifier
        forecast_temps: List of forecasted daily average temperatures (°F)
        forecast_start_date: Start date of the forecast

    Returns:
        dict with:
        - 'daily_temp_deviation': List of (forecast - normal) for each day
        - 'avg_temp_deviation': Mean temperature deviation
        - 'forecast_hdd': Actual HDD from forecast
        - 'forecast_cdd': Actual CDD from forecast
        - 'expected_hdd': Expected HDD from normals
        - 'expected_cdd': Expected CDD from normals
        - 'hdd_deviation': forecast_hdd - expected_hdd (positive = colder than normal)
        - 'cdd_deviation': forecast_cdd - expected_cdd (positive = warmer than normal)
        - 'direction': 'warmer', 'colder', or 'near_normal'
    """
    num_days = len(forecast_temps)
    normal_temps = get_normal_temps_for_period(location_id, forecast_start_date, num_days)

    # Calculate daily deviations
    daily_temp_deviation = []
    for forecast, normal in zip(forecast_temps, normal_temps):
        daily_temp_deviation.append(round(forecast - normal, 1))

    # Calculate degree days
    forecast_hdd = sum(max(0, HDD_BASE - t) for t in forecast_temps)
    forecast_cdd = sum(max(0, t - CDD_BASE) for t in forecast_temps)
    expected_hdd = sum(max(0, HDD_BASE - t) for t in normal_temps)
    expected_cdd = sum(max(0, t - CDD_BASE) for t in normal_temps)

    # Calculate deviations
    hdd_deviation = forecast_hdd - expected_hdd  # Positive = more HDDs = colder
    cdd_deviation = forecast_cdd - expected_cdd  # Positive = more CDDs = warmer
    avg_temp_deviation = sum(daily_temp_deviation) / len(daily_temp_deviation) if daily_temp_deviation else 0

    # Determine overall direction
    if avg_temp_deviation > 2:
        direction = 'warmer'
    elif avg_temp_deviation < -2:
        direction = 'colder'
    else:
        direction = 'near_normal'

    return {
        'normal_temps': normal_temps,
        'daily_temp_deviation': daily_temp_deviation,
        'avg_temp_deviation': round(avg_temp_deviation, 1),
        'forecast_hdd': round(forecast_hdd, 1),
        'forecast_cdd': round(forecast_cdd, 1),
        'expected_hdd': round(expected_hdd, 1),
        'expected_cdd': round(expected_cdd, 1),
        'hdd_deviation': round(hdd_deviation, 1),
        'cdd_deviation': round(cdd_deviation, 1),
        'direction': direction
    }


def calculate_all_locations_vs_normal(
    location_data: Dict[str, Dict],
    forecast_start_date: datetime
) -> Dict[str, Dict]:
    """
    Calculate vs-normal metrics for all locations.

    Args:
        location_data: Dict of location_id -> {'daily_temps': [...], ...}
        forecast_start_date: Start date of the forecast

    Returns:
        Dict of location_id -> vs_normal metrics
    """
    results = {}

    for location_id, data in location_data.items():
        if 'daily_temps' not in data or location_id not in CLIMATE_NORMALS:
            continue

        results[location_id] = calculate_forecast_vs_normal(
            location_id,
            data['daily_temps'],
            forecast_start_date
        )

    return results


def calculate_national_vs_normal(
    location_data: Dict[str, Dict],
    forecast_start_date: datetime
) -> Dict:
    """
    Calculate gas-weighted national deviation from normal.

    Args:
        location_data: Dict of location_id -> {'daily_temps': [...], ...}
        forecast_start_date: Start date of the forecast

    Returns:
        dict with national gas-weighted deviation metrics
    """
    total_weight = 0.0
    weighted_temp_deviation = 0.0
    weighted_hdd_deviation = 0.0
    weighted_cdd_deviation = 0.0

    for location_id, data in location_data.items():
        if location_id not in GAS_CONSUMPTION_CENTERS:
            continue
        if 'daily_temps' not in data or location_id not in CLIMATE_NORMALS:
            continue

        gas_weight = GAS_CONSUMPTION_CENTERS[location_id]['gas_weight']
        vs_normal = calculate_forecast_vs_normal(
            location_id,
            data['daily_temps'],
            forecast_start_date
        )

        weighted_temp_deviation += vs_normal['avg_temp_deviation'] * gas_weight
        weighted_hdd_deviation += vs_normal['hdd_deviation'] * gas_weight
        weighted_cdd_deviation += vs_normal['cdd_deviation'] * gas_weight
        total_weight += gas_weight

    if total_weight > 0:
        avg_temp_deviation = weighted_temp_deviation / total_weight
        avg_hdd_deviation = weighted_hdd_deviation / total_weight
        avg_cdd_deviation = weighted_cdd_deviation / total_weight
    else:
        avg_temp_deviation = 0.0
        avg_hdd_deviation = 0.0
        avg_cdd_deviation = 0.0

    # Determine overall direction
    if avg_temp_deviation > 2:
        direction = 'warmer'
    elif avg_temp_deviation < -2:
        direction = 'colder'
    else:
        direction = 'near_normal'

    return {
        'avg_temp_deviation': round(avg_temp_deviation, 1),
        'hdd_deviation': round(avg_hdd_deviation, 1),
        'cdd_deviation': round(avg_cdd_deviation, 1),
        'direction': direction,
        'total_weight': round(total_weight, 3)
    }


def get_deviation_signal(
    hdd_deviation: float,
    cdd_deviation: float,
    season: str = 'winter'
) -> Dict:
    """
    Interpret degree day deviations as a trading signal.

    Args:
        hdd_deviation: HDD deviation from normal (positive = colder)
        cdd_deviation: CDD deviation from normal (positive = warmer)
        season: 'winter' or 'summer' to determine which metric matters more

    Returns:
        dict with signal interpretation
    """
    if season == 'winter':
        # In winter, HDD matters more
        primary_deviation = hdd_deviation
        if hdd_deviation > 10:
            signal = 'bullish'
            strength = 'strong' if hdd_deviation > 20 else 'moderate'
            reason = f"{hdd_deviation:.0f} HDDs above normal"
        elif hdd_deviation < -10:
            signal = 'bearish'
            strength = 'strong' if hdd_deviation < -20 else 'moderate'
            reason = f"{abs(hdd_deviation):.0f} HDDs below normal"
        else:
            signal = 'neutral'
            strength = 'weak'
            reason = "Near normal heating demand"
    else:
        # In summer, CDD matters more (power burn for A/C)
        primary_deviation = cdd_deviation
        if cdd_deviation > 10:
            signal = 'bullish'
            strength = 'strong' if cdd_deviation > 20 else 'moderate'
            reason = f"{cdd_deviation:.0f} CDDs above normal"
        elif cdd_deviation < -10:
            signal = 'bearish'
            strength = 'strong' if cdd_deviation < -20 else 'moderate'
            reason = f"{abs(cdd_deviation):.0f} CDDs below normal"
        else:
            signal = 'neutral'
            strength = 'weak'
            reason = "Near normal cooling demand"

    return {
        'signal': signal,
        'strength': strength,
        'reason': reason,
        'primary_deviation': round(primary_deviation, 1),
        'season': season
    }


def get_current_season(date: datetime) -> str:
    """
    Determine if we're in heating season (winter) or cooling season (summer).

    Args:
        date: The date to check

    Returns:
        'winter' (Nov-Mar) or 'summer' (Jun-Aug) or 'shoulder' (Apr-May, Sep-Oct)
    """
    month = date.month
    if month in [11, 12, 1, 2, 3]:
        return 'winter'
    elif month in [6, 7, 8]:
        return 'summer'
    else:
        return 'shoulder'
