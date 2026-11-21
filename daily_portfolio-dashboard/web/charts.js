/* 의존성 없는 작은 SVG 차트 모음 (선·누적 면적·막대·도넛) + 호버 툴팁
   색은 CSS 변수 문자열(예: "var(--s1)")로 받아 다크모드에서도 자동으로 바뀝니다. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const M = { l: 62, r: 14, t: 12, b: 30 };
  let tip;

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function tooltip() {
    if (!tip) { tip = document.createElement("div"); tip.className = "viz-tip"; document.body.appendChild(tip); }
    return tip;
  }
  function showTip(html, cx, cy) {
    const t = tooltip(); t.innerHTML = html; t.style.display = "block";
    const w = t.offsetWidth, h = t.offsetHeight;
    let x = cx + 14, y = cy - h - 10;
    if (x + w > window.innerWidth - 6) x = cx - w - 14;
    if (y < 6) y = cy + 16;
    t.style.left = (x + window.scrollX) + "px"; t.style.top = (y + window.scrollY) + "px";
  }
  function hideTip() { if (tip) tip.style.display = "none"; }

  function niceTicks(min, max, n) {
    if (min === max) { min -= 1; max += 1; }
    const span = max - min, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const err = step0 / mag, step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
    for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function legend(chartBox, series) {
    const box = chartBox.parentElement && chartBox.parentElement.querySelector(".viz-legend-slot");
    if (!box) return;
    box.innerHTML = "";
    if (series.length < 2) return;
    const lg = document.createElement("div"); lg.className = "viz-legend";
    series.forEach(s => {
      const i = document.createElement("span");
      i.innerHTML = `<i style="background:${s.color};${s.dash ? "height:0;border-top:2px dashed " + s.color + ";background:none" : ""}"></i>${s.name}`;
      lg.appendChild(i);
    });
    box.appendChild(lg);
  }
  function frame(box, height) {
    box.innerHTML = "";
    const W = Math.max(300, box.clientWidth || 600), H = height || 260;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, class: "viz-svg", role: "img" });
    return { svg, W, H, iw: W - M.l - M.r, ih: H - M.t - M.b };
  }
  function yAxis(svg, ticks, y, W, fmt) {
    ticks.forEach(v => {
      el("line", { x1: M.l, x2: W - M.r, y1: y(v), y2: y(v), class: v === 0 ? "viz-zero" : "viz-grid" }, svg);
      const t = el("text", { x: M.l - 8, y: y(v) + 4, "text-anchor": "end", class: "viz-tick" }, svg);
      t.textContent = fmt(v);
    });
  }
  const pd = s => new Date(s + "T00:00:00").getTime();
  const shortDate = ms => { const d = new Date(ms); return `${String(d.getFullYear()).slice(2)}.${d.getMonth() + 1}`; };

  /* 선 차트. opts: {dates, series:[{name,color,values,dash}], fmt, tipFmt, stack100, height, zero, marker:{index,label}} */
  function line(box, o) {
    const fmt = o.fmt || (v => v.toLocaleString("ko-KR"));
    const tf = o.tipFmt || fmt;
    legend(box, o.series);
    const f = frame(box, o.height); const { svg, W, H, iw, ih } = f;
    const xs = o.dates.map(pd), x0 = xs[0], x1 = xs[xs.length - 1] === x0 ? x0 + 864e5 : xs[xs.length - 1];
    const x = t => M.l + (t - x0) / (x1 - x0) * iw;
    let stacked = null, lo = Infinity, hi = -Infinity;
    if (o.stack100) {
      stacked = []; const acc = xs.map(() => 0);
      o.series.forEach(s => { const base = acc.slice(); s.values.forEach((v, i) => acc[i] += (v || 0)); stacked.push({ base, top: acc.slice() }); });
      lo = 0; hi = 100;
    } else {
      o.series.forEach(s => s.values.forEach(v => { if (v != null && isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      if (o.zero !== false) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    }
    const ticks = o.stack100 ? [0, 25, 50, 75, 100] : niceTicks(lo, hi, 4);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const y = v => M.t + ih - (v - y0) / (y1 - y0) * ih;
    yAxis(svg, ticks, y, W, o.stack100 ? (v => v + "%") : fmt);
    // x 눈금
    const nT = Math.max(2, Math.min(7, Math.floor(iw / 80)));
    for (let k = 0; k <= nT; k++) {
      const t = x0 + (x1 - x0) * k / nT, tx = el("text", { x: x(t), y: H - 8, "text-anchor": k === 0 ? "start" : k === nT ? "end" : "middle", class: "viz-tick" }, svg);
      tx.textContent = shortDate(t);
    }
    if (o.stack100) {
      o.series.forEach((s, si) => {
        const st = stacked[si];
        let d = "M" + xs.map((t, i) => `${x(t)},${y(st.top[i])}`).join("L");
        d += "L" + xs.map((t, i) => `${x(t)},${y(st.base[i])}`).reverse().join("L") + "Z";
        el("path", { d, style: `fill:${s.color};stroke:var(--surface);stroke-width:1` }, svg);
      });
    } else {
      (o.bands || []).forEach(b => { // 두 선 사이 영역 (예: 평가금액 vs 원금)
        const a = o.series[b.a].values, c = o.series[b.b].values;
        let d = "M" + xs.map((t, i) => `${x(t)},${y(a[i] ?? 0)}`).join("L");
        d += "L" + xs.map((t, i) => `${x(t)},${y(c[i] ?? 0)}`).reverse().join("L") + "Z";
        el("path", { d, style: `fill:${b.color};opacity:.14` }, svg);
      });
      o.series.forEach(s => {
        let d = "", pen = false;
        s.values.forEach((v, i) => {
          if (v == null || !isFinite(v)) { pen = false; return; }
          d += (pen ? "L" : "M") + x(xs[i]) + "," + y(v); pen = true;
        });
        el("path", { d, style: `fill:none;stroke:${s.color};stroke-width:2;stroke-linejoin:round${s.dash ? ";stroke-dasharray:5 4" : ""}` }, svg);
      });
    }
    if (o.marker) {
      const mx = x(xs[o.marker.index]);
      el("line", { x1: mx, x2: mx, y1: M.t, y2: M.t + ih, class: "viz-marker" }, svg);
      const t = el("text", { x: mx - 4, y: M.t + 10, "text-anchor": "end", class: "viz-tick viz-marker-t" }, svg); t.textContent = o.marker.label;
    }
    // 크로스헤어
    const cross = el("line", { y1: M.t, y2: M.t + ih, class: "viz-cross", style: "display:none" }, svg);
    const dots = o.series.map(s => el("circle", { r: 4, style: `fill:${s.color};stroke:var(--surface);stroke-width:2;display:none` }, svg));
    const hit = el("rect", { x: M.l, y: M.t, width: iw, height: ih, style: "fill:transparent;cursor:crosshair" }, svg);
    function move(ev) {
      const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
      const t = x0 + (px - M.l) / iw * (x1 - x0);
      let i = 0, best = Infinity; xs.forEach((v, k) => { const dd = Math.abs(v - t); if (dd < best) { best = dd; i = k; } });
      const cx = x(xs[i]); cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.style.display = "";
      let html = `<b>${o.dates[i]}</b>`;
      o.series.forEach((s, si) => {
        const v = o.stack100 ? s.values[i] : s.values[i];
        const yy = o.stack100 ? stacked[si].top[i] : v;
        if (v == null || !isFinite(v) || (o.stack100 && v <= 0)) { dots[si].style.display = "none"; return; }
        dots[si].setAttribute("cx", cx); dots[si].setAttribute("cy", y(yy)); dots[si].style.display = "";
        html += `<div><i style="background:${s.color}"></i>${s.name}<span>${o.stack100 ? v.toFixed(1) + "%" : tf(v)}</span></div>`;
      });
      showTip(html, ev.clientX, ev.clientY);
    }
    hit.addEventListener("pointermove", move); hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => { cross.style.display = "none"; dots.forEach(d => d.style.display = "none"); hideTip(); });
    box.appendChild(svg);
  }

  /* 막대 차트. opts: {labels, series:[{name,color,values}], fmt, signColor:{pos,neg}, height} */
  function bars(box, o) {
    const fmt = o.fmt || (v => v.toLocaleString("ko-KR"));
    legend(box, o.series);
    const f = frame(box, o.height); const { svg, W, H, iw, ih } = f;
    let lo = 0, hi = 0;
    o.series.forEach(s => s.values.forEach(v => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    const ticks = niceTicks(lo, hi, 4), y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const y = v => M.t + ih - (v - y0) / (y1 - y0) * ih;
    yAxis(svg, ticks, y, W, fmt);
    const n = o.labels.length, band = iw / n, ns = o.series.length;
    const bw = Math.max(3, Math.min(28, (band * 0.72 - (ns - 1) * 2) / ns));
    const every = Math.ceil(n / Math.max(1, Math.floor(iw / 46)));
    o.labels.forEach((lb, i) => {
      if (i % every === 0) { const t = el("text", { x: M.l + band * (i + .5), y: H - 8, "text-anchor": "middle", class: "viz-tick" }, svg); t.textContent = lb; }
      const gx = M.l + band * (i + .5) - (ns * bw + (ns - 1) * 2) / 2;
      o.series.forEach((s, si) => {
        const v = s.values[i]; if (v == null || v === 0) return;
        const c = o.signColor ? (v >= 0 ? o.signColor.pos : o.signColor.neg) : s.color;
        const top = y(Math.max(v, 0)), bot = y(Math.min(v, 0));
        const r = el("rect", { x: gx + si * (bw + 2), y: top, width: bw, height: Math.max(1, bot - top), rx: 2, style: `fill:${c}` }, svg);
        const hitr = el("rect", { x: M.l + band * i, y: M.t, width: band, height: ih, style: "fill:transparent" }, svg);
        const h = ev => {
          let html = `<b>${lb}</b>`;
          o.series.forEach(ss => { const vv = ss.values[i]; if (vv != null) html += `<div><i style="background:${o.signColor ? (vv >= 0 ? o.signColor.pos : o.signColor.neg) : ss.color}"></i>${ss.name}<span>${fmt(vv, true)}</span></div>`; });
          if (o.extra) html += o.extra(i);
          showTip(html, ev.clientX, ev.clientY);
        };
        hitr.addEventListener("pointermove", h); hitr.addEventListener("pointerdown", h); hitr.addEventListener("pointerleave", hideTip);
        void r;
      });
    });
    box.appendChild(svg);
  }

  /* 도넛. opts: {labels, values, colors, fmt, center} */
  function donut(box, o) {
    box.innerHTML = "";
    const size = 190, R = 86, r0 = 56, cx = size / 2, cy = size / 2;
    const wrap = document.createElement("div"); wrap.className = "viz-donut";
    const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img" });
    const total = o.values.reduce((a, b) => a + Math.max(0, b), 0) || 1;
    let a0 = -Math.PI / 2;
    const lg = document.createElement("div"); lg.className = "viz-donut-legend";
    o.values.forEach((v, i) => {
      if (v <= 0) return;
      const a1 = a0 + v / total * Math.PI * 2, big = a1 - a0 > Math.PI ? 1 : 0;
      const p = (a, rr) => `${cx + rr * Math.cos(a)},${cy + rr * Math.sin(a)}`;
      const d = (v / total > 0.9999) ?
        `M${cx},${cy - R}A${R},${R} 0 1 1 ${cx - .01},${cy - R}L${cx - .01},${cy - r0}A${r0},${r0} 0 1 0 ${cx},${cy - r0}Z` :
        `M${p(a0, R)}A${R},${R} 0 ${big} 1 ${p(a1, R)}L${p(a1, r0)}A${r0},${r0} 0 ${big} 0 ${p(a0, r0)}Z`;
      const path = el("path", { d, style: `fill:${o.colors[i]};stroke:var(--surface);stroke-width:2` }, svg);
      const h = ev => showTip(`<b>${o.labels[i]}</b><div>${(v / total * 100).toFixed(1)}%<span>${o.fmt ? o.fmt(v) : v}</span></div>`, ev.clientX, ev.clientY);
      path.addEventListener("pointermove", h); path.addEventListener("pointerdown", h); path.addEventListener("pointerleave", hideTip);
      const row = document.createElement("div");
      row.innerHTML = `<i style="background:${o.colors[i]}"></i><span>${o.labels[i]}</span><b>${(v / total * 100).toFixed(1)}%</b>`;
      lg.appendChild(row);
      a0 = a1;
    });
    if (o.center) { const t = el("text", { x: cx, y: cy + 5, "text-anchor": "middle", class: "viz-center" }, svg); t.textContent = o.center; }
    wrap.appendChild(svg); wrap.appendChild(lg); box.appendChild(wrap);
  }

  window.Charts = { line, bars, donut, hideTip };
})();
