"""Streamlit app for GFS Weather Model Analysis"""

import time
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import pandas as pd

from src.data.gfs_fetcher import (
    fetch_gfs_temperature, get_latest_gfs_run, get_newest_possible_run,
    fetch_gfs_partial, is_in_publishing_window, FetchResult, get_previous_gfs_run
)
from src.data.storage import (
    save_model_run, get_previous_run_data, get_latest_saved_run,
    save_partial_run, load_partial_run, delete_partial_run, promote_partial_to_complete,
    load_model_run
)
from src.calculations.point_extraction import extract_hub_temperatures
from src.calculations.degree_days import calculate_all_hubs_degree_days
from src.calculations.comparison import compare_runs, create_comparison_dataframe, get_daily_comparison
from src.config import HUBS, FORECAST_DAYS

# Try to import autorefresh, but make it optional
try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:
    AUTOREFRESH_AVAILABLE = False
    st_autorefresh = None  # type: ignore


# Page configuration
st.set_page_config(
    page_title="GFS Weather Model - Natural Gas Hub Analysis",
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
AUTO_REFRESH_PUBLISHING_MS = 10 * 60 * 1000  # 10 minutes during publishing window
# No auto-refresh outside publishing window (data is static)


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
        tuple: (actual_run_time, hub_data)
    """
    run_time = datetime.fromisoformat(run_time_str)

    with st.spinner('Fetching GFS data from AWS...'):
        gfs_data = fetch_gfs_temperature(run_time, forecast_hours=FORECAST_DAYS * 24)

    # Get the ACTUAL run time from fetched data (may differ if fallback occurred)
    actual_run_time = datetime.fromisoformat(gfs_data.attrs['run_time'])

    with st.spinner('Extracting hub temperatures...'):
        hub_temps = extract_hub_temperatures(gfs_data)

    with st.spinner('Calculating degree days...'):
        hub_data = calculate_all_hubs_degree_days(hub_temps)

    # Save to disk using ACTUAL run time (not requested time)
    save_model_run(actual_run_time, hub_data)

    return actual_run_time, hub_data


def fetch_and_process_partial(run_time: datetime) -> tuple:
    """
    Fetch whatever GFS data is available and process it (partial allowed).
    Supports resuming from previously fetched hours to avoid re-fetching.

    Args:
        run_time: GFS run timestamp

    Returns:
        tuple: (FetchResult, hub_data or None)
    """
    # Check for existing partial data to resume from
    run_key = run_time.isoformat()
    existing_data = None
    start_hour = 0

    # Check session state for raw xarray data from this run
    partial_data_key = f'partial_xarray_{run_key}'
    if partial_data_key in st.session_state:
        existing_data = st.session_state[partial_data_key]
        # Get last fetched hour from the data attributes
        start_hour = existing_data.attrs.get('last_fetched_hour', 0)
        if start_hour > 0:
            # Move to next hour (6-hour intervals)
            start_hour = start_hour + 6

    result = fetch_gfs_partial(
        run_time,
        forecast_hours=FORECAST_DAYS * 24,
        start_hour=start_hour,
        existing_data=existing_data
    )

    if result.data is None or result.hours_fetched == 0:
        return result, None

    # Store raw xarray data in session state for resume capability
    st.session_state[partial_data_key] = result.data

    # Process available data
    hub_temps = extract_hub_temperatures(result.data)
    hub_data = calculate_all_hubs_degree_days(hub_temps)

    # Get last fetched hour from result data
    last_fetched_hour = result.data.attrs.get('last_fetched_hour', 0)

    # Verify actual days in processed hub data (may differ from FetchResult estimate)
    actual_days = len(next(iter(hub_data.values()))['daily_temps'])
    truly_complete = result.is_complete and actual_days >= FORECAST_DAYS

    # Save partial or complete
    if truly_complete:
        promote_partial_to_complete(run_time, hub_data)
        # Clean up session state
        if partial_data_key in st.session_state:
            del st.session_state[partial_data_key]
    else:
        save_partial_run(
            run_time, hub_data,
            result.percent_complete,
            result.hours_fetched,
            result.hours_expected,
            last_fetched_hour
        )

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

    return corrected_result, hub_data


def merge_partial_with_cached(partial_data: dict, cached_data: dict, available_days: int) -> dict:
    """
    Merge partial new data with cached complete data.
    Shows new data for available days, cached data for remaining days.

    Args:
        partial_data: Partial hub data from new run
        cached_data: Complete hub data from cached run
        available_days: Number of days available in partial data

    Returns:
        dict: Merged hub data for display
    """
    merged = {}

    for hub_id in partial_data.keys():
        partial_hub = partial_data[hub_id]
        cached_hub = cached_data.get(hub_id, {})

        merged[hub_id] = {
            'daily_temps': [],
            'hdd': [],
            'cdd': [],
            'hdd_cumulative': [],
            'cdd_cumulative': [],
            'is_partial': [],  # Track which days are from partial vs cached
        }

        for day in range(FORECAST_DAYS):
            if day < available_days and day < len(partial_hub.get('daily_temps', [])):
                # Use partial data
                merged[hub_id]['daily_temps'].append(partial_hub['daily_temps'][day])
                merged[hub_id]['hdd'].append(partial_hub['hdd'][day])
                merged[hub_id]['cdd'].append(partial_hub['cdd'][day])
                merged[hub_id]['is_partial'].append(True)
            elif day < len(cached_hub.get('daily_temps', [])):
                # Use cached data
                merged[hub_id]['daily_temps'].append(cached_hub['daily_temps'][day])
                merged[hub_id]['hdd'].append(cached_hub['hdd'][day])
                merged[hub_id]['cdd'].append(cached_hub['cdd'][day])
                merged[hub_id]['is_partial'].append(False)
            else:
                # No data available
                merged[hub_id]['daily_temps'].append(None)
                merged[hub_id]['hdd'].append(None)
                merged[hub_id]['cdd'].append(None)
                merged[hub_id]['is_partial'].append(False)

        # Recalculate cumulative values
        hdd_cum = 0
        cdd_cum = 0
        for hdd, cdd in zip(merged[hub_id]['hdd'], merged[hub_id]['cdd']):
            if hdd is not None:
                hdd_cum += hdd
            if cdd is not None:
                cdd_cum += cdd
            merged[hub_id]['hdd_cumulative'].append(hdd_cum)
            merged[hub_id]['cdd_cumulative'].append(cdd_cum)

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


def plot_temperature_comparison(hub_id: str, latest_data: dict, previous_data: dict = None,
                                is_partial: bool = False, available_days: int = None):
    """Create temperature comparison chart with partial data support"""
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

    title = f"Daily Average Temperature - {HUBS[hub_id]['name']}"
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


def plot_degree_days_comparison(hub_id: str, latest_data: dict, previous_data: dict = None,
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

    title = f"Daily {metric_name} - {HUBS[hub_id]['name']}"
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


def plot_cumulative_degree_days(hub_id: str, latest_data: dict, previous_data: dict = None):
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

    fig.update_layout(
        title=f"Cumulative Degree Days - {HUBS[hub_id]['name']}",
        xaxis_title="Forecast Day",
        yaxis_title="Cumulative Degree Days",
        hovermode='x unified',
        height=400
    )

    return fig


def plot_cross_hub_comparison(hub_data_dict: dict, metric: str = 'hdd'):
    """Create cross-hub comparison chart"""
    hub_names = [HUBS[hub_id]['name'] for hub_id in hub_data_dict.keys()]
    totals = [sum(data[metric]) for data in hub_data_dict.values()]

    metric_name = "HDD" if metric == 'hdd' else "CDD"
    color = '#1f77b4' if metric == 'hdd' else '#d62728'

    fig = go.Figure(data=[
        go.Bar(x=hub_names, y=totals, marker_color=color)
    ])

    fig.update_layout(
        title=f"{FORECAST_DAYS}-Day Total {metric_name} - Hub Comparison",
        xaxis_title="Hub",
        yaxis_title=f"Total {metric_name}",
        height=400
    )

    return fig


# Main app
def main():
    # Check if we're in a publishing window for any run
    newest_run = get_newest_possible_run()
    in_publishing = is_in_publishing_window(newest_run)

    # Track if current run is complete (will be set later, used for auto-refresh decision)
    run_is_complete = False

    # Initialize session state
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'current_run_time' not in st.session_state:
        st.session_state.current_run_time = None
    if 'is_loading_partial' not in st.session_state:
        st.session_state.is_loading_partial = False

    st.title("GFS Weather Model")
    st.markdown("**Heating and Cooling Degree Days for Natural Gas Trading Hubs**")

    # Get cached data first
    latest_saved = get_latest_saved_run()
    cached_hub_data = latest_saved['hubs'] if latest_saved else None
    cached_run_time = datetime.fromisoformat(latest_saved['run_time']) if latest_saved else None

    # Check for partial run in progress
    partial_run = load_partial_run(newest_run) if in_publishing else None

    # Sidebar
    with st.sidebar:
        st.header("Settings")

        # Refresh button
        refresh_clicked = st.button("Refresh Data", use_container_width=True)

        if refresh_clicked:
            st.cache_data.clear()
            delete_partial_run(newest_run)  # Clear any partial data to force re-fetch
            # Clear session state for partial xarray data
            partial_key = f'partial_xarray_{newest_run.isoformat()}'
            if partial_key in st.session_state:
                del st.session_state[partial_key]
            # Clear session cache for hub data (to force refetch)
            session_cache_key = f'session_hub_data_{newest_run.isoformat()}'
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
                <span style="font-size: 0.8em; color: #15803d;">Auto-refresh: 10 min</span>
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
            st.markdown("""
            <div class="status-idle">
                <strong>IDLE</strong><br/>
                <span style="font-size: 0.9em;">No active publishing</span>
            </div>
            """, unsafe_allow_html=True)
            if not AUTOREFRESH_AVAILABLE:
                st.warning("Install `streamlit-autorefresh` for auto-updates")

        st.markdown("---")
        st.markdown("### Live Update Windows (CST)")
        st.markdown("""
        | Run | Window |
        |-----|--------|
        | 00z | 8:30 PM - 12:00 AM* |
        | 06z | 2:30 AM - 6:00 AM |
        | 12z | 8:30 AM - 12:00 PM |
        | 18z | 2:30 PM - 6:00 PM |

        *Previous day. Add 1hr for CDT.
        """)

        st.markdown("---")
        st.markdown("### About")
        st.markdown("""
        This tool analyzes GFS weather model forecasts for three key natural gas trading hubs:
        - **Henry Hub** (Louisiana) - NYMEX benchmark
        - **Waha Hub** (West Texas) - Permian Basin
        - **Houston Ship Channel** - Gulf Coast

        **Metrics:**
        - HDD (Heating Degree Days): Base 65°F
        - CDD (Cooling Degree Days): Base 65°F
        - 14-day forecast range (GFS 0.5° product)
        """)

    # Determine what to display based on state
    run_time = None
    latest_hub_data = None
    is_partial_display = False
    available_days = FORECAST_DAYS

    # Check if this is an auto-refresh or force refresh (vs just a UI interaction like hub change)
    # Auto-refresh sets a query param, force_fetch is set by button click
    # Use pop() to clear the flag after reading it (prevents repeated refetches)
    is_refresh_trigger = st.session_state.pop('force_fetch', False)

    # During publishing window, try to fetch partial data
    if in_publishing:
        # FIRST: Ensure immediate previous run is cached for comparison
        previous_run_time = get_previous_gfs_run(newest_run)
        previous_run_cached = load_model_run(previous_run_time)

        # Check if cached data is the immediate previous run
        cached_is_previous = (cached_run_time == previous_run_time) if cached_run_time else False

        if previous_run_cached is None and not cached_is_previous:
            # Previous run not specifically cached - need to fetch it
            st.info(f"Fetching previous run ({format_zulu(previous_run_time)}) for comparison...")
            try:
                with st.spinner(f"Fetching {format_zulu(previous_run_time)}..."):
                    _, prev_hub_data = fetch_and_process_gfs_data(previous_run_time.isoformat())
                    # Update cached data references to use the previous run
                    cached_hub_data = prev_hub_data
                    cached_run_time = previous_run_time
                    latest_saved = {'run_time': previous_run_time.isoformat(), 'hubs': prev_hub_data}
                st.success(f"Previous run cached: {format_zulu(previous_run_time)}")
            except Exception as e:
                st.warning(f"Could not fetch previous run: {e}")
                # Continue with whatever cached data we have (if any)

        # Check if we already have session-cached data for this run (avoid refetch on hub change)
        session_cache_key = f'session_hub_data_{newest_run.isoformat()}'
        session_result_key = f'session_fetch_result_{newest_run.isoformat()}'
        session_fetch_time_key = f'session_fetch_time_{newest_run.isoformat()}'

        # Determine if we need to fetch: first load, auto-refresh interval elapsed, or force refresh
        have_session_cache = session_cache_key in st.session_state and st.session_state[session_cache_key] is not None

        # Use timestamp to detect auto-refresh vs UI interaction (like hub change)
        # Auto-refresh is 10 minutes, so if less than 5 minutes have passed, it's just a UI interaction
        current_time = time.time()
        last_fetch_time = st.session_state.get(session_fetch_time_key, 0)
        time_since_fetch = current_time - last_fetch_time
        min_refresh_interval = 5 * 60  # 5 minutes - less than auto-refresh interval

        # Only consider it an auto-refresh if enough time has passed
        is_auto_refresh = time_since_fetch >= min_refresh_interval

        # Check if the cached result is already complete (no need to refetch if complete)
        cached_is_complete = (session_result_key in st.session_state and
                              st.session_state[session_result_key].get('is_complete', False))

        need_fetch = not have_session_cache or (is_auto_refresh and not cached_is_complete) or is_refresh_trigger

        if need_fetch:
            # Fetch whatever is available
            with st.spinner("Checking for new data..."):
                fetch_result, partial_hub_data = fetch_and_process_partial(newest_run)

            # Cache in session state for subsequent reruns (like hub selection changes)
            st.session_state[session_cache_key] = partial_hub_data
            st.session_state[session_result_key] = {
                'is_complete': fetch_result.is_complete,
                'percent_complete': fetch_result.percent_complete,
                'available_days': fetch_result.available_days,
                'hours_fetched': fetch_result.hours_fetched
            }
            # Record fetch timestamp to distinguish auto-refresh from UI interactions
            st.session_state[session_fetch_time_key] = current_time
        else:
            # Use session-cached data (no refetch needed)
            partial_hub_data = st.session_state[session_cache_key]
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
            latest_hub_data = partial_hub_data
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

        elif partial_hub_data is not None:
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

            if cached_hub_data:
                # Merge partial with cached
                run_time = newest_run
                latest_hub_data = merge_partial_with_cached(
                    partial_hub_data, cached_hub_data, fetch_result.available_days
                )
                is_partial_display = True
                available_days = fetch_result.available_days
                st.info(f"Showing days 1-{available_days} from **{format_zulu(newest_run)}** | "
                       f"Days {available_days + 1}-{FORECAST_DAYS} from **{format_zulu(cached_run_time)}**")
            else:
                # No cached data, just show partial
                run_time = newest_run
                latest_hub_data = partial_hub_data
                is_partial_display = True
                available_days = fetch_result.available_days
                st.warning(f"Partial data: {available_days} of {FORECAST_DAYS} days available")
        else:
            # No data from new run yet
            st.warning(f"{format_zulu(newest_run)} not yet available. Waiting...")

            if cached_hub_data:
                run_time = cached_run_time
                latest_hub_data = cached_hub_data
                st.info(f"Displaying cached run: {format_zulu(cached_run_time)}")
            else:
                st.error("No cached data available. Please wait for data to become available.")
                st.stop()

        st.markdown("---")

        # Auto-refresh only if still loading (not complete)
        if AUTOREFRESH_AVAILABLE and st_autorefresh is not None and not run_is_complete:
            st_autorefresh(
                interval=AUTO_REFRESH_PUBLISHING_MS,
                limit=None,
                key="gfs_autorefresh"
            )

    elif cached_hub_data:
        # Not in publishing window, use cached data OR fetch if user requested refresh
        conservative_run = get_latest_gfs_run()
        fetched_something = False

        run_time = cached_run_time
        latest_hub_data = cached_hub_data

        if is_refresh_trigger:
            st.markdown("---")

            # Step 1: Fetch newer run if available
            if cached_run_time != conservative_run:
                st.markdown("## Fetching Latest GFS Data")
                st.markdown(f"**Target run:** {format_zulu(conservative_run)}")

                try:
                    with st.spinner(f"Fetching {format_zulu(conservative_run)}..."):
                        run_time, latest_hub_data = fetch_and_process_gfs_data(conservative_run.isoformat())
                    st.success(f"Fetched GFS run: {format_zulu(run_time)}")
                    fetched_something = True
                    # Update cached references for next check
                    cached_run_time = run_time
                    cached_hub_data = latest_hub_data
                except Exception as e:
                    st.error(f"Failed to fetch: {e}")

            # Step 2: Check if previous run for comparison is missing
            previous_run_time = get_previous_gfs_run(cached_run_time)
            previous_run_cached = load_model_run(previous_run_time)

            if previous_run_cached is None:
                st.markdown("## Fetching Previous Run for Comparison")
                st.markdown(f"**Target run:** {format_zulu(previous_run_time)}")

                try:
                    with st.spinner(f"Fetching {format_zulu(previous_run_time)}..."):
                        _, _ = fetch_and_process_gfs_data(previous_run_time.isoformat())
                    st.success(f"Fetched previous run: {format_zulu(previous_run_time)}")
                    fetched_something = True
                except Exception as e:
                    st.error(f"Failed to fetch previous run: {e}")

            if fetched_something:
                st.rerun()  # Rerun to display fresh data
            else:
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
                run_time, latest_hub_data = fetch_and_process_gfs_data(conservative_run.isoformat())
                progress_bar.progress(100, text="Complete!")
                st.success(f"Fetched GFS run: {format_zulu(run_time)}")
                st.rerun()
            except Exception as e:
                progress_bar.progress(100, text="Failed!")
                st.error(f"Failed to fetch GFS data: {e}")
                st.warning("Please try again later or check your internet connection.")
                st.stop()

    # Load previous run for comparison (use cached complete run if showing partial)
    if is_partial_display and cached_hub_data:
        # For partial display, compare to the cached run
        previous_hub_data = cached_hub_data
        previous_run_raw = latest_saved
    else:
        previous_run_raw = get_previous_run_data(run_time)
        previous_hub_data = previous_run_raw['hubs'] if previous_run_raw else None

    # Display model run info
    col1, col2, col3 = st.columns(3)
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

    st.markdown("---")

    # Hub comparison dashboard
    st.header("Hub Comparison Dashboard")

    comparison_data = compare_runs(latest_hub_data, previous_hub_data)

    cols = st.columns(3)

    for idx, (hub_id, hub_info) in enumerate(HUBS.items()):
        with cols[idx]:
            st.subheader(hub_info['name'])
            st.caption(hub_info['location'])

            comp = comparison_data[hub_id]

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
    comparison_df = create_comparison_dataframe(comparison_data)
    st.dataframe(comparison_df, width='stretch', hide_index=True)

    st.markdown("---")

    # Cross-hub comparison
    st.header("Cross-Hub Comparison")

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(plot_cross_hub_comparison(latest_hub_data, 'hdd'),
                       width='stretch')
    with col2:
        st.plotly_chart(plot_cross_hub_comparison(latest_hub_data, 'cdd'),
                       width='stretch')

    st.markdown("---")

    # Detailed hub views
    st.header("Detailed Hub Analysis")

    selected_hub = st.selectbox(
        "Select hub for detailed view:",
        options=list(HUBS.keys()),
        format_func=lambda x: HUBS[x]['name']
    )

    hub_latest = latest_hub_data[selected_hub]
    hub_previous = previous_hub_data[selected_hub] if previous_hub_data else None

    # Temperature chart
    st.plotly_chart(
        plot_temperature_comparison(selected_hub, hub_latest, hub_previous,
                                   is_partial=is_partial_display, available_days=available_days),
        width='stretch'
    )

    # Degree days charts
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            plot_degree_days_comparison(selected_hub, hub_latest, hub_previous, 'hdd',
                                       is_partial=is_partial_display, available_days=available_days),
            width='stretch'
        )
    with col2:
        st.plotly_chart(
            plot_degree_days_comparison(selected_hub, hub_latest, hub_previous, 'cdd',
                                       is_partial=is_partial_display, available_days=available_days),
            width='stretch'
        )

    # Cumulative chart
    st.plotly_chart(
        plot_cumulative_degree_days(selected_hub, hub_latest, hub_previous),
        width='stretch'
    )

    # Daily breakdown table
    st.subheader(f"Daily Breakdown - {HUBS[selected_hub]['name']}")
    daily_df = get_daily_comparison(latest_hub_data, previous_hub_data, selected_hub)
    st.dataframe(daily_df, width='stretch', hide_index=True)


if __name__ == "__main__":
    main()
