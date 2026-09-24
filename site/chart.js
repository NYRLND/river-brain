// Minimal SVG time-series chart. No dependencies.
// lineChart(el, {series, height, yFmt, refs, now, yDomain, zeroLine})
//   series: [{label, color (CSS var or color), t: [ms], v: [number|null], dash?, width?,
//             band?: {lo: [], hi: []}, noTip?}]
// Crosshair snaps to the nearest time; the tooltip lists every series at that time.
// Arrow keys move the crosshair when the chart has focus.

const TZ = "America/Los_Angeles";
const SVGNS = "http://www.w3.org/2000/svg";
const fmtDay = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric" });
const fmtHour = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric" });
const fmtWhen = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const hourOf = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hourCycle: "h23" });

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return { ticks: out, step };
}

function timeTicks(t0, t1, widthPx) {
  // Local-midnight ticks for multi-day spans; 6-hourly ticks for short spans.
  const hours = (t1 - t0) / 3.6e6;
  const out = [];
  const stepH = hours <= 60 ? 6 : 24;
  const maxTicks = Math.max(2, Math.floor(widthPx / 70));
  for (let t = Math.ceil(t0 / 3.6e6) * 3.6e6; t <= t1; t += 3.6e6) {
    const h = +hourOf.format(t);
    if (h % stepH === 0) out.push(t);
  }
  const every = Math.ceil(out.length / maxTicks);
  return out.filter((_, i) => i % every === 0).map(t => ({
    t, label: (+hourOf.format(t) === 0 || stepH === 24) ? fmtDay.format(t).replace(",", "") : fmtHour.format(t),
  }));
}

function nearestIndex(t, x) {
  let lo = 0, hi = t.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (t[m] < x) lo = m; else hi = m; }
  return Math.abs(t[lo] - x) <= Math.abs(t[hi] - x) ? lo : hi;
}

export function legend(container, items) {
  const div = document.createElement("div");
  div.className = "legend";
  for (const it of items) {
    const s = document.createElement("span");
    const k = document.createElement("i");
    k.className = "lkey" + (it.dash ? " dash" : "") + (it.area ? " area" : "");
    if (it.area) k.style.background = it.color; else k.style.borderTopColor = it.color;
    s.append(k, document.createTextNode(it.label));
    div.appendChild(s);
  }
  container.appendChild(div);
}

