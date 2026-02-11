"""Configuration for GFS Weather Model Tool - Gas-Weighted Demand Signal"""

# =============================================================================
# GAS CONSUMPTION CENTERS (10 major metros weighted by EIA 5-year avg gas consumption)
# Gas weights derived from EIA state-level residential + commercial consumption (2020-2024)
# City temperatures serve as proxies for state-level gas demand (metros drive 60-70% of state consumption)
# =============================================================================
GAS_CONSUMPTION_CENTERS = {
    # Northeast (35% of weighted demand)
    'new_york': {
        'name': 'New York',
        'lat': 40.71,
        'lon': -74.01,
        'state': 'NY',
        'region': 'northeast',
        'gas_weight': 0.185,  # EIA 5-yr avg: ~650 BCF/yr
        'description': 'NYC-Newark-Jersey City MSA'
    },
    'boston': {
        'name': 'Boston',
        'lat': 42.36,
        'lon': -71.06,
        'state': 'MA',
        'region': 'northeast',
        'gas_weight': 0.063,  # EIA 5-yr avg: ~220 BCF/yr
        'description': 'Boston-Cambridge-Newton MSA'
    },
    'philadelphia': {
        'name': 'Philadelphia',
        'lat': 39.95,
        'lon': -75.17,
        'state': 'PA',
        'region': 'northeast',
        'gas_weight': 0.100,  # EIA 5-yr avg: ~350 BCF/yr
        'description': 'Philadelphia-Camden-Wilmington MSA'
    },
    # Midwest (22% of weighted demand)
    'chicago': {
        'name': 'Chicago',
        'lat': 41.88,
        'lon': -87.63,
        'state': 'IL',
        'region': 'midwest',
        'gas_weight': 0.128,  # EIA 5-yr avg: ~450 BCF/yr
        'description': 'Chicago-Naperville-Elgin MSA'
    },
    'detroit': {
        'name': 'Detroit',
        'lat': 42.33,
        'lon': -83.05,
        'state': 'MI',
        'region': 'midwest',
        'gas_weight': 0.091,  # EIA 5-yr avg: ~320 BCF/yr
        'description': 'Detroit-Warren-Dearborn MSA'
    },
    # South (24% of weighted demand)
    'houston': {
        'name': 'Houston',
        'lat': 29.76,
        'lon': -95.37,
        'state': 'TX',
        'region': 'south',
        'gas_weight': 0.114,  # EIA 5-yr avg: ~400 BCF/yr (industrial heavy)
        'description': 'Houston-The Woodlands-Sugar Land MSA'
    },
    'dallas': {
        'name': 'Dallas',
        'lat': 32.78,
        'lon': -96.80,
        'state': 'TX',
        'region': 'south',
        'gas_weight': 0.071,  # EIA 5-yr avg: ~250 BCF/yr (residential)
        'description': 'Dallas-Fort Worth-Arlington MSA'
    },
    'atlanta': {
        'name': 'Atlanta',
        'lat': 33.75,
        'lon': -84.39,
        'state': 'GA',
        'region': 'south',
        'gas_weight': 0.057,  # EIA 5-yr avg: ~200 BCF/yr
        'description': 'Atlanta-Sandy Springs-Alpharetta MSA'
    },
    # West (19% of weighted demand)
    'denver': {
        'name': 'Denver',
        'lat': 39.74,
        'lon': -104.99,
        'state': 'CO',
        'region': 'west',
        'gas_weight': 0.048,  # EIA 5-yr avg: ~170 BCF/yr
        'description': 'Denver-Aurora-Lakewood MSA'
    },
    'los_angeles': {
        'name': 'Los Angeles',
        'lat': 34.05,
        'lon': -118.24,
        'state': 'CA',
        'region': 'west',
        'gas_weight': 0.142,  # EIA 5-yr avg: ~500 BCF/yr
        'description': 'Los Angeles-Long Beach-Anaheim MSA'
    }
}

# Alias for backward compatibility
POPULATION_CENTERS = GAS_CONSUMPTION_CENTERS

# =============================================================================
# REGIONAL DEFINITIONS (2-3 representative cities per region)
# =============================================================================
REGIONS = {
    'northeast': {
        'name': 'Northeast',
        'description': 'High winter heating demand region',
        'cities': ['new_york', 'boston', 'philadelphia']
    },
    'midwest': {
        'name': 'Midwest',
        'description': 'Significant winter heating, moderate summer cooling',
        'cities': ['chicago', 'detroit']
    },
    'south': {
        'name': 'South',
        'description': 'High summer cooling, moderate winter heating',
        'cities': ['houston', 'dallas', 'atlanta']
    },
    'west': {
        'name': 'West',
        'description': 'Mountain and coastal climate mix',
        'cities': ['denver', 'los_angeles']
    }
}

