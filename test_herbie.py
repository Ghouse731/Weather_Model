"""Test script to diagnose Herbie GFS data fetching"""

from datetime import datetime, timedelta
from herbie import Herbie

print("Testing Herbie GFS data access...")
print("=" * 60)

# Try to get latest GFS run
now = datetime.utcnow()
print(f"Current UTC time: {now}")

# Calculate latest run time
run_hours = [0, 6, 12, 18]
current_hour = now.hour
latest_run_hour = max([h for h in run_hours if h <= current_hour], default=18)

if current_hour < run_hours[0]:
    run_time = now.replace(hour=18, minute=0, second=0, microsecond=0) - timedelta(days=1)
else:
    run_time = now.replace(hour=latest_run_hour, minute=0, second=0, microsecond=0)

print(f"Latest GFS run time: {run_time}")
print("=" * 60)

# Try to fetch a single forecast hour (0)
print("\nAttempting to fetch forecast hour 0...")

try:
    H = Herbie(
        date=run_time,
        model='gfs',
        product='pgrb2.0p25',
        fxx=0,
        verbose=False
    )

    print("SUCCESS: Herbie object created successfully")
    print(f"  File: {H.grib}")

    # Try to download
    print("\nAttempting to download TMP:2 m data...")
    ds = H.xarray('TMP:2 m', remove_grib=True)

    # Handle list vs Dataset
    if isinstance(ds, list):
        print(f"  Returned list with {len(ds)} items")
        ds = ds[0]  # Take first dataset

    print("SUCCESS: Data downloaded successfully!")
    print(f"  Dataset shape: {ds.dims}")
    print(f"  Variables: {list(ds.data_vars)}")
    print(f"  Coordinates: {list(ds.coords)}")

except Exception as e:
    print(f"ERROR: {e}")
    print(f"  Type: {type(e).__name__}")
    import traceback
    traceback.print_exc()

    # Try alternative approach - maybe the run isn't ready yet
    print("\n" + "=" * 60)
    print("Trying previous GFS run (6 hours earlier)...")

    prev_run_time = run_time - timedelta(hours=6)
    print(f"Previous run time: {prev_run_time}")

    try:
        H = Herbie(
            date=prev_run_time,
            model='gfs',
            product='pgrb2.0p25',
            fxx=0,
            verbose=False
        )

        print("SUCCESS: Herbie object created for previous run")
        ds = H.xarray('TMP:2 m', remove_grib=True)

        # Handle list vs Dataset
        if isinstance(ds, list):
            print(f"  Returned list with {len(ds)} items")
            ds = ds[0]

        print("SUCCESS: Previous run data downloaded!")
        print(f"  Dataset shape: {ds.dims}")

    except Exception as e2:
        print(f"ERROR: Previous run also failed: {e2}")
        import traceback
        traceback.print_exc()
