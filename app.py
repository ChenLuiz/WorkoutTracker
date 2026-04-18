from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple
import hmac
import math
import re

import gspread
from gspread.utils import rowcol_to_a1
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


APP_TITLE = "Workout Tracker"
APP_VERSION = "2026.04.18.5"
TRACKING_SHEETS = ["Chen Tracking", "Ananda Tracking"]
SPLIT_SHEETS = ["5 Day Split", "3 Day Split"]

MAIN_LIFT_KEYWORDS = [
    "squat",
    "deadlift",
    "bench",
    "row",
    "pulldown",
    "press",
    "rdl",
    "split squat",
]

TRACKING_HEADERS = [
    "Date",
    "Day (Split)",
    "Exercise",
    "Set 1 weight",
    "Set 1 Reps",
    "Set 2 weight",
    "Set 2 Reps",
    "Set 3 weight",
    "Set 3 Reps",
    "Set 4 weight",
    "Set 4 Reps",
    "Total Reps",
    "Weight Moved",
    "Notes Set 1",
    "Notes Set 2",
    "Notes Set 3",
    "Notes Set 4",
]


@dataclass
class SplitExercise:
    day_title: str
    exercise: str
    sets: str
    reps: str
    category: str


@dataclass
class LastPerformance:
    date_value: Optional[pd.Timestamp]
    weight_values: List[float]
    rep_values: List[float]
    total_reps: Optional[float]
    weight_moved: Optional[float]


st.set_page_config(page_title=APP_TITLE, page_icon="🏋️", layout="wide")


# ---------- Access control ----------
def require_app_password() -> None:
    expected_password = str(st.secrets.get("app_password", "")).strip()
    if not expected_password:
        st.title("🏋️ Workout Tracker")
        st.error("App password is not configured yet.")
        st.code(
            'app_password = "choose-a-shared-password"',
            language="toml",
        )
        st.caption("Add that line to .streamlit/secrets.toml locally and to the app Secrets in Streamlit Cloud.")
        st.stop()

    def password_entered() -> None:
        st.session_state["password_attempted"] = True
        entered_password = str(st.session_state.get("password_input", ""))
        if hmac.compare_digest(entered_password, expected_password):
            st.session_state["password_ok"] = True
            st.session_state.pop("password_input", None)
        else:
            st.session_state["password_ok"] = False

    if st.session_state.get("password_ok", False):
        return

    st.title("🏋️ Workout Tracker")
    st.caption("Enter the shared password to open the app.")
    st.text_input("Password", type="password", key="password_input", on_change=password_entered)

    if st.session_state.get("password_attempted", False) and not st.session_state.get("password_ok", False):
        st.error("Wrong password.")

    st.stop()


# ---------- Safety helpers ----------
def safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if text == "":
        return default
    try:
        number = float(text)
    except (TypeError, ValueError):
        return default
    if pd.isna(number) or math.isnan(number) or math.isinf(number):
        return default
    return number


def safe_int(value, default: int = 0) -> int:
    return int(round(safe_float(value, float(default))))


def normalize_split_value(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    # Excel-imported set/rep values sometimes become display-formatted dates like 2/3/2026.
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text):
        dt = pd.to_datetime(text, errors="coerce")
        if pd.notna(dt):
            return f"{dt.month}-{dt.day}"

    if re.fullmatch(r"\d+\.0", text):
        return str(int(float(text)))
    return text


def to_sheet_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# ---------- Google Sheets helpers ----------
def get_service_account_info() -> Optional[dict]:
    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        gs = dict(st.secrets["connections"]["gsheets"])
        keys = [
            "type",
            "project_id",
            "private_key_id",
            "private_key",
            "client_email",
            "client_id",
            "auth_uri",
            "token_uri",
            "auth_provider_x509_cert_url",
            "client_x509_cert_url",
        ]
        info = {k: gs.get(k) for k in keys if gs.get(k)}
        return info or None
    return None


