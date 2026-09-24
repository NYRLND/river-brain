// River Brain app: reads data/*.json (written hourly by the GitHub Action) and renders six views.
// Everything taken from data is inserted with textContent, never innerHTML.
import { legend, lineChart } from "./chart.js";
import { REPO } from "./config.js";
const TZ = "America/Los_Angeles";
const COMP = {
  tide: { label: "Tide", color: "var(--c-tide)",
    about: "Ocean tide, from NOAA's prediction with its size and timing corrected for today's river flow." },
  bonneville: { label: "Bonneville Dam", color: "var(--c-bonneville)",
    about: "Dam releases, arriving about 12½ hours after they leave the dam, 40 river miles upstream." },
  willamette: { label: "Willamette backwater", color: "var(--c-willamette)",
    about: "The Willamette joins just downstream; more Willamette flow backs water up past Hayden Island." },
  sandy: { label: "Sandy River & local streams", color: "var(--c-sandy)",
    about: "Rain-fed streams entering below the dam. The Sandy River gauge stands in for all of them." },
  spring_neap: { label: "Spring–neap setup", color: "var(--c-spring_neap)",
    about: "Tidal friction raises the river's average level during the bigger spring tides of each ~15-day cycle." },
  ocean: { label: "Ocean (Astoria surge)", color: "var(--c-ocean)",
    about: "Wind and air pressure pushing the ocean above or below its predicted tide at Astoria." },
  unexplained: { label: "Unexplained", color: "var(--c-unexplained)",
    about: "What the model can't account for: shown honestly rather than folded into another bar." },
};
const ORDER = ["tide", "bonneville", "willamette", "sandy", "spring_neap", "ocean", "unexplained"];

// ---------- small helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
function h(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "style") Object.assign(n.style, v);
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
const ft = (v, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`);
const num = (v, d = 1) => (v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const int = v => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
const fTime = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", hour: "numeric", minute: "2-digit" });
const fClock = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
const fDate = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric" });
const fFull = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
const ms = iso => Date.parse(iso);
const ago = iso => {
  const m = (Date.now() - ms(iso)) / 60000;
  return m < 90 ? `${Math.round(m)} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
};
const hours = x => { const r = Math.round(x * 2) / 2; return r % 1 ? `${Math.floor(r)}½` : `${r}`; };
const key = color => h("i", { class: "key", style: { background: color } });

// ---------- data ----------
const cache = {};
async function load(name) {
  if (!cache[name]) cache[name] = fetch(`data/${name}.json`, { cache: "no-cache" }).then(r => {
    if (!r.ok) throw new Error(`${name}.json: HTTP ${r.status}`);
    return r.json();
  });
  return cache[name];
}
function columns(hist, from) {
  const t = hist.t.map(s => s * 1000);
  const i0 = from ? t.findIndex(x => x >= from) : 0;
  const out = { t: t.slice(i0) };
  for (const [k, v] of Object.entries(hist)) if (Array.isArray(v) && k !== "t") out[k] = v.slice(i0);
  return out;
}

// ---------- NOW ----------
function summarize(a, hours) {
  const d = a.observed_change_ft;
  const verb = Math.abs(d) < 0.1 ? "held nearly steady" : d > 0 ? `rose ${Math.abs(d).toFixed(2)} ft` : `fell ${Math.abs(d).toFixed(2)} ft`;
  const parts = Object.entries(a.components_ft).filter(([, v]) => v != null);
  parts.sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]));
  const [topKey, topVal] = parts[0];
  let why;
  if (topKey === "unexplained") why = "Most of that isn't explained by the model's drivers.";
  else if (Math.abs(topVal) > 0.8 * Math.abs(d) || parts.length < 2 || Math.abs(parts[1][1]) < 0.3 * Math.abs(topVal))
    why = `Mostly ${COMP[topKey].label.toLowerCase()} (${ft(topVal)} ft).`;
  else why = `${COMP[topKey].label} (${ft(topVal)} ft) and ${COMP[parts[1][0]].label.toLowerCase()} (${ft(parts[1][1])} ft).`;
  return `The river ${verb} in the last ${hours} hours. ${why}`;
}

function whyBars(a) {
  const rows = ORDER.filter(k => a.components_ft[k] != null).map(k => [k, a.components_ft[k]]);
  const max = Math.max(...rows.map(r => Math.abs(r[1])), Math.abs(a.observed_change_ft), 0.05);
  const row = (label, color, v, cls = "") => {
    // Each half of the track keeps 4.4em free so the value label always fits beyond the bar tip.
    const f = (Math.abs(v) / max).toFixed(4);
    const len = `(50% - 4.4em) * ${f}`;
    const bar = h("div", { class: `bar ${v >= 0 ? "pos" : "neg"}`, style: { width: `calc(${len})`, background: color } });
    const val = h("span", { class: "bar-val" }, `${ft(v)} ft`);
    if (v >= 0) val.style.left = `calc(50% + ${len} + 6px)`; else val.style.right = `calc(50% + ${len} + 6px)`;
    return h("div", { class: `bar-row ${cls}`, title: COMP[label]?.about || "" },
      h("div", { class: "lab" }, color ? key(color) : null, h("span", {}, COMP[label]?.label || label)),
      h("div", { class: "track" }, bar, val));
  };
  return h("div", { class: "bars", role: "table", "aria-label": "Change by cause, in feet" },
    rows.map(([k, v]) => row(k, COMP[k].color, v)),
    row("Observed change", "var(--c-observed)", a.observed_change_ft, "total"));
}

