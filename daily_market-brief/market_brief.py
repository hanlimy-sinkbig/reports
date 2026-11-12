#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
모닝 마켓 브리핑 생성기 (market_brief.py)
==========================================

매일 아침 실행하면 아래 5개 섹션으로 구성된 HTML 웹페이지와 PDF(brief_pdf.py)를 만듭니다.

  1) 나스닥 · 코스피 주요 지수 차트 (캔들 + 20/60일 이동평균) 및 보조 지표
  2) 주요 섹터별 히트맵 (미국 대형주 / 코스피 대형주 트리맵 + 섹터 등락 막대)
  3) 주요 종목 차트 (전일 '이상 움직임'이 가장 컸던 종목 자동 선정)
  4) 주요 종목 선정 이유 + 관련 최신 뉴스 (Google News RSS)
  5) 주요 종목과 관련된 다른 종목(동종·공급망·한미 연관주) 비교 분석

데이터: Yahoo Finance(yfinance), 뉴스: Google News RSS
차트:   Plotly.js (CDN) — 파이썬 쪽에는 plotly 설치가 필요 없습니다.

사용법
------
  pip install -r requirements.txt
  python market_brief.py                       # ./output/latest.(pdf|html) + ./output/YYYY-MM/MMDD_요일.*
                                               # 주말·한미 동시 휴장일은 자동으로 건너뜀(--force 로 강제)
  python market_brief.py --outdir "<구글드라이브>/내 드라이브/reports/daily_market-brief"
  python market_brief.py --top 3 --watch NVDA 005930.KS
  python market_brief.py --demo                # 인터넷 없이 가상 데이터로 레이아웃 확인
  python market_brief.py --layout site --outdir _site/daily_market-brief   # GitHub Pages 용 (Actions 에서 사용)
  python market_brief.py --github-repo ~/reports/_github     # GitHub Pages 로도 게시(.../reports/daily_market-brief/)

선택: 환경변수 ANTHROPIC_API_KEY 가 있으면 종목별 한 줄 요약을 LLM으로 추가합니다(없어도 동작).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

KST = dt.timezone(dt.timedelta(hours=9))

# ---------------------------------------------------------------------------
# 1. 설정: 지수 · 유니버스 · 연관 종목
# ---------------------------------------------------------------------------
MAIN_INDICES = {"^IXIC": "나스닥 종합", "^KS11": "코스피"}
SUB_INDICES = {
    "^GSPC": "S&P 500",
    "^NDX": "나스닥 100",
    "^SOX": "필라델피아 반도체",
    "^KQ11": "코스닥",
    "^VIX": "VIX(변동성)",
    "^TNX": "미 10년물 금리",
    "KRW=X": "원/달러 환율",
}

US_SECTOR_ETF = {
    "XLK": "정보기술", "XLC": "커뮤니케이션", "XLY": "임의소비재", "XLP": "필수소비재",
    "XLE": "에너지", "XLF": "금융", "XLV": "헬스케어", "XLI": "산업재",
    "XLB": "소재", "XLRE": "부동산", "XLU": "유틸리티",
}

# 미국 대형주: 티커 -> (이름, 섹터, 기본 시총가중치[조달러, 시총 조회 실패 시 사용])
US_UNIVERSE = {
    "AAPL": ("애플", "정보기술", 3.6), "MSFT": ("마이크로소프트", "정보기술", 3.5),
    "NVDA": ("엔비디아", "정보기술", 4.2), "AVGO": ("브로드컴", "정보기술", 1.5),
    "ORCL": ("오라클", "정보기술", 0.7), "AMD": ("AMD", "정보기술", 0.35),
    "CRM": ("세일즈포스", "정보기술", 0.25), "ADBE": ("어도비", "정보기술", 0.16),
    "CSCO": ("시스코", "정보기술", 0.27), "QCOM": ("퀄컴", "정보기술", 0.18),
    "MU": ("마이크론", "정보기술", 0.2), "INTC": ("인텔", "정보기술", 0.15),
    "GOOGL": ("알파벳", "커뮤니케이션", 3.0), "META": ("메타", "커뮤니케이션", 1.8),
    "NFLX": ("넷플릭스", "커뮤니케이션", 0.5), "TMUS": ("T-모바일", "커뮤니케이션", 0.27),
    "AMZN": ("아마존", "임의소비재", 2.4), "TSLA": ("테슬라", "임의소비재", 1.3),
    "HD": ("홈디포", "임의소비재", 0.4), "MCD": ("맥도날드", "임의소비재", 0.22),
    "NKE": ("나이키", "임의소비재", 0.1),
    "JPM": ("JP모건", "금융", 0.8), "V": ("비자", "금융", 0.65), "MA": ("마스터카드", "금융", 0.52),
    "BAC": ("뱅크오브아메리카", "금융", 0.38), "GS": ("골드만삭스", "금융", 0.24),
    "LLY": ("일라이릴리", "헬스케어", 0.8), "UNH": ("유나이티드헬스", "헬스케어", 0.3),
    "JNJ": ("존슨앤존슨", "헬스케어", 0.45), "ABBV": ("애브비", "헬스케어", 0.38),
    "MRK": ("머크", "헬스케어", 0.23),
    "GE": ("GE 에어로스페이스", "산업재", 0.3), "CAT": ("캐터필러", "산업재", 0.25),
    "BA": ("보잉", "산업재", 0.16), "RTX": ("RTX", "산업재", 0.22),
    "WMT": ("월마트", "필수소비재", 0.8), "COST": ("코스트코", "필수소비재", 0.42),
    "PG": ("P&G", "필수소비재", 0.36), "KO": ("코카콜라", "필수소비재", 0.3),
    "XOM": ("엑슨모빌", "에너지", 0.5), "CVX": ("셰브론", "에너지", 0.3),
    "NEE": ("넥스트에라", "유틸리티", 0.16), "LIN": ("린데", "소재", 0.21),
    "PLD": ("프로로지스", "부동산", 0.1),
}

# 코스피(일부 코스닥) 대형주: 티커 -> (이름, 섹터, 기본 시총가중치[조원])
KR_UNIVERSE = {
    "005930.KS": ("삼성전자", "반도체", 600), "000660.KS": ("SK하이닉스", "반도체", 400),
    "042700.KS": ("한미반도체", "반도체", 12), "009150.KS": ("삼성전기", "전자부품", 15),
    "373220.KS": ("LG에너지솔루션", "2차전지", 90), "006400.KS": ("삼성SDI", "2차전지", 20),
    "247540.KQ": ("에코프로비엠", "2차전지", 15), "086520.KQ": ("에코프로", "2차전지", 12),
    "051910.KS": ("LG화학", "화학", 25), "005490.KS": ("POSCO홀딩스", "철강·소재", 25),
    "005380.KS": ("현대차", "자동차", 55), "000270.KS": ("기아", "자동차", 40),
    "012330.KS": ("현대모비스", "자동차", 25),
    "207940.KS": ("삼성바이오로직스", "바이오", 80), "068270.KS": ("셀트리온", "바이오", 40),
    "196170.KQ": ("알테오젠", "바이오", 20),
    "035420.KS": ("NAVER", "인터넷", 35), "035720.KS": ("카카오", "인터넷", 25),
    "105560.KS": ("KB금융", "금융", 45), "055550.KS": ("신한지주", "금융", 35),
    "086790.KS": ("하나금융지주", "금융", 25), "032830.KS": ("삼성생명", "금융", 30),
    "329180.KS": ("HD현대중공업", "조선·방산·전력", 40), "009540.KS": ("HD한국조선해양", "조선·방산·전력", 25),
    "012450.KS": ("한화에어로스페이스", "조선·방산·전력", 45), "034020.KS": ("두산에너빌리티", "조선·방산·전력", 50),
    "267260.KS": ("HD현대일렉트릭", "조선·방산·전력", 20),
    "017670.KS": ("SK텔레콤", "통신", 12), "028260.KS": ("삼성물산", "지주", 35),
    "402340.KS": ("SK스퀘어", "지주", 30),
}

