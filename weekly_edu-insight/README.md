# weekly_edu-insight — 교육·입시 인사이트 대시보드

매주 월요일 06:50(KST) GitHub Actions가 정리된 입시 정보와 최근 7일 교육 뉴스를 합쳐 게시합니다.

- 웹: https://hanlimy-sinkbig.github.io/reports/weekly_edu-insight/ · PDF `latest.pdf` · 단축어용 `latest.json`
- 섹션: ① 핵심 요약·학생 타임라인 ② 의대 정원·합격선 ③ 고교 유형(영재고·과학고·자사고·일반고) ④ 설카포·서성한 ⑤ 의대 지망 조언·선택과목 로드맵 ⑥ 이번 주 뉴스
- 정리 데이터는 `edu_data.py` 한 파일에 있습니다(기준일 `UPDATED`). 새 정책·입결이 나오면 이 파일만 고치면 됩니다.
- 뉴스는 자동, 정리 데이터는 수동 갱신입니다. 수치는 보도 기준이며 최종 판단은 학교·대학 공식 요강으로 확인하세요.
- 공개 페이지이므로 학생 이름·학교 등 개인 식별 정보는 넣지 않습니다.

로컬 실행: `pip install -r requirements.txt && python edu_insight.py --outdir out/weekly_edu-insight` (`--demo` 가능)
