"""Parseur des rapports PDF de laboratoire (format Polyanalytic, 'Rapport Complet').

Stratégie : pdftotext -layout, puis lecture ligne à ligne.
- En-tête : 'Demande n°', 'Prélèvement du dd/mm/yyyy HH:MM', 'Demandé par'.
- Sections : lignes commençant par un seul espace ('Hémogramme', 'Répartition', ...).
- Paramètres : lignes indentées de 2+ espaces, avec [*] nom  valeur [qualificatif]  unité  normales  [date antériorité] [valeur antériorité].
Les valeurs d'antériorité sont conservées à part : elles permettent de reconstituer des
prélèvements dont on n'a pas le PDF.
"""
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# --- Canonisation des noms -------------------------------------------------
# clé courte -> (libellé affiché, liste de noms bruts possibles, section exigée ou None)
CANON = {
    "crp":       ("CRP ultra-sensible", ["CRP ultra-sensible", "CRP"], None),
    "hb":        ("Hémoglobine", ["Hémoglobine"], None),
    "hct":       ("Hématocrite", ["Hématocrite"], None),
    "rbc":       ("Erythrocytes", ["Erythrocytes", "Érythrocytes"], None),
    "mcv":       ("MCV", ["MCV"], None),
    "mch":       ("MCH", ["MCH"], None),
    "mchc":      ("MCHC", ["MCHC"], None),
    "plq":       ("Thrombocytes", ["Thrombocytes", "Plaquettes"], None),
    "wbc":       ("Leucocytes", ["Leucocytes"], None),
    "neut":      ("Neutrophiles (abs.)", ["Neutrophiles segmentés", "Neutrophiles"], "abs"),
    "lymph":     ("Lymphocytes (abs.)", ["Lymphocytes"], "abs"),
    "mono":      ("Monocytes (abs.)", ["Monocytes"], "abs"),
    "eos":       ("Eosinophiles (abs.)", ["Eosinophiles", "Éosinophiles"], "abs"),
    "baso":      ("Basophiles (abs.)", ["Basophiles"], "abs"),
    "neut_pct":  ("Neutrophiles (%)", ["Neutrophiles segmentés", "Neutrophiles"], "pct"),
    "lymph_pct": ("Lymphocytes (%)", ["Lymphocytes"], "pct"),
    "mono_pct":  ("Monocytes (%)", ["Monocytes"], "pct"),
    "eos_pct":   ("Eosinophiles (%)", ["Eosinophiles", "Éosinophiles"], "pct"),
    "baso_pct":  ("Basophiles (%)", ["Basophiles"], "pct"),
    "alat":      ("ALAT", ["ALAT", "ALAT (GPT)"], None),
    "asat":      ("ASAT", ["ASAT", "ASAT (GOT)"], None),
    "ggt":       ("Gamma-GT", ["Gamma-GT", "Gamma GT", "GGT"], None),
    "pal":       ("Phosphatase alcaline", ["Phosphatase alcaline", "Phosphatases alcalines"], None),
    "creat":     ("Créatinine", ["Créatinine"], None),
    "dfg":       ("DFG (CKD-EPI)", ["Débit de filtration glomérulaire - CKD-EPI", "Débit de filtration glomérulaire"], None),
    "ferritin":  ("Ferritine", ["Ferritine"], None),
    "iron":      ("Fer", ["Fer"], None),
    "transf":    ("Transferrine", ["Transferrine"], None),
    "tsat":      ("Saturation transferrine", ["Saturation transferrine"], None),
    "folate":    ("Folates", ["Folates"], None),
    "b12":       ("Vitamine B12", ["Vitamine B12"], None),
    "vitd":      ("25-OH-Vitamine D", ["25-OH-Vitamine D", "Vitamine D"], None),
    "albumin":   ("Albumine", ["Albumine"], None),
    "ck":        ("CK totale", ["CK totale", "CK"], None),
    "calpro":    ("Calprotectine fécale", ["Calprotectine", "Calprotectine fécale"], None),
    "glucose":   ("Glucose", ["Glucose", "Glycémie"], None),
    "hba1c":     ("HbA1c", ["HbA1c", "Hémoglobine glyquée"], None),
    "tsh":       ("TSH", ["TSH"], None),
    "chol":      ("Cholestérol total", ["Cholestérol total", "Cholestérol"], None),
    "ldl":       ("LDL", ["LDL-cholestérol", "LDL"], None),
    "hdl":       ("HDL", ["HDL-cholestérol", "HDL"], None),
    "tg":        ("Triglycérides", ["Triglycérides"], None),
}
_RAW2KEY = {}
for k, (label, raws, sect) in CANON.items():
    for r in raws:
        _RAW2KEY.setdefault(r.lower(), []).append((k, sect))

# Panneaux du tableau de bord (ordre d'affichage), avec min/max d'axe conseillés
PANELS = [
    ("Inflammation", ["crp"]),
    ("Hémoglobine", ["hb"]),
    ("Thrombocytes", ["plq"]),
    ("Formule leucocytaire (valeurs absolues)", ["wbc", "neut", "lymph"]),
    ("Foie", ["alat", "asat", "ggt"]),
    ("Reins", ["creat"]),
    ("DFG", ["dfg"]),
    ("Fer et vitamines", ["ferritin", "vitd", "folate", "b12"]),
    ("Métabolisme", ["glucose", "hba1c", "ldl", "hdl", "tg", "tsh"]),
]