async function renderNow(v) {
  const n = await load("now");
  v.textContent = "";
  const actionUsgs = n.nws_forecast?.flood_stages_ft_usgs_datum?.action;
  const arrow = { rising: "↑", falling: "↓", steady: "→" }[n.now.direction] || "";
  const rate = n.now.rate_ft_per_h;
  v.append(h("div", { class: "card hero" },
    h("div", { class: "muted" }, `Columbia River at Hayden Island · ${fFull.format(ms(n.now.time))}`),
    h("div", { class: "value" }, n.now.stage_ft.toFixed(2), " ", h("small", {}, "ft")),
    rate == null ? null : h("div", { class: "dir" }, h("span", { class: "dir-arrow", "aria-hidden": "true" }, arrow),
      n.now.direction === "steady" ? "Steady" : `${n.now.direction[0].toUpperCase()}${n.now.direction.slice(1)} ${Math.abs(rate).toFixed(2)} ft per hour`),
    actionUsgs != null ? h("div", { class: "faint" },
      `${(actionUsgs - n.now.stage_ft).toFixed(1)} ft below the NWS "action" stage. Heights are on the USGS gauge datum.`) : null));

  const sb = staleBanner(n);
  if (sb) v.append(sb);
  for (const w of n.warnings || []) v.append(h("div", { class: "banner", role: "status" }, "⚠ ", w));

  // Why it moved
  const card = h("div", { class: "card" });
  const body = h("div");
  const wins = Object.keys(n.why_it_moved).filter(k => n.why_it_moved[k]);
  let sel = wins.includes("6h") ? "6h" : wins[0];
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Time window" });
  const paint = () => {
    body.textContent = "";
    const a = n.why_it_moved[sel];
    body.append(h("p", {}, summarize(a, parseInt(sel))), whyBars(a));
    for (const b of seg.children) b.setAttribute("aria-pressed", b.dataset.k === sel);
  };
  for (const k of wins) seg.append(h("button", { "data-k": k, onclick: () => { sel = k; paint(); } }, `Last ${parseInt(k)} h`));
  card.append(h("div", { class: "card-head" }, h("h2", {}, "Why it moved"), seg), body,
    h("p", { class: "faint", style: { marginTop: "10px", fontSize: ".82rem" } },
      "Bars add up to the observed change. Hover or tap a row for what it means. Method: see the Method tab."));
  v.append(card);
  paint();

  // Next tides + pipe
  const tides = h("div", { class: "card" }, h("h2", {}, "Next highs and lows"),
    h("div", { class: "tides", style: { marginTop: "8px" } }, n.next_tides.map(t =>
      h("div", { class: "tide" }, h("div", { class: "t" }, `${t.type === "high" ? "High" : "Low"} ${t.stage_ft.toFixed(1).replace("-", "−")} ft`),
        h("div", { class: "muted" }, fTime.format(ms(t.time)))))),
    h("p", { class: "faint", style: { fontSize: ".82rem", marginTop: "8px" } }, "From the River Brain forecast (tide + river), not a plain tide table."));
  const p = n.in_the_pipe;
  let pipe = null;
  if (p) {
    const d24 = p.bonneville_24h_ago_kcfs != null ? p.bonneville_latest_kcfs - p.bonneville_24h_ago_kcfs : null;
    const trend = d24 == null ? "" : Math.abs(d24) < 3 ? "steady over the last day" : `${d24 > 0 ? "up" : "down"} ${Math.abs(d24).toFixed(0)} kcfs from a day ago`;
    const e12 = p.expected_change_ft?.["12h"];
    pipe = h("div", { class: "card" }, h("h2", {}, "Coming down the river"),
      h("p", {}, `Bonneville Dam is releasing ${num(p.bonneville_latest_kcfs)} kcfs (${fClock.format(ms(p.bonneville_latest_time))}), ${trend}.`),
      h("p", {}, `Changes take about ${hours(p.lag_centroid_h)} hours to reach Hayden Island. If the dam holds steady, its effect here over the next 12 hours: `,
        h("b", {}, e12 == null ? "unknown" : Math.abs(e12) < 0.02 ? "essentially none" : `${ft(e12)} ft`), "."));
  }
  v.append(h("div", { class: "grid2" }, tides, pipe));

  // Drivers
  const d = n.drivers, sn = d.spring_neap || {};
  const shift = d.tide_timing_shift_min;
  v.append(h("div", { class: "card" }, h("h2", {}, "Today's conditions"),
    h("div", { class: "chips", style: { marginTop: "8px" } },
      h("span", { class: "chip" }, "Tide is ", h("b", {}, `${d.tide_gain_vs_noaa?.toFixed(2)}×`), " NOAA's prediction",
        shift != null && Math.abs(shift) >= 5 ? `, ${Math.abs(shift)} min ${shift > 0 ? "later" : "earlier"}` : ""),
      sn.state ? h("span", { class: "chip" }, h("b", {}, sn.state[0].toUpperCase() + sn.state.slice(1)),
        sn.next_spring ? ` · next spring tides ${fDate.format(ms(sn.next_spring))}` : "") : null,
      h("span", { class: "chip" }, "Bonneville ", h("b", {}, `${num(d.bonneville_24h_mean_kcfs, 0)} kcfs`)),
      h("span", { class: "chip" }, "Willamette ", h("b", {}, `${num(d.willamette_25h_mean_kcfs, 1)} kcfs`)),
      d.sandy_12h_mean_kcfs != null ? h("span", { class: "chip" }, "Sandy ", h("b", {}, `${num(d.sandy_12h_mean_kcfs, 2)} kcfs`)) : null,
      d.astoria_surge_25h_mean_ft != null ? h("span", { class: "chip" }, "Ocean surge ", h("b", {}, `${ft(d.astoria_surge_25h_mean_ft)} ft`)) : null)));

  v.append(freshnessCard(n));
}

