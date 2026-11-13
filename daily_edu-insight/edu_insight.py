#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
교육·입시 인사이트 대시보드 (daily_edu-insight)
================================================
매일 아침, 정리된 입시 정보(edu_data.py)와 최근 7일 교육 뉴스(Google News RSS)를 합쳐
대시보드(HTML)와 PDF를 GitHub Pages 에 게시합니다.

  ① 핵심 요약 · 학생 타임라인        ② 의대 정원·합격선 (차트)
  ③ 고교 유형 비교 · 영재고/과학고/자사고  ④ 대학: 설카포 · 서성한
  ⑤ 의대 지망 학생 조언 · 선택과목 로드맵   ⑥ 이번 주 교육 뉴스(자동)

  python edu_insight.py --outdir _site/daily_edu-insight
  python edu_insight.py --demo --outdir out/daily_edu-insight     # 뉴스 없이 레이아웃 확인
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edu_data as E  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

KST = dt.timezone(dt.timedelta(hours=9))
WEEKDAY = "월화수목금토일"


def log(m):
    print(f"[{dt.datetime.now(KST):%H:%M:%S}] {m}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- 뉴스
def fetch_news(label: str, q: str, limit: int = 8) -> list[dict]:
    if requests is None:
        return []
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} when:7d") + "&hl=ko&gl=KR&ceid=KR:ko"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log(f"뉴스 실패 · {label}: {e}")
        return []
    out, seen = [], set()
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        key = re.sub(r"\W", "", title)[:30]
        if not title or key in seen:
            continue
        seen.add(key)
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(KST)
            ps = pub.strftime("%m/%d")
        except Exception:
            pub, ps = None, ""
        out.append({"title": title, "link": it.findtext("link") or "", "source": src, "date": ps,
                    "ts": pub.isoformat() if pub else ""})
        if len(out) >= limit:
            break
    log(f"뉴스 · {label}: {len(out)}건")
    return out


def demo_news():
    return {lab: [{"title": f"[데모] {lab} 관련 가상 헤드라인 {i + 1}", "link": "#", "source": "데모", "date": "", "ts": ""}
                  for i in range(3)] for lab, _ in E.NEWS_QUERIES}