# 섹터를 넘어서는 연관 관계(공급망·한미 연관주). 양방향으로 자동 확장됩니다.
CROSS_LINKS = {
    "NVDA": ["000660.KS", "005930.KS", "042700.KS", "MU", "AVGO", "AMD"],
    "MU": ["000660.KS", "005930.KS"],
    "AVGO": ["000660.KS", "NVDA"],
    "AMD": ["005930.KS", "NVDA"],
    "AAPL": ["009150.KS", "QCOM", "005930.KS"],
    "TSLA": ["373220.KS", "006400.KS", "247540.KQ", "005380.KS"],
    "INTC": ["005930.KS", "AMD"],
    "META": ["000660.KS", "GOOGL"],
    "MSFT": ["ORCL", "034020.KS", "267260.KS"],
    "GOOGL": ["000660.KS", "035420.KS"],
    "AMZN": ["267260.KS", "MSFT"],
    "ORCL": ["267260.KS", "034020.KS"],
    "BA": ["012450.KS", "GE"],
    "RTX": ["012450.KS"],
    "XOM": ["329180.KS", "CVX"],
    "LLY": ["207940.KS", "196170.KQ"],
    "MRK": ["196170.KQ", "207940.KS"],
    "JPM": ["105560.KS"],
    "NFLX": ["035720.KS"],
}

NAMES_EN = {  # 미국 종목 뉴스 검색용 영문명
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AVGO": "Broadcom", "ORCL": "Oracle",
    "AMD": "AMD", "CRM": "Salesforce", "ADBE": "Adobe", "CSCO": "Cisco", "QCOM": "Qualcomm",
    "MU": "Micron", "INTC": "Intel", "GOOGL": "Alphabet Google", "META": "Meta Platforms",
    "NFLX": "Netflix", "TMUS": "T-Mobile", "AMZN": "Amazon", "TSLA": "Tesla", "HD": "Home Depot",
    "MCD": "McDonald's", "NKE": "Nike", "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard",
    "BAC": "Bank of America", "GS": "Goldman Sachs", "LLY": "Eli Lilly", "UNH": "UnitedHealth",
    "JNJ": "Johnson & Johnson", "ABBV": "AbbVie", "MRK": "Merck", "GE": "GE Aerospace",
    "CAT": "Caterpillar", "BA": "Boeing", "RTX": "RTX Raytheon", "WMT": "Walmart",
    "COST": "Costco", "PG": "Procter & Gamble", "KO": "Coca-Cola", "XOM": "Exxon Mobil",
    "CVX": "Chevron", "NEE": "NextEra Energy", "LIN": "Linde", "PLD": "Prologis",
}