const SOURCE_NAMES = { stage: "River level (USGS)", bonneville: "Bonneville (USACE)", willamette: "Willamette (USGS)",
  sandy: "Sandy River (USGS)", astoria: "Astoria (NOAA)", tide_predictions: "Tide predictions (NOAA)",
  nwps_forecast: "NWS forecast", fish: "Fish counts (DART)", chemistry: "Water quality (USGS)" };
// Same thresholds as riverbrain/config.py STALE_HOURS, re-checked in the browser so an old page
// never claims its data is fresh.
const STALE_H = { stage: 2, bonneville: 6, willamette: 3, sandy: 3, astoria: 3, nwps_forecast: 12, fish: 72, chemistry: 6 };
function liveStatus(k, f) {
  if (f.status === "missing" || !f.latest) return f.status;
  return (Date.now() - ms(f.latest)) / 3.6e6 > (STALE_H[k] ?? 6) ? "stale" : "ok";
}
function staleBanner(n) {
  const hrs = (Date.now() - ms(n.generated)) / 3.6e6;
  return hrs > 1.5 ? h("div", { class: "banner", role: "status" },
    `⚠ This page's data was last updated ${ago(n.generated)}. The hourly update may be delayed; numbers below are from then.`) : null;
}
function freshnessCard(n) {
  const icon = { ok: "✓", stale: "!", missing: "×" };
  return h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Data freshness"),
    h("span", { class: "faint", style: { fontSize: ".82rem" } }, `Updated ${ago(n.generated)}`)),
    h("div", { class: "fresh" }, Object.entries(n.freshness).map(([k, f]) => {
      const st = liveStatus(k, f);
      return h("span", { class: `status ${st}` }, h("i", { "aria-hidden": "true" }, icon[st] || "?"),
        `${SOURCE_NAMES[k] || k}: ${f.latest ? ago(f.latest) : st}${st === "stale" ? " (stale)" : ""}`);
    })));
}

