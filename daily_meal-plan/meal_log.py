# -*- coding: utf-8 -*-
"""식사 기록(구글 드라이브 '은형/식사기록.xlsx') 읽기 + 추천에 반영할 값 계산.

- 파일 ID 는 GitHub Actions 비밀값 MEAL_LOG_ID 로 받습니다(공개 저장소에 ID를 남기지 않음).
  파일은 '링크가 있는 모든 사용자 · 뷰어'로 공유돼 있어야 내려받을 수 있습니다.
- 읽는 탭: 이름이 YYYY-MM 인 탭. 열: 날짜 | 요일 | 아침 | 점심 | 저녁 | 간식·기타 | 맛있었던 메뉴 | 별로였던 메뉴 | 메모
  (메모는 공개 페이지에 올리지 않으므로 읽지 않습니다.)

추천 반영 규칙 (그날 이전 기록만 사용)
  ① 최근 7일 안에 먹은 메뉴는 빼고   ② '맛있었던 메뉴'는 1번당 ×1.5(최대 ×3)   ③ '별로였던 메뉴'는 ×0.15
  ④ 최근 14일 기록에서 한 종류(#고기·#매콤·#국물 등)가 40% 넘게 나오면 그 종류를 ×0.6
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
from collections import Counter

import meal_data as M

COLS = {"날짜": "date", "아침": "m", "점심": "m", "저녁": "m", "간식·기타": "m", "간식": "m", "기타": "m",
        "맛있었던 메뉴": "like", "별로였던 메뉴": "dislike"}
STOP = ("배달", "외식", "밀키트", "포장", "집밥", "시켜먹음", "사먹음")
# 흔히 쓰는 이름 → 메뉴 목록 이름
ALIAS = {
    "치킨": "에어프라이어 치킨", "후라이드": "에어프라이어 치킨", "양념치킨": "에어프라이어 치킨", "피자": "또띠아 피자",
    "햄버거": "수제 햄버거", "버거": "수제 햄버거", "불고기": "소불고기", "보쌈": "돼지고기 수육", "수육": "돼지고기 수육",
    "닭갈비": "춘천닭갈비", "찜닭": "안동찜닭", "초밥": "모둠초밥", "스시": "모둠초밥", "스테이크": "소고기 스테이크",
    "포케": "연어 포케", "리조또": "버섯 리조또", "들깨탕": "채소 들깨 버섯탕", "샐러드": "닭가슴살 샐러드",
    "미역국": "소고기미역국", "무국": "소고기무국", "야채죽": "소고기 야채죽", "호박죽": "단호박죽", "냉면": "물냉면",
    "닭도리탕": "닭볶음탕", "샤브": "샤브샤브", "나베": "밀푀유나베", "장조림": "메추리알 장조림", "카레": "카레라이스",
    "파스타": "크림파스타", "까르보나라": "크림파스타", "볶음밥": "새우볶음밥", "파전": "해물파전", "고등어": "고등어구이",
    "갈치": "갈치조림", "오징어": "오징어볶음", "삼겹살": "삼겹살 구이", "연어": "연어 스테이크", "어묵": "어묵탕",
    "오뎅": "어묵탕", "떡볶기": "떡볶이", "짜장": "짜장면", "자장면": "짜장면", "돈가스": "돈까스", "규동": "규동",
}


def norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", "", str(s or ""))
    for w in STOP:
        s = s.replace(w, "")
    return re.sub(r"[\s\W_]+", "", s)


_NAMES = [(norm(d["name"]), i) for i, d in enumerate(M.DISHES)]
_NAMES.sort(key=lambda x: -len(x[0]))
_ALIAS = sorted(((norm(k), norm(v)) for k, v in ALIAS.items()), key=lambda x: -len(x[0]))
_BY = {n: i for n, i in _NAMES}


def match(text: str) -> int | None:
    t = norm(text)
    if len(t) < 2:
        return None
    if t in _BY:
        return _BY[t]
    for n, i in _NAMES:                         # 긴 이름부터: '소고기미역국' 이 '미역국' 보다 먼저
        if n in t or (len(t) >= 3 and t in n):
            return i
    for a, target in _ALIAS:
        if a in t:
            return _BY.get(target)
    return None


def split_items(v) -> list[str]:
    if v is None:
        return []
    return [x.strip() for x in re.split(r"[,，/·+\n]|그리고", str(v)) if x.strip() and x.strip() not in ("-", "x", "X")]


def to_date(v) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    m = re.search(r"(20\d{2})\D(\d{1,2})\D(\d{1,2})", str(v or ""))
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


class History:
    def __init__(self, days: dict[dt.date, dict] | None = None):
        self.days = days or {}
        self._cache: dict[dt.date, tuple] = {}

    # ---------------------------------------------------------- 읽기
    @classmethod
    def from_xlsx(cls, data: bytes) -> "History":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        days: dict[dt.date, dict] = {}
        for ws in wb.worksheets:
            if not re.fullmatch(r"\d{4}-\d{2}", ws.title.strip()):
                continue
            rows = ws.iter_rows(values_only=True)
            head = next(rows, None) or ()
            kind = [COLS.get(str(h or "").strip()) for h in head]
            for r in rows:
                rec = {"meals": [], "like": [], "dislike": []}
                day = None
                for k, v in zip(kind, r):
                    if k == "date":
                        day = to_date(v)
                    elif k == "m":
                        rec["meals"] += split_items(v)
                    elif k in ("like", "dislike"):
                        rec[k] += split_items(v)
                if day and (rec["meals"] or rec["like"] or rec["dislike"]):
                    days[day] = {
                        "meals": [{"t": t[:30], "i": match(t)} for t in rec["meals"]],
                        "like": {i for i in map(match, rec["like"]) if i is not None},
                        "dislike": {i for i in map(match, rec["dislike"]) if i is not None},
                    }
        return cls(days)

    @classmethod
    def fetch(cls, get, file_id: str) -> "History":
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        r = get(url)
        if not r.content.startswith(b"PK"):       # 로그인 화면 등 HTML → 공유 설정 문제
            raise RuntimeError("엑셀 파일이 아닌 응답(공유가 '링크가 있는 모든 사용자'인지 확인)")
        return cls.from_xlsx(r.content)

    # ---------------------------------------------------------- 추천용 값
    def context(self, day: dt.date):
        """그날 추천에 쓸 (뺄 메뉴, 메뉴별 가중치 배수). 그날 이전 기록만 본다."""
        if day in self._cache:
            return self._cache[day]
        avoid, mult = set(), {}
        if self.days:
            likes, dislikes, tags, n = Counter(), Counter(), Counter(), 0
            for d, rec in self.days.items():
                if d >= day:
                    continue
                for i in rec["like"]:
                    likes[i] += 1
                for i in rec["dislike"]:
                    dislikes[i] += 1
                age = (day - d).days
                for m in rec["meals"]:
                    if m["i"] is None:
                        continue
                    if age <= 7:
                        avoid.add(m["i"])
                    if age <= 14:
                        n += 1
                        tags.update(set(M.DISHES[m["i"]]["tags"]) - {"한식"})
            heavy = {t for t, c in tags.items() if n >= 4 and c / n > 0.4}
            for i, dd in enumerate(M.DISHES):
                f = min(3.0, 1.5 ** likes[i]) if likes[i] else 1.0
                if dislikes[i] > likes[i]:
                    f = 0.15
                if heavy & set(dd["tags"]):
                    f *= 0.6
                if f != 1.0:
                    mult[i] = f
        self._cache[day] = (avoid, mult)
        return avoid, mult

    def summary(self, today: dt.date) -> dict:
        """화면 맨 위 '기록 반영' 안내용."""
        rec7 = [d for d in self.days if 0 < (today - d).days <= 7]
        tags, n = Counter(), 0
        for d, rec in self.days.items():
            if 0 < (today - d).days <= 14:
                for m in rec["meals"]:
                    if m["i"] is not None:
                        n += 1
                        tags.update(set(M.DISHES[m["i"]]["tags"]) - {"한식"})
        heavy = [f"{t} {round(c / n * 100)}%" for t, c in tags.most_common() if n >= 4 and c / n > 0.4]
        likes = Counter(i for d, r in self.days.items() if d < today for i in r["like"])
        dislikes = Counter(i for d, r in self.days.items() if d < today for i in r["dislike"])
        unmatched = sum(1 for r in self.days.values() for m in r["meals"] if m["i"] is None)
        total = sum(len(r["meals"]) for r in self.days.values())
        return {"days": len(self.days), "days7": len(rec7), "heavy": heavy,
                "likes": [M.DISHES[i]["name"] for i, _ in likes.most_common(6)],
                "dislikes": [M.DISHES[i]["name"] for i, _ in dislikes.most_common(6)],
                "matched": total - unmatched, "total": total}

    def by_date(self) -> dict[str, list]:
        """달력에 '먹은 음식' 표시용: {'2026-11-24': [[이름, 메뉴번호 또는 -1], ...]}"""
        return {d.isoformat(): [[m["t"], -1 if m["i"] is None else m["i"]] for m in rec["meals"]]
                for d, rec in sorted(self.days.items()) if rec["meals"]}


def log_file_id() -> str:
    return os.environ.get("MEAL_LOG_ID", "").strip()
