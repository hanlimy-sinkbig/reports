"""포트폴리오 대시보드 빌드
  1) tickers.json 종목의 시세(현재가·전일가·거래량·52주 범위·일별 종가·액면분할)와 USD/KRW 환율을 야후 파이낸스에서 받아 prices.json 저장
  2) web/ 폴더(페이지·스크립트·샘플 CSV)를 출력 폴더로 복사
  3) 사이트 루트의 리포트 목록 index.html 갱신
매매일지(수량·금액)는 여기서 다루지 않습니다. 페이지에서 사용자가 고른 CSV를 브라우저 안에서만 읽습니다.

사용: python build.py --outdir _site/daily_portfolio-dashboard [--years 3]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))


def log(msg: str) -> None:
    print(f"[portfolio] {msg}", flush=True)


def yahoo_symbol(t: dict) -> str:
    code, mk = t["ticker"].strip().upper(), t.get("market", "").upper()
    if code.isdigit():
        return f"{code.zfill(6)}.{'KQ' if mk == 'KQ' else 'KS'}"
    return code


def fetch_one(yf, sym: str, years: int) -> dict | None:
    tk = yf.Ticker(sym)
    h = tk.history(period=f"{years}y", interval="1d", auto_adjust=False, actions=True)
    if h is None or h.empty:
        return None
    h = h.dropna(subset=["Close"])
    close = h["Close"]          # 액면분할만 조정된 종가(배당 미조정)
    dates = [d.strftime("%Y-%m-%d") for d in h.index]
    last, prev = float(close.iloc[-1]), (float(close.iloc[-2]) if len(close) > 1 else None)
    vol = h["Volume"].fillna(0)
    one_year = close[close.index >= close.index[-1] - dt.timedelta(days=365)]
    splits = []
    if "Stock Splits" in h:
        for d, r in h["Stock Splits"].items():
            if r and float(r) not in (0.0, 1.0):
                splits.append([d.strftime("%Y-%m-%d"), float(r)])
    # 장중 최신가(가능하면)
    try:
        fi = tk.fast_info
        lp = fi.get("last_price") if hasattr(fi, "get") else getattr(fi, "last_price", None)
        if lp and lp == lp:
            last = float(lp)
    except Exception:
        pass
    return {
        "symbol": sym, "last": round(last, 4), "prev": round(prev, 4) if prev else None,
        "volume": int(vol.iloc[-1]), "avgVolume20": int(vol.tail(20).mean()),
        "high52": round(float(one_year.max()), 4), "low52": round(float(one_year.min()), 4),
        "lastDate": dates[-1], "splits": splits,
        "history": {"dates": dates, "close": [round(float(v), 4) for v in close]},
    }


def build_prices(years: int) -> dict:
    import yfinance as yf
    cfg = json.loads((HERE / "tickers.json").read_text(encoding="utf-8"))
    out = {"generated": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "tickers": {}, "fx": None, "errors": []}
    for t in cfg["tickers"]:
        key = t["ticker"].strip().upper()
        key = key.zfill(6) if key.isdigit() else key
        sym = yahoo_symbol(t)
        try:
            d = fetch_one(yf, sym, years)
            if d is None and key.isdigit():          # 코스피에 없으면 코스닥 재시도
                sym = f"{key}.KQ"
                d = fetch_one(yf, sym, years)
            if d is None:
                raise RuntimeError("데이터 없음")
            d.update({"name": t.get("name", key), "sector": t.get("sector", "기타")})
            out["tickers"][key] = d
            log(f"{key} ({sym}) {d['last']} · {len(d['history']['dates'])}일 · 분할 {d['splits']}")
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{key}: {e}")
            log(f"실패 {key} ({sym}): {e}")
    try:
        fx = fetch_one(yf, "KRW=X", years)
        if fx:
            out["fx"] = {"pair": "USD/KRW", "last": fx["last"], "prev": fx["prev"], "history": fx["history"]}
            log(f"USD/KRW {fx['last']}")
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"USD/KRW: {e}")
    return out


def write_indexes(site: Path, sub: str) -> None:
    """다른 리포트와 같은 형식의 사이트 목록 + 이 리포트의 archive/index.html(목록 링크 깨짐 방지)."""
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
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--no-fetch", action="store_true", help="시세를 받지 않고 페이지만 복사(테스트용)")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for f in (HERE / "web").iterdir():
        shutil.copy2(f, out / f.name)
    if not a.no_fetch:
        prices = build_prices(a.years)
        if not prices["tickers"]:
            log("시세를 하나도 받지 못했습니다. 이전 prices.json 을 유지합니다.")
        else:
            (out / "prices.json").write_text(json.dumps(prices, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_indexes(out.parent, out.name)
    log(f"완료 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