# =============================================================================
# CLIMATE NORMALS (30-year monthly averages, NOAA 1991-2020)
# Values are average daily temperatures in °F
# Used to calculate forecast deviation from normal
# =============================================================================
CLIMATE_NORMALS = {
    # Northeast - New York
    'new_york': {
        'jan': 33.0, 'feb': 35.5, 'mar': 43.5, 'apr': 54.0, 'may': 63.5, 'jun': 72.5,
        'jul': 77.5, 'aug': 76.0, 'sep': 69.0, 'oct': 57.5, 'nov': 47.5, 'dec': 37.5
    },
    # Northeast - Boston
    'boston': {
        'jan': 30.0, 'feb': 32.0, 'mar': 40.0, 'apr': 50.0, 'may': 60.0, 'jun': 70.0,
        'jul': 75.5, 'aug': 74.5, 'sep': 67.0, 'oct': 56.0, 'nov': 45.5, 'dec': 35.0
    },
    # Northeast - Philadelphia
    'philadelphia': {
        'jan': 33.5, 'feb': 36.0, 'mar': 44.5, 'apr': 55.0, 'may': 65.0, 'jun': 74.0,
        'jul': 79.0, 'aug': 77.5, 'sep': 70.5, 'oct': 58.5, 'nov': 48.0, 'dec': 38.0
    },
    # Midwest - Chicago
    'chicago': {
        'jan': 26.0, 'feb': 29.5, 'mar': 40.0, 'apr': 51.0, 'may': 62.0, 'jun': 72.0,
        'jul': 76.5, 'aug': 75.0, 'sep': 67.5, 'oct': 55.0, 'nov': 42.5, 'dec': 30.5
    },
    # Midwest - Detroit
    'detroit': {
        'jan': 25.5, 'feb': 27.5, 'mar': 37.0, 'apr': 49.0, 'may': 60.5, 'jun': 70.0,
        'jul': 74.0, 'aug': 72.5, 'sep': 65.0, 'oct': 53.0, 'nov': 41.5, 'dec': 30.0
    },
    # South - Houston
    'houston': {
        'jan': 53.0, 'feb': 56.5, 'mar': 63.0, 'apr': 69.5, 'may': 77.0, 'jun': 82.5,
        'jul': 85.0, 'aug': 85.0, 'sep': 80.5, 'oct': 72.0, 'nov': 62.5, 'dec': 54.5
    },
    # South - Dallas
    'dallas': {
        'jan': 46.0, 'feb': 50.0, 'mar': 58.0, 'apr': 66.0, 'may': 74.5, 'jun': 82.5,
        'jul': 86.0, 'aug': 86.5, 'sep': 79.0, 'oct': 68.0, 'nov': 56.5, 'dec': 47.0
    },
    # South - Atlanta
    'atlanta': {
        'jan': 43.5, 'feb': 47.5, 'mar': 54.5, 'apr': 62.5, 'may': 70.5, 'jun': 78.0,
        'jul': 81.0, 'aug': 80.5, 'sep': 74.5, 'oct': 64.0, 'nov': 53.5, 'dec': 45.0
    },
    # West - Denver
    'denver': {
        'jan': 34.5, 'feb': 36.0, 'mar': 43.5, 'apr': 49.5, 'may': 58.5, 'jun': 68.5,
        'jul': 74.0, 'aug': 72.0, 'sep': 64.0, 'oct': 52.0, 'nov': 41.5, 'dec': 33.5
    },
    # West - Los Angeles
    'los_angeles': {
        'jan': 58.0, 'feb': 59.0, 'mar': 60.5, 'apr': 62.5, 'may': 65.5, 'jun': 69.0,
        'jul': 73.0, 'aug': 74.0, 'sep': 73.0, 'oct': 68.5, 'nov': 62.5, 'dec': 57.5
    }
}

# =============================================================================
# GFS DATA CONFIGURATION
# =============================================================================
# Geographic bounds for GFS data fetch
# Minimal bounding box covering all 10 gas consumption centers with 1° buffer:
# - Northernmost: Boston (42.36°N)
# - Southernmost: Houston (29.76°N)
# - Westernmost: Los Angeles (-118.24°W)
# - Easternmost: Boston (-71.06°W)
GFS_BOUNDS = {
    'lat': (28.5, 43.5),      # Houston to Boston with buffer
    'lon': (-119.5, -70.0)    # Los Angeles to Boston with buffer
}

# Degree day base temperatures (°F)
HDD_BASE = 65
CDD_BASE = 65

# Forecast configuration
# Using GFS 0.5 degree product (pgrb2.0p50) which provides forecasts out to 384 hours (16 days)
# Note: Using 14 days (336 hours) for reliability - some runs may not have hours 354+ available immediately
FORECAST_DAYS = 16

# Data storage
DATA_DIR = './data'
CACHE_HOURS = 6
MAX_STORED_RUNS = 10

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def get_all_locations():
    """Return dictionary of all gas consumption centers."""
    return GAS_CONSUMPTION_CENTERS.copy()

def get_total_gas_weight():
    """Return total gas weight across all centers (should sum to ~1.0)."""
    return sum(city['gas_weight'] for city in GAS_CONSUMPTION_CENTERS.values())

def get_region_gas_weight(region_id):
    """Return total gas weight for a specific region."""
    if region_id not in REGIONS:
        return 0
    cities = REGIONS[region_id]['cities']
    return sum(GAS_CONSUMPTION_CENTERS[city]['gas_weight'] for city in cities if city in GAS_CONSUMPTION_CENTERS)

# Backward compatibility aliases
def get_total_population():
    """Alias for get_total_gas_weight for backward compatibility."""
    return get_total_gas_weight()

def get_region_population(region_id):
    """Alias for get_region_gas_weight for backward compatibility."""
    return get_region_gas_weight(region_id)
