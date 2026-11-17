"""포트폴리오 대시보드 빌드 — 시장 전체 시세 수집

매매일지(수량·금액)는 다루지 않습니다. 대신 '살 수 있는 거의 모든 종목'의 시세를 받아 두고,
페이지가 사용자가 고른 매매일지에 있는 종목 파일만 골라 읽습니다. → 사용자는 매매일지.csv만 고치면 됩니다.

수집 범위 (상장 목록도 매번 자동 갱신 → 신규 상장 자동 포함)
  - 국내: 코스피·코스닥 전 종목(KIND 상장법인 목록), 국내 ETF 전체(네이버 금융)
  - 미국: NASDAQ·NYSE·NYSE American 상장 보통주와 ETF (나스닥 스크리너, 실패 시 nasdaqtrader 목록)
  - USD/KRW 환율

저장 (data 폴더 → market-data 브랜치, 페이지는 raw.githubusercontent.com 에서 읽음)
  data/<키>.json   종목 하나: 일별 종가(액면분할 조정)·최근 거래량·분할 기록
                   키 = 국내 6자리 코드(005930), 미국은 야후 티커(LRCX, BRK-B)
  data/_fx.json    USD/KRW
  data/_meta.json  수집 시각·종목 수·실패 수
  data/_universe.json  수집 대상 목록 (목록 받기 실패 시 이전 목록 재사용)

방식: 이미 파일이 있는 종목은 최근 7일만 받아 이어 붙이고(빠름),
      파일이 없는 종목(첫 실행·신규 상장)과 최근 분할이 생긴 종목은 2년치를 새로 받습니다(실행당 상한 있음).

사용: python build.py --data _data/data --site _site/daily_portfolio-dashboard [--backfill 4000]
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json, text/plain, */*", "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
HIST_DAYS = 760          # 보관하는 일별 종가 기간(약 2년)
SEED = ["005930", "000660", "LRCX", "SNDK"]   # 샘플 매매일지 종목은 첫 실행부터 바로 채우기


def log(msg: str) -> None:
    print(f"[portfolio] {msg}", flush=True)


def get(url: str, **kw):
    import requests
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=40, **kw)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            if i == 2:
                raise
            log(f"재시도 {url[:70]} ({e})")
            time.sleep(3 * (i + 1))


def sector_ko(text: str) -> str:
    t = (text or "").lower()
    rules = [("반도체", ["반도체", "semiconductor"]), ("2차전지", ["축전지", "2차전지", "battery"]),
             ("자동차", ["자동차", "auto"]), ("바이오·제약", ["의약", "바이오", "pharma", "biotech", "health"]),
             ("금융", ["은행", "보험", "증권", "금융", "bank", "insurance", "financ", "capital market"]),
             ("소프트웨어·인터넷", ["소프트웨어", "software", "internet", "interactive media"]),
             ("IT하드웨어", ["computer", "technology hardware", "electronic", "통신 및 방송", "전자부품", "컴퓨터"]),
             ("에너지", ["석유", "energy", "oil", "gas"]), ("유틸리티", ["utilit", "전기", "가스"]),
             ("소비재", ["consumer", "retail", "식료품", "음료", "의복", "화장품", "소매"]),
             ("산업재", ["industrial", "machinery", "aerospace", "조선", "기계", "건설", "운송"]),
             ("소재", ["material", "chemical", "화학", "철강", "금속"]), ("부동산", ["real estate", "reit", "부동산"]),
             ("통신", ["telecom", "communication"])]
    for ko, keys in rules:
        if any(k in t for k in keys):
            return ko
    return "기타"


# ───────── 1. 수집 대상 목록 ─────────
def list_kr_stocks() -> dict:
    import pandas as pd
    r = get("https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13")
    df = pd.read_html(io.StringIO(r.content.decode("euc-kr", "replace")), header=0)[0]
    out = {}
    for _, x in df.iterrows():
        mk = str(x.get("시장구분", ""))
        suf = "KS" if "유가" in mk else "KQ" if "코스닥" in mk else None
        if not suf:
            continue
        code = str(x["종목코드"]).strip()
        code = code.zfill(6) if code.isdigit() else code.upper()
        out[code] = [f"{code}.{suf}", str(x["회사명"]), sector_ko(str(x.get("업종", ""))), "KRW", 2]
    return out


def list_kr_etfs() -> dict:
    r = get("https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc")
    try:
        js = json.loads(r.content.decode("euc-kr"))
    except Exception:  # noqa: BLE001
        js = r.json()
    out = {}
    for it in js["result"]["etfItemList"]:
        code = str(it["itemcode"]).strip().upper()
        out[code] = [f"{code}.KS", it.get("itemname", code), "ETF", "KRW", 3]
    return out


def _usym(s: str) -> str | None:
    s = s.strip().upper().replace("/", "-").replace(".", "-").replace(" ", "")
    return s if re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", s) and not s.endswith("-W") else None


def list_us() -> dict:
    out = {}
    try:   # 나스닥 스크리너: 시가총액·섹터 포함
        r = get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true")
        rows = r.json()["data"]["rows"]
        rows.sort(key=lambda x: -float(re.sub(r"[^\d.]", "", str(x.get("marketCap") or "0")) or 0))
        for i, x in enumerate(rows):
            s, nm = _usym(x.get("symbol", "")), x.get("name", "")
            if not s or re.search(r"warrant|right|unit|preferred|depositary shares? represent|notes? due", nm, re.I):
                continue
            out[s] = [s, nm, sector_ko(f"{x.get('industry', '')} {x.get('sector', '')}"), "USD", 1 if i < 1500 else 4]
        log(f"미국 주식(나스닥 스크리너) {len(out)}")
    except Exception as e:  # noqa: BLE001
        log(f"나스닥 스크리너 실패 → nasdaqtrader 목록 사용: {e}")
    try:   # nasdaqtrader: ETF 구분 포함, 스크리너 실패 대비
        for url, symcol, etfcol in (("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", 0, 6),
                                    ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", 0, 4)):
            lines = get(url).text.splitlines()
            for ln in lines[1:]:
                p = ln.split("|")
                if len(p) < 7 or p[0].startswith("File Creation"):
                    continue
                test = p[3] if "nasdaqlisted" in url else p[6]
                if test == "Y":
                    continue
                s, nm, etf = _usym(p[symcol]), p[1], p[etfcol] == "Y"
                if not s or re.search(r"warrant|right|unit|preferred|depositary|notes? due|%", nm, re.I):
                    continue
                if etf:
                    out.setdefault(s, [s, nm, "ETF", "USD", 3])
                else:
                    out.setdefault(s, [s, nm, "기타", "USD", 4])
        log(f"미국 합계(ETF 포함) {len(out)}")
    except Exception as e:  # noqa: BLE001
        log(f"nasdaqtrader 실패: {e}")
    return out


def build_universe(prev: dict) -> dict:
    uni = {}
    for name, fn in (("국내 주식", list_kr_stocks), ("국내 ETF", list_kr_etfs), ("미국", list_us)):
        try:
            part = fn()
            log(f"{name} {len(part)}개")
            uni.update(part)
        except Exception as e:  # noqa: BLE001
            log(f"{name} 목록 실패: {e} → 이전 목록 사용")
            uni.update({k: v for k, v in prev.items() if (v[3] == "KRW") == (name != "미국")})
    if len(uni) < 1000 and prev:
        log("목록이 너무 적어 이전 목록과 합칩니다.")
        uni = {**prev, **uni}
    return uni


# ───────── 2. 시세 ─────────
def download(symbols: list[str], **kw):
    import yfinance as yf
    for i in range(3):
        try:
            return yf.download(symbols, interval="1d", auto_adjust=False, actions=True, group_by="ticker",
                               threads=True, progress=False, **kw)
        except Exception as e:  # noqa: BLE001
            log(f"download 오류({e}) {i + 1}/3")
            time.sleep(20 * (i + 1))
    return None


def frames(df, symbols):
    """yf.download 결과에서 종목별 DataFrame(Close·Volume·Stock Splits) 꺼내기"""
    if df is None or df.empty:
        return {}
    out = {}
    lv0 = set(df.columns.get_level_values(0)) if df.columns.nlevels > 1 else set()
    for s in symbols:
        try:
            sub = df[s] if s in lv0 else (df if len(symbols) == 1 else None)
            if sub is None:
                continue
            sub = sub.dropna(subset=["Close"])
            if not sub.empty:
                out[s] = sub
        except Exception:  # noqa: BLE001
            pass
    return out


def r4(v: float) -> float:
    return float(f"{v:.6g}") if v and math.isfinite(v) else 0.0


def to_series(sub) -> tuple[list[str], list[float], list[int], list[list]]:
    dates = [d.strftime("%Y-%m-%d") for d in sub.index]
    closes = [r4(float(v)) for v in sub["Close"]]
    vols = [int(v) if v == v else 0 for v in sub.get("Volume", [0] * len(dates))]
    splits = []
    if "Stock Splits" in sub:
        for d, r in sub["Stock Splits"].items():
            if r == r and float(r) not in (0.0, 1.0):
                splits.append([d.strftime("%Y-%m-%d"), float(r)])
    return dates, closes, vols, splits


def pack(meta: list, dates, closes, vols, splits) -> dict:
    """날짜는 첫날 + 일수 차이 배열로 줄여 저장 (파일 크기 절반 이하)"""
    d0 = dt.date.fromisoformat(dates[0])
    dd = [(dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days for a, b in zip(dates, dates[1:])]
    return {"s": meta[0], "n": meta[1], "sec": meta[2], "cur": meta[3], "d0": d0.isoformat(), "dd": dd, "c": closes,
            "v": vols[-25:], "sp": splits, "u": dates[-1]}


def unpack(js: dict):
    d = dt.date.fromisoformat(js["d0"])
    dates = [d.isoformat()]
    for x in js["dd"]:
        d += dt.timedelta(days=x)
        dates.append(d.isoformat())
    return dates, js["c"], js.get("v", []), js.get("sp", [])


def save(path: Path, js: dict) -> None:
    path.write_text(json.dumps(js, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def run(data: Path, backfill_cap: int, chunk_new: int = 80, chunk_upd: int = 250) -> dict:
    data.mkdir(parents=True, exist_ok=True)
    uf = data / "_universe.json"
    prev = json.loads(uf.read_text(encoding="utf-8")) if uf.exists() else {}
    uni = build_universe(prev)
    save(uf, uni)
    log(f"수집 대상 {len(uni)}개")
    have = {p.stem for p in data.glob("*.json") if not p.stem.startswith("_")}
    stats = {"updated": 0, "new": 0, "failed": 0, "refetch": 0}
    cutoff = (dt.date.today() - dt.timedelta(days=HIST_DAYS)).isoformat()

    # 2-1. 기존 파일: 최근 7일 이어 붙이기
    olds = [k for k in uni if k in have]
    refetch = []
    for i in range(0, len(olds), chunk_upd):
        keys = olds[i:i + chunk_upd]
        syms = [uni[k][0] for k in keys]
        fr = frames(download(syms, period="7d"), syms)
        for k in keys:
            sub = fr.get(uni[k][0])
            if sub is None:
                continue
            nd, nc, nv, nsp = to_series(sub)
            if nsp:                       # 분할 발생 → 과거 종가 전체가 바뀌므로 다시 받기
                refetch.append(k)
                continue
            js = json.loads((data / f"{k}.json").read_text(encoding="utf-8"))
            d, c, v, sp = unpack(js)
            vol = dict(zip(d[-len(v):], v)) if v else {}          # 거래량은 최근 25일만 보관
            vol.update(zip(nd, nv))
            keep = [j for j, x in enumerate(d) if x < nd[0] and x >= cutoff]
            d = [d[j] for j in keep] + nd
            c = [c[j] for j in keep] + nc
            v = [vol.get(x, 0) for x in d[-25:]]
            save(data / f"{k}.json", pack(uni[k], d, c, v, sp))
            stats["updated"] += 1
        log(f"업데이트 {min(i + chunk_upd, len(olds))}/{len(olds)}")
        time.sleep(1)
    stats["refetch"] = len(refetch)

    # 2-2. 새 종목·분할 종목: 2년치 받기 (우선순위: 샘플 종목 → 분할 → 국내 주식·미국 대형주 → ETF → 나머지)
    news = [k for k in uni if k not in have]
    news.sort(key=lambda k: (0 if k in SEED else 1, uni[k][4]))
    todo = refetch + news[:max(0, backfill_cap - len(refetch))]
    for i in range(0, len(todo), chunk_new):
        keys = todo[i:i + chunk_new]
        syms = [uni[k][0] for k in keys]
        fr = frames(download(syms, period="2y"), syms)
        for k in keys:
            sub = fr.get(uni[k][0])
            if sub is None:
                stats["failed"] += 1
                continue
            d, c, v, sp = to_series(sub)
            save(data / f"{k}.json", pack(uni[k], d, c, v, sp))
            stats["new"] += 1
        log(f"신규 {min(i + chunk_new, len(todo))}/{len(todo)} (실패 누적 {stats['failed']})")
        time.sleep(2)
    stats["pending"] = max(0, len(news) - (len(todo) - len(refetch)))

    # 2-3. 환율
    fr = frames(download(["KRW=X"], period="2y"), ["KRW=X"])
    if "KRW=X" in fr:
        d, c, v, sp = to_series(fr["KRW=X"])
        save(data / "_fx.json", pack(["KRW=X", "USD/KRW", "", "KRW"], d, c, v, []))
    stats["total"] = sum(1 for p in data.glob("*.json") if not p.stem.startswith("_"))
    stats["universe"] = len(uni)
    stats["generated"] = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    save(data / "_meta.json", stats)
    log(f"완료 {stats}")
    return stats


# ───────── 3. 페이지 ─────────
def write_indexes(site: Path, sub: str) -> None:
    head = ('<!DOCTYPE html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<body style="font-family:-apple-system,sans-serif;padding:20px;line-height:1.8">')
    arch = site / sub / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "index.html").write_text(f'{head}<title>{sub}</title><h2>{sub}</h2>'
                                     '<p>이 대시보드는 매번 최신 시세로 다시 계산되어 지난 리포트가 없습니다.</p>'
                                     '<p><a href="../">← 대시보드로</a></p>', encoding="utf-8")
    subs = sorted(d.name for d in site.iterdir() if d.is_dir() and (d / "index.html").exists())
    items = "".join(f'<li><a href="{d}/">{d}</a> · <a href="{d}/archive/">지난 리포트</a></li>' for d in subs)
    (site / "index.html").write_text(f'{head}<title>reports</title><h2>reports</h2><ul>{items}</ul>', encoding="utf-8")
    (site / ".nojekyll").touch()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="시세 폴더 (market-data 브랜치의 data/)")
    ap.add_argument("--site", required=True, help="페이지 출력 폴더 (gh-pages 의 daily_portfolio-dashboard/)")
    ap.add_argument("--backfill", type=int, default=4000, help="한 번에 새로 받을 종목 수 상한")
    a = ap.parse_args()
    site = Path(a.site)
    site.mkdir(parents=True, exist_ok=True)
    for f in (HERE / "web").iterdir():
        shutil.copy2(f, site / f.name)
    (site / "prices.json").unlink(missing_ok=True)      # 예전 방식 파일 정리
    write_indexes(site.parent, site.name)
    if a.data:
        run(Path(a.data), a.backfill)
    log(f"페이지 → {site}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