export function lineChart(container, opts) {
  const state = { idx: null };
  const wrap = document.createElement("div");
  wrap.className = "chart";
  container.appendChild(wrap);
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.hidden = true;

  function draw() {
    const W = Math.max(280, wrap.clientWidth || container.clientWidth || 600);
    const H = opts.height || 220;
    const m = { l: 40, r: 12, t: 10, b: 24 };
    const series = opts.series.filter(s => s.t && s.t.length);
    const allT = series.flatMap(s => s.t);
    const t0 = opts.tDomain?.[0] ?? Math.min(...allT), t1 = opts.tDomain?.[1] ?? Math.max(...allT);
    let ys = series.flatMap(s => [...s.v, ...(s.band ? [...s.band.lo, ...s.band.hi] : [])]).filter(v => v != null && isFinite(v));
    for (const r of opts.refs || []) if (r.alwaysShow) ys.push(r.y);
    if (opts.zeroLine) ys.push(0);
    let [y0, y1] = opts.yDomain || [Math.min(...ys), Math.max(...ys)];
    const pad = (y1 - y0) * 0.06 || 0.5;
    y0 -= pad; y1 += pad;
    const { ticks } = niceTicks(y0, y1, H < 160 ? 3 : 5);
    y0 = Math.min(y0, ticks[0]); y1 = Math.max(y1, ticks[ticks.length - 1]);
    const X = t => m.l + (t - t0) / (t1 - t0 || 1) * (W - m.l - m.r);
    const Y = v => m.t + (1 - (v - y0) / (y1 - y0 || 1)) * (H - m.t - m.b);

    wrap.textContent = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", tabindex: "0",
      "aria-label": opts.ariaLabel || series.map(s => s.label).join(", ") });
    const grid = el("g", { class: "grid" }, svg);
    const axis = el("g", { class: "axis" }, svg);
    for (const v of ticks) {
      el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, grid);
      const tx = el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end" }, axis);
      tx.textContent = opts.yFmt ? opts.yFmt(v) : v;
    }
    for (const { t, label } of (opts.xTicks ? opts.xTicks(t0, t1) : timeTicks(t0, t1, W - m.l - m.r))) {
      const tx = el("text", { x: X(t), y: H - 6, "text-anchor": "middle" }, axis);
      tx.textContent = label;
    }
    for (const r of opts.refs || []) {
      if (r.y < y0 || r.y > y1) continue;
      const g = el("g", { class: "ref" }, svg);
      el("line", { x1: m.l, x2: W - m.r, y1: Y(r.y), y2: Y(r.y), "stroke-dasharray": r.dash ? "4 3" : "" }, g);
      const tx = el("text", { x: W - m.r, y: Y(r.y) - 4, "text-anchor": "end" }, g);
      tx.textContent = r.label;
    }
    if (opts.now != null && opts.now >= t0 && opts.now <= t1) {
      const g = el("g", { class: "now" }, svg);
      el("line", { x1: X(opts.now), x2: X(opts.now), y1: m.t, y2: H - m.b }, g);
      const tx = el("text", { x: X(opts.now) + 4, y: m.t + 10 }, g);
      tx.textContent = "now";
    }
    for (const s of series) {
      if (s.band) {
        let d = "", back = "";
        s.t.forEach((t, i) => {
          const lo = s.band.lo[i], hi = s.band.hi[i];
          if (lo == null || hi == null) return;
          d += (d ? "L" : "M") + X(t).toFixed(1) + "," + Y(hi).toFixed(1);
          back = "L" + X(t).toFixed(1) + "," + Y(lo).toFixed(1) + back;
        });
        if (d) el("path", { d: d + back + "Z", fill: s.bandColor || "var(--band)", stroke: "none" }, svg);
      }
    }
    for (const s of series) {
      let d = "", pen = false;
      s.t.forEach((t, i) => {
        const v = s.v[i];
        if (v == null || !isFinite(v) || t < t0 || t > t1) { pen = false; return; }
        d += (pen ? "L" : "M") + X(t).toFixed(1) + "," + Y(v).toFixed(1);
        pen = true;
      });
      el("path", { d, fill: "none", stroke: s.color, "stroke-width": s.width || 2, "stroke-linejoin": "round",
        "stroke-linecap": "round", "stroke-dasharray": s.dash ? "5 4" : "" }, svg);
    }
    const cross = el("line", { class: "cross", y1: m.t, y2: H - m.b, visibility: "hidden" }, svg);
    const dots = series.map(s => el("circle", { class: "dot", r: 4, fill: s.color, visibility: "hidden" }, svg));
    const hit = el("rect", { x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: "transparent" }, svg);
    wrap.appendChild(svg);
    wrap.appendChild(tip);

    // union of times for keyboard stepping / snapping
    const union = [...new Set(allT)].filter(t => t >= t0 && t <= t1).sort((a, b) => a - b);

    function show(t) {
      const tt = union[nearestIndex(union, t)];
      cross.setAttribute("x1", X(tt)); cross.setAttribute("x2", X(tt)); cross.setAttribute("visibility", "visible");
      tip.textContent = "";
      const when = document.createElement("div");
      when.className = "when";
      when.textContent = (opts.whenFmt || (x => fmtWhen.format(x)))(tt);
      tip.appendChild(when);
      series.forEach((s, k) => {
        const i = nearestIndex(s.t, tt);
        const ok = Math.abs(s.t[i] - tt) <= (opts.snapMs || 5.4e6) && s.v[i] != null && isFinite(s.v[i]);
        dots[k].setAttribute("visibility", ok ? "visible" : "hidden");
        if (!ok) return;
        dots[k].setAttribute("cx", X(s.t[i])); dots[k].setAttribute("cy", Y(s.v[i]));
        if (s.noTip) return;
        const row = document.createElement("div");
        row.className = "row";
        const key = document.createElement("i");
        key.className = "lkey" + (s.dash ? " dash" : "");
        key.style.borderTopColor = s.color;
        const b = document.createElement("b");
        b.textContent = (opts.tipFmt || opts.yFmt || (v => v.toFixed(2)))(s.v[i]);
        const lab = document.createElement("span");
        lab.textContent = s.label;
        row.append(key, b, lab);
        tip.appendChild(row);
      });
      tip.hidden = false;
      const px = X(tt) / W * wrap.clientWidth;
      const tw = tip.offsetWidth;
      tip.style.left = Math.min(Math.max(0, px + 12), wrap.clientWidth - tw) + "px";
      if (px + 12 + tw > wrap.clientWidth) tip.style.left = Math.max(0, px - tw - 12) + "px";
      tip.style.top = "4px";
      state.idx = union.indexOf(tt);
    }
    function hide() {
      cross.setAttribute("visibility", "hidden");
      dots.forEach(d => d.setAttribute("visibility", "hidden"));
      tip.hidden = true;
    }
    const toT = e => {
      const r = svg.getBoundingClientRect();
      return t0 + ((e.clientX - r.left) / r.width * W - m.l) / (W - m.l - m.r) * (t1 - t0);
    };
    hit.addEventListener("pointermove", e => show(toT(e)));
    hit.addEventListener("pointerdown", e => show(toT(e)));
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("blur", hide);
    svg.addEventListener("focus", () => show(union[state.idx ?? union.length - 1]));
    svg.addEventListener("keydown", e => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const i = Math.min(union.length - 1, Math.max(0, (state.idx ?? union.length - 1) + (e.key === "ArrowRight" ? 1 : -1)));
      show(union[i]);
    });
  }

  draw();
  let last = wrap.clientWidth;
  new ResizeObserver(() => { if (Math.abs(wrap.clientWidth - last) > 4) { last = wrap.clientWidth; draw(); } }).observe(wrap);
  return { redraw: draw };
}