def get_spreadsheet_locator() -> Optional[str]:
    if "google_sheet_url" in st.secrets:
        return str(st.secrets["google_sheet_url"])
    if "google_sheet_id" in st.secrets:
        return str(st.secrets["google_sheet_id"])
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        gs = st.secrets["connections"]["gsheets"]
        if "spreadsheet" in gs:
            return str(gs["spreadsheet"])
    return None


@st.cache_resource
def get_spreadsheet():
    service_account_info = get_service_account_info()
    locator = get_spreadsheet_locator()
    if not service_account_info or not locator:
        raise RuntimeError("Missing Google Sheets credentials or spreadsheet locator.")

    client = gspread.service_account_from_dict(service_account_info)
    if locator.startswith("http"):
        return client.open_by_url(locator)
    return client.open_by_key(locator)


def get_worksheet(sheet_name: str):
    spreadsheet = get_spreadsheet()
    return spreadsheet.worksheet(sheet_name)


def worksheet_matrix(sheet_name: str) -> List[List[str]]:
    ws = get_worksheet(sheet_name)
    rows = ws.get_all_values()
    if not rows:
        return []
    max_cols = max(len(row) for row in rows)
    return [row + [""] * (max_cols - len(row)) for row in rows]


def read_split_sheet(sheet_name: str) -> Dict[str, List[SplitExercise]]:
    matrix = worksheet_matrix(sheet_name)
    if not matrix:
        return {}

    max_cols = max(len(row) for row in matrix)
    split: Dict[str, List[SplitExercise]] = {}

    for start_col in range(0, max_cols, 4):
        title = normalize_split_value(matrix[0][start_col] if len(matrix) > 0 and start_col < len(matrix[0]) else "")
        if not title:
            continue

        exercises: List[SplitExercise] = []
        for row_idx in range(2, len(matrix)):
            row = matrix[row_idx]
            exercise = normalize_split_value(row[start_col] if start_col < len(row) else "")
            sets = normalize_split_value(row[start_col + 1] if start_col + 1 < len(row) else "")
            reps = normalize_split_value(row[start_col + 2] if start_col + 2 < len(row) else "")
            if not exercise:
                continue
            exercises.append(
                SplitExercise(
                    day_title=title,
                    exercise=exercise,
                    sets=sets,
                    reps=reps,
                    category=lift_category(exercise),
                )
            )
        split[title] = exercises

    return split


def read_instructions_sheet(sheet_name: str = "Instructions") -> pd.DataFrame:
    matrix = worksheet_matrix(sheet_name)
    rows = []
    for row in matrix:
        label = normalize_split_value(row[0] if len(row) > 0 else "")
        detail = normalize_split_value(row[1] if len(row) > 1 else "")
        if not label and not detail:
            continue
        rows.append({"Label": label, "Detail": detail})
    return pd.DataFrame(rows)


def lift_category(exercise_name: str) -> str:
    lowered = exercise_name.lower()
    return "Main" if any(keyword in lowered for keyword in MAIN_LIFT_KEYWORDS) else "Accessory"


