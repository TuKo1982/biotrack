"""Ingestion d'un export Oura (zip 'data.zip' contenant 'App Data/*.csv').

Seuls les fichiers utiles sont lus ; rawlocation.csv et les séries brutes (motion, heartrate,
temperature) sont ignorés. Chaque upload fusionne : un jour déjà présent est mis à jour.
"""
import csv
import io
import json
import zipfile
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

NEEDED = ["dailysleep", "dailyreadiness", "dailyactivity", "sleepmodel", "dailyspo2", "dailystress",
          "dailyresilience", "dailyvo2maxestimate", "dailysmoothedcardiovascularage", "workout", "tag", "stepcount"]


def _read_csv(z: zipfile.ZipFile, member: str):
    with z.open(member) as f:
        txt = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
        return list(csv.DictReader(txt, delimiter=";"))


def _find(z: zipfile.ZipFile):
    found = {}
    for n in z.namelist():
        base = n.rsplit("/", 1)[-1]
        if base.endswith(".csv"):
            stem = base[:-4].lower()
            if stem in NEEDED:
                found[stem] = n
    return found


def _f(x):
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def _i(x):
    v = _f(x)
    return int(v) if v is not None else None


def parse_zip(path: str, tz: str = "Europe/Zurich"):
    """Retourne (daily: dict day->dict, tags: list, workouts: list, hourly_steps: dict (day,hour)->int)."""
    tzinfo = ZoneInfo(tz)
    daily = defaultdict(dict)
    tags, workouts = [], []
    hourly = defaultdict(int)
    with zipfile.ZipFile(path) as z:
        files = _find(z)
        if "sleepmodel" not in files and "dailysleep" not in files:
            raise ValueError("Archive Oura non reconnue : aucun fichier 'App Data/sleepmodel.csv' ou 'dailysleep.csv'.")

        if "dailysleep" in files:
            for r in _read_csv(z, files["dailysleep"]):
                daily[r["day"]]["sleep_score"] = _i(r.get("score"))
        if "dailyreadiness" in files:
            for r in _read_csv(z, files["dailyreadiness"]):
                d = daily[r["day"]]
                d["readiness"] = _i(r.get("score"))
                d["temp_dev"] = _f(r.get("temperature_deviation"))
                d["temp_trend"] = _f(r.get("temperature_trend_deviation"))
        if "sleepmodel" in files:
            best = {}
            for r in _read_csv(z, files["sleepmodel"]):
                if r.get("type") != "long_sleep":
                    continue
                dur = _i(r.get("total_sleep_duration")) or 0
                if r["day"] not in best or dur > best[r["day"]][0]:
                    best[r["day"]] = (dur, r)
            for day, (dur, r) in best.items():
                d = daily[day]
                d["rhr"] = _i(r.get("lowest_heart_rate"))
                d["avg_hr"] = _f(r.get("average_heart_rate"))
                d["hrv"] = _f(r.get("average_hrv"))
                d["resp"] = _f(r.get("average_breath"))
                d["sleep_h"] = dur / 3600
                d["deep_h"] = (_i(r.get("deep_sleep_duration")) or 0) / 3600
                d["rem_h"] = (_i(r.get("rem_sleep_duration")) or 0) / 3600
                d["light_h"] = (_i(r.get("light_sleep_duration")) or 0) / 3600
                d["tib_h"] = (_i(r.get("time_in_bed")) or 0) / 3600
                d["efficiency"] = _i(r.get("efficiency"))
                d["latency_min"] = (_i(r.get("latency")) or 0) / 60
                d["awake_min"] = (_i(r.get("awake_time")) or 0) / 60
                d["restless"] = _i(r.get("restless_periods"))
                d["bed_start"] = r.get("bedtime_start")
                d["bed_end"] = r.get("bedtime_end")
        if "dailyactivity" in files:
            for r in _read_csv(z, files["dailyactivity"]):
                d = daily[r["day"]]
                d["steps"] = _i(r.get("steps"))
                d["active_cal"] = _i(r.get("active_calories"))
                d["total_cal"] = _i(r.get("total_calories"))
                d["high_min"] = (_i(r.get("high_activity_time")) or 0) // 60
                d["med_min"] = (_i(r.get("medium_activity_time")) or 0) // 60
                d["low_min"] = (_i(r.get("low_activity_time")) or 0) // 60
                d["activity_score"] = _i(r.get("score"))
        if "dailyspo2" in files:
            for r in _read_csv(z, files["dailyspo2"]):
                d = daily[r["day"]]
                try:
                    avg = json.loads(r.get("spo2_percentage") or "{}").get("average")
                except json.JSONDecodeError:
                    avg = None
                d["spo2"] = avg if avg else None   # 0 = capteur absent
                d["bdi"] = _i(r.get("breathing_disturbance_index"))
        if "dailystress" in files:
            for r in _read_csv(z, files["dailystress"]):
                d = daily[r["day"]]
                d["stress_h"] = (_i(r.get("stress_high")) or 0) / 3600
                d["recovery_h"] = (_i(r.get("recovery_high")) or 0) / 3600
                d["stress_summary"] = r.get("day_summary")
        if "dailyresilience" in files:
            for r in _read_csv(z, files["dailyresilience"]):
                daily[r["day"]]["resilience"] = r.get("level")
        if "dailyvo2maxestimate" in files:
            for r in _read_csv(z, files["dailyvo2maxestimate"]):
                daily[r["day"]]["vo2max"] = _f(r.get("vo2max"))
        if "dailysmoothedcardiovascularage" in files:
            for r in _read_csv(z, files["dailysmoothedcardiovascularage"]):
                if r.get("cardiovascular_age"):
                    daily[r["day"]]["cv_age"] = _f(r.get("cardiovascular_age"))
        if "workout" in files:
            for r in _read_csv(z, files["workout"]):
                workouts.append(dict(id=r["id"], day=r["day"], activity=r.get("activity"), intensity=r.get("intensity"),
                                     calories=_f(r.get("calories")), distance=_f(r.get("distance")),
                                     start_at=r.get("start_datetime"), end_at=r.get("end_datetime")))
        if "tag" in files:
            for r in _read_csv(z, files["tag"]):
                try:
                    tl = json.loads(r.get("tags") or "[]")
                except json.JSONDecodeError:
                    tl = []
                for t in tl:
                    t = t.replace("tag_generic_", "").replace("tag_sleep_", "")
                    tags.append(dict(day=r["day"], tag=t, text=r.get("text") or ""))
        if "stepcount" in files:
            # timestamps en UTC ('...Z') -> heure locale
            with z.open(files["stepcount"]) as f:
                txt = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                rd = csv.DictReader(txt, delimiter=";")
                for r in rd:
                    ts = r.get("timestamp", "")
                    if not ts:
                        continue
                    try:
                        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tzinfo)
                    except ValueError:
                        continue
                    hourly[(t.strftime("%Y-%m-%d"), t.hour)] += int(float(r.get("steps") or 0))
    # ne garder que les jours avec au moins une donnée de nuit ou d'activité
    daily = {d: v for d, v in daily.items() if v.get("rhr") is not None or v.get("steps") is not None}
    return daily, tags, workouts, dict(hourly)


