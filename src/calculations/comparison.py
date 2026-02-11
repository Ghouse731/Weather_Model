"""Compare model runs to identify forecast changes"""

import pandas as pd
from typing import Dict, List, Optional, Tuple
from src.calculations.degree_days import get_total_degree_days
from src.config import GAS_CONSUMPTION_CENTERS, REGIONS, get_all_locations

# Alias for backward compatibility
POPULATION_CENTERS = GAS_CONSUMPTION_CENTERS


def compare_runs(latest_data: Dict[str, Dict],
                previous_data: Optional[Dict[str, Dict]] = None) -> Dict[str, Dict]:
    """
    Compare latest model run to previous run.
    (Original function - kept for backward compatibility)

    Args:
        latest_data: Latest run results from calculate_all_hubs_degree_days()
        previous_data: Previous run results (None if no previous run available)

    Returns:
        dict: Comparison results for each hub/location
    """
    comparison = {}

    for loc_id, latest_loc_data in latest_data.items():
        latest_hdd, latest_cdd = get_total_degree_days(latest_loc_data)

        result = {
            'latest_hdd': latest_hdd,
            'latest_cdd': latest_cdd,
            'previous_hdd': None,
            'previous_cdd': None,
            'hdd_change': None,
            'cdd_change': None,
            'hdd_pct_change': None,
            'cdd_pct_change': None
        }

        if previous_data and loc_id in previous_data:
            prev_hdd, prev_cdd = get_total_degree_days(previous_data[loc_id])

            result['previous_hdd'] = prev_hdd
            result['previous_cdd'] = prev_cdd
            result['hdd_change'] = latest_hdd - prev_hdd
            result['cdd_change'] = latest_cdd - prev_cdd

            # Calculate percentage change (avoid division by zero)
            if prev_hdd > 0:
                result['hdd_pct_change'] = (result['hdd_change'] / prev_hdd) * 100
            if prev_cdd > 0:
                result['cdd_pct_change'] = (result['cdd_change'] / prev_cdd) * 100

        comparison[loc_id] = result

    return comparison


def compare_runs_enhanced(
    latest_data: Dict[str, Dict],
    previous_data: Optional[Dict[str, Dict]] = None
) -> Dict:
    """
    Enhanced comparison with regional and national aggregates.

    Args:
        latest_data: Latest run results (all locations)
        previous_data: Previous run results

    Returns:
        dict: {
            'locations': per-location comparisons,
            'regions': per-region weighted comparisons,
            'national': national weighted comparison,
            'summary': high-level delta summary
        }
    """
    # Per-location comparisons (existing logic)
    location_comparison = compare_runs(latest_data, previous_data)

    # Regional aggregates
    regional_comparison = compare_regional_aggregates(latest_data, previous_data)

    # National aggregate
    national_comparison = compare_national_aggregate(latest_data, previous_data)

    # Delta summary
    delta_summary = create_delta_summary(
        location_comparison,
        regional_comparison,
        national_comparison
    )

    return {
        'locations': location_comparison,
        'regions': regional_comparison,
        'national': national_comparison,
        'summary': delta_summary
    }


def compare_regional_aggregates(
    latest_data: Dict[str, Dict],
    previous_data: Optional[Dict[str, Dict]] = None
) -> Dict[str, Dict]:
    """
    Compare gas-weighted regional aggregates.

    Args:
        latest_data: Latest run results
        previous_data: Previous run results

    Returns:
        dict: region_id -> comparison results
    """
    from src.calculations.weighted_aggregates import calculate_regional_aggregates

    latest_regional = calculate_regional_aggregates(latest_data)

    if previous_data:
        previous_regional = calculate_regional_aggregates(previous_data)
    else:
        previous_regional = None

    results = {}

    for region_id, latest in latest_regional.items():
        result = {
            'name': latest['name'],
            'latest_hdd': latest['weighted_hdd'],
            'latest_cdd': latest['weighted_cdd'],
            'gas_weight': latest['total_weight'],
            'previous_hdd': None,
            'previous_cdd': None,
            'hdd_change': None,
            'cdd_change': None
        }

        if previous_regional and region_id in previous_regional:
            prev = previous_regional[region_id]
            result['previous_hdd'] = prev['weighted_hdd']
            result['previous_cdd'] = prev['weighted_cdd']
            result['hdd_change'] = round(latest['weighted_hdd'] - prev['weighted_hdd'], 1)
            result['cdd_change'] = round(latest['weighted_cdd'] - prev['weighted_cdd'], 1)

        results[region_id] = result

    return results


