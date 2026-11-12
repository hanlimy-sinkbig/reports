# daily_market-brief — 모닝 마켓 브리핑

평일 아침 GitHub Actions가 아래 5개 섹션 리포트를 만들어 GitHub Pages에 게시합니다.
PDF는 아이패드 단축어 자동화가 받아 아이클라우드 드라이브에 월별로 저장합니다.

| 섹션 | 내용 |
|---|---|
| ① 지수 | 나스닥 종합·코스피 6개월 캔들(20/60일선), S&P500·나스닥100·SOX·코스닥·VIX·미10년물·원달러, 자동 요약 |
| ② 섹터 히트맵 | 미국 대형주 44개 / 코스피 대형주 30개 트리맵(면적=시총, 색=전일 등락), 섹터 등락 막대 |
| ③ 주요 종목 차트 | '이상 움직임 점수'(전일 등락 ÷ 20일 평균 변동폭 × √거래량 배수)로 미국·한국 각 3종목 자동 선정 |
| ④ 선정 이유·뉴스 | 변동 크기·거래량·52주 고저·이평선 돌파 + Google News 최근 3일 기사 |
| ⑤ 연관 종목 분석 | 같은 업종 + 공급망·한미 연관주 성과·60일 상관(한미 시차 반영)·해석 |

## 보는 곳
| 무엇 | 어디 |
|---|---|
| 오늘 웹페이지 | https://hanlimy-sinkbig.github.io/reports/daily_market-brief/ |
| 지난 웹페이지 (최근 365일) | https://hanlimy-sinkbig.github.io/reports/daily_market-brief/archive/ |
| 오늘 PDF | https://hanlimy-sinkbig.github.io/reports/daily_market-brief/latest.pdf |
| 지난 PDF | 아이클라우드 드라이브 `reports/daily_market-brief/YYYY-MM/MMDD_요일.pdf` |

## 실행 일정
- 평일 07:30 KST 예약(`.github/workflows/daily_market-brief.yml`). GitHub 예약 실행은 늦어질 수 있어 보통 8시 전후 완료.
- 한국·미국이 모두 휴장이라 새 데이터가 없으면 건너뜁니다.
- 수동 실행: 저장소 **Actions → daily_market-brief → Run workflow** (`force` 체크 시 휴장일에도 생성)
- 선택: 저장소 Settings → Secrets → Actions 에 `ANTHROPIC_API_KEY` 를 넣으면 종목별 뉴스 요약 한 줄 추가

## 아이패드 단축어 (PDF → 아이클라우드)
`latest.json`에서 파일명(`pdf_name`, 예: `1113_금.pdf`)과 월(`month`, 예: `2026-11`)을 읽고,
`latest.pdf`를 받아 `iCloud Drive/reports/daily_market-brief/<month>/<pdf_name>`으로 저장합니다.
매일 08:30 개인용 자동화로 실행합니다("즉시 실행", 같은 이름이면 덮어쓰기).

## 로컬(맥) 실행도 가능
```bash
pip install -r requirements.txt
python market_brief.py --outdir <폴더>                 # latest.* + YYYY-MM/MMDD_요일.* (드라이브용)
python market_brief.py --layout site --outdir _site/daily_market-brief   # Pages용 구조
python market_brief.py --demo                          # 인터넷 없이 가상 데이터로 레이아웃 확인
```

## 커스터마이즈
- 종목 유니버스: `US_UNIVERSE`, `KR_UNIVERSE` / 연관 관계: `CROSS_LINKS`
- 보관 기간: 워크플로의 실행 명령에 `--keep-days 365` 조정
- 색상(상승=빨강, 하락=파랑): HTML은 CSS `--up/--down`, PDF는 `brief_pdf.py`의 `UP/DOWN`

무료 데이터(Yahoo Finance·Google News)라 지연·누락이 있을 수 있습니다. 투자 판단 전 원 출처를 확인하세요.