// ---------- FORECAST ----------
async function renderForecast(v) {
  const [n, hist, model] = await Promise.all([load("now"), load("history_30d"), load("model")]);
  v.textContent = "";
  const t0 = ms(n.forecast.issued);
  const H = columns(hist, t0 - 36 * 3.6e6);
  const F = n.forecast.hours;
  const tf = F.map(r => ms(r.t));
  const nws = n.nws_forecast;
  const series = [
    { label: "Observed", color: "var(--c-observed)", t: H.t, v: H.stage, width: 1.6 },
    { label: "River Brain forecast", color: "var(--accent)", t: tf, v: F.map(r => r.stage_ft),
      band: { lo: F.map(r => r.lo_ft), hi: F.map(r => r.hi_ft) } },
  ];
  if (nws) series.push({ label: "NWS forecast", color: "var(--c-nws)", dash: true, width: 1.6,
    t: nws.points.map(p => ms(p[0])).filter(t => t <= tf[tf.length - 1]), v: nws.points.filter(p => ms(p[0]) <= tf[tf.length - 1]).map(p => p[1]) });
  const card = h("div", { class: "card" }, h("h2", {}, "Next 48 hours"));
  legend(card, [{ label: "Observed", color: "var(--c-observed)" }, { label: "River Brain forecast", color: "var(--accent)" },
    { label: "5–95% range", color: "var(--band)", area: true }, ...(nws ? [{ label: "NWS forecast", color: "var(--c-nws)", dash: true }] : [])]);
  v.append(card);
  lineChart(card, { series, now: t0, height: 280, yFmt: x => x.toFixed(1), tipFmt: x => `${x.toFixed(2)} ft`,
    ariaLabel: "Observed river level and 48-hour forecasts" });
  const maxF = Math.max(...F.map(r => r.hi_ft ?? -Infinity));
  if (nws) card.append(h("p", { class: "faint", style: { fontSize: ".82rem" } },
    `NWS action stage is ${nws.flood_stages_ft_usgs_datum.action.toFixed(1)} ft on this datum; the forecast's upper range peaks at ${maxF.toFixed(1)} ft. `,
    `NWS forecast issued ${fFull.format(ms(nws.issued))}.`));

  // What drives the forecast
  const moving = ["tide", "bonneville", "willamette", "sandy", "spring_neap", "ocean"].filter(k => F[0][k] != null)
    .filter(k => Math.max(...F.map(r => r[k])) - Math.min(...F.map(r => r[k])) > 0.03);
  const c2 = h("div", { class: "card" }, h("h2", {}, "What moves the forecast"),
    h("p", { class: "muted" }, "Each driver's change from now, in feet. Flows are held at their latest values; the tide comes from NOAA's predictions."));
  legend(c2, moving.map(k => ({ label: COMP[k].label, color: COMP[k].color })));
  lineChart(c2, { series: moving.map(k => ({ label: COMP[k].label, color: COMP[k].color, t: tf, v: F.map(r => r[k] - F[0][k]) })),
    height: 200, zeroLine: true, yFmt: x => x.toFixed(1), tipFmt: x => `${ft(x)} ft` });
  v.append(c2);

  // Skill
  const sk = model.forecast.skill_ft, bs = model.forecast.baseline_skill_ft;
  const leads = ["1", "6", "12", "24", "48"].filter(k => sk[k]);
  v.append(h("div", { class: "card" }, h("h2", {}, "How good is this forecast?"),
    h("p", { class: "muted" }, "Tested by re-running it on five past years (Oct 2021 – Sep 2026) using only the data that would have been available at the time. Typical error (RMSE), in feet:"),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Hours ahead"), leads.map(k => h("th", { class: "r" }, k)))),
      h("tbody", {},
        h("tr", {}, h("td", {}, "River Brain"), leads.map(k => h("td", { class: "r" }, sk[k].rmse.toFixed(2)))),
        h("tr", {}, h("td", {}, "Tide table + today's offset"), leads.map(k => h("td", { class: "r" }, bs[k].rmse.toFixed(2)))))))));
}