def compare_national_aggregate(
    latest_data: Dict[str, Dict],
    previous_data: Optional[Dict[str, Dict]] = None
) -> Dict:
    """
    Compare gas-weighted national aggregate.

    Args:
        latest_data: Latest run results
        previous_data: Previous run results

    Returns:
        dict: National comparison results
    """
    from src.calculations.weighted_aggregates import calculate_national_aggregate

    latest_national = calculate_national_aggregate(latest_data)

    result = {
        'latest_hdd': latest_national['weighted_hdd'],
        'latest_cdd': latest_national['weighted_cdd'],
        'gas_weight': latest_national['total_weight'],
        'previous_hdd': None,
        'previous_cdd': None,
        'hdd_change': None,
        'cdd_change': None,
        'hdd_pct_change': None,
        'cdd_pct_change': None
    }

    if previous_data:
        previous_national = calculate_national_aggregate(previous_data)
        result['previous_hdd'] = previous_national['weighted_hdd']
        result['previous_cdd'] = previous_national['weighted_cdd']
        result['hdd_change'] = round(latest_national['weighted_hdd'] - previous_national['weighted_hdd'], 1)
        result['cdd_change'] = round(latest_national['weighted_cdd'] - previous_national['weighted_cdd'], 1)

        if previous_national['weighted_hdd'] > 0:
            result['hdd_pct_change'] = round(
                (result['hdd_change'] / previous_national['weighted_hdd']) * 100, 1
            )
        if previous_national['weighted_cdd'] > 0:
            result['cdd_pct_change'] = round(
                (result['cdd_change'] / previous_national['weighted_cdd']) * 100, 1
            )

    return result


def create_delta_summary(
    location_comparison: Dict[str, Dict],
    regional_comparison: Dict[str, Dict],
    national_comparison: Dict
) -> Dict:
    """
    Create a clear summary of run-over-run changes.

    Returns:
        dict: {
            'direction': 'warmer' | 'colder' | 'mixed' | 'unchanged',
            'national_hdd_change': float,
            'national_cdd_change': float,
            'narrative': str,
            'regional_changes': dict,
            'notable_changes': list of top 3 city changes
        }
    """
    hdd_change = national_comparison.get('hdd_change')
    cdd_change = national_comparison.get('cdd_change')

    # Determine overall direction
    if hdd_change is None:
        direction = 'no_comparison'
        narrative = "No previous run available for comparison."
    elif hdd_change > 5:
        direction = 'colder'
        narrative = f"Forecast shifted COLDER: +{hdd_change:.1f} weighted HDDs nationally"
    elif hdd_change < -5:
        direction = 'warmer'
        narrative = f"Forecast shifted WARMER: {hdd_change:.1f} weighted HDDs nationally"
    elif cdd_change and cdd_change > 5:
        direction = 'warmer'
        narrative = f"Forecast shifted WARMER: +{cdd_change:.1f} weighted CDDs nationally"
    elif cdd_change and cdd_change < -5:
        direction = 'colder'
        narrative = f"Forecast shifted COLDER: {cdd_change:.1f} weighted CDDs nationally"
    else:
        direction = 'unchanged'
        narrative = "Forecast largely unchanged from previous run."

    # Regional changes summary
    regional_changes = {}
    for region_id, data in regional_comparison.items():
        if data['hdd_change'] is not None:
            regional_changes[region_id] = {
                'name': data['name'],
                'hdd_change': data['hdd_change'],
                'cdd_change': data['cdd_change'],
                'direction': 'colder' if data['hdd_change'] > 2 else ('warmer' if data['hdd_change'] < -2 else 'unchanged')
            }

    # Notable city changes (top 3 by absolute HDD change)
    notable_changes = get_notable_changes(location_comparison, top_n=3)

    return {
        'direction': direction,
        'national_hdd_change': hdd_change,
        'national_cdd_change': cdd_change,
        'narrative': narrative,
        'regional_changes': regional_changes,
        'notable_changes': notable_changes
    }


def get_notable_changes(
    location_comparison: Dict[str, Dict],
    top_n: int = 3
) -> List[Dict]:
    """
    Get the most significant city changes.

    Args:
        location_comparison: Per-location comparison data
        top_n: Number of notable changes to return

    Returns:
        List of notable changes sorted by absolute HDD change
    """
    changes = []
    all_locations = get_all_locations()

    for loc_id, data in location_comparison.items():
        # Only include population centers
        if loc_id not in POPULATION_CENTERS:
            continue

        hdd_change = data.get('hdd_change')
        if hdd_change is None:
            continue

        changes.append({
            'location_id': loc_id,
            'name': all_locations[loc_id]['name'],
            'region': POPULATION_CENTERS[loc_id]['region'],
            'hdd_change': round(hdd_change, 1),
            'cdd_change': round(data.get('cdd_change', 0), 1),
            'direction': 'colder' if hdd_change > 0 else 'warmer'
        })

    # Sort by absolute HDD change
    changes.sort(key=lambda x: abs(x['hdd_change']), reverse=True)

    return changes[:top_n]


