"""Moteur d'analyse : séries labo, contexte Oura autour de chaque prélèvement, statistiques de
sommeil, corrélations exploratoires et constats rédigés en français.

Toutes les règles sont volontairement simples et explicites ; elles mettent en évidence, elles
ne diagnostiquent pas.
"""
import statistics as st
from collections import defaultdict
from datetime import date, datetime, timedelta

from ingest_lab import CANON

# Seuils (modifiables dans settings plus tard)
HEAVY_RHR = 68          # nuit « lourde » : FC repos >= HEAVY_RHR et VFC <= HEAVY_HRV
HEAVY_HRV = 24
TEMP_FLAG = 0.3         # écart de température nocturne signalant une possible infection
AFTERNOON_HOUR = 12     # prélèvement après midi -> remarque
ILLNESS_TAGS = {"sick", "fever", "flu", "sore_throat", "cold", "headache", "covid", "ill", "migraine"}
ALCOHOL_TAGS = {"alcohol", "liquor", "party", "wine", "beer", "late_night", "hangover"}
SPORT = {"running", "cycling", "tennis", "hiit", "strength", "mountainbiking", "swimming", "hiking", "crossfit", "rowing", "skiing"}


def _mean(v):
    v = [x for x in v if x is not None]
    return round(st.mean(v), 2) if v else None


def _sd(v):
    v = [x for x in v if x is not None]
    return round(st.pstdev(v), 2) if len(v) > 1 else None


# ---------------------------------------------------------------- Labo ----
def lab_series(conn):
    """{key: {'label','unit','points':[{date,value,lo,hi,flag,source,drawn_at}]}} trié par date."""
    out = {}
    reports = {r["request_no"]: r for r in conn.execute("SELECT * FROM lab_reports")}
    rows = conn.execute("SELECT * FROM lab_results WHERE key IS NOT NULL").fetchall()
    for r in rows:
        rep = reports.get(r["request_no"])
        if not rep or not rep["drawn_at"]:
            continue
        s = out.setdefault(r["key"], {"label": CANON[r["key"]][0], "unit": r["unit"], "points": []})
        s["points"].append(dict(date=rep["drawn_at"][:10], drawn_at=rep["drawn_at"], value=r["value"], lo=r["lo"], hi=r["hi"],
                                flag=bool(r["flag"]), source="rapport", request_no=r["request_no"]))
    # antériorités : uniquement si aucun rapport pour (clé, date)
    have = {(k, p["date"]) for k, s in out.items() for p in s["points"]}
    for r in conn.execute("SELECT * FROM lab_prev"):
        if (r["key"], r["date"]) in have or r["key"] not in CANON:
            continue
        s = out.setdefault(r["key"], {"label": CANON[r["key"]][0], "unit": r["unit"], "points": []})
        s["points"].append(dict(date=r["date"], drawn_at=None, value=r["value"], lo=r["lo"], hi=r["hi"],
                                flag=(r["lo"] is not None and r["value"] < r["lo"]) or (r["hi"] is not None and r["value"] > r["hi"]),
                                source="antériorité", request_no=None))
        have.add((r["key"], r["date"]))
    for s in out.values():
        s["points"].sort(key=lambda p: p["date"])
        # bornes de référence : les plus récentes connues
        for p in reversed(s["points"]):
            if p["lo"] is not None or p["hi"] is not None:
                s["lo"], s["hi"] = p["lo"], p["hi"]
                break
        else:
            s["lo"] = s["hi"] = None
    return out


def _slope(points):
    """Pente (unités/mois) sur les 4 derniers points, en % de la largeur de la norme si connue."""
    pts = points[-4:]
    if len(pts) < 3:
        return None
    xs = [(date.fromisoformat(p["date"]) - date.fromisoformat(pts[0]["date"])).days / 30.4 for p in pts]
    ys = [p["value"] for p in pts]
    mx, my = st.mean(xs), st.mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


# ---------------------------------------------------------------- Oura ----
def oura_days(conn):
    return {r["day"]: dict(r) for r in conn.execute("SELECT * FROM oura_daily ORDER BY day")}


