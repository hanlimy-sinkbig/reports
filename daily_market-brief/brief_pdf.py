# -*- coding: utf-8 -*-
"""
market_brief.py 가 만든 데이터(dict)로 PDF 리포트를 그립니다 (matplotlib 사용).
PDF는 구글 드라이브 앱에서 아이패드·안드로이드·PC 어디서나 바로 미리보기됩니다.
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator

# ---- 스타일 -----------------------------------------------------------------
UP, DOWN = "#d63b3a", "#2a6fd0"
TEXT, SUB, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#85847f", "#e6e5e0", "#fcfcfb"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
DIV = LinearSegmentedColormap.from_list(
    "kr_div", [(0, "#1c5cab"), (0.25, "#6da7ec"), (0.5, "#f0efec"), (0.75, "#f08a89"), (1, "#c22f2e")])
NORM = Normalize(-3, 3)
A4 = (8.27, 11.69)


def _setup_font():
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic", "Noto Sans CJK KR",
                 "NanumGothic", "Noto Sans KR"):
        if name in have:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams.update({"axes.unicode_minus": False, "font.size": 8.5, "axes.edgecolor": GRID,
                         "axes.labelcolor": SUB, "xtick.color": SUB, "ytick.color": SUB,
                         "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                         "axes.spines.top": False, "axes.spines.right": False})


def _c(v):
    return SUB if v is None or abs(v) < 0.005 else (UP if v > 0 else DOWN)


def _s(v, d=2):
    return "–" if v is None else f"{v:+.{d}f}%"


def _human(v, _pos=None):
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.0f}{suf}"
    return f"{v:.0f}"


def _strip(h):
    return re.sub(r"<[^>]+>", "", h or "").replace("&amp;", "&")


def _wrap(text, width):
    """한글 폭을 고려한 단순 줄바꿈"""
    lines, cur, w = [], "", 0
    for ch in text:
        cw = 2 if ord(ch) > 0x2000 else 1
        if w + cw > width and cur:
            lines.append(cur)
            cur, w = "", 0
        cur += ch
        w += cw
    if cur:
        lines.append(cur)
    return lines


# ---- 차트 부품 --------------------------------------------------------------
def candle(ax, p, vol_ax=None, title=None):
    n = len(p["x"])
    xs = range(n)
    for i in xs:
        o, h, l, c = p["o"][i], p["h"][i], p["l"][i], p["c"][i]
        if None in (o, h, l, c):
            continue
        col = UP if c >= o else DOWN
        ax.vlines(i, l, h, color=col, linewidth=0.6)
        ax.add_patch(Rectangle((i - 0.33, min(o, c)), 0.66, max(abs(c - o), (h - l) * 0.01 or 1e-9),
                               facecolor=col, edgecolor=col, linewidth=0))
    if p.get("ma20"):
        ax.plot(xs, p["ma20"], color=SERIES[3], linewidth=1.1, label="20일선")
    if p.get("ma60"):
        ax.plot(xs, p["ma60"], color=SERIES[6], linewidth=1.1, label="60일선")
    ax.yaxis.tick_right()
    ax.set_xlim(-1, n)
    ticks = list(range(0, n, max(1, n // 6)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([p["x"][i][5:] for i in ticks])
    ax.legend(loc="upper left", frameon=False, fontsize=7.5)
    if title:
        ax.set_title(title, loc="left", fontsize=10, color=TEXT, fontweight="bold")
    if vol_ax is not None:
        cols = [UP if (c or 0) >= (o or 0) else DOWN for o, c in zip(p["o"], p["c"])]
        vol_ax.bar(xs, p["v"], color=cols, alpha=0.45, width=0.7)
        vol_ax.yaxis.tick_right()
        vol_ax.set_xlim(-1, n)
        vol_ax.set_xticks(ticks)
        vol_ax.set_xticklabels([p["x"][i][5:] for i in ticks])
        vol_ax.grid(False)
        vol_ax.yaxis.set_major_locator(MaxNLocator(2))
        vol_ax.yaxis.set_major_formatter(FuncFormatter(_human))
        ax.set_xticklabels([])


def _squarify(values, x, y, w, h):
    """Squarified treemap: 값 리스트(내림차순) -> 사각형 리스트"""
    values = [max(v, 1e-9) for v in values]
    total = sum(values)
    vals = [v * w * h / total for v in values]
    rects, i = [], 0

    def worst(row, side):
        s = sum(row)
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row)

    while i < len(vals):
        side = min(w, h)
        row = [vals[i]]
        i += 1
        while i < len(vals) and worst(row + [vals[i]], side) <= worst(row, side):
            row.append(vals[i])
            i += 1
        s = sum(row)
        if w >= h:  # 세로 띠
            rw = s / h
            yy = y
            for r in row:
                rh = r / rw
                rects.append((x, yy, rw, rh))
                yy += rh
            x, w = x + rw, w - rw
        else:  # 가로 띠
            rh = s / w
            xx = x
            for r in row:
                rw = r / rh
                rects.append((xx, y, rw, rh))
                xx += rw
            y, h = y + rh, h - rh
    return rects


def treemap(ax, tm, title):
    ax.set_title(title, loc="left", fontsize=10, color=TEXT, fontweight="bold")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    root = tm["ids"][0]
    sectors = [(i, tm["ids"][i]) for i in range(len(tm["ids"])) if tm["parents"][i] == root]
    kids = {sid: [j for j in range(len(tm["ids"])) if tm["parents"][j] == sid] for _, sid in sectors}
    sec_val = {sid: sum(tm["values"][j] or 0 for j in kids[sid]) for _, sid in sectors}
    sectors.sort(key=lambda s: -sec_val[s[1]])
    for (si, sid), (x, y, w, h) in zip(sectors, _squarify([sec_val[s[1]] for s in sectors], 0, 0, 100, 100)):
        ax.add_patch(Rectangle((x, y), w, h, facecolor="white", edgecolor="white", linewidth=2))
        head = 4.2 if h > 12 else 0
        ch = sorted(kids[sid], key=lambda j: -(tm["values"][j] or 0))
        for j, (cx, cy, cw, chh) in zip(ch, _squarify([tm["values"][j] for j in ch], x + .4, y + .4,
                                                       w - .8, h - .8 - head)):
            v = tm["colors"][j] or 0
            fc = DIV(NORM(v))
            ax.add_patch(Rectangle((cx, cy), cw, chh, facecolor=fc, edgecolor="white", linewidth=1))
            lum = 0.299 * fc[0] + 0.587 * fc[1] + 0.114 * fc[2]
            tc = "white" if lum < 0.55 else TEXT
            area = cw * chh
            if area > 22 and cw > 6:
                fs = 6.5 if area < 80 else 8
                ax.text(cx + cw / 2, cy + chh / 2, f"{tm['labels'][j]}\n{tm['texts'][j]}", ha="center",
                        va="center", fontsize=fs, color=tc, linespacing=1.2, clip_on=True)
        if head:
            ax.text(x + 1, y + h - 2.2, f"{tm['labels'][si]} {tm['texts'][si]}", fontsize=7, color=TEXT,
                    va="center", fontweight="bold", clip_on=True)


def sector_bars(ax, rows, title):
    rows = list(reversed(rows))
    ys = range(len(rows))
    vals = [r["r1"] for r in rows]
    ax.barh(ys, vals, color=[UP if v >= 0 else DOWN for v in vals], height=0.6)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([r["sector"] for r in rows])
    ax.axvline(0, color=MUTED, linewidth=0.8)
    lim = max(abs(v) for v in vals) * 1.35 if vals else 1
    ax.set_xlim(-lim, lim)
    for y, v in zip(ys, vals):
        ax.text(v + (lim * 0.03 if v >= 0 else -lim * 0.03), y, _s(v), va="center",
                ha="left" if v >= 0 else "right", fontsize=7, color=SUB)
    ax.grid(axis="y", visible=False)
    ax.set_title(title, loc="left", fontsize=10, color=TEXT, fontweight="bold")


def _text_block(fig, x, y, lines, size=8.5, lh=0.017, color=TEXT, width=95, bullet="• "):
    for ln in lines:
        for k, part in enumerate(_wrap(ln, width)):
            fig.text(x, y, (bullet if k == 0 else "   ") + part, fontsize=size, color=color, va="top")
            y -= lh
    return y


def _header(fig, data, page, title):
    fig.text(0.06, 0.965, title, fontsize=15, fontweight="bold", color=TEXT, va="top")
    fig.text(0.06, 0.94, f"생성 {data['generated']} · 미국 기준 {data['asof_us']} · 한국 기준 {data['asof_kr']}"
             f" · 상승=빨강 / 하락=파랑" + ("  [데모: 가상 데이터]" if data.get("demo") else ""),
             fontsize=7.5, color=SUB, va="top")
    fig.text(0.94, 0.02, f"{page}", fontsize=7, color=MUTED, ha="right")
    fig.text(0.06, 0.02, "자동 생성 참고자료 · 투자 권유 아님 · 데이터: Yahoo Finance, Google News",
             fontsize=6.5, color=MUTED)


# ---- 페이지 -----------------------------------------------------------------
def page_indices(pdf, data, pno):
    fig = plt.figure(figsize=A4)
    _header(fig, data, pno, "모닝 마켓 브리핑 ① 주요 지수")
    y = _text_block(fig, 0.06, 0.905, [_strip(s) for s in data["summary"]], size=9, lh=0.019)
    # 지수 표
    y -= 0.008
    cols = [0.06, 0.30, 0.45, 0.57, 0.69, 0.80]
    for x, h in zip(cols, ["지수", "종가", "전일", "5일", "1개월", "기준일"]):
        fig.text(x, y, h, fontsize=7.5, color=SUB, fontweight="bold", va="top")
    y -= 0.017
    for r in data["indices"]:
        fig.text(cols[0], y, r["name"], fontsize=8.5, va="top")
        fig.text(cols[1], y, f"{r['close']:,.2f}" if r["close"] is not None else "–", fontsize=8.5, va="top")
        for x, k, d in ((cols[2], "r1", 2), (cols[3], "r5", 1), (cols[4], "r20", 1)):
            fig.text(x, y, _s(r[k], d), fontsize=8.5, color=_c(r[k]), va="top")
        fig.text(cols[5], y, r["date"], fontsize=8, color=MUTED, va="top")
        y -= 0.016
    top = y - 0.015
    avail = top - 0.05
    keys = list(data["main_charts"])
    hgt = (avail - 0.05 * len(keys)) / max(len(keys), 1)
    for i, t in enumerate(keys):
        p = data["main_charts"][t]
        r = next((x for x in data["indices"] if x["ticker"] == t), {})
        ax = fig.add_axes([0.07, top - (i + 1) * hgt - i * 0.05, 0.84, hgt - 0.03])
        candle(ax, p, title=f"{p['name']}  {r.get('close', 0):,.2f} ({_s(r.get('r1'))}) · 최근 6개월")
    pdf.savefig(fig)
    plt.close(fig)


def page_sectors(pdf, data, pno):
    fig = plt.figure(figsize=A4)
    _header(fig, data, pno, "② 섹터별 히트맵")
    treemap(fig.add_axes([0.06, 0.60, 0.88, 0.31]), data["treemaps"]["US"], "미국 대형주 (면적=시가총액, 색=전일 등락)")
    treemap(fig.add_axes([0.06, 0.25, 0.88, 0.31]), data["treemaps"]["KR"], "코스피 대형주 (면적=시가총액, 색=전일 등락)")
    sector_bars(fig.add_axes([0.16, 0.05, 0.31, 0.16]), data["us_etf"], "미국 섹터 ETF")
    sector_bars(fig.add_axes([0.63, 0.05, 0.31, 0.16]), data["kr_sector"], "국내 업종(시총가중)")
    # 색 범례
    cax = fig.add_axes([0.64, 0.583, 0.30, 0.006])
    cb = plt.colorbar(plt.cm.ScalarMappable(norm=NORM, cmap=DIV), cax=cax, orientation="horizontal")
    cb.set_ticks([-3, 0, 3])
    cb.set_ticklabels(["-3%", "0", "+3%"])
    cb.outline.set_visible(False)
    cax.tick_params(labelsize=6.5)
    pdf.savefig(fig)
    plt.close(fig)


def page_stock(pdf, data, k, pno):
    fig = plt.figure(figsize=A4)
    flag = "미국" if k["market"] == "US" else "한국"
    st = k["stats"]
    _header(fig, data, pno, f"③④⑤ {k['name']} ({k['ticker']})")
    fig.text(0.06, 0.915, f"{flag} · {k['sector']} · 종가 {st['close']:,.2f}", fontsize=9, color=SUB, va="top")
    fig.text(0.94, 0.915, _s(st["r1"]), fontsize=14, color=_c(st["r1"]), ha="right", va="top", fontweight="bold")
    # ③ 차트
    ax = fig.add_axes([0.07, 0.715, 0.84, 0.17])
    vax = fig.add_axes([0.07, 0.66, 0.84, 0.05], sharex=ax)
    candle(ax, k["chart"], vax, title="③ 최근 3개월 일봉 · 거래량")
    # ④ 선정 이유 + 뉴스
    y = 0.625
    fig.text(0.06, y, "④ 선정 이유", fontsize=10, fontweight="bold", va="top")
    y -= 0.022
    reasons = k["reasons"] + [f"5일 {_s(st['r5'], 1)} · 1개월 {_s(st['r20'], 1)} · 60일선 {'위' if st['above_ma60'] else '아래'}"]
    y = _text_block(fig, 0.07, y, reasons, size=8.5, lh=0.016)
    if k.get("llm"):
        y = _text_block(fig, 0.07, y - 0.004, ["뉴스 요약: " + k["llm"]], size=8.5, lh=0.016, color=SUB)
    y -= 0.008
    fig.text(0.06, y, "관련 최신 뉴스", fontsize=9, fontweight="bold", va="top")
    y -= 0.02
    for n in k["news"][:6]:
        line = f"{n['title']}  ({n['source']} {n['date']})".strip()
        for j, part in enumerate(_wrap(line, 100)[:2]):
            t = fig.text(0.07, y, ("· " if j == 0 else "  ") + part, fontsize=7.8, va="top",
                         color=TEXT if j == 0 else TEXT)
            if n.get("link") and n["link"] != "#":
                t.set_url(n["link"])
            y -= 0.0145
    if not k["news"]:
        fig.text(0.07, y, "최근 3일 내 검색된 뉴스 없음", fontsize=8, color=MUTED, va="top")
        y -= 0.015
    # ⑤ 연관 종목
    P = k["peers"]
    y -= 0.012
    fig.text(0.06, y, "⑤ 연관 종목 분석", fontsize=10, fontweight="bold", va="top")
    top = y - 0.025
    ax2 = fig.add_axes([0.07, top - 0.19, 0.40, 0.165])
    for j, (t, s) in enumerate(P["perf"].items()):
        ax2.plot(range(len(s["y"])), s["y"], color=SERIES[j % len(SERIES)], linewidth=2.2 if j == 0 else 1.2,
                 label=s["name"])
    ax2.axhline(100, color=MUTED, linewidth=0.8, linestyle=":")
    ax2.yaxis.tick_right()
    ax2.set_xticks([])
    ax2.set_title("최근 1개월 성과 (시작=100)", loc="left", fontsize=8.5, color=TEXT)
    ax2.legend(fontsize=6.5, frameon=False, loc="upper left", ncol=3, bbox_to_anchor=(0, -0.01),
               handlelength=1.2, columnspacing=0.8)
    # 표
    cols = [0.53, 0.72, 0.79, 0.86, 0.93]
    ty = top
    for x, h in zip(cols, ["종목", "전일", "5일", "1개월", "상관"]):
        fig.text(x, ty, h, fontsize=7.5, color=SUB, fontweight="bold", va="top", ha="left" if x == cols[0] else "right")
    ty -= 0.017
    rows = [{"name": "★ " + k["name"], "r1": st["r1"], "r5": st["r5"], "r20": st["r20"], "corr": 1.0, "cross": False}] + P["rows"]
    for r in rows:
        fig.text(cols[0], ty, r["name"][:12], fontsize=8, va="top")
        for x, kk, d in ((cols[1], "r1", 1), (cols[2], "r5", 1), (cols[3], "r20", 1)):
            fig.text(x, ty, _s(r[kk], d), fontsize=8, color=_c(r[kk]), va="top", ha="right")
        fig.text(cols[4], ty, ("–" if r["corr"] is None else f"{r['corr']:.2f}") + ("*" if r["cross"] else ""),
                 fontsize=8, va="top", ha="right")
        ty -= 0.016
    fig.text(cols[0], ty - 0.002, "* 한·미 교차: 미국 전일 → 한국 익일 시차 상관", fontsize=6.5, color=MUTED, va="top")
    ny = min(ty - 0.02, top - 0.255)
    _text_block(fig, 0.07, ny, [_strip(n) for n in P["notes"]] or ["연관 종목 데이터 부족"], size=8.3, lh=0.016, width=100)
    pdf.savefig(fig)
    plt.close(fig)


def render_pdf(data: dict, path: str | Path) -> Path:
    _setup_font()
    path = Path(path)
    with PdfPages(path) as pdf:
        pno = 1
        page_indices(pdf, data, pno); pno += 1
        page_sectors(pdf, data, pno); pno += 1
        for k in data["key_stocks"]:
            page_stock(pdf, data, k, pno); pno += 1
        d = pdf.infodict()
        d["Title"] = f"모닝 마켓 브리핑 {data['generated'][:10]}"
    return path
