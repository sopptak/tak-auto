# TAK AUTO Trend Content Factory MVP

## 목적
최신 공개 웹 트렌드를 Perplexity로 발굴하고, 키워드별 콘텐츠 기회를 제시한 뒤 블로그·YouTube Shorts·Threads 초안을 빠르게 미리 보는 로컬 웹 MVP입니다. 법원경매 등 특정 분야에 고정하지 않습니다.

## 실행 (Windows PowerShell)
```powershell
git switch feature/trend-content-factory-mvp
git pull origin feature/trend-content-factory-mvp
$env:TAK_SCOUT_PERPLEXITY_API_KEY = "실제 Perplexity API 키"
py scripts/run_trend_content_mvp.py
```
브라우저에서 `http://127.0.0.1:8765`를 엽니다.

## 사용
1. **Perplexity 최신 트렌드 TOP 20 조사**를 누릅니다.
2. 분야가 섞인 최근 7일 트렌드 후보와 출처, 독자 질문, 콘텐츠 관점을 확인합니다.
3. 원하는 키워드에서 **이 키워드로 콘텐츠 패키지 생성**을 누릅니다.
4. 블로그 1편, 쇼츠 3편, Threads 5편의 초안을 확인합니다.

## 데이터와 안전
- API 키는 `TAK_SCOUT_PERPLEXITY_API_KEY` 환경변수로만 읽으며 저장소에 기록하지 않습니다.
- 조사 결과: `data/tak_auto_live_trends.json`
- 콘텐츠 미리보기: `data/tak_auto_content_previews.json`
- 미리보기는 생성 품질 확인용이며 승인된 콘텐츠, Production Archive, 게시 상태가 아닙니다.
- 실제 게시 전에는 각 출처 원문, 날짜, 사실관계를 확인해야 합니다.
- Perplexity가 반환한 순서는 검색량 순위가 아닙니다. 검색량·SNS 도달·경쟁도를 측정했다고 주장하지 않습니다.
- 초기 MVP 서버는 127.0.0.1에만 바인딩하며 외부 공개 배포는 하지 않습니다.

## 테스트
```powershell
py -m unittest discover -s tests -p "test_trend_discovery.py" -v
```
