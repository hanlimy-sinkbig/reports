#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
야구 인사이트 대시보드 (daily_baseball-insight)
=============================================
매일 아침 한국(KBO)·미국(MLB)·일본(NPB) 프로야구 순위·팀 정보·주요 소식과
사회인야구 소식을 모아 대시보드(HTML)와 PDF 를 GitHub Pages 에 게시합니다.

  ① 오늘의 헤드라인   ② KBO 순위·팀·소식   ③ MLB 순위·어제 경기·코리안리거·소식
  ④ NPB 순위·팀·소식   ⑤ 사회인야구 소식

데이터: KBO 공식 기록실(koreabaseball.com) · MLB Stats API(statsapi.mlb.com) · NPB 공식(npb.jp)
        · 뉴스는 Google News RSS (제목·링크만)

  python baseball_insight.py --outdir _site/daily_baseball-insight
  python baseball_insight.py --demo --outdir out/daily_baseball-insight    # 네트워크 없이 레이아웃 확인
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseball_data as B  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

KST = dt.timezone(dt.timedelta(hours=9))
WEEKDAY = "월화수목금토일"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def log(m):
    print(f"[{dt.datetime.now(KST):%H:%M:%S}] {m}", file=sys.stderr, flush=True)


def get(url, **kw):
    r = requests.get(url, timeout=25, headers=UA, **kw)
    r.raise_for_status()
    return r


def season_year(now: dt.datetime) -> int:
    """3월 전에는 지난 시즌 순위를 보여 준다."""
    return now.year if now.month >= 3 else now.year - 1


