"""Streamlit app for GFS Weather Model Analysis"""

import time
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import pandas as pd

from src.data.gfs_fetcher import (
    fetch_gfs_temperature, get_latest_gfs_run, get_newest_possible_run,
    fetch_gfs_partial, is_in_publishing_window, FetchResult, get_previous_gfs_run
)
from src.data.storage import (
    save_model_run, get_previous_run_data, get_latest_saved_run,
    save_partial_run, load_partial_run, delete_partial_run, promote_partial_to_complete,
    load_model_run, get_city_data
)
from src.calculations.point_extraction import extract_all_temperatures
from src.calculations.degree_days import calculate_all_hubs_degree_days
from src.calculations.comparison import (
    compare_runs, create_comparison_dataframe, get_daily_comparison,
    compare_runs_enhanced
)
from src.calculations.weighted_aggregates import (
    calculate_national_aggregate, calculate_regional_aggregates,
    calculate_daily_weighted_aggregates, calculate_daily_normal_gwhdd
)
from src.calculations.climate_deviation import (
    calculate_national_vs_normal, get_current_season, get_deviation_signal
)
from src.config import FORECAST_DAYS, GAS_CONSUMPTION_CENTERS, REGIONS, CLIMATE_NORMALS

# Alias for backward compatibility in display code
POPULATION_CENTERS = GAS_CONSUMPTION_CENTERS

# Try to import autorefresh, but make it optional
try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:
    AUTOREFRESH_AVAILABLE = False
    st_autorefresh = None  # type: ignore


# Page configuration
st.set_page_config(
    page_title="GFS Weather Model - Natural Gas Demand Signal",
    page_icon="🌡️",
    layout="wide"
)