def oura_tags(conn):
    t = defaultdict(list)
    for r in conn.execute("SELECT day, tag FROM oura_tags ORDER BY day"):
        t[r["day"]].append(r["tag"])
    return t


def is_heavy(d):
    return d.get("rhr") is not None and d.get("hrv") is not None and d["rhr"] >= HEAVY_RHR and d["hrv"] <= HEAVY_HRV


def oura_baseline(days):
    v = list(days.values())
    return {k: _mean([d.get(k) for d in v]) for k in ["rhr", "hrv", "temp_dev", "resp", "sleep_h", "readiness", "steps", "active_cal", "efficiency", "latency_min", "awake_min", "tib_h"]}


def window(days, end: date, n: int, include_end=True):
    ds = [(end - timedelta(i)).isoformat() for i in range(0 if include_end else 1, n + (0 if include_end else 1))]
    return [days[d] for d in ds if d in days]


def draw_context(conn, days, tags, drawn_at: str):
    """Contexte Oura autour d'un prélèvement (drawn_at ISO)."""
    if not drawn_at:
        return None
    dt = datetime.fromisoformat(drawn_at)
    d0 = dt.date()
    if not days or d0.isoformat() < min(days) or d0.isoformat() > max(days):
        return None   # période non couverte par la bague
    w14 = window(days, d0, 14, include_end=False)
    w3 = window(days, d0, 3, include_end=True)        # nuit du prélèvement incluse (nuit précédant la prise de sang)
    w21 = window(days, d0, 21, include_end=True)
    w7 = window(days, d0, 7, include_end=True)
    night_before = days.get(d0.isoformat())
    ctx = dict(
        drawn_at=drawn_at, hour=dt.hour + dt.minute / 60,
        rhr14=_mean([d["rhr"] for d in w14]), hrv14=_mean([d["hrv"] for d in w14]), sleep14=_mean([d["sleep_h"] for d in w14]),
        readiness14=_mean([d["readiness"] for d in w14]), steps14=_mean([d["steps"] for d in w14]), temp14=_mean([d["temp_dev"] for d in w14]),
        rhr3=_mean([d["rhr"] for d in w3]), hrv3=_mean([d["hrv"] for d in w3]), sleep3=_mean([d["sleep_h"] for d in w3]), temp3=_mean([d["temp_dev"] for d in w3]),
        heavy21=sum(1 for d in w21 if is_heavy(d)),
        temp_max7=max([d["temp_dev"] for d in w7 if d.get("temp_dev") is not None], default=None),
        night_before_missing=(night_before is None or night_before.get("rhr") is None),
        night_before=night_before,
    )
    # tags des 10 jours précédents
    tg = []
    for i in range(0, 11):
        day = (d0 - timedelta(i)).isoformat()
        for t in tags.get(day, []):
            tg.append((day, t))
    ctx["tags"] = tg
    ctx["illness_tags"] = [(d, t) for d, t in tg if t in ILLNESS_TAGS]
    ctx["alcohol_tags"] = [(d, t) for d, t in tg if t in ALCOHOL_TAGS]
    # sport le matin même (terminé avant le prélèvement) et la veille
    wo_same = conn.execute("SELECT activity, intensity, calories, start_at, end_at FROM oura_workouts WHERE day=? ORDER BY start_at", (d0.isoformat(),)).fetchall()
    before = []
    for w in wo_same:
        try:
            e = datetime.fromisoformat(w["end_at"]).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if e <= dt and (w["activity"] or "").lower() in SPORT:
            before.append(dict(w))
    ctx["workouts_before"] = before
    prev = (d0 - timedelta(1)).isoformat()
    ctx["workouts_prev_day"] = [dict(w) for w in conn.execute("SELECT activity, intensity, calories, start_at, end_at FROM oura_workouts WHERE day=? AND lower(activity) IN (%s)" % ",".join("?" * len(SPORT)), (prev, *SPORT))]
    ctx["steps_before"] = sum(r["steps"] for r in conn.execute("SELECT steps FROM oura_hourly_steps WHERE day=? AND hour<?", (d0.isoformat(), dt.hour)))
    # remarques
    notes = []
    if ctx["illness_tags"]:
        notes.append("Maladie taguée dans les 10 jours précédents (%s) : CRP et formule leucocytaire peuvent refléter une infection en cours de résolution." % ", ".join(f"{t} le {d[8:]}.{d[5:7]}" for d, t in ctx["illness_tags"]))
    if ctx["temp_max7"] is not None and ctx["temp_max7"] >= TEMP_FLAG:
        notes.append(f"Température nocturne jusqu'à +{ctx['temp_max7']:.2f} °C dans les 7 jours précédents : signal compatible avec une infection ou une inflammation.")
    if ctx["alcohol_tags"]:
        notes.append("Alcool / fête taguée dans les 10 jours précédents (%s) : peut peser sur la gamma-GT, les triglycérides et la FC de repos." % ", ".join(f"{t} le {d[8:]}.{d[5:7]}" for d, t in ctx["alcohol_tags"]))
    if ctx["heavy21"] >= 4:
        notes.append(f"{ctx['heavy21']} nuits « lourdes » (FC ≥ {HEAVY_RHR}, VFC ≤ {HEAVY_HRV}) sur les 21 jours précédents : charge élevée (alcool, infection, stress ou dette de sommeil).")
    if before:
        notes.append("Sport le matin même, avant la prise de sang (%s) : peut élever transitoirement les neutrophiles, les leucocytes, la CK et les transaminases." % ", ".join(f"{w['activity']} {w['start_at'][11:16]}–{w['end_at'][11:16]}" for w in before))
    elif ctx["steps_before"] and ctx["steps_before"] > 5000:
        notes.append(f"{ctx['steps_before']} pas avant la prise de sang : activité marquée le matin même.")
    if ctx["workouts_prev_day"]:
        notes.append("Entraînement la veille (%s) : CK, transaminases et créatinine peuvent être légèrement majorées." % ", ".join(w["activity"] for w in ctx["workouts_prev_day"]))
    if ctx["hour"] >= AFTERNOON_HOUR:
        notes.append(f"Prélèvement à {dt.strftime('%H:%M')} : un prélèvement d'après-midi (non à jeun, après repas) rend créatinine, glycémie, lipides et fer moins comparables aux prélèvements du matin.")
    if ctx["night_before_missing"]:
        notes.append("Pas de données Oura pour la nuit précédant le prélèvement (bague retirée ?).")
    if ctx["rhr3"] is not None and ctx.get("rhr14") is not None and ctx["rhr3"] - ctx["rhr14"] >= 5:
        notes.append(f"FC de repos des 3 dernières nuits ({ctx['rhr3']:.0f}) nettement au-dessus des 14 jours ({ctx['rhr14']:.0f}) : organisme sous charge au moment du prélèvement.")
    ctx["notes"] = notes
    ctx["clean"] = not notes
    return ctx