DAILY_COLS = ["sleep_score", "readiness", "activity_score", "temp_dev", "temp_trend", "rhr", "avg_hr", "hrv", "resp",
              "sleep_h", "deep_h", "rem_h", "light_h", "tib_h", "efficiency", "latency_min", "awake_min", "restless",
              "bed_start", "bed_end", "steps", "active_cal", "total_cal", "high_min", "med_min", "low_min",
              "spo2", "bdi", "stress_h", "recovery_h", "stress_summary", "resilience", "vo2max", "cv_age"]


def store(conn, daily, tags, workouts, hourly):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n_new = n_upd = 0
    for day, d in daily.items():
        exists = conn.execute("SELECT 1 FROM oura_daily WHERE day=?", (day,)).fetchone()
        cols = [c for c in DAILY_COLS if c in d]
        if exists:
            n_upd += 1
            if cols:
                conn.execute(f"UPDATE oura_daily SET {', '.join(c+'=?' for c in cols)}, updated_at=? WHERE day=?",
                             [d[c] for c in cols] + [now, day])
        else:
            n_new += 1
            conn.execute(f"INSERT INTO oura_daily (day, {', '.join(cols)}, updated_at) VALUES (?, {', '.join('?' for _ in cols)}, ?)",
                         [day] + [d[c] for c in cols] + [now])
    for t in tags:
        conn.execute("INSERT OR IGNORE INTO oura_tags (day, tag, text) VALUES (?,?,?)", (t["day"], t["tag"], t["text"]))
    for w in workouts:
        conn.execute("INSERT OR REPLACE INTO oura_workouts (id, day, activity, intensity, calories, distance, start_at, end_at) VALUES (?,?,?,?,?,?,?,?)",
                     (w["id"], w["day"], w["activity"], w["intensity"], w["calories"], w["distance"], w["start_at"], w["end_at"]))
    for (day, hour), s in hourly.items():
        conn.execute("INSERT OR REPLACE INTO oura_hourly_steps (day, hour, steps) VALUES (?,?,?)", (day, hour, s))
    days = sorted(daily)
    return dict(new=n_new, updated=n_upd, first=days[0] if days else None, last=days[-1] if days else None,
                tags=len(tags), workouts=len(workouts))
