# reports

GitHub Actions가 자동으로 만드는 개인 리포트 모음입니다. 결과는 GitHub Pages로 게시됩니다.

- 목록: https://hanlimy-sinkbig.github.io/reports/
- 시장 브리핑: https://hanlimy-sinkbig.github.io/reports/daily_market-brief/

## 이름 규칙
- 모두 소문자. 구획 사이는 `_`, 한 구획 안 단어 사이는 `-` → `<주기>_<주제>`
- 예: `daily_market-brief`, `daily_ai-news`, `weekly_kids-edu`
- 리포트 하나 = 폴더 하나(`<이름>/`) + 워크플로 하나(`.github/workflows/<이름>.yml`) + 게시 경로 하나(`/reports/<이름>/`)

## 구조
```
main 브랜치 (코드만)                      gh-pages 브랜치 (결과물, 매번 이력 없이 덮어씀)
├── .github/workflows/                    ├── index.html               리포트 목록
│   └── daily_market-brief.yml            └── daily_market-brief/
└── daily_market-brief/                       ├── index.html           오늘 웹페이지
    ├── market_brief.py                       ├── latest.pdf           오늘 PDF (단축어가 아이클라우드로 저장)
    ├── brief_pdf.py                          ├── latest.json          단축어용 파일명·날짜 정보
    ├── requirements.txt                      └── archive/             지난 웹페이지 (최근 365일)
    └── README.md
```