# ---------------------------------------------------------- Sommeil ----
def _bed_hour(s):
    try:
        t = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    h = t.hour + t.minute / 60
    return h - 24 if h > 12 else h


def sleep_stats(days):
    v = [d for d in days.values() if d.get("sleep_h") is not None]
    if len(v) < 14:
        return None
    beds = [_bed_hour(d.get("bed_start")) for d in v]
    beds = [b for b in beds if b is not None]
    wakes = []
    for d in v:
        try:
            t = datetime.fromisoformat(d["bed_end"]); wakes.append(t.hour + t.minute / 60)
        except (TypeError, ValueError):
            pass
    out = dict(
        n=len(v), tib=_mean([d["tib_h"] for d in v]), sleep=_mean([d["sleep_h"] for d in v]), eff=_mean([d["efficiency"] for d in v]),
        latency=_mean([d["latency_min"] for d in v]), awake=_mean([d["awake_min"] for d in v]),
        latency_median=round(st.median([d["latency_min"] for d in v if d.get("latency_min") is not None]), 1),
        deep=_mean([d["deep_h"] for d in v]), rem=_mean([d["rem_h"] for d in v]),
        bed_mean=_mean(beds), bed_sd=_sd(beds), wake_mean=_mean(wakes), wake_sd=_sd(wakes),
        pct_over7=round(100 * sum(1 for d in v if d["sleep_h"] >= 7) / len(v)),
        n_latency20=sum(1 for d in v if (d.get("latency_min") or 0) > 20), n_awake60=sum(1 for d in v if (d.get("awake_min") or 0) > 60),
        n_bdi15=sum(1 for d in v if (d.get("bdi") or 0) >= 15), n_bdi25=sum(1 for d in v if (d.get("bdi") or 0) >= 25),
    )
    # variabilité du coucher d'une nuit à l'autre
    seq = sorted(days)
    shifts = 0; pairs = 0
    for a, b in zip(seq, seq[1:]):
        ba, bb = _bed_hour(days[a].get("bed_start")), _bed_hour(days[b].get("bed_start"))
        if ba is not None and bb is not None:
            pairs += 1
            if abs(ba - bb) > 1:
                shifts += 1
    out["bed_shift_pct"] = round(100 * shifts / pairs) if pairs else None
    # tôt / tard
    def grp(f):
        g = [d for d, b in zip(v, [_bed_hour(d.get("bed_start")) for d in v]) if b is not None and f(b)]
        return dict(n=len(g), sleep=_mean([d["sleep_h"] for d in g]), score=_mean([d["sleep_score"] for d in g]),
                    rhr=_mean([d["rhr"] for d in g]), hrv=_mean([d["hrv"] for d in g]))
    out["early"] = grp(lambda b: b < -1.0)
    out["late"] = grp(lambda b: b >= 0.5)
    # jour de semaine
    wd = {}
    for name, idx in zip(["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"], range(7)):
        g = [d for day, d in days.items() if date.fromisoformat(day).weekday() == idx and d.get("rhr") is not None]
        wd[name] = dict(rhr=_mean([d["rhr"] for d in g]), hrv=_mean([d["hrv"] for d in g]), sleep=_mean([d["sleep_h"] for d in g]),
                        bed=_mean([_bed_hour(d.get("bed_start")) for d in g]))
    out["weekday"] = wd
    heavy = [day for day, d in days.items() if is_heavy(d)]
    out["heavy_total"] = len(heavy)
    out["heavy_thu_sun"] = sum(1 for day in heavy if date.fromisoformat(day).weekday() >= 3)
    return out