// ---------- EXPLORE ----------
async function renderExplore(v) {
  const hist = await load("history_30d");
  v.textContent = "";
  let days = 7;
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Time range" });
  const body = h("div", { style: { display: "grid", gap: "16px" } });
  const paint = () => {
    for (const b of seg.children) b.setAttribute("aria-pressed", +b.dataset.d === days);
    body.textContent = "";
    const end = hist.t[hist.t.length - 1] * 1000;
    const C = columns(hist, end - days * 864e5);
    const c1 = h("div", { class: "card" }, h("h2", {}, "Observed vs model"));
    legend(c1, [{ label: "Observed", color: "var(--c-observed)" }, { label: "Model (sum of all drivers)", color: "var(--accent)", dash: true }]);
    lineChart(c1, { series: [{ label: "Observed", color: "var(--c-observed)", t: C.t, v: C.stage },
      { label: "Model", color: "var(--accent)", t: C.t, v: C.model, dash: true, width: 1.6 }], height: 220,
      yFmt: x => x.toFixed(1), tipFmt: x => `${x.toFixed(2)} ft` });
    body.append(c1);

    // components as small multiples on one shared y-scale (heights are comparable)
    const comps = ORDER.filter(k => C[k]);
    const rel = Object.fromEntries(comps.map(k => {
      const vals = C[k].filter(x => x != null);
      const mean = vals.reduce((a, b) => a + b, 0) / (vals.length || 1);
      return [k, C[k].map(x => (x == null ? null : x - mean))];
    }));
    const all = comps.flatMap(k => rel[k]).filter(x => x != null);
    const lim = Math.max(0.2, ...all.map(Math.abs));
    const c2 = h("div", { class: "card" }, h("h2", {}, "Each driver's contribution"),
      h("p", { class: "muted" }, `Relative to its average over the period, in feet. All panels share one scale (±${lim.toFixed(1)} ft), so heights compare directly.`));
    const smalls = h("div", { class: "smalls" });
    for (const k of comps) {
      const box = h("div", {}, h("div", { class: "small-title", title: COMP[k].about }, key(COMP[k].color), COMP[k].label));
      smalls.append(box);
      lineChart(box, { series: [{ label: COMP[k].label, color: COMP[k].color, t: C.t, v: rel[k] }], height: 110,
        yDomain: [-lim, lim], yFmt: x => x.toFixed(1), tipFmt: x => `${ft(x)} ft` });
    }
    c2.append(smalls);
    body.append(c2);

    const c3 = h("div", { class: "card" }, h("h2", {}, "Bonneville Dam outflow"),
      h("p", { class: "muted" }, "Hourly, kcfs. Powerhouse flow follows daily electricity demand; spill passes water (and young fish) over the dam."));
    const dam = [{ label: "Total outflow", color: "var(--c-bonneville)", t: C.t, v: C.bonneville_kcfs }];
    if (C.bonneville_generation_kcfs) dam.push({ label: "Through powerhouse", color: "var(--text-2)", t: C.t, v: C.bonneville_generation_kcfs, width: 1.4 });
    if (C.bonneville_spill_kcfs) dam.push({ label: "Spill", color: "var(--text-3)", t: C.t, v: C.bonneville_spill_kcfs, dash: true, width: 1.4 });
    legend(c3, dam.map(s => ({ label: s.label, color: s.color, dash: s.dash })));
    lineChart(c3, { series: dam, height: 200, yFmt: x => x.toFixed(0), tipFmt: x => `${x.toFixed(1)} kcfs` });
    body.append(c3);

    const c4 = h("div", { class: "card" }, h("h2", {}, "Tributaries"));
    for (const [k, lab, color] of [["willamette_kcfs", "Willamette at Portland (25-h mean, kcfs)", "var(--c-willamette)"],
                                    ["sandy_kcfs", "Sandy River (12-h mean, kcfs)", "var(--c-sandy)"]]) {
      if (!C[k]) continue;
      const box = h("div", {}, h("div", { class: "small-title" }, key(color), lab));
      c4.append(box);
      lineChart(box, { series: [{ label: lab, color, t: C.t, v: C[k] }], height: 130, yFmt: x => x.toFixed(1), tipFmt: x => `${x.toFixed(2)} kcfs` });
    }
    body.append(c4);
  };
  for (const d of [3, 7, 30]) seg.append(h("button", { "data-d": d, onclick: () => { days = d; paint(); } }, `${d} days`));
  v.append(h("div", { class: "card-head" }, h("h2", {}, "Explore the last 30 days"), seg), body);
  paint();
}

// ---------- FISH ----------
async function renderFish(v) {
  const f = await load("fish");
  v.textContent = "";
  if (!f.available) { v.append(h("div", { class: "card" }, "Fish counts are not available right now.")); return; }
  const rows = Object.entries(f.species);
  v.append(h("div", { class: "card" }, h("h2", {}, "Adult fish counted at Bonneville Dam"),
    h("p", { class: "muted" }, `Fish ladder window counts through ${fDate.format(ms(f.through + "T12:00:00Z"))}, compared with the 10-year average for the same days.`),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Species"), h("th", { class: "r" }, "Last 7 days"), h("th", { class: "r" }, "10-yr avg"),
        h("th", {}, "vs average"), h("th", { class: "r" }, "This year"), h("th", { class: "r" }, "10-yr avg"))),
      h("tbody", {}, rows.map(([, s]) => {
        const pct = s.last7_10yr_avg ? s.last7 / s.last7_10yr_avg : null;
        return h("tr", {}, h("td", {}, s.name), h("td", { class: "r" }, int(s.last7)), h("td", { class: "r" }, int(s.last7_10yr_avg)),
          h("td", {}, pct == null ? h("span", { class: "faint" }, "—") : h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } },
            h("div", { class: "meter", title: "Bar = this week; tick = 10-year average", style: { flex: "1" } },
              h("i", { style: { width: `${Math.min(100, pct * 50)}%` } }), h("b", { style: { left: "50%" } })),
            h("span", { class: "num", style: { minWidth: "3.2em", textAlign: "right" } }, `${Math.round(pct * 100)}%`))),
          h("td", { class: "r" }, int(s.ytd)), h("td", { class: "r" }, int(s.ytd_10yr_avg)));
      })))),
    f.ladder_temp_c?.latest != null ? h("p", { class: "muted", style: { marginTop: "8px" } },
      `Fish-ladder water temperature: ${f.ladder_temp_c.latest.toFixed(1)} °C (${(f.ladder_temp_c.latest * 9 / 5 + 32).toFixed(0)} °F) on ${fDate.format(ms(f.ladder_temp_c.date + "T12:00:00Z"))}. `,
      "Salmon begin to show heat stress above about 20 °C.") : null,
    h("p", { class: "faint", style: { fontSize: ".82rem" } }, "Source: Columbia River DART, University of Washington. The meter's tick marks the 10-year average; a full bar is twice average.")));

  // Daily chart for one species
  const card = h("div", { class: "card" });
  const select = h("select", { "aria-label": "Species" }, rows.map(([k, s]) => h("option", { value: k }, s.name)));
  const body = h("div");
  const t = f.dates.map(d => ms(d + "T12:00:00Z"));
  const paint = () => {
    body.textContent = "";
    const s = f.species[select.value];
    const lastIdx = s.daily.findLastIndex(x => x != null);
    const firstIdx = Math.max(0, s.daily.findIndex(x => x > 0) - 14);
    const sl = a => a.slice(firstIdx, lastIdx + 1);
    legend(body, [{ label: "This year", color: "var(--accent)" }, { label: "10-year average", color: "var(--text-3)", dash: true }]);
    lineChart(body, { series: [{ label: "This year", color: "var(--accent)", t: sl(t), v: sl(s.daily) },
      ...(s.daily_10yr_avg ? [{ label: "10-year average", color: "var(--text-3)", dash: true, width: 1.6, t: sl(t), v: sl(s.daily_10yr_avg) }] : [])],
      height: 220, snapMs: 864e5, yFmt: x => (x >= 1000 ? `${(x / 1000).toFixed(x >= 10000 ? 0 : 1)}k` : x.toFixed(0)), tipFmt: x => int(x),
      whenFmt: x => fDate.format(x) });
  };
  select.addEventListener("change", paint);
  card.append(h("div", { class: "card-head" }, h("h2", {}, "Daily counts this season"), select), body);
  v.append(card);
  paint();
}

