# daily_ai-news — AI 뉴스 종합 대시보드

매일 06:40(KST) GitHub Actions가 국내외 AI 뉴스·기업 공식 블로그·커뮤니티 피드를 모아 대시보드로 게시합니다.

| 섹션 | 내용 |
|---|---|
| ① 오늘의 핵심 | 기사·이야기·새 이야기 수, (선택) AI 브리핑 5줄, 여러 매체가 함께 다룬 이야기 TOP 10 |
| ② 이번 주 흐름 | 최근 7일 가장 임팩트 있는 흐름 TOP 7, 오늘 뉴스가 주간 흐름과 이어지는지·달라졌는지 해설, 기업 언급 변화 |
| ③ 숫자로 보는 오늘 | 기업·모델 언급 수, 분야별 이야기 수, 최근 7일 언급 추이 |
| ④ 분야별 뉴스 | 모델·제품 / 연구 / 정책·규제 / 투자·산업 / 국내 / 기타 (탭) |
| ⑤ 공식 발표 | OpenAI, Google DeepMind, Google AI, NVIDIA, Hugging Face 블로그 최근 7일 |

- 웹: https://hanlimy-sinkbig.github.io/reports/daily_ai-news/
- PDF: `latest.pdf` / 단축어용 정보: `latest.json` (`pdf_name`, `month`) — 구조는 daily_market-brief 와 동일
- 같은 이야기는 제목 단어 겹침으로 묶고, 묶음에 참여한 매체 수로 화제도를 셉니다.
- 'NEW'는 최근 7일 안에 처음 본 이야기입니다(`seen.json`). 7일 추이는 `history.json`에 쌓입니다.
- **주간 흐름**: 매일 상위 40개 이야기를 `stories.json`(14일 보관)에 쌓고, 날짜를 넘어 같은 사건을 묶습니다.
  ① 여러 기사에 함께 나오는 핵심어 쌍(예: `anthropic+ipo`, `nvidia+huang`)으로 큰 사건을 묶고 ② 나머지는 제목 단어 겹침으로 묶습니다.
  한국어 제목은 `KO_ALIAS`(예: 젠슨→huang, 상장→ipo)로 영어 제목과 잇습니다.
- **임팩트** = 다룬 매체 수×2 + 이어진 날 수×4 + 하루 최고 화제도×0.5 (하루 반짝보다 여러 날 이어진 사건을 우대)
- **오늘 상태**: 새 흐름(오늘 처음) · 확대(이전 평균의 1.3배 이상) · 지속 · 축소(0.7배 이하) · 재부상(하루 이상 끊겼다 다시) · 잠잠(오늘 없음).
  TOP 10 이야기에도 '3일째 흐름 · 확대' 같은 배지가 붙습니다.
- 첫 실행 때 `stories.json`이 없으면 지난 `archive/*.html`에서 최근 6일치를 복원합니다.
- `ANTHROPIC_API_KEY`가 있으면 **사건 묶기도 AI가 합니다**: 최근 7일 이야기 제목 전체를 보내 '같은 사건'끼리 묶고 짧은 한국어 이름(예: '젠슨 황 사임·엔비디아 사태')을 붙입니다.
  표현이 달라도(scandal·turmoil·사임) 뜻으로 묶습니다. 키가 없거나 호출이 실패하면 위의 핵심어 규칙으로 자동 대체되고, 페이지 해설 아래에 어떤 방식으로 묶었는지 표시됩니다.
  흐름 해설(4~5줄)도 AI가 씁니다. 모델은 환경변수 `FLOW_LLM_MODEL`(없으면 `BRIEF_LLM_MODEL`, 기본 claude-sonnet-5-5)로 바꿉니다.
- 출처는 `ai_news.py`의 `FEEDS`, 분류 키워드는 `CATEGORIES`, 기업 목록은 `ENTITIES`에서 바꿉니다.
- 선택: 저장소 Secrets 에 `ANTHROPIC_API_KEY`를 넣으면 'AI 브리핑' 5줄이 추가됩니다(사용량만큼 요금).
- 기사 본문은 싣지 않고 제목·짧은 설명·원문 링크만 게시합니다.

로컬 실행: `pip install -r requirements.txt && python ai_news.py --outdir out/daily_ai-news` (`--demo`로 가상 데이터 확인)
