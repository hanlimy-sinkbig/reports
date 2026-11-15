#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 뉴스 종합 대시보드 (daily_ai-news)
=====================================

매일 아침 국내외 AI 뉴스·공식 블로그·커뮤니티 피드(RSS)를 모아 하나의 대시보드(HTML)와 PDF로 만듭니다.

  ① 오늘의 핵심       여러 매체가 함께 다룬 이야기 순(화제 묶음) + (선택) AI 요약
  ② 숫자로 보는 오늘   기업·모델 언급 수, 분야별 기사 수, 최근 7일 언급 추이
  ③ 분야별 뉴스        모델·제품 / 연구 / 정책·규제 / 투자·산업 / 국내 / 기타
  ④ 공식 발표          OpenAI·Google DeepMind·Google AI·NVIDIA·Hugging Face 블로그 최근 글

사용법
------
  pip install -r requirements.txt
  python ai_news.py --outdir _site/daily_ai-news           # GitHub Pages 구조로 생성
  python ai_news.py --demo --outdir out                    # 인터넷 없이 가상 데이터로 레이아웃 확인

선택: 환경변수 ANTHROPIC_API_KEY 가 있으면 '오늘의 AI 브리핑' 요약 5줄을 추가합니다(없어도 동작).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

KST = dt.timezone(dt.timedelta(hours=9))
WEEKDAY = "월화수목금토일"
UA = {"User-Agent": "Mozilla/5.0 (daily_ai-news; +https://github.com)"}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(KST):%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 1. 피드 설정
# ---------------------------------------------------------------------------
def gnews(q: str, lang: str) -> str:
    q = urllib.parse.quote(f"{q} when:1d")
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


# (표시 이름, URL, 언어, 종류: news / official / community, 최대 기사 수)
FEEDS = [
    ("Google News · AI", gnews('"artificial intelligence" OR OpenAI OR Anthropic OR Gemini OR LLM', "en"), "en", "news", 40),
    ("Google News · AI 기업", gnews("OpenAI OR Anthropic OR DeepMind OR Nvidia AI OR Meta AI OR xAI", "en"), "en", "news", 30),
    ("Google News · 인공지능", gnews("인공지능 OR 생성형AI OR LLM OR 챗GPT", "ko"), "ko", "news", 40),
    ("AI타임스", "https://www.aitimes.com/rss/allArticle.xml", "ko", "news", 25),
    ("OpenAI", "https://openai.com/news/rss.xml", "en", "official", 10),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "en", "official", 10),
    ("Google AI", "https://blog.google/technology/ai/rss/", "en", "official", 10),
    ("NVIDIA", "https://blogs.nvidia.com/feed/", "en", "official", 10),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", "en", "official", 10),
    ("Hacker News", "https://hnrss.org/newest?q=AI+OR+LLM+OR+OpenAI+OR+Anthropic+OR+GPT&points=100", "en", "community", 20),
]
NEWS_WINDOW_H = 36       # 뉴스·커뮤니티: 최근 36시간
OFFICIAL_WINDOW_D = 7    # 공식 블로그: 최근 7일

CATEGORIES = [  # (이름, 키워드) — 위에서부터 먼저 맞는 것으로 분류
    ("국내", ["네이버", "카카오", "삼성", "lg ", "엘지", "sk텔레콤", "skt", "kt ", "업스테이지", "하이퍼클로바",
              "엑사원", "과기정통부", "과기부", "국내", "한국형", "k-ai", "korea", "korean", "리벨리온", "퓨리오사"]),
    ("정책·규제", ["regulat", "law", "policy", "act ", "senate", "congress", "government", "eu ", "lawsuit", "court",
                "copyright", "ban", "규제", "법안", "법 ", "정부", "정책", "소송", "저작권", "가이드라인", "기본법"]),
    ("투자·산업", ["funding", "raises", "valuation", "acquir", "ipo", "revenue", "deal", "invest", "data center",
                "datacenter", "chip", "gpu", "stock", "shares", "billion", "투자", "인수", "매출", "상장", "반도체",
                "데이터센터", "칩", "주가", "조원", "억 달러", "억달러"]),
    ("연구", ["research", "paper", "benchmark", "study", "arxiv", "researchers", "scientists", "breakthrough",
            "논문", "연구", "벤치마크", "학회"]),
    ("모델·제품", ["launch", "release", "unveil", "introduc", "model", "gpt", "claude", "gemini", "llama", "agent",
               "app", "feature", "update", "출시", "공개", "발표", "모델", "에이전트", "서비스", "업데이트", "기능"]),
]
CAT_ORDER = [c for c, _ in CATEGORIES] + ["기타"]
CAT_DISPLAY = ["모델·제품", "연구", "정책·규제", "투자·산업", "국내", "기타"]

ENTITIES = {  # 표시 이름: [패턴(영문은 단어 경계)]
    "OpenAI": ["openai", "chatgpt", "gpt-", "gpt5", "sora", "오픈ai", "오픈AI", "챗gpt", "챗GPT"],
    "Anthropic": ["anthropic", "claude", "앤트로픽", "클로드"],
    "Google": ["google", "gemini", "deepmind", "구글", "제미나이", "딥마인드"],
    "Meta": ["meta", "llama", "메타", "라마4", "라마 4"],
    "Microsoft": ["microsoft", "copilot", "마이크로소프트", "MS "],
    "NVIDIA": ["nvidia", "엔비디아"],
    "Apple": ["apple", "애플"],
    "Amazon": ["amazon", "aws", "아마존"],
    "xAI": ["xai", "grok", "그록"],
    "DeepSeek": ["deepseek", "딥시크"],
    "Mistral": ["mistral", "미스트랄"],
    "네이버": ["naver", "네이버", "하이퍼클로바"],
    "카카오": ["kakao", "카카오"],
    "삼성": ["samsung", "삼성"],
    "LG": ["lg ai", "exaone", "엑사원", "lg"],
    "SK": ["sk hynix", "sk텔레콤", "skt", "sk하이닉스", "에스케이"],
}
_ENTITY_RE = {}
for _name, _pats in ENTITIES.items():
    parts = []
    for p in _pats:
        if re.fullmatch(r"[A-Za-z0-9\- ]+", p):
            parts.append(r"(?<![A-Za-z])" + re.escape(p.strip()) + r"(?![A-Za-z])")
        else:
            parts.append(re.escape(p))
    _ENTITY_RE[_name] = re.compile("|".join(parts), re.I)


# ---------------------------------------------------------------------------
# 2. 수집
# ---------------------------------------------------------------------------
def _text(el, *names):
    for n in names:
        for child in el:
            tag = child.tag.split("}")[-1]
            if tag == n:
                if n == "link" and child.get("href"):
                    return child.get("href")
                return (child.text or "").strip()
    return ""


def _parse_date(s: str):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(KST)


def _clean(s: str, n: int = 260) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n] + ("…" if len(s) > n else "")


def fetch_feed(feed) -> list[dict]:
    name, url, lang, kind, limit = feed
    if requests is None:
        return []
    try:
        r = requests.get(url, timeout=20, headers=UA)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log(f"피드 실패 · {name}: {str(e)[:120]}")
        return []
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = _clean(_text(it, "title"), 220)
        link = _text(it, "link") or _text(it, "guid")
        pub = _parse_date(_text(it, "pubDate", "published", "updated", "date"))
        source = _text(it, "source") or name
        if kind == "news" and source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        summary = _clean(_text(it, "description", "summary", "content"))
        if summary.startswith(title[:30]):  # Google News 는 설명=제목+링크
            summary = ""
        if title and link:
            items.append({"title": title, "link": link, "source": source if kind == "news" else name,
                          "feed": name, "lang": lang, "kind": kind, "summary": summary,
                          "published": pub.isoformat() if pub else None})
        if len(items) >= limit:
            break
    log(f"피드 · {name}: {len(items)}건")
    return items


def collect(now: dt.datetime) -> tuple[list[dict], dict]:
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_feed, FEEDS))
    status = {f[0]: len(r) for f, r in zip(FEEDS, results)}
    items = [i for r in results for i in r]
    out = []
    for i in items:
        p = dt.datetime.fromisoformat(i["published"]) if i["published"] else None
        win = dt.timedelta(days=OFFICIAL_WINDOW_D) if i["kind"] == "official" else dt.timedelta(hours=NEWS_WINDOW_H)
        if p is None or now - p <= win:
            out.append(i)
    return out, status


# ---------------------------------------------------------------------------
# 3. 분석
# ---------------------------------------------------------------------------
_STOP = set("the a an of to in on for and with at by from as is are be its it this that new how why what "
            "after over into about says said will can than more ai 의 및 등 위해 대한 통해 있다 했다 한다".split())


def tokens(title: str) -> set[str]:
    t = re.findall(r"[a-z0-9][a-z0-9\-\.]+|[가-힣]{2,}", title.lower())
    return {w for w in t if w not in _STOP and len(w) > 1}


def categorize(it: dict) -> str:
    text = " " + (it["title"] + " " + it["summary"]).lower() + " "
    for name, kws in CATEGORIES:
        if name == "국내" and it["lang"] != "ko" and not any(k in text for k in ("korea", "korean", "naver", "kakao", "samsung")):
            continue
        if any(k in text for k in kws):
            return name
    return "기타"


def entities_of(it: dict) -> list[str]:
    text = it["title"] + " " + it["summary"]
    return [n for n, rx in _ENTITY_RE.items() if rx.search(text)]