// ---------- CHEMISTRY ----------
async function renderChem(v) {
  const c = await load("chem");
  v.textContent = "";
  if (!c.available) { v.append(h("div", { class: "card" }, "Water-quality data is not available right now.")); return; }
  const L = c.latest, val = (k, d) => (L[k] ? L[k].value.toFixed(d) : "—");
  const tile = (lab, value, sub) => h("div", { class: "tile" }, h("div", { class: "lab" }, lab), h("div", { class: "v" }, value), sub ? h("div", { class: "sub" }, sub) : null);
  const tC = L.water_temp?.value;
  v.append(h("div", { class: "card" }, h("h2", {}, "Water quality now"),
    h("p", { class: "muted" }, `Willamette River at Portland (USGS 14211720), about 5 miles from Hayden Island. Latest hourly means, ${L.water_temp ? fFull.format(ms(L.water_temp.time)) : ""}.`),
    h("div", { class: "tiles" },
      tile("Water temperature", `${val("water_temp", 1)} °C`, tC != null ? `${(tC * 9 / 5 + 32).toFixed(0)} °F` : null),
      tile("Dissolved oxygen", `${val("dissolved_oxygen", 1)} mg/L`, L.do_percent_saturation ? `${val("do_percent_saturation", 0)}% of saturation` : null),
      tile("pH", val("ph", 2)),
      tile("Specific conductance", `${val("specific_conductance", 0)} µS/cm`, "at 25 °C"),
      tile("Turbidity", `${val("turbidity", 1)} FNU`),
      tile("Nitrate", `${val("nitrate", 2)} mg/L`, "as N"),
      tile("Chlorophyll", `${val("chlorophyll_fchl", 2)} RFU`, "relative fluorescence"),
      tile("Phycocyanin", `${val("phycocyanin_fpc", 2)} RFU`, "cyanobacteria pigment (relative)"))));

  const t = c.t.map(s => s * 1000);
  const chart = (title, sub, k, color, fmt, refs = []) => {
    if (!c[k]) return null;
    const card = h("div", { class: "card" }, h("h2", {}, title), sub ? h("p", { class: "muted" }, sub) : null);
    lineChart(card, { series: [{ label: title, color, t, v: c[k] }], height: 180, refs, yFmt: fmt, tipFmt: fmt });
    return card;
  };
  v.append(chart("Oxygen, % of saturation", "Saturation is calculated from water temperature (Benson & Krause, 1 atm). Above 100% means photosynthesis is adding oxygen faster than it escapes.",
    "do_percent_saturation", "var(--accent)", x => `${x.toFixed(0)}%`, [{ y: 100, label: "100% saturated" }]));

  // Diel cycle: average by hour of day over the 14 days
  const byHour = k => {
    const s = Array(24).fill(0), n = Array(24).fill(0);
    const hr = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hourCycle: "h23" });
    c[k]?.forEach((x, i) => { if (x != null) { const hh = +hr.format(t[i]); s[hh] += x; n[hh] += 1; } });
    return s.map((x, i) => (n[i] ? x / n[i] : null));
  };
  const base = Date.UTC(2026, 0, 1, 8); // local midnight PST on a reference day
  const ht = [...Array(24).keys()].map(i => base + i * 3.6e6);
  const hourTicks = () => [0, 6, 12, 18].map(i => ({ t: base + i * 3.6e6, label: ["12 AM", "6 AM", "Noon", "6 PM"][i / 6] }));
  const whenHr = x => new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric" }).format(x);
  const diel = h("div", { class: "card" }, h("h2", {}, "The daily breathing of the river"),
    h("p", { class: "muted" }, "Average by hour of day over the last 14 days. Algae photosynthesize by day, adding oxygen and using up CO₂ (which raises pH); at night respiration reverses both."));
  for (const [k, lab, fmt] of [["do_percent_saturation", "Oxygen, % saturation", x => `${x.toFixed(0)}%`], ["ph", "pH", x => x.toFixed(2)]]) {
    if (!c[k]) continue;
    const box = h("div", {}, h("div", { class: "small-title" }, lab));
    diel.append(box);
    lineChart(box, { series: [{ label: lab, color: "var(--accent)", t: ht, v: byHour(k) }], height: 130, yFmt: fmt, tipFmt: fmt,
      xTicks: hourTicks, whenFmt: whenHr });
  }
  v.append(diel);
  v.append(chart("Water temperature", null, "water_temp", "var(--c-bonneville)", x => `${x.toFixed(1)}°`));
  v.append(chart("Specific conductance", "Dissolved salts. Rain and snowmelt dilute it; low flow concentrates it.", "specific_conductance", "var(--c-willamette)", x => x.toFixed(0)));
  v.append(chart("Phycocyanin (cyanobacteria pigment)", "A relative index, not a toxin measurement. Sustained rises can signal a blue-green algae bloom.", "phycocyanin_fpc", "var(--c-spring_neap)", x => x.toFixed(2)));
}

