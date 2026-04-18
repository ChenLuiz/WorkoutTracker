# Workout Tracker Streamlit App

This app wraps your existing `Workouts.xlsx` workbook in a faster interface for logging workouts and viewing progress.

## What it does
- Logs workout data into `Chen Tracking` or `Ananda Tracking`
- Reads the split directly from `5 Day Split` or `3 Day Split`
- Shows the plan and instructions in separate app tabs
- Autofills from your last logged performance for convenience
- Shows progress charts, volume trends, streaks, and exercise-level estimated 1RM trends
- Lets you export your tracking data as CSV

## Files
- `app.py` — main Streamlit app
- `requirements.txt` — Python dependencies
- `Workouts.xlsx` — your workbook backend

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes
- Keep `Workouts.xlsx` in the same folder as `app.py` unless you want to point the sidebar to another path.
- The app writes one row per exercise into the selected tracking sheet.
- If you change the split or instructions in Excel, the app will reflect it automatically.