def tracking_sheet_to_df(sheet_name: str) -> pd.DataFrame:
    matrix = worksheet_matrix(sheet_name)
    if not matrix:
        return pd.DataFrame(columns=TRACKING_HEADERS)

    headers = matrix[0]
    rows = []
    for row in matrix[1:]:
        padded = row + [""] * (len(headers) - len(row))
        record = dict(zip(headers, padded))
        if not str(record.get("Exercise", "")).strip() and not str(record.get("Date", "")).strip():
            continue
        rows.append(record)

    if not rows:
        return pd.DataFrame(columns=headers)

    df = pd.DataFrame(rows)
    if "Exercise" in df.columns:
        df = df[df["Exercise"].astype(str).str.strip() != ""].copy()

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    numeric_cols = [
        "Day (Split)",
        "Set 1 weight", "Set 1 Reps",
        "Set 2 weight", "Set 2 Reps",
        "Set 3 weight", "Set 3 Reps",
        "Set 4 weight", "Set 4 Reps",
        "Total Reps", "Weight Moved",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["Total Reps"] = df.apply(calc_total_reps, axis=1)
    df["Weight Moved"] = df.apply(calc_weight_moved, axis=1)
    df["Best Set Weight"] = df.apply(best_set_weight, axis=1)
    df["Estimated 1RM"] = df.apply(best_estimated_1rm, axis=1)

    if "Date" in df.columns:
        df = df.sort_values(["Date", "Exercise"], ascending=[True, True])
    return df


def calc_total_reps(row: pd.Series) -> float:
    return sum(safe_float(row.get(col)) for col in ["Set 1 Reps", "Set 2 Reps", "Set 3 Reps", "Set 4 Reps"])


def calc_weight_moved(row: pd.Series) -> float:
    total = 0.0
    pairs = [
        ("Set 1 weight", "Set 1 Reps"),
        ("Set 2 weight", "Set 2 Reps"),
        ("Set 3 weight", "Set 3 Reps"),
        ("Set 4 weight", "Set 4 Reps"),
    ]
    for weight_col, rep_col in pairs:
        total += safe_float(row.get(weight_col)) * safe_float(row.get(rep_col))
    return total


def best_set_weight(row: pd.Series) -> float:
    weights = [safe_float(row.get(col)) for col in ["Set 1 weight", "Set 2 weight", "Set 3 weight", "Set 4 weight"]]
    return max(weights) if weights else 0.0


def best_estimated_1rm(row: pd.Series) -> float:
    best = 0.0
    for i in range(1, 5):
        weight = safe_float(row.get(f"Set {i} weight"))
        reps = safe_float(row.get(f"Set {i} Reps"))
        if weight <= 0 or reps <= 0:
            continue
        estimate = weight * (1 + reps / 30)
        best = max(best, estimate)
    return round(best, 2)


def row_to_performance(row: pd.Series) -> LastPerformance:
    weights = [safe_float(row.get(f"Set {i} weight")) for i in range(1, 5)]
    reps = [safe_float(row.get(f"Set {i} Reps")) for i in range(1, 5)]
    return LastPerformance(
        date_value=row.get("Date"),
        weight_values=weights,
        rep_values=reps,
        total_reps=safe_float(row.get("Total Reps")),
        weight_moved=safe_float(row.get("Weight Moved")),
    )


def find_current_session(df: pd.DataFrame, exercise: str, workout_date: date, day_number: int) -> Optional[LastPerformance]:
    if df.empty:
        return None
    subset = df[
        (df["Exercise"].astype(str).str.lower() == exercise.lower())
        & (df["Date"].dt.date == workout_date)
        & (df["Day (Split)"].fillna(0).astype(int) == day_number)
    ].sort_values("Date")
    if subset.empty:
        return None
    return row_to_performance(subset.iloc[-1])


def find_previous_performance(df: pd.DataFrame, exercise: str, workout_date: date, day_number: int) -> Optional[LastPerformance]:
    if df.empty:
        return None
    subset = df[df["Exercise"].astype(str).str.lower() == exercise.lower()].sort_values("Date")
    subset = subset[
        ~(
            (subset["Date"].dt.date == workout_date)
            & (subset["Day (Split)"].fillna(0).astype(int) == day_number)
        )
    ]
    if subset.empty:
        return None
    return row_to_performance(subset.iloc[-1])


def parse_rep_range(rep_text: str) -> Optional[Tuple[int, int]]:
    numbers = [int(n) for n in re.findall(r"\d+", str(rep_text))]
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def progression_hint(rep_text: str, weights: List[float], reps: List[float], exercise_name: str) -> str:
    nonzero_pairs = [(w, r) for w, r in zip(weights, reps) if w > 0 and r > 0]
    if not nonzero_pairs:
        return "No prior data yet. Log this once and the app will start suggesting next steps."

    rep_range = parse_rep_range(rep_text)
    if rep_range is None:
        return "Use the last logged numbers as your baseline and aim to beat either reps or weight next time."

    _, high = rep_range
    completed_reps = [r for _, r in nonzero_pairs]
    consistent_weight = len({w for w, _ in nonzero_pairs}) == 1

    if all(r >= high for r in completed_reps):
        if any(k in exercise_name.lower() for k in ["bench", "curl", "lateral", "triceps", "shoulder"]):
            return "You hit the top of the rep range. Try the next small jump next time."
        return "You hit the top of the rep range. Add a little weight next time."

    if consistent_weight:
        return "Keep the weight the same and try to add 1 rep somewhere next session."
    return "This looks like a ramp-up set pattern. Keep the structure and try to beat one set next time."


def day_number_from_title(title: str) -> int:
    match = re.search(r"Day\s*(\d+)", title)
    return int(match.group(1)) if match else 0


def planned_set_count(sets_text: str) -> int:
    numbers = [int(n) for n in re.findall(r"\d+", str(sets_text))]
    if not numbers:
        return 4
    return max(1, min(max(numbers), 4))


def summarize_logged_sets(performance: Optional[LastPerformance], max_sets: int) -> List[str]:
    if performance is None:
        return []
    lines = []
    for i in range(max_sets):
        weight = safe_float(performance.weight_values[i])
        reps = safe_float(performance.rep_values[i])
        if weight > 0 or reps > 0:
            lines.append(f"Set {i + 1}: {weight:g} x {safe_int(reps)}")
    return lines


def next_set_number(performance: Optional[LastPerformance], max_sets: int) -> int:
    if performance is None:
        return 1
    for i in range(max_sets):
        if safe_float(performance.weight_values[i]) <= 0 and safe_float(performance.rep_values[i]) <= 0:
            return i + 1
    return max_sets


def find_or_create_exercise_row(sheet_name: str, workout_date: date, day_number: int, exercise: str) -> int:
    matrix = worksheet_matrix(sheet_name)
    data_rows = matrix[1:] if len(matrix) > 1 else []

    for offset, row in enumerate(data_rows, start=2):
        row_date = pd.to_datetime(row[0] if len(row) > 0 else "", errors="coerce")
        row_day = safe_int(row[1] if len(row) > 1 else 0)
        row_exercise = str(row[2] if len(row) > 2 else "").strip()
        if pd.notna(row_date) and row_date.date() == workout_date and row_day == day_number and row_exercise.lower() == exercise.lower():
            return offset

    return len(matrix) + 1 if matrix else 2


def update_cells(sheet_name: str, updates: Dict[Tuple[int, int], object]) -> None:
    ws = get_worksheet(sheet_name)
    payload = []
    for (row_idx, col_idx), value in updates.items():
        payload.append({
            "range": rowcol_to_a1(row_idx, col_idx),
            "values": [[to_sheet_value(value)]],
        })
    ws.batch_update(payload)


def update_set_entry(
    sheet_name: str,
    workout_date: date,
    day_number: int,
    exercise: str,
    set_number: int,
    weight: float,
    reps: float,
    note: str,
) -> None:
    row_idx = find_or_create_exercise_row(sheet_name, workout_date, day_number, exercise)
    existing_df = tracking_sheet_to_df(sheet_name)
    current = find_current_session(existing_df, exercise, workout_date, day_number)

    existing_weights = current.weight_values if current else [0.0, 0.0, 0.0, 0.0]
    existing_reps = current.rep_values if current else [0.0, 0.0, 0.0, 0.0]
    existing_notes = [""] * 4

    matrix = worksheet_matrix(sheet_name)
    if row_idx - 1 < len(matrix):
        row = matrix[row_idx - 1]
        for i in range(4):
            note_col = 13 + i
            existing_notes[i] = row[note_col] if note_col < len(row) else ""

    existing_weights[set_number - 1] = safe_float(weight)
    existing_reps[set_number - 1] = safe_float(reps)
    existing_notes[set_number - 1] = str(note).strip()

    total_reps = sum(existing_reps)
    total_volume = sum(w * r for w, r in zip(existing_weights, existing_reps))

    updates = {
        (row_idx, 1): workout_date.isoformat(),
        (row_idx, 2): day_number,
        (row_idx, 3): exercise,
        (row_idx, 4 + (set_number - 1) * 2): weight if safe_float(weight) > 0 else "",
        (row_idx, 5 + (set_number - 1) * 2): reps if safe_float(reps) > 0 else "",
        (row_idx, 14 + (set_number - 1)): existing_notes[set_number - 1],
        (row_idx, 12): safe_int(total_reps),
        (row_idx, 13): round(total_volume, 2),
    }
    update_cells(sheet_name, updates)


def streak_days(df: pd.DataFrame) -> int:
    dates = sorted({d.date() for d in df["Date"].dropna()})
    if not dates:
        return 0
    streak = 1
    for idx in range(len(dates) - 1, 0, -1):
        delta = (dates[idx] - dates[idx - 1]).days
        if delta == 1:
            streak += 1
        elif delta > 1:
            break
    return streak


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


# ---------- Visual helpers ----------
def metric_row(df: pd.DataFrame):
    distinct_days = df["Date"].dt.date.nunique() if not df.empty else 0
    total_volume = int(df["Weight Moved"].sum()) if not df.empty else 0
    last_30_cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=30)
    last_30 = df[df["Date"] >= last_30_cutoff]
    last_30_volume = int(last_30["Weight Moved"].sum()) if not last_30.empty else 0
    st1, st2, st3, st4 = st.columns(4)
    st1.metric("Workout days logged", distinct_days)
    st2.metric("Total weight moved", f"{total_volume:,}")
    st3.metric("Last 30 days volume", f"{last_30_volume:,}")
    st4.metric("Current streak", f"{streak_days(df)} day(s)")


