import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("BIOTRACK_DB", os.path.join(os.environ.get("BIOTRACK_DATA", "/var/lib/biotrack"), "biotrack.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
  id INTEGER PRIMARY KEY, filename TEXT, kind TEXT, imported_at TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS lab_reports (
  request_no TEXT PRIMARY KEY, drawn_at TEXT, ordered_by TEXT, filename TEXT, imported_at TEXT
);
CREATE TABLE IF NOT EXISTS lab_results (
  id INTEGER PRIMARY KEY, request_no TEXT, key TEXT, name TEXT, section TEXT,
  value REAL, value_text TEXT, unit TEXT, range_text TEXT, lo REAL, hi REAL, flag INTEGER,
  UNIQUE(request_no, name, section)
);
CREATE TABLE IF NOT EXISTS lab_prev (
  key TEXT, date TEXT, value REAL, unit TEXT, lo REAL, hi REAL, UNIQUE(key, date)
);
CREATE TABLE IF NOT EXISTS oura_daily (
  day TEXT PRIMARY KEY,
  sleep_score INTEGER, readiness INTEGER, activity_score INTEGER,
  temp_dev REAL, temp_trend REAL,
  rhr INTEGER, avg_hr REAL, hrv REAL, resp REAL,
  sleep_h REAL, deep_h REAL, rem_h REAL, light_h REAL, tib_h REAL, efficiency INTEGER,
  latency_min REAL, awake_min REAL, restless INTEGER,
  bed_start TEXT, bed_end TEXT,
  steps INTEGER, active_cal INTEGER, total_cal INTEGER, high_min INTEGER, med_min INTEGER, low_min INTEGER,
  spo2 REAL, bdi INTEGER,
  stress_h REAL, recovery_h REAL, stress_summary TEXT, resilience TEXT,
  vo2max REAL, cv_age REAL,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS oura_tags (day TEXT, tag TEXT, text TEXT, UNIQUE(day, tag, text));
CREATE TABLE IF NOT EXISTS oura_workouts (
  id TEXT PRIMARY KEY, day TEXT, activity TEXT, intensity TEXT, calories REAL, distance REAL, start_at TEXT, end_at TEXT
);
CREATE TABLE IF NOT EXISTS oura_hourly_steps (day TEXT, hour INTEGER, steps INTEGER, UNIQUE(day, hour));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()
