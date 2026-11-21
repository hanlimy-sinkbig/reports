/* 포트폴리오 대시보드
   - 매매일지 CSV는 브라우저 안에서만 읽습니다 (서버 전송 없음, 이 기기 localStorage에만 보관).
   - 시세: GitHub Actions가 코스피·코스닥·국내 ETF·미국 상장 종목 전체를 market-data 브랜치에 종목별 파일로 저장해 둡니다.
     페이지는 매매일지에 있는 종목 파일만 골라 읽습니다. 파일이 없으면 최근 체결가로 대신 계산합니다. */
(function () {
  "use strict";
  const $ = s => document.querySelector(s);
  const LS_KEY = "pf_csv_v1";
  const COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];
  const SECTOR_HINT = { "005930": "반도체", "000660": "반도체", LRCX: "반도체", SNDK: "반도체", MU: "반도체", NVDA: "반도체", AMAT: "반도체", TSM: "반도체", ASML: "반도체", AVGO: "반도체", AMD: "반도체", INTC: "반도체" };
  const DATA_BASE = (() => {
    const h = location.hostname;
    if (h.endsWith("github.io")) return `https://raw.githubusercontent.com/${h.split(".")[0]}/${location.pathname.split("/")[1]}/market-data/data/`;
    return "data/";   // 로컬 테스트용
  })();
  const ENC_URL = (() => {
    const h = location.hostname;
    if (h.endsWith("github.io")) return `https://raw.githubusercontent.com/${h.split(".")[0]}/${location.pathname.split("/")[1]}/journal/journal.enc.json`;
    return "journal.enc.json";
  })();
  const PW_KEY = "pf_pw_v1";
  const S = { raw: [], rows: [], inst: {}, keys: [], prices: null, base: null, edits: {}, fxEdit: null, scenario: false, range: "ALL", warnings: [], pFrom: "", pTo: "" };

  /* ───────── 형식 ───────── */
  const nf = (v, d = 0) => (v == null || !isFinite(v)) ? "–" : v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const won = v => (v == null || !isFinite(v)) ? "–" : nf(Math.round(v)) + "원";
  const short = v => {
    if (v == null || !isFinite(v)) return "–";
    const a = Math.abs(v);
    if (a >= 1e8) return (v / 1e8).toFixed(a >= 1e10 ? 0 : a >= 1e9 ? 1 : 2) + "억";
    if (a >= 1e4) return nf(Math.round(v / 1e4)) + "만";
    return nf(Math.round(v));
  };
  const pct = (v, d = 1) => (v == null || !isFinite(v)) ? "–" : (v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
  const signed = v => (v == null || !isFinite(v)) ? "–" : (v > 0 ? "+" : "") + nf(Math.round(v)) + "원";
  const cls = v => v > 0 ? "up" : v < 0 ? "down" : "";
  const px = (v, cur) => (v == null || !isFinite(v)) ? "–" : cur === "USD" ? "$" + nf(v, 2) : nf(Math.round(v)) + "원";
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const today = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const month = d => d.slice(0, 7);
  const mLabel = m => `${m.slice(2, 4)}.${+m.slice(5, 7)}`;

  /* ───────── CSV ───────── */
  function decode(buf) {
    try { return new TextDecoder("utf-8", { fatal: true }).decode(buf); }
    catch (e) { return new TextDecoder("euc-kr").decode(buf); }   // 엑셀 한글 CSV(CP949)
  }
  function parseCSV(text) {
    text = text.replace(/^﻿/, "");
    const out = []; let row = [], f = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
      else if (c === '"') q = true;
      else if (c === ",") { row.push(f); f = ""; }
      else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(f); out.push(row); row = []; f = ""; }
      else f += c;
    }
    if (f !== "" || row.length) { row.push(f); out.push(row); }
    return out.filter(r => r.some(x => x.trim() !== ""));
  }
  const ALIAS = {
    date: ["날짜", "일자", "거래일", "체결일", "date"], account: ["계좌"], market: ["구분", "시장"], name: ["종목", "종목명"],
    ticker: ["티커", "종목코드", "코드", "ticker", "symbol"], side: ["매매", "매매구분", "거래구분", "유형"],
    price: ["단가", "매매가", "매수가", "체결가", "가격", "금액"], qty: ["수량"], cur: ["통화"], fx: ["환율"],
    fee: ["수수료"], tax: ["세금", "제세금"], target: ["목표가"], stop: ["손절가"], reason: ["매매사유", "사유"], memo: ["메모", "비고"]
  };
  const num = v => { if (v == null) return null; const s = String(v).replace(/[,\s₩$원]/g, ""); if (s === "") return null; const n = Number(s); return isFinite(n) ? n : null; };
  function normDate(s) {
    const m = String(s).trim().match(/(\d{4})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})/);
    return m ? `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}` : null;
  }
  function normSide(s) {
    s = String(s || "").trim().toLowerCase();
    if (/매수|buy/.test(s)) return "BUY"; if (/매도|sell/.test(s)) return "SELL"; if (/배당|div/.test(s)) return "DIV";
    if (/입금|deposit/.test(s)) return "DEP"; if (/출금|withdraw/.test(s)) return "WD"; if (/분할|split/.test(s)) return "SPLIT";
    if (/입고|transfer.?in/.test(s)) return "TIN"; if (/이자|interest|기타수익/.test(s)) return "INT";
    return null;
  }
  const SIDE_KO = { BUY: "매수", SELL: "매도", DIV: "배당", DEP: "입금", WD: "출금", SPLIT: "분할", TIN: "입고", INT: "이자" };
  const HOLD_SIDES = ["BUY", "SELL", "DIV", "SPLIT", "TIN"];   // 종목이 있어야 하는 매매

  function ingest(text) {
    const grid = parseCSV(text);
    if (grid.length < 2) throw new Error("CSV에 데이터가 없습니다.");
    const head = grid[0].map(h => h.trim());
    const col = {};
    for (const k in ALIAS) col[k] = head.findIndex(h => ALIAS[k].some(a => h.toLowerCase() === a.toLowerCase()));
    if (col.date < 0 || col.side < 0 || col.price < 0) throw new Error("필수 열(날짜·매매·단가)을 찾지 못했습니다. 첫 줄 제목을 확인하세요.");
    S.warnings = []; S.raw = []; S.rows = [];
    grid.slice(1).forEach((r, i) => {
      const g = k => col[k] >= 0 ? (r[col[k]] ?? "").trim() : "";
      const rec = {
        line: i + 2, date: normDate(g("date")), account: g("account"), market: g("market"), name: g("name"), ticker: g("ticker").toUpperCase(),
        side: normSide(g("side")), price: num(g("price")), qty: num(g("qty")) ?? 1, cur: (g("cur") || "").toUpperCase(),
        fx: num(g("fx")), fee: num(g("fee")) || 0, tax: num(g("tax")) || 0, target: num(g("target")), stop: num(g("stop")),
        reason: g("reason"), memo: g("memo"), sideRaw: g("side")
      };
      if (!rec.cur) rec.cur = /미장|미국|us/i.test(rec.market) ? "USD" : "KRW";
      if (/^\d{1,6}$/.test(rec.ticker)) rec.ticker = rec.ticker.padStart(6, "0");
      else if (!/^[0-9][0-9A-Z]{5}$/.test(rec.ticker)) rec.ticker = rec.ticker.replace(/[./\s]/g, "-");   // BRK.B → BRK-B (야후 표기)
      rec.key = rec.ticker || rec.name;
      S.raw.push(rec);
      if (!rec.date || !rec.side || rec.price == null) { S.warnings.push(`${rec.line}행: 날짜·매매·단가 중 읽을 수 없는 값이 있어 건너뜀`); return; }
      if (HOLD_SIDES.includes(rec.side) && !rec.key) { S.warnings.push(`${rec.line}행: 종목/티커가 없어 건너뜀`); return; }
      S.rows.push(rec);
    });
    S.rows.sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : a.line - b.line);
    // 종목 정보
    S.inst = {}; S.keys = [];
    S.rows.forEach(r => {
      if (!HOLD_SIDES.includes(r.side)) return;
      if (!S.inst[r.key]) { S.inst[r.key] = { key: r.key, name: r.name || r.key, market: r.market || (r.cur === "USD" ? "미장" : "국장"), cur: r.cur, color: COLORS[S.keys.length % COLORS.length] }; S.keys.push(r.key); }
      const I = S.inst[r.key];
      if (r.target != null) I.target = r.target; if (r.stop != null) I.stop = r.stop;
      if (r.side === "BUY" && r.reason) I.thesis = r.reason;
    });
    if (S.keys.length > 8) S.warnings.push("종목이 8개를 넘어 9번째부터는 색이 반복됩니다.");
  }

  /* ───────── 시세 파일 읽기 ───────── */
  const fileCache = {};
  async function getJSON(name) {
    if (name in fileCache) return fileCache[name];
    try { const r = await fetch(DATA_BASE + encodeURIComponent(name) + ".json", { cache: "no-cache" }); fileCache[name] = r.ok ? await r.json() : null; }
    catch (e) { fileCache[name] = null; }
    return fileCache[name];
  }
  function unpackFile(js) {
    const dates = []; let d = new Date(js.d0 + "T00:00:00Z");
    dates.push(js.d0);
    js.dd.forEach(x => { d = new Date(d.getTime() + x * 864e5); dates.push(d.toISOString().slice(0, 10)); });
    const c = js.c, v = js.v || [], v20 = v.slice(-20);
    return {
      last: c[c.length - 1], prev: c.length > 1 ? c[c.length - 2] : null, volume: v.length ? v[v.length - 1] : null,
      avgVolume20: v20.length ? v20.reduce((a, b) => a + b, 0) / v20.length : null, history: { dates, close: c },
      splits: js.sp || [], sector: js.sec, lastDate: dates[dates.length - 1], yname: js.n, cur: js.cur
    };
  }
  async function loadQuotes(keys) {
    const [meta, fx, ...files] = await Promise.all([getJSON("_meta"), getJSON("_fx"), ...keys.map(getJSON)]);
    S.prices = { generated: meta ? meta.generated : null, meta, tickers: {}, fx: null };
    keys.forEach((k, i) => { if (files[i]) S.prices.tickers[k] = unpackFile(files[i]); });
    if (fx) { const u = unpackFile(fx); S.prices.fx = { last: u.last, history: u.history }; }
    if (!meta && !fx && !Object.keys(S.prices.tickers).length) S.prices = null;
    staleWarnings(keys);
  }

  /* 시세 '데이터 없음'·오래된 시세 경고: 같은 통화(시장) 종목 중 가장 최근 날짜보다 4일 넘게 뒤처지면 표시 */
  function staleWarnings(keys) {
    if (!S.prices) { S.warnings.push("시세 데이터 없음 — 시세 파일을 읽지 못해 모든 종목을 최근 체결가로 계산했습니다."); return; }
    const T = S.prices.tickers, newest = {};
    keys.forEach(k => { const t = T[k]; if (t && (!newest[t.cur] || t.lastDate > newest[t.cur])) newest[t.cur] = t.lastDate; });
    const none = [], old = [];
    keys.forEach(k => {
      const t = T[k], nm = (S.inst[k] && S.inst[k].name) || k;
      if (!t) { none.push(nm); return; }
      const ref = newest[t.cur];
      if (ref && (new Date(ref) - new Date(t.lastDate)) / 864e5 > 4) old.push(`${nm}(${t.lastDate.slice(5).replace("-", "/")})`);
    });
    if (none.length) S.warnings.push(`시세 데이터 없음: ${none.join(", ")} → 현재가 대신 최근 체결가로 계산`);
    if (old.length) S.warnings.push(`시세가 오래됨(받아 오기 실패): ${old.join(", ")} — 괄호 안 날짜 종가로 계산`);
    if (S.prices.meta && S.prices.meta.fx_ok === false) S.warnings.push("환율 데이터 없음(이번 갱신 실패) → 지난 환율로 계산");
  }

  /* 환율 칸이 빈 미장 행: 시세 환율(_fx.json)의 그날(없으면 직전 거래일) 값으로 채움 */
  function fillFx() {
    const h = S.prices && S.prices.fx && S.prices.fx.history;
    if (!h || !h.dates.length) return;
    S.rows.forEach(r => {
      if (r.cur !== "USD" || r.fx) return;
      const i = lastLE(h.dates, r.date);
      r.fx = h.close[Math.max(i, 0)]; r.fxAuto = true;
    });
    const early = S.rows.filter(r => r.fxAuto && r.date < h.dates[0]).length;
    if (early) S.warnings.push(`환율 시세가 ${h.dates[0]}부터라 그 이전 미장 ${early}건은 ${h.dates[0]} 환율로 계산`);
  }

  /* 분할 비율: 키움 자동입력은 수량=비율(단가 0), 예전 형식은 단가=비율 */
  const splitRatio = r => r.price > 0 ? r.price : r.qty;

  /* 액면분할: 시세 파일(야후 분할 기록)과 CSV '분할' 행을 반영해 분할 이전 매매의 수량·단가를 조정.
     같은 분할이 양쪽에 있으면(비율 같고 날짜 ±10일, 입고일과 분할일이 다를 수 있음) CSV 쪽만 적용해 이중 반영을 막음 */
  function applySplits() {
    S.rows.forEach(r => { r.aqty = r.qty; r.aprice = r.price; });
    const near = (a, b) => Math.abs(new Date(a) - new Date(b)) <= 10 * 864e5;
    S.keys.forEach(k => {
      const manual = S.rows.filter(r => r.key === k && r.side === "SPLIT").map(r => [r.date, splitRatio(r)]);
      const auto = ((S.prices && S.prices.tickers[k] && S.prices.tickers[k].splits) || [])
        .filter(([d, x]) => !manual.some(([md, mx]) => near(md, d) && Math.abs(mx / x - 1) < 0.01));
      [...manual, ...auto].forEach(([d, ratio]) => {
        if (!ratio || ratio === 1) return;
        S.rows.forEach(r => { if (r.key === k && r.date < d && (r.side === "BUY" || r.side === "SELL" || r.side === "DIV" || r.side === "TIN")) { r.aqty *= ratio; r.aprice /= ratio; } });
        S.inst[k].splitNote = (S.inst[k].splitNote ? S.inst[k].splitNote + ", " : "") + `${d} 1:${ratio} 분할 반영`;
      });
    });
  }

  /* ───────── 시세 ───────── */
  function lastLE(dates, d) { let lo = 0, hi = dates.length - 1, ans = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (dates[m] <= d) { ans = m; lo = m + 1; } else hi = m - 1; } return ans; }
  function histOf(k) { const t = S.prices && S.prices.tickers[k]; return t && t.history && t.history.dates.length ? t.history : null; }
  function lastTradePx(k, d) { let p = null; for (const r of S.rows) { if (r.date > d) break; if (r.key === k && (r.side === "BUY" || r.side === "SELL" || (r.side === "TIN" && r.aprice > 0))) p = r.aprice; } return p; }
  function priceAt(k, d) {
    const h = histOf(k);
    if (h) { const i = lastLE(h.dates, d); if (i >= 0) return h.close[i]; }
    return lastTradePx(k, d);
  }
  function lastTradeFx(d) { let f = null; for (const r of S.rows) { if (d && r.date > d) break; if (r.cur === "USD" && r.fx) f = r.fx; } return f; }
  function fxAt(d) {
    const h = S.prices && S.prices.fx && S.prices.fx.history;
    if (h && h.dates.length) { const i = lastLE(h.dates, d); if (i >= 0) return h.close[i]; }
    return lastTradeFx(d) || lastTradeFx() || 1400;
  }
  function quote(k) {
    const t = S.prices && S.prices.tickers[k];
    if (t && t.last != null) return { price: t.last, prev: t.prev, volume: t.volume, avgVol: t.avgVolume20, src: "시세", sector: t.sector, high52: t.high52, low52: t.low52 };
    return { price: lastTradePx(k, "9999"), src: "최근 체결가" };
  }
  const fxNow = () => (S.prices && S.prices.fx && S.prices.fx.last) || lastTradeFx() || 1400;

  /* ───────── 시뮬레이션 ─────────
     평균단가(이동평균) 방식, 원화 기준. 미장은 체결 환율(없으면 그날 환율)로 원화 원가를 잡습니다. */
  function simulate(sc) {
    const T = today();
    const set = new Set(S.rows.map(r => r.date));
    const first = S.rows.length ? S.rows[0].date : T;
    S.keys.forEach(k => { const h = histOf(k); if (h) h.dates.forEach(d => { if (d >= first && d <= T) set.add(d); }); });
    set.add(T);
    const dates = [...set].sort();
    const pos = {}; S.keys.forEach(k => pos[k] = { qty: 0, costL: 0, costK: 0, realK: 0, divK: 0 });
    let cash = 0, dep = 0, real = 0, div = 0, intr = 0, fees = 0, taxes = 0, hasCash = false, ei = 0;
    const flows = {}, trades = [], usRealYear = {};
    const F = m => flows[m] || (flows[m] = { buy: 0, sell: 0, real: 0, div: 0, int: 0 });
    const tl = { dates, asset: [], value: [], cost: [], unreal: [], realCum: [], dep: [], cash: [], ret: [], w: {}, r: {} };
    S.keys.forEach(k => { tl.w[k] = []; tl.r[k] = []; });
    dates.forEach((d, di) => {
      while (ei < S.rows.length && S.rows[ei].date <= d) {
        const e = S.rows[ei++], p = pos[e.key], m = month(e.date);
        const fxT = e.cur === "USD" ? (e.fx || fxAt(e.date)) : 1;
        const amt = e.aprice * e.aqty;
        fees += e.fee * fxT; taxes += e.tax * fxT;
        if (e.side === "BUY") {
          p.costL += amt + e.fee; p.costK += (amt + e.fee) * fxT; p.qty += e.aqty;
          cash -= (amt + e.fee) * fxT; F(m).buy += amt * fxT;
        } else if (e.side === "SELL") {
          let q = e.aqty;
          if (q > p.qty + 1e-9) { if (!sc) S.warnings.push(`${e.line}행: ${S.inst[e.key].name} 보유수량(${nf(p.qty, 2)})보다 많이 매도 → 보유분만 계산`); q = p.qty; }
          if (q <= 0) continue;
          const avgK = p.costK / p.qty, avgL = p.costL / p.qty, ratio = q / e.aqty;
          const procK = (e.aprice * q - (e.fee + e.tax) * ratio) * fxT, basisK = avgK * q, pnl = procK - basisK;
          p.costK -= basisK; p.costL -= avgL * q; p.qty -= q; if (p.qty < 1e-9) { p.qty = 0; p.costK = 0; p.costL = 0; }
          p.realK += pnl; real += pnl; cash += procK; F(m).sell += e.aprice * q * fxT; F(m).real += pnl;
          trades.push({ date: e.date, key: e.key, pnl, ret: pnl / basisK, line: e.line });
          if (e.cur === "USD") usRealYear[e.date.slice(0, 4)] = (usRealYear[e.date.slice(0, 4)] || 0) + pnl;
        } else if (e.side === "TIN") {   // 타사대체입고: 보유·원가 증가, 현금 대신 순입금(주식으로 들어온 자산)에 더함
          p.costL += amt; p.costK += amt * fxT; p.qty += e.aqty; dep += amt * fxT; hasCash = true;
        } else if (e.side === "INT") {   // 이자·리워드 등: 현금·실현손익 (세금·수수료는 차감)
          const v = (amt - e.fee - e.tax) * fxT; real += v; intr += v; cash += v; F(m).int += v; F(m).real += v;
        } else if (e.side === "DIV") {
          const v = (amt - e.fee - e.tax) * fxT; p.divK += v; real += v; div += v; cash += v; F(m).div += v; F(m).real += v;
        } else if (e.side === "DEP" || e.side === "WD") {
          const v = amt * (e.cur === "USD" ? fxT : 1) * (e.side === "DEP" ? 1 : -1); cash += v; dep += v; hasCash = true;
        }
      }
      const last = di === dates.length - 1;
      const fx = last && sc && S.fxEdit ? S.fxEdit : fxAt(d);
      let val = 0, cost = 0; const vals = {};
      S.keys.forEach(k => {
        let p = pos[k], price = last ? quote(k).price : priceAt(k, d);
        if (last && sc && S.edits[k]) {   // 시나리오: 마지막 날짜에 수정값 적용
          const e = S.edits[k], ratio = p.costL > 0 ? p.costK / p.costL : (S.inst[k].cur === "USD" ? fx : 1);
          p = Object.assign({}, p); p.qty = e.qty; p.costL = e.qty * e.avg; p.costK = p.costL * ratio; price = e.price;
          pos["__sc_" + k] = p;
        }
        const v = p.qty * (price || 0) * (S.inst[k].cur === "USD" ? fx : 1);
        vals[k] = v; val += v; cost += p.costK;
        tl.r[k].push(p.qty > 0 && p.costK > 0 ? (v - p.costK) / p.costK * 100 : null);
      });
      S.keys.forEach(k => tl.w[k].push(val > 0 ? vals[k] / val * 100 : 0));
      tl.value.push(val); tl.cost.push(cost); tl.unreal.push(val - cost); tl.realCum.push(real); tl.dep.push(dep);
      tl.cash.push(cash); tl.asset.push(hasCash ? val + cash : val);
      const base = hasCash ? dep : cost;
      tl.ret.push(base > 0 ? (hasCash ? (val + cash - dep) / dep : (val - cost + real) / cost) * 100 : null);
    });
    // 최종 스냅샷(표용)
    const fx = sc && S.fxEdit ? S.fxEdit : fxNow();
    const rows = S.keys.map(k => {
      const p = (sc && pos["__sc_" + k]) || pos[k], q = quote(k), I = S.inst[k];
      const price = sc && S.edits[k] ? S.edits[k].price : q.price;
      const valueK = p.qty * (price || 0) * (I.cur === "USD" ? fx : 1);
      const avg = p.qty > 0 ? p.costL / p.qty : null;
      return {
        key: k, name: I.name, market: I.market, cur: I.cur, qty: p.qty, avg, price, chg: q.prev ? price / q.prev - 1 : null,
        volume: q.volume, avgVol: q.avgVol, src: q.src, valueK, costK: p.costK, pnlK: valueK - p.costK, ret: p.costK > 0 ? valueK / p.costK - 1 : null,
        realK: p.realK + p.divK, target: I.target, stop: I.stop, fxCost: p.costL > 0 ? p.costK / p.costL : null, color: I.color, sector: SECTOR_HINT[k] || q.sector || "기타"
      };
    });
    const val = rows.reduce((a, r) => a + r.valueK, 0);
    rows.forEach(r => r.weight = val > 0 ? r.valueK / val : 0);
    const n = dates.length - 1;
    return { tl, rows, fx, cash: tl.cash[n], dep, real, div, intr, fees, taxes, hasCash, flows, trades, usRealYear, value: val, cost: tl.cost[n], asset: tl.asset[n] };
  }

  /* ───────── 화면: 타일 ───────── */
  function renderTiles(R) {
    const totalPnl = R.hasCash ? R.asset - R.dep : R.value - R.cost + R.real;
    const totRet = R.hasCash ? (R.dep > 0 ? totalPnl / R.dep : null) : (R.cost > 0 ? totalPnl / R.cost : null);
    const t = [
      ["총 자산", won(R.asset), R.hasCash ? `순입금 ${short(R.dep)}원` : "현금 기록 없음", ""],
      ["총 손익", signed(totalPnl), pct(totRet), cls(totalPnl)],
      ["평가손익(보유)", signed(R.value - R.cost), pct(R.cost > 0 ? R.value / R.cost - 1 : null), cls(R.value - R.cost)],
      ["실현손익(배당·이자 포함)", signed(R.real), `배당 ${short(R.div)}원${R.intr ? ` · 이자 ${short(R.intr)}원` : ""}`, cls(R.real)],
      ["현금", R.hasCash ? won(R.cash) : "–", R.hasCash && R.asset > 0 ? `자산의 ${(R.cash / R.asset * 100).toFixed(1)}%` : "입금 행을 넣으면 계산", ""],
      ["USD/KRW", nf(R.fx, 1), S.prices ? "시세 기준" : "체결 환율 기준", ""]
    ];
    $("#tiles").innerHTML = t.map(([k, v, d, c]) => `<div class="tile"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="d ${c}">${d}</div></div>`).join("");
  }

  /* ───────── 기간 · 행 수 ───────── */
  const inPeriod = d => (!S.pFrom && !S.pTo) || (!!d && (!S.pFrom || d >= S.pFrom) && (!S.pTo || d <= S.pTo));
  function setPeriod(p) {
    const t = today(), d = new Date(t + "T00:00:00");
    const back = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 }[p];
    S.pTo = p === "ALL" ? "" : t;
    S.pFrom = p === "ALL" ? "" : p === "YTD" ? t.slice(0, 4) + "-01-01" : (d.setMonth(d.getMonth() - back), d.toISOString().slice(0, 10));
    $("#pFrom").value = S.pFrom; $("#pTo").value = S.pTo;
    document.querySelectorAll("#pRanges button").forEach(x => x.classList.toggle("on", x.dataset.p === p));
    syncChartButtons(p);
  }
  function syncChartButtons(p) { document.querySelectorAll("#ranges button").forEach(x => x.classList.toggle("on", x.dataset.r === p)); }
  function applyLimit(id) {
    const sel = document.querySelector(`select.limit[data-t="${id}"]`), n = sel ? +sel.value : 0;
    const trs = [...document.querySelectorAll(`#${id} tbody tr`)].filter(tr => !tr.classList.contains("total") && !tr.classList.contains("cash"));
    trs.forEach((tr, i) => { tr.style.display = n && i >= n ? "none" : ""; });
    const cnt = $(`#cnt-${id}`); if (cnt) cnt.textContent = n && trs.length > n ? `${n} / ${trs.length}행` : `${trs.length}행`;
  }

  /* ───────── 표 ① ───────── */
  function fillFilters() {
    const opt = (sel, vals, lab) => { const cur = sel.value; sel.innerHTML = `<option value="">${lab}</option>` + vals.map(v => `<option value="${esc(v[0])}">${esc(v[1])}</option>`).join(""); sel.value = cur; };
    opt($("#fMarket"), [...new Set(S.raw.map(r => r.market).filter(Boolean))].map(v => [v, v]), "전체 구분");
    opt($("#fTicker"), S.keys.map(k => [k, S.inst[k].name]), "전체 종목");
    opt($("#fSide"), [...new Set(S.rows.map(r => r.side))].map(v => [v, SIDE_KO[v]]), "전체 매매");
  }
  function renderT1() {
    const fm = $("#fMarket").value, ft = $("#fTicker").value, fs = $("#fSide").value;
    const head = ["날짜", "구분", "종목", "티커", "매매", "단가", "수량", "통화", "환율", "거래금액(원)", "수수료", "세금", "목표가", "손절가", "매매사유", "메모", "계좌"];
    const rows = S.raw.filter(r => inPeriod(r.date) && (!fm || r.market === fm) && (!ft || r.key === ft) && (!fs || r.side === fs));
    $("#t1").innerHTML = `<thead><tr>${head.map((h, i) => `<th class="${i < 5 || i > 13 ? "l" : ""}">${h}</th>`).join("")}</tr></thead><tbody>` +
      rows.map(r => {
        const fx = r.cur === "USD" ? (r.fx || (r.date ? fxAt(r.date) : null)) : 1;
        const amt = r.price != null && r.side !== "SPLIT" ? r.price * r.qty * (fx || 0) : null;
        const tag = r.side === "BUY" || r.side === "TIN" ? "buy" : r.side === "SELL" ? "sell" : "";
        return `<tr><td class="l">${esc(r.date || "?")}</td><td class="l">${esc(r.market)}</td><td class="l">${esc(r.name)}</td><td class="l">${esc(r.ticker)}</td>
        <td class="l"><span class="tag ${tag}">${esc(SIDE_KO[r.side] || r.sideRaw)}</span></td><td>${r.side === "DEP" || r.side === "WD" ? won(r.price) : r.side === "SPLIT" ? "1:" + nf(splitRatio(r), splitRatio(r) % 1 ? 4 : 0) : px(r.price, r.cur)}</td><td>${nf(r.qty, r.qty % 1 ? 4 : 0)}</td>
        <td>${esc(r.cur)}</td><td${r.fxAuto ? ' class="muted" title="환율 칸이 비어 그날 시세 환율로 채움"' : ""}>${r.cur === "USD" ? nf(r.fx, 1) : ""}</td><td>${amt == null ? "" : won(amt)}</td><td>${r.fee ? px(r.fee, r.cur) : ""}</td><td>${r.tax ? px(r.tax, r.cur) : ""}</td>
        <td>${r.target != null ? px(r.target, r.cur) : ""}</td><td>${r.stop != null ? px(r.stop, r.cur) : ""}</td><td class="reason">${esc(r.reason)}</td><td class="l">${esc(r.memo)}</td><td class="l">${esc(r.account)}</td></tr>`;
      }).join("") + `</tbody>`;
    applyLimit("t1");
  }

  /* ───────── 표 ②·③ ───────── */
  const COLS = [["종목", "l"], ["구분", "l"], ["보유수량", ""], ["평균단가", ""], ["현재가", ""], ["등락률", ""], ["거래량", ""], ["평가금액", ""], ["매입금액", ""], ["평가손익", ""], ["수익률", ""], ["비중", ""], ["실현손익", ""], ["목표가 / 손절가", ""]];
  function cells(r, editable) {
    const ed = (f, v, d) => editable ? `<td class="edit" data-k="${esc(r.key)}" data-f="${f}"><input type="number" step="any" inputmode="decimal" value="${v == null ? "" : +(+v).toFixed(d)}"></td>` : null;
    const c = (col, html, k) => `<td class="${k || ""}" data-c="${col}">${html}</td>`;
    const tgt = `${r.target != null ? px(r.target, r.cur) : "–"} / ${r.stop != null ? px(r.stop, r.cur) : "–"}`;
    const vol = r.volume != null ? `${short(r.volume)}${r.avgVol ? ` <small class="${r.volume > r.avgVol * 1.5 ? "up" : ""}">(${(r.volume / r.avgVol * 100).toFixed(0)}%)</small>` : ""}` : "–";
    return `<td class="l"><span class="sw" style="background:${r.color}"></span>${esc(r.name)}${r.src !== "시세" ? ' <span class="tag" title="시세 파일이 없어 최근 체결가 사용 (티커 표기 확인)">체결가</span>' : ""}</td>
      <td class="l">${esc(r.market)}</td>
      ${ed("qty", r.qty, 4) || c("qty", nf(r.qty, r.qty % 1 ? 4 : 0))}
      ${ed("avg", r.avg, r.cur === "USD" ? 2 : 0) || c("avg", px(r.avg, r.cur))}
      ${ed("price", r.price, r.cur === "USD" ? 2 : 0) || c("price", px(r.price, r.cur))}
      ${c("chg", pct(r.chg, 2), cls(r.chg))}${c("vol", vol)}
      ${c("valueK", won(r.valueK))}${c("costK", won(r.costK))}${c("pnlK", signed(r.pnlK), cls(r.pnlK))}${c("ret", pct(r.ret), cls(r.ret))}
      ${c("weight", (r.weight * 100).toFixed(1) + "%")}${c("realK", signed(r.realK), cls(r.realK))}${c("tgt", tgt)}`;
  }
  function totalRow(R) {
    const v = R.rows.reduce((a, r) => a + r.valueK, 0), co = R.rows.reduce((a, r) => a + r.costK, 0), re = R.rows.reduce((a, r) => a + r.realK, 0);
    let h = "";
    if (R.hasCash) h += `<tr class="cash"><td class="l">현금</td><td class="l">원화</td><td colspan="5"></td><td data-c="cash">${won(R.cash)}</td><td colspan="6"></td></tr>`;
    h += `<tr class="total"><td class="l">합계</td><td></td><td colspan="5"></td><td data-c="tv">${won(v + (R.hasCash ? R.cash : 0))}</td><td data-c="tc">${won(co)}</td>
      <td data-c="tp" class="${cls(v - co)}">${signed(v - co)}</td><td data-c="tr" class="${cls(v - co)}">${pct(co > 0 ? v / co - 1 : null)}</td><td>100%</td><td class="${cls(re)}">${signed(re)}</td><td></td></tr>`;
    return h;
  }
  function renderT2() {
    let R = S.base;
    if (S.pFrom || S.pTo) {
      const keys = new Set(S.rows.filter(r => r.key && inPeriod(r.date)).map(r => r.key));
      R = Object.assign({}, R, { rows: R.rows.filter(r => keys.has(r.key)) });
    }
    const head = `<thead><tr>${COLS.map(([h, k]) => `<th class="${k}">${h}</th>`).join("")}</tr></thead>`;
    $("#t2").innerHTML = head + "<tbody>" + R.rows.map(r => `<tr class="${r.qty > 0 ? "" : "closed"}">${cells(r, false)}</tr>`).join("") + totalRow(R) + "</tbody>";
    const asof = S.prices && S.prices.generated ? `시세 기준: ${S.prices.generated}` : "시세 파일 없음 → 현재가 대신 최근 체결가로 계산";
    $("#t2hint").textContent = `${asof} · 거래량 괄호는 20일 평균 대비${S.pFrom || S.pTo ? " · 기간 내 거래 종목만 (수량·손익은 전체 기간 기준)" : ""}`;
    applyLimit("t2");
  }
  function editRows() {   // 표③ 현재 입력값으로 행 다시 계산
    const fx = +$("#fxEdit").value || S.base.fx;
    const rows = S.base.rows.filter(b => b.qty > 0).map(b => {
      const e = S.edits[b.key] || { qty: b.qty, avg: b.avg, price: b.price };
      const ratio = b.fxCost || (b.cur === "USD" ? fx : 1);
      const valueK = e.qty * (e.price || 0) * (b.cur === "USD" ? fx : 1), costK = e.qty * (e.avg || 0) * ratio;
      return Object.assign({}, b, { qty: e.qty, avg: e.avg, price: e.price, valueK, costK, pnlK: valueK - costK, ret: costK > 0 ? valueK / costK - 1 : null, chg: b.chg != null && b.price ? (e.price / (b.price / (1 + b.chg))) - 1 : null });
    });
    const tv = rows.reduce((a, r) => a + r.valueK, 0); rows.forEach(r => r.weight = tv > 0 ? r.valueK / tv : 0);
    return { rows, fx, hasCash: S.base.hasCash, cash: S.base.cash };
  }
  function renderT3() {
    const head = `<thead><tr>${COLS.map(([h, k]) => `<th class="${k}">${h}</th>`).join("")}</tr></thead>`;
    const R = editRows();
    $("#t3").innerHTML = head + "<tbody>" + R.rows.map(r => `<tr data-row="${esc(r.key)}">${cells(r, true)}</tr>`).join("") + totalRow(R) + "</tbody>";
    markChanged();
    applyLimit("t3");
  }
  function refreshT3Derived() {   // 입력 중에는 입력칸을 다시 그리지 않고 계산 칸만 바꿈
    const R = editRows();
    R.rows.forEach(r => {
      const tr = $(`#t3 tr[data-row="${CSS.escape(r.key)}"]`); if (!tr) return;
      const tmp = document.createElement("tr"); tmp.innerHTML = cells(r, false);
      tmp.querySelectorAll("td[data-c]").forEach(td => { const t = tr.querySelector(`td[data-c="${td.dataset.c}"]`); if (t) { t.innerHTML = td.innerHTML; t.className = td.className; } });
    });
    const tb = $("#t3 tbody"); tb.querySelectorAll("tr.total, tr.cash").forEach(x => x.remove()); tb.insertAdjacentHTML("beforeend", totalRow(R));
    markChanged();
  }
  function readEdits() {
    const ed = {};
    S.base.rows.forEach(b => ed[b.key] = { qty: b.qty, avg: b.avg, price: b.price });
    document.querySelectorAll("#t3 td.edit").forEach(td => { const v = num(td.querySelector("input").value); ed[td.dataset.k][td.dataset.f] = v == null ? 0 : v; });
    return ed;
  }
  function markChanged() {
    document.querySelectorAll("#t3 td.edit").forEach(td => {
      const b = S.base.rows.find(r => r.key === td.dataset.k), v = num(td.querySelector("input").value), o = b[td.dataset.f];
      td.classList.toggle("changed", v != null && o != null ? Math.abs(v - o) > Math.abs(o) * 1e-9 + 1e-9 : v !== o);
    });
    const fx = +$("#fxEdit").value; $("#fxEdit").parentElement.classList.toggle("changed", Math.abs(fx - S.base.fx) > 1e-6);
  }

  /* ───────── 추세 ───────── */
  function sliceRange(tl) {
    // 위쪽 '기간' 필터(S.pFrom~S.pTo)를 표와 그래프가 함께 씀
    const n = tl.dates.length, from = S.pFrom || tl.dates[0], to = S.pTo || tl.dates[n - 1];
    let i0 = tl.dates.findIndex(x => x >= from); if (i0 < 0) i0 = n - 1;
    let i1 = n - 1; while (i1 > i0 && tl.dates[i1] > to) i1--;
    const cut = a => a.slice(i0, i1 + 1);
    const o = { dates: cut(tl.dates), w: {}, r: {} };
    ["asset", "value", "cost", "unreal", "realCum", "dep", "ret"].forEach(k => o[k] = cut(tl[k]));
    S.keys.forEach(k => { o.w[k] = cut(tl.w[k]); o.r[k] = cut(tl.r[k]); });
    o.i0 = i0; return o;
  }
  function renderCharts(R) {
    const t = sliceRange(R.tl), held = S.keys.filter(k => t.r[k].some(v => v != null));
    const mk = S.scenario ? { index: t.dates.length - 1, label: "시나리오" } : null;
    const ser = [{ name: R.hasCash ? "총자산" : "평가금액", color: "var(--s1)", values: t.asset }];
    if (R.hasCash) ser.push({ name: "평가금액", color: "var(--s2)", values: t.value });
    ser.push({ name: "매입원금", color: "var(--s3)", values: t.cost });
    if (R.hasCash) ser.push({ name: "순입금액", color: "var(--muted)", values: t.dep, dash: true });
    const vi = R.hasCash ? 1 : 0;
    Charts.line($("#cAsset"), { dates: t.dates, series: ser, fmt: short, tipFmt: won, bands: [{ a: vi, b: ser.findIndex(s => s.name === "매입원금"), color: "var(--s2)" }], marker: mk, height: 280, zero: false });
    Charts.line($("#cPnl"), {
      dates: t.dates, series: [
        { name: "평가손익", color: "var(--s1)", values: t.unreal },
        { name: "누적 실현손익", color: "var(--s2)", values: t.realCum },
        { name: "합계", color: "var(--s7)", values: t.unreal.map((v, i) => v + t.realCum[i]) }], fmt: short, tipFmt: signed, marker: mk, height: 260
    });
    Charts.line($("#cWeight"), { dates: t.dates, series: S.keys.map(k => ({ name: S.inst[k].name, color: S.inst[k].color, values: t.w[k] })), stack100: true, marker: mk });
    Charts.line($("#cRet"), { dates: t.dates, series: held.map(k => ({ name: S.inst[k].name, color: S.inst[k].color, values: t.r[k] })), fmt: v => Math.round(v) + "%", tipFmt: v => (v > 0 ? "+" : "") + v.toFixed(1) + "%", marker: mk });
    // 수익률·낙폭
    let peak = -Infinity; const dd = t.ret.map(v => { if (v == null) return null; const idx = 1 + v / 100; peak = Math.max(peak, idx); return (idx / peak - 1) * 100; });
    R.ddNow = dd[dd.length - 1]; R.ddMin = Math.min(...dd.filter(v => v != null));
    Charts.line($("#cDD"), { dates: t.dates, series: [{ name: "누적 수익률", color: "var(--s1)", values: t.ret }, { name: "고점 대비 하락", color: "var(--s2)", values: dd }], fmt: v => Math.round(v) + "%", tipFmt: v => (v > 0 ? "+" : "") + v.toFixed(1) + "%", marker: mk });
    // 월별
    const start = t.dates[0].slice(0, 7);
    const endM = t.dates[t.dates.length - 1].slice(0, 7);
    const months = Object.keys(R.flows).filter(m => m >= start && m <= endM).sort();
    Charts.bars($("#cReal"), {
      labels: months.map(mLabel), series: [{ name: "실현손익", color: "var(--up)", values: months.map(m => R.flows[m].real) }],
      signColor: { pos: "var(--up)", neg: "var(--down)" }, fmt: (v, full) => full ? signed(v) : short(v),
      extra: i => { const f = R.flows[months[i]]; return `<div>매도 손익<span>${signed(f.real - f.div - f.int)}</span></div><div>배당<span>${signed(f.div)}</span></div>${f.int ? `<div>이자<span>${signed(f.int)}</span></div>` : ""}`; }
    });
    Charts.bars($("#cFlow"), { labels: months.map(mLabel), series: [{ name: "매수", color: "var(--up)", values: months.map(m => R.flows[m].buy) }, { name: "매도", color: "var(--down)", values: months.map(m => R.flows[m].sell) }], fmt: (v, full) => full ? won(v) : short(v) });
    const tr = R.trades.filter(x => x.date >= t.dates[0] && x.date <= t.dates[t.dates.length - 1]);
    Charts.bars($("#cTrades"), {
      labels: tr.map(x => `${+x.date.slice(5, 7)}.${+x.date.slice(8)} ${S.inst[x.key].name}`), series: [{ name: "손익", color: "var(--up)", values: tr.map(x => x.pnl) }],
      signColor: { pos: "var(--up)", neg: "var(--down)" }, fmt: (v, full) => full ? signed(v) : short(v), extra: i => `<div>수익률<span>${pct(tr[i].ret)}</span></div>`
    });
    if (!tr.length) $("#cTrades").innerHTML = '<p class="hint">이 기간에 매도 기록이 없습니다.</p>';
    if (!months.length) { $("#cReal").innerHTML = $("#cFlow").innerHTML = '<p class="hint">이 기간에 기록이 없습니다.</p>'; }
    // 도넛
    const live = R.rows.filter(r => r.valueK > 0);
    const lab = live.map(r => r.name), val = live.map(r => r.valueK), col = live.map(r => r.color);
    if (R.hasCash && R.cash > 0) { lab.push("현금"); val.push(R.cash); col.push("var(--muted)"); }
    Charts.donut($("#dStock"), { labels: lab, values: val, colors: col, fmt: won, center: "종목" });
    const mk2 = {}; live.forEach(r => mk2[r.market] = (mk2[r.market] || 0) + r.valueK); if (R.hasCash && R.cash > 0) mk2["현금"] = R.cash;
    const mks = Object.keys(mk2);
    Charts.donut($("#dMarket"), { labels: mks, values: mks.map(k => mk2[k]), colors: mks.map(k => k === "현금" ? "var(--muted)" : k === "국장" ? "var(--s1)" : "var(--s2)"), fmt: won, center: "시장" });
    renderStats(R);
  }
  function renderStats(R) {
    const tr = R.trades, win = tr.filter(x => x.pnl > 0), loss = tr.filter(x => x.pnl < 0);
    const aw = win.length ? win.reduce((a, x) => a + x.pnl, 0) / win.length : null, al = loss.length ? loss.reduce((a, x) => a + x.pnl, 0) / loss.length : null;
    R.stat = { n: tr.length, win: win.length, aw, al };
    const best = tr.reduce((a, x) => !a || x.pnl > a.pnl ? x : a, null), worst = tr.reduce((a, x) => !a || x.pnl < a.pnl ? x : a, null);
    const s = [
      ["매도 횟수", `${tr.length}회`], ["승률", tr.length ? `${(win.length / tr.length * 100).toFixed(0)}% (${win.length}승 ${loss.length}패)` : "–"],
      ["평균 이익", aw != null ? signed(aw) : "–"], ["평균 손실", al != null ? signed(al) : "–"],
      ["손익비", aw != null && al ? (aw / -al).toFixed(2) + " : 1" : "–"], ["최대 낙폭(MDD)", R.ddMin != null && isFinite(R.ddMin) ? R.ddMin.toFixed(1) + "%" : "–"],
      ["최고 매매", best ? `${S.inst[best.key].name} ${signed(best.pnl)}` : "–"], ["최악 매매", worst ? `${S.inst[worst.key].name} ${signed(worst.pnl)}` : "–"],
      ["수수료+세금", won(R.fees + R.taxes)], ["배당 합계", won(R.div)]
    ];
    $("#stats").innerHTML = s.map(([k, v]) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  }

  /* ───────── 조언 ───────── */
  function renderAdvice(R) {
    const A = [], add = (c, t, b) => A.push(`<li class="${c}"><b>${t}</b>${b}</li>`);
    const live = R.rows.filter(r => r.qty > 0 && r.valueK > 0).sort((a, b) => b.weight - a.weight);
    if (S.scenario) {
      const d = R.asset - S.base.asset;
      add("info", "시나리오 결과", `수정한 값 기준 총자산은 ${won(R.asset)}로, 현재 대비 <span class="${cls(d)}">${signed(d)}</span> 차이입니다. 아래 점검은 시나리오 값으로 계산했습니다.`);
    }
    if (live.length) {
      const top = live[0];
      if (top.weight > 0.4) add("risk", `한 종목 쏠림: ${top.name} ${(top.weight * 100).toFixed(0)}%`, `보유 주식의 40%를 넘습니다. 이 종목이 20% 빠지면 주식 평가액이 약 ${(top.weight * 20).toFixed(1)}% 줄어듭니다. 종목당 상한(예: 30%)을 정해 두고 넘는 부분은 분할 매도나 신규 매수 중단으로 맞추는 방법을 고려해 보세요.`);
      else if (top.weight > 0.3) add("info", `최대 비중 ${top.name} ${(top.weight * 100).toFixed(0)}%`, "상한 근처입니다. 추가 매수는 다른 종목 위주로 하는 편이 균형에 유리합니다.");
      else add("good", "종목 분산 양호", `최대 비중이 ${top.name} ${(top.weight * 100).toFixed(0)}%로 30% 이하입니다.`);
      const sec = {}; live.forEach(r => sec[r.sector] = (sec[r.sector] || 0) + r.weight);
      const [sn, sw] = Object.entries(sec).sort((a, b) => b[1] - a[1])[0];
      if (sw >= 0.7) add("risk", `업종 집중: ${sn} ${(sw * 100).toFixed(0)}%`, `종목은 ${live.length}개지만 같은 업종이라 메모리 가격·AI 설비투자 같은 한 가지 변수에 함께 움직입니다(국장·미장을 섞어도 분산 효과가 작음). 업종이 다른 종목·ETF나 현금 비중으로 변동성을 낮추는 방안을 검토해 보세요.`);
      const us = live.filter(r => r.cur === "USD"), usW = us.reduce((a, r) => a + r.weight, 0);
      if (us.length) {
        const fxPnl = us.reduce((a, r) => a + r.qty * r.price * (R.fx - (r.fxCost || R.fx)), 0);
        add("info", `환율 노출: 미장 ${(usW * 100).toFixed(0)}%`, `현재 환율 ${nf(R.fx, 1)}원 기준, 미장 보유분의 환차손익은 <span class="${cls(fxPnl)}">${signed(fxPnl)}</span>입니다. 환율이 10원 움직이면 평가액이 약 ${won(us.reduce((a, r) => a + r.qty * r.price * 10, 0))} 변합니다.`);
      }
      live.forEach(r => {
        if (r.stop != null && r.price <= r.stop) add("risk", `${r.name}: 손절가 이탈`, `현재가 ${px(r.price, r.cur)}, 손절가 ${px(r.stop, r.cur)}보다 낮습니다. 매수 이유("${esc(S.inst[r.key].thesis || "기록 없음")}")가 여전히 유효한지 확인하고, 규칙대로 정리할지 손절가를 다시 정할지 결정해 두세요.`);
        else if (r.stop != null && r.price <= r.stop * 1.05) add("info", `${r.name}: 손절가 근접`, `손절가까지 ${((r.price / r.stop - 1) * 100).toFixed(1)}% 남았습니다.`);
        if (r.target != null && r.price >= r.target) add("info", `${r.name}: 목표가 도달`, `현재가 ${px(r.price, r.cur)}, 목표가 ${px(r.target, r.cur)} 이상입니다. 일부 차익실현이나 목표가 재설정을 고려하세요.`);
        if (r.ret != null && r.ret < -0.15) add("risk", `${r.name}: 수익률 ${pct(r.ret)}`, "손실 폭이 15%를 넘었습니다. 물타기 전에 처음 세운 매수 이유와 손절 기준을 먼저 점검하세요.");
      });
      const winners = live.filter(r => r.ret > 0.5);
      if (winners.length) add("info", `큰 수익 종목: ${winners.map(r => `${r.name} ${pct(r.ret, 0)}`).join(", ")}`, "수익이 크게 난 종목은 비중이 저절로 커집니다. 정기적으로(예: 분기마다) 목표 비중으로 되돌리는 리밸런싱 규칙을 정해 두면 이익을 지키는 데 도움이 됩니다.");
    }
    const st = R.stat || {};
    if (st.n >= 3) {
      const wr = st.win / st.n, pr = st.aw && st.al ? st.aw / -st.al : null;
      if (pr != null && pr < 1 && wr < 0.6) add("risk", "손익비가 1 미만", `이익일 때 평균 ${signed(st.aw)}, 손실일 때 평균 ${signed(st.al)}입니다. 손실은 빨리 끊고 이익은 길게 가져가는 규칙(손절가 지키기)이 필요합니다.`);
      else add("good", `매매 성과: 승률 ${(wr * 100).toFixed(0)}%${pr ? `, 손익비 ${pr.toFixed(2)}` : ""}`, "지금 방식이 통하고 있습니다. 매도할 때마다 매매사유를 남기면 무엇이 통했는지 나중에 확인할 수 있습니다.");
    }
    if (R.ddNow != null && R.ddNow < -15) add("risk", `고점 대비 ${R.ddNow.toFixed(1)}% 하락 중`, "변동성이 큰 구간입니다. 추가 매수는 한 번에 하지 말고 나눠서 하세요.");
    if (R.hasCash && R.asset > 0) {
      const cr = R.cash / R.asset;
      if (cr < 0.05) add("info", `현금 비중 ${(cr * 100).toFixed(1)}%`, "조정이 왔을 때 살 수 있는 여력이 거의 없습니다. 5~10% 정도의 현금은 남겨 두는 편이 대응에 유리합니다.");
      else if (cr > 0.4) add("info", `현금 비중 ${(cr * 100).toFixed(0)}%`, "놀고 있는 현금이 많습니다. 파킹통장·MMF·단기채 ETF 등으로 이자를 받는 방법도 있습니다.");
      else add("good", `현금 비중 ${(cr * 100).toFixed(0)}%`, "추가 매수 여력이 적당히 있습니다.");
    }
    const y = today().slice(0, 4), usg = R.usRealYear[y] || 0;
    if (usg > 0) {
      const over = usg - 2500000;
      add(over > 0 ? "todo" : "info", `${y}년 미장 실현이익 ${won(usg)}`, over > 0
        ? `해외주식 양도소득 기본공제(연 250만 원)를 넘었습니다. 넘는 금액의 약 22%(${won(over * 0.22)} 추정)를 내년 5월에 신고·납부해야 할 수 있습니다. 연말 전에 손실 종목을 정리해 이익과 상계하는 방법도 있습니다.`
        : `기본공제 250만 원까지 ${won(-over)} 남았습니다. 연말 전에 공제 한도 안에서 이익을 실현해 두면 세금 없이 원가를 높일 수 있습니다.`);
    }
    const gross = R.trades.reduce((a, x) => a + Math.abs(x.pnl), 0);
    if (gross > 0 && (R.fees + R.taxes) / gross > 0.05) add("info", "거래 비용 점검", `수수료·세금이 ${won(R.fees + R.taxes)}로 매매 손익 규모의 ${((R.fees + R.taxes) / gross * 100).toFixed(1)}%입니다. 잦은 매매를 줄이거나 우대 수수료 이벤트를 확인해 보세요.`);
    const noPx = S.keys.filter(k => !(S.prices && S.prices.tickers[k]));
    if (noPx.length) {
      const pend = S.prices && S.prices.meta && S.prices.meta.pending > 0;
      add("todo", "시세를 찾지 못한 종목", `${noPx.map(k => `${esc(S.inst[k].name)}(${esc(k)})`).join(", ")} → 매매일지의 티커 표기를 확인하세요. 국내는 6자리 종목코드(005930), 미국은 야후 티커(AAPL, BRK-B)입니다.${pend ? ` 지금은 전체 시세를 처음 채우는 중이라(남은 종목 ${nf(S.prices.meta.pending)}개) 다음 실행 후 나타날 수도 있습니다.` : " 상장폐지·장외 종목은 수집 대상이 아닙니다."}`);
    }
    const noReason = S.rows.filter(r => (r.side === "BUY" || r.side === "SELL") && !r.reason).length;
    if (noReason) add("todo", `매매사유 빈칸 ${noReason}건`, "매수·매도 이유를 한 줄이라도 남겨 두면 손절·목표가 판단과 복기에 큰 도움이 됩니다.");
    $("#advice").innerHTML = A.join("") || '<li class="info"><b>특이사항 없음</b>현재 규칙에 걸리는 항목이 없습니다.</li>';
  }

  /* ───────── 전체 그리기 ───────── */
  function renderAll() {
    const R = S.scenario ? simulate(true) : S.base;
    renderTiles(R); renderCharts(R); renderAdvice(R);
    $("#scnBadge").hidden = !S.scenario;
  }
  async function start(text, fromStorage) {
    try { ingest(text); } catch (e) { showWarn([e.message]); return; }
    $("#asof").textContent = `시세 불러오는 중… (${S.keys.length}종목)`;
    await loadQuotes(S.keys);
    fillFx();
    applySplits();
    S.edits = {}; S.fxEdit = null; S.scenario = false;
    S.base = simulate(false);
    $("#fxEdit").value = +S.base.fx.toFixed(1);
    $("#app").hidden = false; $("#btnForget").hidden = !fromStorage && !safeGet();
    fillFilters(); renderT1(); renderT2(); renderT3(); renderAll();
    const first = S.rows[0] ? S.rows[0].date : "", last = S.rows.length ? S.rows[S.rows.length - 1].date : "";
    $("#asof").textContent = `매매 ${S.rows.length}건 · ${first} ~ ${last} · 종목 ${S.keys.length}개 · ${S.prices && S.prices.generated ? "시세 " + S.prices.generated : "시세 파일 없음"}`;
    showWarn(S.warnings);
  }
  function showWarn(list) { const w = $("#warn"); w.hidden = !list.length; w.innerHTML = list.map(esc).join("<br>"); }
  const safeGet = () => { try { return localStorage.getItem(LS_KEY); } catch (e) { return null; } };
  const safeSet = v => { try { v == null ? localStorage.removeItem(LS_KEY) : localStorage.setItem(LS_KEY, v); } catch (e) { } };

  /* ───────── 암호화 매매일지 자동 불러오기 ───────── */
  const b64d = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const pwGet = () => { try { return localStorage.getItem(PW_KEY); } catch (e) { return null; } };
  const pwSet = v => { try { v == null ? localStorage.removeItem(PW_KEY) : localStorage.setItem(PW_KEY, v); } catch (e) { } };
  async function decryptJournal(j, pw) {
    const cs = crypto.subtle, te = new TextEncoder();
    const base = await cs.importKey("raw", te.encode(pw), "PBKDF2", false, ["deriveBits"]);
    const bits = new Uint8Array(await cs.deriveBits({ name: "PBKDF2", salt: b64d(j.salt), iterations: j.iter, hash: "SHA-256" }, base, 512));
    const ek = await cs.importKey("raw", bits.slice(0, 32), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const mk = await cs.importKey("raw", bits.slice(32), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
    const nonce = b64d(j.nonce), ct = b64d(j.ct), tag = b64d(j.tag);
    const md = new Uint8Array(nonce.length + ct.length); md.set(nonce); md.set(ct, nonce.length);
    if (!await cs.verify("HMAC", mk, tag, md)) throw new Error("비밀번호가 맞지 않습니다");
    const n = Math.ceil(ct.length / 32), ps = [];
    for (let i = 0; i < n; i++) { const m = new Uint8Array(nonce.length + 4); m.set(nonce); new DataView(m.buffer).setUint32(nonce.length, i); ps.push(cs.sign("HMAC", ek, m)); }
    const ks = await Promise.all(ps), pt = new Uint8Array(ct.length);
    for (let i = 0; i < n; i++) { const k = new Uint8Array(ks[i]); for (let b = 0; b < 32 && i * 32 + b < ct.length; b++) pt[i * 32 + b] = ct[i * 32 + b] ^ k[b]; }
    if (!j.gz) return pt.buffer;
    return await new Response(new Blob([pt]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
  }
  function showPw(on, msg) { $("#pwBox").hidden = !on; if (msg) showWarn([msg]); if (on) $("#pw").focus(); }
  async function openEncrypted(pw) {
    const text = decode(await decryptJournal(S.enc, pw));
    pwSet(pw); safeSet(text); showPw(false); showWarn([]);
    await start(text, true);
    $("#asof").textContent = `자동 불러옴 (맥 동기화 ${S.enc.updated || "?"}) · ` + $("#asof").textContent;
  }
  async function tryAuto() {
    try {
      const r = await fetch(ENC_URL + "?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) return false;
      S.enc = await r.json();
    } catch (e) { return false; }
    const pw = pwGet();
    if (!pw) { showPw(true); return false; }
    try { await openEncrypted(pw); return true; }
    catch (e) { pwSet(null); showPw(true, "저장된 비밀번호로 열지 못했습니다. 다시 입력하세요."); return false; }
  }

  /* ───────── 이벤트 ───────── */
  $("#file").addEventListener("change", async ev => {
    const f = ev.target.files[0]; if (!f) return;
    const text = decode(await f.arrayBuffer()); safeSet(text); await start(text, true); $("#btnForget").hidden = false; ev.target.value = "";
  });
  $("#btnSample").addEventListener("click", async () => {
    const r = await fetch("sample.csv", { cache: "no-store" }); await start(decode(await r.arrayBuffer()), false);
    $("#asof").textContent = "샘플 데이터 · " + $("#asof").textContent;
  });
  $("#btnForget").addEventListener("click", () => { safeSet(null); pwSet(null); location.reload(); });
  const submitPw = async () => {
    const pw = $("#pw").value; if (!pw || !S.enc) return;
    try { await openEncrypted(pw); $("#pw").value = ""; } catch (e) { showWarn([e.message]); $("#pw").select(); }
  };
  $("#btnPw").addEventListener("click", submitPw);
  $("#pw").addEventListener("keydown", ev => { if (ev.key === "Enter") submitPw(); });
  ["#fMarket", "#fTicker", "#fSide"].forEach(s => $(s).addEventListener("change", renderT1));
  document.querySelectorAll("select.limit").forEach(s => s.addEventListener("change", () => applyLimit(s.dataset.t)));
  const periodChanged = () => { if (!S.base) return; renderT1(); renderT2(); renderCharts(S.scenario ? simulate(true) : S.base); };
  $("#pRanges").addEventListener("click", ev => { const b = ev.target.closest("button"); if (!b) return; setPeriod(b.dataset.p); periodChanged(); });
  ["#pFrom", "#pTo"].forEach(s => $(s).addEventListener("change", () => {
    S.pFrom = $("#pFrom").value; S.pTo = $("#pTo").value;
    const all = !S.pFrom && !S.pTo;
    document.querySelectorAll("#pRanges button").forEach(x => x.classList.toggle("on", all && x.dataset.p === "ALL"));
    syncChartButtons(all ? "ALL" : "");
    periodChanged();
  }));
  $("#t3").addEventListener("input", refreshT3Derived);
  $("#fxEdit").addEventListener("input", refreshT3Derived);
  $("#btnUpdate").addEventListener("click", () => {
    S.edits = readEdits(); S.fxEdit = +$("#fxEdit").value || S.base.fx;
    const changed = S.base.rows.some(b => { const e = S.edits[b.key]; return e.qty !== b.qty || Math.abs((e.avg || 0) - (b.avg || 0)) > 1e-9 || Math.abs((e.price || 0) - (b.price || 0)) > 1e-9; }) || Math.abs(S.fxEdit - S.base.fx) > 1e-6;
    S.scenario = changed; renderAll();
    document.querySelector(".sec").scrollIntoView({ behavior: "smooth" });
  });
  $("#btnReset").addEventListener("click", () => {
    S.edits = {}; S.fxEdit = null; S.scenario = false;
    $("#fxEdit").value = +S.base.fx.toFixed(1); renderT3(); renderAll();
  });
  $("#ranges").addEventListener("click", ev => {
    const b = ev.target.closest("button"); if (!b) return;
    setPeriod(b.dataset.r); periodChanged();   // 그래프 버튼도 위쪽 기간 필터와 같이 움직임
  });
  let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => S.base && renderCharts(S.scenario ? simulate(true) : S.base), 200); });
  window.addEventListener("scroll", () => Charts.hideTip(), { passive: true });

  (async function init() {
    const m = await getJSON("_meta");
    $("#foot").textContent = m ? `시세 갱신: ${m.generated} · 수집 종목 ${nf(m.total)}개 (코스피·코스닥·국내 ETF·미국 상장 주식/ETF, 평일 2회)${m.pending ? ` · 처음 채우는 중, 남은 ${nf(m.pending)}개` : ""}${m.missed ? ` · ⚠ 이번 갱신에서 ${nf(m.missed)}개 종목은 받지 못해 지난 종가 유지` : ""}` : "시세 파일이 아직 없습니다. Actions 실행 후 생깁니다.";
    const saved = safeGet();
    if (saved) await start(saved, true);          // 이전 내용 먼저 보여 주고
    await tryAuto();                               // 최신 암호화 매매일지로 교체
  })();
})();