// ---------- METHOD ----------
async function renderMethod(v) {
  const [m, n] = await Promise.all([load("model"), load("now")]);
  v.textContent = "";
  const terms = Object.entries(m.coef);
  const eq = "stage = " + terms.map(([k, c], i) => `${i ? (c < 0 ? " − " : " + ") : ""}${Math.abs(c).toFixed(4)}${k === "const" ? "" : "·" + k}`).join("");
  v.append(h("div", { class: "card", style: { borderColor: "var(--accent)" } }, h("h2", {}, "The full story"),
    h("p", {}, "This tab is the short model card. The ", h("a", { href: "guide.html" }, "River Brain guide"),
      " explains everything in depth: each data source and its quirks, the physics of every driver, how the model was found and tested, and what it can't do yet.")));
  v.append(h("div", { class: "card" }, h("h2", {}, "How River Brain works"),
    h("p", {}, "Every hour, a free GitHub Action fetches the river level, NOAA tide predictions, Bonneville Dam releases, tributary flows and Astoria sea level; checks them for bad values; and applies a statistical model fitted to five years of history. Each driver's contribution is the model term for it, so the bars on the Now tab always add up to the observed change (with whatever the model misses shown as “unexplained”)."),
    h("p", {}, "The model is ordinary least squares on physically motivated terms:"),
    h("div", { class: "equation" }, eq.replace(/ \+ /g, "\n        + ").replace(/ − /g, "\n        − ")),
    h("div", { class: "table-wrap", style: { marginTop: "10px" } }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Term"), h("th", { class: "r" }, "Coefficient"), h("th", {}, "Meaning"))),
      h("tbody", {}, terms.map(([k, c]) => h("tr", {}, h("td", {}, h("code", {}, k)), h("td", { class: "r" }, c.toFixed(4)),
        h("td", {}, k === "const" ? "intercept (ft, USGS gauge datum)" : m.feature_doc[k] || ""))))))));

  const phys = m.physics.by_bonneville_flow;
  v.append(h("div", { class: "card" }, h("h2", {}, "What the coefficients say about the river"),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Bonneville flow"), h("th", { class: "r" }, "+10 kcfs at the dam"), h("th", { class: "r" }, "Tide size vs NOAA"), h("th", { class: "r" }, "Tide timing"))),
      h("tbody", {}, Object.entries(phys).map(([q, r]) => h("tr", {}, h("td", {}, `${q} kcfs`),
        h("td", { class: "r" }, `${ft(r.ft_per_10kcfs_bonneville)} ft`), h("td", { class: "r" }, `${r.tide_gain_vs_noaa.toFixed(2)}×`),
        h("td", { class: "r" }, `${ft(r.tide_timing_shift_min, 0)} min`)))))),
    h("ul", {},
      h("li", {}, `Travel time from Bonneville: about ${hours(m.physics.bonneville_lag_centroid_h)} hours (fitted from the data, not assumed).`),
      m.physics.ft_per_10kcfs_willamette ? h("li", {}, `Willamette: +10 kcfs raises the river here about ${ft(Object.values(m.physics.ft_per_10kcfs_willamette)[0])} ft.`) : null,
      m.physics.ft_per_10kcfs_sandy != null ? h("li", {}, `Sandy River: +10 kcfs → ${ft(m.physics.ft_per_10kcfs_sandy)} ft. Large for a small river, so it likely also stands in for other rain-fed local streams.`) : null,
      m.physics.ft_per_ft_astoria_surge != null ? h("li", {}, `Ocean: 1 ft of storm surge at Astoria raises Hayden Island about ${m.physics.ft_per_ft_astoria_surge.toFixed(2)} ft.`) : null,
      h("li", {}, "At high flow the tide shrinks to a fraction of NOAA's prediction and its timing becomes poorly defined; its effect there is small either way."))));

  const pooled = Object.entries(m.cv.pooled_rmse_ft).sort((a, b) => a[1] - b[1]);
  v.append(h("div", { class: "card" }, h("h2", {}, "How it was tested"),
    h("p", {}, `Trained on ${m.training.start_utc.slice(0, 10)} to ${m.training.end_utc.slice(0, 10)} (${int(m.training.hours_used)} hours; Bonneville ${m.training.bonneville_range_kcfs.join("–")} kcfs). `,
      "Each water year was predicted by a model fitted without that year. Candidate models competed under a rule fixed in advance: ", h("i", {}, m.cv.selection_rule), "."),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Model"), h("th", { class: "r" }, "Held-out error (ft)"), h("th", { class: "r" }, "R²"))),
      h("tbody", {}, pooled.map(([k, e]) => h("tr", { style: k === m.model_name ? { fontWeight: "650" } : {} },
        h("td", {}, k === m.model_name ? `${k} ✓ selected` : k), h("td", { class: "r" }, e.toFixed(3)), h("td", { class: "r" }, m.cv.pooled_r2[k].toFixed(3)))))))));

  const src = [
    ["River level: USGS 14144700, Columbia River at Vancouver", "https://waterdata.usgs.gov/monitoring-location/USGS-14144700/"],
    ["Tide predictions: NOAA 9440083 Vancouver", "https://tidesandcurrents.noaa.gov/stationhome.html?id=9440083"],
    ["Storm surge: NOAA 9439040 Astoria", "https://tidesandcurrents.noaa.gov/stationhome.html?id=9439040"],
    ["Bonneville outflow: US Army Corps of Engineers (Dataquery / CWMS)", "https://www.nwd-wc.usace.army.mil/dd/common/dataquery/www/"],
    ["Willamette flow & water quality: USGS 14211720", "https://waterdata.usgs.gov/monitoring-location/USGS-14211720/"],
    ["Sandy River: USGS 14142500", "https://waterdata.usgs.gov/monitoring-location/USGS-14142500/"],
    ["NWS forecast: Northwest River Forecast Center, gauge VAPW1", "https://water.noaa.gov/gauges/VAPW1"],
    ["Fish counts: Columbia River DART, University of Washington", "https://www.cbr.washington.edu/dart/query/adult_daily"],
  ];
  v.append(h("div", { class: "card" }, h("h2", {}, "Data sources"),
    h("ul", {}, src.map(([t, u]) => h("li", {}, h("a", { href: u, target: "_blank", rel: "noopener" }, t)))),
    h("p", { class: "muted" }, `Model fitted ${fDate.format(ms(m.fitted_utc))}. `,
      h("a", { href: "guide.html" }, "Read the full guide"), ": where the data comes from, how the model was found, and its limits",
      REPO ? [". Code, notebook and fit report: ", h("a", { href: REPO, target: "_blank", rel: "noopener" }, "GitHub repository")] : null, ".")));
  v.append(freshnessCard(n));
}