def key_of(it: dict) -> str:
    return hashlib.sha1(re.sub(r"\W", "", it["title"].lower())[:80].encode()).hexdigest()[:12]


def cluster(items: list[dict]) -> list[dict]:
    """제목 단어 겹침으로 같은 이야기 묶기 → 매체 수가 많은 순"""
    clusters: list[dict] = []
    for it in sorted(items, key=lambda x: x["published"] or "", reverse=True):
        tk, ents = tokens(it["title"]), set(it["entities"])
        best, best_s = None, 0.0
        for c in clusters:
            inter = len(tk & c["tokens"])
            s = inter / max(1, min(len(tk), len(c["tokens"])))
            # 단어 3개 이상 겹치거나, 같은 기업을 다루면서 핵심 단어 2개 이상 겹치면 같은 이야기
            ok = (inter >= 3 and s >= 0.4) or (inter >= 2 and s >= 0.28 and ents & c["ents"])
            if ok and s > best_s:
                best, best_s = c, s
        if best is not None:
            best["items"].append(it)
            best["tokens"] |= tk
            best["ents"] |= ents
        else:
            clusters.append({"tokens": set(tk), "ents": set(ents), "items": [it]})
    for c in clusters:
        srcs = {i["source"] for i in c["items"]}
        c["n_sources"] = len(srcs)
        lead = sorted(c["items"], key=lambda i: (i["kind"] != "official", i["lang"] != "ko", -len(i["title"])))[0]
        c["lead"] = lead
        c["category"] = lead["category"]
        c["entities"] = sorted({e for i in c["items"] for e in i["entities"]})
        c["latest"] = max((i["published"] or "") for i in c["items"])
        c["score"] = c["n_sources"] * 2 + len(c["items"]) + (2 if any(i["kind"] == "official" for i in c["items"]) else 0) \
            + (1 if any(i["kind"] == "community" for i in c["items"]) else 0)
        del c["tokens"], c["ents"]
    clusters.sort(key=lambda c: c["latest"], reverse=True)   # 동점이면 최신 순
    return sorted(clusters, key=lambda c: -c["score"])


