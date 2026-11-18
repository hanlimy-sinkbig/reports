"""모든 리포트 공용: 네트워크 재시도 + 실패 기록 + '데이터 없음' 안내 배너.

사용법 (각 리포트 스크립트 맨 위):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_shared"))
    import net_retry as NR

    r = NR.retry(lambda: requests.get(url, timeout=20), "KBO 순위")   # 실패하면 마지막 예외를 그대로 올림
    ...
    except Exception as e:
        NR.fail("KBO 순위", e)          # 기존 except 블록에서 실패를 기록
    ...
    page = NR.inject_banner(page)        # </header> 바로 뒤에 '가져오지 못한 데이터' 안내를 넣음

재시도 규칙
- 연결 오류·시간 초과·429(요청 과다)·5xx(서버 오류)만 재시도합니다. 404 같은 오류는 다시 해도 같으므로 바로 포기.
- 기본 3번 시도, 대기 3초 → 6초 (+0~1초 무작위). 429에 Retry-After가 있으면 그 값(최대 30초)을 따릅니다.
"""
from __future__ import annotations

import html
import random
import sys
import time

TRIES = 3
BASE_WAIT = 3.0
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

FAILS: list[str] = []          # 이번 실행에서 끝내 못 가져온 항목 (화면 표시용)


def _log(msg: str) -> None:
    print(f"[retry] {msg}", file=sys.stderr, flush=True)


def _status(err: Exception) -> int | None:
    resp = getattr(err, "response", None)
    return getattr(resp, "status_code", None)


def retry(fn, label: str, tries: int = TRIES, base: float = BASE_WAIT):
    """fn()을 최대 tries번 시도. 끝내 실패하면 마지막 예외를 그대로 올린다(기록은 호출한 쪽에서 fail()로)."""
    last: Exception | None = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            st = _status(e)
            if st is not None and st not in RETRY_STATUS:
                break                                   # 404·403 등: 재시도해도 같음
            if i == tries - 1:
                break
            wait = base * (2 ** i) + random.uniform(0, 1)
            ra = getattr(getattr(e, "response", None), "headers", {}) or {}
            if st == 429 and str(ra.get("Retry-After", "")).isdigit():
                wait = min(30.0, float(ra["Retry-After"]))
            _log(f"{label} 실패 → {wait:.0f}초 후 재시도 ({i + 1}/{tries - 1}): {str(e)[:120]}")
            time.sleep(wait)
    assert last is not None
    raise last


def fail(label: str, err: Exception | str | None = None) -> None:
    """끝내 못 가져온 항목을 기록 (같은 이름은 한 번만)."""
    if label not in FAILS:
        FAILS.append(label)
    if err is not None:
        _log(f"최종 실패 · {label}: {str(err)[:160]}")


def banner_html(fails: list[str] | None = None) -> str:
    fails = FAILS if fails is None else fails
    if not fails:
        return ""
    shown = fails[:12]
    more = f" 외 {len(fails) - len(shown)}건" if len(fails) > len(shown) else ""
    items = ", ".join(html.escape(x) for x in shown) + more
    return ('<div class="fetch-fail" style="background:#fff4d6;color:#5a4300;border:1px solid #f0d27a;'
            'padding:10px 14px;border-radius:10px;margin:14px 0;font-size:14px;line-height:1.6">'
            f'<b>⚠ 일부 데이터 없음</b> — {TRIES}번 다시 시도했지만 가져오지 못했습니다: {items}. '
            '해당 칸은 비어 있거나 "데이터 없음"으로 표시됩니다. 사이트가 일시적으로 응답하지 않은 경우가 많아 '
            '보통 다음 실행 때 돌아옵니다.</div>')


def inject_banner(page: str, fails: list[str] | None = None) -> str:
    b = banner_html(fails)
    if not b:
        return page
    if "</header>" in page:
        return page.replace("</header>", "</header>\n" + b, 1)
    return page.replace('<div class="wrap">', '<div class="wrap">' + b, 1)