def volume_chart(df: pd.DataFrame):
    if df.empty:
        st.info("No tracking data yet.")
        return
    daily = df.groupby(df["Date"].dt.date, as_index=False)["Weight Moved"].sum()
    fig = px.line(daily, x="Date", y="Weight Moved", markers=True, title="Daily volume")
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=45, b=20))
    st.plotly_chart(fig, width="stretch")


def weekday_chart(df: pd.DataFrame):
    if df.empty:
        return
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    temp = df.copy()
    temp["Weekday"] = temp["Date"].dt.day_name()
    temp["Weekday"] = pd.Categorical(temp["Weekday"], categories=weekday_names, ordered=True)
    counts = temp.groupby("Weekday", as_index=False)["Exercise"].count().rename(columns={"Exercise": "Logged exercises"})
    counts = counts.sort_values("Weekday")
    fig = px.bar(counts, x="Weekday", y="Logged exercises", title="Training pattern by weekday")
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=45, b=20))
    st.plotly_chart(fig, width="stretch")


def exercise_progress_chart(df: pd.DataFrame):
    if df.empty:
        return
    exercises = sorted(df["Exercise"].dropna().unique())
    selected = st.selectbox("Exercise to track", exercises)
    subset = df[df["Exercise"] == selected].sort_values("Date")
    if subset.empty:
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=subset["Date"], y=subset["Best Set Weight"], mode="lines+markers", name="Best set weight"))
    fig.add_trace(go.Scatter(x=subset["Date"], y=subset["Estimated 1RM"], mode="lines+markers", name="Estimated 1RM", yaxis="y2"))
    fig.update_layout(
        title=f"Progress for {selected}",
        height=380,
        margin=dict(l=20, r=20, t=45, b=20),
        yaxis=dict(title="Weight"),
        yaxis2=dict(title="Estimated 1RM", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, width="stretch")


def top_exercises_chart(df: pd.DataFrame):
    if df.empty:
        return
    top = df.groupby("Exercise", as_index=False)["Weight Moved"].sum().sort_values("Weight Moved", ascending=False).head(10)
    fig = px.bar(top, x="Weight Moved", y="Exercise", orientation="h", title="Top exercises by total volume")
    fig.update_layout(height=420, margin=dict(l=20, r=20, t=45, b=20), yaxis=dict(categoryorder="total ascending"))
    st.plotly_chart(fig, width="stretch")


# ---------- UI ----------
def sidebar_controls() -> Tuple[str, str]:
    st.sidebar.title("Settings")

    person_labels = [sheet.replace(" Tracking", "") for sheet in TRACKING_SHEETS]
    selected_person = st.sidebar.selectbox("Save/view section", person_labels)
    tracking_sheet = f"{selected_person} Tracking"

    split_sheet = st.sidebar.selectbox("Program tab", SPLIT_SHEETS, index=0)

    if st.sidebar.button("Lock app"):
        st.session_state["password_ok"] = False
        st.rerun()

    st.sidebar.caption(f"Version: {APP_VERSION}")
    locator = get_spreadsheet_locator()
    if locator:
        st.sidebar.caption("Backend: Google Sheets")
        st.sidebar.caption(locator)
    return tracking_sheet, split_sheet


def render_log_tab(tracking_sheet: str, split_sheet: str):
    st.subheader("Log workout")
    split = read_split_sheet(split_sheet)
    history_df = tracking_sheet_to_df(tracking_sheet)

    day_titles = list(split.keys())
    if not day_titles:
        st.warning("No split data found in the selected program tab.")
        return

    day_title = st.selectbox("Workout day", day_titles)
    workout_date = st.date_input("Workout date", value=date.today())
    day_number = day_number_from_title(day_title)

    planned_rows = split[day_title]
    planned_df = pd.DataFrame(
        [{"Exercise": row.exercise, "Sets": row.sets, "Reps": row.reps, "Type": row.category} for row in planned_rows]
    )

    with st.expander("Today’s plan", expanded=True):
        st.dataframe(planned_df, width="stretch", hide_index=True)

    st.caption("Log one set at a time. Finish a set, enter the numbers, and save just that set.")

    for idx, item in enumerate(planned_rows):
        current = find_current_session(history_df, item.exercise, workout_date, day_number)
        previous = find_previous_performance(history_df, item.exercise, workout_date, day_number)
        max_sets = planned_set_count(item.sets)
        suggested_set = next_set_number(current, max_sets)
        logged_lines = summarize_logged_sets(current, max_sets)

        with st.container(border=True):
            st.markdown(f"### {item.exercise}")
            meta_a, meta_b, meta_c = st.columns(3)
            meta_a.markdown(f"**Planned:** {item.sets} sets x {item.reps}")
            meta_b.markdown(f"**Type:** {item.category}")

            if previous and previous.date_value is not None:
                meta_c.markdown(f"**Previous log:** {previous.date_value.date()}")
                st.caption(
                    f"Last total reps: {safe_int(previous.total_reps)} | Last volume: {safe_int(previous.weight_moved):,} | {progression_hint(item.reps, previous.weight_values, previous.rep_values, item.exercise)}"
                )
            else:
                meta_c.markdown("**Previous log:** —")
                st.caption("No prior data yet.")

            if logged_lines:
                st.markdown("**Logged today:**")
                st.markdown("  \n".join(logged_lines))
            else:
                st.markdown("**Logged today:** none yet")

            if len(logged_lines) >= max_sets:
                st.success("All planned sets are logged. You can still pick a set below to edit it.")

            with st.form(key=f"single_set_form_{tracking_sheet}_{split_sheet}_{idx}", border=False):
                cols = st.columns([0.9, 1.1, 1.1, 1.7])
                set_number = cols[0].selectbox(
                    "Set",
                    options=list(range(1, max_sets + 1)),
                    index=max(0, suggested_set - 1),
                    key=f"set_select_{idx}",
                )
                default_weight = safe_float(current.weight_values[set_number - 1]) if current else 0.0
                default_reps = safe_float(current.rep_values[set_number - 1]) if current else 0.0
                weight = cols[1].number_input(
                    "Weight",
                    min_value=0.0,
                    step=2.5,
                    value=default_weight,
                    key=f"single_weight_{idx}",
                )
                reps = cols[2].number_input(
                    "Reps",
                    min_value=0.0,
                    step=1.0,
                    value=default_reps,
                    key=f"single_reps_{idx}",
                )
                note = cols[3].text_input(
                    "Note",
                    value="",
                    placeholder="optional",
                    key=f"single_note_{idx}",
                )
                submitted = st.form_submit_button(f"Save set {set_number}")

            if submitted:
                if safe_float(weight) <= 0 and safe_float(reps) <= 0 and not str(note).strip():
                    st.warning("Enter at least weight or reps before saving that set.")
                else:
                    update_set_entry(
                        tracking_sheet,
                        workout_date,
                        day_number,
                        item.exercise,
                        set_number,
                        weight,
                        reps,
                        note,
                    )
                    st.success(f"Saved {item.exercise} — set {set_number}.")
                    st.rerun()


def render_dashboard_tab(tracking_sheet: str):
    st.subheader("Progress dashboard")
    df = tracking_sheet_to_df(tracking_sheet)
    if df.empty:
        st.info("Start logging workouts and the dashboard will fill in automatically.")
        return

    metric_row(df)
    col1, col2 = st.columns(2)
    with col1:
        volume_chart(df)
    with col2:
        weekday_chart(df)

    col3, col4 = st.columns([1.3, 1])
    with col3:
        exercise_progress_chart(df)
    with col4:
        top_exercises_chart(df)

    with st.expander("Recent logs", expanded=False):
        preview_cols = [
            "Date", "Day (Split)", "Exercise", "Total Reps", "Weight Moved", "Best Set Weight", "Estimated 1RM"
        ]
        recent = df.sort_values("Date", ascending=False)[preview_cols].head(30)
        st.dataframe(recent, width="stretch", hide_index=True)


def render_split_tab(split_sheet: str):
    st.subheader("Program split")
    split = read_split_sheet(split_sheet)
    if not split:
        st.info("No split data found.")
        return
    tabs = st.tabs(list(split.keys()))
    for tab, (day_title, exercises) in zip(tabs, split.items()):
        with tab:
            day_df = pd.DataFrame(
                [{"Exercise": ex.exercise, "Sets": ex.sets, "Reps": ex.reps, "Type": ex.category} for ex in exercises]
            )
            st.dataframe(day_df, width="stretch", hide_index=True)


def render_instructions_tab():
    st.subheader("Instructions")
    instructions_df = read_instructions_sheet()
    if instructions_df.empty:
        st.info("No instructions found in the sheet.")
        return
    for _, row in instructions_df.iterrows():
        if row["Detail"]:
            st.markdown(f"**{row['Label']}** — {row['Detail']}")
        else:
            st.markdown(f"### {row['Label']}")


def render_data_tab(tracking_sheet: str):
    st.subheader("Data tools")
    df = tracking_sheet_to_df(tracking_sheet)
    if not df.empty:
        st.dataframe(df.sort_values("Date", ascending=False), width="stretch", hide_index=True)
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download tracking CSV",
            data=csv_bytes,
            file_name=f"{sanitize_filename(tracking_sheet.lower())}_tracking_export.csv",
            mime="text/csv",
        )
    else:
        st.info("No rows to export yet.")

    st.markdown("### App notes")
    st.write("- This version uses Google Sheets as the source of truth.")
    st.write("- The logger saves one set at a time into the same exercise row.")
    st.write("- Split and instruction tabs read directly from your sheet tabs, so you only maintain one source of truth.")
    st.write("- Progress charts are computed from the tracking sheet and do not require extra formulas in Google Sheets.")


def render_setup_error(exc: Exception):
    st.error("Google Sheets is not configured yet.")
    st.code(
        """
# .streamlit/secrets.toml

google_sheet_url = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit#gid=0"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
        """.strip(),
        language="toml",
    )
    st.caption(str(exc))
    st.stop()


def main():
    require_app_password()

    st.title("🏋️ Workout Tracker")
    st.caption("Fast logging, built around your Google Sheet.")

    try:
        _ = get_spreadsheet()
    except Exception as exc:  # pragma: no cover - setup feedback path
        render_setup_error(exc)

    tracking_sheet, split_sheet = sidebar_controls()

    tabs = st.tabs(["Log Workout", "Dashboard", "Split", "Instructions", "Data"])
    with tabs[0]:
        render_log_tab(tracking_sheet, split_sheet)
    with tabs[1]:
        render_dashboard_tab(tracking_sheet)
    with tabs[2]:
        render_split_tab(split_sheet)
    with tabs[3]:
        render_instructions_tab()
    with tabs[4]:
        render_data_tab(tracking_sheet)


if __name__ == "__main__":
    main()
