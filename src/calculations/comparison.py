"""Compare model runs to identify forecast changes"""

import pandas as pd
from typing import Dict, Optional
from src.calculations.degree_days import get_total_degree_days


def compare_runs(latest_data: Dict[str, Dict],
                previous_data: Optional[Dict[str, Dict]] = None) -> Dict[str, Dict]:
    """
    Compare latest model run to previous run.

    Args:
        latest_data: Latest run results from calculate_all_hubs_degree_days()
        previous_data: Previous run results (None if no previous run available)

    Returns:
        dict: Comparison results for each hub with structure:
            {
                'hub_id': {
                    'latest_hdd': float,
                    'latest_cdd': float,
                    'previous_hdd': float,
                    'previous_cdd': float,
                    'hdd_change': float,
                    'cdd_change': float,
                    'hdd_pct_change': float,
                    'cdd_pct_change': float
                }
            }
    """
    comparison = {}

    for hub_id, latest_hub_data in latest_data.items():
        latest_hdd, latest_cdd = get_total_degree_days(latest_hub_data)

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

        if previous_data and hub_id in previous_data:
            prev_hdd, prev_cdd = get_total_degree_days(previous_data[hub_id])

            result['previous_hdd'] = prev_hdd
            result['previous_cdd'] = prev_cdd
            result['hdd_change'] = latest_hdd - prev_hdd
            result['cdd_change'] = latest_cdd - prev_cdd

            # Calculate percentage change (avoid division by zero)
            if prev_hdd > 0:
                result['hdd_pct_change'] = (result['hdd_change'] / prev_hdd) * 100
            if prev_cdd > 0:
                result['cdd_pct_change'] = (result['cdd_change'] / prev_cdd) * 100

        comparison[hub_id] = result

    return comparison


def create_comparison_dataframe(comparison: Dict[str, Dict]) -> pd.DataFrame:
    """
    Create a DataFrame showing comparison between runs.

    Args:
        comparison: Results from compare_runs()

    Returns:
        pd.DataFrame: Comparison summary
    """
    from src.config import HUBS

    rows = []

    for hub_id, comp_data in comparison.items():
        row = {
            'Hub': HUBS[hub_id]['name'],
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
                        hub_id: str) -> pd.DataFrame:
    """
    Get day-by-day comparison for a specific hub.

    Args:
        latest_data: Latest run results
        previous_data: Previous run results
        hub_id: Hub identifier

    Returns:
        pd.DataFrame: Daily comparison with temps, HDD, CDD
    """
    latest = latest_data[hub_id]

    df = pd.DataFrame({
        'Day': range(1, len(latest['daily_temps']) + 1),
        'Latest Temp': [round(t, 1) for t in latest['daily_temps']],
        'Latest HDD': [round(h, 1) for h in latest['hdd']],
        'Latest CDD': [round(c, 1) for c in latest['cdd']]
    })

    if previous_data and hub_id in previous_data:
        previous = previous_data[hub_id]

        df['Previous Temp'] = [round(t, 1) for t in previous['daily_temps']]
        df['Previous HDD'] = [round(h, 1) for h in previous['hdd']]
        df['Previous CDD'] = [round(c, 1) for c in previous['cdd']]
        df['Temp Change'] = df['Latest Temp'] - df['Previous Temp']
        df['HDD Change'] = df['Latest HDD'] - df['Previous HDD']
        df['CDD Change'] = df['Latest CDD'] - df['Previous CDD']

    return df
