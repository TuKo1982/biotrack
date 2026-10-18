/* BioTrack — graphiques SVG sans dépendance. Données injectées dans window.BT. */
(function () {
  const BT = window.BT; if (!BT) return;
  const COLORS = ["#1f5fbf", "#d9534f", "#2a9d8f", "#e9a23b", "#7b2cbf", "#666"];
  const W = 1060, H = 250, L = 48, R = 14, T = 20, B = 40;
  const DAY = 864e5;
  const fmtD = d => d.slice(8) + "." + d.slice(5, 7) + "." + d.slice(2, 4);

  function axisX(s, t0, t1, xs) {
    // un repère par mois
    const start = new Date(t0); start.setDate(1); start.setMonth(start.getMonth() + 1);
    for (let d = start; d.getTime() < t1; d.setMonth(d.getMonth() + 1)) {
      const x = xs(d.getTime());
      const lab = (d.getMonth() === 0) ? d.getFullYear() : ["jan", "fév", "mar", "avr", "mai", "juin", "juil", "août", "sep", "oct", "nov", "déc"][d.getMonth()];
      s.push(`<line x1="${x}" x2="${x}" y1="${T}" y2="${H - B}" stroke="#eee"/><text x="${x + 3}" y="${H - B + 14}" fill="#777" font-size="10">${lab}</text>`);
    }
  }
  function axisY(s, min, max, ys) {
    const step = (max - min) / 5;
    for (let i = 0; i <= 5; i++) { const v = min + i * step, y = ys(v); s.push(`<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#e5e5e5"/><text x="${L - 6}" y="${y + 4}" text-anchor="end" fill="#777" font-size="10">${+v.toFixed((max-min)<2?2:1)}</text>`); }
  }
  function nice(min, max) { const pad = (max - min) * 0.12 || 1; return [min - pad, max + pad]; }

  /* ---- panneaux labo ---- */
  function labPanel(title, keys) {
    const ser = keys.map(k => BT.series[k]).filter(Boolean);
    if (!ser.length) return "";
    const all = ser.flatMap(s => s.points);
    const dates = all.map(p => Date.parse(p.date));
    const t0 = Math.min(...dates) - 20 * DAY, t1 = Math.max(...dates) + 20 * DAY;
    let vmin = Math.min(...all.map(p => p.value)), vmax = Math.max(...all.map(p => p.value));
    const s0 = ser[0];
    if (ser.length === 1) { if (s0.lo != null) vmin = Math.min(vmin, s0.lo); if (s0.hi != null) vmax = Math.max(vmax, s0.hi); }
    [vmin, vmax] = nice(vmin, vmax); if (vmin < 0 && Math.min(...all.map(p => p.value)) >= 0) vmin = 0;
    const xs = t => L + (t - t0) / (t1 - t0) * (W - L - R), ys = v => T + (vmax - v) / (vmax - vmin) * (H - T - B);
    const s = [`<svg viewBox="0 0 ${W} ${H}" font-family="inherit">`];
    if (ser.length === 1 && (s0.lo != null || s0.hi != null)) {
      const lo = s0.lo != null ? Math.max(vmin, s0.lo) : vmin, hi = s0.hi != null ? Math.min(vmax, s0.hi) : vmax;
      s.push(`<rect x="${L}" y="${ys(hi)}" width="${W - L - R}" height="${ys(lo) - ys(hi)}" fill="#dff3e6"/>`);
    }
    axisY(s, vmin, vmax, ys); axisX(s, t0, t1, xs);
    ser.forEach((se, i) => {
      const c = ser.length === 1 ? COLORS[1] : COLORS[i % COLORS.length];
      const pts = se.points.map(p => [xs(Date.parse(p.date)), ys(p.value), p]);
      s.push(`<polyline fill="none" stroke="${c}" stroke-width="2" points="${pts.map(q => q[0] + "," + q[1]).join(" ")}"/>`);
      pts.forEach(([x, y, p]) => {
        const out = (p.lo != null && p.value < p.lo) || (p.hi != null && p.value > p.hi);
        const prev = p.source !== "rapport";
        s.push(`<circle cx="${x}" cy="${y}" r="${out ? 4.5 : 3.2}" fill="${out || prev ? "#fff" : c}" stroke="${c}" stroke-width="${prev ? 1.2 : 2}" ${prev ? 'stroke-dasharray="2 1"' : ""}><title>${fmtD(p.date)} : ${p.value} ${se.unit}${prev ? " (antériorité)" : ""}</title></circle>`);
        if (ser.length === 1 || out) s.push(`<text x="${x}" y="${y - 8}" text-anchor="middle" fill="${c}" font-size="10" font-weight="600">${p.value}</text>`);
      });
    });
    s.push("</svg>");
    const legend = ser.map((se, i) => `<span style="color:${ser.length === 1 ? COLORS[1] : COLORS[i % COLORS.length]}">${se.label} (${se.unit})</span>`).join("");
    const norm = ser.length === 1 ? ` · norme ${s0.lo != null ? s0.lo : "<"}${s0.lo != null && s0.hi != null ? "–" : ""}${s0.hi != null ? s0.hi : (s0.lo != null ? " et plus" : "")}` : "";
    return `<div class="panel"><h3>${title}<span class="muted">${norm}</span></h3>${s.join("")}<div class="legend">${legend}</div></div>`;
  }

  /* ---- panneaux Oura ---- */
  function ouraPanel(title, desc, key, color, min, max, zero) {
    const D = BT.oura; if (!D || D.length < 7) return "";
    const t0 = Date.parse(D[0].d) - 2 * DAY, t1 = Date.parse(D[D.length - 1].d) + 2 * DAY;
    const xs = t => L + (t - t0) / (t1 - t0) * (W - L - R), ys = v => T + (max - v) / (max - min) * (H - T - B);
    const s = [`<svg viewBox="0 0 ${W} ${H}" font-family="inherit">`];
    axisY(s, min, max, ys); axisX(s, t0, t1, xs);
    if (zero) { const y = ys(0); s.push(`<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#999" stroke-dasharray="3 3"/>`); }
    BT.draws.forEach(dr => { const x = xs(Date.parse(dr.d)); if (x < L || x > W - R) return; s.push(`<line x1="${x}" x2="${x}" y1="${T}" y2="${H - B}" stroke="#d9534f" stroke-width="1.4" stroke-dasharray="4 2"><title>${fmtD(dr.d)} ${dr.label}</title></line><text x="${x - 3}" y="${T + 9}" text-anchor="end" fill="#d9534f" font-size="10" font-weight="600">${dr.d.slice(8)}.${dr.d.slice(5, 7)}</text>`); });
    D.forEach(x => { if (x[key] == null) return; s.push(`<circle cx="${xs(Date.parse(x.d))}" cy="${ys(Math.max(min, Math.min(max, x[key])))}" r="1.6" fill="${color}" opacity="0.45"><title>${fmtD(x.d)} : ${x[key]}</title></circle>`); });
    const roll = []; for (let i = 0; i < D.length; i++) { const w = D.slice(Math.max(0, i - 6), i + 1).map(x => x[key]).filter(v => v != null); roll.push(w.length >= 4 ? w.reduce((a, b) => a + b, 0) / w.length : null); }
    const pts = []; D.forEach((x, i) => { if (roll[i] != null) pts.push(xs(Date.parse(x.d)) + "," + ys(roll[i])); });
    s.push(`<polyline fill="none" stroke="${color}" stroke-width="2.4" points="${pts.join(" ")}"/>`);
    let ei = 0;
    D.filter(x => /party|alcohol|liquor|sick|fever|flu/.test(x.tag)).forEach(x => { const px = xs(Date.parse(x.d)), y = H - B - 6; const ill = /sick|fever|flu/.test(x.tag); s.push(`<path d="M${px} ${y - 5} l4 5 l-4 5 l-4 -5 z" fill="${ill ? "#7b2cbf" : "#e9a23b"}" stroke="#333" stroke-width="0.6"><title>${fmtD(x.d)} : ${x.tag}</title></path>`); if (key === "rhr") s.push(`<text x="${px}" y="${y - (ei++ % 2 ? 22 : 9)}" text-anchor="middle" fill="#333" font-size="9">${ill ? "malade" : "alcool/fête"}</text>`); });
    s.push("</svg>");
    return `<div class="panel"><h3>${title}<span class="muted"> · ${desc}</span></h3>${s.join("")}</div>`;
  }

  const lab = document.getElementById("lab-charts");
  if (lab) {
    const used = new Set();
    lab.innerHTML = BT.panels.map(([t, keys]) => { keys.forEach(k => used.add(k)); return labPanel(t, keys); }).join("");
    const rest = Object.keys(BT.series).filter(k => !used.has(k) && !k.endsWith("_pct") && BT.series[k].points.length >= 2);
    if (rest.length) lab.innerHTML += `<details><summary>Autres paramètres (${rest.length})</summary>` + rest.map(k => labPanel(BT.series[k].label, [k])).join("") + "</details>";
  }
  const ou = document.getElementById("oura-charts");
  if (ou) {
    const D = BT.oura || [];
    const rhr = D.map(x => x.rhr).filter(v => v != null), hrv = D.map(x => x.hrv).filter(v => v != null);
    ou.innerHTML = [
      ouraPanel("Fréquence cardiaque de repos (nuit)", "bpm · plus bas = mieux · trait épais = moyenne sur 7 nuits · traits rouges = prélèvements", "rhr", "#d9534f", Math.max(35, Math.min(...rhr) - 3), Math.max(...rhr) + 3),
      ouraPanel("Variabilité de la fréquence cardiaque (VFC)", "ms · plus haut = meilleure récupération", "hrv", "#2a9d8f", Math.max(0, Math.min(...hrv) - 3), Math.max(...hrv) + 3),
      ouraPanel("Écart de température cutanée nocturne", "°C par rapport à la référence personnelle · ≥ +0.3 sur plusieurs nuits = infection probable", "t", "#e9a23b", -0.8, 1.2, true),
      ouraPanel("Durée de sommeil", "heures par nuit", "sl", "#1f5fbf", 3, 9.5),
    ].join("");
  }
})();
