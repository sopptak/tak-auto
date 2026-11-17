# TAK AUTO와 기존 TAK SCOUT Dashboard 통합

## 원칙
별도 대시보드를 중복 운영하지 않는다. 기존 `scripts/run_scout_dashboard.py`를 통합 운영 화면으로 유지하고, TAK AUTO의 일일 트렌드 리포트를 읽기 전용 화면으로 붙인다.

## 화면
- `/`: 기존 SCOUT 소재·인터뷰
- `/trends`: TAK AUTO 반복 키워드, 급상승 후보, 콘텐츠 기회
- `/research`: Perplexity 조사 기록
- `/research/{scout_id}`: 조사 내용·인용 URL·기록 완성도·KNOWLEDGE 검토 초안 생성
- 기존 Threads 검수, MEDIA, Shorts Studio, Performance, MONEY 화면은 기존 경로를 유지한다.

## 데이터 흐름
1. 일일 RSS 수집 및 트렌드 리포트가 `data/tak_auto_trend_daily.json`을 생성한다.
2. 기존 Dashboard의 `/trends`가 이 파일을 읽어 키워드 목록을 표시한다.
3. 기회 후보의 근거 소재는 SCOUT 후보 ID와 연결된다.
4. 기존 SCOUT 홈에서 소재별 Perplexity 조사를 실행한다.
5. `/research/{scout_id}`에서 출처를 검토하고 필요하면 pending KNOWLEDGE를 만든다.
6. 승인된 KNOWLEDGE만 기존 TAK MEDIA 생성 파이프라인의 입력이 된다.

## 안전 경계
- 새 트렌드 화면은 읽기 전용이다.
- 심층 조사 API 호출은 사용자가 소재별 조사 버튼을 누를 때만 실행된다.
- 조사 결과는 자동 사실 검증이나 KNOWLEDGE 승인으로 간주하지 않는다.
- MEDIA 생성은 승인된 KNOWLEDGE만 사용한다.
- 실제 SNS 게시 및 외부 공개는 기존 승인·발행 절차를 우회하지 않는다.

## 실행
기존 Dashboard 실행 명령을 그대로 사용한다. 데이터가 없으면 `/trends`에 수집 안내가 표시된다. 별도 웹 프레임워크나 의존성은 추가하지 않는다.

## 조사 결과에서 콘텐츠 초안으로
Perplexity 조사 결과를 KNOWLEDGE로 연결할 때 조사 본문의 명시적 문단·불릿을 key_points로 보존한다. 승인된 외부 정보형 KNOWLEDGE는 TAK MEDIA 생성기에서 factual_information, summary, key_points를 근거 단위로 사용한다. 조사 내용을 개인 경험이나 작성자 의견으로 바꾸지 않는다. 생성물은 Blog 1, Shorts 3, Threads 5개이며 각 초안은 원문 URL, 인용 근거, 근거 단위 ID를 유지한다. 승인 전 외부 게시를 허용하지 않는다.

자동 테스트는 `tests/test_research_media_bridge.py`에서 승인 전 차단 원칙과 승인 후 9개 초안 생성, 출처·근거 추적성을 확인한다.