# ---------------------------------------------------------------- HTML
HTML = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>교육·입시 인사이트 · __DATE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{--surface-0:#f4f3f0;--surface-1:#fcfcfb;--border:#e3e2dd;--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#85847f;
 --grid:#ebeae6;--accent:#2a78d6;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;
 --warn-bg:#fdf1e8;--warn-bd:#f2c7a6;--info-bg:#eaf2fc;--info-bd:#b9d3f3;--good-bg:#e7f6ef;--good-bd:#a9dcc4}
@media (prefers-color-scheme: dark){:root{--surface-0:#121211;--surface-1:#1a1a19;--border:#2e2e2b;--text-primary:#f0efec;--text-secondary:#c3c2b7;
 --text-muted:#8d8c84;--grid:#2a2a27;--accent:#3987e5;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;
 --warn-bg:#2e2119;--warn-bd:#5a3a24;--info-bg:#18243a;--info-bd:#2b4468;--good-bg:#15291f;--good-bd:#265a41}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);line-height:1.6;font-size:15px;
 font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:24px;margin:0 0 4px}.meta{color:var(--text-secondary);font-size:13px}
nav{position:sticky;top:0;z-index:5;background:var(--surface-0);padding:10px 0;margin:8px 0 6px;display:flex;gap:6px;overflow-x:auto;border-bottom:1px solid var(--border)}
nav a{white-space:nowrap;text-decoration:none;color:var(--text-secondary);font-size:13px;padding:6px 10px;border-radius:999px;border:1px solid var(--border);background:var(--surface-1)}
section{margin-top:28px} h2{font-size:19px;margin:0 0 12px} h2 .num{color:var(--accent);margin-right:6px} h3{font-size:16px;margin:0 0 8px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:16px}
.grid{display:grid;gap:14px}.g2{grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))}
.kp{border-radius:12px;padding:12px 14px;border:1px solid}
.kp.warn{background:var(--warn-bg);border-color:var(--warn-bd)}.kp.info{background:var(--info-bg);border-color:var(--info-bd)}.kp.good{background:var(--good-bg);border-color:var(--good-bd)}
.kp b{display:block;margin-bottom:4px}.kp .tag{font-size:11.5px;font-weight:700;margin-right:6px}
.kp p{margin:0;font-size:14px;color:var(--text-secondary)}
.tl{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.tl > div{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:8px 10px;font-size:13px}
.tl .y{font-weight:700;color:var(--accent)}.tl .g{font-size:12px;color:var(--text-muted)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:8px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
th{color:var(--text-secondary);font-weight:600;font-size:12.5px;white-space:nowrap}
.tbl{overflow-x:auto}
table.num th,table.num td{text-align:right;white-space:nowrap;padding:6px 5px}table.num th:first-child,table.num td:first-child{text-align:left}
table.num td small{color:var(--s2);font-size:11px;margin-left:2px}table.num tr.sum td{font-weight:700;border-top:2px solid var(--border)}
table.num tr.grp td{color:var(--text-muted);font-size:12px;text-align:left;padding-top:10px}
.stars{color:var(--accent);letter-spacing:1px;white-space:nowrap}
.chart{width:100%;height:330px}
ul.tight{margin:0;padding-left:18px} ul.tight li{margin:4px 0}
.pill{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:999px;border:1px solid var(--border);color:var(--text-secondary);margin-right:4px}
.news li{padding:6px 0;border-bottom:1px solid var(--border);list-style:none}.news{margin:0;padding:0}
.news a{color:var(--text-primary);text-decoration:none}.news a:hover{text-decoration:underline}
.src{color:var(--text-muted);font-size:12px;margin-left:6px}
.muted{color:var(--text-muted);font-size:12.5px}
.note{font-size:12.5px;color:var(--text-secondary);margin:8px 0 0}
footer{margin-top:40px;color:var(--text-muted);font-size:12px}
footer a{color:var(--text-muted)}
</style></head><body><div class="wrap">
<header><h1>교육·입시 인사이트</h1>
<div class="meta">생성 __GENERATED__ · 정리 데이터 기준일 __UPDATED__ · 매일 갱신 · <a href="latest.pdf">PDF</a> · <a href="archive/">지난 리포트</a></div></header>
__DEMO__
<nav><a href="#s1">① 핵심 요약</a><a href="#s2">② 의대 정원·합격선</a><a href="#s3">③ 고교 선택</a><a href="#s4">④ 대학</a><a href="#s5">⑤ 의대 지망 조언</a><a href="#s6">⑥ 이번 주 뉴스</a></nav>

<section id="s1"><h2><span class="num">①</span>핵심 요약 — 2031학년도 대입 학생 기준</h2>
 <div class="grid g3" id="kp"></div>
 <h3 style="margin-top:18px">학생 타임라인 (2026년 중2 → 2031학년도 입학)</h3>
 <div class="tl" id="tl"></div>
 <p class="note">2031학년도 대입은 2028 대입 개편 체제(내신 5등급·통합형 수능)를 따릅니다. 대학별 세부 요강은 2029년경 확정되므로 그 전까지는 2028학년도 계획을 기준으로 봅니다.</p>
</section>

<section id="s2"><h2><span class="num">②</span>의대 정원과 합격선</h2>
 <div class="grid g2">
  <div class="card"><h3>의대 정원 계획 (명)</h3><div id="quota" class="chart"></div><p class="note" id="quota-note"></p>
   <h3 style="margin-top:16px">권역별 의대 정원 (명)</h3><div class="tbl"><table class="num" id="quota-region"></table></div>
   <h3 style="margin-top:16px">주요 대학 의대 정원 (명)</h3><div class="tbl"><table class="num" id="quota-univ"></table></div>
   <p class="note" id="quota-tbl-note"></p></div>
  <div class="card"><h3>2026학년도 정시 합격선 (국수탐 백분위 평균, 70%컷)</h3><div id="cuts" class="chart"></div>
   <p class="note"><span style="color:var(--s1)">■</span> 의대 &nbsp;<span style="color:var(--s2)">■</span> 반도체 계약학과 &nbsp;<span style="color:var(--s3)">■</span> 서울대 자연계 · 출처: 종로학원 분석(어디가 공개 자료)</p></div>
 </div>
</section>

<section id="s3"><h2><span class="num">③</span>고교 선택 — 의대 지망 기준 비교</h2>
 <div class="card tbl"><table><thead><tr><th>유형</th><th>원서 시기</th><th>경쟁률</th><th>의대 적합도</th><th>내신</th><th>장점</th><th>유의점</th></tr></thead><tbody id="types"></tbody></table>
  <p class="note">의대 적합도(★5)는 의·약학 진학 제재, 5등급제 내신 확보 난도, 서울대 지역균형 지원 가능 여부를 종합한 정리입니다. 학생의 성향·성적에 따라 달라질 수 있습니다.</p></div>
 <div class="grid g3" style="margin-top:14px">
  <div class="card"><h3>영재학교 경쟁률 추이</h3><div id="gifted" class="chart" style="height:240px"></div>
   <table id="gifted-tbl"></table></div>
  <div class="card"><h3>서울 과학고</h3><table id="sci"></table><p class="note" id="sci-note"></p></div>
  <div class="card"><h3>자사고 경쟁률 (2026학년도)</h3><table id="jsg"></table>
   <p class="note">5등급제에서 내신 1등급(상위 10%) 확보가 어렵다는 인식으로 학군지 자사고 지원이 줄고, 대형 일반고·외고·국제고로 분산되는 흐름입니다.</p></div>
 </div>
</section>

<section id="s4"><h2><span class="num">④</span>대학 — 설카포 · 서성한</h2>
 <div class="card tbl"><table><thead><tr><th>대학</th><th>의대</th><th>입시 포인트</th><th>참고 합격선·실적</th></tr></thead><tbody id="univ"></tbody></table></div>
</section>

<section id="s5"><h2><span class="num">⑤</span>의대 지망 학생을 위한 조언 (서울 학군지·2028년 고1 입학 기준)</h2>
 <div class="grid g2" id="advice"></div>
 <div class="card" style="margin-top:14px"><h3>선택과목 로드맵 (2022 개정 교육과정 · 의예과 지망)</h3>
  <div class="tbl"><table><thead><tr><th>학년</th><th>영역</th><th>과목</th><th>왜</th></tr></thead><tbody id="subj"></tbody></table></div></div>
 <p class="note">이 조언은 공개 자료를 바탕으로 한 일반적 정리입니다. 고교 선택과 과목 편성은 목표 학교의 교육과정 편성표, 대학별 최신 요강, 학교 진학 상담으로 꼭 확인하세요.</p>
</section>

<section id="s6"><h2><span class="num">⑥</span>이번 주 교육 뉴스 (최근 7일 · 자동 수집)</h2><div class="grid g2" id="news"></div></section>

<footer><b>출처</b><ul class="tight" id="sources"></ul>
 기사 본문은 싣지 않고 제목과 원문 링크만 제공합니다. 수치는 보도 기준이며 최종 판단은 공식 요강을 확인하세요. · edu_insight.py</footer>
</div>
<script>
const D=__DATA__;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C={text:css('--text-primary'),sub:css('--text-secondary'),muted:css('--text-muted'),grid:css('--grid'),surf:css('--surface-1'),
 s1:css('--s1'),s2:css('--s2'),s3:css('--s3'),s4:css('--s4')};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cfg={displayModeBar:false,responsive:true};
const L=(x={})=>Object.assign({paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
 font:{family:getComputedStyle(document.body).fontFamily,color:C.sub,size:12},margin:{l:50,r:20,t:8,b:30},showlegend:false,
 hoverlabel:{bgcolor:C.surf,bordercolor:C.grid,font:{color:C.text}},xaxis:{gridcolor:'rgba(0,0,0,0)'},yaxis:{gridcolor:C.grid,zeroline:false}},x);
const tag={warn:'주의',info:'제도',good:'기회'};
document.getElementById('kp').innerHTML=D.key_points.map(([t,b,k])=>`<div class="kp ${k}"><b><span class="tag">${tag[k]}</span>${esc(t)}</b><p>${esc(b)}</p></div>`).join('');
document.getElementById('tl').innerHTML=D.timeline.map(([y,g,t])=>`<div><div class="y">${esc(y)}</div><div class="g">${esc(g)}</div>${esc(t)}</div>`).join('');

// 정원 (2단 누적: 기존 + 지역의사 증원)
const Q=D.quota;
Plotly.newPlot('quota',[
 {type:'bar',x:Q.x,y:Q.base,name:'기존 정원',marker:{color:C.s1,line:{color:C.surf,width:2}},hovertemplate:'기존 %{y:,}명<extra></extra>'},
 {type:'bar',x:Q.x,y:Q.regional,name:'지역의사 증원',marker:{color:C.s2,line:{color:C.surf,width:2}},
  text:Q.regional.map(v=>v?'+'+v:''),textposition:'outside',cliponaxis:false,textfont:{color:C.sub},hovertemplate:'지역의사 +%{y:,}명<extra></extra>'}],
 L({barmode:'stack',showlegend:true,legend:{orientation:'h',y:1.12,x:0},yaxis:{gridcolor:C.grid,range:[0,4300],tickformat:','}}),cfg);
document.getElementById('quota-note').textContent=D.quota_note;
const MT=D.med_table, yh='<tr><th></th>'+MT.years.map(y=>`<th>${y}</th>`).join('')+'</tr>';
const cell=(v,inc)=>`<td>${v.toLocaleString()}${inc?`<small>+${inc}</small>`:''}</td>`;
document.getElementById('quota-region').innerHTML=yh+MT.regions.map(r=>`<tr class="${r.sum?'sum':''}"><td>${esc(r.name)}</td>${r.vals.map((v,i)=>cell(v,r.inc[i])).join('')}</tr>`).join('');
let lastG='';document.getElementById('quota-univ').innerHTML=yh+MT.univs.map(u=>{const g=u.group!==lastG?`<tr class="grp"><td colspan="${MT.years.length+1}">${esc(u.group)}</td></tr>`:'';lastG=u.group;
 return g+`<tr><td>${esc(u.name)}</td>${u.vals.map((v,i)=>cell(v,u.inc[i])).join('')}</tr>`}).join('');
document.getElementById('quota-tbl-note').textContent=MT.note;

// 합격선
const cuts=[...D.cuts].sort((a,b)=>a[1]-b[1]);
const col={med:C.s1,semi:C.s2,eng:C.s3};
Plotly.newPlot('cuts',[{type:'bar',orientation:'h',y:cuts.map(c=>c[0]),x:cuts.map(c=>c[1]),marker:{color:cuts.map(c=>col[c[2]])},width:0.6,
 text:cuts.map(c=>c[1].toFixed(1)),textposition:'outside',cliponaxis:false,textfont:{color:C.sub,size:11},hovertemplate:'%{y}: %{x:.1f}<extra></extra>'}],
 L({margin:{l:150,r:36,t:8,b:30},xaxis:{range:[93,100],gridcolor:C.grid},yaxis:{gridcolor:'rgba(0,0,0,0)',automargin:true}}),cfg);

// 고교 유형
const star=n=>'★'.repeat(n)+'<span style="opacity:.25">'+'★'.repeat(5-n)+'</span>';
document.getElementById('types').innerHTML=D.school_types.map(s=>`<tr><td><b>${esc(s.type)}</b></td><td>${esc(s.when)}</td><td>${esc(s.rate)}</td>
 <td class="stars">${star(s.fit)}</td><td>${esc(s.naesin)}</td><td>${esc(s.pros)}</td><td>${esc(s.cons)}</td></tr>`).join('');
const G=D.gifted_rate;
Plotly.newPlot('gifted',[{type:'bar',x:G.x,y:G.y,marker:{color:C.s1},width:0.55,text:G.y.map(v=>v.toFixed(2)),textposition:'outside',
 cliponaxis:false,textfont:{color:C.sub},hovertemplate:'%{x}학년도 %{y:.2f}:1<extra></extra>'}],L({yaxis:{gridcolor:C.grid,range:[0,7]}}),cfg);
document.getElementById('gifted-tbl').innerHTML='<tr><th>영재학교 (2027 모집)</th><th>인원</th></tr>'+D.gifted.map(([n,c])=>`<tr><td>${esc(n)}</td><td>${c}명</td></tr>`).join('');
document.getElementById('sci').innerHTML=D.science_seoul.map(([n,t])=>`<tr><td><b>${esc(n)}</b></td><td>${esc(t)}</td></tr>`).join('');
document.getElementById('sci-note').textContent=D.science_note;
document.getElementById('jsg').innerHTML=D.jasago.map(([n,t])=>`<tr><td><b>${esc(n)}</b></td><td>${esc(t)}</td></tr>`).join('');

// 대학
document.getElementById('univ').innerHTML=D.univs.map(u=>`<tr><td><b>${esc(u.name)}</b><br><span class="pill">${esc(u.group)}</span></td>
 <td>${esc(u.med)}</td><td>${esc(u.points)}</td><td>${esc(u.result)}</td></tr>`).join('');

// 조언
document.getElementById('advice').innerHTML=D.advice.map(([t,items])=>`<div class="card"><h3>${esc(t)}</h3><ul class="tight">${items.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></div>`).join('');
document.getElementById('subj').innerHTML=D.subjects.map(r=>`<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td><b>${esc(r[2])}</b></td><td>${esc(r[3])}</td></tr>`).join('');

// 뉴스
document.getElementById('news').innerHTML=Object.entries(D.news).map(([lab,items])=>`<div class="card"><h3>${esc(lab)} <span class="muted">${items.length}건</span></h3>
 ${items.length?`<ul class="news">${items.map(n=>`<li><a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a><span class="src">${esc(n.source)} ${esc(n.date)}</span></li>`).join('')}</ul>`:'<p class="muted">이번 주 기사가 없습니다.</p>'}</div>`).join('');
document.getElementById('sources').innerHTML=D.sources.map(([t,u])=>`<li><a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a></li>`).join('');
</script></body></html>
"""


def med_table() -> dict:
    """대학별 정원(edu_data.MED_SCHOOLS)에서 2026~2031 권역·주요 대학 표를 만든다."""
    years = E.QUOTA["x"]

    def series(base, i27, i28):
        inc = [0 if y == "2026" else (i27 if y == "2027" else i28) for y in years]
        return [base + i for i in inc], inc

    regions = []
    for key, label in (("서울", "서울권"), ("경인", "경인권"), ("지방", "지방권")):
        rows = [v for v in E.MED_SCHOOLS.values() if v[0] == key]
        vals, inc = series(sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows))
        regions.append({"name": f"{label} ({len(rows)}개교)", "vals": vals, "inc": inc})
    new = [E.NEW_MED_2030 if int(y) >= 2030 else 0 for y in years]
    regions.append({"name": "공공·신설 의대", "vals": new, "inc": [0] * len(years)})
    tot = [sum(r["vals"][i] for r in regions) for i in range(len(years))]
    regions.append({"name": "전국 합계", "vals": tot, "inc": [t - tot[0] for t in tot], "sum": True})

    grp = {"서울": "서울권", "경인": "경인권", "지방": "지방권"}
    univs = []
    for n in sorted(E.MED_FEATURED, key=lambda n: ["서울", "경인", "지방"].index(E.MED_SCHOOLS[n][0])):
        reg, b, i27, i28 = E.MED_SCHOOLS[n]
        vals, inc = series(b, i27, i28)
        univs.append({"name": n, "group": grp[reg], "vals": vals, "inc": inc})
    return {"years": years, "regions": regions, "univs": univs, "note": E.MED_TABLE_NOTE}


def build_data(news: dict, now: dt.datetime) -> dict:
    return {
        "generated": now.strftime("%Y-%m-%d %H:%M KST"), "today": now.strftime("%Y-%m-%d"), "updated": E.UPDATED,
        "key_points": E.KEY_POINTS, "timeline": E.TIMELINE, "quota": E.QUOTA, "quota_note": E.QUOTA_NOTE, "med_table": med_table(),
        "cuts": E.CUTS, "school_types": E.SCHOOL_TYPES, "gifted": E.GIFTED, "gifted_rate": E.GIFTED_RATE,
        "science_seoul": E.SCIENCE_SEOUL, "science_note": E.SCIENCE_NOTE, "jasago": E.JASAGO_NOTE,
        "univs": E.UNIVS, "advice": E.ADVICE, "subjects": E.SUBJECTS, "sources": E.SOURCES, "news": news,
    }


def render_html(d: dict, demo: bool) -> str:
    banner = ('<div style="background:#fff4d6;color:#5a4300;border:1px solid #f0d27a;padding:10px 14px;border-radius:10px;'
              'margin:14px 0;font-size:14px"><b>데모 모드</b> — 뉴스는 가상 데이터입니다.</div>') if demo else ""
    return (HTML.replace("__DATA__", json.dumps(d, ensure_ascii=False).replace("</", "<\\/")).replace("__DEMO__", banner)
            .replace("__DATE__", d["today"]).replace("__GENERATED__", html.escape(d["generated"]))
            .replace("__UPDATED__", d["updated"]))


# ---------------------------------------------------------------- PDF
def render_pdf(d: dict, path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.backends.backend_pdf import PdfPages

    have = {f.name for f in font_manager.fontManager.ttflist}
    for nm in ("Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic", "Noto Sans CJK KR", "NanumGothic"):
        if nm in have:
            plt.rcParams["font.family"] = nm
            break
    plt.rcParams.update({"axes.unicode_minus": False, "font.size": 8.5, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.edgecolor": "#e6e5e0"})
    TEXT, SUB, MUTED, S1, S2, S3 = "#0b0b0b", "#52514e", "#85847f", "#2a78d6", "#eb6834", "#1baf7a"
    KC = {"warn": S2, "info": S1, "good": S3}

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
            s.pdf, s.fig, s.y = pdf, plt.figure(figsize=(8.27, 11.69)), 0.905
            s.fig.text(0.06, 0.965, title, fontsize=15, fontweight="bold", color=TEXT, va="top")
            s.fig.text(0.06, 0.94, f"생성 {d['generated']} · 정리 기준일 {d['updated']} · 수치는 보도 기준, 공식 요강으로 확인",
                       fontsize=7.5, color=SUB, va="top")
            s.fig.text(0.94, 0.02, str(pno), fontsize=7, color=MUTED, ha="right")
            s.fig.text(0.06, 0.02, "daily_edu-insight · 일반 정보 정리이며 개별 진학 상담을 대신하지 않습니다", fontsize=6.5, color=MUTED)

        def t(s, txt, size=8.5, color=TEXT, bold=False, ind=0.0, lh=0.0155, w=104, url=None):
            for k, part in enumerate(wrap(txt, w)):
                o = s.fig.text(0.06 + ind, s.y, part, fontsize=size, color=color, va="top", fontweight="bold" if bold else "normal")
                if url:
                    o.set_url(url)
                s.y -= lh

        def close(s):
            s.pdf.savefig(s.fig); plt.close(s.fig)

    with PdfPages(path) as pdf:
        pno = 1
        pg = Page(pdf, f"교육·입시 인사이트 · {d['today']}", pno)
        pg.t("① 핵심 요약 — 2031학년도 대입 학생 기준", 10.5, bold=True)
        for title, body, k in d["key_points"]:
            pg.t("■ " + title, 9, KC[k], bold=True)
            pg.t(body, 8, SUB, ind=0.02, lh=0.0145, w=100)
            pg.y -= 0.004
        pg.y -= 0.006
        pg.t("학생 타임라인", 10, bold=True)
        for y, g, txt in d["timeline"]:
            pg.t(f"{y} ({g})  {txt}", 8.2, ind=0.01, lh=0.0148)
        pg.y -= 0.01
        h = 0.2
        ax = pg.fig.add_axes([0.08, pg.y - h, 0.38, h - 0.03])
        Q = d["quota"]
        ax.bar(Q["x"], Q["base"], color=S1, label="기존 정원", edgecolor="white", linewidth=1.5)
        ax.bar(Q["x"], Q["regional"], bottom=Q["base"], color=S2, label="지역의사 증원", edgecolor="white", linewidth=1.5)
        for x, b, r in zip(Q["x"], Q["base"], Q["regional"]):
            if r:
                ax.text(x, b + r + 40, f"+{r}", ha="center", fontsize=7, color=SUB)
        ax.set_ylim(0, 4300); ax.set_title("의대 정원 계획(명)", loc="left", fontsize=9)
        ax.legend(fontsize=6.5, frameon=False, loc="upper left", ncol=2); ax.tick_params(labelsize=7)
        ax2 = pg.fig.add_axes([0.66, pg.y - h, 0.29, h - 0.03])
        cuts = sorted(d["cuts"], key=lambda c: c[1])
        ax2.barh([c[0] for c in cuts], [c[1] for c in cuts], color=[{"med": S1, "semi": S2, "eng": S3}[c[2]] for c in cuts], height=0.6)
        ax2.set_xlim(93, 100); ax2.set_title("2026 정시 70%컷(백분위)", loc="left", fontsize=9); ax2.tick_params(labelsize=6.5)
        pg.close()

        pno += 1
        pg = Page(pdf, "② 의대 정원 — 권역·주요 대학 (2026~2031학년도)", pno)
        MT = d["med_table"]
        cols = [0.27 + i * 0.115 for i in range(len(MT["years"]))]

        def row(name, vals, inc, bold=False, color=TEXT):
            pg.fig.text(0.06, pg.y, name, fontsize=8.2, color=color, weight="bold" if bold else "normal", va="top")
            for x, v, i in zip(cols, vals, inc):
                pg.fig.text(x + 0.07, pg.y, f"{v:,}" + (f" (+{i})" if i else ""), fontsize=8.2, color=color,
                            weight="bold" if bold else "normal", va="top", ha="right")
            pg.y -= 0.019

        for title, rows in (("권역별 의대 정원(명)", MT["regions"]), ("주요 대학 의대 정원(명)", MT["univs"])):
            pg.t(title, 10, bold=True)
            for x, y in zip(cols, MT["years"]):
                pg.fig.text(x + 0.07, pg.y, y, fontsize=8, color=SUB, va="top", ha="right", weight="bold")
            pg.y -= 0.019
            last = ""
            for r in rows:
                if r.get("group") and r["group"] != last:
                    pg.t(r["group"], 7.8, MUTED, bold=True); last = r["group"]
                row(r["name"], r["vals"], r["inc"], bold=r.get("sum", False))
            pg.y -= 0.012
        pg.t(MT["note"], 7.6, SUB, lh=0.0138, w=110)
        pg.close()

        pno += 1
        pg = Page(pdf, "③ 고교 선택 · ④ 대학", pno)
        pg.t("고교 유형 비교 (의대 지망 기준, 적합도 ★5)", 10.5, bold=True)
        for s in d["school_types"]:
            pg.t(f"{s['type']}  {'★' * s['fit']}{'☆' * (5 - s['fit'])}  · {s['when']} · {s['rate']}", 8.8, bold=True)
            pg.t("장점: " + s["pros"], 7.8, SUB, ind=0.02, lh=0.014, w=102)
            pg.t("유의: " + s["cons"], 7.8, SUB, ind=0.02, lh=0.014, w=102)
            pg.y -= 0.004
        pg.t("영재학교 2027 모집: " + ", ".join(f"{n} {c}" for n, c in d["gifted"]) + f" · 경쟁률 {d['gifted_rate']['y'][-1]}:1", 7.8, ind=0.0, w=110)
        pg.t("서울 과학고: " + " / ".join(f"{n} {t}" for n, t in d["science_seoul"]) + " · " + d["science_note"], 7.8, w=110)
        pg.t("자사고(2026): " + " / ".join(f"{n} {t}" for n, t in d["jasago"]), 7.8, w=110)
        pg.y -= 0.012
        pg.t("대학 — 설카포 · 서성한", 10.5, bold=True)
        for u in d["univs"]:
            pg.t(f"{u['name']} ({u['group']}) · {u['med']}", 8.8, bold=True)
            pg.t(u["points"], 7.8, SUB, ind=0.02, lh=0.014, w=102)
            pg.t(u["result"], 7.8, MUTED, ind=0.02, lh=0.014, w=102)
            pg.y -= 0.003
        pg.close()

        pno += 1
        pg = Page(pdf, "⑤ 의대 지망 학생 조언 · 선택과목", pno)
        for title, items in d["advice"]:
            pg.t("■ " + title, 9.5, S1, bold=True)
            for i in items:
                pg.t("• " + i, 8, SUB, ind=0.015, lh=0.0145, w=102)
            pg.y -= 0.006
        pg.t("선택과목 로드맵 (2022 개정, 의예 지망)", 9.5, S1, bold=True)
        for g, area, subj, why in d["subjects"]:
            pg.t(f"{g} · {area}: {subj}", 8.3, bold=True, ind=0.01)
            pg.t(why, 7.6, MUTED, ind=0.03, lh=0.0138, w=100)
        pg.close()

        pno += 1
        pg = Page(pdf, "⑥ 이번 주 교육 뉴스 (최근 7일)", pno)
        for lab, items in d["news"].items():
            if pg.y < 0.12:
                pg.close(); pno += 1; pg = Page(pdf, "⑥ 이번 주 교육 뉴스 (계속)", pno)
            pg.t(f"■ {lab}", 9.5, S1, bold=True)
            for n in items[:6] or [{"title": "이번 주 기사 없음", "link": "", "source": "", "date": ""}]:
                pg.t(f"· {n['title']}  ({n['source']} {n['date']})", 8, ind=0.01, lh=0.0145, w=104, url=n["link"] or None)
            pg.y -= 0.006
        pg.y -= 0.01
        pg.t("출처", 9, bold=True)
        for t, u in d["sources"]:
            if pg.y < 0.05:
                break
            pg.t("· " + t, 7.2, SUB, lh=0.0125, url=u)
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
    ap = argparse.ArgumentParser(description="교육·입시 인사이트 대시보드")
    ap.add_argument("--outdir", default="_site/daily_edu-insight")
    ap.add_argument("--keep-days", type=int, default=365)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args(argv)

    now = dt.datetime.now(KST)
    out = Path(os.path.expanduser(a.outdir))
    (out / "archive").mkdir(parents=True, exist_ok=True)
    news = demo_news() if a.demo else {lab: fetch_news(lab, q) for lab, q in E.NEWS_QUERIES}
    d = build_data(news, now)
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