# ---------------------------------------------------------------- 표 파서 (표준 라이브러리)
class Tables(HTMLParser):
    """페이지의 모든 <table>을 [행[셀 텍스트]] 목록으로 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack, self._row, self._cell = [], [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            if self._row:
                self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_tables(text: str) -> list[list[list[str]]]:
    p = Tables()
    p.feed(text)
    return p.tables


def nfkc(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


# ---------------------------------------------------------------- KBO
def kbo_standings_from_html(text: str) -> dict:
    rows, date = [], ""
    m = re.search(r"(20\d{2})[.\-/](\d{2})[.\-/](\d{2})", text)
    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for tb in parse_tables(text):
        hdr = next((r for r in tb if "팀명" in r), None)
        idx = {h: i for i, h in enumerate(hdr)} if hdr else {}
        cand = []
        for r in tb:
            team = next((c for c in r if c in B.KBO_TEAMS), None)
            if not team or r is hdr:
                continue
            ti = r.index(team)

            def col(name, off):
                i = idx.get(name, ti + off)
                return r[i] if i < len(r) else ""
            cand.append({"rank": col("순위", -1), "team": team, "g": col("경기", 1), "w": col("승", 2), "l": col("패", 3),
                         "t": col("무", 4), "pct": col("승률", 5), "gb": col("게임차", 6), "l10": col("최근10경기", 7),
                         "streak": col("연속", 8)})
        if len(cand) >= 8:
            rows = cand
            break
    return {"date": date, "rows": rows}


def fetch_kbo() -> dict:
    url = "https://www.koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx"
    try:
        r = get(url)
        r.encoding = r.encoding or "utf-8"
        d = kbo_standings_from_html(r.text)
        log(f"KBO 순위: {len(d['rows'])}팀 ({d['date']})")
        d["src"] = url
        return d
    except Exception as e:
        log(f"KBO 순위 실패: {e}")
        return {"date": "", "rows": [], "src": url, "error": str(e)}


# ---------------------------------------------------------------- NPB
NPB_ALIAS = {"読売": "巨人", "ジャイアンツ": "巨人", "タイガース": "阪神", "ベイスターズ": "DeNA", "カープ": "広島",
             "スワローズ": "ヤクルト", "ドラゴンズ": "中日", "ホークス": "ソフトバンク", "ファイターズ": "日本ハム",
             "マリーンズ": "ロッテ", "イーグルス": "楽天", "ライオンズ": "西武", "バファローズ": "オリックス"}


def npb_key(cell: str) -> str | None:
    """'阪神タイガース'·'阪　神'·'巨人' 등 표기 → NPB_TEAMS 키."""
    c = nfkc(cell)
    if c in B.NPB_TEAMS:
        return c
    if len(c) > 20:
        return None
    for k in B.NPB_TEAMS:
        if c.startswith(k):
            return k
    for a, k in NPB_ALIAS.items():
        if a in c:
            return k
    return None


def npb_standings_from_html(text: str) -> list[dict]:
    out = []
    for tb in parse_tables(text):
        cand = []
        for r in tb:
            if not r:
                continue
            ti = next((i for i, c in enumerate(r[:3]) if npb_key(c)), None)
            if ti is None:
                continue
            nums = r[ti + 1: ti + 7]
            if len(nums) < 6 or not re.fullmatch(r"\d+", nfkc(nums[0])):
                continue
            key = npb_key(r[ti])
            gb = nfkc(nums[5])
            cand.append({"team": key, "g": nfkc(nums[0]), "w": nfkc(nums[1]), "l": nfkc(nums[2]), "t": nfkc(nums[3]),
                         "pct": nfkc(nums[4]), "gb": "-" if gb in ("--", "-", "") else gb})
        if len(cand) >= 6:
            # 같은 표에 팀이 두 번 나오면(맞대결 표 등) 첫 등장만
            seen, uniq = set(), []
            for c in cand:
                if c["team"] not in seen:
                    seen.add(c["team"]); uniq.append(c)
            out = uniq[:6]
            break
    for i, c in enumerate(out, 1):
        c["rank"] = str(i)
    return out


def fetch_npb(year: int) -> dict:
    res = {"year": year, "central": [], "pacific": []}
    for key, page in (("central", "std_c"), ("pacific", "std_p")):
        url = f"https://npb.jp/bis/{year}/stats/{page}.html"
        try:
            r = get(url)
            r.encoding = "utf-8"
            res[key] = npb_standings_from_html(r.text)
            log(f"NPB {key}: {len(res[key])}팀")
        except Exception as e:
            log(f"NPB {key} 실패: {e}")
        res[key + "_src"] = url
    return res


# ---------------------------------------------------------------- MLB
def fetch_mlb(year: int, now: dt.datetime) -> dict:
    res = {"year": year, "divisions": [], "games": [], "game_date": "", "teams": {}}
    base = "https://statsapi.mlb.com/api/v1"
    try:
        t = get(f"{base}/teams", params={"sportId": 1, "season": year}).json()
        for tm in t.get("teams", []):
            res["teams"][tm["id"]] = {"city": tm.get("locationName", ""), "venue": (tm.get("venue") or {}).get("name", ""),
                                      "abbr": tm.get("abbreviation", "")}
    except Exception as e:
        log(f"MLB 팀 정보 실패: {e}")
    try:
        s = get(f"{base}/standings", params={"leagueId": "103,104", "season": year, "standingsTypes": "regularSeason"}).json()
        divs = {}
        for rec in s.get("records", []):
            did = (rec.get("division") or {}).get("id")
            rows = []
            for tr in rec.get("teamRecords", []):
                tid = tr["team"]["id"]
                rows.append({"rank": tr.get("divisionRank", ""), "id": tid, "team": B.MLB_KO.get(tid, tr["team"].get("name", "")),
                             "w": tr.get("wins", ""), "l": tr.get("losses", ""), "pct": tr.get("winningPercentage", ""),
                             "gb": tr.get("gamesBack", ""), "streak": (tr.get("streak") or {}).get("streakCode", "")})
            rows.sort(key=lambda r: int(r["rank"] or 99))
            divs[did] = rows
        res["divisions"] = [{"name": B.MLB_DIV.get(k, str(k)), "rows": divs[k]} for k in B.MLB_DIV_ORDER if k in divs]
        log(f"MLB 순위: {len(res['divisions'])}개 지구")
    except Exception as e:
        log(f"MLB 순위 실패: {e}")
    # 어제(미국 기준) 경기 결과 — 시즌 중에만 있음
    us_day = (now - dt.timedelta(hours=14)).date() - dt.timedelta(days=1)
    for day in (us_day + dt.timedelta(days=1), us_day):
        try:
            sch = get(f"{base}/schedule", params={"sportId": 1, "date": day.isoformat()}).json()
            games = []
            for dd in sch.get("dates", []):
                for g in dd.get("games", []):
                    a, h = g["teams"]["away"], g["teams"]["home"]
                    games.append({"away": B.MLB_KO.get(a["team"]["id"], a["team"]["name"]), "home": B.MLB_KO.get(h["team"]["id"], h["team"]["name"]),
                                  "as": a.get("score", ""), "hs": h.get("score", ""), "state": g.get("status", {}).get("detailedState", ""),
                                  "type": g.get("gameType", "")})
            done = [g for g in games if g["state"] in ("Final", "Game Over", "Completed Early")]
            if done:
                res["games"], res["game_date"] = done, day.isoformat()
                break
        except Exception as e:
            log(f"MLB 일정 실패: {e}")
            break
    log(f"MLB 경기 결과: {len(res['games'])}경기 ({res['game_date'] or '없음'})")
    return res


# ---------------------------------------------------------------- 뉴스
def fetch_news(label: str, q: str, limit: int = 10, lang: str = "ko", days: int = 2) -> list[dict]:
    if requests is None:
        return []
    loc = {"ko": "hl=ko&gl=KR&ceid=KR:ko", "ja": "hl=ja&gl=JP&ceid=JP:ja"}[lang]
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} when:{days}d") + "&" + loc
    try:
        root = ET.fromstring(get(url).content)
    except Exception as e:
        log(f"뉴스 실패 · {label}: {e}")
        return []
    out, seen = [], set()
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        key = re.sub(r"\W", "", title)[:28]
        if not title or key in seen:
            continue
        seen.add(key)
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(KST)
        except Exception:
            pub = None
        out.append({"title": title, "link": it.findtext("link") or "", "source": src,
                    "date": pub.strftime("%m/%d %H:%M") if pub else "", "ts": pub.isoformat() if pub else ""})
    out.sort(key=lambda n: n["ts"], reverse=True)
    out = out[:limit]
    log(f"뉴스 · {label}: {len(out)}건")
    return out


def headlines(news: dict, n_per=2, total=10) -> list[dict]:
    """섹션마다 최신 기사 몇 건씩 모아 중복 없이 헤드라인을 만든다."""
    out, seen = [], set()
    for key, label, _ in B.NEWS_QUERIES:
        for it in news.get(key, [])[:n_per]:
            k = re.sub(r"\W", "", it["title"])[:20]
            if k not in seen:
                seen.add(k); out.append({**it, "tag": label})
    return out[:total]


# ---------------------------------------------------------------- 데모
def demo_data(year: int):
    kbo = {"date": f"{year}-10-01", "src": "#", "rows": [
        {"rank": str(i + 1), "team": t, "g": "144", "w": str(85 - i * 4), "l": str(56 + i * 4), "t": "3",
         "pct": f"{(85 - i * 4) / 141:.3f}", "gb": "0" if i == 0 else f"{i * 4.0}", "l10": "6승0무4패", "streak": "1승"}
        for i, t in enumerate(B.KBO_TEAMS)]}
    npb = {"year": year, "central_src": "#", "pacific_src": "#"}
    for key, lg in (("central", "센트럴"), ("pacific", "퍼시픽")):
        teams = [k for k, v in B.NPB_TEAMS.items() if v[1] == lg]
        npb[key] = [{"rank": str(i + 1), "team": t, "g": "143", "w": str(80 - i * 5), "l": str(60 + i * 5), "t": "3",
                     "pct": f".{571 - i * 35}", "gb": "-" if i == 0 else f"{i * 5.0}"} for i, t in enumerate(teams)]
    ids = list(B.MLB_KO)
    mlb = {"year": year, "game_date": "", "games": [], "teams": {i: {"city": "City", "venue": "Ballpark", "abbr": "ABC"} for i in ids},
           "divisions": [{"name": B.MLB_DIV[k], "rows": [{"rank": str(j + 1), "id": ids[(n * 5 + j) % 30], "team": B.MLB_KO[ids[(n * 5 + j) % 30]],
                                                           "w": 95 - j * 6, "l": 67 + j * 6, "pct": f".{586 - j * 37}", "gb": "-" if j == 0 else str(j * 6.0),
                                                           "streak": "W1"} for j in range(5)]} for n, k in enumerate(B.MLB_DIV_ORDER)]}
    news = {k: [{"title": f"[데모] {lab} 가상 헤드라인 {i + 1}", "link": "#", "source": "데모", "date": "11/13 06:00", "ts": ""}
                for i in range(4)] for k, lab, _ in B.NEWS_QUERIES}
    news["npb_ja"] = [{"title": f"[デモ] プロ野球 見出し {i + 1}", "link": "#", "source": "デモ", "date": "", "ts": ""} for i in range(3)]
    return kbo, npb, mlb, news


# ---------------------------------------------------------------- 데이터 조립
def build_data(kbo, npb, mlb, news, now, year) -> dict:
    kbo_rows = [{**r, "name": B.KBO_TEAMS[r["team"]][0], "city": B.KBO_TEAMS[r["team"]][1], "park": B.KBO_TEAMS[r["team"]][2]}
                for r in kbo["rows"]]
    kbo_info = [{"short": k, "name": v[0], "city": v[1], "park": v[2]} for k, v in B.KBO_TEAMS.items()]
    npb_out = {}
    for key in ("central", "pacific"):
        npb_out[key] = [{**r, "name": B.NPB_TEAMS[r["team"]][0]} for r in npb.get(key, [])]
    npb_info = [{"ja": k, "name": v[0], "league": v[1], "city": v[2], "park": v[3]} for k, v in B.NPB_TEAMS.items()]
    mlb_info = []
    for dv in mlb["divisions"]:
        for r in dv["rows"]:
            t = mlb["teams"].get(r["id"], {})
            r["city"], r["venue"] = t.get("city", ""), t.get("venue", "")
            mlb_info.append({"div": dv["name"], "name": r["team"], "city": r["city"], "venue": r["venue"]})
    sections = {k: {"label": lab, "items": news.get(k, []), "days": B.NEWS_DAYS.get(k, 2)} for k, lab, _ in B.NEWS_QUERIES}
    return {
        "generated": now.strftime("%Y-%m-%d %H:%M KST"), "today": now.strftime("%Y-%m-%d"), "updated": B.UPDATED, "year": year,
        "headlines": headlines(news), "news": sections, "npb_ja": news.get("npb_ja", []),
        "kbo": {"date": kbo.get("date", ""), "src": kbo.get("src", ""), "rows": kbo_rows, "info": kbo_info},
        "npb": {"central": npb_out["central"], "pacific": npb_out["pacific"], "info": npb_info,
                "src_c": npb.get("central_src", ""), "src_p": npb.get("pacific_src", "")},
        "mlb": {"divisions": mlb["divisions"], "games": mlb["games"], "game_date": mlb["game_date"], "info": mlb_info},
    }


# ---------------------------------------------------------------- HTML
HTML = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>야구 인사이트 · __DATE__</title>
<style>
:root{--surface-0:#f4f3f0;--surface-1:#fcfcfb;--border:#e3e2dd;--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#85847f;
 --accent:#2a78d6;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--hl:#eaf2fc}
@media (prefers-color-scheme: dark){:root{--surface-0:#121211;--surface-1:#1a1a19;--border:#2e2e2b;--text-primary:#f0efec;--text-secondary:#c3c2b7;
 --text-muted:#8d8c84;--accent:#3987e5;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--hl:#18243a}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);line-height:1.6;font-size:15px;
 font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:24px;margin:0 0 4px}.meta{color:var(--text-secondary);font-size:13px}.meta a{color:var(--text-secondary)}
nav{position:sticky;top:0;z-index:5;background:var(--surface-0);padding:10px 0;margin:8px 0 6px;display:flex;gap:6px;overflow-x:auto;border-bottom:1px solid var(--border)}
nav a{white-space:nowrap;text-decoration:none;color:var(--text-secondary);font-size:13px;padding:6px 10px;border-radius:999px;border:1px solid var(--border);background:var(--surface-1)}
section{margin-top:28px} h2{font-size:19px;margin:0 0 12px} h2 .num{color:var(--accent);margin-right:6px} h3{font-size:16px;margin:0 0 8px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:16px}
.grid{display:grid;gap:14px;align-items:start}.g2{grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:6px 7px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
th{color:var(--text-secondary);font-weight:600;font-size:12.5px}
th.l,td.l{text-align:left}td.wrap{white-space:normal}
tr.top td{background:var(--hl)}
.tbl{overflow-x:auto}
.news li{padding:6px 0;border-bottom:1px solid var(--border);list-style:none}.news{margin:0;padding:0}
.news a{color:var(--text-primary);text-decoration:none}.news a:hover{text-decoration:underline}
.src{color:var(--text-muted);font-size:12px;margin-left:6px;white-space:nowrap}
.tag{display:inline-block;font-size:11.5px;padding:0 8px;border-radius:999px;border:1px solid var(--border);color:var(--text-secondary);margin-right:6px}
.muted{color:var(--text-muted);font-size:12.5px}.note{font-size:12.5px;color:var(--text-secondary);margin:8px 0 0}
details summary{cursor:pointer;color:var(--text-secondary);font-size:13.5px;margin-top:10px}
footer{margin-top:40px;color:var(--text-muted);font-size:12px}footer a{color:var(--text-muted)}
</style></head><body><div class="wrap">
<header><h1>야구 인사이트</h1>
<div class="meta">생성 __GENERATED__ · 매일 갱신 · <a href="latest.pdf">PDF</a> · <a href="archive/">지난 리포트</a></div></header>
__DEMO__
<nav><a href="#s1">① 헤드라인</a><a href="#s2">② KBO</a><a href="#s3">③ MLB</a><a href="#s4">④ NPB</a><a href="#s5">⑤ 사회인야구</a></nav>

<section id="s1"><h2><span class="num">①</span>오늘의 헤드라인</h2><div class="card"><ul class="news" id="hl"></ul></div></section>

<section id="s2"><h2><span class="num">②</span>KBO 리그</h2>
 <div class="grid g2">
  <div class="card tbl"><h3>순위 <span class="muted" id="kbo-date"></span></h3><table id="kbo-tbl"></table>
   <details><summary>구단 정보 (연고지·홈구장)</summary><table id="kbo-info"></table></details></div>
  <div class="grid"><div class="card" id="n-kbo"></div><div class="card" id="n-kbo_move"></div></div>
 </div>
</section>

<section id="s3"><h2><span class="num">③</span>MLB</h2>
 <div class="grid g2">
  <div class="card" id="n-korean_mlb"></div><div class="card" id="n-mlb"></div>
 </div>
 <div class="card" style="margin-top:14px" id="mlb-games"></div>
 <h3 style="margin:18px 0 8px">지구별 순위 <span class="muted" id="mlb-year"></span></h3>
 <div class="grid g3" id="mlb-div"></div>
</section>

<section id="s4"><h2><span class="num">④</span>NPB (일본프로야구)</h2>
 <div class="grid g2">
  <div class="card tbl"><h3>센트럴 리그 <span class="muted" id="npb-year"></span></h3><table id="npb-c"></table></div>
  <div class="card tbl"><h3>퍼시픽 리그</h3><table id="npb-p"></table></div>
 </div>
 <div class="card tbl" style="margin-top:14px"><details><summary>구단 정보 (리그·연고지·홈구장)</summary><table id="npb-info"></table></details></div>
 <div class="grid g2" style="margin-top:14px"><div class="card" id="n-npb"></div>
  <div class="card"><h3>일본 현지 헤드라인 <span class="muted">일본어 원문</span></h3><ul class="news" id="npb-ja"></ul></div></div>
</section>

<section id="s5"><h2><span class="num">⑤</span>사회인야구</h2>
 <div class="grid g2"><div class="card" id="n-amateur"></div><div class="card" id="n-amateur2"></div></div>
</section>

<footer>출처: KBO 기록실(koreabaseball.com) · MLB Stats API · NPB 공식(npb.jp) · Google News. 기사 본문은 싣지 않고 제목과 원문 링크만 제공합니다.
 비시즌에는 마지막 정규시즌 최종 순위를 보여 줍니다. · baseball_insight.py</footer>
</div>
<script>
const D=__DATA__;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const li=n=>`<li>${n.tag?`<span class="tag">${esc(n.tag)}</span>`:''}<a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a><span class="src">${esc(n.source)} ${esc(n.date)}</span></li>`;
const none='<p class="muted">가져오지 못했습니다(사이트 응답 없음 또는 비시즌). 출처 링크에서 직접 확인하세요.</p>';
document.getElementById('hl').innerHTML=D.headlines.map(li).join('')||'<li class="muted">최근 2일 기사가 없습니다.</li>';
for(const [k,s] of Object.entries(D.news)){const el=document.getElementById('n-'+k);if(!el)continue;
 el.innerHTML=`<h3>${esc(s.label)} <span class="muted">${s.items.length}건</span></h3>`+(s.items.length?`<ul class="news">${s.items.map(li).join('')}</ul>`:`<p class="muted">최근 ${s.days}일 기사가 없습니다.</p>`);}
// KBO
const K=D.kbo;
document.getElementById('kbo-date').textContent=K.date?`(${K.date} 기준)`:'';
document.getElementById('kbo-tbl').outerHTML=K.rows.length?`<table><tr><th>순위</th><th class="l">팀</th><th>경기</th><th>승</th><th>패</th><th>무</th><th>승률</th><th>게임차</th><th>최근10</th><th>연속</th></tr>`+
 K.rows.map((r,i)=>`<tr class="${i<5?'top':''}"><td>${esc(r.rank)}</td><td class="l"><b>${esc(r.name)}</b></td><td>${esc(r.g)}</td><td>${esc(r.w)}</td><td>${esc(r.l)}</td><td>${esc(r.t)}</td><td>${esc(r.pct)}</td><td>${esc(r.gb)}</td><td>${esc(r.l10)}</td><td>${esc(r.streak)}</td></tr>`).join('')+
 `</table><p class="note">음영: 5위까지(포스트시즌 진출권). 시즌이 끝나면 KBO 기록실은 포스트시즌 결과를 반영한 최종 순위를 보여 주며, 게임차는 정규시즌 기준입니다 · <a href="${esc(K.src)}" target="_blank" rel="noopener">KBO 기록실</a></p>`:none;
document.getElementById('kbo-info').innerHTML='<tr><th class="l">구단</th><th class="l">연고지</th><th class="l">홈구장</th></tr>'+K.info.map(t=>`<tr><td class="l">${esc(t.name)}</td><td class="l">${esc(t.city)}</td><td class="l">${esc(t.park)}</td></tr>`).join('');
// MLB
const M=D.mlb;
document.getElementById('mlb-year').textContent=`(${D.year} 정규시즌)`;
document.getElementById('mlb-games').innerHTML=M.games.length?`<h3>최근 경기 결과 <span class="muted">${esc(M.game_date)} (미국 현지)</span></h3><div class="tbl"><table>`+
 M.games.map(g=>{const aw=+g.as>+g.hs;return `<tr><td class="l">${aw?'<b>':''}${esc(g.away)}${aw?'</b>':''}</td><td>${esc(g.as)} : ${esc(g.hs)}</td><td class="l">${aw?'':'<b>'}${esc(g.home)}${aw?'':'</b>'}</td></tr>`}).join('')+'</table></div>'
 :'<h3>최근 경기 결과</h3><p class="muted">최근 이틀간 경기가 없습니다(비시즌 또는 휴식일).</p>';
document.getElementById('mlb-div').innerHTML=M.divisions.length?M.divisions.map(dv=>`<div class="card tbl"><h3>${esc(dv.name)}</h3><table><tr><th>#</th><th class="l">팀</th><th>승</th><th>패</th><th>승률</th><th>GB</th></tr>`+
 dv.rows.map(r=>`<tr class="${r.rank==1?'top':''}"><td>${esc(r.rank)}</td><td class="l wrap" title="${esc(r.city)} · ${esc(r.venue)}"><b>${esc(r.team)}</b><br><span class="muted">${esc(r.venue)}</span></td><td>${esc(r.w)}</td><td>${esc(r.l)}</td><td>${esc(r.pct)}</td><td>${esc(r.gb)}</td></tr>`).join('')+'</table></div>').join(''):`<div class="card">${none}</div>`;
// NPB
const N=D.npb;
document.getElementById('npb-year').textContent=`(${D.year} 정규시즌)`;
const npbT=(rows,src)=>rows.length?`<table><tr><th>순위</th><th class="l">팀</th><th>경기</th><th>승</th><th>패</th><th>무</th><th>승률</th><th>게임차</th></tr>`+
 rows.map((r,i)=>`<tr class="${i<3?'top':''}"><td>${esc(r.rank)}</td><td class="l"><b>${esc(r.name)}</b></td><td>${esc(r.g)}</td><td>${esc(r.w)}</td><td>${esc(r.l)}</td><td>${esc(r.t)}</td><td>${esc(r.pct)}</td><td>${esc(r.gb)}</td></tr>`).join('')+
 `</table><p class="note">음영: 3위까지(클라이맥스 시리즈) · <a href="${esc(src)}" target="_blank" rel="noopener">NPB 공식</a></p>`:none;
document.getElementById('npb-c').outerHTML=npbT(N.central,N.src_c);
document.getElementById('npb-p').outerHTML=npbT(N.pacific,N.src_p);
document.getElementById('npb-info').innerHTML='<tr><th class="l">구단</th><th class="l">리그</th><th class="l">연고지</th><th class="l">홈구장</th></tr>'+N.info.map(t=>`<tr><td class="l">${esc(t.name)}</td><td class="l">${esc(t.league)}</td><td class="l">${esc(t.city)}</td><td class="l">${esc(t.park)}</td></tr>`).join('');
document.getElementById('npb-ja').innerHTML=D.npb_ja.map(li).join('')||'<li class="muted">기사가 없습니다.</li>';
</script></body></html>
"""


