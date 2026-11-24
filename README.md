# reports

GitHub Actions가 자동으로 만드는 개인 리포트 모음입니다. 결과는 GitHub Pages로 게시됩니다.

- 목록: https://hanlimy-sinkbig.github.io/reports/
- 이번달 식단 추천 (매일 06:15): https://hanlimy-sinkbig.github.io/reports/daily_meal-plan/
- 시장 브리핑 (평일 06:30): https://hanlimy-sinkbig.github.io/reports/daily_market-brief/
- AI 뉴스 대시보드 (매일 06:40): https://hanlimy-sinkbig.github.io/reports/daily_ai-news/
- 교육·입시 인사이트 (매일 06:50): https://hanlimy-sinkbig.github.io/reports/daily_edu-insight/
- 야구 인사이트 (매일 07:05): https://hanlimy-sinkbig.github.io/reports/daily_baseball-insight/
- 포트폴리오 대시보드 (평일 07:20·16:10 시세 갱신, 매매일지는 브라우저에서만 읽음): https://hanlimy-sinkbig.github.io/reports/daily_portfolio-dashboard/

## 이름 규칙
- 모두 소문자. 구획 사이는 `_`, 한 구획 안 단어 사이는 `-` → `<주기>_<주제>`
- 예: `daily_market-brief`, `daily_ai-news`, `weekly_kids-edu`
- 리포트 하나 = 폴더 하나(`<이름>/`) + 워크플로 하나(`.github/workflows/<이름>.yml`) + 게시 경로 하나(`/reports/<이름>/`)

## 구조
```
main 브랜치 (코드만)                      gh-pages 브랜치 (결과물, 매번 이력 없이 덮어씀)
├── .github/workflows/                    ├── index.html               리포트 목록
│   ├── daily_market-brief.yml            ├── daily_market-brief/
│   └── daily_ai-news.yml                 ├── daily_ai-news/   (구조 동일)
│                                         └── daily_market-brief/
└── daily_market-brief/                       ├── index.html           오늘 웹페이지
    ├── market_brief.py                       ├── latest.pdf           오늘 PDF (단축어가 아이클라우드로 저장)
    ├── brief_pdf.py                          ├── latest.json          단축어용 파일명·날짜 정보
    ├── requirements.txt                      └── archive/             지난 웹페이지 (최근 365일)
    └── README.md
```

## 새 리포트 추가 규칙
- 워크플로는 반드시 ① 기존 gh-pages 게시본을 먼저 가져오고 ② 자기 폴더만 바꾼 뒤 ③ `concurrency: gh-pages`로 게시해야 다른 리포트가 지워지지 않습니다.
- 네트워크 요청은 `_shared/net_retry.py`의 `NR.retry()`로 감싸고, 끝내 실패하면 `NR.fail("항목 이름")`으로 기록한 뒤 `NR.inject_banner(page)`로 페이지에 안내를 넣습니다.

## 실패 처리 (`_shared/net_retry.py`)
- 연결 오류·시간 초과·429(요청 과다)·5xx는 최대 3번 시도(3초 → 6초 쉬고). 404처럼 다시 해도 같은 오류는 바로 포기.
- 끝내 못 받은 항목은 페이지 맨 위 노란 상자 **"⚠ 일부 데이터 없음"**과 PDF 첫 장에 이름이 나오고, 해당 칸은 "데이터 없음"으로 표시됩니다.
- 핵심 데이터가 통째로 없으면 빈 페이지로 덮어쓰지 않고 실패로 끝납니다 → 어제 페이지가 그대로 남고 GitHub이 실패 메일을 보냅니다.
  - 시장 브리핑: 나스닥·코스피 시세 둘 다 없음 / AI 뉴스: 기사 0건 / 포트폴리오: 기존 종목 시세 0건
- 포트폴리오 화면은 시세가 없거나 4일 넘게 뒤처진 종목을 경고 줄에 따로 표시합니다.