def monthly(days):
    g = defaultdict(list)
    for day, d in days.items():
        g[day[:7]].append(d)
    return {m: dict(rhr=_mean([d["rhr"] for d in v]), hrv=_mean([d["hrv"] for d in v]), sleep=_mean([d["sleep_h"] for d in v]),
                    readiness=_mean([d["readiness"] for d in v]), steps=_mean([d["steps"] for d in v]), n=len(v)) for m, v in sorted(g.items())}


def rhr_trend(days):
    """Moyenne des 30 derniers jours vs 90 jours précédents."""
    seq = sorted(d for d in days if days[d].get("rhr") is not None)
    if len(seq) < 60:
        return None
    last = seq[-30:]; prev = seq[-120:-30]
    return dict(rhr_last=_mean([days[d]["rhr"] for d in last]), rhr_prev=_mean([days[d]["rhr"] for d in prev]),
                hrv_last=_mean([days[d]["hrv"] for d in last]), hrv_prev=_mean([days[d]["hrv"] for d in prev]),
                since=last[0])


# ----------------------------------------------------- Corrélations ----
def spearman(xs, ys):
    n = len(xs)
    if n < 4:
        return None
    def rank(v):
        order = sorted(range(n), key=lambda i: v[i]); r = [0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(num / den, 2) if den else None


CORR_METRICS = [("rhr14", "FC repos 14 nuits"), ("hrv14", "VFC 14 nuits"), ("sleep14", "Sommeil 14 nuits"),
                ("rhr3", "FC repos 3 nuits"), ("temp3", "Température 3 nuits"), ("heavy21", "Nuits lourdes 21 j"), ("steps14", "Pas 14 jours")]
CORR_KEYS = ["crp", "neut", "lymph", "wbc", "hb", "plq", "ggt", "alat", "asat", "creat", "ferritin"]


def correlations(series, contexts):
    """contexts: {request_no: ctx}. Retourne lignes (clé, métrique, rho, n)."""
    rows = []
    for key in CORR_KEYS:
        s = series.get(key)
        if not s:
            continue
        pts = [p for p in s["points"] if p["request_no"] in contexts and contexts[p["request_no"]]]
        if len(pts) < 5:
            continue
        for mk, mlabel in CORR_METRICS:
            xs, ys = [], []
            for p in pts:
                v = contexts[p["request_no"]].get(mk)
                if v is not None:
                    xs.append(v); ys.append(p["value"])
            if len(xs) >= 5:
                rho = spearman(xs, ys)
                if rho is not None:
                    rows.append(dict(key=key, label=s["label"], metric=mlabel, rho=rho, n=len(xs), strong=abs(rho) >= 0.7))
    rows.sort(key=lambda r: -abs(r["rho"]))
    return rows


# ------------------------------------------------------------ Constats ----
def findings(series, contexts, days, ss, trend):
    """Liste de constats (dict level: 'info'|'warn'|'good', text)."""
    out = []
    fmt = lambda v: f"{v:g}"
    # 1. valeurs hors norme au dernier bilan + tendances
    latest_date = max((s["points"][-1]["date"] for s in series.values()), default=None)
    for key, s in series.items():
        pts = s["points"]
        if not pts or key.endswith("_pct"):   # les % se lisent via les valeurs absolues
            continue
        last = pts[-1]
        when = f" le {last['date'][8:]}.{last['date'][5:7]}.{last['date'][:4]}"
        lo, hi = s.get("lo"), s.get("hi")
        out_of = (lo is not None and last["value"] < lo) or (hi is not None and last["value"] > hi)
        n_out = sum(1 for p in pts[-6:] if (p["lo"] is not None and p["value"] < p["lo"]) or (p["hi"] is not None and p["value"] > p["hi"]))
        if out_of:
            side = "sous la norme" if (lo is not None and last["value"] < lo) else "au-dessus de la norme"
            rec = f" — hors norme sur {n_out} des {min(6, len(pts))} derniers bilans" if n_out >= 2 else ""
            out.append(dict(level="warn", text=f"{s['label']} {side} au dernier dosage{when} ({fmt(last['value'])} {s['unit']}, norme {s.get('lo') if lo is not None else '<'}{'-' if lo is not None and hi is not None else ''}{hi if hi is not None else ''}){rec}."))
        elif n_out >= 2 and len(pts) >= 3:
            out.append(dict(level="info", text=f"{s['label']} : normale au dernier dosage{when} ({fmt(last['value'])} {s['unit']}) mais hors norme sur {n_out} des {min(6, len(pts))} derniers bilans — paramètre fluctuant à suivre."))
        sl = _slope(pts)
        if sl is not None and lo is not None and hi is not None and len(pts) >= 4:
            width = hi - lo
            if abs(sl) * 6 > 0.5 * width:   # > moitié de la norme en 6 mois
                direction = "monte" if sl > 0 else "baisse"
                out.append(dict(level="info", text=f"{s['label']} {direction} régulièrement sur les 4 derniers bilans ({', '.join(fmt(p['value']) for p in pts[-4:])})."))
    # 2. CRP : épisodes
    crp = series.get("crp")
    if crp:
        high = [p for p in crp["points"] if p["value"] >= 5]
        if high:
            last_high = high[-1]["date"]
            since = [p for p in crp["points"] if p["date"] > last_high]
            if since and all(p["value"] < 5 for p in since):
                out.append(dict(level="good", text=f"CRP : {len(high)} dosage(s) ≥ 5 mg/L (dernier le {last_high[8:]}.{last_high[5:7]}.{last_high[:4]}, {fmt(high[-1]['value'])}), puis normale sur les {len(since)} bilans suivants."))
    # 3. vitamine D, folates
    vd = series.get("vitd")
    if vd and vd["points"][-1]["value"] < 75:
        p = vd["points"][-1]
        out.append(dict(level="warn", text=f"Vitamine D à {fmt(p['value'])} nmol/L le {p['date'][8:]}.{p['date'][5:7]} : sous la valeur recommandée (> 75). Supplémentation à discuter, surtout d'octobre à mars."))
    fo = series.get("folate")
    if fo and fo["points"][-1]["value"] < 8.8:
        out.append(dict(level="info", text=f"Folates à {fmt(fo['points'][-1]['value'])} nmol/L : zone « carence possible » (6.0–8.8) selon le laboratoire."))
    # 4. qualité des prélèvements
    perturbed = [(rn, c) for rn, c in contexts.items() if c and not c["clean"]]
    covered = [c for c in contexts.values() if c]
    if covered:
        out.append(dict(level="info" if perturbed else "good",
                        text=f"{len(perturbed)} des {len(covered)} prélèvements couverts par la bague ont un contexte perturbé (maladie, alcool, sport le matin même, après-midi, nuit manquante). Voir le détail par prélèvement."))
    afternoon = [c for c in contexts.values() if c and c["hour"] >= AFTERNOON_HOUR]
    if afternoon:
        out.append(dict(level="info", text=f"{len(afternoon)} prélèvement(s) l'après-midi : préférer le matin à jeun pour des valeurs comparables."))
    # 5. Oura global
    if trend:
        diff = trend["rhr_last"] - trend["rhr_prev"]
        if abs(diff) >= 2:
            out.append(dict(level="good" if diff < 0 else "warn",
                            text=f"FC de repos des 30 derniers jours : {trend['rhr_last']:.1f} bpm contre {trend['rhr_prev']:.1f} sur les 90 jours précédents ({diff:+.1f}) ; VFC {trend['hrv_last']:.0f} contre {trend['hrv_prev']:.0f} ms."))
    if ss:
        if ss["sleep"] < 7:
            out.append(dict(level="warn", text=f"Sommeil moyen {ss['sleep']:.2f} h ({ss['pct_over7']} % des nuits ≥ 7 h) pour {ss['tib']:.2f} h au lit : efficacité {ss['eff']:.0f} %, endormissement {ss['latency_median']:.0f} min (médiane), {ss['awake']:.0f} min éveillé par nuit."))
        if ss["bed_sd"] and ss["bed_sd"] >= 0.75:
            out.append(dict(level="info", text=f"Heure de coucher irrégulière (écart-type {ss['bed_sd']:.1f} h ; {ss['bed_shift_pct']} % des nuits décalées de plus d'une heure par rapport à la veille). La régularité est le levier le plus documenté contre l'endormissement long et les réveils."))
        if ss["early"]["n"] >= 10 and ss["late"]["n"] >= 10 and ss["early"]["sleep"] and ss["late"]["sleep"] and ss["early"]["sleep"] - ss["late"]["sleep"] >= 0.5:
            out.append(dict(level="info", text=f"Coucher avant 23:00 ({ss['early']['n']} nuits) : {ss['early']['sleep']:.2f} h, FC {ss['early']['rhr']:.0f}, VFC {ss['early']['hrv']:.0f} ; après 00:30 ({ss['late']['n']} nuits) : {ss['late']['sleep']:.2f} h, FC {ss['late']['rhr']:.0f}, VFC {ss['late']['hrv']:.0f}."))
        wd = ss["weekday"]
        if wd["Dim"]["rhr"] and wd["Lun"]["rhr"] and wd["Dim"]["rhr"] - wd["Lun"]["rhr"] >= 3:
            out.append(dict(level="info", text=f"Effet week-end : FC de repos {wd['Dim']['rhr']:.1f} le dimanche matin contre {wd['Lun']['rhr']:.1f} le lundi ; {ss['heavy_thu_sun']} des {ss['heavy_total']} nuits « lourdes » tombent du jeudi au dimanche."))
        if ss["n_bdi25"] >= 5 or ss["n_bdi15"] >= 0.25 * ss["n"]:
            out.append(dict(level="info", text=f"Indice de perturbations respiratoires Oura ≥ 15 sur {ss['n_bdi15']} nuits et ≥ 25 sur {ss['n_bdi25']} nuits : à mentionner au médecin (ronflements, pauses ?), surtout avec {ss['awake']:.0f} min d'éveil nocturne."))
    return out
