# Workout Tracker Streamlit App (Google Sheets)

This version of the app uses **Google Sheets** as the source of truth so your logs persist when the app is hosted and you can use it from your phone.

## What it does
- Protects the app with one shared password
- Logs workout data into `Chen Tracking` or `Ananda Tracking`
- Reads the split directly from `5 Day Split` or `3 Day Split`
- Shows the plan and instructions in separate app tabs
- Lets you log **one set at a time**
- Shows progress charts, volume trends, streaks, and exercise-level estimated 1RM trends
- Lets you export your tracking data as CSV

## Recommended sheet structure
Use your existing `Workouts.xlsx` as the template:
1. Upload `Workouts.xlsx` to Google Drive.
2. Open it with Google Sheets.
3. Keep these worksheet names:
   - `5 Day Split`
   - `3 Day Split`
   - `Instructions`
   - `Chen Tracking`
   - `Ananda Tracking`

## Files
- `app.py` — main Streamlit app
- `requirements.txt` — Python dependencies
- `Workouts.xlsx` — template workbook to import into Google Sheets
- `.streamlit/secrets.toml` — local secrets file (create this yourself, do **not** commit it)

## Local setup
### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create `.streamlit/secrets.toml`
```toml
app_password = "choose-a-shared-password"
google_sheet_url = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit#gid=0"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

### 3. Run the app
```bash
streamlit run app.py
```

## Community Cloud setup
Paste the same `secrets.toml` content into your app's **Secrets** settings.
The app will stay locked until the shared password is entered.

## Notes
- Share the Google Sheet with your service-account email.
- This app writes one row per exercise into the selected tracking sheet.
- Use the sidebar to choose whether you are saving into the Chen or Ananda section.
- If you change the split or instructions inside Google Sheets, the app will reflect it automatically.
