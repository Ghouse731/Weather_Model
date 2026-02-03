"""Configuration for GFS Weather Model Tool"""

HUBS = {
    'henry_hub': {
        'name': 'Henry Hub',
        'lat': 29.95,
        'lon': -92.05,
        'location': 'Erath, Louisiana',
        'description': 'NYMEX pricing benchmark'
    },
    'waha_hub': {
        'name': 'Waha Hub',
        'lat': 31.85,
        'lon': -103.08,
        'location': 'West Texas (Permian Basin)',
        'description': 'West Texas trading hub'
    },
    'houston_ship_channel': {
        'name': 'Houston Ship Channel',
        'lat': 29.76,
        'lon': -95.37,
        'location': 'Houston, Texas',
        'description': 'Gulf Coast trading hub'
    }
}

# Geographic bounds for GFS data fetch (covers all hubs)
GFS_BOUNDS = {
    'lat': (29.0, 32.0),
    'lon': (-104.0, -92.0)
}

# Degree day base temperatures (°F)
HDD_BASE = 65
CDD_BASE = 65

# Forecast configuration
# Using GFS 0.5 degree product (pgrb2.0p50) which provides forecasts out to 384 hours (16 days)
# Note: Using 14 days (336 hours) for reliability - some runs may not have hours 354+ available immediately
FORECAST_DAYS = 14

# Data storage
DATA_DIR = './data'
CACHE_HOURS = 6
MAX_STORED_RUNS = 10
