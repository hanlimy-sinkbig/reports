#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이번달 식단 추천 (daily_meal-plan)
=================================
매일 아침 이번달(+다음달) 식단 달력과 오늘의 음식 뉴스 10개를 웹페이지·PDF 로 GitHub Pages 에 게시합니다.

  ① 테마 버튼(#고기 #야채 #국물 …)  → 누르면 달력이 그 테마 메뉴로 바뀜
  ② 달력: 하루 3가지 (집밥 🍳 · 밀키트 📦 · 가끔 배달 🛵) → 메뉴를 누르면 레시피/밀키트 주문/배달 음식점
  ③ 오늘의 음식 뉴스 10개 (제목만, Google News RSS)

메뉴·레시피·테마·배달 음식점은 meal_data.py 에서 고칩니다.
같은 달·같은 테마는 매일 다시 만들어도 같은 식단이 나옵니다(메뉴 목록을 바꾸면 새로 짜임).

  python meal_plan.py --outdir _site/daily_meal-plan
  python meal_plan.py --demo --outdir out/daily_meal-plan      # 네트워크 없이 확인
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import html
import json
import os
import random
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meal_data as M  # noqa: E402
import meal_log as L  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_shared"))
import net_retry as NR  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

KST = dt.timezone(dt.timedelta(hours=9))
WEEKDAY = "월화수목금토일"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
NEWS_QUERY = "음식 OR 식품 OR 외식 OR 맛집 OR 레시피 OR 밀키트 OR 식재료"
HOME, KIT, DLV = 0, 1, 2


def log(m):
    print(f"[{dt.datetime.now(KST):%H:%M:%S}] {m}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- 식단 짜기
def in_pool(d: dict, theme: str, month: int) -> bool:
    if theme == "전체":
        return True
    if theme == "제철":
        return month in d["season"]
    if theme == "밀키트":
        return d["kit"]
    if theme == "배달맛집":
        return bool(d["dl"])
    return theme in d["tags"]


LEVEL_W = {"쉬움": 1.0, "보통": 0.6, "어려움": 0.3}   # 쉬운 메뉴가 더 자주 나오게


def weight(d: dict, month: int) -> float:
    w = LEVEL_W.get(d["lv"], 1.0)
    if not d["season"]:
        return w
    return w * (3.0 if month in d["season"] else 0.1)


HIST = L.History()          # 식사 기록 (main 에서 채움). 비어 있으면 기록 반영 없이 짠다.


def pick(rng: random.Random, cands: list[int], month: int, avoid: set[int], mult: dict | None = None) -> int | None:
    pool = [i for i in cands if i not in avoid]
    if not pool:
        return None
    mult = mult or {}
    ws = [weight(M.DISHES[i], month) * mult.get(i, 1.0) for i in pool]
    return rng.choices(pool, weights=ws, k=1)[0]


def plan_month(year: int, month: int, theme: str, variant: int = 0) -> list[list[list[int]]]:
    """하루마다 [[메뉴번호, 방법], ...] 3개. 방법 0=집밥 1=밀키트 2=배달."""
    dishes = M.DISHES
    idx = [i for i, d in enumerate(dishes) if in_pool(d, theme, month)]
    if not idx:
        return []
    rng = random.Random(f"meal|{year}-{month:02d}|{theme}|{len(dishes)}" + (f"|v{variant}" if variant else ""))
    per = min(3, len(idx))
    keep_days = max(0, min(3, len(idx) // per - 1))       # 메뉴가 적은 테마는 반복 허용
    recent: list[list[int]] = []
    ndays = calendar.monthrange(year, month)[1]
    out = []
    soup = [i for i in idx if "국물" in dishes[i]["tags"]]
    main = [i for i in idx if i not in soup and ({"고기", "해산물"} & set(dishes[i]["tags"]))]
    for day in range(1, ndays + 1):
        date = dt.date(year, month, day)
        wd = date.weekday()
        ate, mult = HIST.context(date)                      # 최근 7일에 먹은 메뉴·좋아한/별로인 메뉴·많이 먹은 종류
        avoid = {i for r in recent for i in r} | ate
        dlv_day = theme != "밀키트" and (theme == "배달맛집" or wd in (4, 5) or rng.random() < 0.15)
        picks: list[int] = []
        if theme == "전체":
            # 국·찌개 1 + 고기·생선 메인 1 + 별미 1 (배달 날엔 별미를 배달 가능 메뉴로)
            for cands in (soup, main):
                p = pick(rng, cands, month, avoid | set(picks), mult)
                if p is not None:
                    picks.append(p)
            third = [i for i in idx if i not in soup and (not dlv_day or dishes[i]["dl"])]
            p = pick(rng, third, month, avoid | set(picks), mult)
            if p is not None:
                picks.append(p)
        while len(picks) < per:
            p = pick(rng, idx, month, avoid | set(picks), mult)
            if p is None:                                  # 최근 메뉴를 빼면 모자랄 때만 반복 허용
                p = pick(rng, idx, month, set(picks), mult)
            if p is None:
                break
            picks.append(p)
        modes = []
        dl_done = False
        for k, i in enumerate(reversed(picks)):           # 마지막 칸부터 배달 배정
            d = dishes[i]
            if theme == "배달맛집":
                m = DLV
            elif theme == "밀키트":
                m = KIT
            elif dlv_day and not dl_done and d["dl"]:
                m, dl_done = DLV, True
            elif d["kit"] and rng.random() < 0.45:
                m = KIT
            else:
                m = HOME
            modes.append(m)
        modes.reverse()
        out.append([[i, m] for i, m in zip(picks, modes)])
        recent.append(picks)
        if len(recent) > keep_days:
            recent.pop(0)
    return out


LOG_STATE = "off"            # off: 파일 ID 없음 · ok: 읽음 · fail: 못 읽음


def load_history() -> None:
    global HIST, LOG_STATE
    fid = L.log_file_id()
    if not fid or requests is None:
        log("식사 기록: MEAL_LOG_ID 없음 → 기록 없이 추천")
        return
    try:
        HIST = L.History.fetch(get, fid)
        LOG_STATE = "ok"
        log(f"식사 기록: {len(HIST.days)}일치")
    except Exception as e:
        LOG_STATE = "fail"
        log(f"식사 기록 실패: {e}")
        NR.fail("식사 기록(구글 드라이브)", e)


def months_to_show(now: dt.datetime) -> list[tuple[int, int]]:
    y, m = now.year, now.month
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return [(y, m), (ny, nm)]


VARIANTS = 6                 # '추천 다시 받기' 버튼으로 돌아가며 보는 추천 세트 수 (0번 = 기본, PDF 기준)


def encode(days: list) -> list:
    """[[메뉴, 방법], ...] → [메뉴*3+방법, ...] (페이지 크기 줄이기)"""
    return [[i * 3 + m for i, m in day] for day in days]


def decode(days: list) -> list:
    return [[[x // 3, x % 3] for x in day] for day in days]


def build_plans(now: dt.datetime) -> dict:
    """plans[YYYY-MM][테마] = [세트0, 세트1, …]"""
    themes = ["전체"] + [k for k, _ in M.THEMES]
    plans = {}
    for y, m in months_to_show(now):
        plans[f"{y}-{m:02d}"] = {t: [encode(plan_month(y, m, t, v)) for v in range(VARIANTS)] for t in themes}
    return plans


# ---------------------------------------------------------------- 뉴스
def get(url):
    def once():
        r = requests.get(url, timeout=25, headers=UA)
        r.raise_for_status()
        return r
    return NR.retry(once, url[:80])


def fetch_news(limit: int = 10) -> list[dict]:
    if requests is None:
        NR.fail("오늘의 음식 뉴스", "requests 없음")
        return []
    out, seen = [], set()
    for days in (1, 2):
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{NEWS_QUERY} when:{days}d")
               + "&hl=ko&gl=KR&ceid=KR:ko")
        try:
            root = ET.fromstring(get(url).content)
        except Exception as e:
            log(f"뉴스 실패: {e}")
            NR.fail("오늘의 음식 뉴스", e)
            return out
        items = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            src = (it.findtext("source") or "").strip()
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            key = re.sub(r"\W", "", title)[:24]
            if not title or key in seen:
                continue
            seen.add(key)
            try:
                ts = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(KST).isoformat()
            except Exception:
                ts = ""
            items.append({"title": title, "link": it.findtext("link") or "", "ts": ts})
        items.sort(key=lambda n: n["ts"], reverse=True)
        out += items
        if len(out) >= limit:
            break
    out = out[:limit]
    log(f"뉴스: {len(out)}건")
    return out


def demo_news() -> list[dict]:
    return [{"title": f"[데모] 오늘의 음식·식품 뉴스 헤드라인 {i + 1}", "link": "#", "ts": ""} for i in range(10)]


# ---------------------------------------------------------------- 데이터 조립
def build_data(now: dt.datetime, news: list[dict]) -> dict:
    dishes = []
    for d in M.DISHES:
        dl = None
        if d["dl"]:
            chains, kw = M.DELIVERY[d["dl"]]
            dl = {"chains": chains, "kw": kw}
        dishes.append({"n": d["name"], "t": d["tags"], "time": d["time"], "lv": d["lv"], "ing": d["ing"],
                       "steps": d["steps"], "kit": d["kit"], "dl": dl, "s": d["season"]})
    return {
        "generated": now.strftime("%Y-%m-%d %H:%M KST"), "today": now.strftime("%Y-%m-%d"), "area": M.AREA,
        "updated": M.UPDATED, "themes": [{"k": k, "e": e} for k, e in M.THEMES], "dishes": dishes,
        "plans": build_plans(now), "news": news,
        "log": HIST.by_date(), "logsum": HIST.summary(now.date()) if HIST.days else None, "logon": LOG_STATE,
    }


# ---------------------------------------------------------------- HTML
HTML = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>이번달 식단 추천 · __DATE__</title>
<style>
:root{--surface-0:#f6f4ef;--surface-1:#fffdf9;--border:#e6e1d6;--text-primary:#1b1a17;--text-secondary:#56534c;--text-muted:#8a867c;
 --accent:#d9622b;--accent-soft:#fbe9df;--home:#2f8f5b;--kit:#2a78d6;--dlv:#c2410c;--today:#fff3c4;--sun:#d1352b;--sat:#2a6fd6}
@media (prefers-color-scheme: dark){:root{--surface-0:#131211;--surface-1:#1c1b19;--border:#302e2a;--text-primary:#f1efe9;--text-secondary:#c7c3b8;
 --text-muted:#8f8b81;--accent:#ef7a43;--accent-soft:#3a2418;--home:#4cb37c;--kit:#4b93ea;--dlv:#f0774a;--today:#3b3415;--sun:#ff6b5e;--sat:#6aa2ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);line-height:1.55;font-size:15px;
 font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 14px 60px}
h1{font-size:24px;margin:0 0 4px}.meta{color:var(--text-secondary);font-size:13px}.meta a{color:var(--text-secondary)}
section{margin-top:24px}h2{font-size:19px;margin:0 0 12px}h2 .num{color:var(--accent);margin-right:6px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:14px}
.themes{display:flex;flex-wrap:wrap;gap:7px}
.th{border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);border-radius:999px;padding:7px 12px;font-size:14px;cursor:pointer;font-family:inherit}
.th small{color:var(--text-muted);margin-left:3px;font-size:11.5px}
.th.on{background:var(--accent);border-color:var(--accent);color:#fff}.th.on small{color:#ffe6d9}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.regen{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.regen #regen{border:none;background:var(--accent);color:#fff;font-size:15px;font-weight:600;padding:10px 16px;border-radius:12px;cursor:pointer;font-family:inherit}
.regen #regen:active{transform:scale(.97)}
.regen .vl{font-size:12.5px;color:var(--text-secondary)}
.regen #vreset{border:none;background:none;color:var(--text-secondary);text-decoration:underline;font-size:12.5px;cursor:pointer;font-family:inherit;padding:0}
.flash{animation:fl .5s}@keyframes fl{from{background:var(--accent-soft)}to{background:transparent}}
.calhead{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.mnav{display:flex;align-items:center;gap:8px}.mnav b{font-size:18px;min-width:120px;text-align:center}
.mnav button{border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);border-radius:10px;width:36px;height:34px;font-size:18px;cursor:pointer}
.mnav button:disabled{opacity:.3;cursor:default}
.legend{font-size:12.5px;color:var(--text-secondary);display:flex;gap:10px;flex-wrap:wrap}
.cur{font-size:13px;color:var(--text-secondary);margin:0 0 10px}.cur b{color:var(--accent)}
.todaybox{background:var(--accent-soft);border-radius:12px;padding:10px 12px;margin-bottom:12px;font-size:14px}
.todaybox .dish{display:inline-flex;margin:3px 4px 0 0}
.cal{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px}
.wd{text-align:center;font-size:12.5px;color:var(--text-secondary);font-weight:600;padding:4px 0}
.wd.sun{color:var(--sun)}.wd.sat{color:var(--sat)}
.day{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:5px 4px 6px;min-height:118px;display:flex;flex-direction:column;gap:3px}
.day.blank{background:transparent;border:none}
.day.past .dish{opacity:.5}.day .dish.ate{opacity:1;background:var(--accent-soft);border-color:transparent;border-left:3px solid var(--text-secondary)}
.ate-s{display:block;font-size:12px;line-height:1.3;padding:3px 5px;border-radius:7px;background:var(--accent-soft);color:var(--text-secondary);border-left:3px solid var(--text-secondary)}
.atel{font-size:11px;color:var(--text-muted);padding:0 3px}
.logbox{font-size:13px;line-height:1.7;background:var(--surface-0);border:1px dashed var(--border);border-radius:12px;padding:8px 12px;margin-bottom:12px;color:var(--text-secondary)}
.logbox b{color:var(--text-primary)}.day.today{background:var(--today);border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset;opacity:1}
.dn{font-size:12.5px;font-weight:700;padding:0 3px}.dn.sun{color:var(--sun)}.dn.sat{color:var(--sat)}.dn .w{display:none}
.dish{display:flex;align-items:flex-start;gap:3px;width:100%;text-align:left;border:1px solid var(--border);background:var(--surface-0);color:var(--text-primary);
 border-radius:7px;padding:3px 5px;font-size:12px;line-height:1.3;cursor:pointer;font-family:inherit;word-break:keep-all}
.dish:hover{border-color:var(--accent)}
.dish .m{flex:none}.dish .nm{flex:1;min-width:0}
.lv{flex:none;margin-left:auto;font-size:10.5px;font-weight:600;line-height:1;padding:3px 5px;border-radius:999px;white-space:nowrap;align-self:center}
.lv0{background:#e3f4ea;color:#1f7a49}.lv1{background:#fdf0d5;color:#9a6200}.lv2{background:#fde2df;color:#b3261e}
@media (prefers-color-scheme: dark){.lv0{background:#1d3a2a;color:#7fd3a4}.lv1{background:#3d2f12;color:#f0c46a}.lv2{background:#45201d;color:#ff9b91}}
.dish{align-items:center}.dish.m0{border-left:3px solid var(--home)}.dish.m1{border-left:3px solid var(--kit)}.dish.m2{border-left:3px solid var(--dlv)}
.empty{font-size:12px;color:var(--text-muted);padding:4px}
@media (max-width:720px){
 .cal{grid-template-columns:1fr;gap:6px}.wd,.day.blank{display:none}
 .day{min-height:0;flex-direction:row;flex-wrap:wrap;align-items:center;padding:8px}
 .dn{width:100%;font-size:13.5px}.dn .w{display:inline}
 .dish{width:auto;font-size:13.5px;padding:5px 8px}}
.news{margin:0;padding-left:22px}.news li{padding:5px 0;border-bottom:1px solid var(--border)}
.news a{color:var(--text-primary);text-decoration:none}.news a:hover{text-decoration:underline}
.muted{color:var(--text-muted);font-size:12.5px}
footer{margin-top:40px;color:var(--text-muted);font-size:12px}
dialog{border:none;border-radius:16px;padding:0;max-width:560px;width:calc(100% - 24px);max-height:86vh;background:var(--surface-1);color:var(--text-primary)}
dialog::backdrop{background:rgba(0,0,0,.45)}
.mh{position:sticky;top:0;background:var(--surface-1);padding:14px 16px 10px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:10px}
.mh h3{margin:0;font-size:19px}.mh .x{border:none;background:none;font-size:24px;line-height:1;cursor:pointer;color:var(--text-secondary)}
.mb{padding:12px 16px 18px;overflow:auto}
.tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}.tags span{font-size:11.5px;border:1px solid var(--border);border-radius:999px;padding:0 7px;color:var(--text-secondary)}
.blk{border:1px solid var(--border);border-radius:12px;padding:12px;margin-top:12px}
.blk h4{margin:0 0 8px;font-size:15.5px}.blk.main{border-color:var(--accent);background:var(--accent-soft)}
.blk ol{margin:6px 0 0;padding-left:20px}.blk li{margin:3px 0}
.ing{font-size:13.5px;color:var(--text-secondary)}
.btns{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.btns a{text-decoration:none;font-size:13.5px;border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);border-radius:999px;padding:6px 12px}
.other{font-size:13px;color:var(--text-muted);margin:16px 0 0}
</style></head><body><div class="wrap">
<header><div><h1>이번달 식단 추천</h1>
<div class="meta">생성 __GENERATED__ · 매일 갱신 · <a href="latest.pdf">PDF</a> · <a href="archive/">지난 리포트</a></div></div>
<div class="regen"><button id="regen">🔄 추천 다시 받기</button><span class="vl" id="vlabel"></span><button id="vreset" hidden>처음 추천으로</button></div></header>
__DEMO__
<section id="s1"><h2><span class="num">①</span>테마</h2>
 <div class="card"><div class="themes" id="themes"></div></div></section>

<section id="s2"><h2><span class="num">②</span>식단 달력</h2>
 <div class="card">
  <div class="calhead"><div class="mnav"><button id="prev" aria-label="이전 달">‹</button><b id="mtitle"></b><button id="next" aria-label="다음 달">›</button></div>
   <div class="legend"><span>🍳 집밥(레시피)</span><span>📦 밀키트</span><span>🛵 배달</span><span>✔ 실제로 먹은 음식</span></div></div>
  <p class="cur" id="cur"></p>
  <div id="logbox"></div>
  <div id="todaybox"></div>
  <div class="cal" id="cal"></div>
 </div></section>

<section id="s3"><h2><span class="num">③</span>오늘의 음식 뉴스</h2>
 <div class="card"><ol class="news" id="news"></ol></div></section>

<footer>메뉴를 누르면 레시피·밀키트 주문·배달 음식점을 볼 수 있습니다. 배달 프랜차이즈는 동네마다 가맹점 유무가 다르니 지도·배달앱에서 확인하세요.
 뉴스: Google News(제목·링크만). 메뉴·레시피 목록 기준일 __UPDATED__ · meal_plan.py</footer>
</div>
<dialog id="dlg"><div class="mh"><div><h3 id="dt"></h3><div class="tags" id="dtags"></div></div><button class="x" id="dx" aria-label="닫기">×</button></div><div class="mb" id="db"></div></dialog>
<script>
const D=__DATA__;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const EMO=['🍳','📦','🛵'],MODE=['집밥','밀키트','배달'],WD='일월화수목금토';
const months=Object.keys(D.plans).sort();
let theme='전체',mi=0,NV=1,vsel=0;
try{NV=D.plans[months[0]]['전체'].length;vsel=Math.min(NV-1,+(localStorage.getItem('meal-variant')||0))||0;}catch(e){}
// 지난 날짜는 기본 세트(0번), 오늘부터는 고른 세트
function getPlan(ym,t){const sets=(D.plans[ym]||{})[t]||[],dec=a=>(a||[]).map(d=>d.map(x=>[Math.floor(x/3),x%3]));
 const base=dec(sets[0]),cur=dec(sets[vsel]||sets[0]);
 return base.map((d,k)=>(`${ym}-${String(k+1).padStart(2,'0')}`<D.today)?d:cur[k]);}
function renderV(){document.getElementById('vlabel').textContent=vsel?`추천 세트 ${vsel+1}/${NV} · 오늘부터 적용`:`기본 추천 (세트 1/${NV})`;
 document.getElementById('vreset').hidden=!vsel;}
const q=s=>encodeURIComponent(s);
function inTheme(d,t,mon){if(t==='전체')return true;if(t==='제철')return d.s.includes(mon);if(t==='밀키트')return d.kit;if(t==='배달맛집')return !!d.dl;return d.t.includes(t);}
function renderThemes(){const mon=+months[mi].slice(5);
 const all=[{k:'전체',e:'🍽️'}].concat(D.themes);
 document.getElementById('themes').innerHTML=all.map(t=>{const n=D.dishes.filter(d=>inTheme(d,t.k,mon)).length;
  return `<button class="th${t.k===theme?' on':''}" data-t="${esc(t.k)}">${t.e} ${t.k==='전체'?'전체':'#'+esc(t.k)}<small>${n}</small></button>`}).join('');}
const LV={'쉬움':[0,'쉬움'],'보통':[1,'중간'],'어려움':[2,'어려움']};
const lvTag=d=>{const [c,t]=LV[d.lv]||LV['쉬움'];return `<span class="lv lv${c}">${t}</span>`;};
// 요리하는 메뉴(집밥·밀키트)만 오른쪽에 난이도, 배달은 표시 안 함
function dishBtn(day,k,[i,m]){const d=D.dishes[i];return `<button class="dish m${m}" data-i="${i}" data-m="${m}" title="${MODE[m]}"><span class="m">${EMO[m]}</span><span class="nm">${esc(d.n)}</span>${m===2?'':(m===1?'<span class="lv lv0">쉬움</span>':lvTag(d))}</button>`;}
function renderCal(){const ym=months[mi],[y,mo]=ym.split('-').map(Number);
 document.getElementById('mtitle').textContent=`${y}년 ${mo}월`;
 document.getElementById('prev').disabled=mi===0;document.getElementById('next').disabled=mi===months.length-1;
 const plan=getPlan(ym,theme);
 document.getElementById('cur').innerHTML=theme==='전체'?'하루 3가지: 국·찌개 + 고기·생선 메인 + 별미 · 금·토와 가끔은 배달 메뉴 포함':`<b>#${esc(theme)}</b> 테마로 짠 식단입니다 · 다시 누르면 전체로 돌아갑니다`;
 const first=new Date(y,mo-1,1).getDay(),nd=new Date(y,mo,0).getDate();
 let h=[...WD].map((w,i)=>`<div class="wd${i===0?' sun':i===6?' sat':''}">${w}</div>`).join('');
 for(let i=0;i<first;i++)h+='<div class="day blank"></div>';
 for(let day=1;day<=nd;day++){const ds=`${ym}-${String(day).padStart(2,'0')}`,w=(first+day-1)%7;
  const cls=ds===D.today?' today':ds<D.today?' past':'';
  const items=plan[day-1]||[],ate=(D.log||{})[ds];
  const ateH=ate?'<div class="atel">먹은 음식</div>'+ate.map(([t,i])=>i>=0?`<button class="dish ate" data-i="${i}" data-m="0"><span class="m">✔</span><span>${esc(t)}</span></button>`:`<span class="ate-s">✔ ${esc(t)}</span>`).join(''):'';
  const recH=(ate&&ds<D.today)?'':(items.length?(ate?'<div class="atel">추천</div>':'')+items.map((it,k)=>dishBtn(day,k,it)).join(''):'<div class="empty">해당 메뉴 없음</div>');
  h+=`<div class="day${cls}"><div class="dn${w===0?' sun':w===6?' sat':''}">${day}<span class="w"> (${WD[w]})${ds===D.today?' · 오늘':''}</span></div>`+ateH+recH+'</div>';}
 document.getElementById('cal').innerHTML=h;
 const tb=document.getElementById('todaybox');
 if(D.today.slice(0,7)===ym&&plan.length){const it=plan[+D.today.slice(8)-1]||[];
  tb.innerHTML=`<div class="todaybox"><b>오늘의 추천</b> ${it.map((x,k)=>dishBtn(0,k,x)).join('')}</div>`;}else tb.innerHTML='';}
function renderLog(){const el=document.getElementById('logbox'),S=D.logsum;
 if(D.logon==='off'){el.innerHTML='<div class="logbox">📒 식사 기록 파일이 아직 연결되지 않아 기본 추천만 보여 줍니다.</div>';return;}
 if(D.logon==='fail'){el.innerHTML='<div class="logbox">📒 오늘은 식사 기록을 읽지 못해 기본 추천을 보여 줍니다. 다음 실행 때 다시 읽습니다.</div>';return;}
 if(!S){el.innerHTML='<div class="logbox">📒 식사 기록 연결됨 · 아직 적힌 날이 없습니다. 먹은 음식을 적으면 다음 날부터 추천에 반영됩니다.</div>';return;}
 const p=[`📒 <b>식사 기록 ${S.days}일</b> 반영 (최근 7일 ${S.days7}일) · 최근 7일에 먹은 메뉴는 추천에서 뺐습니다`];
 if(S.heavy.length)p.push(`최근 2주 많이 먹은 종류 <b>${S.heavy.map(x=>'#'+esc(x)).join(' ')}</b> → 줄여서 추천`);
 if(S.likes.length)p.push(`맛있었던 메뉴 <b>${S.likes.map(esc).join(', ')}</b> → 더 자주`);
 if(S.dislikes.length)p.push(`별로였던 메뉴 <b>${S.dislikes.map(esc).join(', ')}</b> → 덜 추천`);
 if(S.total)p.push(`기록 ${S.total}개 중 추천 메뉴와 연결된 것 ${S.matched}개`);
 el.innerHTML='<div class="logbox">'+p.join('<br>')+'</div>';}
function linkBtns(list){return '<div class="btns">'+list.map(([t,u])=>`<a href="${u}" target="_blank" rel="noopener">${esc(t)}</a>`).join('')+'</div>';}
function blkHome(d,main){return `<div class="blk${main?' main':''}"><h4>🍳 레시피 <span class="muted">${d.time}분 · 난이도 ${(LV[d.lv]||LV['쉬움'])[1]}</span></h4>
 <div class="ing"><b>재료</b> ${esc(d.ing)}</div><ol>${d.steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ol></div>`;}
function blkKit(d,main){const kw=d.n+' 밀키트';return `<div class="blk${main?' main':''}"><h4>📦 밀키트 주문 방법</h4>
 ${linkBtns([['쿠팡에서 찾기','https://www.coupang.com/np/search?q='+q(kw)],['컬리에서 찾기','https://www.kurly.com/search?sword='+q(kw)],['네이버쇼핑 비교','https://search.shopping.naver.com/search/all?query='+q(kw)]])}
 <ol><li>위 버튼으로 ‘${esc(kw)}’ 검색 결과를 열어 인원·후기를 비교해 고릅니다 (프레시지·마이셰프·쿡킷·피코크 등).</li>
 <li>새벽배송: 보통 밤 11시~자정 전에 주문하면 다음 날 아침에 도착합니다 (쿠팡 로켓프레시·컬리 샛별배송, 지역마다 다름).</li>
 <li>급할 땐 이마트몰·홈플러스 당일배송이나 동네 마트 밀키트 코너를 이용하세요.</li>
 <li>조리는 포장 뒷면 안내대로 하면 대부분 15~25분이면 됩니다.</li></ol></div>`;}
function blkDlv(d,main){const x=d.dl,map=s=>'https://map.naver.com/p/search/'+q(D.area+' '+s);
 return `<div class="blk${main?' main':''}"><h4>🛵 배달 가능한 주요 음식점</h4>
 ${x.chains.length?`<div class="ing">대표 프랜차이즈 — 눌러서 ${esc(D.area)} 근처 매장 찾기</div>`+linkBtns(x.chains.map(c=>[c,map(c)])):''}
 <div class="ing">동네 가게까지 보기</div>${linkBtns([[`${D.area} ${x.kw} 맛집 (네이버 지도)`,map(x.kw)]])}
 <ol><li>배달의민족·쿠팡이츠·요기요 앱에서 ‘${esc(x.kw)}’를 검색하면 지금 배달되는 가게와 예상 시간이 나옵니다.</li>
 <li>프랜차이즈는 가맹점마다 배달 지역이 달라 앱에서 주소를 먼저 확인하세요.</li></ol></div>`;}
function openDish(i,m){const d=D.dishes[i];
 document.getElementById('dt').textContent=d.n;
 document.getElementById('dtags').innerHTML=d.t.map(t=>`<span>#${esc(t)}</span>`).join('')+(d.kit?'<span>#밀키트</span>':'')+(d.dl?'<span>#배달가능</span>':'');
 const blocks={0:()=>blkHome(d,m===0),1:()=>d.kit?blkKit(d,m===1):'',2:()=>d.dl?blkDlv(d,m===2):''};
 const order=[m,...[0,1,2].filter(x=>x!==m)];
 const parts=order.map(x=>blocks[x]()).filter(Boolean);
 document.getElementById('db').innerHTML=parts[0]+(parts.length>1?'<p class="other">다른 방법</p>'+parts.slice(1).join(''):'');
 const dlg=document.getElementById('dlg');dlg.showModal?dlg.showModal():dlg.setAttribute('open','');document.getElementById('db').scrollTop=0;}
document.addEventListener('click',e=>{const t=e.target.closest('.th');if(t){theme=(t.dataset.t===theme&&theme!=='전체')?'전체':t.dataset.t;renderThemes();renderCal();return;}
 const b=e.target.closest('.dish');if(b){openDish(+b.dataset.i,+b.dataset.m);return;}});
const dlg=document.getElementById('dlg');
document.getElementById('dx').onclick=()=>dlg.close?dlg.close():dlg.removeAttribute('open');
dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close();});
document.getElementById('prev').onclick=()=>{if(mi>0){mi--;renderThemes();renderCal();}};
document.getElementById('next').onclick=()=>{if(mi<months.length-1){mi++;renderThemes();renderCal();}};
const FAILS=D.fails||[];
document.getElementById('news').innerHTML=D.news.length?D.news.map(n=>`<li><a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a></li>`).join('')
 :`<li class="muted">${FAILS.includes('오늘의 음식 뉴스')?'<b>데이터 없음</b> — 다시 시도했지만 가져오지 못했습니다. 다음 실행 때 다시 받아 옵니다.':'오늘 기사가 없습니다.'}</li>`;
function setV(v){vsel=v;try{localStorage.setItem('meal-variant',String(v));}catch(e){}renderV();renderCal();
 const c=document.getElementById('cal');c.classList.remove('flash');void c.offsetWidth;c.classList.add('flash');}
document.getElementById('regen').onclick=()=>setV((vsel+1)%NV);
document.getElementById('vreset').onclick=()=>setV(0);
renderLog();renderThemes();renderV();renderCal();
</script></body></html>
"""


def render_html(d: dict, demo: bool) -> str:
    banner = ('<div style="background:#fff4d6;color:#5a4300;border:1px solid #f0d27a;padding:10px 14px;border-radius:10px;'
              'margin:14px 0;font-size:14px"><b>데모 모드</b> — 뉴스는 가상 데이터입니다.</div>') if demo else ""
    return (HTML.replace("__DATA__", json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
            .replace("__DEMO__", banner).replace("__DATE__", d["today"]).replace("__UPDATED__", d["updated"])
            .replace("__GENERATED__", html.escape(d["generated"])))


# ---------------------------------------------------------------- PDF
def render_pdf(d: dict, now: dt.datetime, path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Rectangle

    have = {f.name for f in font_manager.fontManager.ttflist}
    for nm in ("Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic"):
        if nm in have:
            plt.rcParams["font.family"] = nm
            break
    plt.rcParams.update({"axes.unicode_minus": False})
    TEXT, SUB, MUTED, ACC = "#1b1a17", "#56534c", "#8a867c", "#d9622b"
    MC = ["#2f8f5b", "#2a78d6", "#c2410c"]
    MK = ["", "[키트] ", "[배달] "]
    ym = now.strftime("%Y-%m")
    plan = decode(d["plans"][ym]["전체"][0])
    dishes = d["dishes"]

    def wrap(t, w):
        out, cur, n = [], "", 0
        for ch in t:
            cw = 2 if ord(ch) > 0x2000 else 1
            if n + cw > w and cur:
                out.append(cur); cur, n = "", 0
            cur += ch; n += cw
        return out + ([cur] if cur else [])

    with PdfPages(path) as pdf:
        # 1쪽: 달력 (가로)
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.text(0.04, 0.955, f"이번달 식단 추천 · {now.year}년 {now.month}월", fontsize=17, fontweight="bold", color=TEXT, va="top")
        fig.text(0.04, 0.918, f"생성 {d['generated']} · 하루 3가지(국·찌개 + 메인 + 별미) · 표시 없음=집밥  [키트]=밀키트  [배달]=배달  먹음=식사 기록"
                 " · 레시피·주문 링크는 웹페이지에서", fontsize=8, color=SUB, va="top")
        if d.get("fails"):
            fig.text(0.96, 0.955, "※ 데이터 없음: " + ", ".join(d["fails"]), fontsize=8, color="#a15c00", ha="right", va="top")
        x0, x1, ytop, ybot = 0.04, 0.96, 0.885, 0.04
        cw = (x1 - x0) / 7
        first = (dt.date(now.year, now.month, 1).weekday() + 1) % 7      # 일요일 시작
        nd = calendar.monthrange(now.year, now.month)[1]
        rows = (first + nd + 6) // 7
        hh = 0.03
        rh = (ytop - hh - ybot) / rows
        for i, w in enumerate("일월화수목금토"):
            fig.text(x0 + cw * (i + 0.5), ytop - 0.006, w, fontsize=10, fontweight="bold", ha="center", va="top",
                     color="#d1352b" if i == 0 else "#2a6fd6" if i == 6 else SUB)
        for day in range(1, nd + 1):
            pos = first + day - 1
            r, c = divmod(pos, 7)
            cx, cy = x0 + c * cw, ytop - hh - (r + 1) * rh
            today = day == now.day
            fig.add_artist(Rectangle((cx + 0.002, cy + 0.003), cw - 0.004, rh - 0.006, transform=fig.transFigure,
                                     facecolor="#fff3c4" if today else "#fffdf9", edgecolor=ACC if today else "#d8d2c4", lw=1.2 if today else 0.6))
            fig.text(cx + 0.007, cy + rh - 0.011, str(day) + (" 오늘" if today else ""), fontsize=8.5, fontweight="bold", va="top",
                     color="#d1352b" if c == 0 else "#2a6fd6" if c == 6 else TEXT)
            yy = cy + rh - 0.034
            ate = d.get("log", {}).get(f"{ym}-{day:02d}")
            if ate:
                for k, part in enumerate(wrap("먹음: " + ", ".join(t for t, _ in ate), 22)[:3]):
                    fig.text(cx + 0.008, yy, part, fontsize=6.6, va="top", color=SUB, fontweight="bold")
                    yy -= 0.0165
            for i, m in ([] if ate and day < now.day else (plan[day - 1] if day - 1 < len(plan) else [])):
                for k, part in enumerate(wrap(MK[m] + dishes[i]["n"], 22)[:2]):
                    fig.text(cx + 0.008, yy, ("· " if k == 0 else "  ") + part, fontsize=6.8, va="top", color=MC[m] if m else TEXT)
                    yy -= 0.0165
        pdf.savefig(fig); plt.close(fig)

        # 2쪽: 오늘의 추천 레시피 + 뉴스 (세로)
        fig = plt.figure(figsize=(8.27, 11.69))
        y = [0.955]

        def t(txt, size=8.5, color=TEXT, bold=False, ind=0.0, lh=0.0155, w=100, url=None):
            for part in wrap(txt, w):
                o = fig.text(0.06 + ind, y[0], part, fontsize=size, color=color, va="top", fontweight="bold" if bold else "normal")
                if url:
                    o.set_url(url)
                y[0] -= lh

        t(f"오늘의 추천 · {d['today']} ({WEEKDAY[now.weekday()]})", 15, bold=True, lh=0.03)
        today_items = plan[now.day - 1] if now.day - 1 < len(plan) else []
        for i, m in today_items:
            dd = dishes[i]
            t(f"■ {dd['n']}  —  {['집밥', '밀키트', '배달'][m]} · {dd['time']}분 · 난이도 {({'보통': '중간'}).get(dd['lv'], dd['lv'])}", 10.5, ACC, bold=True, lh=0.02)
            if m == 2 and dd["dl"]:
                ch = ", ".join(dd["dl"]["chains"]) or "동네 가게"
                t(f"배달: {ch} · 배달앱에서 '{dd['dl']['kw']}' 검색 (아래는 집에서 만들 때 레시피)", 8, SUB, ind=0.01)
            elif m == 1:
                t(f"밀키트: 쿠팡·컬리·네이버쇼핑에서 '{dd['n']} 밀키트' 검색, 밤 11시~자정 전 주문 시 다음 날 아침 도착 (아래는 직접 만들 때)", 8, SUB, ind=0.01)
            t("재료  " + dd["ing"], 8, SUB, ind=0.01, lh=0.0145, w=104)
            for k, s in enumerate(dd["steps"], 1):
                t(f"{k}. {s}", 8.3, ind=0.01, lh=0.0148, w=102)
            y[0] -= 0.012
        y[0] -= 0.01
        t("오늘의 음식 뉴스", 13, bold=True, lh=0.025)
        for k, n in enumerate(d["news"], 1):
            t(f"{k}. {n['title']}", 8.6, ind=0.01, lh=0.0158, w=102, url=n["link"] or None)
        if not d["news"]:
            t("뉴스를 가져오지 못했습니다.", 8.5, MUTED)
        fig.text(0.06, 0.02, "daily_meal-plan", fontsize=6.5, color=MUTED)
        pdf.savefig(fig); plt.close(fig)
    return path


# ---------------------------------------------------------------- 저장
def write_indexes(site: Path, sub: str) -> None:
    head = ('<!DOCTYPE html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<body style="font-family:-apple-system,sans-serif;padding:20px;line-height:1.8">')
    arch = site / sub / "archive"
    links = sorted((p for p in arch.glob("*.html") if p.name != "index.html"), reverse=True)
    items = "".join(f'<li><a href="{p.name}">{p.stem}</a></li>' for p in links)
    (arch / "index.html").write_text(f'{head}<title>{sub} 지난 리포트</title><h2>{sub} · 지난 리포트</h2>'
                                     f'<p><a href="../">← 최신</a></p><ul>{items}</ul>', encoding="utf-8")
    subs = sorted(x.name for x in site.iterdir() if x.is_dir() and (x / "index.html").exists())
    items = "".join(f'<li><a href="{x}/">{x}</a> · <a href="{x}/archive/">지난 리포트</a></li>' for x in subs)
    (site / "index.html").write_text(f'{head}<title>reports</title><h2>reports</h2><ul>{items}</ul>', encoding="utf-8")
    (site / ".nojekyll").touch()


def main(argv=None):
    ap = argparse.ArgumentParser(description="이번달 식단 추천")
    ap.add_argument("--outdir", default="_site/daily_meal-plan")
    ap.add_argument("--keep-days", type=int, default=365)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--date", help="테스트용 기준 날짜 YYYY-MM-DD")
    ap.add_argument("--log-file", help="테스트용: 구글 드라이브 대신 로컬 식사기록.xlsx")
    a = ap.parse_args(argv)

    now = dt.datetime.now(KST)
    if a.date:
        now = dt.datetime.strptime(a.date, "%Y-%m-%d").replace(hour=6, tzinfo=KST)
    out = Path(os.path.expanduser(a.outdir))
    (out / "archive").mkdir(parents=True, exist_ok=True)
    global HIST, LOG_STATE
    if a.log_file:
        HIST, LOG_STATE = L.History.from_xlsx(Path(a.log_file).read_bytes()), "ok"
    elif not a.demo:
        load_history()
    news = demo_news() if a.demo else fetch_news()
    d = build_data(now, news)
    d["fails"] = list(NR.FAILS)
    wd = WEEKDAY[now.weekday()]
    sfx = "_demo" if a.demo else ""
    page = NR.inject_banner(render_html(d, a.demo))
    (out / "index.html").write_text(page, encoding="utf-8")
    dated = out / "archive" / f"{now:%Y-%m-%d}_{wd}{sfx}.html"
    dated.write_text(page, encoding="utf-8")
    meta = {"date": now.strftime("%Y-%m-%d"), "weekday": wd, "month": now.strftime("%Y-%m"),
            "pdf_name": f"{now:%m%d}_{wd}{sfx}.pdf", "html_name": dated.name, "generated": d["generated"], "pdf": False}
    if not a.no_pdf:
        try:
            render_pdf(d, now, out / "latest.pdf"); meta["pdf"] = True
        except Exception as e:
            log(f"PDF 실패: {e}")
    (out / "latest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    cut = (now - dt.timedelta(days=a.keep_days)).strftime("%Y-%m-%d")
    for p in (out / "archive").glob("*.html"):
        if p.name != "index.html" and p.name[:10] < cut:
            p.unlink()
    write_indexes(out.parent, out.name)
    log(f"완료: {dated}")


if __name__ == "__main__":
    main()