def info(ticker: str) -> tuple[str, str, float, str]:
    """(이름, 섹터, 기본가중치, 시장)"""
    if ticker in US_UNIVERSE:
        n, s, w = US_UNIVERSE[ticker]
        return n, s, w, "US"
    if ticker in KR_UNIVERSE:
        n, s, w = KR_UNIVERSE[ticker]
        return n, s, w, "KR"
    mkt = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
    return ticker, "기타", 1.0, mkt


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(KST):%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 2. 데이터 수집
# ---------------------------------------------------------------------------
class LiveSource:
    """yfinance 로 실제 시세를 가져옵니다."""

    def __init__(self):
        try:
            import yfinance as yf  # noqa: F401
        except ImportError:
            sys.exit("yfinance 가 필요합니다: pip install -r requirements.txt")
        import yfinance as yf
        self.yf = yf

    def history(self, tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        raw = self.yf.download(tickers, period=period, interval="1d", group_by="ticker",
                               auto_adjust=False, progress=False, threads=True)
        for t in tickers:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                if len(df) >= 5:
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    out[t] = df
            except Exception:
                pass
        missing = sorted(set(tickers) - set(out))
        if missing:
            log(f"시세 없음(건너뜀): {', '.join(missing)}")
        return out

    def market_caps(self, tickers: list[str]) -> dict[str, float]:
        def one(t):
            try:
                v = getattr(self.yf.Ticker(t).fast_info, "market_cap", None)
                return t, float(v) if v else None
            except Exception:
                return t, None
        with ThreadPoolExecutor(max_workers=8) as ex:
            return {t: v for t, v in ex.map(one, tickers) if v}

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        name, _, _, mkt = info(ticker)
        if mkt == "KR":
            items = google_news(f'"{name}"', "ko", limit)
        else:
            items = google_news(f'{NAMES_EN.get(ticker, ticker)} stock', "en", limit)
            items += google_news(f'{name} 주가', "ko", max(2, limit // 2))
        if not items:  # 대체: yfinance 뉴스
            try:
                for n in (self.yf.Ticker(ticker).news or [])[:limit]:
                    c = n.get("content", n)
                    items.append({"title": c.get("title", ""),
                                  "link": (c.get("canonicalUrl") or {}).get("url") or c.get("link", ""),
                                  "source": (c.get("provider") or {}).get("displayName", "Yahoo Finance"),
                                  "date": c.get("pubDate", "")})
            except Exception:
                pass
        # 중복 제거
        seen, uniq = set(), []
        for it in items:
            k = re.sub(r"\W", "", it["title"])[:40]
            if k and k not in seen:
                seen.add(k)
                uniq.append(it)
        return uniq[:limit + 2]


def google_news(query: str, lang: str, limit: int) -> list[dict]:
    if requests is None:
        return []
    q = urllib.parse.quote(f"{query} when:3d")
    if lang == "ko":
        url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    else:
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log(f"뉴스 조회 실패({query}): {e}")
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        pub = it.findtext("pubDate") or ""
        try:
            pub = parsedate_to_datetime(pub).astimezone(KST).strftime("%m/%d %H:%M")
        except Exception:
            pass
        items.append({"title": title, "link": it.findtext("link") or "", "source": src, "date": pub})
        if len(items) >= limit:
            break
    return items


class DemoSource:
    """인터넷 없이 레이아웃을 확인하기 위한 가상 데이터(실제 시세 아님)."""

    def __init__(self, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.factor_cache: dict[str, np.ndarray] = {}

    def _factor(self, key: str, n: int, vol: float) -> np.ndarray:
        if key not in self.factor_cache:
            self.factor_cache[key] = self.rng.normal(0.0004, vol, n)
        return self.factor_cache[key]

    def history(self, tickers, period="1y"):
        end = pd.Timestamp(dt.date.today()) - pd.Timedelta(days=1)
        idx = pd.bdate_range(end=end, periods=250)
        n = len(idx)
        mkt_us = self._factor("US", n, 0.011)
        mkt_kr = self._factor("KR", n, 0.012)
        out = {}
        for t in tickers:
            _, sector, w, mkt = info(t)
            base_mkt = mkt_kr if mkt == "KR" else mkt_us
            sec = self._factor(sector, n, 0.008)
            idio = self.rng.normal(0, 0.012 if not t.startswith("^") else 0.003, n)
            beta = 1.0 if not t.startswith("^") else 0.9
            r = beta * base_mkt + (0.7 * sec if not t.startswith("^") else 0) + idio
            if t in ("^VIX",):
                r = -2.5 * mkt_us + self.rng.normal(0, 0.03, n)
            # 마지막 날 일부 종목에 '이벤트' 부여
            if t in ("NVDA", "000660.KS", "TSLA", "012450.KS", "LLY", "035420.KS"):
                r[-1] += self.rng.choice([-1, 1]) * self.rng.uniform(0.04, 0.08)
            start = {"^IXIC": 22000, "^KS11": 4800, "^GSPC": 6800, "^NDX": 25000, "^SOX": 6500,
                     "^KQ11": 900, "^VIX": 18, "^TNX": 4.3, "KRW=X": 1380}.get(t, 50 + 400 * self.rng.random())
            close = start * np.exp(np.cumsum(r))
            open_ = close * np.exp(self.rng.normal(0, 0.004, n))
            high = np.maximum(open_, close) * (1 + np.abs(self.rng.normal(0, 0.006, n)))
            low = np.minimum(open_, close) * (1 - np.abs(self.rng.normal(0, 0.006, n)))
            vol = self.rng.lognormal(15, 0.3, n)
            vol[-1] *= 1 + 8 * abs(r[-1])
            out[t] = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)
        return out

    def market_caps(self, tickers):
        return {}

    def news(self, ticker, limit=5):
        name = info(ticker)[0]
        return [{"title": f"[데모] {name} 관련 가상 뉴스 헤드라인 {i + 1} — 실제 실행 시 최신 기사로 대체됩니다",
                 "link": "#", "source": "데모", "date": ""} for i in range(3)]


# ---------------------------------------------------------------------------
# 3. 계산
# ---------------------------------------------------------------------------
def pct(a, b):
    try:
        return (a / b - 1) * 100 if b else None
    except Exception:
        return None


def last_change(df: pd.DataFrame, days: int = 1):
    if df is None or len(df) <= days:
        return None
    return pct(df["Close"].iloc[-1], df["Close"].iloc[-1 - days])


def clean(x):
    """JSON 직렬화를 위해 NaN/inf 제거, numpy -> python"""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else round(float(x), 4)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def ohlc_payload(df: pd.DataFrame, days: int, with_ma=True) -> dict:
    d = df.copy()
    if with_ma:
        d["MA20"] = d["Close"].rolling(20).mean()
        d["MA60"] = d["Close"].rolling(60).mean()
    d = d.tail(days)
    p = {"x": [i.strftime("%Y-%m-%d") for i in d.index],
         "o": d["Open"].tolist(), "h": d["High"].tolist(), "l": d["Low"].tolist(),
         "c": d["Close"].tolist(), "v": d["Volume"].tolist()}
    if with_ma:
        p["ma20"] = d["MA20"].tolist()
        p["ma60"] = d["MA60"].tolist()
    return p


def stock_stats(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 25:
        return None
    c, v = df["Close"], df["Volume"]
    rets = c.pct_change()
    r1 = rets.iloc[-1] * 100
    sigma = rets.iloc[-21:-1].std() * 100
    z = r1 / sigma if sigma and sigma > 0 else 0.0
    vavg = v.iloc[-21:-1].mean()
    vr = (v.iloc[-1] / vavg) if vavg and vavg > 0 else 1.0
    hi52, lo52 = c.tail(252).max(), c.tail(252).min()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    return {
        "close": c.iloc[-1], "r1": r1, "r5": last_change(df, 5), "r20": last_change(df, 20),
        "sigma": sigma, "z": z, "vr": vr,
        "at_hi52": c.iloc[-1] >= hi52 * 0.995, "at_lo52": c.iloc[-1] <= lo52 * 1.005,
        "cross_ma20_up": c.iloc[-2] < ma20.iloc[-2] and c.iloc[-1] > ma20.iloc[-1],
        "cross_ma20_dn": c.iloc[-2] > ma20.iloc[-2] and c.iloc[-1] < ma20.iloc[-1],
        "above_ma60": bool(len(c) > 60 and c.iloc[-1] > ma60.iloc[-1]),
        "score": abs(z) * math.sqrt(max(vr, 0.3)),
    }


def selection_reason(t: str, s: dict) -> list[str]:
    reasons = [f"전일 {s['r1']:+.2f}% — 최근 20일 평균 변동폭(±{s['sigma']:.2f}%)의 {abs(s['z']):.1f}배 움직임"]
    if s["vr"] >= 1.5:
        reasons.append(f"거래량이 20일 평균의 {s['vr']:.1f}배로 급증")
    if s["at_hi52"]:
        reasons.append("52주 신고가 부근")
    if s["at_lo52"]:
        reasons.append("52주 신저가 부근")
    if s["cross_ma20_up"]:
        reasons.append("20일 이동평균선 상향 돌파")
    if s["cross_ma20_dn"]:
        reasons.append("20일 이동평균선 하향 이탈")
    return reasons


def related_tickers(t: str, universe: list[str], limit: int = 5) -> list[str]:
    _, sector, _, mkt = info(t)
    links = list(CROSS_LINKS.get(t, []))
    links += [k for k, v in CROSS_LINKS.items() if t in v and k not in links]
    same = [u for u in universe if u != t and info(u)[1] == sector and info(u)[3] == mkt]
    # 같은 섹터는 시총 큰 순
    same.sort(key=lambda u: -info(u)[2])
    out = []
    for u in links + same:
        if u != t and u not in out and u in universe:
            out.append(u)
    return out[:limit]


def correlation(a: pd.DataFrame, b: pd.DataFrame, cross: bool, a_mkt: str) -> float | None:
    """60거래일 일간수익률 상관. 한·미 교차 시 미국(t-1일) → 한국(t일) 시차 반영."""
    ra = a["Close"].pct_change().rename("a")
    rb = b["Close"].pct_change().rename("b")
    if cross:
        us, kr = (ra, rb) if a_mkt == "US" else (rb, ra)
        us = us.copy()
        us.index = us.index + pd.offsets.BDay(1)  # 미국 t일 종가가 한국 t+1일 장에 반영
        j = pd.concat([us, kr], axis=1, join="inner").dropna().tail(60)
    else:
        j = pd.concat([ra, rb], axis=1, join="inner").dropna().tail(60)
    if len(j) < 20:
        return None
    return float(j.iloc[:, 0].corr(j.iloc[:, 1]))


def peer_analysis(t: str, hist: dict, universe: list[str]) -> dict:
    name, sector, _, mkt = info(t)
    base = hist[t]
    s0 = stock_stats(base)
    rows = []
    for p in related_tickers(t, [u for u in universe if u in hist]):
        sp = stock_stats(hist[p])
        if not sp:
            continue
        pm = info(p)[3]
        cross = pm != mkt
        corr = correlation(base, hist[p], cross, mkt)
        same_dir = (sp["r1"] >= 0) == (s0["r1"] >= 0)
        rows.append({
            "ticker": p, "name": info(p)[0], "sector": info(p)[1], "market": pm,
            "r1": sp["r1"], "r5": sp["r5"], "r20": sp["r20"], "corr": corr, "cross": cross,
            "same_dir": same_dir,
        })
    # 정규화 성과(1개월, 100 기준)
    perf = {}
    for tk in [t] + [r["ticker"] for r in rows]:
        c = hist[tk]["Close"].tail(22)
        perf[tk] = {"name": info(tk)[0], "x": [i.strftime("%Y-%m-%d") for i in c.index],
                    "y": (c / c.iloc[0] * 100).tolist()}

    # 규칙 기반 해석
    notes = []
    if rows:
        same_cnt = sum(r["same_dir"] for r in rows)
        dir_word = "상승" if s0["r1"] >= 0 else "하락"
        if same_cnt >= len(rows) * 0.7:
            notes.append(f"관련주 {len(rows)}개 중 {same_cnt}개가 같은 방향({dir_word})으로 움직여 "
                         f"<b>개별 이슈보다 업종·테마 전반의 흐름</b>일 가능성이 큽니다.")
        elif same_cnt <= len(rows) * 0.3:
            notes.append(f"관련주 대부분이 반대로 움직여 <b>{html.escape(name)} 고유의 재료(실적·공시·뉴스)</b>에 "
                         f"따른 움직임으로 보입니다.")
        else:
            notes.append(f"관련주 {len(rows)}개 중 {same_cnt}개만 같은 방향 — 테마 내에서도 종목별 차별화가 나타납니다.")
        with_corr = [r for r in rows if r["corr"] is not None]
        if with_corr:
            top = max(with_corr, key=lambda r: r["corr"])
            lag = " (미국 전일 → 한국 익일 시차 기준)" if top["cross"] else ""
            notes.append(f"최근 60거래일 기준 가장 같이 움직인 종목은 <b>{html.escape(top['name'])}</b>"
                         f"(상관계수 {top['corr']:.2f}{lag})입니다.")
            cross_rows = [r for r in with_corr if r["cross"] and r["corr"] >= 0.3]
            if cross_rows and mkt == "US":
                names = ", ".join(html.escape(r["name"]) for r in cross_rows[:3])
                notes.append(f"한국 연관주({names})는 이 종목의 전일 움직임을 다음 날 따라가는 경향이 있어 "
                             f"오늘 국내 장에서 주목할 만합니다.")
        avg20 = np.nanmean([r["r20"] for r in rows if r["r20"] is not None]) if rows else None
        if avg20 is not None and s0["r20"] is not None and not math.isnan(avg20):
            gap = s0["r20"] - avg20
            word = "강한" if gap > 0 else "약한"
            notes.append(f"1개월 수익률 {s0['r20']:+.1f}% vs 관련주 평균 {avg20:+.1f}% → 상대적으로 "
                         f"<b>{word}</b> 흐름({gap:+.1f}%p).")
        div = [r for r in rows if not r["same_dir"] and abs(r["r1"]) >= 1.0]
        if div:
            names = ", ".join(f"{html.escape(r['name'])}({r['r1']:+.1f}%)" for r in div[:3])
            notes.append(f"반대 방향으로 1% 이상 움직인 종목: {names} — 디커플링 여부를 확인하세요.")
    return {"rows": rows, "perf": perf, "notes": notes}


def weighted_sector(universe: dict, hist: dict, caps: dict) -> list[dict]:
    agg: dict[str, list] = {}
    for t, (n, sec, w) in universe.items():
        if t in hist:
            r = last_change(hist[t], 1)
            if r is None:
                continue
            cap = caps.get(t) or w
            agg.setdefault(sec, []).append((r, cap))
    out = []
    for sec, lst in agg.items():
        tw = sum(c for _, c in lst)
        out.append({"sector": sec, "r1": sum(r * c for r, c in lst) / tw if tw else 0, "n": len(lst)})
    return sorted(out, key=lambda x: -x["r1"])


def treemap_payload(universe: dict, hist: dict, caps: dict, root: str) -> dict:
    ids, labels, parents, values, colors, texts = [root], [root], [""], [0], [None], [""]
    sectors = {}
    for t, (n, sec, w) in universe.items():
        if t not in hist:
            continue
        r = last_change(hist[t], 1)
        if r is None:
            continue
        cap = caps.get(t) or w
        sectors.setdefault(sec, []).append((t, n, r, cap))
    for sec, lst in sectors.items():
        tw = sum(c for *_, c in lst)
        sr = sum(r * c for _, _, r, c in lst) / tw if tw else 0
        sid = f"{root}/{sec}"
        ids.append(sid); labels.append(sec); parents.append(root); values.append(0)
        colors.append(sr); texts.append(f"{sr:+.2f}%")
        for t, n, r, c in lst:
            ids.append(f"{sid}/{t}"); labels.append(n); parents.append(sid)
            values.append(c); colors.append(r); texts.append(f"{r:+.2f}%")
    return {"ids": ids, "labels": labels, "parents": parents, "values": values,
            "colors": colors, "texts": texts}


def market_summary(idx_rows: list[dict], us_sec: list[dict], kr_sec: list[dict]) -> list[str]:
    s = []
    m = {r["ticker"]: r for r in idx_rows}
    if "^IXIC" in m and m["^IXIC"]["r1"] is not None:
        r = m["^IXIC"]
        s.append(f"나스닥은 전일 <b>{r['r1']:+.2f}%</b> {'상승' if r['r1'] >= 0 else '하락'}한 "
                 f"{r['close']:,.2f}에 마감했습니다(1개월 {r['r20']:+.1f}%).")
    if "^KS11" in m and m["^KS11"]["r1"] is not None:
        r = m["^KS11"]
        s.append(f"코스피는 직전 거래일 <b>{r['r1']:+.2f}%</b> 움직인 {r['close']:,.2f}입니다(1개월 {r['r20']:+.1f}%).")
    if us_sec:
        up = sum(1 for x in us_sec if x["r1"] > 0)
        s.append(f"미국 11개 섹터 중 {up}개 상승 — 최강 <b>{us_sec[0]['sector']}</b>({us_sec[0]['r1']:+.2f}%), "
                 f"최약 <b>{us_sec[-1]['sector']}</b>({us_sec[-1]['r1']:+.2f}%).")
    if kr_sec:
        s.append(f"국내 대형주 업종은 <b>{kr_sec[0]['sector']}</b>({kr_sec[0]['r1']:+.2f}%)이 가장 강했고 "
                 f"<b>{kr_sec[-1]['sector']}</b>({kr_sec[-1]['r1']:+.2f}%)이 가장 약했습니다.")
    for t, label in (("^VIX", "VIX"), ("KRW=X", "원/달러")):
        if t in m and m[t]["r1"] is not None:
            s.append(f"{label} {m[t]['close']:,.2f} ({m[t]['r1']:+.2f}%)")
    return s


# ---------------------------------------------------------------------------
# 4. (선택) LLM 요약 — ANTHROPIC_API_KEY 가 있을 때만
# ---------------------------------------------------------------------------
def llm_comment(stock: dict) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or requests is None:
        return None
    heads = "\n".join(f"- {n['title']} ({n['source']})" for n in stock["news"][:6])
    prompt = (f"종목: {stock['name']}({stock['ticker']}), 전일 등락 {stock['stats']['r1']:+.2f}%, "
              f"거래량 {stock['stats']['vr']:.1f}배.\n최신 헤드라인:\n{heads}\n\n"
              "헤드라인만 근거로, 이 종목이 움직인 가장 그럴듯한 이유를 한국어 2문장 이내로 요약하세요. "
              "헤드라인에 근거가 없으면 '뉴스상 뚜렷한 재료 없음'이라고 쓰세요. 투자 권유 표현은 쓰지 마세요.")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("BRIEF_LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": 300,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", [])).strip() or None
    except Exception as e:
        log(f"LLM 요약 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 5. 조립
# ---------------------------------------------------------------------------
def build(source, top_n: int = 3, watch: list[str] | None = None, news_on: bool = True, demo=False) -> dict:
    watch = watch or []
    all_idx = list(MAIN_INDICES) + list(SUB_INDICES)
    stocks = list(US_UNIVERSE) + list(KR_UNIVERSE) + [w for w in watch if w not in US_UNIVERSE and w not in KR_UNIVERSE]
    log(f"시세 수집: 지수 {len(all_idx)}, 섹터 ETF {len(US_SECTOR_ETF)}, 종목 {len(stocks)}")
    hist = source.history(all_idx + list(US_SECTOR_ETF) + stocks, period="1y")
    log("시가총액 조회")
    caps = source.market_caps([s for s in stocks if s in hist])

    # (1) 지수
    idx_rows = []
    for t in all_idx:
        if t in hist:
            df = hist[t]
            idx_rows.append({"ticker": t, "name": {**MAIN_INDICES, **SUB_INDICES}[t], "close": df["Close"].iloc[-1],
                             "r1": last_change(df, 1), "r5": last_change(df, 5), "r20": last_change(df, 20),
                             "date": df.index[-1].strftime("%m/%d"),
                             "spark": df["Close"].tail(30).tolist()})
    main_charts = {t: {"name": n, **ohlc_payload(hist[t], 130)} for t, n in MAIN_INDICES.items() if t in hist}

    # (2) 섹터
    us_etf = sorted([{"sector": n, "ticker": t, "r1": last_change(hist[t], 1), "r5": last_change(hist[t], 5)}
                     for t, n in US_SECTOR_ETF.items() if t in hist and last_change(hist[t], 1) is not None],
                    key=lambda x: -x["r1"])
    kr_sec = weighted_sector(KR_UNIVERSE, hist, caps)
    us_sec_w = weighted_sector(US_UNIVERSE, hist, caps)
    treemaps = {"US": treemap_payload(US_UNIVERSE, hist, caps, "미국 대형주"),
                "KR": treemap_payload(KR_UNIVERSE, hist, caps, "코스피 대형주")}

    # (3) 주요 종목 선정
    scored = []
    for t in stocks:
        s = stock_stats(hist.get(t))
        if s:
            scored.append((t, s))
    picks: list[str] = []
    for mkt in ("US", "KR"):
        cand = sorted([x for x in scored if info(x[0])[3] == mkt], key=lambda x: -x[1]["score"])
        picks += [t for t, _ in cand[:top_n]]
    picks += [w for w in watch if w in hist and w not in picks]
    stat_map = dict(scored)
    universe_all = [t for t in stocks if t in hist]

    key_stocks = []
    for t in picks:
        name, sector, _, mkt = info(t)
        s = stat_map[t]
        log(f"주요 종목: {name} ({t}) {s['r1']:+.2f}%")
        item = {"ticker": t, "name": name, "sector": sector, "market": mkt, "stats": s,
                "reasons": selection_reason(t, s) + (["관심종목(--watch)"] if t in watch else []),
                "chart": ohlc_payload(hist[t], 65),
                "news": source.news(t) if news_on else [],
                "peers": peer_analysis(t, hist, universe_all)}
        item["llm"] = llm_comment(item) if news_on and not demo else None
        key_stocks.append(item)

    asof_us = hist["^IXIC"].index[-1].strftime("%Y-%m-%d") if "^IXIC" in hist else "-"
    asof_kr = hist["^KS11"].index[-1].strftime("%Y-%m-%d") if "^KS11" in hist else "-"
    return clean({
        "generated": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "asof_us": asof_us, "asof_kr": asof_kr, "demo": demo,
        "summary": market_summary(idx_rows, us_etf, kr_sec),
        "indices": idx_rows, "main_charts": main_charts,
        "us_etf": us_etf, "kr_sector": kr_sec, "us_sector_w": us_sec_w, "treemaps": treemaps,
        "key_stocks": key_stocks,
    })


# ---------------------------------------------------------------------------
# 6. HTML 렌더링
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>모닝 마켓 브리핑 · __DATE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{
  --surface-0:#f4f3f0; --surface-1:#fcfcfb; --border:#e3e2dd;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#85847f; --grid:#ebeae6;
  --up:#d63b3a; --up-soft:#fbe4e3; --down:#2a6fd0; --down-soft:#e1ecfb; --neutral:#f0efec;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300; --s7:#6250d6;
  --accent:#2a78d6;
}
@media (prefers-color-scheme: dark){
  :root{
    --surface-0:#121211; --surface-1:#1a1a19; --border:#2e2e2b;
    --text-primary:#f0efec; --text-secondary:#c3c2b7; --text-muted:#8d8c84; --grid:#2a2a27;
    --up:#ef6463; --up-soft:#3a1f1e; --down:#5598e7; --down-soft:#1a2a40; --neutral:#383835;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
  font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR","Malgun Gothic",sans-serif;
  line-height:1.55;font-size:15px}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
header h1{font-size:24px;margin:0 0 4px;letter-spacing:-.3px}
header .meta{color:var(--text-secondary);font-size:13px}
.demo-banner{background:#fff4d6;color:#5a4300;border:1px solid #f0d27a;padding:10px 14px;border-radius:10px;margin:14px 0;font-size:14px}
nav{position:sticky;top:0;z-index:5;background:var(--surface-0);padding:10px 0;margin:8px 0 6px;
  display:flex;gap:6px;overflow-x:auto;border-bottom:1px solid var(--border)}
nav a{white-space:nowrap;text-decoration:none;color:var(--text-secondary);font-size:13px;padding:6px 10px;border-radius:999px;border:1px solid var(--border);background:var(--surface-1)}
nav a:hover{color:var(--text-primary)}
section{margin-top:28px}
h2{font-size:19px;margin:0 0 12px;letter-spacing:-.2px}
h2 .num{color:var(--accent);margin-right:6px}
h3{font-size:16px;margin:0 0 6px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:16px}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr))}
.tiles{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));margin-bottom:14px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:10px 12px}
.tile .lab{font-size:12px;color:var(--text-secondary)}
.tile .val{font-size:18px;font-weight:650;font-variant-numeric:tabular-nums}
.tile .chg{font-size:13px;font-variant-numeric:tabular-nums}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--text-secondary)}
.summary li{margin:3px 0}
.chart{width:100%;height:360px}
.chart.sm{height:300px}
.chart.tm{height:460px}
.chart.bar{height:330px}
table{width:100%;border-collapse:collapse;font-size:13.5px;font-variant-numeric:tabular-nums}
th,td{padding:7px 8px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
th{color:var(--text-secondary);font-weight:600;font-size:12.5px}
th:first-child,td:first-child{text-align:left}
.tbl-wrap{overflow-x:auto}
.pill{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;border:1px solid var(--border);color:var(--text-secondary);margin-right:4px}
.stock{margin-bottom:18px}
.stock-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin-bottom:8px}
.stock-head .px{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums}
.reasons{margin:6px 0 10px;padding-left:18px}
.reasons li{margin:2px 0}
.news{list-style:none;margin:0;padding:0}
.news li{padding:8px 0;border-bottom:1px solid var(--border)}
.news li:last-child{border-bottom:none}
.news a{color:var(--text-primary);text-decoration:none}
.news a:hover{text-decoration:underline}
.news .src{color:var(--text-muted);font-size:12px;margin-left:6px}
.llm{background:var(--neutral);border-radius:10px;padding:10px 12px;margin:8px 0;font-size:14px}
.notes{margin:8px 0 0;padding-left:18px}
.notes li{margin:4px 0}
.muted{color:var(--text-muted);font-size:12.5px}
.legend-note{font-size:12.5px;color:var(--text-secondary);margin:6px 0 0}
footer{margin-top:40px;color:var(--text-muted);font-size:12px}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>모닝 마켓 브리핑</h1>
  <div class="meta">생성 __GENERATED__ · 미국 기준일 __ASOF_US__ · 한국 기준일 __ASOF_KR__ · 색상: <span class="up">상승=빨강</span> / <span class="down">하락=파랑</span></div>
</header>
__DEMO__
<nav>
  <a href="#s1">① 지수</a><a href="#s2">② 섹터 히트맵</a><a href="#s3">③ 주요 종목 차트</a>
  <a href="#s4">④ 선정 이유·뉴스</a><a href="#s5">⑤ 연관 종목 분석</a>
</nav>

<section id="s1">
  <h2><span class="num">①</span>나스닥 · 코스피 주요 지수</h2>
  <div class="card" style="margin-bottom:14px"><ul class="summary" id="summary" style="margin:0;padding-left:18px"></ul></div>
  <div class="tiles" id="tiles"></div>
  <div class="grid g2" id="idx-charts"></div>
</section>

<section id="s2">
  <h2><span class="num">②</span>주요 섹터별 히트맵</h2>
  <div class="grid g2">
    <div class="card"><h3>미국 대형주 (S&amp;P 섹터별, 면적=시가총액)</h3><div id="tm-US" class="chart tm"></div></div>
    <div class="card"><h3>코스피 대형주 (업종별, 면적=시가총액)</h3><div id="tm-KR" class="chart tm"></div></div>
    <div class="card"><h3>미국 섹터 ETF 전일 등락</h3><div id="bar-US" class="chart bar"></div></div>
    <div class="card"><h3>국내 업종(대형주 시총가중) 전일 등락</h3><div id="bar-KR" class="chart bar"></div></div>
  </div>
  <p class="legend-note">히트맵 색: 진한 빨강 = 큰 상승, 회색 = 보합, 진한 파랑 = 큰 하락 (±3%에서 최대 농도). 타일에 마우스를 올리면 수치가 표시됩니다.</p>
</section>

<section id="s3">
  <h2><span class="num">③</span>주요 종목 차트</h2>
  <p class="muted">선정 기준: 전일 등락률을 최근 20일 평균 변동폭으로 나눈 '이상 움직임 점수'에 거래량 급증 정도를 곱해 미국·한국 각각 상위 종목 자동 선정</p>
  <div class="grid g2" id="stock-charts"></div>
</section>

<section id="s4">
  <h2><span class="num">④</span>주요 종목 선정 이유와 최신 뉴스</h2>
  <div id="stock-news"></div>
</section>

<section id="s5">
  <h2><span class="num">⑤</span>연관 종목 포함 분석</h2>
  <div id="peers"></div>
</section>

<footer>
  데이터: Yahoo Finance(yfinance), 뉴스: Google News RSS. 자동 생성된 참고 자료이며 투자 권유가 아닙니다.
  지연·누락된 데이터가 있을 수 있으니 중요한 결정 전에는 원 출처를 확인하세요. · market_brief.py
</footer>
</div>

<script>
const D = __DATA__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = {up:css('--up'), down:css('--down'), text:css('--text-primary'), sub:css('--text-secondary'),
  muted:css('--text-muted'), grid:css('--grid'), surf:css('--surface-1'), neutral:css('--neutral'),
  s:[css('--s1'),css('--s2'),css('--s3'),css('--s4'),css('--s5'),css('--s6'),css('--s7')]};
const fmt = (v,d=2) => v==null ? '–' : Number(v).toLocaleString('ko-KR',{minimumFractionDigits:d,maximumFractionDigits:d});
const sgn = (v,d=2) => v==null ? '–' : (v>0?'+':'')+fmt(v,d)+'%';
const cls = v => v==null||Math.abs(v)<0.005 ? 'flat' : (v>0?'up':'down');
const esc = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cfg = {displayModeBar:false, responsive:true};
const baseLayout = (extra={}) => Object.assign({
  paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
  font:{family:getComputedStyle(document.body).fontFamily, color:C.sub, size:12},
  margin:{l:52,r:14,t:10,b:30}, showlegend:false, hovermode:'x unified',
  hoverlabel:{bgcolor:C.surf, bordercolor:C.grid, font:{color:C.text}},
  xaxis:{gridcolor:C.grid, linecolor:C.grid, zeroline:false, rangeslider:{visible:false}, showspikes:true, spikecolor:C.muted, spikethickness:1, spikedash:'dot'},
  yaxis:{gridcolor:C.grid, linecolor:C.grid, zeroline:false, side:'right', tickformat:',.0f'}
}, extra);
// 한국식 다이버징 색: 파랑(하락) - 회색(0) - 빨강(상승)
const DIV = [[0,'#1c5cab'],[0.25,'#6da7ec'],[0.5,C.neutral],[0.75,'#f08a89'],[1,'#c22f2e']];

// ---------- ① 지수 ----------
document.getElementById('summary').innerHTML = D.summary.map(s=>`<li>${s}</li>`).join('');
document.getElementById('tiles').innerHTML = D.indices.map(r=>`
  <div class="tile"><div class="lab">${esc(r.name)} <span class="muted">${r.date}</span></div>
  <div class="val">${fmt(r.close, r.close>1000?2:2)}</div>
  <div class="chg ${cls(r.r1)}">${sgn(r.r1)} <span class="muted">5일 ${sgn(r.r5,1)} · 1개월 ${sgn(r.r20,1)}</span></div></div>`).join('');

function candle(el, p, height){
  const traces = [
    {type:'candlestick', x:p.x, open:p.o, high:p.h, low:p.l, close:p.c, name:'가격',
     increasing:{line:{color:C.up,width:1}, fillcolor:C.up}, decreasing:{line:{color:C.down,width:1}, fillcolor:C.down}},
  ];
  if(p.ma20) traces.push({type:'scatter', mode:'lines', x:p.x, y:p.ma20, name:'20일선', line:{color:C.s[3],width:1.5}, hovertemplate:'%{y:,.2f}'});
  if(p.ma60) traces.push({type:'scatter', mode:'lines', x:p.x, y:p.ma60, name:'60일선', line:{color:C.s[6],width:1.5}, hovertemplate:'%{y:,.2f}'});
  return traces;
}
const idxWrap = document.getElementById('idx-charts');
Object.entries(D.main_charts).forEach(([t,p],i)=>{
  const r = D.indices.find(x=>x.ticker===t)||{};
  const div = document.createElement('div'); div.className='card';
  div.innerHTML = `<h3>${esc(p.name)} <span class="${cls(r.r1)}" style="font-size:14px">${fmt(r.close)} (${sgn(r.r1)})</span></h3>
    <div id="idx-${i}" class="chart"></div>
    <div class="legend-note"><span style="color:${C.s[3]}">━</span> 20일 이동평균 &nbsp; <span style="color:${C.s[6]}">━</span> 60일 이동평균 · 최근 6개월 일봉</div>`;
  idxWrap.appendChild(div);
  Plotly.newPlot(`idx-${i}`, candle(null,p), baseLayout({yaxis:{gridcolor:C.grid,side:'right',tickformat:',.0f'}}), cfg);
});

// ---------- ② 섹터 히트맵 ----------
['US','KR'].forEach(m=>{
  const t = D.treemaps[m];
  Plotly.newPlot(`tm-${m}`, [{
    type:'treemap', ids:t.ids, labels:t.labels, parents:t.parents, values:t.values, branchvalues:'remainder',
    text:t.texts, textinfo:'label+text', hovertemplate:'<b>%{label}</b><br>%{text}<extra></extra>',
    marker:{colors:t.colors.map(v=>v==null?0:v), colorscale:DIV, cmin:-3, cmax:3, cmid:0,
            line:{color:C.surf,width:2}, pad:{t:22,l:2,r:2,b:2}},
    tiling:{pad:2}, pathbar:{visible:false}, root:{color:C.surf},
    textfont:{size:13}, insidetextfont:{size:13}, maxdepth:3
  }], {margin:{l:0,r:0,t:0,b:0}, paper_bgcolor:'rgba(0,0,0,0)',
       font:{family:getComputedStyle(document.body).fontFamily}}, cfg);
});
function sectorBar(el, rows){
  const r = [...rows].reverse();
  Plotly.newPlot(el, [{type:'bar', orientation:'h', y:r.map(x=>x.sector), x:r.map(x=>x.r1),
    marker:{color:r.map(x=>x.r1>=0?C.up:C.down)}, text:r.map(x=>sgn(x.r1)), textposition:'outside',
    cliponaxis:false, textfont:{color:C.sub,size:11}, hovertemplate:'%{y}: %{x:+.2f}%<extra></extra>', width:0.6}],
    baseLayout({hovermode:'closest', margin:{l:96,r:46,t:6,b:24},
      xaxis:{gridcolor:C.grid, zeroline:true, zerolinecolor:C.muted, ticksuffix:'%'},
      yaxis:{automargin:true, gridcolor:'rgba(0,0,0,0)'}, bargap:0.35}), cfg);
}
sectorBar('bar-US', D.us_etf); sectorBar('bar-KR', D.kr_sector);

// ---------- ③ 주요 종목 차트 ----------
const sc = document.getElementById('stock-charts');
D.key_stocks.forEach((k,i)=>{
  const div = document.createElement('div'); div.className='card';
  const flag = k.market==='US' ? '🇺🇸' : '🇰🇷';
  div.innerHTML = `<h3>${flag} ${esc(k.name)} <span class="muted">${esc(k.ticker)} · ${esc(k.sector)}</span></h3>
    <div class="${cls(k.stats.r1)}" style="font-variant-numeric:tabular-nums">${fmt(k.stats.close)} &nbsp;${sgn(k.stats.r1)} <span class="muted">· 거래량 ${fmt(k.stats.vr,1)}배</span></div>
    <div id="sc-${i}" class="chart sm"></div>`;
  sc.appendChild(div);
  const p = k.chart;
  const vcol = p.c.map((c,j)=> c >= p.o[j] ? C.up : C.down);
  const tr = candle(null,p);
  tr.forEach(t=>{t.yaxis='y';});
  tr.push({type:'bar', x:p.x, y:p.v, yaxis:'y2', marker:{color:vcol, opacity:0.45}, name:'거래량', hovertemplate:'%{y:,.0f}'});
  Plotly.newPlot(`sc-${i}`, tr, baseLayout({
    yaxis:{domain:[0.28,1], gridcolor:C.grid, side:'right', tickformat:',.0f'},
    yaxis2:{domain:[0,0.2], gridcolor:C.grid, side:'right', tickformat:'.2s', showgrid:false},
    margin:{l:10,r:52,t:6,b:26}}), cfg);
});

// ---------- ④ 선정 이유 · 뉴스 ----------
document.getElementById('stock-news').innerHTML = D.key_stocks.map(k=>`
  <div class="card stock">
    <div class="stock-head"><h3 style="margin:0">${esc(k.name)}</h3>
      <span class="pill">${esc(k.ticker)}</span><span class="pill">${esc(k.sector)}</span>
      <span class="px ${cls(k.stats.r1)}">${sgn(k.stats.r1)}</span></div>
    <b style="font-size:13.5px">선정 이유</b>
    <ul class="reasons">${k.reasons.map(r=>`<li>${esc(r)}</li>`).join('')}
      <li>5일 ${sgn(k.stats.r5,1)} · 1개월 ${sgn(k.stats.r20,1)} · 60일선 ${k.stats.above_ma60?'위':'아래'}</li></ul>
    ${k.llm ? `<div class="llm"><b>뉴스 요약</b> · ${esc(k.llm)}</div>` : ''}
    <b style="font-size:13.5px">관련 최신 뉴스</b>
    ${k.news.length ? `<ul class="news">${k.news.map(n=>`<li><a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>
      <span class="src">${esc(n.source)} ${esc(n.date)}</span></li>`).join('')}</ul>` : '<p class="muted">최근 3일 내 검색된 뉴스가 없습니다.</p>'}
  </div>`).join('');

// ---------- ⑤ 연관 종목 ----------
const pw = document.getElementById('peers');
D.key_stocks.forEach((k,i)=>{
  const P = k.peers;
  const div = document.createElement('div'); div.className='card stock';
  const rows = P.rows.map(r=>`<tr><td>${r.market==='US'?'🇺🇸':'🇰🇷'} ${esc(r.name)} <span class="muted">${esc(r.sector)}</span></td>
    <td class="${cls(r.r1)}">${sgn(r.r1)}</td><td class="${cls(r.r5)}">${sgn(r.r5,1)}</td><td class="${cls(r.r20)}">${sgn(r.r20,1)}</td>
    <td>${r.corr==null?'–':fmt(r.corr,2)}${r.cross?' <span class="muted">시차</span>':''}</td></tr>`).join('');
  div.innerHTML = `<h3>${esc(k.name)}와(과) 연관 종목</h3>
    <div class="grid g2">
      <div><div id="pf-${i}" class="chart sm"></div>
        <div class="legend-note" id="pl-${i}"></div></div>
      <div class="tbl-wrap"><table><thead><tr><th>종목</th><th>전일</th><th>5일</th><th>1개월</th><th>상관(60일)</th></tr></thead>
        <tbody><tr style="font-weight:650"><td>★ ${esc(k.name)}</td><td class="${cls(k.stats.r1)}">${sgn(k.stats.r1)}</td>
        <td class="${cls(k.stats.r5)}">${sgn(k.stats.r5,1)}</td><td class="${cls(k.stats.r20)}">${sgn(k.stats.r20,1)}</td><td>1.00</td></tr>${rows}</tbody></table>
        <p class="muted" style="margin:6px 0 0">시차: 한·미 교차 종목은 미국 전일 수익률과 한국 익일 수익률로 계산</p></div>
    </div>
    <b style="font-size:13.5px;display:block;margin-top:10px">분석</b>
    <ul class="notes">${P.notes.map(n=>`<li>${n}</li>`).join('') || '<li class="muted">연관 종목 데이터가 부족합니다.</li>'}</ul>`;
  pw.appendChild(div);
  const keys = Object.keys(P.perf);
  const tr = keys.map((t,j)=>({type:'scatter', mode:'lines', x:P.perf[t].x, y:P.perf[t].y, name:P.perf[t].name,
     line:{color:C.s[j % C.s.length], width: j===0?3:1.6}, opacity: j===0?1:0.85,
     hovertemplate:'%{y:.1f}'}));
  Plotly.newPlot(`pf-${i}`, tr, baseLayout({yaxis:{gridcolor:C.grid, side:'right', tickformat:'.0f'},
    shapes:[{type:'line', xref:'paper', x0:0, x1:1, y0:100, y1:100, line:{color:C.muted, width:1, dash:'dot'}}]}), cfg);
  document.getElementById(`pl-${i}`).innerHTML = '최근 1개월 성과(시작=100): ' + keys.map((t,j)=>
    `<span style="color:${C.s[j % C.s.length]}">━</span> ${esc(P.perf[t].name)}`).join(' &nbsp;');
});
</script>
</body>
</html>
"""


def render(data: dict) -> str:
    demo = ('<div class="demo-banner"><b>데모 모드</b> — 인터넷 없이 만든 <b>가상 데이터</b>입니다. '
            '실제 시세·뉴스가 아니며 레이아웃 확인용입니다. 실제 브리핑은 --demo 없이 실행하세요.</div>'
            if data.get("demo") else "")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (HTML_TEMPLATE
            .replace("__DATA__", payload)
            .replace("__DEMO__", demo)
            .replace("__DATE__", data["generated"][:10])
            .replace("__GENERATED__", html.escape(data["generated"]))
            .replace("__ASOF_US__", data["asof_us"])
            .replace("__ASOF_KR__", data["asof_kr"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="모닝 마켓 브리핑 HTML 생성기")
    ap.add_argument("--outdir", default="output", help="결과 저장 폴더 (예: 구글 드라이브 동기화 폴더)")
    ap.add_argument("--top", type=int, default=3, help="시장별 주요 종목 수 (기본 3)")
    ap.add_argument("--watch", nargs="*", default=[], help="항상 포함할 관심 종목 티커 (예: NVDA 005930.KS)")
    ap.add_argument("--no-news", action="store_true", help="뉴스 수집 생략")
    ap.add_argument("--demo", action="store_true", help="인터넷 없이 가상 데이터로 생성(레이아웃 확인용)")
    ap.add_argument("--json", action="store_true", help="원자료 JSON도 함께 저장")
    ap.add_argument("--no-pdf", action="store_true", help="PDF 생성 생략")
    ap.add_argument("--github-repo", default=None,
                    help="GitHub Pages 저장소(reports)의 로컬 클론 경로. 지정하면 <저장소>/<--github-path>/ 에 게시 후 push")
    ap.add_argument("--github-path", default="daily_market-brief", help="저장소 안 게시 폴더명 (기본 daily_market-brief)")
    ap.add_argument("--force", action="store_true", help="주말·휴장일에도 강제로 생성")
    ap.add_argument("--layout", choices=["drive", "site"], default="drive",
                    help="drive: latest + 월별 폴더(구글 드라이브용) / site: GitHub Pages용(index.html, latest.pdf, latest.json, archive/)")
    ap.add_argument("--keep-days", type=int, default=365, help="site 모드에서 archive 보관 기간(일)")
    args = ap.parse_args(argv)

    now = dt.datetime.now(KST)
    outdir = Path(os.path.expanduser(args.outdir))
    if now.weekday() >= 5 and not (args.force or args.demo):
        log("주말이라 건너뜁니다 (--force 로 강제 실행)")
        return

    source = DemoSource() if args.demo else LiveSource()
    data = build(source, top_n=args.top, watch=args.watch, news_on=not args.no_news, demo=args.demo)

    # 한·미 모두 휴장이어서 직전 리포트와 기준일이 같으면 건너뜀
    state = outdir / ".last_asof.json"
    asof = {"us": data["asof_us"], "kr": data["asof_kr"]}
    if not (args.force or args.demo) and state.exists():
        try:
            if json.loads(state.read_text(encoding="utf-8")) == asof:
                log(f"한·미 모두 새 거래일 데이터가 없어 건너뜁니다 (기준일 {asof})")
                return
        except Exception:
            pass

    suffix = "_demo" if args.demo else ""
    page = render(data)
    if args.layout == "site":
        dated = save_site(outdir, data, page, now, suffix, not args.no_pdf, args.keep_days)
    else:
        dated = save_drive(outdir, data, page, now, suffix, not args.no_pdf, args.json)
    if not args.demo:
        state.write_text(json.dumps(asof), encoding="utf-8")
    if args.github_repo:
        publish_github(Path(os.path.expanduser(args.github_repo)), args.github_path, page,
                       now.strftime("%Y-%m-%d_") + WEEKDAY[now.weekday()], suffix)
    log(f"완료: {dated}")
    print(dated)


WEEKDAY = "월화수목금토일"


def _pdf(data, path: Path) -> Path | None:
    try:
        from brief_pdf import render_pdf
        out = render_pdf(data, path)
        log(f"PDF: {out}")
        return out
    except Exception as e:  # PDF 실패해도 HTML은 유지
        log(f"PDF 생성 실패: {e}")
        return None


def save_drive(outdir: Path, data, page, now, suffix, pdf_on, json_on) -> Path:
    """outdir/latest.(pdf|html) + outdir/YYYY-MM/MMDD_요일.(pdf|html)"""
    import shutil
    month_dir = outdir / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    base = f"{now:%m%d}_{WEEKDAY[now.weekday()]}{suffix}"
    dated = month_dir / f"{base}.html"
    dated.write_text(page, encoding="utf-8")
    (outdir / f"latest{suffix}.html").write_text(page, encoding="utf-8")
    if json_on:
        (month_dir / f"{base}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if pdf_on:
        p = _pdf(data, month_dir / f"{base}.pdf")
        if p:
            shutil.copyfile(p, outdir / f"latest{suffix}.pdf")
    return dated


def save_site(outdir: Path, data, page, now, suffix, pdf_on, keep_days) -> Path:
    """GitHub Pages 용 구조 (outdir = <사이트>/<리포트명>)
         index.html            오늘 웹페이지
         latest.pdf            오늘 PDF 하나만 (아이패드 단축어가 받아 아이클라우드에 저장)
         latest.json           단축어용 정보: 파일명·월 폴더·기준일
         archive/YYYY-MM-DD_요일.html   지난 웹페이지 (keep_days 지나면 삭제)
       상위 폴더(<사이트>)에는 리포트 목록 index.html 을 갱신합니다."""
    wd = WEEKDAY[now.weekday()]
    arch = outdir / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    (outdir / "index.html").write_text(page, encoding="utf-8")
    dated = arch / f"{now:%Y-%m-%d}_{wd}{suffix}.html"
    dated.write_text(page, encoding="utf-8")
    meta = {"date": now.strftime("%Y-%m-%d"), "weekday": wd, "month": now.strftime("%Y-%m"),
            "pdf_name": f"{now:%m%d}_{wd}{suffix}.pdf", "html_name": dated.name,
            "asof_us": data["asof_us"], "asof_kr": data["asof_kr"], "generated": data["generated"],
            "pdf": False}
    if pdf_on and _pdf(data, outdir / "latest.pdf"):
        meta["pdf"] = True
    (outdir / "latest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    # 보관 기간 정리
    cutoff = (now - dt.timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for p in arch.glob("*.html"):
        if p.name != "index.html" and p.name[:10] < cutoff:
            p.unlink()
            log(f"보관 기간 경과 삭제: {p.name}")
    write_indexes(outdir.parent, outdir.name)
    return dated


def write_indexes(site: Path, sub: str) -> None:
    head = ('<!DOCTYPE html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<body style="font-family:-apple-system,sans-serif;padding:20px;line-height:1.8">')
    arch = site / sub / "archive"
    links = sorted((p for p in arch.glob("*.html") if p.name != "index.html"), reverse=True)
    items = "".join(f'<li><a href="{p.name}">{p.stem}</a></li>' for p in links)
    (arch / "index.html").write_text(
        f'{head}<title>{sub} 지난 리포트</title><h2>{sub} · 지난 리포트</h2>'
        f'<p><a href="../">← 최신</a></p><ul>{items}</ul>', encoding="utf-8")
    subs = sorted(d.name for d in site.iterdir() if d.is_dir() and (d / "index.html").exists())
    items = "".join(f'<li><a href="{d}/">{d}</a> · <a href="{d}/archive/">지난 리포트</a></li>' for d in subs)
    (site / "index.html").write_text(f'{head}<title>reports</title><h2>reports</h2><ul>{items}</ul>', encoding="utf-8")
    (site / ".nojekyll").touch()


def publish_github(repo: Path, sub: str, page: str, stamp: str, suffix: str) -> None:
    """GitHub Pages 저장소(로컬 클론)의 <sub>/index.html + <sub>/archive/날짜.html 을 갱신하고 push.
    저장소 루트 index.html 에는 리포트 목록(하위 폴더)을 자동으로 만듭니다."""
    import subprocess
    if not (repo / ".git").exists():
        log(f"GitHub 저장소가 아닙니다: {repo}")
        return
    site = repo / sub
    (site / "archive").mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(page, encoding="utf-8")
    (site / "archive" / f"{stamp}{suffix}.html").write_text(page, encoding="utf-8")
    head = ('<!DOCTYPE html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<body style="font-family:-apple-system,sans-serif;padding:20px;line-height:1.8">')
    links = sorted((p for p in (site / "archive").glob("*.html") if p.name != "index.html"), reverse=True)[:120]
    items = "".join(f'<li><a href="{p.name}">{p.stem}</a></li>' for p in links)
    (site / "archive" / "index.html").write_text(
        f'{head}<title>{sub} 지난 리포트</title><h2>{sub} · 지난 리포트</h2>'
        f'<p><a href="../">← 최신</a></p><ul>{items}</ul>', encoding="utf-8")
    subs = sorted(d.name for d in repo.iterdir() if d.is_dir() and (d / "index.html").exists())
    items = "".join(f'<li><a href="{d}/">{d}</a> · <a href="{d}/archive/">지난 리포트</a></li>' for d in subs)
    (repo / "index.html").write_text(f'{head}<title>reports</title><h2>reports</h2><ul>{items}</ul>', encoding="utf-8")
    try:
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
        git("pull", "--rebase", "--autostash")
        git("add", "-A")
        if subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"]).returncode != 0:
            git("commit", "-m", f"brief {stamp}")
        git("push")
        log("GitHub Pages 업로드 완료")
    except subprocess.CalledProcessError as e:
        log(f"GitHub 업로드 실패: {(e.stderr or e.stdout or '').strip()[:300]}")


if __name__ == "__main__":
    main()
