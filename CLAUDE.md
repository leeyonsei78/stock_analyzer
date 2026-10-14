# 종목 검색기 (Theme Scanner · Analyst)

유튜브 "주식 초보자가 종목 분석기로 급등주를 잡는 법" 영상의 프로그램을 참고해 새로 만든 한국 주식 수급 테마 스캐너 + 종목 분석기.
저장소: https://github.com/leeyonsei78/stock_analyzer (branch `main`)

## 실행
```
pip install -r requirements.txt
python server.py        # http://127.0.0.1:8000
```
- 키는 `.env`에 둔다 (`.env.example` 참고, git 제외): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DART_API_KEY`.
- 엔진 선택: `ANALYZER_PROVIDER=openai|anthropic` (미지정 시 키가 있는 쪽, openai 모델은 `OPENAI_MODEL`, 기본 gpt-4o).
- 키가 없거나 호출 실패 시 규칙 기반으로 대체되고, 화면에 사유가 표시된다.
- 서버 종료: `taskkill /F /IM python.exe` (로그는 `server.log`).

## 구조
- `server.py` FastAPI. `/api/scan`(백그라운드 job + 폴링), `/api/analyze`, `/api/status`, `/` → `static/index.html`
- `static/index.html` 순수 HTML/JS 단일 페이지 (STEP 1 수급 테마 검색 / STEP 2 종목 분석)
- `scanner.py` 5일 누적 상승률·거래량 배수·상승일 수·시총으로 후보 필터. 일별 캐시 `.cache/`
- `themes.py` 후보를 테마로 묶고 트리거/대장주/수혜주 생성 (LLM, 없으면 업종별 묶음)
- `report.py` 7단계 리포트 (기본정보→공시·재료→테마→수급→차트→리스크→최종판단[단기 1~4주/중장기 3~12개월])
- `data.py` KRX 목록/시세(FinanceDataReader), 네이버 모바일 API(`m.stock.naver.com/api`), DART
- `analyzer.py` 지표 계산(이동평균/RSI/MACD/볼린저/거래량비)
- `llm.py` OpenAI/Anthropic 래퍼 + `.env` 로더

## 주의/배운 점
- 네이버 PC 증권 페이지(finance.naver.com)는 React로 바뀌어 HTML 스크래핑 불가 → 모바일 JSON API 사용.
- 윈도우 콘솔은 한글이 깨져 보인다(cp949). 확인할 때 `PYTHONIOENCODING=utf-8` 사용. curl로 한글 JSON을 보내면 400 → python requests 사용.
- 영상의 판단 기준은 비공개라 판단 로직(규칙 기반 점수)은 임의 구현이다. 투자 참고용 면책 문구 유지.

## 상태 / 다음 할 일
- 완료: STEP 1·2 동작, OpenAI 연동 확인, GitHub 반영.
- 아직 안 한 것: Anthropic 경로 실사용 확인, DART 키 연동 확인, 영상의 3-엔진(OpenAI/Claude/Gemini) 병렬 분석, 6단계 항목 영상과 일치 여부 확인, 테스트 코드.
