# GFS Weather Model - Natural Gas Hub Analysis

A Streamlit application that fetches GFS weather model data for key natural gas trading hubs, calculates Heating Degree Days (HDD) and Cooling Degree Days (CDD), and compares forecast changes between model runs.

## Features

- **Real-time GFS Data**: Fetches latest GFS forecast data from NOMADS/AWS
- **Hub-Specific Analysis**: Tracks three key natural gas trading hubs:
  - Henry Hub (Louisiana) - NYMEX pricing benchmark
  - Waha Hub (West Texas) - Permian Basin
  - Houston Ship Channel (Gulf Coast)
- **Degree Day Calculations**: Computes HDD and CDD with 65°F base temperature
- **Run Comparison**: Compares latest vs previous GFS run to identify forecast changes
- **Interactive Visualizations**: Charts showing temperatures, degree days, and cross-hub comparisons
- **14-Day Forecast**: Full 14-day outlook for each hub (GFS 0.5° resolution)
- **Smart Data Fetching**: Auto-detects available runs and falls back if newest isn't ready

## Installation

1. Clone or download this repository

2. Install dependencies:
```bash
pip install -r requirements.txt
```

**Windows Users**: If you encounter issues with cfgrib, you may need to install eccodes:
```bash
conda install -c conda-forge eccodes
```

### Requirements
- Python 3.8+
- herbie-data (for GFS data access)
- xarray & cfgrib (for GRIB2 file handling)
- streamlit (web app framework)
- plotly (interactive charts)
- pandas & numpy (data processing)

## Usage

Run the Streamlit app:

```bash
streamlit run app.py
```

The app will:
1. Check for cached GFS data
2. Fetch latest GFS forecast from NOMADS/AWS if needed
3. Extract temperatures at each hub location
4. Calculate HDD/CDD for 14-day forecast
5. Compare with previous model run (if available)
6. Display interactive dashboard with charts and tables

### Refreshing Data

Click the "Refresh Data" button in the sidebar to fetch the latest model run. The app will:
1. Try the newest possible run first
2. Automatically fall back to previous runs if not yet available
3. Only display complete 14-day forecasts (no partial data)

## GFS Model Availability Schedule

GFS runs 4 times daily. Data typically becomes available ~3-3.5 hours after initialization:

| Run | Init (UTC) | Available (UTC) | Central Standard Time |
|-----|------------|-----------------|----------------------|
| 00z | 00:00 | ~03:00-03:30 | ~9:00-9:30 PM (prev day) |
| 06z | 06:00 | ~09:00-09:30 | ~3:00-3:30 AM |
| 12z | 12:00 | ~15:00-15:30 | ~9:00-9:30 AM |
| 18z | 18:00 | ~21:00-21:30 | ~3:00-3:30 PM |

**Notes:**
- Add 1 hour for Central Daylight Time (CDT)
- Early forecast hours (days 1-5) may be available slightly earlier
- NOMADS can occasionally be delayed during high traffic

## Sharing the App

### Option 1: Share Code (Simplest)

Share the entire `Weather_Model` folder with recipients. They'll need to:

```bash
# 1. Install Python 3.8+ from python.org
# 2. Open terminal in the Weather_Model folder
# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py

# 5. Opens in browser at http://localhost:8501
```

### Option 2: Streamlit Community Cloud (Public URL)

1. Push your code to a public GitHub repository
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Deploy and get a public URL like `yourapp.streamlit.app`

**Note:** Free tier apps are public. For private access, you'd need Streamlit Teams.

### Option 3: Local Network

Run on your machine and share with others on the same WiFi:
```bash
streamlit run app.py --server.address 0.0.0.0
```
Share your local IP (e.g., `http://192.168.1.100:8501`)

### Option 4: Temporary Public Access (ngrok)

```bash
pip install pyngrok
ngrok http 8501
```
Get a temporary public URL for demos.

## Project Structure

```
Weather_Model/
├── app.py                          # Main Streamlit application
├── requirements.txt                # Python dependencies
├── README.md                       # This file
├── data/                          # Local storage for model runs
│   └── gfs_YYYYMMDD_HH.json       # Cached model run data
└── src/
    ├── config.py                  # Hub configurations and settings
    ├── data/
    │   ├── gfs_fetcher.py        # Fetch GFS data from NOMADS/AWS
    │   └── storage.py            # Save/load model runs
    └── calculations/
        ├── point_extraction.py   # Extract temps at hub locations
        ├── degree_days.py        # HDD/CDD calculations
        └── comparison.py         # Compare model runs
```

## Configuration

Edit `src/config.py` to customize:
- Hub locations (lat/lon coordinates)
- HDD/CDD base temperatures (default: 65°F)
- Forecast range (default: 14 days)
- Data storage settings

## How It Works

### Data Flow

1. **Availability Check**: Quick check if newest GFS run is available (tests hour 0)
2. **Auto-Fallback**: If not available, automatically tries previous runs (up to 24 hours back)
3. **GFS Data Fetching**: Downloads 2m temperature data from NOMADS (primary) or AWS (backup)
4. **Completeness Check**: Requires 95%+ of forecast hours before accepting data
5. **Point Extraction**: Extracts temperature at exact hub coordinates (nearest grid point)
6. **Daily Averaging**: Converts 6-hourly GFS output to daily average temperatures
7. **Degree Days**: Calculates HDD = max(0, 65 - temp) and CDD = max(0, temp - 65)
8. **Storage**: Saves complete results to JSON files in `data/` directory
9. **Comparison**: Loads previous run and computes differences
10. **Visualization**: Displays results in interactive Streamlit dashboard

### Data Sources

- **Primary**: NOAA NOMADS (typically faster)
- **Backup**: AWS Open Data
- **Resolution**: GFS 0.5° (~50km grid spacing)
- **Forecast Range**: 14 days (336 hours)

## Dashboard Features

- **Hub Comparison Dashboard**: Side-by-side HDD/CDD totals with change indicators
  - Green arrows = upward revision
  - Red arrows = downward revision
- **Summary Table**: All hubs with current and previous values
- **Cross-Hub Charts**: Bar charts comparing total HDD/CDD across hubs
- **Detailed Analysis**: Per-hub temperature and degree day charts
- **Daily Breakdown**: Table showing day-by-day forecast values

## Use Cases

This tool is designed for natural gas market analysis:

- **Basis Trading**: Compare weather forecasts at different hubs to identify basis differentials
- **Demand Forecasting**: HDD/CDD correlate with heating and cooling demand
- **Forecast Changes**: Track how weather model runs evolve to anticipate price movements
- **Regional Analysis**: Compare weather patterns across TX/LA producing and consuming regions

## Troubleshooting

### "No index file was found" Error
The GFS run isn't available yet. The app will automatically try previous runs.

### Partial Data / Length Mismatch
Old cached data may be incomplete. Delete files in `data/` folder and refresh.

### cfgrib Installation Issues (Windows)
Install eccodes via conda: `conda install -c conda-forge eccodes`

### Slow Initial Load
First fetch downloads ~57 GRIB files. Subsequent loads use cached data.

## Future Enhancements

- Option to switch between 0.25° (higher resolution, 10 days) and 0.5° (current, 14 days) products
- Add ECMWF model support
- Historical trend analysis
- Email alerts for significant forecast changes
- CSV/Excel export functionality
- Additional hub locations
- Ensemble forecast support


## Notes

- First run may take a few minutes to download GFS data (~57 forecast hours)
- Data is cached locally to improve performance
- Internet connection required for GFS data access
- Storage directory keeps last 10 model runs (configurable in `src/config.py`)
- App requires complete 14-day forecast before displaying (no partial data)