def create_comparison_dataframe(comparison: Dict[str, Dict],
                                 location_type: str = 'population_centers') -> pd.DataFrame:
    """
    Create a DataFrame showing comparison between runs.

    Args:
        comparison: Results from compare_runs()
        location_type: 'population_centers' or 'all'

    Returns:
        pd.DataFrame: Comparison summary
    """
    if location_type == 'population_centers':
        locations = POPULATION_CENTERS
    else:
        locations = get_all_locations()

    rows = []

    for loc_id, comp_data in comparison.items():
        if loc_id not in locations:
            continue

        row = {
            'Location': locations[loc_id]['name'],
            'Latest HDD': round(comp_data['latest_hdd'], 1),
            'Latest CDD': round(comp_data['latest_cdd'], 1)
        }

        if comp_data['previous_hdd'] is not None:
            row['Previous HDD'] = round(comp_data['previous_hdd'], 1)
            row['Previous CDD'] = round(comp_data['previous_cdd'], 1)
            row['HDD Change'] = round(comp_data['hdd_change'], 1)
            row['CDD Change'] = round(comp_data['cdd_change'], 1)

            # Add percentage change if applicable
            if comp_data['hdd_pct_change'] is not None:
                row['HDD % Change'] = round(comp_data['hdd_pct_change'], 1)
            if comp_data['cdd_pct_change'] is not None:
                row['CDD % Change'] = round(comp_data['cdd_pct_change'], 1)
        else:
            row['Previous HDD'] = 'N/A'
            row['Previous CDD'] = 'N/A'
            row['HDD Change'] = 'N/A'
            row['CDD Change'] = 'N/A'

        rows.append(row)

    return pd.DataFrame(rows)


def get_daily_comparison(latest_data: Dict[str, Dict],
                        previous_data: Optional[Dict[str, Dict]],
                        location_id: str) -> pd.DataFrame:
    """
    Get day-by-day comparison for a specific location.

    Args:
        latest_data: Latest run results
        previous_data: Previous run results
        location_id: Location identifier (hub or city)

    Returns:
        pd.DataFrame: Daily comparison with temps, HDD, CDD
    """
    latest = latest_data[location_id]

    df = pd.DataFrame({
        'Day': range(1, len(latest['daily_temps']) + 1),
        'Latest Temp': [round(t, 1) for t in latest['daily_temps']],
        'Latest HDD': [round(h, 1) for h in latest['hdd']],
        'Latest CDD': [round(c, 1) for c in latest['cdd']]
    })

    if previous_data and location_id in previous_data:
        previous = previous_data[location_id]

        # Align to minimum length when comparing runs with different forecast horizons
        num_days = min(len(latest['daily_temps']), len(previous['daily_temps']))
        df = df.head(num_days).copy()

        df['Previous Temp'] = [round(t, 1) for t in previous['daily_temps'][:num_days]]
        df['Previous HDD'] = [round(h, 1) for h in previous['hdd'][:num_days]]
        df['Previous CDD'] = [round(c, 1) for c in previous['cdd'][:num_days]]
        df['Temp Change'] = df['Latest Temp'] - df['Previous Temp']
        df['HDD Change'] = df['Latest HDD'] - df['Previous HDD']
        df['CDD Change'] = df['Latest CDD'] - df['Previous CDD']

    return df


def get_daily_delta_summary(
    latest_data: Dict[str, Dict],
    previous_data: Dict[str, Dict]
) -> pd.DataFrame:
    """
    Create day-by-day national weighted delta summary.
    Shows which days are driving the run-over-run change.

    Args:
        latest_data: Latest run results
        previous_data: Previous run results

    Returns:
        pd.DataFrame with day-by-day weighted delta
    """
    from src.calculations.weighted_aggregates import calculate_daily_weighted_aggregates

    latest_daily = calculate_daily_weighted_aggregates(latest_data)
    previous_daily = calculate_daily_weighted_aggregates(previous_data)

    if not latest_daily['daily_weighted_hdd'] or not previous_daily['daily_weighted_hdd']:
        return pd.DataFrame()

    num_days = min(len(latest_daily['daily_weighted_hdd']),
                   len(previous_daily['daily_weighted_hdd']))

    rows = []
    for i in range(num_days):
        rows.append({
            'Day': i + 1,
            'Latest HDD': latest_daily['daily_weighted_hdd'][i],
            'Previous HDD': previous_daily['daily_weighted_hdd'][i],
            'HDD Change': round(latest_daily['daily_weighted_hdd'][i] - previous_daily['daily_weighted_hdd'][i], 2),
            'Latest CDD': latest_daily['daily_weighted_cdd'][i],
            'Previous CDD': previous_daily['daily_weighted_cdd'][i],
            'CDD Change': round(latest_daily['daily_weighted_cdd'][i] - previous_daily['daily_weighted_cdd'][i], 2)
        })

    return pd.DataFrame(rows)