# Professional styling - compatible with light/dark themes
st.markdown("""
<style>
    /* Main container styling */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 8px;
        padding: 1rem;
    }

    /* Status indicators - with explicit dark text */
    .status-live {
        background-color: #dcfce7;
        border-left: 4px solid #22c55e;
        padding: 0.75rem 1rem;
        border-radius: 0 4px 4px 0;
        margin: 0.5rem 0;
        color: #166534;
    }

    .status-live strong {
        color: #166534;
    }

    .status-idle {
        background-color: #e2e8f0;
        border-left: 4px solid #64748b;
        padding: 0.75rem 1rem;
        border-radius: 0 4px 4px 0;
        margin: 0.5rem 0;
        color: #334155;
    }

    .status-idle strong {
        color: #334155;
    }

    .status-complete {
        background-color: #dbeafe;
        border-left: 4px solid #3b82f6;
        padding: 0.75rem 1rem;
        border-radius: 0 4px 4px 0;
        margin: 0.5rem 0;
        color: #1e40af;
    }

    .status-complete strong {
        color: #1e40af;
    }

    /* National summary card */
    .national-summary {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
        border-radius: 12px;
        padding: 1.5rem;
        color: white;
        margin-bottom: 1rem;
    }

    .national-summary h2 {
        color: white;
        margin-bottom: 0.5rem;
    }

    /* Regional cards */
    .regional-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.5rem;
    }

    .regional-card.colder {
        border-left: 4px solid #3b82f6;
    }

    .regional-card.warmer {
        border-left: 4px solid #ef4444;
    }

    .regional-card.unchanged {
        border-left: 4px solid #9ca3af;
    }

    /* Delta summary */
    .delta-colder {
        background-color: #dbeafe;
        border: 1px solid #3b82f6;
        border-radius: 8px;
        padding: 1rem;
        color: #1e40af;
    }

    .delta-warmer {
        background-color: #fee2e2;
        border: 1px solid #ef4444;
        border-radius: 8px;
        padding: 1rem;
        color: #991b1b;
    }

    .delta-unchanged {
        background-color: #f3f4f6;
        border: 1px solid #9ca3af;
        border-radius: 8px;
        padding: 1rem;
        color: #374151;
    }

    /* Data tables */
    [data-testid="stDataFrame"] {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 8px;
    }

    /* Buttons */
    .stButton > button {
        background-color: #3b82f6;
        color: white !important;
        border: none;
        border-radius: 6px;
        font-weight: 500;
        transition: background-color 0.2s;
    }

    .stButton > button:hover {
        background-color: #2563eb;
        color: white !important;
    }

    /* Progress bar */
    .stProgress > div > div {
        background-color: #3b82f6;
    }

    /* Info/Warning/Success boxes */
    [data-testid="stAlert"] {
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# Auto-refresh intervals
AUTO_REFRESH_PUBLISHING_MS = 1 * 60 * 1000  # 1 minute during publishing window (fetch guard prevents concurrent)
AUTO_REFRESH_IDLE_MS = 5 * 60 * 1000  # 5 minutes when idle OR when fetch complete (to detect new windows)


def format_zulu(dt: datetime) -> str:
    """Format datetime in Zulu notation (e.g., '1/29/26 18z')"""
    return f"{dt.month}/{dt.day}/{dt.strftime('%y')} {dt.hour:02d}z"


@st.cache_data(ttl=3600)
def fetch_and_process_gfs_data(run_time_str: str):
    """
    Fetch GFS data and process it. Cached for 1 hour.

    Args:
        run_time_str: Run time as ISO string (for cache key)

    Returns:
        tuple: (actual_run_time, city_data)
    """
    print(f"DEBUG fetch_and_process_gfs_data: Starting for {run_time_str}", flush=True)
    run_time = datetime.fromisoformat(run_time_str)

    try:
        with st.spinner('Fetching GFS data from NOMADS/AWS...'):
            gfs_data = fetch_gfs_temperature(run_time, forecast_hours=FORECAST_DAYS * 24)

        print(f"DEBUG: GFS data fetched, checking attributes...", flush=True)
        # Get the ACTUAL run time from fetched data (may differ if fallback occurred)
        actual_run_time = datetime.fromisoformat(gfs_data.attrs['run_time'])
        print(f"DEBUG: Actual run time = {actual_run_time}", flush=True)

        print(f"DEBUG: Starting temperature extraction...", flush=True)
        with st.spinner('Extracting temperatures for population centers...'):
            city_temps = extract_all_temperatures(gfs_data)
        print(f"DEBUG: Extracted temps for {len(city_temps)} cities", flush=True)

        print(f"DEBUG: Calculating degree days...", flush=True)
        with st.spinner('Calculating degree days...'):
            city_data = calculate_all_hubs_degree_days(city_temps)
        print(f"DEBUG: Calculated degree days for {len(city_data)} cities", flush=True)

        # Save to disk using ACTUAL run time (not requested time)
        print(f"DEBUG: Attempting to save model run...", flush=True)
        save_model_run(actual_run_time, city_data)
        print(f"DEBUG: Save complete!", flush=True)

        return actual_run_time, city_data
    except Exception as e:
        print(f"ERROR in fetch_and_process_gfs_data: {type(e).__name__}: {e}", flush=True)
        raise


def fetch_and_process_partial(run_time: datetime) -> tuple:
    """
    Fetch whatever GFS data is available and process it (partial allowed).
    Supports resuming from previously fetched hours to avoid re-fetching.

    Args:
        run_time: GFS run timestamp

    Returns:
        tuple: (FetchResult, city_data or None)
    """
    print(f"DEBUG fetch_and_process_partial: Starting for {run_time}", flush=True)

    # Check for existing partial data to resume from
    run_key = run_time.isoformat()
    existing_data = None
    start_hour = 0

    # Check session state for raw xarray data from this run
    partial_data_key = f'partial_xarray_{run_key}'
    if partial_data_key in st.session_state:
        existing_data = st.session_state[partial_data_key]
        # Verify the data structure is intact
        print(f"DEBUG: Retrieved existing_data from session state", flush=True)
        print(f"DEBUG: existing_data type: {type(existing_data)}", flush=True)
        if hasattr(existing_data, 'dims'):
            print(f"DEBUG: existing_data dims: {dict(existing_data.dims)}", flush=True)
        else:
            print(f"WARNING: existing_data has no dims attribute - may be corrupted!", flush=True)
            existing_data = None  # Force fresh fetch if data is corrupted

        if existing_data is not None:
            # Get last fetched hour from the data attributes
            last_fetched_hour = existing_data.attrs.get('last_fetched_hour', 0)

            # Validate last_fetched_hour against actual time dimension
            actual_time_points = existing_data.dims.get('time', 0)
            expected_last_hour = (actual_time_points - 1) * 6 if actual_time_points > 0 else 0

            if last_fetched_hour > expected_last_hour + 6:
                # Attr is corrupted (inflated) - recalculate from actual data
                print(f"WARNING: last_fetched_hour={last_fetched_hour} inconsistent with {actual_time_points} time points (expected ~{expected_last_hour})", flush=True)
                print(f"DEBUG: Correcting last_fetched_hour to {expected_last_hour}", flush=True)
                last_fetched_hour = expected_last_hour
                existing_data.attrs['last_fetched_hour'] = last_fetched_hour

            if last_fetched_hour > 0:
                # Move to next hour (6-hour intervals)
                start_hour = last_fetched_hour + 6
            else:
                start_hour = 0
            print(f"DEBUG: Resuming from hour {start_hour} (last_fetched={last_fetched_hour}, time_points={actual_time_points})", flush=True)
    else:
        print(f"DEBUG: Starting fresh fetch", flush=True)

    try:
        result = fetch_gfs_partial(
            run_time,
            forecast_hours=FORECAST_DAYS * 24,
            start_hour=start_hour,
            existing_data=existing_data
        )
        print(f"DEBUG: fetch_gfs_partial returned: hours={result.hours_fetched}, complete={result.is_complete}", flush=True)

        if result.data is None or result.hours_fetched == 0:
            print(f"DEBUG: No data returned from fetch_gfs_partial", flush=True)
            return result, None

        # Store raw xarray data in session state for resume capability
        st.session_state[partial_data_key] = result.data

        # Process available data for population centers
        print(f"DEBUG: Extracting temperatures...", flush=True)
        city_temps = extract_all_temperatures(result.data)
        print(f"DEBUG: Extracted {len(city_temps)} cities", flush=True)

        print(f"DEBUG: Calculating degree days...", flush=True)
        city_data = calculate_all_hubs_degree_days(city_temps)
        print(f"DEBUG: Calculated degree days for {len(city_data)} cities", flush=True)

        # Get last fetched hour from result data
        last_fetched_hour = result.data.attrs.get('last_fetched_hour', 0)

        # Verify actual days in processed data (may differ from FetchResult estimate)
        actual_days = len(next(iter(city_data.values()))['daily_temps'])
        truly_complete = result.is_complete and actual_days >= FORECAST_DAYS
        print(f"DEBUG: actual_days={actual_days}, truly_complete={truly_complete}", flush=True)

        # Save partial or complete
        if truly_complete:
            print(f"DEBUG: Promoting to complete run...", flush=True)
            promote_partial_to_complete(run_time, city_data)
            # Clean up session state
            if partial_data_key in st.session_state:
                del st.session_state[partial_data_key]
            print(f"DEBUG: Promoted successfully!", flush=True)
        else:
            print(f"DEBUG: Saving partial run...", flush=True)
            save_partial_run(
                run_time, city_data,
                result.percent_complete,
                result.hours_fetched,
                result.hours_expected,
                last_fetched_hour
            )
            print(f"DEBUG: Partial run saved", flush=True)

        # Return a corrected FetchResult with actual days and completion status
        corrected_result = FetchResult(
            data=result.data,
            run_time=result.run_time,
            hours_fetched=result.hours_fetched,
            hours_expected=result.hours_expected,
            is_complete=truly_complete,
            percent_complete=result.percent_complete,
            available_days=actual_days
        )

        return corrected_result, city_data
    except Exception as e:
        print(f"ERROR in fetch_and_process_partial: {type(e).__name__}: {e}", flush=True)
        raise


def merge_partial_with_cached(partial_data: dict, cached_data: dict, available_days: int) -> dict:
    """
    Merge partial new data with cached complete data.
    Shows new data for available days, cached data for remaining days.

    Args:
        partial_data: Partial city data from new run
        cached_data: Complete city data from cached run
        available_days: Number of days available in partial data

    Returns:
        dict: Merged city data for display
    """
    merged = {}

    for city_id in partial_data.keys():
        partial_city = partial_data[city_id]
        cached_city = cached_data.get(city_id, {})

        merged[city_id] = {
            'daily_temps': [],
            'hdd': [],
            'cdd': [],
            'hdd_cumulative': [],
            'cdd_cumulative': [],
            'is_partial': [],  # Track which days are from partial vs cached
        }

        for day in range(FORECAST_DAYS):
            if day < available_days and day < len(partial_city.get('daily_temps', [])):
                # Use partial data
                merged[city_id]['daily_temps'].append(partial_city['daily_temps'][day])
                merged[city_id]['hdd'].append(partial_city['hdd'][day])
                merged[city_id]['cdd'].append(partial_city['cdd'][day])
                merged[city_id]['is_partial'].append(True)
            elif day < len(cached_city.get('daily_temps', [])):
                # Use cached data
                merged[city_id]['daily_temps'].append(cached_city['daily_temps'][day])
                merged[city_id]['hdd'].append(cached_city['hdd'][day])
                merged[city_id]['cdd'].append(cached_city['cdd'][day])
                merged[city_id]['is_partial'].append(False)
            else:
                # No data available
                merged[city_id]['daily_temps'].append(None)
                merged[city_id]['hdd'].append(None)
                merged[city_id]['cdd'].append(None)
                merged[city_id]['is_partial'].append(False)

        # Recalculate cumulative values
        hdd_cum = 0
        cdd_cum = 0
        for hdd, cdd in zip(merged[city_id]['hdd'], merged[city_id]['cdd']):
            if hdd is not None:
                hdd_cum += hdd
            if cdd is not None:
                cdd_cum += cdd
            merged[city_id]['hdd_cumulative'].append(hdd_cum)
            merged[city_id]['cdd_cumulative'].append(cdd_cum)

    return merged


def display_metric_with_change(label: str, current: float, previous: float = None,
                               format_str: str = "{:.1f}"):
    """Display a metric with change indicator"""
    if previous is not None:
        change = current - previous
        delta = f"{change:+.1f}"
        # Green for upward revision, red for downward revision
        delta_color = "normal"
    else:
        delta = None
        delta_color = "off"

    st.metric(label, format_str.format(current), delta=delta, delta_color=delta_color)


def display_national_summary(national_data: dict, vs_normal: dict = None, comparison: dict = None):
    """Display gas-weighted national HDD/CDD summary"""
    st.markdown("### National Weather Summary (GWHDDs)")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        hdd = national_data.get('weighted_hdd', 0)
        hdd_change = comparison.get('hdd_change') if comparison else None
        display_metric_with_change("Total 14-Day GWHDDs", hdd,
                                   hdd - hdd_change if hdd_change else None)

    with col2:
        cdd = national_data.get('weighted_cdd', 0)
        cdd_change = comparison.get('cdd_change') if comparison else None
        display_metric_with_change("Total 15-Day GWCDDs", cdd,
                                   cdd - cdd_change if cdd_change else None)

    with col3:
        if vs_normal:
            deviation = vs_normal.get('hdd_deviation', 0)
            direction = vs_normal.get('direction', 'near_normal')
            if deviation > 0:
                st.metric("vs 30yr Avg GWHDD", f"+{deviation:.1f}", delta="Colder", delta_color="normal")
            elif deviation < 0:
                st.metric("vs 30yr Avg GWHDD", f"{deviation:.1f}", delta="Warmer", delta_color="inverse")
            else:
                st.metric("vs 30yr Avg GWHDD", "0.0", delta="Normal")
        else:
            st.metric("vs 30yr Avg GWHDD", "N/A")

    with col4:
        total_weight = national_data.get('total_weight', 1.0)
        st.metric("Gas Weight Coverage", f"{total_weight * 100:.0f}%")


def display_regional_cards(regional_data: dict, comparison: dict = None):
    """Display regional breakdown cards"""
    st.markdown("### Regional Breakdown")

    cols = st.columns(4)
    region_order = ['northeast', 'midwest', 'south', 'west']

    for idx, region_id in enumerate(region_order):
        if region_id not in regional_data:
            continue

        data = regional_data[region_id]
        with cols[idx]:
            # Determine direction for styling
            hdd_change = comparison.get(region_id, {}).get('hdd_change', 0) if comparison else 0
            if hdd_change and hdd_change > 2:
                direction_class = 'colder'
            elif hdd_change and hdd_change < -2:
                direction_class = 'warmer'
            else:
                direction_class = 'unchanged'

            st.markdown(f"**{data['name']}**")
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("HDD", f"{data['weighted_hdd']:.1f}")
            with col_b:
                st.metric("CDD", f"{data['weighted_cdd']:.1f}")

            if hdd_change:
                if hdd_change > 0:
                    st.caption(f"+{hdd_change:.1f} HDD vs prev")
                else:
                    st.caption(f"{hdd_change:.1f} HDD vs prev")


def display_delta_summary(summary: dict):
    """Display run-over-run change summary"""
    if not summary or summary.get('direction') == 'no_comparison':
        st.info("No previous run available for comparison")
        return

    direction = summary.get('direction', 'unchanged')
    narrative = summary.get('narrative', '')

    # Style based on direction
    if direction == 'colder':
        css_class = 'delta-colder'
        icon = "Forecast shifted COLDER"
    elif direction == 'warmer':
        css_class = 'delta-warmer'
        icon = "Forecast shifted WARMER"
    else:
        css_class = 'delta-unchanged'
        icon = "Forecast largely unchanged"

    st.markdown(f"""
    <div class="{css_class}">
        <strong>{icon}</strong><br/>
        <span>{narrative}</span>
    </div>
    """, unsafe_allow_html=True)

    # Notable changes
    notable = summary.get('notable_changes', [])
    if notable:
        st.markdown("**Top Changes:**")
        for change in notable[:3]:
            name = change.get('name', '')
            hdd_change = change.get('hdd_change', 0)
            if hdd_change > 0:
                st.caption(f"- {name}: +{hdd_change:.1f} HDD (colder)")
            else:
                st.caption(f"- {name}: {hdd_change:.1f} HDD (warmer)")


def plot_temperature_comparison(city_id: str, latest_data: dict, previous_data: dict = None,
                                is_partial: bool = False, available_days: int = None,
                                normal_temp: float = None):
    """Create temperature comparison chart with partial data support and optional normal line"""
    fig = go.Figure()

    days = list(range(1, len(latest_data['daily_temps']) + 1))
    temps = latest_data['daily_temps']

    # ALWAYS show previous run first (so it's behind current run in layering)
    if previous_data:
        fig.add_trace(go.Scatter(
            x=list(range(1, len(previous_data['daily_temps']) + 1)),
            y=previous_data['daily_temps'],
            mode='lines+markers',
            name='Previous Run',
            line=dict(color='#ff7f0e', width=2, dash='dash'),
            marker=dict(size=6),
            opacity=0.7
        ))

    if is_partial and available_days:
        # Split into new run days vs cached days
        new_days = days[:available_days]
        new_temps = temps[:available_days]
        cached_days = days[available_days:]
        cached_temps = temps[available_days:]

        # New run data (solid, bold green)
        fig.add_trace(go.Scatter(
            x=new_days,
            y=new_temps,
            mode='lines+markers',
            name=f'New Run (Day 1-{available_days})',
            line=dict(color='#2ecc71', width=3),
            marker=dict(size=8)
        ))

        # Remaining days from cached/merged data (gray, indicates not yet loaded from new run)
        if cached_temps:
            fig.add_trace(go.Scatter(
                x=cached_days,
                y=cached_temps,
                mode='lines+markers',
                name='Pending (from cache)',
                line=dict(color='#95a5a6', width=2, dash='dot'),
                marker=dict(size=5),
                opacity=0.5
            ))

        # Add vertical line at transition point
        fig.add_vline(x=available_days + 0.5, line_dash="dot", line_color="green",
                     annotation_text=f"Loading day {available_days + 1}...")
    else:
        # Standard display (complete run)
        fig.add_trace(go.Scatter(
            x=days,
            y=temps,
            mode='lines+markers',
            name='Latest Run',
            line=dict(color='#1f77b4', width=2)
        ))

    # Base temperature line
    fig.add_hline(y=65, line_dash="dot", line_color="gray",
                 annotation_text="Base Temp (65°F)")

    # Add normal temperature line if provided
    if normal_temp is not None:
        fig.add_hline(y=normal_temp, line_dash="dash", line_color="purple",
                     annotation_text=f"30-yr Normal ({normal_temp:.0f}°F)")

    city_name = POPULATION_CENTERS[city_id]['name']
    title = f"Daily Average Temperature - {city_name}"
    if is_partial:
        title += f" (Days 1-{available_days} loading)"

    fig.update_layout(
        title=title,
        xaxis_title="Forecast Day",
        yaxis_title="Temperature (°F)",
        hovermode='x unified',
        height=400
    )

    return fig


def plot_degree_days_comparison(city_id: str, latest_data: dict, previous_data: dict = None,
                                metric: str = 'hdd', is_partial: bool = False,
                                available_days: int = None):
    """Create degree days comparison bar chart with partial data support"""
    days = list(range(1, len(latest_data[metric]) + 1))
    latest_values = latest_data[metric]
    previous_values = previous_data[metric] if previous_data else None

    fig = go.Figure()

    metric_name = "HDD" if metric == 'hdd' else "CDD"
    base_color = '#1f77b4' if metric == 'hdd' else '#d62728'
    new_color = '#2ecc71' if metric == 'hdd' else '#e74c3c'

    if is_partial and available_days:
        # ALWAYS show previous run for comparison (all 14 days)
        if previous_values:
            fig.add_trace(go.Bar(
                x=days,
                y=previous_values,
                name='Previous Run',
                marker_color='#ff7f0e',
                opacity=0.4
            ))

        # New run bars (loaded days only - vibrant color)
        new_values = latest_values[:available_days]
        fig.add_trace(go.Bar(
            x=days[:available_days],
            y=new_values,
            name=f'New Run (Day 1-{available_days})',
            marker_color=new_color
        ))

        # Pending days from cache (muted)
        cached_values = latest_values[available_days:]
        if cached_values:
            fig.add_trace(go.Bar(
                x=days[available_days:],
                y=cached_values,
                name='Pending (from cache)',
                marker_color='#95a5a6',
                opacity=0.5
            ))

        # Add vertical line at transition
        fig.add_vline(x=available_days + 0.5, line_dash="dot", line_color="green")
    else:
        # Standard display (complete run)
        if previous_values:
            fig.add_trace(go.Bar(
                x=days,
                y=previous_values,
                name='Previous Run',
                marker_color='lightgray'
            ))

        fig.add_trace(go.Bar(
            x=days,
            y=latest_values,
            name='Latest Run',
            marker_color=base_color
        ))

    city_name = POPULATION_CENTERS[city_id]['name']
    title = f"Daily {metric_name} - {city_name}"
    if is_partial:
        title += f" (Days 1-{available_days} loaded)"

    fig.update_layout(
        title=title,
        xaxis_title="Forecast Day",
        yaxis_title=f"{metric_name} (degree days)",
        barmode='group',
        hovermode='x unified',
        height=400
    )

    return fig


def plot_cumulative_degree_days(city_id: str, latest_data: dict, previous_data: dict = None):
    """Create cumulative degree days chart"""
    days = list(range(1, len(latest_data['hdd_cumulative']) + 1))

    fig = go.Figure()

    # Latest HDD
    fig.add_trace(go.Scatter(
        x=days,
        y=latest_data['hdd_cumulative'],
        mode='lines+markers',
        name='Latest HDD',
        line=dict(color='#1f77b4', width=2)
    ))

    # Latest CDD
    fig.add_trace(go.Scatter(
        x=days,
        y=latest_data['cdd_cumulative'],
        mode='lines+markers',
        name='Latest CDD',
        line=dict(color='#d62728', width=2)
    ))

    # Previous runs
    if previous_data:
        fig.add_trace(go.Scatter(
            x=days,
            y=previous_data['hdd_cumulative'],
            mode='lines',
            name='Previous HDD',
            line=dict(color='#1f77b4', width=2, dash='dash')
        ))

        fig.add_trace(go.Scatter(
            x=days,
            y=previous_data['cdd_cumulative'],
            mode='lines',
            name='Previous CDD',
            line=dict(color='#d62728', width=2, dash='dash')
        ))

    city_name = POPULATION_CENTERS[city_id]['name']
    fig.update_layout(
        title=f"Cumulative Degree Days - {city_name}",
        xaxis_title="Forecast Day",
        yaxis_title="Cumulative Degree Days",
        hovermode='x unified',
        height=400
    )

    return fig


def plot_cross_city_comparison(city_data_dict: dict, metric: str = 'hdd'):
    """Create cross-city comparison chart"""
    city_names = [POPULATION_CENTERS[city_id]['name'] for city_id in city_data_dict.keys()]
    totals = [sum(data[metric]) for data in city_data_dict.values()]

    metric_name = "HDD" if metric == 'hdd' else "CDD"
    color = '#1f77b4' if metric == 'hdd' else '#d62728'

    fig = go.Figure(data=[
        go.Bar(x=city_names, y=totals, marker_color=color)
    ])

    fig.update_layout(
        title=f"{FORECAST_DAYS}-Day Total {metric_name} - City Comparison",
        xaxis_title="City",
        yaxis_title=f"Total {metric_name}",
        height=400
    )

    return fig


def plot_national_gwhdd_comparison(
    latest_city_data: dict,
    previous_city_data: dict,
    run_time: datetime,
    is_partial: bool = False,
    available_days: int = None
):
    """
    Create chart showing daily national GWHDD comparing current run, previous run, and normal.

    Args:
        latest_city_data: Current run city data
        previous_city_data: Previous run city data (or None)
        run_time: Forecast start datetime
        is_partial: Whether current data is still loading
        available_days: Number of days loaded so far (if partial)
    """
    # Calculate daily weighted aggregates for current and previous
    latest_daily = calculate_daily_weighted_aggregates(latest_city_data)
    previous_daily = calculate_daily_weighted_aggregates(previous_city_data) if previous_city_data else None

    num_days = len(latest_daily['daily_weighted_hdd'])
    days = list(range(1, num_days + 1))

    # Calculate daily normal GWHDD
    normal_gwhdd = calculate_daily_normal_gwhdd(run_time, num_days)

    fig = go.Figure()

    # Add normal line first (background)
    fig.add_trace(go.Scatter(
        x=days,
        y=normal_gwhdd,
        mode='lines',
        name='30-yr Normal',
        line=dict(color='purple', width=2, dash='dash'),
        opacity=0.7
    ))

    # Add previous run (if available)
    if previous_daily and previous_daily['daily_weighted_hdd']:
        prev_days = min(len(previous_daily['daily_weighted_hdd']), num_days)
        fig.add_trace(go.Scatter(
            x=list(range(1, prev_days + 1)),
            y=previous_daily['daily_weighted_hdd'][:prev_days],
            mode='lines+markers',
            name='Previous Run',
            line=dict(color='#ff7f0e', width=2, dash='dash'),
            marker=dict(size=6),
            opacity=0.7
        ))

    # Add current run
    if is_partial and available_days:
        # Split into loaded vs pending
        new_days = days[:available_days]
        new_values = latest_daily['daily_weighted_hdd'][:available_days]
        pending_days = days[available_days:]
        pending_values = latest_daily['daily_weighted_hdd'][available_days:]

        fig.add_trace(go.Scatter(
            x=new_days,
            y=new_values,
            mode='lines+markers',
            name=f'Latest Run (Day 1-{available_days})',
            line=dict(color='#2ecc71', width=3),
            marker=dict(size=8)
        ))

        if pending_values:
            fig.add_trace(go.Scatter(
                x=pending_days,
                y=pending_values,
                mode='lines+markers',
                name='Pending (from cache)',
                line=dict(color='#95a5a6', width=2, dash='dot'),
                marker=dict(size=5),
                opacity=0.5
            ))

        fig.add_vline(x=available_days + 0.5, line_dash="dot", line_color="green",
                     annotation_text=f"Loading day {available_days + 1}...")
    else:
        fig.add_trace(go.Scatter(
            x=days,
            y=latest_daily['daily_weighted_hdd'],
            mode='lines+markers',
            name='Latest Run',
            line=dict(color='#1f77b4', width=2),
            marker=dict(size=6)
        ))

    title = "Daily Gas-Weighted HDD (10 Cities)"
    if is_partial:
        title += f" (Days 1-{available_days} loading)"

    fig.update_layout(
        title=title,
        xaxis_title="Forecast Day",
        yaxis_title="GWHDD",
        hovermode='x unified',
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    return fig

# Alias for backward compatibility
plot_national_pwhdd_comparison = plot_national_gwhdd_comparison


def plot_city_vs_normal(city_data_dict: dict, run_time: datetime):
    """Create chart comparing forecast HDD to 30-year normal for each city"""
    from src.calculations.climate_deviation import calculate_forecast_vs_normal

    cities = []
    forecast_hdds = []
    normal_hdds = []
    deviations = []

    for city_id, data in city_data_dict.items():
        if city_id not in POPULATION_CENTERS:
            continue

        city_name = POPULATION_CENTERS[city_id]['name']
        cities.append(city_name)

        # Calculate forecast total HDD
        forecast_hdd = sum(data['hdd'])
        forecast_hdds.append(forecast_hdd)

        # Calculate normal HDD for forecast period
        vs_normal = calculate_forecast_vs_normal(city_id, data['daily_temps'], run_time)
        if vs_normal:
            normal_hdds.append(vs_normal['expected_hdd'])
            deviations.append(vs_normal['hdd_deviation'])
        else:
            normal_hdds.append(0)
            deviations.append(0)

    fig = go.Figure()

    # Normal HDD bars
    fig.add_trace(go.Bar(
        x=cities,
        y=normal_hdds,
        name='30-yr Normal HDD',
        marker_color='#9ca3af'
    ))

    # Forecast HDD bars
    fig.add_trace(go.Bar(
        x=cities,
        y=forecast_hdds,
        name='Forecast HDD',
        marker_color='#3b82f6'
    ))

    fig.update_layout(
        title=f"{FORECAST_DAYS}-Day Forecast HDD vs 30-Year Normal",
        xaxis_title="City",
        yaxis_title="Total HDD",
        barmode='group',
        height=400
    )

    return fig


# Main app
def main():
    print(f"\n{'='*60}", flush=True)
    print(f"DEBUG main(): App starting...", flush=True)

    # Check if we're in a publishing window for any run
    newest_run = get_newest_possible_run()
    in_publishing = is_in_publishing_window(newest_run)

    print(f"DEBUG main: newest_run={format_zulu(newest_run)}, in_publishing={in_publishing}", flush=True)

    # Track if current run is complete (will be set later, used for auto-refresh decision)
    run_is_complete = False

    # Initialize session state
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'current_run_time' not in st.session_state:
        st.session_state.current_run_time = None
    if 'is_loading_partial' not in st.session_state:
        st.session_state.is_loading_partial = False

    # Start auto-refresh - fast during publishing, slow when idle
    # This must be called early in the script to ensure the refresh cycle starts
    run_complete_this_session = st.session_state.get('run_complete_for', None) == newest_run.isoformat()
    if AUTOREFRESH_AVAILABLE and st_autorefresh is not None:
        if in_publishing and not run_complete_this_session:
            # Fast refresh during active publishing
            st_autorefresh(
                interval=AUTO_REFRESH_PUBLISHING_MS,
                limit=None,
                key="gfs_autorefresh"
            )
        else:
            # Slow refresh when idle - detects when new publishing window opens
            st_autorefresh(
                interval=AUTO_REFRESH_IDLE_MS,
                limit=None,
                key="gfs_autorefresh_idle"
            )

    st.title("GFS Weather Model")
    st.markdown("**Gas-Weighted Heating & Cooling Degree Days for Natural Gas Trading**")

    # Get cached data first
    latest_saved = get_latest_saved_run()
    cached_city_data = get_city_data(latest_saved) if latest_saved else None
    cached_run_time = datetime.fromisoformat(latest_saved['run_time']) if latest_saved else None

    print(f"DEBUG main: Disk cache check - latest_saved exists: {latest_saved is not None}", flush=True)
    if latest_saved:
        print(f"DEBUG main: Cached run_time from disk: {format_zulu(cached_run_time)}", flush=True)
        print(f"DEBUG main: Cached city_data has {len(cached_city_data)} cities", flush=True)
    else:
        print(f"DEBUG main: No cached data on disk", flush=True)

    # Check for partial run in progress
    partial_run = load_partial_run(newest_run) if in_publishing else None
    print(f"DEBUG main: partial_run exists: {partial_run is not None}", flush=True)

    # Sidebar
    with st.sidebar:
        st.header("Settings")

        # Refresh button
        refresh_clicked = st.button("Refresh Data", width='stretch')

        if refresh_clicked:
            st.cache_data.clear()
            delete_partial_run(newest_run)  # Clear any partial data to force re-fetch
            # Clear session state for partial xarray data
            partial_key = f'partial_xarray_{newest_run.isoformat()}'
            if partial_key in st.session_state:
                del st.session_state[partial_key]
            # Clear session cache for city data (to force refetch)
            session_cache_key = f'session_city_data_{newest_run.isoformat()}'
            session_result_key = f'session_fetch_result_{newest_run.isoformat()}'
            session_fetch_time_key = f'session_fetch_time_{newest_run.isoformat()}'
            if session_cache_key in st.session_state:
                del st.session_state[session_cache_key]
            if session_result_key in st.session_state:
                del st.session_state[session_result_key]
            if session_fetch_time_key in st.session_state:
                del st.session_state[session_fetch_time_key]
            st.session_state['force_fetch'] = True  # Signal to fetch new data
            st.rerun()

        st.markdown("---")

        # Publishing status indicator
        # Check session state for completion status (set later in code)
        run_complete_this_session = st.session_state.get('run_complete_for', None) == newest_run.isoformat()

        st.markdown("### Status")

        if in_publishing and not run_complete_this_session:
            st.markdown(f"""
            <div class="status-live">
                <strong>LIVE</strong><br/>
                <span style="font-size: 0.9em;">{format_zulu(newest_run)} publishing</span><br/>
                <span style="font-size: 0.8em; color: #15803d;">Auto-refresh: 1 min</span>
            </div>
            """, unsafe_allow_html=True)

            # If we have partial data, show progress
            if partial_run:
                pct = partial_run.get('percent_complete', 0)
                days = partial_run.get('forecast_days', 0)
                # Clamp to max 1.0 in case of over-fetch
                progress_value = min(pct / 100, 1.0)
                st.progress(progress_value, text=f"{pct:.0f}% ({days}/{FORECAST_DAYS} days)")

        elif in_publishing and run_complete_this_session:
            st.markdown(f"""
            <div class="status-complete">
                <strong>COMPLETE</strong><br/>
                <span style="font-size: 0.9em;">{format_zulu(newest_run)} loaded</span><br/>
                <span style="font-size: 0.8em; color: #1d4ed8;">Auto-refresh: stopped</span>
            </div>
            """, unsafe_allow_html=True)

        else:
            if AUTOREFRESH_AVAILABLE:
                st.markdown("""
                <div class="status-idle">
                    <strong>IDLE</strong><br/>
                    <span style="font-size: 0.9em;">No active publishing</span><br/>
                    <span style="font-size: 0.8em; color: #6b7280;">Auto-check: 5 min</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="status-idle">
                    <strong>IDLE</strong><br/>
                    <span style="font-size: 0.9em;">No active publishing</span>
                </div>
                """, unsafe_allow_html=True)
                st.warning("Install `streamlit-autorefresh` for auto-updates")

        st.markdown("---")
        st.markdown("### Update Windows - Estimate")
        st.markdown("""
        | Run | Window |
        |-----|--------|
        | 00z | 8:30 PM - 12:00 AM* |
        | 06z | 2:30 AM - 6:00 AM |
        | 12z | 8:30 AM - 12:00 PM |
        | 18z | 2:30 PM - 6:00 PM |

                    
        """)

        st.markdown("---")
        st.markdown("### About")
        st.markdown("""
        This tool pulls GFS weather forecasts as Gas-Weighted HDDs (GWHDDs).

        **10 Cities (weighted by EIA 5-yr avg gas consumption):**
        - **Northeast (35%):** NY, Boston, Philadelphia
        - **Midwest (22%):** Chicago, Detroit
        - **South (24%):** Houston, Dallas, Atlanta
        - **West (19%):** Denver, Los Angeles

        **Metrics:**
        - HDD (Heating Degree Days): Base 65°F
        - CDD (Cooling Degree Days): Base 65°F
        - GWHDD (Gas-weighted DDs): HDD/CDDs weighted by state gas consumption
        - 15-day forecast (GFS 0.5°, 2 meter air temp)
        """)

    # Determine what to display based on state
    run_time = None
    latest_city_data = None
    is_partial_display = False
    available_days = FORECAST_DAYS

    # Check if this is an auto-refresh or force refresh (vs just a UI interaction like city change)
    # Auto-refresh sets a query param, force_fetch is set by button click
    # Use pop() to clear the flag after reading it (prevents repeated refetches)
    is_refresh_trigger = st.session_state.pop('force_fetch', False)

    # GLOBAL fetch guard - only one fetch at a time across ALL runs
    # Reset the guard on each fresh page load to prevent it getting stuck
    if 'global_fetch_in_progress' not in st.session_state:
        st.session_state.global_fetch_in_progress = False
    elif st.session_state.global_fetch_in_progress:
        # Guard might be stuck from a previous interrupted run - reset it
        print(f"DEBUG main: Resetting stuck global_fetch_in_progress flag", flush=True)
        st.session_state.global_fetch_in_progress = False

    # During publishing window, try to fetch partial data
    if in_publishing:
        print(f"DEBUG main: In publishing window for {format_zulu(newest_run)}", flush=True)

        # FIRST: Ensure immediate previous run is cached for comparison
        previous_run_time = get_previous_gfs_run(newest_run)
        previous_run_cached = load_model_run(previous_run_time)
        print(f"DEBUG main: previous_run_time={format_zulu(previous_run_time)}, cached={previous_run_cached is not None}", flush=True)

        # Check if cached data is the immediate previous run
        cached_is_previous = (cached_run_time == previous_run_time) if cached_run_time else False
        print(f"DEBUG main: cached_run_time={format_zulu(cached_run_time) if cached_run_time else None}, cached_is_previous={cached_is_previous}", flush=True)

        # Fetch previous run if needed (using global guard)
        if previous_run_cached is None and not cached_is_previous and not st.session_state.global_fetch_in_progress:
            print(f"DEBUG main: Need to fetch previous run, setting global_fetch_in_progress=True", flush=True)
            # Previous run not specifically cached - need to fetch it
            st.session_state.global_fetch_in_progress = True
            st.info(f"Fetching previous run ({format_zulu(previous_run_time)}) for comparison...")
            try:
                with st.spinner(f"Fetching {format_zulu(previous_run_time)}..."):
                    _, prev_city_data = fetch_and_process_gfs_data(previous_run_time.isoformat())
                    # Update cached data references to use the previous run
                    cached_city_data = prev_city_data
                    cached_run_time = previous_run_time
                    latest_saved = {'run_time': previous_run_time.isoformat(), 'cities': prev_city_data}
                print(f"DEBUG main: Previous run fetch successful!", flush=True)
                st.success(f"Previous run cached: {format_zulu(previous_run_time)}")
            except Exception as e:
                print(f"DEBUG main: Previous run fetch FAILED: {type(e).__name__}: {e}", flush=True)
                st.warning(f"Could not fetch previous run: {e}")
                # Continue with whatever cached data we have (if any)
            finally:
                st.session_state.global_fetch_in_progress = False
                print(f"DEBUG main: global_fetch_in_progress reset to False", flush=True)
        else:
            print(f"DEBUG main: Skipping previous run fetch (cached={previous_run_cached is not None}, cached_is_previous={cached_is_previous}, fetch_in_progress={st.session_state.global_fetch_in_progress})", flush=True)

        # Check if we already have session-cached data for this run (avoid refetch on city change)
        session_cache_key = f'session_city_data_{newest_run.isoformat()}'
        session_result_key = f'session_fetch_result_{newest_run.isoformat()}'
        session_fetch_time_key = f'session_fetch_time_{newest_run.isoformat()}'

        # Determine if we need to fetch: first load, auto-refresh interval elapsed, or force refresh
        have_session_cache = session_cache_key in st.session_state and st.session_state[session_cache_key] is not None

        # Use timestamp to detect auto-refresh vs UI interaction (like city change)
        # Auto-refresh is 1 minute, so if less than 45 seconds have passed, it's just a UI interaction
        current_time = time.time()
        last_fetch_time = st.session_state.get(session_fetch_time_key, 0)
        time_since_fetch = current_time - last_fetch_time
        min_refresh_interval = 45  # 45 seconds - less than auto-refresh interval

        # Only consider it an auto-refresh if enough time has passed
        is_auto_refresh = time_since_fetch >= min_refresh_interval

        # Check if the cached result is already complete (no need to refetch if complete)
        cached_is_complete = (session_result_key in st.session_state and
                              st.session_state[session_result_key].get('is_complete', False))

        need_fetch = not have_session_cache or (is_auto_refresh and not cached_is_complete) or is_refresh_trigger

        # Check if a fetch is already in progress (global guard - prevents concurrent fetches)
        fetch_already_running = st.session_state.global_fetch_in_progress

        print(f"DEBUG main: Newest run fetch decision:", flush=True)
        print(f"  have_session_cache={have_session_cache}", flush=True)
        print(f"  is_auto_refresh={is_auto_refresh} (time_since_fetch={time_since_fetch:.1f}s)", flush=True)
        print(f"  cached_is_complete={cached_is_complete}", flush=True)
        print(f"  is_refresh_trigger={is_refresh_trigger}", flush=True)
        print(f"  need_fetch={need_fetch}", flush=True)
        print(f"  fetch_already_running={fetch_already_running}", flush=True)

        if need_fetch and not fetch_already_running:
            print(f"DEBUG main: Starting newest run fetch for {format_zulu(newest_run)}", flush=True)
            # Set global fetch in progress flag
            st.session_state.global_fetch_in_progress = True

            try:
                # Fetch whatever is available
                with st.spinner("Checking for new data..."):
                    fetch_result, partial_city_data = fetch_and_process_partial(newest_run)

                print(f"DEBUG main: Newest run fetch complete. is_complete={fetch_result.is_complete}, days={fetch_result.available_days}", flush=True)

                # Cache in session state for subsequent reruns (like city selection changes)
                st.session_state[session_cache_key] = partial_city_data
                st.session_state[session_result_key] = {
                    'is_complete': fetch_result.is_complete,
                    'percent_complete': fetch_result.percent_complete,
                    'available_days': fetch_result.available_days,
                    'hours_fetched': fetch_result.hours_fetched
                }
                # Record fetch timestamp to distinguish auto-refresh from UI interactions
                st.session_state[session_fetch_time_key] = current_time
                print(f"DEBUG main: Session state updated for newest run", flush=True)
            except Exception as e:
                print(f"DEBUG main: Newest run fetch FAILED: {type(e).__name__}: {e}", flush=True)
                raise
            finally:
                # Clear global fetch in progress flag
                st.session_state.global_fetch_in_progress = False
                print(f"DEBUG main: global_fetch_in_progress reset to False after newest run", flush=True)
        elif fetch_already_running:
            # Fetch in progress, use cached data if available
            if have_session_cache:
                partial_city_data = st.session_state[session_cache_key]
                cached_result = st.session_state[session_result_key]
                class CachedResult:
                    def __init__(self, d):
                        self.is_complete = d['is_complete']
                        self.percent_complete = d['percent_complete']
                        self.available_days = d['available_days']
                        self.hours_fetched = d['hours_fetched']
                fetch_result = CachedResult(cached_result)
            else:
                # No session cache but fetch in progress - use disk-cached data and continue
                st.info("Data fetch in progress... showing cached data.")
                # Create a minimal fetch_result to allow display to continue
                class MinimalResult:
                    def __init__(self):
                        self.is_complete = False
                        self.percent_complete = 0
                        self.available_days = 0
                        self.hours_fetched = 0
                fetch_result = MinimalResult()
                partial_city_data = None  # Will fall through to use cached_city_data below
        else:
            # Use session-cached data (no refetch needed)
            partial_city_data = st.session_state[session_cache_key]
            cached_result = st.session_state[session_result_key]
            # Reconstruct a minimal fetch_result-like object
            class CachedResult:
                def __init__(self, d):
                    self.is_complete = d['is_complete']
                    self.percent_complete = d['percent_complete']
                    self.available_days = d['available_days']
                    self.hours_fetched = d['hours_fetched']
            fetch_result = CachedResult(cached_result)

        # Display status header based on completion
        st.markdown("---")

        if fetch_result.is_complete:
            # Complete! Use the new data
            run_time = newest_run
            latest_city_data = partial_city_data
            is_partial_display = False
            available_days = FORECAST_DAYS
            run_is_complete = True  # Stop auto-refresh

            # Check if this is first time detecting completion
            was_already_complete = st.session_state.get('run_complete_for', None) == newest_run.isoformat()
            st.session_state['run_complete_for'] = newest_run.isoformat()  # Track completion in session

            if not was_already_complete:
                # First time detecting completion - rerun to update sidebar status
                st.rerun()

            st.markdown(f"""
            <div class="status-complete">
                <strong>Run Complete:</strong> {format_zulu(newest_run)} &mdash; All {FORECAST_DAYS} days loaded
            </div>
            """, unsafe_allow_html=True)

        elif partial_city_data is not None:
            # Partial data available - show loading header with progress
            progress_col1, progress_col2 = st.columns([3, 1])

            with progress_col1:
                st.subheader(f"Loading {format_zulu(newest_run)}...")

            with progress_col2:
                st.metric("Progress", f"{fetch_result.percent_complete:.0f}%",
                         delta=f"{fetch_result.available_days} days")

            # Create progress bar (clamp to max 1.0 in case of over-fetch)
            progress_value = min(fetch_result.percent_complete / 100, 1.0)
            st.progress(progress_value,
                       text=f"Day {fetch_result.available_days} of {FORECAST_DAYS} loaded")

            if cached_city_data:
                # Merge partial with cached
                run_time = newest_run
                latest_city_data = merge_partial_with_cached(
                    partial_city_data, cached_city_data, fetch_result.available_days
                )
                is_partial_display = True
                available_days = fetch_result.available_days
                st.info(f"Showing days 1-{available_days} from **{format_zulu(newest_run)}** | "
                       f"Days {available_days + 1}-{FORECAST_DAYS} from **{format_zulu(cached_run_time)}**")
            else:
                # No cached data, just show partial
                run_time = newest_run
                latest_city_data = partial_city_data
                is_partial_display = True
                available_days = fetch_result.available_days
                st.warning(f"Partial data: {available_days} of {FORECAST_DAYS} days available")
        else:
            # No data from new run yet
            st.warning(f"{format_zulu(newest_run)} not yet available. Waiting...")

            if cached_city_data:
                run_time = cached_run_time
                latest_city_data = cached_city_data
                st.info(f"Displaying cached run: {format_zulu(cached_run_time)}")
            else:
                st.error("No cached data available. Please wait for data to become available.")
                st.stop()

        st.markdown("---")

    elif cached_city_data:
        # Not in publishing window, use cached data OR fetch if newer run available
        conservative_run = get_latest_gfs_run()
        fetched_something = False

        run_time = cached_run_time
        latest_city_data = cached_city_data

        # Check if cached data is stale (newer run available)
        cached_is_stale = cached_run_time < conservative_run if cached_run_time else True

        if is_refresh_trigger or cached_is_stale:
            if is_refresh_trigger:
                st.markdown("---")

            # Step 1: Fetch newer run if available
            if cached_run_time != conservative_run:
                if is_refresh_trigger:
                    st.markdown("## Fetching Latest GFS Data")
                    st.markdown(f"**Target run:** {format_zulu(conservative_run)}")

                try:
                    spinner_msg = f"Fetching {format_zulu(conservative_run)}..."
                    if cached_is_stale and not is_refresh_trigger:
                        spinner_msg = f"New run available - fetching {format_zulu(conservative_run)}..."
                    with st.spinner(spinner_msg):
                        run_time, latest_city_data = fetch_and_process_gfs_data(conservative_run.isoformat())
                    if is_refresh_trigger:
                        st.success(f"Fetched GFS run: {format_zulu(run_time)}")
                    fetched_something = True
                    # Update cached references for next check
                    cached_run_time = run_time
                    cached_city_data = latest_city_data
                except Exception as e:
                    st.error(f"Failed to fetch: {e}")

            # Step 2: Check if previous run for comparison is missing
            previous_run_time = get_previous_gfs_run(cached_run_time)
            previous_run_cached = load_model_run(previous_run_time)

            if previous_run_cached is None:
                if is_refresh_trigger:
                    st.markdown("## Fetching Previous Run for Comparison")
                    st.markdown(f"**Target run:** {format_zulu(previous_run_time)}")

                try:
                    with st.spinner(f"Fetching {format_zulu(previous_run_time)}..."):
                        fetch_and_process_gfs_data(previous_run_time.isoformat())
                    if is_refresh_trigger:
                        st.success(f"Fetched previous run: {format_zulu(previous_run_time)}")
                    fetched_something = True
                except Exception as e:
                    st.error(f"Failed to fetch previous run: {e}")

            if fetched_something:
                st.rerun()  # Rerun to display fresh data
            elif is_refresh_trigger:
                st.info("All data is up to date")

        # Check if previous run for comparison is missing (for display purposes)
        previous_run_time = get_previous_gfs_run(run_time)
        previous_run_cached = load_model_run(previous_run_time)

        if cached_run_time == conservative_run:
            st.info(f"Displaying latest GFS run: {format_zulu(run_time)}")
        else:
            st.warning(f"Displaying cached run: {format_zulu(run_time)}")
            st.info(f"Newer run available: {format_zulu(conservative_run)} - Click 'Refresh Data' to update")

        # Show warning if previous run is missing
        if previous_run_cached is None:
            st.warning(f"Previous run ({format_zulu(previous_run_time)}) not cached - Click 'Refresh Data' to fetch for comparison")

    else:
        # No cached data, must fetch complete run
        st.markdown("---")
        _, loading_col, _ = st.columns([1, 2, 1])
        with loading_col:
            st.markdown("## Loading GFS Data")
            st.markdown("*No cached data found. Fetching complete forecast...*")
            conservative_run = get_latest_gfs_run()
            st.markdown(f"**Fetching run:** {format_zulu(conservative_run)}")
            progress_bar = st.progress(0, text="Initializing...")

            try:
                progress_bar.progress(10, text="Connecting to NOMADS...")
                run_time, latest_city_data = fetch_and_process_gfs_data(conservative_run.isoformat())
                progress_bar.progress(100, text="Complete!")
                st.success(f"Fetched GFS run: {format_zulu(run_time)}")
                st.rerun()
            except Exception as e:
                progress_bar.progress(100, text="Failed!")
                st.error(f"Failed to fetch GFS data: {e}")
                st.warning("Please try again later or check your internet connection.")
                st.stop()

    # Load previous run for comparison (use cached complete run if showing partial)
    if is_partial_display and cached_city_data:
        # For partial display, compare to the cached run
        previous_city_data = cached_city_data
        previous_run_raw = latest_saved
    else:
        previous_run_raw = get_previous_run_data(run_time)
        previous_city_data = get_city_data(previous_run_raw) if previous_run_raw else None

    # Display model run info
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if is_partial_display:
            st.warning(f"**Loading:** {format_zulu(run_time)} ({available_days} days)")
        else:
            st.info(f"**Latest Run:** {format_zulu(run_time)}")
    with col2:
        if previous_run_raw:
            prev_time = datetime.fromisoformat(previous_run_raw['run_time'])
            if is_partial_display:
                st.info(f"**Cached Run:** {format_zulu(prev_time)}")
            else:
                st.info(f"**Previous Run:** {format_zulu(prev_time)}")
        else:
            st.warning("**Previous Run:** Not available")
    with col3:
        if is_partial_display:
            st.warning(f"**Loaded:** {available_days} / {FORECAST_DAYS} days")
        else:
            st.info(f"**Forecast Range:** {FORECAST_DAYS} days")
    with col4:
        # Show when this data pull completed (in Central Time)
        if is_partial_display:
            st.warning("**Pull Status:** In Progress...")
        else:
            fetch_time = latest_saved.get('fetch_completed_at') if latest_saved else None
            if fetch_time:
                st.info(f"**Pull Finished:** {fetch_time}")
            else:
                st.info("**Pull Finished:** N/A")

    st.markdown("---")

    # ==========================================================================
    # NATIONAL & REGIONAL SUMMARY (Population-Weighted)
    # ==========================================================================
    st.header("National Weather Signal")

    # Calculate national and regional aggregates from city data
    national_agg = calculate_national_aggregate(latest_city_data)
    regional_agg = calculate_regional_aggregates(latest_city_data)

    # Show info about data coverage
    num_gas_centers = sum(1 for loc_id in latest_city_data if loc_id in GAS_CONSUMPTION_CENTERS)
    total_weight = national_agg.get('total_weight', 0)
    if num_gas_centers > 0:
        st.caption(f"Based on {num_gas_centers} cities weighted by EIA gas consumption ({total_weight * 100:.0f}% coverage)")
    else:
        st.caption("Loading gas consumption center data...")

    # Calculate comparison if previous data available
    if previous_city_data:
        prev_national = calculate_national_aggregate(previous_city_data)
        prev_regional = calculate_regional_aggregates(previous_city_data)
        national_comparison = {
            'hdd_change': national_agg['weighted_hdd'] - prev_national['weighted_hdd'],
            'cdd_change': national_agg['weighted_cdd'] - prev_national['weighted_cdd']
        }
        regional_comparison = {}
        for region_id in regional_agg:
            if region_id in prev_regional:
                regional_comparison[region_id] = {
                    'hdd_change': regional_agg[region_id]['weighted_hdd'] - prev_regional[region_id]['weighted_hdd'],
                    'cdd_change': regional_agg[region_id]['weighted_cdd'] - prev_regional[region_id]['weighted_cdd']
                }
    else:
        national_comparison = None
        regional_comparison = None

    # Calculate vs normal deviation
    national_vs_normal = calculate_national_vs_normal(latest_city_data, run_time)

    # Display national summary
    display_national_summary(national_agg, vs_normal=national_vs_normal, comparison=national_comparison)

    st.markdown("---")

    # Display delta summary if comparison available
    if national_comparison:
        # Create simple delta summary
        hdd_change = national_comparison.get('hdd_change', 0)
        if hdd_change > 5:
            direction = 'colder'
            narrative = f"Forecast shifted COLDER: +{hdd_change:.1f} weighted HDDs"
        elif hdd_change < -5:
            direction = 'warmer'
            narrative = f"Forecast shifted WARMER: {hdd_change:.1f} weighted HDDs"
        else:
            direction = 'unchanged'
            narrative = "Forecast largely unchanged from previous run"

        # Calculate per-city HDD changes for notable changes
        notable_changes = []
        for city_id, city_info in POPULATION_CENTERS.items():
            if city_id in latest_city_data and city_id in previous_city_data:
                latest_hdd = sum(latest_city_data[city_id].get('hdd', []))
                prev_hdd = sum(previous_city_data[city_id].get('hdd', []))
                city_hdd_change = latest_hdd - prev_hdd
                notable_changes.append({
                    'name': city_info['name'],
                    'hdd_change': city_hdd_change
                })
        # Sort by absolute change, descending
        notable_changes.sort(key=lambda x: abs(x['hdd_change']), reverse=True)

        delta_summary = {
            'direction': direction,
            'narrative': narrative,
            'national_hdd_change': hdd_change,
            'notable_changes': notable_changes
        }
        display_delta_summary(delta_summary)
        st.markdown("---")

    # National GWHDD Chart - shows daily run-over-run changes vs normal
    st.plotly_chart(
        plot_national_gwhdd_comparison(
            latest_city_data, previous_city_data, run_time,
            is_partial=is_partial_display, available_days=available_days
        ),
        width='stretch'
    )
    st.markdown("---")

    # Display regional breakdown
    display_regional_cards(regional_agg, regional_comparison)

    st.markdown("---")

    # ==========================================================================
    # CITY ANALYSIS (10 Gas Consumption Centers)
    # ==========================================================================
    st.header("City Analysis")

    # City data is now our primary and only data source
    city_data = latest_city_data
    prev_city_data = previous_city_data

    comparison_data = compare_runs(city_data, prev_city_data)

    # Display cities in rows of 5 (2 rows for 10 cities)
    city_list = list(POPULATION_CENTERS.items())
    cities_per_row = 5

    for row_start in range(0, len(city_list), cities_per_row):
        row_cities = city_list[row_start:row_start + cities_per_row]
        cols = st.columns(len(row_cities))

        for idx, (city_id, city_info) in enumerate(row_cities):
            with cols[idx]:
                st.subheader(city_info['name'])
                st.caption(f"{city_info['state']} - {city_info['region'].title()}")

                if city_id in comparison_data:
                    comp = comparison_data[city_id]
                    col_a, col_b = st.columns(2)
                    with col_a:
                        display_metric_with_change(
                            "Total HDD",
                            comp['latest_hdd'],
                            comp['previous_hdd']
                        )
                    with col_b:
                        display_metric_with_change(
                            "Total CDD",
                            comp['latest_cdd'],
                            comp['previous_cdd']
                        )

    st.markdown("---")

    # Comparison table
    st.header("Summary Table")
    comparison_df = create_comparison_dataframe(comparison_data, location_type='population_centers')
    st.dataframe(comparison_df, width='stretch', hide_index=True)

    st.markdown("---")

    # Forecast vs Normal comparison
    st.header("Forecast vs 30-Year Normal")
    st.plotly_chart(plot_city_vs_normal(city_data, run_time),
                   width='stretch')

    st.markdown("---")

    # Detailed city views
    st.header("Detailed City Analysis")

    selected_city = st.selectbox(
        "Select city for detailed view:",
        options=list(POPULATION_CENTERS.keys()),
        format_func=lambda x: f"{POPULATION_CENTERS[x]['name']} ({POPULATION_CENTERS[x]['state']})"
    )

    city_latest = city_data.get(selected_city)
    city_previous = prev_city_data.get(selected_city) if prev_city_data else None

    if city_latest:
        # Get normal temperature for this city/month
        from src.calculations.climate_deviation import get_climate_normal_for_date
        normal_temp = get_climate_normal_for_date(selected_city, run_time)

        # Temperature chart with normal line
        st.plotly_chart(
            plot_temperature_comparison(selected_city, city_latest, city_previous,
                                       is_partial=is_partial_display, available_days=available_days,
                                       normal_temp=normal_temp),
            width='stretch'
        )

        # Degree days charts
        col1, col2 = st.columns(2)
        with col1:
            st.plotly_chart(
                plot_degree_days_comparison(selected_city, city_latest, city_previous, 'hdd',
                                           is_partial=is_partial_display, available_days=available_days),
                width='stretch'
            )
        with col2:
            st.plotly_chart(
                plot_degree_days_comparison(selected_city, city_latest, city_previous, 'cdd',
                                           is_partial=is_partial_display, available_days=available_days),
                width='stretch'
            )

        # Daily breakdown table
        st.subheader(f"Daily Breakdown - {POPULATION_CENTERS[selected_city]['name']}")
        daily_df = get_daily_comparison(city_data, prev_city_data, selected_city)
        st.dataframe(daily_df, width='stretch', hide_index=True)
    else:
        st.warning(f"No data available for {POPULATION_CENTERS[selected_city]['name']}")


if __name__ == "__main__":
    main()
