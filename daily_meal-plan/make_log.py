#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""식사 기록 엑셀(식사기록.xlsx) 만들기 — 구글 드라이브 '은형' 폴더에 올려 두고 매일 먹은 음식을 적는 파일.

  python make_log.py --start 2026-11 --months 14 --out 식사기록.xlsx

탭: 사용법 · 메뉴목록 · YYYY-MM(달마다 하나). meal_plan.py 가 YYYY-MM 탭만 읽습니다.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meal_data as M  # noqa: E402

HEAD = ["날짜", "요일", "아침", "점심", "저녁", "간식·기타", "맛있었던 메뉴", "별로였던 메뉴", "메모"]
WIDTH = [12, 6, 22, 22, 22, 18, 20, 20, 26]
F = "Arial"
thin = Side(style="thin", color="D9D4C7")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
HFILL = PatternFill("solid", fgColor="D9622B")
INFILL = PatternFill("solid", fgColor="FFF9DB")      # 적는 칸
SUN, SAT = "D1352B", "2A6FD6"


def month_sheet(wb, y, m):
    ws = wb.create_sheet(f"{y}-{m:02d}")
    for c, (h, w) in enumerate(zip(HEAD, WIDTH), 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(name=F, bold=True, color="FFFFFF")
        cell.fill = HFILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BOX
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[1].height = 22
    for d in range(1, calendar.monthrange(y, m)[1] + 1):
        day = dt.date(y, m, d)
        r = d + 1
        wd = "월화수목금토일"[day.weekday()]
        color = SUN if wd == "일" else SAT if wd == "토" else "1B1A17"
        a = ws.cell(r, 1, day)
        a.number_format = "yyyy-mm-dd"
        ws.cell(r, 2, wd)
        for c in (1, 2):
            ws.cell(r, c).font = Font(name=F, color=color, bold=(c == 1))
            ws.cell(r, c).alignment = Alignment(horizontal="center", vertical="center")
        for c in range(1, len(HEAD) + 1):
            cell = ws.cell(r, c)
            cell.border = BOX
            if c >= 3:
                cell.fill = INFILL
                cell.font = Font(name=F)
                cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "C2"
    return ws


def guide_sheet(wb):
    ws = wb.active
    ws.title = "사용법"
    rows = [
        ("식사 기록 — 사용법", True),
        ("", False),
        ("1. 달마다 탭이 하나씩 있습니다 (예: 2026-11). 그날 먹은 음식을 노란 칸에 적으세요.", False),
        ("2. 한 칸에 여러 음식은 쉼표로 구분합니다. 예) 김치찌개, 계란말이", False),
        ("3. '맛있었던 메뉴'에 적은 음식은 더 자주, '별로였던 메뉴'는 덜 추천됩니다.", False),
        ("4. 최근 7일 안에 먹은 메뉴는 추천에서 빠지고, 최근 2주에 많이 먹은 종류(예: 고기)는 줄여서 추천합니다.", False),
        ("5. 외식·배달도 그대로 적으세요. 예) 치킨 배달, 회사 급식 — 추천 목록에 없는 음식도 기록으로 남습니다.", False),
        ("6. 날짜·요일 칸, 탭 이름, 첫 줄 제목은 고치지 마세요 (식단 페이지가 이 이름으로 읽습니다).", False),
        ("7. 매일 아침 06:15 식단 페이지가 이 파일을 읽어 지난 날짜에는 실제로 먹은 음식을 보여 주고, 앞으로의 추천을 바꿉니다.", False),
        ("8. '메뉴목록' 탭의 이름과 같게(또는 비슷하게) 적으면 더 정확히 반영됩니다. 예) 치킨→에어프라이어 치킨, 피자→또띠아 피자로 인식", False),
        ("", False),
        ("작성 예시 (실제 기록은 달별 탭에)", True),
    ]
    for r, (t, b) in enumerate(rows, 1):
        ws.cell(r, 1, t).font = Font(name=F, bold=b, size=14 if r == 1 else 11)
    r0 = len(rows) + 1
    for c, h in enumerate(HEAD, 1):
        cell = ws.cell(r0, c, h)
        cell.font = Font(name=F, bold=True, color="FFFFFF")
        cell.fill = HFILL
        cell.border = BOX
    ex = [dt.date(2026, 11, 24), "화", "토스트", "급식", "김치찌개, 계란말이", "귤", "김치찌개", "", "아이들이 찌개 잘 먹음"]
    for c, v in enumerate(ex, 1):
        cell = ws.cell(r0 + 1, c, v)
        cell.font = Font(name=F, italic=True, color="85847F")
        cell.border = BOX
        if c == 1:
            cell.number_format = "yyyy-mm-dd"
    ws.column_dimensions["A"].width = 14
    for c, w in enumerate(WIDTH[1:], 2):
        ws.column_dimensions[ws.cell(1, c).column_letter].width = w


def menu_sheet(wb):
    ws = wb.create_sheet("메뉴목록")
    for c, h in enumerate(["추천 메뉴", "테마", "밀키트", "배달"], 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(name=F, bold=True, color="FFFFFF")
        cell.fill = HFILL
    for r, d in enumerate(M.DISHES, 2):
        ws.cell(r, 1, d["name"]).font = Font(name=F)
        ws.cell(r, 2, " ".join("#" + t for t in d["tags"])).font = Font(name=F, color="56534C")
        ws.cell(r, 3, "○" if d["kit"] else "").font = Font(name=F)
        ws.cell(r, 4, "○" if d["dl"] else "").font = Font(name=F)
    for col, w in zip("ABCD", (20, 50, 8, 8)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-11")
    ap.add_argument("--months", type=int, default=14)
    ap.add_argument("--out", default="식사기록.xlsx")
    a = ap.parse_args()
    y, m = map(int, a.start.split("-"))
    wb = Workbook()
    guide_sheet(wb)
    for _ in range(a.months):
        month_sheet(wb, y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    menu_sheet(wb)
    wb.active = 1                         # 첫 달 탭이 열리게
    wb.save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()