def render_html(d: dict, demo: bool) -> str:
    banner = ('<div style="background:#fff4d6;color:#5a4300;border:1px solid #f0d27a;padding:10px 14px;border-radius:10px;'
              'margin:14px 0;font-size:14px"><b>데모 모드</b> — 순위·뉴스는 가상 데이터입니다.</div>') if demo else ""
    return (HTML.replace("__DATA__", json.dumps(d, ensure_ascii=False).replace("</", "<\\/")).replace("__DEMO__", banner)
            .replace("__DATE__", d["today"]).replace("__GENERATED__", html.escape(d["generated"])))


# ---------------------------------------------------------------- PDF
def render_pdf(d: dict, path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.backends.backend_pdf import PdfPages

    have = {f.name for f in font_manager.fontManager.ttflist}
    for nm in ("Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic"):
        if nm in have:
            plt.rcParams["font.family"] = nm
            break
    plt.rcParams.update({"axes.unicode_minus": False})
    TEXT, SUB, MUTED, S1 = "#0b0b0b", "#52514e", "#85847f", "#2a78d6"

    def wrap(t, w):
        out, cur, n = [], "", 0
        for ch in t:
            cw = 2 if ord(ch) > 0x2000 else 1
            if n + cw > w and cur:
                out.append(cur); cur, n = "", 0
            cur += ch; n += cw
        return out + ([cur] if cur else [])

    class Page:
        def __init__(s, pdf, title, pno):
            s.pdf, s.fig, s.y, s.pno, s.title = pdf, plt.figure(figsize=(8.27, 11.69)), 0.905, pno, title
            s.fig.text(0.06, 0.965, title, fontsize=15, fontweight="bold", color=TEXT, va="top")
            s.fig.text(0.06, 0.94, f"생성 {d['generated']} · 비시즌에는 마지막 정규시즌 최종 순위", fontsize=7.5, color=SUB, va="top")
            s.fig.text(0.94, 0.02, str(pno), fontsize=7, color=MUTED, ha="right")
            s.fig.text(0.06, 0.02, "daily_baseball-insight", fontsize=6.5, color=MUTED)

        def t(s, txt, size=8.5, color=TEXT, bold=False, ind=0.0, lh=0.0155, w=104, url=None):
            for part in wrap(txt, w):
                o = s.fig.text(0.06 + ind, s.y, part, fontsize=size, color=color, va="top", fontweight="bold" if bold else "normal")
                if url:
                    o.set_url(url)
                s.y -= lh

        def row(s, cells, xs, size=7.8, bold=False, color=TEXT):
            for c, (x, ha) in zip(cells, xs):
                s.fig.text(x, s.y, str(c), fontsize=size, color=color, ha=ha, va="top", fontweight="bold" if bold else "normal")
            s.y -= 0.0158

        def close(s):
            s.pdf.savefig(s.fig); plt.close(s.fig)

    def news_block(pg, title, items, n=6):
        pg.t("■ " + title, 9.5, S1, bold=True)
        for it in items[:n] or [{"title": "최근 기사 없음", "link": "", "source": "", "date": ""}]:
            pg.t(f"· {it['title']}  ({it['source']} {it['date']})", 7.8, ind=0.01, lh=0.0142, w=108, url=it["link"] or None)
        pg.y -= 0.006

    with PdfPages(path) as pdf:
        pg = Page(pdf, f"야구 인사이트 · {d['today']}", 1)
        pg.t("① 오늘의 헤드라인", 10.5, bold=True)
        for it in d["headlines"]:
            pg.t(f"[{it['tag']}] {it['title']}  ({it['source']} {it['date']})", 8, ind=0.01, lh=0.0148, w=106, url=it["link"] or None)
        pg.y -= 0.012
        pg.t(f"② KBO 순위 {('(' + d['kbo']['date'] + ' 기준)') if d['kbo']['date'] else ''}", 10.5, bold=True)
        xs = [(0.08, "right"), (0.1, "left"), (0.33, "right"), (0.39, "right"), (0.45, "right"), (0.5, "right"), (0.58, "right"), (0.66, "right"), (0.78, "right"), (0.87, "right")]
        if d["kbo"]["rows"]:
            pg.row(["순위", "팀", "경기", "승", "패", "무", "승률", "게임차", "최근10", "연속"], xs, bold=True, color=SUB)
            for r in d["kbo"]["rows"]:
                pg.row([r["rank"], r["name"], r["g"], r["w"], r["l"], r["t"], r["pct"], r["gb"], r["l10"], r["streak"]], xs)
        else:
            pg.t("순위를 가져오지 못했습니다.", 8, MUTED)
        pg.y -= 0.01
        news_block(pg, d["news"]["kbo"]["label"], d["news"]["kbo"]["items"], 6)
        news_block(pg, d["news"]["kbo_move"]["label"], d["news"]["kbo_move"]["items"], 6)
        pg.close()

        pg = Page(pdf, "③ MLB", 2)
        news_block(pg, d["news"]["korean_mlb"]["label"], d["news"]["korean_mlb"]["items"], 7)
        news_block(pg, d["news"]["mlb"]["label"], d["news"]["mlb"]["items"], 7)
        if d["mlb"]["games"]:
            pg.t(f"최근 경기 결과 ({d['mlb']['game_date']} 미국 현지)", 9.5, S1, bold=True)
            for g in d["mlb"]["games"][:15]:
                pg.t(f"{g['away']} {g['as']} : {g['hs']} {g['home']}", 7.8, ind=0.01, lh=0.0142)
            pg.y -= 0.006
        pg.t(f"지구별 순위 ({d['year']} 정규시즌)", 9.5, S1, bold=True)
        cols = [(0.06, 0.0), (0.37, 0.0), (0.68, 0.0)]
        top = pg.y
        for i, dv in enumerate(d["mlb"]["divisions"]):
            x0 = 0.06 + (i % 3) * 0.31
            pg.y = top - (i // 3) * 0.125
            pg.fig.text(x0, pg.y, dv["name"], fontsize=8.5, fontweight="bold", va="top", color=TEXT); pg.y -= 0.016
            for r in dv["rows"]:
                pg.row([r["rank"], r["team"], f"{r['w']}-{r['l']}", r["gb"]], [(x0 + 0.01, "right"), (x0 + 0.02, "left"), (x0 + 0.23, "right"), (x0 + 0.285, "right")], size=7.2)
        if not d["mlb"]["divisions"]:
            pg.t("순위를 가져오지 못했습니다.", 8, MUTED)
        pg.close()

        pg = Page(pdf, "④ NPB · ⑤ 사회인야구", 3)
        xs = [(0.08, "right"), (0.1, "left"), (0.42, "right"), (0.48, "right"), (0.54, "right"), (0.59, "right"), (0.67, "right"), (0.75, "right")]
        for key, lab in (("central", "센트럴 리그"), ("pacific", "퍼시픽 리그")):
            pg.t(f"{lab} ({d['year']})", 9.5, S1, bold=True)
            if d["npb"][key]:
                pg.row(["순위", "팀", "경기", "승", "패", "무", "승률", "게임차"], xs, bold=True, color=SUB)
                for r in d["npb"][key]:
                    pg.row([r["rank"], r["name"], r["g"], r["w"], r["l"], r["t"], r["pct"], r["gb"]], xs)
            else:
                pg.t("순위를 가져오지 못했습니다.", 8, MUTED)
            pg.y -= 0.008
        news_block(pg, d["news"]["npb"]["label"], d["news"]["npb"]["items"], 5)
        news_block(pg, d["news"]["amateur"]["label"], d["news"]["amateur"]["items"], 8)
        news_block(pg, d["news"]["amateur2"]["label"], d["news"]["amateur2"]["items"], 6)
        pg.close()
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
    ap = argparse.ArgumentParser(description="야구 인사이트 대시보드")
    ap.add_argument("--outdir", default="_site/daily_baseball-insight")
    ap.add_argument("--keep-days", type=int, default=365)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args(argv)

    now = dt.datetime.now(KST)
    year = season_year(now)
    out = Path(os.path.expanduser(a.outdir))
    (out / "archive").mkdir(parents=True, exist_ok=True)
    if a.demo:
        kbo, npb, mlb, news = demo_data(year)
    else:
        kbo, npb, mlb = fetch_kbo(), fetch_npb(year), fetch_mlb(year, now)
        news = {k: fetch_news(lab, q, days=B.NEWS_DAYS.get(k, 2)) for k, lab, q in B.NEWS_QUERIES}
        news["npb_ja"] = fetch_news("NPB 일본어", B.NPB_JA_QUERY, limit=8, lang="ja", days=1)
    d = build_data(kbo, npb, mlb, news, now, year)
    wd = WEEKDAY[now.weekday()]
    sfx = "_demo" if a.demo else ""
    page = render_html(d, a.demo)
    (out / "index.html").write_text(page, encoding="utf-8")
    dated = out / "archive" / f"{now:%Y-%m-%d}_{wd}{sfx}.html"
    dated.write_text(page, encoding="utf-8")
    meta = {"date": now.strftime("%Y-%m-%d"), "weekday": wd, "month": now.strftime("%Y-%m"),
            "pdf_name": f"{now:%m%d}_{wd}{sfx}.pdf", "html_name": dated.name, "generated": d["generated"], "pdf": False}
    if not a.no_pdf:
        try:
            render_pdf(d, out / "latest.pdf"); meta["pdf"] = True
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
