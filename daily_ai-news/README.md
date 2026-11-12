# daily_ai-news — AI 뉴스 종합 대시보드

매일 06:40(KST) GitHub Actions가 국내외 AI 뉴스·기업 공식 블로그·커뮤니티 피드를 모아 대시보드로 게시합니다.

| 섹션 | 내용 |
|---|---|
| ① 오늘의 핵심 | 기사·이야기·새 이야기 수, (선택) AI 브리핑 5줄, 여러 매체가 함께 다룬 이야기 TOP 10 |
| ② 숫자로 보는 오늘 | 기업·모델 언급 수, 분야별 이야기 수, 최근 7일 언급 추이 |
| ③ 분야별 뉴스 | 모델·제품 / 연구 / 정책·규제 / 투자·산업 / 국내 / 기타 (탭) |
| ④ 공식 발표 | OpenAI, Google DeepMind, Google AI, NVIDIA, Hugging Face 블로그 최근 7일 |

- 웹: https://hanlimy-sinkbig.github.io/reports/daily_ai-news/
- PDF: `latest.pdf` / 단축어용 정보: `latest.json` (`pdf_name`, `month`) — 구조는 daily_market-brief 와 동일
- 같은 이야기는 제목 단어 겹침으로 묶고, 묶음에 참여한 매체 수로 화제도를 셉니다.
- 'NEW'는 최근 7일 안에 처음 본 이야기입니다(`seen.json`). 7일 추이는 `history.json`에 쌓입니다.
- 출처는 `ai_news.py`의 `FEEDS`, 분류 키워드는 `CATEGORIES`, 기업 목록은 `ENTITIES`에서 바꿉니다.
- 선택: 저장소 Secrets 에 `ANTHROPIC_API_KEY`를 넣으면 'AI 브리핑' 5줄이 추가됩니다(사용량만큼 요금).
- 기사 본문은 싣지 않고 제목·짧은 설명·원문 링크만 게시합니다.

로컬 실행: `pip install -r requirements.txt && python ai_news.py --outdir out/daily_ai-news` (`--demo`로 가상 데이터 확인)
