// Live parts of the guide: tables from model.json, a worked example from now.json, the
// travel-time explorer and the lag-vs-flow scatter (guide/travel_time.json).
import { legend, lineChart } from "./chart.js";
import { REPO } from "./config.js";

const $ = s => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
function h(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v; else if (k === "style") Object.assign(n.style, v); else n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
const ft = (v, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`);
const get = name => fetch(name, { cache: "no-cache" }).then(r => { if (!r.ok) throw new Error(`${name}: ${r.status}`); return r.json(); });
const table = (head, rows, right = []) => h("table", {},
  h("thead", {}, h("tr", {}, head.map((c, i) => h("th", { class: right.includes(i) ? "r" : "" }, c)))),
  h("tbody", {}, rows.map(r => h("tr", r.bold ? { style: { fontWeight: "650" } } : {}, r.cells.map((c, i) => h("td", { class: right.includes(i) ? "r" : "" }, c))))));

// Repo link: shown only once the repository URL is configured
for (const el of document.querySelectorAll(".repo-wrap")) el.hidden = !REPO;
for (const a of document.querySelectorAll(".repo-link")) if (REPO) a.href = REPO;

const NAMES = {
  "M0 tide + Bonneville": "Tide + Bonneville (the original idea)",
  "M3 + Willamette, flow-dependent tide": "+ Willamette, flow-dependent tide",
  "M5 + Q², spring–neap (Phase 1 pick)": "+ curved dam response, spring–neap (feasibility pick)",
  "M5 + overtides": "… + tidal distortion terms",
  "M5 + fast Bonneville kernel": "… + fast dam response",
  "M6 = M5 + Astoria surge": "+ ocean storm surge",
  "M8 = M6 + Sandy River": "+ Sandy River & local streams",
  "M9 = M8 + Willamette²": "… + curved Willamette effect",
  "M10 all terms": "Everything (all 14 terms)",
};

async function modelParts() {
  const m = await get("data/model.json");
  $("#live-fitted").textContent = new Date(m.fitted_utc).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });

  const cv = Object.entries(m.cv.pooled_rmse_ft).sort((a, b) => b[1] - a[1]);
  $("#cv-table").replaceChildren(table(["Model", "Error on unseen years (ft)", "R²"],
    cv.map(([k, e]) => ({ bold: k === m.model_name,
      cells: [k === m.model_name ? `${NAMES[k] || k}  ✓ selected` : NAMES[k] || k, e.toFixed(2), m.cv.pooled_r2[k].toFixed(3)] })), [1, 2]));

  const terms = Object.entries(m.coef);
  $("#eq").textContent = "stage (ft) =  " + terms.map(([k, c], i) =>
    `${i ? (c < 0 ? "\n            − " : "\n            + ") : c < 0 ? "−" : ""}${Math.abs(c).toFixed(4)}${k === "const" ? "" : " × " + k}`).join("");
  $("#coef-table").replaceChildren(table(["Term", "Coefficient", "What it is"],
    terms.map(([k, c]) => ({ cells: [h("code", {}, k), c.toFixed(4), k === "const" ? "constant (ft, USGS gauge datum)" : m.feature_doc[k] || ""] })), [1]));

  const p = m.physics;
  $("#phys-table").replaceChildren(table(["Bonneville flow", "+10 kcfs at the dam", "Tide size vs NOAA", "Tide timing vs NOAA"],
    Object.entries(p.by_bonneville_flow).map(([q, r]) => ({ cells: [`${q} kcfs`, `${ft(r.ft_per_10kcfs_bonneville)} ft`,
      `${r.tide_gain_vs_noaa.toFixed(2)}×`, `${ft(r.tide_timing_shift_min, 0)} min`] })), [1, 2, 3]));

  const sk = m.forecast.skill_ft, bs = m.forecast.baseline_skill_ft;
  const leads = ["1", "3", "6", "12", "24", "48"].filter(k => sk[k]);
  $("#skill-table").replaceChildren(table(["Hours ahead", ...leads],
    [{ cells: ["River Brain (ft)", ...leads.map(k => sk[k].rmse.toFixed(2))] },
     { cells: ["Tide table + offset (ft)", ...leads.map(k => bs[k].rmse.toFixed(2))] }], leads.map((_, i) => i + 1)));
}

async function example() {
  const n = await get("data/now.json");
  const a = n.why_it_moved["6h"] || n.why_it_moved["3h"];
  if (!a) return;
  const labels = { tide: "Tide", bonneville: "Bonneville Dam", willamette: "Willamette backwater", sandy: "Sandy River & local streams",
    spring_neap: "Spring–neap setup", ocean: "Ocean surge", unexplained: "Unexplained" };
  const rows = Object.entries(a.components_ft).map(([k, v]) => ({ cells: [labels[k] || k, `${ft(v)} ft`] }));
  const sum = Object.values(a.components_ft).reduce((s, v) => s + (v || 0), 0);
  rows.push({ bold: true, cells: ["Sum = observed change", `${ft(sum)} ft  (gauge: ${ft(a.observed_change_ft)} ft)`] });
  const from = new Date(a.from), to = new Date(a.to);
  const f = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", weekday: "short", hour: "numeric", minute: "2-digit" });
  $("#example").replaceChildren(h("h3", { style: { marginTop: 0 } }, "Worked example from the latest data ", h("span", { class: "faint", style: { fontWeight: 400 } }, "(live)")),
    h("p", { class: "muted" }, `${f.format(from)} to ${f.format(to)}:`), h("div", { class: "table-wrap" }, table(["Driver", "Change"], rows, [1])),
    h("p", { class: "faint", style: { fontSize: ".84rem" } }, "Any mismatch in the last digit is rounding."));
}

// ---- small XY chart for the cross-correlation curve and the lag-vs-flow scatter ----
function xy(container, { points, line, xLabel, yLabel, xDomain, yDomain, marker, height = 190, fmtX = v => v, fmtY = v => v }) {
  const W = Math.max(300, container.clientWidth || 600), H = height, m = { l: 44, r: 12, t: 10, b: 36 };
  const X = v => m.l + (v - xDomain[0]) / (xDomain[1] - xDomain[0]) * (W - m.l - m.r);
  const Y = v => m.t + (1 - (v - yDomain[0]) / (yDomain[1] - yDomain[0])) * (H - m.t - m.b);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "xy"); svg.style.width = "100%"; svg.style.display = "block";
  const add = (tag, a, text) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); if (text != null) e.textContent = text; svg.append(e); return e; };
  const ticks = (d, n) => { const s = (d[1] - d[0]) / n; return [...Array(n + 1).keys()].map(i => d[0] + i * s); };
  for (const v of ticks(yDomain, 4)) { add("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: "var(--line)" }); add("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end" }, fmtY(v)); }
  for (const v of ticks(xDomain, 6)) add("text", { x: X(v), y: H - 18, "text-anchor": "middle" }, fmtX(v));
  add("text", { x: (m.l + W - m.r) / 2, y: H - 3, "text-anchor": "middle", class: "lbl" }, xLabel);
  add("text", { x: 12, y: m.t + (H - m.t - m.b) / 2, "text-anchor": "middle", class: "lbl", transform: `rotate(-90 12 ${m.t + (H - m.t - m.b) / 2})` }, yLabel);
  if (line) add("path", { d: line.map(([x, y], i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(""), fill: "none", stroke: "var(--accent)", "stroke-width": 2 });
  for (const p of points || []) {
    const c = add("circle", { cx: X(p.x), cy: Y(p.y), r: 4.5, fill: "var(--accent)", stroke: "var(--surface-1)", "stroke-width": 2, "fill-opacity": 0.8 });
    if (p.title) { const t = document.createElementNS(NS, "title"); t.textContent = p.title; c.append(t); }
  }
  if (marker) add("circle", { cx: X(marker[0]), cy: Y(marker[1]), r: 6, fill: "var(--c-bonneville)", stroke: "var(--surface-1)", "stroke-width": 2 });
  container.replaceChildren(svg);
}

async function explorer() {
  const d = await get("guide/travel_time.json");
  const t = d.t.map(s => s * 1000);
  const z = a => { const v = a.filter(x => x != null); const mu = v.reduce((s, x) => s + x, 0) / v.length;
    const sd = Math.sqrt(v.reduce((s, x) => s + (x - mu) ** 2, 0) / v.length) || 1; return a.map(x => (x == null ? null : (x - mu) / sd)); };
  const river = z(d.river_bp);
  const full = [...d.bon_bp_before, ...d.bon_bp];
  const pre = d.bon_bp_before.length;
  const shifted = L => t.map((_, i) => full[pre + i - L] ?? null);
  const corr = (a, b) => {
    const p = a.map((x, i) => [x, b[i]]).filter(([x, y]) => x != null && y != null);
    const n = p.length, mx = p.reduce((s, q) => s + q[0], 0) / n, my = p.reduce((s, q) => s + q[1], 0) / n;
    let sxy = 0, sxx = 0, syy = 0; for (const [x, y] of p) { sxy += (x - mx) * (y - my); sxx += (x - mx) ** 2; syy += (y - my) ** 2; }
    return sxy / Math.sqrt(sxx * syy);
  };
  const curve = [...Array(37).keys()].map(L => [L, corr(river, shifted(L))]);
  const fmtD = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric" });
  const meanQ = d.bon.reduce((s, x) => s + (x || 0), 0) / d.bon.length;
  $("#ex-intro").textContent = `Real data from ${fmtD.format(new Date(d.window_start))} to ${fmtD.format(new Date(d.window_end))} (Bonneville averaging ${meanQ.toFixed(0)} kcfs). `
    + "The black line is the river's level at Hayden Island with every other driver the model knows about (tide, spring–neap, ocean, Willamette, Sandy) subtracted, leaving mostly the dam's influence. "
    + "The orange line is Bonneville's outflow. Both keep only changes lasting 30 hours to 10 days and are scaled to the same units. Drag the slider to delay the dam's signal and watch the lines line up.";
  $("#ex-note").textContent = `This 30-day stretch was chosen automatically: of the windows in five years with a strong dam signal, it's the one where the travel time stands out most clearly. Its best match is ${d.peak_lag_h} hours; across all five years the best match ranges from a few hours to about a day, depending on flow (see below). ` + d.note;
  const chartBox = $("#ex-chart");
  legend(chartBox, [{ label: "Dam-driven level at Hayden Island", color: "var(--c-observed)" }, { label: "Bonneville outflow, shifted", color: "var(--c-bonneville)" }]);
  const holder = h("div");
  chartBox.append(holder);
  const xcBox = $("#ex-xcorr");
  const slider = $("#lag");
  const draw = () => {
    const L = +slider.value;
    const b = z(shifted(L));
    holder.replaceChildren();
    lineChart(holder, { series: [{ label: "Dam-driven level", color: "var(--c-observed)", t, v: river, width: 1.6 },
      { label: `Bonneville, ${L} h later`, color: "var(--c-bonneville)", t, v: b, width: 1.6 }], height: 200,
      yFmt: v => v.toFixed(0), tipFmt: v => `${v.toFixed(2)} σ`, ariaLabel: "Standardized river level and shifted Bonneville outflow" });
    const r = curve[L][1];
    const best = curve.reduce((a, c) => (c[1] > a[1] ? c : a));
    $("#lag-out").textContent = `${L} h`;
    $("#r-out").textContent = `Correlation at ${L} h: r = ${r.toFixed(3)}   ·   best: ${best[0]} h (r = ${best[1].toFixed(3)})`;
    xy(xcBox, { line: curve, marker: [L, r], xDomain: [0, 36], yDomain: [Math.floor(Math.min(...curve.map(c => c[1])) * 10) / 10, 1],
      xLabel: "delay applied to the dam's flow (hours)", yLabel: "correlation", height: 170, fmtY: v => v.toFixed(1), fmtX: v => v.toFixed(0) });
  };
  slider.addEventListener("input", draw);
  draw();

  const good = d.windows.filter(w => w.peak_r > 0.6);
  $("#n-windows").textContent = good.length;
  const sc = $("#lag-scatter");
  sc.style.margin = "10px 0";
  xy(sc, { points: good.map(w => ({ x: w.bonneville_mean_kcfs, y: w.peak_lag_h,
      title: `${w.start}: ${w.bonneville_mean_kcfs} kcfs, best lag ${w.peak_lag_h} h (r ${w.peak_r})` })),
    xDomain: [50, 400], yDomain: [0, 30], xLabel: "Bonneville average flow in the 30-day window (kcfs)", yLabel: "best lag (h)",
    height: 210, fmtX: v => v.toFixed(0), fmtY: v => v.toFixed(0) });
}

for (const [fn, sel] of [[modelParts, "#cv-table"], [example, "#example"], [explorer, "#ex-intro"]]) {
  fn().catch(e => { const el = $(sel); if (el) el.textContent = `Couldn't load live data: ${e.message}`; });
}
