# daily_baseball-insight — 야구 인사이트 대시보드

매일 07:05(KST) GitHub Actions가 한국·미국·일본 프로야구 순위와 주요 소식, 사회인야구 소식을 모아 게시합니다.

- 웹: https://hanlimy-sinkbig.github.io/reports/daily_baseball-insight/ · PDF `latest.pdf` · 단축어용 `latest.json`
- 섹션: ① 오늘의 헤드라인 ② KBO 순위·구단 정보·소식·스토브리그 ③ MLB 코리안리거·소식·최근 경기 결과·지구별 순위 ④ NPB 센트럴/퍼시픽 순위·구단 정보·소식(한국어+일본 현지) ⑤ 사회인야구·생활체육 야구 소식
- 데이터: KBO 기록실(koreabaseball.com), MLB Stats API(statsapi.mlb.com), NPB 공식(npb.jp), Google News RSS(제목·링크만)
- 비시즌(3월 전)에는 지난 정규시즌 최종 순위를 보여 줍니다. 사이트 구조가 바뀌어 순위를 못 가져오면 해당 칸에 안내와 출처 링크가 나옵니다.
- 구단 정보(연고지·홈구장)와 뉴스 검색어는 `baseball_data.py`에서 고칩니다.

로컬 실행: `pip install -r requirements.txt && python baseball_insight.py --outdir out/daily_baseball-insight` (`--demo` 가능)