// ---------- routing ----------
const VIEWS = { now: renderNow, forecast: renderForecast, explore: renderExplore, fish: renderFish, chemistry: renderChem, method: renderMethod };
const rendered = new Set();
async function route() {
  const name = (location.hash.slice(1) || "now").toLowerCase();
  const view = VIEWS[name] ? name : "now";
  for (const a of document.querySelectorAll("nav.tabs a")) {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  for (const s of document.querySelectorAll("section.view")) s.hidden = s.id !== view;
  if (rendered.has(view)) return;
  const el = $(`#${view}`);
  try {
    await VIEWS[view](el);
    rendered.add(view);
  } catch (e) {
    el.textContent = "";
    el.append(h("div", { class: "card" }, h("h2", {}, "Couldn't load this view"), h("p", { class: "muted" }, String(e.message || e))));
  }
}
window.addEventListener("hashchange", route);
route();
const tickUpdated = () => load("now").then(n => { $("#updated").textContent = `Updated ${ago(n.generated)}`; }).catch(() => {});
tickUpdated();
setInterval(tickUpdated, 60_000);
// A page left open (or reopened from the home screen) refetches when it comes back into view.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  load("now").then(n => {
    if (Date.now() - ms(n.generated) < 15 * 60_000) return;
    for (const k of Object.keys(cache)) delete cache[k];
    rendered.clear();
    route();
    tickUpdated();
  });
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