@dataclass
class LabResult:
    key: Optional[str]      # clé canonique ou None
    name: str               # nom brut
    section: str
    value: float
    value_text: str         # texte brut ('<0.10', '174 Positif++')
    unit: str
    range_text: str
    lo: Optional[float]
    hi: Optional[float]
    flag: bool              # '*' hors norme selon le labo
    prev_date: Optional[str] = None   # ISO date de l'antériorité
    prev_value: Optional[float] = None


@dataclass
class LabReport:
    request_no: str
    drawn_at: str           # ISO 'YYYY-MM-DDTHH:MM'
    ordered_by: str
    results: list = field(default_factory=list)


_NUM = r"[<>]?\s?\d+(?:[.,]\d+)?"
_LINE = re.compile(
    r"^\s{2,}(?P<flag>\*\s+)?(?P<name>[^\s].*?)\s{2,}"
    r"(?P<value>" + _NUM + r")(?:\s+(?P<qual>Positif\+*|Négatif|Positive|Négative|Pos\.|Nég\.))?\s{2,}"
    r"(?P<unit>[^\s]+)\s{2,}(?P<rest>.*?)\s*$"
)
_PREV = re.compile(r"^(?P<range>.*?)(?:\s{2,}(?P<pdate>\d\d/\d\d/\d{4}))?(?:\s{2,}|\s+)(?P<pval>" + _NUM + r")\s*$")
_SECTION = re.compile(r"^ (?P<name>[A-Za-zÀ-ÿ][^\d]*?)\s*$")
_RANGE_LOHI = re.compile(r"^(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)$")
_RANGE_LT = re.compile(r"^<\s*(\d+(?:[.,]\d+)?)")
_RANGE_GT = re.compile(r"^>\s*(\d+(?:[.,]\d+)?)")
_STOP = ("Sans interprétation médicale", "Le catalogue des analyses", "Résultats validés", "Généré le", "Demande n°:")


def _num(s: str) -> Optional[float]:
    s = s.replace(",", ".").replace(" ", "")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def parse_range(rt: str):
    rt = rt.strip()
    m = _RANGE_LOHI.match(rt)
    if m:
        return _num(m.group(1)), _num(m.group(2))
    m = _RANGE_LT.match(rt)
    if m and "-" not in rt:
        return None, _num(m.group(1))
    m = _RANGE_GT.match(rt)
    if m:
        return _num(m.group(1)), None
    return None, None


def pdf_to_text(path: str) -> str:
    out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True)
    return out.stdout


def _section_kind(section: str) -> Optional[str]:
    s = section.lower()
    if "valeurs absolues" in s:
        return "abs"
    if s.startswith("répartition") or s.startswith("repartition"):
        return "pct"
    return None


def _canon(name: str, section: str, unit: str) -> Optional[str]:
    cands = _RAW2KEY.get(name.strip().lower())
    if not cands:
        return None
    kind = _section_kind(section)
    if kind is None:  # déduire du % si la section n'aide pas
        kind = "pct" if unit == "%" else "abs"
    for k, sect in cands:
        if sect is None or sect == kind:
            return k
    return None


def parse_text(text: str) -> LabReport:
    req = ""
    drawn = ""
    ordered = ""
    m = re.search(r"Demande n°\s+([\d ]+?)\s{2,}", text)
    if m:
        req = m.group(1).strip()
    m = re.search(r"Prélèvement du\s+(\d\d)/(\d\d)/(\d{4})\s+(\d\d):(\d\d)", text)
    if m:
        d, mo, y, h, mi = m.groups()
        drawn = f"{y}-{mo}-{d}T{h}:{mi}"
    m = re.search(r"Demandé par\s+(.+?)\s{2,}|Demandé par\s+(.+?)$", text, re.M)
    if m:
        ordered = (m.group(1) or m.group(2) or "").strip()

    results: list[LabResult] = []
    seen = set()
    section = ""
    carry_prev_date: Optional[str] = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if any(raw.strip().startswith(s) for s in _STOP):
            continue
        ms = _SECTION.match(raw)
        if ms and not raw.startswith("  "):
            section = ms.group("name").strip()
            carry_prev_date = None
            continue
        ml = _LINE.match(raw)
        if not ml:
            continue
        name = ml.group("name").strip()
        if name.lower() in ("dosage", "commentaire") or name.startswith("CH-") or name.startswith("Classification"):
            continue
        unit = ml.group("unit")
        rest = ml.group("rest")
        rng, pdate, pval = rest, None, None
        mp = _PREV.match(rest)
        if mp and (mp.group("pdate") or re.search(r"\s{2,}" + _NUM + r"\s*$", rest)):
            rng = mp.group("range").strip()
            if mp.group("pdate"):
                d, mo, y = mp.group("pdate").split("/")
                pdate = f"{y}-{mo}-{d}"
                carry_prev_date = pdate
            else:
                pdate = carry_prev_date
            pval = _num(mp.group("pval"))
            if pdate is None:
                pval = None
        val_text = ml.group("value") + (" " + ml.group("qual") if ml.group("qual") else "")
        value = _num(ml.group("value"))
        if value is None:
            continue
        lo, hi = parse_range(rng)
        key = _canon(name, section, unit)
        dedup = (key or name.lower(), _section_kind(section))
        if dedup in seen:   # répétition en haut de page suivante
            continue
        seen.add(dedup)
        results.append(LabResult(key=key, name=name, section=section, value=value, value_text=val_text.strip(),
                                 unit=unit, range_text=rng, lo=lo, hi=hi, flag=bool(ml.group("flag")),
                                 prev_date=pdate, prev_value=pval))
    return LabReport(request_no=req, drawn_at=drawn, ordered_by=ordered, results=results)


def parse_pdf(path: str) -> LabReport:
    return parse_text(pdf_to_text(path))
