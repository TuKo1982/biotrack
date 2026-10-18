import json
import os
import secrets
import shutil
import tempfile
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import analysis
import db
import ingest_lab
import ingest_oura

HERE = os.path.dirname(__file__)
app = FastAPI(title="BioTrack")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
security = HTTPBasic(auto_error=False)
PASSWORD = os.environ.get("BIOTRACK_PASSWORD", "")
TZ = os.environ.get("BIOTRACK_TZ", "Europe/Zurich")
UPLOAD_DIR = os.path.join(os.environ.get("BIOTRACK_DATA", "/var/lib/biotrack"), "uploads")


def auth(creds: HTTPBasicCredentials = Depends(security)):
    if not PASSWORD:
        return True
    if creds is None or not secrets.compare_digest(creds.password, PASSWORD):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic realm=BioTrack"})
    return True


@app.on_event("startup")
def _startup():
    db.init()
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ------------------------------------------------------------ données ----
def build_payload(conn):
    series = analysis.lab_series(conn)
    days = analysis.oura_days(conn)
    tags = analysis.oura_tags(conn)
    reports = [dict(r) for r in conn.execute("SELECT * FROM lab_reports ORDER BY drawn_at")]
    contexts = {r["request_no"]: analysis.draw_context(conn, days, tags, r["drawn_at"]) for r in reports}
    ss = analysis.sleep_stats(days) if days else None
    trend = analysis.rhr_trend(days) if days else None
    corr = analysis.correlations(series, contexts)
    finds = analysis.findings(series, contexts, days, ss, trend)
    # résumé par prélèvement : valeurs notables
    notable = {}
    for key, s in series.items():
        for p in s["points"]:
            if p["request_no"] and not key.endswith("_pct") and (p["flag"] or key in ("crp", "ggt", "neut", "vitd")):
                notable.setdefault(p["request_no"], []).append(f"{s['label']} {p['value']:g}{' ⚠' if p['flag'] else ''}")
    oura_rows = [dict(d=day, rhr=d.get("rhr"), hrv=d.get("hrv"), t=d.get("temp_dev"), sl=d.get("sleep_h"), rd=d.get("readiness"),
                      st=d.get("steps"), tag=",".join(tags.get(day, []))) for day, d in days.items()]
    uploads = [dict(r) for r in conn.execute("SELECT * FROM uploads ORDER BY imported_at DESC LIMIT 50")]
    return dict(series=series, panels=ingest_lab.PANELS, reports=reports, contexts=contexts, notable=notable, sleep=ss, trend=trend,
                monthly=analysis.monthly(days) if days else {}, baseline=analysis.oura_baseline(days) if days else {},
                corr=corr, findings=finds, oura=oura_rows, uploads=uploads,
                oura_range=(min(days), max(days)) if days else None, n_days=len(days))


@app.get("/", response_class=HTMLResponse)
def index(request: Request, _=Depends(auth)):
    with db.connect() as conn:
        p = build_payload(conn)
    return templates.TemplateResponse(request, "index.html", {"p": p, "chart_json": json.dumps(
        dict(series=p["series"], panels=p["panels"], oura=p["oura"], draws=[dict(d=r["drawn_at"][:10], label=", ".join(p["notable"].get(r["request_no"], [])[:3])) for r in p["reports"] if r["drawn_at"]]),
        ensure_ascii=False, default=str)})


@app.get("/api/data")
def api_data(_=Depends(auth)):
    with db.connect() as conn:
        return JSONResponse(json.loads(json.dumps(build_payload(conn), default=str)))


# ------------------------------------------------------------- upload ----
def store_lab(conn, rep: ingest_lab.LabReport, filename: str):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not rep.request_no:
        rep.request_no = "sans-numero-" + (rep.drawn_at or now)
    existed = conn.execute("SELECT 1 FROM lab_reports WHERE request_no=?", (rep.request_no,)).fetchone()
    conn.execute("INSERT OR REPLACE INTO lab_reports (request_no, drawn_at, ordered_by, filename, imported_at) VALUES (?,?,?,?,?)",
                 (rep.request_no, rep.drawn_at, rep.ordered_by, filename, now))
    for r in rep.results:
        conn.execute("""INSERT OR REPLACE INTO lab_results (request_no, key, name, section, value, value_text, unit, range_text, lo, hi, flag)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (rep.request_no, r.key, r.name, r.section, r.value, r.value_text, r.unit, r.range_text, r.lo, r.hi, int(r.flag)))
        if r.key and r.prev_date and r.prev_value is not None:
            conn.execute("INSERT OR IGNORE INTO lab_prev (key, date, value, unit, lo, hi) VALUES (?,?,?,?,?,?)",
                         (r.key, r.prev_date, r.prev_value, r.unit, r.lo, r.hi))
    return dict(request_no=rep.request_no, drawn_at=rep.drawn_at, n=len(rep.results), replaced=bool(existed))


@app.post("/upload")
async def upload(request: Request, files: list[UploadFile] = File(...), _=Depends(auth)):
    msgs = []
    with db.connect() as conn:
        for up in files:
            name = os.path.basename(up.filename or "fichier")
            suffix = os.path.splitext(name)[1].lower()
            fd, tmp = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                shutil.copyfileobj(up.file, f)
            try:
                if suffix == ".zip":
                    daily, tags, wo, hourly = ingest_oura.parse_zip(tmp, TZ)
                    s = ingest_oura.store(conn, daily, tags, wo, hourly)
                    summary = f"Oura : {s['new']} jours ajoutés, {s['updated']} mis à jour ({s['first']} → {s['last']}), {s['workouts']} entraînements, {s['tags']} tags"
                    kind = "oura"
                elif suffix == ".pdf":
                    rep = ingest_lab.parse_pdf(tmp)
                    if not rep.results:
                        raise ValueError("aucun résultat reconnu dans ce PDF (format Polyanalytic « Rapport Complet » attendu)")
                    s = store_lab(conn, rep, name)
                    shutil.copy(tmp, os.path.join(UPLOAD_DIR, f"{s['request_no'].replace(' ', '')}.pdf"))
                    summary = f"Bilan du {s['drawn_at'].replace('T', ' ')} : {s['n']} résultats" + (" (rapport déjà présent, remplacé)" if s["replaced"] else "")
                    kind = "labo"
                else:
                    raise ValueError("format non pris en charge (attendu : .zip Oura ou .pdf de laboratoire)")
                conn.execute("INSERT INTO uploads (filename, kind, imported_at, summary) VALUES (?,?,?,?)",
                             (name, kind, datetime.now(timezone.utc).isoformat(timespec="seconds"), summary))
                msgs.append(dict(file=name, ok=True, msg=summary))
            except Exception as e:  # noqa: BLE001 — on veut remonter l'erreur à l'utilisateur
                msgs.append(dict(file=name, ok=False, msg=str(e)))
            finally:
                os.unlink(tmp)
    if "application/json" in (request.headers.get("accept") or ""):
        return JSONResponse(msgs)
    return templates.TemplateResponse(request, "upload_result.html", {"msgs": msgs})


@app.post("/report/{request_no}/delete")
def delete_report(request_no: str, _=Depends(auth)):
    with db.connect() as conn:
        conn.execute("DELETE FROM lab_results WHERE request_no=?", (request_no,))
        conn.execute("DELETE FROM lab_reports WHERE request_no=?", (request_no,))
    return RedirectResponse("/", status_code=303)


@app.get("/health")
def health():
    return {"ok": True}