def llm_brief(top: list[dict]) -> list[str] | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or requests is None or not top:
        return None
    heads = "\n".join(f"- [{c['category']}] {c['lead']['title']} ({c['n_sources']}개 매체)" for c in top[:20])
    prompt = ("아래는 지난 하루 AI 관련 뉴스 헤드라인입니다(매체 수가 많을수록 화제).\n" + heads +
              "\n\n헤드라인만 근거로 오늘 AI 업계에서 가장 중요한 흐름 5가지를 한국어로, 각각 한 문장(60자 이내)으로 "
              "'- '로 시작하는 목록으로 쓰세요. 헤드라인에 없는 사실은 추측하지 마세요.")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("BRIEF_LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": 600,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        lines = [re.sub(r"^\s*[-•]\s*", "", l).strip() for l in text.splitlines() if l.strip().startswith(("-", "•"))]
        return lines[:5] or None
    except Exception as e:
        log(f"AI 요약 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 3-2. 주간 흐름 (최근 7일 이야기를 날짜를 넘어 묶고, 오늘 뉴스와 연결)
# ---------------------------------------------------------------------------
WEEK_DAYS = 7
STORIES_KEEP_D = 14       # stories.json 보관 기간
STORIES_PER_DAY = 40      # 하루에 저장하는 이야기 수(점수 순)
FRESH_H = 24              # 직전 실행 이후(24시간 안) 기사가 있어야 '그날 다뤄졌다'고 봄 (수집 창 36시간 겹침 보정)

# 한국어 제목을 영어 제목과 잇기 위한 간단한 대응표 (앞부분 일치)
KO_ALIAS = [("엔비디아", "nvidia"), ("젠슨", "huang"), ("오픈", "openai"), ("앤트로픽", "anthropic"), ("클로드", "claude"),
            ("구글", "google"), ("제미나이", "gemini"), ("딥마인드", "deepmind"), ("메타", "meta"), ("애플", "apple"),
            ("마이크로소프트", "microsoft"), ("아마존", "amazon"), ("딥시크", "deepseek"), ("월렛", "wallet"),
            ("상장", "ipo"), ("기업공개", "ipo"), ("소송", "lawsuit"), ("규제", "regulation"), ("에이전트", "agent"),
            ("반도체", "chip"), ("데이터센터", "datacenter"), ("삼성", "samsung"), ("네이버", "naver"), ("카카오", "kakao"),
            ("하이닉스", "hynix"), ("수출", "export"), ("중국", "china"), ("결제", "payment")]

# 사건 단어 사전: 기자마다 다르게 쓰는 '사건·파문' 표현을 하나의 표시어(EVENT)로 봄
#   → 'Nvidia scandal', 'Nvidia turmoil', 'Huang ousted', '엔비디아 사태'가 같은 사건 신호가 됨
#   새 표현이 보이면 여기에 추가하세요. (영어는 복수형 s 를 뗀 형태로 비교)
EVENT = "§사건"
EVENT_EN = set("scandal turmoil crisi crises fallout turbulence upheaval chaos ousted oust ouster ousting resign resigned "
               "resignation resigning exit exited departure step stepped boardroom shakeup shake-up affair affairs "
               "controversy saga exodu".split())
EVENT_KO = ("사태", "사임", "퇴임", "퇴진", "경질", "해임", "스캔들", "파문", "위기", "혼란", "논란", "내홍", "불륜", "후폭풍", "충격")
_KO_JOSA = ("에서", "으로", "은", "는", "이", "가", "을", "를", "의", "에", "도", "로", "과", "와")
_FLOW_STOP = set("stock market today news week report could would should here what's s just now".split())


def _norm(w: str) -> str | None:
    w = w.strip(".-")
    if w in EVENT_EN or (len(w) > 4 and w[:-1] in EVENT_EN) or w.startswith(EVENT_KO):
        return EVENT
    if re.fullmatch(r"[\d\.\-$]+", w) or w in _FLOW_STOP:
        return None
    if re.match(r"[a-z]", w):
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        return w
    for k, v in KO_ALIAS:
        if w.startswith(k):
            return v
    for j in _KO_JOSA:
        if len(w) >= len(j) + 2 and w.endswith(j):
            return w[: -len(j)]
    return w


def flow_tokens(st: dict, title_only: bool = False) -> set[str]:
    out = set()
    for t in [st["title"]] + ([] if title_only else st.get("alt", [])):
        for w in tokens(t):
            n = _norm(w)
            if n:
                out.add(n)
    return out


def story_record(c: dict, run_at: dt.datetime) -> dict:
    """하루치 묶음(cluster) → 날짜를 넘어 비교할 이야기 기록"""
    items = c["items"]
    fresh_cut = (run_at - dt.timedelta(hours=FRESH_H)).isoformat()
    lead = c["lead"]
    others = [i for i in items if i["link"] != lead["link"]]
    return {"title": lead["title"], "link": lead["link"], "source": lead["source"], "category": c["category"],
            "entities": c["entities"], "n_sources": c["n_sources"], "score": c["score"],
            "sources": sorted({i["source"] for i in items}),
            "fresh": sum(1 for i in items if (i.get("published") or "9") >= fresh_cut),
            "alt": [i["title"] for i in others[:4]],
            "links": [{"title": i["title"], "source": i["source"], "link": i["link"]} for i in [lead] + others[:2]]}


def bootstrap_stories(out: Path, stories: dict, now: dt.datetime) -> dict:
    """stories.json 에 없는 지난 날짜는 archive/*.html 안의 데이터(const D)로 채움 → 첫 실행부터 주간 분석 가능"""
    for k in range(1, WEEK_DAYS):
        d = (now - dt.timedelta(days=k)).strftime("%Y-%m-%d")
        if d in stories:
            continue
        for p in sorted((out / "archive").glob(f"{d}_*.html")):
            if "_demo" in p.name:
                continue
            try:
                m = re.search(r"const D = (\{.*?\});\nconst css", p.read_text(encoding="utf-8"), re.S)
                D = json.loads(m.group(1).replace("<\\/", "</"))
                run_at = dt.datetime.strptime(D["generated"][:16], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
                cl = [c for cs in D["by_cat"].values() for c in cs]
                cl.sort(key=lambda c: -c["score"])
                stories[d] = [story_record(c, run_at) for c in cl[:STORIES_PER_DAY]]
                log(f"주간 기록 보충 · {d} ({len(stories[d])}개, {p.name})")
            except Exception as e:
                log(f"주간 기록 보충 실패 · {p.name}: {e}")
            break
    return stories


_GENERIC = set("인공지능 생성형 기업 세계 지원 활용 업무 영향 개발 수행 수준 공개 출시 모델 미국 기술 서비스 시장 전망 국내 글로벌 "
               "도입 강화 최초 발표 기반 국가 산업 시대 정부 ceo model test you my us other know face ahead buy price firm "
               "risk investor launche launch top big first year next one two may artificial intelligence agent ai-agent 에이전트 "
               "chatbot 챗봇 startup tech company llm genai 확대 추진 계약 체결 협력 선보 선보여 출범 돌입 가속 본격 나서 "
               "추천 연결 서비스 플랫폼 솔루션 데이터 디지털 전환 상용화 계획".split())
_CANON = {"gpt": "openai", "chatgpt": "openai", "claude": "anthropic", "gemini": "google", "deepmind": "google",
          "alphabet": "google", "llama": "meta", "copilot": "microsoft", "aws": "amazon", "grok": "xai"}  # 제품명 → 회사명
_WEAK = {EVENT}   # 혼자서는 열쇠가 못 되는 단어(기업명 + 사건 표시어)
_ENT_TOK = {"openai": "OpenAI", "gpt": "OpenAI", "chatgpt": "OpenAI", "anthropic": "Anthropic", "claude": "Anthropic",
            "google": "Google", "gemini": "Google", "deepmind": "Google", "alphabet": "Google", "meta": "Meta",
            "llama": "Meta", "microsoft": "Microsoft", "copilot": "Microsoft", "nvidia": "NVIDIA", "apple": "Apple",
            "amazon": "Amazon", "aws": "Amazon", "xai": "xAI", "grok": "xAI", "deepseek": "DeepSeek",
            "samsung": "삼성", "naver": "네이버", "kakao": "카카오"}


def _themes(pool: list[dict]) -> list[list[dict]]:
    """1단계: 여러 이야기에 함께 나오는 '핵심어 쌍'(예: nvidia+huang, anthropic+ipo)으로 큰 사건 묶기"""
    import math
    from itertools import combinations
    N = len(pool)
    df: dict[str, int] = {}
    for st in pool:
        st["ct"] = {w for w in st["tk"] if w not in _GENERIC}                       # 제목+같은 이야기 다른 제목
        st["tt"] = {_CANON.get(w, w) for w in flow_tokens(st, title_only=True) if w not in _GENERIC}  # 대표 제목만
        for w in st["ct"]:
            df[w] = df.get(w, 0) + 1
    left = list(range(N))
    groups = []
    while True:
        sup: dict[tuple, list[int]] = {}
        for i in left:
            ws = sorted(w for w in pool[i]["tt"] if df.get(w, 0) >= 3)
            for a, b in combinations(ws, 2):
                if a in _ENT_TOK and b in _ENT_TOK:          # 기업끼리 쌍(OpenAI+Google 등)은 사건이 아님
                    continue
                if (a in _WEAK and b not in _ENT_TOK) or (b in _WEAK and a not in _ENT_TOK):
                    continue                                 # 사건 표시어는 기업명과 짝일 때만 (예: nvidia+§사건)
                if _ENT_TOK.get(a, a) == _ENT_TOK.get(b, b):
                    continue
                sup.setdefault((a, b), []).append(i)
        best, best_v = None, 0.0
        for pr, idx in sup.items():
            if len(idx) < 3 or len({pool[i]["source"] for i in idx}) < 2:
                continue
            lift = len(idx) * N / (df[pr[0]] * df[pr[1]])
            if lift < 1.5:
                continue
            v = len(idx) * math.log(lift) + sum(pool[i]["n_sources"] for i in idx) * 0.1
            if v > best_v:
                best, best_v = pr, v
        if best is None:
            break
        members = set(sup[best])
        # 사건에 집중된 단어(이 묶음에 75% 이상 몰린 단어)를 가진 이야기도 합류 (예: '젠슨 황' 한국어 기사)
        cnt: dict[str, int] = {}
        for i in members:
            for w in pool[i]["ct"]:
                cnt[w] = cnt.get(w, 0) + 1
        core = {w for w, n in cnt.items() if n >= 3 and n / df[w] >= 0.6 and w not in _ENT_TOK and w not in _WEAK}
        weak = set(_ENT_TOK) | _WEAK
        strong_best = set(best) - weak
        th_ents = {_ENT_TOK[w] for w in best if w in _ENT_TOK}
        for i in left:
            tt = pool[i]["tt"]
            if i in members:
                continue
            st_ents = {_ENT_TOK[w] for w in tt if w in _ENT_TOK}
            if th_ents and st_ents and not (th_ents & st_ents):   # 다른 기업 이야기(예: 구글 월렛)는 제외
                continue
            if tt & (strong_best | core):     # 사건 고유 단어(huang·wallet 등)가 있으면 합류
                n_hit = len(tt & (core | set(best)))
                if th_ents and not st_ents and n_hit < 2:   # 기업명 없는 기사는 단어 2개 이상 맞아야 (예: '中 상장 증권사' 제외)
                    continue
                if n_hit >= 2 or tt & strong_best:
                    members.add(i)
            elif not strong_best and set(best) <= tt:   # 쌍이 '기업+사건 표시어'면 둘 다 있어야 합류
                members.add(i)
        groups.append(([pool[i] for i in sorted(members)], list(best) + sorted(core - set(best), key=lambda w: -cnt.get(w, 0))[:2]))
        left = [i for i in left if i not in members]
    groups = _merge_themes(groups)
    # 3단계: 합쳐진 흐름의 대표 단어(구성 기사의 30% 이상)로 남은 기사 한 번 더 흡수
    #   예: 'nvidia' 없이 '젠슨 황 퇴임'만 쓴 한국어 기사 → huang + 사건 표시어로 합류
    for gi, (ms, kw) in enumerate(groups):
        cnt: dict[str, int] = {}
        for m in ms:
            for w in m["tt"]:
                cnt[w] = cnt.get(w, 0) + 1
        sig = {w for w, n in cnt.items() if n >= 3 and n / len(ms) >= 0.3}
        sig_strong = sig - set(_ENT_TOK) - _WEAK
        sig_ents = {_ENT_TOK[w] for w in sig if w in _ENT_TOK}
        take = []
        for i in left:
            tt = pool[i]["tt"]
            st_ents = {_ENT_TOK[w] for w in tt if w in _ENT_TOK}
            if sig_ents and st_ents and not (sig_ents & st_ents):
                continue
            if tt & sig_strong and len(tt & sig) >= 2:
                take.append(i)
        if take:
            groups[gi] = (ms + [pool[i] for i in take], kw)
            left = [i for i in left if i not in take]
    return groups, [pool[i] for i in left]


def _merge_themes(groups):
    """2단계: 같은 기업 + 같은 사건 신호를 공유하는 흐름 합치기
    (예: 'huang+nvidia' 흐름과 'nvidia+§사건' 흐름 → 하나). 기업만 같은 별개 발표는 합치지 않음."""
    def sig(ms):
        cnt = {}
        for m in ms:
            for w in m["tt"]:
                cnt[w] = cnt.get(w, 0) + 1
        return {w for w, n in cnt.items() if n / len(ms) >= 0.3}, cnt

    merged = True
    while merged:
        merged = False
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                (ma, ka), (mb, kb) = groups[a], groups[b]
                sa, ca = sig(ma)
                sb, cb = sig(mb)
                ents = {_ENT_TOK[w] for w in sa & sb if w in _ENT_TOK}
                shared = (sa & sb) - set(_ENT_TOK)
                da, db = {m["date"] for m in ma}, {m["date"] for m in mb}
                # 사건 표시어·사건 고유 단어를 함께 쓰고, 기간이 겹치면 같은 사건
                if ents and shared and da & db:
                    # 각 흐름의 사건 단어를 상대 흐름도 실제로 쓰는지(25% 이상) 확인
                    ok_b = any(cb.get(w, 0) / len(mb) >= 0.25 for w in set(ka) - set(_ENT_TOK))
                    ok_a = any(ca.get(w, 0) / len(ma) >= 0.25 for w in set(kb) - set(_ENT_TOK))
                    if ok_a or ok_b:
                        groups[a] = (ma + mb, ka + [w for w in kb if w not in ka])
                        del groups[b]
                        merged = True
                        break
            if merged:
                break
    return groups


def llm_groups(pool: list[dict]) -> list[tuple[list[int], str]] | None:
    """AI에게 '같은 사건'끼리 묶게 함 (단어가 달라도 뜻으로 묶음). 실패하면 None → 규칙 방식으로 대체"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or requests is None or len(pool) < 2:
        return None
    lines = "\n".join(f"{i}|{st['date'][5:]}|{st['title'][:140]}" + (f" / {st['alt'][0][:80]}" if st.get("alt") else "")
                      for i, st in enumerate(pool))
    prompt = ("아래는 최근 며칠 AI 뉴스 기사 묶음 목록입니다. 형식: 번호|날짜|제목 (/ 뒤는 같은 묶음의 다른 제목).\n\n" + lines +
              "\n\n같은 사건·이슈를 다룬 것끼리 묶으세요. 규칙:\n"
              "- 표현이 달라도(예: scandal·turmoil·ousted·사임·사태) 같은 사건이면 한 묶음. 한국어·영어 기사도 같은 사건이면 함께.\n"
              "- 사건의 여파(주가·투자 흐름·정책 반응)도 그 사건이 중심이면 같은 묶음.\n"
              "- 같은 기업이라는 이유만으로 묶지 말 것(별개 발표·실적은 따로).\n"
              "- 두 사건을 함께 다룬 기사는 더 중심인 쪽 하나에만.\n"
              "- 2개 이상 모인 묶음만 쓰고, 혼자인 기사는 빼세요.\n"
              "- label 은 사건을 나타내는 짧은 한국어(25자 이내).\n"
              'JSON 배열만 출력: [{"label": "...", "ids": [번호, ...]}, ...]')
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("FLOW_LLM_MODEL", os.environ.get("BRIEF_LLM_MODEL", "claude-sonnet-5-5")),
                  "max_tokens": 6000, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        m = re.search(r"\[.*\]", text, re.S)
        raw = json.loads(m.group(0))
    except Exception as e:
        log(f"AI 사건 묶기 실패 → 규칙 방식 사용: {str(e)[:150]}")
        return None
    used, out = set(), []
    for g in raw if isinstance(raw, list) else []:
        ids = [int(i) for i in g.get("ids", []) if str(i).isdigit() and 0 <= int(i) < len(pool) and int(i) not in used]
        if len(ids) >= 2:
            used.update(ids)
            out.append((ids, str(g.get("label", "")).strip()[:40]))
    log(f"AI 사건 묶기 · {len(out)}개 묶음, {len(used)}/{len(pool)}개 기사")
    return out or None


def build_threads(stories: dict, days: list[str], use_llm: bool = False) -> list[dict]:
    """여러 날의 이야기를 '흐름'으로 묶기: ① 핵심어 쌍으로 큰 사건 ② 나머지는 제목 단어 겹침"""
    pool = []
    for d in days:
        for st in stories.get(d, []):
            pool.append(dict(st, date=d, tk=flow_tokens(st), ents=set(st["entities"])))
    if not pool:
        return []
    import math
    ai = llm_groups(pool) if use_llm else None
    if ai:
        for st in pool:   # 대표 제목 선정에 쓰는 단어
            st["tt"] = flow_tokens(st, title_only=True)
        used = {i for ids, _ in ai for i in ids}
        groups = [([pool[i] for i in sorted(ids)], [], label) for ids, label in ai]
        rest = [st for i, st in enumerate(pool) if i not in used]
        method = "ai"
    else:
        groups, rest = _themes(pool)
        groups = [(ms, kw, "") for ms, kw in groups]
        method = "rule"
    df: dict[str, int] = {}
    for st in rest:
        for w in st["tk"]:
            df[w] = df.get(w, 0) + 1
    N = len(rest) or 1
    idf = {w: math.log((N + 1) / (n + 0.5)) for w, n in df.items()}

    def sim(a, b):
        sh = a["tk"] & b["tk"]
        if len(sh) < 3:
            return 0.0
        s = sum(idf[x] for x in sh) / max(1e-9, min(sum(idf[x] for x in a["tk"]), sum(idf[x] for x in b["tk"])))
        return s if s >= 0.4 or (s >= 0.3 and a["ents"] & b["ents"]) else 0.0

    small: list[list[dict]] = []
    for st in sorted(rest, key=lambda s: (s["date"], -s["score"])):
        best, best_s = None, 0.0
        for g in small:
            sc = max(sim(st, m) for m in g)
            if sc > best_s:
                best, best_s = g, sc
        if best is not None:
            best.append(st)
        else:
            small.append([st])

    if ai:   # AI가 혼자라고 본 기사는 다시 묶지 않음
        small = [[st] for st in rest]
    threads = [{"members": ms, "keywords": kw, "label": lb, "method": method} for ms, kw, lb in groups] + \
              [{"members": ms, "keywords": [], "label": "", "method": method} for ms in small]
    for th in threads:
        ms = th["members"]
        per_day: dict[str, float] = {}
        for m in ms:
            if m["fresh"] > 0 or m["date"] == days[-1]:
                per_day[m["date"]] = per_day.get(m["date"], 0) + m["score"]
        kw = set(th["keywords"][:2])
        lead = max(ms, key=lambda m: (kw <= m.get("tt", m["tk"]), m["n_sources"], m["score"], m["date"]))
        srcs = {s for m in ms for s in m["sources"]}
        ranked = sorted(ms, key=lambda m: (m["date"], m["score"]), reverse=True)
        th.update({
            "title": lead["title"], "link": lead["link"], "category": lead["category"],
            "entities": sorted({e for m in ms for e in m["entities"]}),
            "days": sorted(per_day), "series": [round(per_day.get(d, 0)) for d in days],
            "n_sources": len(srcs), "n_stories": len(ms),
            "first": min(per_day) if per_day else ms[0]["date"], "last": max(per_day) if per_day else ms[-1]["date"],
            "peak": max(per_day.values()) if per_day else 0,
            "links": [dict(m["links"][0], date=m["date"]) for m in ranked if m["link"] != lead["link"]][:5],
            "keys": [m["date"] + "|" + m["link"] for m in ms],
        })
        # 임팩트 = 매체 폭 + 지속 일수 + 최고 화제도 (하루 반짝보다 여러 날 이어진 이야기를 우대)
        th["impact"] = round(th["n_sources"] * 2 + len(th["days"]) * 4 + th["peak"] * 0.5, 1)
        del th["members"]
    threads.sort(key=lambda t: -t["impact"])
    return threads


def relate(th: dict, days: list[str]) -> dict:
    """한 흐름의 오늘 상태: 새 흐름 / 확대 / 지속 / 축소 / 재부상 / 잠잠"""
    today, yday = days[-1], days[-2] if len(days) > 1 else None
    s = dict(zip(days, th["series"]))
    prev = [s[d] for d in th["days"] if d != today]
    if today not in th["days"]:
        return {"status": "잠잠", "note": f"{th['last'][5:].replace('-', '/')} 이후 소식 없음"}
    if not prev:
        return {"status": "새 흐름", "note": "오늘 처음 등장"}
    n = len(th["days"])
    if yday not in th["days"]:
        return {"status": "재부상", "note": f"{th['days'][-2][5:].replace('-', '/')} 이후 다시 등장 · {n}일째"}
    avg = sum(prev) / len(prev)
    r = s[today] / max(1, avg)
    if r >= 1.3:
        return {"status": "확대", "note": f"{n}일째 · 화제도 {s[today]} (이전 평균 {avg:.0f})"}
    if r <= 0.7:
        return {"status": "축소", "note": f"{n}일째 · 화제도 {s[today]} (이전 평균 {avg:.0f})"}
    return {"status": "지속", "note": f"{n}일째 · 화제도 {s[today]}"}


def _short(t: str, n: int = 60) -> str:
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def weekly_flow(stories: dict, history: dict, now: dt.datetime, use_llm: bool = False) -> dict:
    today = now.strftime("%Y-%m-%d")
    days = [(now - dt.timedelta(days=k)).strftime("%Y-%m-%d") for k in range(WEEK_DAYS - 1, -1, -1)]
    days = [d for d in days if d in stories]
    threads = build_threads(stories, days, use_llm)
    if not threads:
        return {}
    for th in threads:
        th.update(relate(th, days))
    top = [t for t in threads if len(t["days"]) >= 2 or t["n_sources"] >= 4][:7] or threads[:7]

    # 오늘 이야기 → 어떤 흐름에 속하는지
    today_map = {}
    for th in threads:
        for k in th.pop("keys"):
            if k.startswith(today + "|"):
                today_map[k.split("|", 1)[1]] = th
    # 기업 언급 모멘텀: 오늘 vs 이전 날 평균
    prev_days = [d for d in sorted(history) if d < today][-(WEEK_DAYS - 1):]
    mom = []
    if today in history and prev_days:
        for e, n in history[today]["entities"].items():
            avg = sum(history[d]["entities"].get(e, 0) for d in prev_days) / len(prev_days)
            if n or avg:
                mom.append({"name": e, "today": n, "avg": round(avg, 1), "delta": round(n - avg, 1)})
        mom.sort(key=lambda m: -abs(m["delta"]))
    cat_share = {}
    if today in history and prev_days:
        tot_t = max(1, sum(history[today]["categories"].values()))
        for c in CAT_DISPLAY:
            pw = sum(history[d]["categories"].get(c, 0) for d in prev_days)
            tw = max(1, sum(sum(history[d]["categories"].values()) for d in prev_days))
            cat_share[c] = {"today": round(100 * history[today]["categories"].get(c, 0) / tot_t),
                            "week": round(100 * pw / tw)}

    # 규칙 기반 흐름 해설 (API 키 없어도 동작)
    ins = []
    if top:
        t0 = top[0]
        ins.append(f"이번 주 가장 큰 흐름은 「{_short(t0.get('label') or t0['title'])}」 — {len(t0['days'])}일 동안 {t0['n_sources']}개 매체가 다뤘고, "
                   f"오늘은 '{t0['status']}' 상태입니다.")
    if len(top) > 2:
        ins.append("그 밖의 주간 핵심: " + ", ".join(f"「{_short(t.get('label') or t['title'], 45)}」({len(t['days'])}일·{t['status']})" for t in top[1:3]) + ".")
    shown = [id(t) for t in top[:3]]
    grow = [t for t in threads if t["status"] in ("확대", "재부상") and id(t) not in shown and t["n_sources"] >= 3][:2]
    for t in grow:
        ins.append(f"{'다시 떠오른' if t['status'] == '재부상' else '오늘 커진'} 흐름: 「{_short(t.get('label') or t['title'])}」 ({t['note']}).")
    newt = [t for t in threads if t["status"] == "새 흐름" and t["n_sources"] >= 2][:2]
    for t in newt:
        ins.append(f"오늘 새로 등장: 「{_short(t.get('label') or t['title'])}」 ({t['n_sources']}개 매체). 주간 흐름과 별개의 새 이슈입니다.")
    quiet = [t for t in top if t["status"] == "잠잠"][:2]
    for t in quiet:
        ins.append(f"잠잠해진 흐름: 「{_short(t.get('label') or t['title'])}」 — {t['note']}.")
    ups = [m for m in mom if m["delta"] >= 2][:2]
    downs = [m for m in mom if m["delta"] <= -2][:2]
    if ups or downs:
        ins.append("언급 변화: " + ", ".join([f"{m['name']} ▲ (오늘 {m['today']} / 평균 {m['avg']:g})" for m in ups] +
                                          [f"{m['name']} ▼ (오늘 {m['today']} / 평균 {m['avg']:g})" for m in downs]) + ".")
    return {"days": days, "n_days": len(days), "top": top, "momentum": mom[:10], "method": threads[0].get("method", "rule"),
            "cat_share": cat_share, "insights": ins, "llm": None, "_map": today_map}


def llm_flow(wk: dict, top_today: list[dict]) -> list[str] | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or requests is None or not wk:
        return None
    week = "\n".join(f"- {(t.get('label') + ': ') if t.get('label') else ''}{t['title']} | {len(t['days'])}일, {t['n_sources']}개 매체, 일별 화제도 {t['series']}, 오늘 상태: {t['status']}"
                     for t in wk["top"])
    today = "\n".join(f"- {c['lead']['title']} ({c['n_sources']}개 매체)" for c in top_today[:10])
    prompt = ("최근 7일 AI 뉴스의 주요 흐름(헤드라인 기준)과 오늘 헤드라인입니다.\n[주간 흐름]\n" + week + "\n\n[오늘]\n" + today +
              "\n\n헤드라인만 근거로, 오늘 뉴스가 이번 주 흐름과 어떻게 이어지는지 또는 흐름이 어떻게 달라졌는지(새 국면, 확대, "
              "진정, 반전)를 한국어로 4~5개, 각 90자 이내 '- ' 목록으로 쓰세요. 헤드라인에 없는 사실은 추측하지 마세요.")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("BRIEF_LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": 800,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        lines = [re.sub(r"^\s*[-•]\s*", "", l).strip() for l in text.splitlines() if l.strip().startswith(("-", "•"))]
        return lines[:5] or None
    except Exception as e:
        log(f"AI 흐름 분석 실패: {e}")
        return None


def analyze(items: list[dict], history: dict, seen: dict, now: dt.datetime, use_llm=True,
            stories: dict | None = None) -> dict:
    today = now.strftime("%Y-%m-%d")
    for it in items:
        it["category"] = categorize(it)
        it["entities"] = entities_of(it)
        it["key"] = key_of(it)
        it["new"] = it["key"] not in seen
    news = [i for i in items if i["kind"] != "official"]
    official = sorted([i for i in items if i["kind"] == "official"], key=lambda i: i["published"] or "", reverse=True)
    clusters = cluster(news)

    ent_count = {e: 0 for e in ENTITIES}
    for c in clusters:  # 같은 이야기는 한 번만 셈
        for e in c["entities"]:
            ent_count[e] += 1
    ent_rows = sorted([(e, n) for e, n in ent_count.items() if n], key=lambda x: -x[1])
    cat_count = {c: 0 for c in CAT_DISPLAY}
    for c in clusters:
        cat_count[c["category"]] += 1

    history[today] = {"entities": ent_count, "categories": cat_count, "stories": len(clusters), "articles": len(news)}
    for d in sorted(history)[:-30]:
        history.pop(d)
    days = sorted(history)[-7:]
    top_ents = [e for e, _ in ent_rows[:6]]
    trend = {"x": days, "series": {e: [history[d]["entities"].get(e, 0) for d in days] for e in top_ents}}

    by_cat = {c: [] for c in CAT_DISPLAY}
    for c in clusters:
        by_cat[c["category"]].append(c)

    wk = {}
    if stories is not None:
        stories[today] = [story_record(c, now) for c in sorted(clusters, key=lambda c: -c["score"])[:STORIES_PER_DAY]]
        for d in sorted(stories)[:-STORIES_KEEP_D]:
            stories.pop(d)
        wk = weekly_flow(stories, history, now, use_llm)
        mp = wk.pop("_map", {}) if wk else {}
        for c in clusters:
            th = mp.get(c["lead"]["link"])
            if th and len(th["days"]) >= 2:
                c["flow"] = {"status": th["status"], "days": len(th["days"]), "thread": th.get("label") or th["title"], "note": th["note"]}
        if wk and use_llm:
            wk["llm"] = llm_flow(wk, clusters[:10])

    top = clusters[:10]
    return {
        "weekly": wk,
        "today": today, "generated": now.strftime("%Y-%m-%d %H:%M KST"),
        "n_articles": len(news), "n_stories": len(clusters), "n_official": len(official),
        "n_new": sum(1 for c in clusters if any(i["new"] for i in c["items"])),
        "brief": llm_brief(top) if use_llm else None,
        "top": top, "by_cat": by_cat, "official": official[:12],
        "entities": ent_rows, "categories": cat_count, "trend": trend,
    }


# ---------------------------------------------------------------------------
# 4. HTML
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 뉴스 대시보드 · __DATE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{--surface-0:#f4f3f0;--surface-1:#fcfcfb;--border:#e3e2dd;--text-primary:#0b0b0b;--text-secondary:#52514e;
 --text-muted:#85847f;--grid:#ebeae6;--accent:#2a78d6;--new:#eb6834;
 --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#6250d6}
@media (prefers-color-scheme: dark){:root{--surface-0:#121211;--surface-1:#1a1a19;--border:#2e2e2b;--text-primary:#f0efec;
 --text-secondary:#c3c2b7;--text-muted:#8d8c84;--grid:#2a2a27;--accent:#3987e5;--new:#d95926;
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#9085e9}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);line-height:1.55;font-size:15px;
 font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:24px;margin:0 0 4px} .meta{color:var(--text-secondary);font-size:13px}
nav{position:sticky;top:0;z-index:5;background:var(--surface-0);padding:10px 0;margin:8px 0 6px;display:flex;gap:6px;overflow-x:auto;border-bottom:1px solid var(--border)}
nav a{white-space:nowrap;text-decoration:none;color:var(--text-secondary);font-size:13px;padding:6px 10px;border-radius:999px;border:1px solid var(--border);background:var(--surface-1)}
section{margin-top:26px} h2{font-size:19px;margin:0 0 12px} h2 .num{color:var(--accent);margin-right:6px} h3{font-size:16px;margin:0 0 8px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:16px}
.grid{display:grid;gap:14px}.g2{grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr))}
.tiles{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));margin-bottom:14px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:10px 12px}
.tile .lab{font-size:12px;color:var(--text-secondary)} .tile .val{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}
.brief li{margin:4px 0}
.story{padding:12px 0;border-bottom:1px solid var(--border)} .story:last-child{border-bottom:none}
.story a{color:var(--text-primary);text-decoration:none;font-weight:600} .story a:hover{text-decoration:underline}
.story .sub{font-size:12.5px;color:var(--text-muted);margin-top:3px}
.story .sum{font-size:13.5px;color:var(--text-secondary);margin-top:4px}
.story .more{font-size:12.5px;margin-top:4px} .story .more a{font-weight:400;color:var(--text-secondary)}
.pill{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:999px;border:1px solid var(--border);color:var(--text-secondary);margin-right:4px}
.new{display:inline-block;font-size:10.5px;font-weight:700;color:#fff;background:var(--new);border-radius:4px;padding:0 5px;margin-right:6px;vertical-align:1px}
.rank{display:inline-block;width:22px;color:var(--accent);font-weight:700}
.chart{width:100%;height:320px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tabs button{font:inherit;font-size:13px;padding:6px 12px;border-radius:999px;border:1px solid var(--border);background:var(--surface-1);color:var(--text-secondary);cursor:pointer}
.tabs button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.muted{color:var(--text-muted);font-size:12.5px}
.flow{display:inline-block;font-size:11px;font-weight:650;padding:0 7px;border-radius:4px;margin-right:6px;vertical-align:1px;border:1px solid currentColor}
.st-확대{color:var(--new)} .st-새{color:var(--accent)} .st-지속{color:var(--s3)} .st-재부상{color:var(--s6)} .st-축소,.st-잠잠{color:var(--text-muted)}
.insight li{margin:6px 0}
.strip{display:inline-flex;gap:3px;vertical-align:middle;margin-left:4px}
.strip i{display:inline-block;width:16px;height:10px;border-radius:2px;background:var(--accent)}
.strip i.off{background:var(--grid)}
.kw{display:inline-block;font-size:11px;padding:0 6px;border-radius:4px;background:var(--grid);color:var(--text-secondary);margin-right:3px}
table.mom{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
table.mom td,table.mom th{padding:5px 6px;border-bottom:1px solid var(--border);text-align:right}
table.mom td:first-child,table.mom th:first-child{text-align:left} table.mom th{color:var(--text-secondary);font-weight:500;font-size:12px}
.up{color:var(--new)} .down{color:var(--accent)}
footer{margin-top:40px;color:var(--text-muted);font-size:12px}
</style></head><body><div class="wrap">
<header><h1>AI 뉴스 대시보드</h1>
<div class="meta">생성 __GENERATED__ · 최근 36시간 뉴스 · 공식 블로그 최근 7일 · <a href="latest.pdf">PDF</a> · <a href="archive/">지난 대시보드</a></div></header>
__DEMO__
<nav><a href="#s1">① 오늘의 핵심</a><a href="#sw">② 이번 주 흐름</a><a href="#s2">③ 숫자로 보는 오늘</a><a href="#s3">④ 분야별 뉴스</a><a href="#s4">⑤ 공식 발표</a></nav>

<section id="s1"><h2><span class="num">①</span>오늘의 핵심</h2>
 <div class="tiles" id="tiles"></div>
 <div class="card" id="brief-card" style="margin-bottom:14px;display:none"><h3>AI 브리핑</h3><ul class="brief" id="brief" style="margin:0;padding-left:18px"></ul>
  <p class="muted" style="margin:6px 0 0">헤드라인을 바탕으로 AI가 요약했습니다. 세부 사실은 원문을 확인하세요.</p></div>
 <div class="card"><h3>가장 많이 다뤄진 이야기 TOP 10</h3><div id="top"></div></div>
</section>

<section id="sw"><h2><span class="num">②</span>이번 주 흐름 <span class="muted" id="wk-range"></span></h2>
 <div class="card" style="margin-bottom:14px"><h3>오늘 뉴스는 이번 주 흐름과 어떻게 이어지나</h3><ul class="insight" id="wk-ins" style="margin:0;padding-left:18px"></ul>
  <p class="muted" id="wk-ins-note" style="margin:6px 0 0"></p></div>
 <div class="card" style="margin-bottom:14px"><h3>이번 주 가장 임팩트 있는 흐름</h3><div id="wk-top"></div>
  <p class="muted" style="margin:8px 0 0">임팩트 = 다룬 매체 수 × 2 + 이어진 날 수 × 4 + 하루 최고 화제도 × 0.5 · 막대는 날짜별 화제도(진할수록 많이 다룸) ·
  상태: <span class="flow st-새">새 흐름</span><span class="flow st-확대">확대</span><span class="flow st-지속">지속</span><span class="flow st-재부상">재부상</span><span class="flow st-축소">축소</span><span class="flow st-잠잠">잠잠</span></p></div>
 <div class="card"><h3>기업 언급 변화 (오늘 vs 이전 날 평균)</h3><div id="wk-mom"></div></div>
</section>

<section id="s2"><h2><span class="num">③</span>숫자로 보는 오늘</h2>
 <div class="grid g2">
  <div class="card"><h3>기업·모델 언급 (이야기 수 기준)</h3><div id="ent" class="chart"></div></div>
  <div class="card"><h3>분야별 이야기 수</h3><div id="cat" class="chart"></div></div>
 </div>
 <div class="card" style="margin-top:14px"><h3>최근 7일 언급 추이 (상위 기업)</h3><div id="trend" class="chart"></div>
  <div class="muted" id="trend-legend"></div></div>
</section>

<section id="s3"><h2><span class="num">④</span>분야별 뉴스</h2>
 <div class="card"><div class="tabs" id="tabs"></div><div id="catlist"></div></div>
</section>

<section id="s4"><h2><span class="num">⑤</span>공식 발표 (기업 블로그)</h2><div class="card" id="official"></div></section>

<footer>출처: Google News, AI타임스, 각 기업 공식 블로그, Hacker News(100점 이상) RSS. 제목·요약 일부와 원문 링크만 싣습니다.
 같은 이야기는 제목 단어 겹침으로 묶어 '매체 수'로 화제도를 셉니다. 자동 생성 자료라 분류가 틀릴 수 있습니다. · ai_news.py</footer>
</div>
<script>
const D = __DATA__;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C={text:css('--text-primary'),sub:css('--text-secondary'),muted:css('--text-muted'),grid:css('--grid'),surf:css('--surface-1'),
 accent:css('--accent'),s:[css('--s1'),css('--s2'),css('--s3'),css('--s4'),css('--s5'),css('--s6')]};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stc=s=>'st-'+String(s).split(' ')[0];
const flowBadge=f=>f?`<span class="flow ${stc(f.status)}" title="${esc(f.thread)}">${f.days}일째 흐름 · ${esc(f.status)}</span>`:'';
const tm=s=>{if(!s)return'';const d=new Date(s);return (d.getMonth()+1)+'/'+d.getDate()+' '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')};
const cfg={displayModeBar:false,responsive:true};
const L=(x={})=>Object.assign({paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
 font:{family:getComputedStyle(document.body).fontFamily,color:C.sub,size:12},margin:{l:90,r:30,t:6,b:30},showlegend:false,
 hoverlabel:{bgcolor:C.surf,bordercolor:C.grid,font:{color:C.text}},
 xaxis:{gridcolor:C.grid,zeroline:false},yaxis:{gridcolor:'rgba(0,0,0,0)',automargin:true}},x);

// ① tiles / brief / top
const tiles=[['기사',D.n_articles],['이야기(묶음)',D.n_stories],['새 이야기',D.n_new],['공식 발표(7일)',D.n_official]];
document.getElementById('tiles').innerHTML=tiles.map(([l,v])=>`<div class="tile"><div class="lab">${l}</div><div class="val">${v}</div></div>`).join('');
if(D.brief&&D.brief.length){document.getElementById('brief-card').style.display='block';
 document.getElementById('brief').innerHTML=D.brief.map(b=>`<li>${esc(b)}</li>`).join('');}
function story(c,i){
 const l=c.lead, isNew=c.items.some(x=>x.new);
 const others=c.items.filter(x=>x.link!==l.link).slice(0,3);
 return `<div class="story">${i!=null?`<span class="rank">${i+1}</span>`:''}${isNew?'<span class="new">NEW</span>':''}${flowBadge(c.flow)}
  <a href="${esc(l.link)}" target="_blank" rel="noopener">${esc(l.title)}</a>
  <div class="sub"><span class="pill">${esc(c.category)}</span>${esc(l.source)} · ${tm(l.published)}${c.n_sources>1?` · <b>${c.n_sources}개 매체</b>`:''}${c.entities.length?' · '+c.entities.map(esc).join(', '):''}</div>
  ${l.summary?`<div class="sum">${esc(l.summary)}</div>`:''}
  ${others.length?`<div class="more">같은 이야기: ${others.map(o=>`<a href="${esc(o.link)}" target="_blank" rel="noopener">${esc(o.source)}</a>`).join(' · ')}</div>`:''}</div>`;
}
document.getElementById('top').innerHTML=D.top.map((c,i)=>story(c,i)).join('')||'<p class="muted">수집된 뉴스가 없습니다.</p>';

// ② weekly
(function(){
 const W=D.weekly||{};
 if(!W.top){document.getElementById('sw').innerHTML+='<p class="muted">주간 기록이 쌓이면 표시됩니다.</p>';return;}
 const md=d=>d.slice(5).replace('-','/');
 document.getElementById('wk-range').textContent=`${md(W.days[0])} ~ ${md(W.days.at(-1))} · ${W.n_days}일치`;
 const ins=(W.llm&&W.llm.length)?W.llm:W.insights;
 document.getElementById('wk-ins').innerHTML=ins.map(x=>`<li>${esc(x)}</li>`).join('');
 document.getElementById('wk-ins-note').textContent=(W.llm&&W.llm.length)?'헤드라인을 바탕으로 AI가 분석했습니다. 세부 사실은 원문을 확인하세요.'
  :'제목 핵심어로 날짜별 기사를 묶어 자동 판정했습니다. 저장소 Secrets에 ANTHROPIC_API_KEY를 넣으면 AI 해설로 바뀝니다.';
 document.getElementById('wk-ins-note').textContent+=W.method==='ai'?' · 사건 묶기: AI(같은 사건이면 표현이 달라도 함께 묶음)':' · 사건 묶기: 제목 핵심어 규칙';
 document.getElementById('wk-top').innerHTML=W.top.map((t,i)=>{
  const mx=Math.max(...W.top.flatMap(x=>x.series),1);
  const strip=t.series.map((v,k)=>`<i class="${v?'':'off'}" style="${v?`opacity:${(0.25+0.75*v/mx).toFixed(2)}`:''}" title="${md(W.days[k])}: ${v}"></i>`).join('');
  return `<div class="story"><span class="rank">${i+1}</span><span class="flow ${stc(t.status)}">${esc(t.status)}</span>
   ${t.label?`<b>${esc(t.label)}</b><div style="margin:2px 0 0 22px">`:''}<a href="${esc(t.link)}" target="_blank" rel="noopener" style="${t.label?'font-weight:400;font-size:14px':''}">${esc(t.title)}</a>${t.label?'</div>':''}
   <div class="sub">${t.keywords.map(k=>`<span class="kw">${esc(k==='§사건'?'사건·파문':k)}</span>`).join('')}<span class="pill">${esc(t.category)}</span>
    ${t.days.length}일 · ${t.n_sources}개 매체 · 기사 묶음 ${t.n_stories}개${t.entities.length?' · '+t.entities.slice(0,5).map(esc).join(', '):''}
    <span class="strip">${strip}</span></div>
   <div class="sum">${esc(t.note)} · 임팩트 ${t.impact}</div>
   ${t.links.length?`<div class="more">이어진 기사: ${t.links.slice(0,3).map(o=>`<a href="${esc(o.link)}" target="_blank" rel="noopener">${md(o.date)} ${esc(o.source)}</a>`).join(' · ')}</div>`:''}</div>`;}).join('');
 const M=W.momentum||[];
 document.getElementById('wk-mom').innerHTML=M.length?`<table class="mom"><tr><th>기업</th><th>오늘</th><th>이전 평균</th><th>변화</th></tr>${
  M.map(m=>`<tr><td>${esc(m.name)}</td><td>${m.today}</td><td>${m.avg}</td><td class="${m.delta>0?'up':m.delta<0?'down':''}">${m.delta>0?'▲ +':m.delta<0?'▼ ':''}${m.delta}</td></tr>`).join('')}</table>`
  :'<p class="muted">비교할 지난 기록이 아직 없습니다.</p>';
})();

// ③ charts (단일 색: 크기 비교)
const ent=[...D.entities].slice(0,12).reverse();
Plotly.newPlot('ent',[{type:'bar',orientation:'h',y:ent.map(e=>e[0]),x:ent.map(e=>e[1]),marker:{color:C.accent},width:0.6,
 text:ent.map(e=>e[1]),textposition:'outside',cliponaxis:false,textfont:{color:C.sub,size:11},hovertemplate:'%{y}: %{x}건<extra></extra>'}],
 L({xaxis:{gridcolor:C.grid,zeroline:false,dtick:Math.max(1,Math.ceil((ent.at(-1)?.[1]||1)/5))}}),cfg);
const cats=Object.entries(D.categories).reverse();
Plotly.newPlot('cat',[{type:'bar',orientation:'h',y:cats.map(c=>c[0]),x:cats.map(c=>c[1]),marker:{color:C.accent},width:0.6,
 text:cats.map(c=>c[1]),textposition:'outside',cliponaxis:false,textfont:{color:C.sub,size:11},hovertemplate:'%{y}: %{x}건<extra></extra>'}],L(),cfg);
const T=D.trend, names=Object.keys(T.series);
Plotly.newPlot('trend',names.map((n,i)=>({type:'scatter',mode:'lines+markers',x:T.x.map(d=>d.slice(5)),y:T.series[n],name:n,
 line:{color:C.s[i%6],width:2},marker:{size:8,color:C.s[i%6],line:{color:C.surf,width:2}},hovertemplate:n+': %{y}건<extra></extra>'})),
 L({margin:{l:36,r:14,t:6,b:30},hovermode:'x unified',yaxis:{gridcolor:C.grid,rangemode:'tozero'},xaxis:{type:'category',gridcolor:'rgba(0,0,0,0)'}}),cfg);
document.getElementById('trend-legend').innerHTML=names.map((n,i)=>`<span style="color:${C.s[i%6]}">━</span> ${esc(n)}`).join(' &nbsp; ')
 +(T.x.length<2?' · 추이는 매일 쌓이면서 채워집니다.':'');

// ③ tabs
const tabs=document.getElementById('tabs'), list=document.getElementById('catlist');
const catNames=Object.keys(D.by_cat);
function show(cn){[...tabs.children].forEach(b=>b.classList.toggle('on',b.dataset.c===cn));
 list.innerHTML=D.by_cat[cn].map(c=>story(c)).join('')||'<p class="muted">해당 분야 뉴스가 없습니다.</p>';}
tabs.innerHTML=catNames.map(c=>`<button data-c="${esc(c)}">${esc(c)} ${D.by_cat[c].length}</button>`).join('');
tabs.onclick=e=>{const b=e.target.closest('button'); if(b) show(b.dataset.c);};
show(catNames.find(c=>D.by_cat[c].length)||catNames[0]);

// ④ official
document.getElementById('official').innerHTML=D.official.map(o=>`<div class="story">${o.new?'<span class="new">NEW</span>':''}
 <a href="${esc(o.link)}" target="_blank" rel="noopener">${esc(o.title)}</a><div class="sub"><span class="pill">${esc(o.feed)}</span>${tm(o.published)}</div>
 ${o.summary?`<div class="sum">${esc(o.summary)}</div>`:''}</div>`).join('')||'<p class="muted">최근 7일 공식 발표가 없습니다.</p>';
</script></body></html>
"""


def render_html(data: dict, demo: bool) -> str:
    banner = ('<div style="background:#fff4d6;color:#5a4300;border:1px solid #f0d27a;padding:10px 14px;border-radius:10px;'
              'margin:14px 0;font-size:14px"><b>데모 모드</b> — 가상 데이터입니다. 실제 뉴스가 아닙니다.</div>') if demo else ""
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (HTML.replace("__DATA__", payload).replace("__DEMO__", banner)
            .replace("__DATE__", data["today"]).replace("__GENERATED__", html.escape(data["generated"])))


# ---------------------------------------------------------------------------
# 5. PDF (matplotlib)
# ---------------------------------------------------------------------------
def render_pdf(data: dict, path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.ticker import MaxNLocator

    have = {f.name for f in font_manager.fontManager.ttflist}
    for nm in ("Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic", "Noto Sans CJK KR", "NanumGothic"):
        if nm in have:
            plt.rcParams["font.family"] = nm
            break
    plt.rcParams.update({"axes.unicode_minus": False, "font.size": 8.5, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.edgecolor": "#e6e5e0"})
    TEXT, SUB, MUTED, ACC, NEW = "#0b0b0b", "#52514e", "#85847f", "#2a78d6", "#eb6834"
    A4 = (8.27, 11.69)

    def wrap(t, w):
        out, cur, n = [], "", 0
        for ch in t:
            cw = 2 if ord(ch) > 0x2000 else 1
            if n + cw > w and cur:
                out.append(cur); cur, n = "", 0
            cur += ch; n += cw
        if cur:
            out.append(cur)
        return out

    class Page:
        def __init__(self, pdf, title, pno):
            self.pdf, self.pno = pdf, pno
            self.fig = plt.figure(figsize=A4)
            self.fig.text(0.06, 0.965, title, fontsize=15, fontweight="bold", color=TEXT, va="top")
            self.fig.text(0.06, 0.94, f"생성 {data['generated']} · 기사 {data['n_articles']} · 이야기 {data['n_stories']}",
                          fontsize=7.5, color=SUB, va="top")
            self.fig.text(0.94, 0.02, str(pno), fontsize=7, color=MUTED, ha="right")
            self.fig.text(0.06, 0.02, "자동 생성 · 출처: Google News, AI타임스, 기업 블로그, Hacker News", fontsize=6.5, color=MUTED)
            self.y = 0.91

        def text(self, s, size=8.5, color=TEXT, bold=False, indent=0.0, lh=0.0155, width=104, url=None):
            for k, part in enumerate(wrap(s, width)):
                t = self.fig.text(0.06 + indent, self.y, part, fontsize=size, color=color, va="top",
                                  fontweight="bold" if bold else "normal")
                if url:
                    t.set_url(url)
                self.y -= lh
            return self

        def close(self):
            self.pdf.savefig(self.fig)
            plt.close(self.fig)

    def story_lines(pg, c, rank=None):
        l = c["lead"]
        new = "[NEW] " if any(i["new"] for i in c["items"]) else ""
        head = (f"{rank}. " if rank else "· ") + new + l["title"]
        pg.text(head, size=8.6, bold=True, url=l["link"], width=100)
        meta = f"{c['category']} · {l['source']}" + (f" · {c['n_sources']}개 매체" if c["n_sources"] > 1 else "")
        if c["entities"]:
            meta += " · " + ", ".join(c["entities"][:5])
        pg.text(meta, size=7.2, color=MUTED, indent=0.02, lh=0.014)
        if l["summary"]:
            pg.text(l["summary"][:160], size=7.6, color=SUB, indent=0.02, lh=0.0135, width=110)
        pg.y -= 0.006

    with PdfPages(path) as pdf:
        pno = 1
        pg = Page(pdf, f"AI 뉴스 대시보드 · {data['today']}", pno)
        if data.get("brief"):
            pg.text("AI 브리핑", size=10, bold=True)
            for b in data["brief"]:
                pg.text("• " + b, size=8.6, indent=0.01)
            pg.y -= 0.01
        # 차트 2개
        ax_h = 0.16
        ax1 = pg.fig.add_axes([0.14, pg.y - ax_h, 0.33, ax_h - 0.02])
        ents = data["entities"][:10][::-1]
        ax1.barh([e for e, _ in ents], [n for _, n in ents], color=ACC, height=0.6)
        ax1.set_title("기업·모델 언급", loc="left", fontsize=9, color=TEXT)
        ax1.tick_params(labelsize=7)
        ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax2 = pg.fig.add_axes([0.62, pg.y - ax_h, 0.32, ax_h - 0.02])
        cats = list(data["categories"].items())[::-1]
        ax2.barh([c for c, _ in cats], [n for _, n in cats], color=ACC, height=0.6)
        ax2.set_title("분야별 이야기 수", loc="left", fontsize=9, color=TEXT)
        ax2.tick_params(labelsize=7)
        ax2.xaxis.set_major_locator(MaxNLocator(integer=True))
        pg.y -= ax_h + 0.03
        pg.text("가장 많이 다뤄진 이야기 TOP 10", size=10, bold=True)
        pg.y -= 0.004
        for i, c in enumerate(data["top"]):
            if pg.y < 0.08:
                pg.close(); pno += 1; pg = Page(pdf, "가장 많이 다뤄진 이야기 (계속)", pno)
            story_lines(pg, c, i + 1)
        pg.close()
        # 이번 주 흐름
        wk = data.get("weekly") or {}
        if wk.get("top"):
            pno += 1
            d0, d1 = wk["days"][0][5:].replace("-", "/"), wk["days"][-1][5:].replace("-", "/")
            pg = Page(pdf, f"이번 주 흐름 ({d0}~{d1}, {wk['n_days']}일치)", pno)
            pg.text("오늘 뉴스는 이번 주 흐름과 어떻게 이어지나" + (" (AI 분석)" if wk.get("llm") else ""), size=10, bold=True)
            for x in (wk.get("llm") or wk["insights"]):
                pg.text("• " + x, size=8.4, indent=0.01, width=102)
            pg.y -= 0.012
            pg.text("이번 주 가장 임팩트 있는 흐름", size=10, bold=True)
            pg.y -= 0.004
            for i, t in enumerate(wk["top"]):
                if pg.y < 0.1:
                    pg.close(); pno += 1; pg = Page(pdf, "이번 주 흐름 (계속)", pno)
                pg.text(f"{i + 1}. [{t['status']}] " + (f"{t['label']} — " if t.get("label") else "") + t["title"],
                        size=8.6, bold=True, url=t["link"], width=100)
                days_s = " ".join(f"{d[5:].replace('-', '/')}:{v}" for d, v in zip(wk["days"], t["series"]))
                pg.text(f"{len(t['days'])}일 · {t['n_sources']}개 매체 · 임팩트 {t['impact']} · 핵심어 {', '.join('사건·파문' if k == EVENT else k for k in t['keywords']) or '-'}",
                        size=7.2, color=MUTED, indent=0.02, lh=0.014)
                pg.text(f"{t['note']} · 날짜별 화제도 {days_s}", size=7.4, color=SUB, indent=0.02, lh=0.0135, width=110)
                pg.y -= 0.006
            mom = [m for m in wk.get("momentum", []) if m["delta"]][:8]
            if mom and pg.y > 0.15:
                pg.y -= 0.008
                pg.text("기업 언급 변화 (오늘 / 이전 평균)", size=10, bold=True)
                pg.text("   ".join(f"{m['name']} {'▲' if m['delta'] > 0 else '▼'} {m['today']}/{m['avg']:g}" for m in mom),
                        size=8.2, color=SUB, width=104)
            pg.close()
        # 분야별
        pno += 1
        pg = Page(pdf, "분야별 뉴스", pno)
        for cat, cl in data["by_cat"].items():
            if not cl:
                continue
            if pg.y < 0.12:
                pg.close(); pno += 1; pg = Page(pdf, "분야별 뉴스 (계속)", pno)
            pg.text(f"■ {cat} ({len(cl)})", size=10, bold=True, color=ACC)
            for c in cl[:8]:
                if pg.y < 0.08:
                    pg.close(); pno += 1; pg = Page(pdf, f"분야별 뉴스 · {cat} (계속)", pno)
                story_lines(pg, c)
            pg.y -= 0.008
        if data["official"]:
            if pg.y < 0.2:
                pg.close(); pno += 1; pg = Page(pdf, "공식 발표", pno)
            pg.text("■ 공식 발표 (기업 블로그, 최근 7일)", size=10, bold=True, color=ACC)
            for o in data["official"]:
                if pg.y < 0.08:
                    pg.close(); pno += 1; pg = Page(pdf, "공식 발표 (계속)", pno)
                pg.text(("[NEW] " if o["new"] else "· ") + o["title"], size=8.6, bold=True, url=o["link"])
                pg.text(f"{o['feed']} · {(o['published'] or '')[:10]}", size=7.2, color=MUTED, indent=0.02, lh=0.014)
        pg.close()
    return path


# ---------------------------------------------------------------------------
# 6. 데모 데이터
# ---------------------------------------------------------------------------
def demo_items(now: dt.datetime) -> list[dict]:
    import random
    rnd = random.Random(3)
    base = [
        ("en", "OpenAI unveils new reasoning model for enterprise agents", ["Reuters", "The Verge", "CNBC", "TechCrunch"]),
        ("en", "Anthropic releases Claude update with longer context and lower prices", ["The Verge", "Bloomberg", "Wired"]),
        ("en", "Nvidia shares climb as AI data center demand stays strong", ["CNBC", "Reuters"]),
        ("en", "EU regulators publish draft guidance under the AI Act for general-purpose models", ["Politico", "Reuters"]),
        ("en", "Google DeepMind paper shows new benchmark gains in math reasoning", ["Nature", "VentureBeat"]),
        ("en", "Meta open-sources new Llama model for on-device use", ["TechCrunch", "Engadget"]),
        ("ko", "네이버 하이퍼클로바X 신규 모델 공개…기업용 에이전트 강화", ["전자신문", "조선비즈", "AI타임스"]),
        ("ko", "정부, AI 기본법 시행령 초안 발표…고영향 AI 기준 제시", ["연합뉴스", "한겨레"]),
        ("ko", "삼성전자 HBM 공급 확대…AI 반도체 투자 수조원 규모", ["한국경제", "매일경제"]),
        ("ko", "LG AI연구원 엑사원 새 버전 공개, 수학·코딩 성능 향상", ["AI타임스", "전자신문"]),
        ("en", "Startup raises $400 million to build AI coding agents", ["TechCrunch"]),
        ("en", "Researchers warn about AI model evaluation contamination", ["MIT Tech Review"]),
    ]
    out = []
    for lang, title, srcs in base:
        for k, s in enumerate(srcs):
            t = title if k == 0 else title.replace("new", "latest", 1) if lang == "en" else title
            out.append({"title": t, "link": "#", "source": s, "feed": "demo", "lang": lang, "kind": "news",
                        "summary": "가상 요약입니다. 실제 실행 시 기사 설명이 들어갑니다." if k == 0 else "",
                        "published": (now - dt.timedelta(hours=rnd.randint(1, 30))).isoformat()})
    for f, t in [("OpenAI", "Introducing new tools for building agents"), ("Google DeepMind", "Advancing AI for science"),
                 ("NVIDIA", "New inference platform for data centers"), ("Hugging Face", "Open-source model leaderboard update")]:
        out.append({"title": t, "link": "#", "source": f, "feed": f, "lang": "en", "kind": "official", "summary": "",
                    "published": (now - dt.timedelta(days=rnd.randint(0, 6))).isoformat()})
    return out


# ---------------------------------------------------------------------------
# 7. 저장 (GitHub Pages 구조)
# ---------------------------------------------------------------------------
def write_indexes(site: Path, sub: str) -> None:
    head = ('<!DOCTYPE html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<body style="font-family:-apple-system,sans-serif;padding:20px;line-height:1.8">')
    arch = site / sub / "archive"
    links = sorted((p for p in arch.glob("*.html") if p.name != "index.html"), reverse=True)
    items = "".join(f'<li><a href="{p.name}">{p.stem}</a></li>' for p in links)
    (arch / "index.html").write_text(f'{head}<title>{sub} 지난 리포트</title><h2>{sub} · 지난 리포트</h2>'
                                     f'<p><a href="../">← 최신</a></p><ul>{items}</ul>', encoding="utf-8")
    subs = sorted(d.name for d in site.iterdir() if d.is_dir() and (d / "index.html").exists())
    items = "".join(f'<li><a href="{d}/">{d}</a> · <a href="{d}/archive/">지난 리포트</a></li>' for d in subs)
    (site / "index.html").write_text(f'{head}<title>reports</title><h2>reports</h2><ul>{items}</ul>', encoding="utf-8")
    (site / ".nojekyll").touch()


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 뉴스 종합 대시보드 생성")
    ap.add_argument("--outdir", default="_site/daily_ai-news")
    ap.add_argument("--keep-days", type=int, default=365, help="archive 보관 기간(일)")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="AI 요약 생략")
    ap.add_argument("--demo", action="store_true", help="인터넷 없이 가상 데이터로 생성")
    args = ap.parse_args(argv)

    now = dt.datetime.now(KST)
    out = Path(os.path.expanduser(args.outdir))
    (out / "archive").mkdir(parents=True, exist_ok=True)
    history = _load(out / "history.json", {})
    seen = _load(out / "seen.json", {})
    stories = {} if args.demo else bootstrap_stories(out, _load(out / "stories.json", {}), now)

    if args.demo:
        items, status = demo_items(now), {"demo": 1}
    else:
        items, status = collect(now)
    log(f"수집 {len(items)}건 (기간 내)")
    if not items and not args.demo:
        log("수집된 기사가 없어 기존 게시본을 유지합니다.")
        return

    data = analyze(items, history, seen, now, use_llm=not (args.no_llm or args.demo),
                   stories=None if args.demo else stories)
    data["feeds"] = status
    wd = WEEKDAY[now.weekday()]
    suffix = "_demo" if args.demo else ""
    page = render_html(data, args.demo)
    (out / "index.html").write_text(page, encoding="utf-8")
    dated = out / "archive" / f"{now:%Y-%m-%d}_{wd}{suffix}.html"
    dated.write_text(page, encoding="utf-8")

    meta = {"date": now.strftime("%Y-%m-%d"), "weekday": wd, "month": now.strftime("%Y-%m"),
            "pdf_name": f"{now:%m%d}_{wd}{suffix}.pdf", "html_name": dated.name, "generated": data["generated"],
            "articles": data["n_articles"], "stories": data["n_stories"], "pdf": False}
    if not args.no_pdf:
        try:
            render_pdf(data, out / "latest.pdf")
            meta["pdf"] = True
        except Exception as e:
            log(f"PDF 생성 실패: {e}")
    (out / "latest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    if not args.demo:
        cutoff = (now - dt.timedelta(days=7)).isoformat()
        for it in items:
            seen.setdefault(it["key"], now.isoformat())
        seen = {k: v for k, v in seen.items() if v >= cutoff}
        (out / "seen.json").write_text(json.dumps(seen), encoding="utf-8")
        (out / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        (out / "stories.json").write_text(json.dumps(stories, ensure_ascii=False), encoding="utf-8")

    cut = (now - dt.timedelta(days=args.keep_days)).strftime("%Y-%m-%d")
    for p in (out / "archive").glob("*.html"):
        if p.name != "index.html" and p.name[:10] < cut:
            p.unlink()
    write_indexes(out.parent, out.name)
    log(f"완료: {dated}")


if __name__ == "__main__":
    main()
