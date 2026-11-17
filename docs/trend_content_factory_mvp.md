# TAK AUTO Trend Content Factory MVP

## 목적
최신 공개 웹 트렌드를 Perplexity Agent API로 발굴하고, 키워드별 콘텐츠 기회를 제시한 뒤 블로그·YouTube Shorts·Threads 초안을 빠르게 미리 보는 로컬 웹 MVP입니다. 법원경매 등 특정 분야에 고정하지 않습니다.

## 실행 (Windows PowerShell)
```powershell
git fetch origin
# 로컬 브랜치가 이미 있으면:
git switch feature/trend-content-factory-mvp
# 처음 받는 PC라 로컬 브랜치가 없으면 위 switch 대신:
# git switch --track origin/feature/trend-content-factory-mvp
git pull origin feature/trend-content-factory-mvp
$env:TAK_SCOUT_PERPLEXITY_API_KEY = "실제 Perplexity API 키"
py scripts/run_trend_content_mvp.py
```
브라우저에서 `http://127.0.0.1:8765`를 엽니다.

## 사용
1. **Perplexity 최신 트렌드 TOP 20 조사**를 누릅니다.
2. 분야가 섞인 최근 7일 트렌드 후보와 출처, 독자 질문, 콘텐츠 관점을 확인합니다.
3. 원하는 키워드에서 **이 키워드로 콘텐츠 패키지 생성**을 누릅니다.
4. 선택 키워드에 대해 Perplexity가 추가 조사·작성한 블로그 1편, 약 60초 쇼츠 1편(장면별 구성), Threads 2편을 확인합니다. 콘텐츠 생성 시 API 호출이 한 번 더 발생합니다.

## 데이터와 안전
- Perplexity Agent API는 `POST https://api.perplexity.ai/v1/agent`를 사용합니다. API 키는 `TAK_SCOUT_PERPLEXITY_API_KEY` 환경변수로만 읽으며 저장소에 기록하지 않습니다. 기본 검색 모델은 `perplexity/sonar`이며 웹 검색 도구와 최근성 필터를 명시적으로 전달합니다.
- 조사 결과: `data/tak_auto_live_trends.json`
- 콘텐츠 미리보기: `data/tak_auto_content_previews.json`
- 미리보기는 생성 품질 확인용이며 승인된 콘텐츠, Production Archive, 게시 상태가 아닙니다. 콘텐츠 생성은 Perplexity 추가 호출을 사용하며, 응답 JSON/분량 검증에 실패하면 초안을 저장하지 않고 오류를 표시합니다.
- 실제 게시 전에는 각 출처 원문, 날짜, 사실관계를 확인해야 합니다.
- Perplexity가 반환한 순서는 검색량 순위가 아닙니다. 검색량·SNS 도달·경쟁도를 측정했다고 주장하지 않습니다.
- 로컬 실행은 127.0.0.1에 바인딩할 수 있으며, 클라우드 실행은 별도 Render 서비스에서 0.0.0.0 및 Render PORT에 바인딩합니다.

## 테스트
```powershell
py -m unittest discover -s tests -p "test_perplexity_research.py" -v
py -m unittest discover -s tests -p "test_trend_discovery.py" -v
```

## 클라우드 웹 실행 (PC 상시 실행 불필요)

이 브랜치의 `render.yaml`에는 기존 서비스 설정을 유지하면서 별도 웹 서비스 `tak-auto-trend-factory`를 추가했습니다. Render의 Persistent Disk에 조사 결과와 콘텐츠 초안을 저장합니다.

### 최초 배포
1. Render 계정에서 **New + → Blueprint**를 선택합니다.
2. GitHub 저장소 `sopptak/tak-auto`를 연결합니다.
3. 브랜치 `feature/trend-content-factory-mvp`를 선택하고 Blueprint를 생성합니다.
4. Blueprint 리소스 중 `tak-auto-trend-factory`가 추가되는지 확인합니다. 기존 `tak-auto-mvp` 서비스가 이미 연결되어 있다면 중복 생성하지 않도록 리소스 목록을 먼저 확인합니다.
5. 새 서비스의 Environment에 아래 3개 값을 입력합니다.
   - `TAK_WEB_USERNAME`: 웹 로그인 아이디
   - `TAK_WEB_PASSWORD`: 충분히 길고 추측하기 어려운 웹 로그인 비밀번호
   - `TAK_SCOUT_PERPLEXITY_API_KEY`: Perplexity API 키
6. 저장 후 배포가 끝나면 Render가 제공하는 `https://...onrender.com` 주소로 접속합니다. 브라우저의 인증 창에 위 아이디와 비밀번호를 입력합니다.

### 운영 방식
- Render가 GitHub 브랜치의 코드를 받아 빌드하고 웹 서버를 실행합니다.
- 서버는 `0.0.0.0` 및 Render가 지정하는 `PORT`에서 실행됩니다.
- `/health`는 호스팅 상태 확인용이며, 실제 화면과 작업 요청은 Basic Authentication으로 보호됩니다.
- POST 요청은 동일 출처 검사를 통과해야 처리됩니다.
- Persistent Disk를 연결한 경우 데이터는 `/var/data/trend-factory`에 저장되어 일반 재배포 후에도 유지됩니다. 무료 인스턴스에는 Persistent Disk를 연결할 수 없으므로 무료 운영 중에는 인스턴스 재시작·재배포 시 로컬 파일이 보존되지 않을 수 있습니다.
- Perplexity API 키와 웹 비밀번호는 GitHub에 넣지 않습니다. Render 대시보드의 비밀 환경변수로만 등록합니다.
- 게시 자동화는 연결하지 않았습니다. 생성 결과는 검토용 초안이며, 외부 게시 전 사람의 승인이 필요합니다.

### 비용 및 제한
- Render 무료 인스턴스는 서버 절전 및 영구 디스크 미지원 제약이 있습니다. Starter와 Persistent Disk는 상시 실행과 파일 보존이 필요할 때만 비용을 확인한 뒤 선택하세요.
- Render 계정 연결, 비밀 환경변수 입력, 유료 서비스 생성은 계정 소유자가 직접 승인해야 합니다. 이 저장소 변경만으로 실제 서비스가 자동 생성되거나 공개 주소가 발급되는 것은 아닙니다.
- Perplexity 호출은 트렌드 조사 1회, 키워드 콘텐츠 생성 1회 이상이므로 API 사용료가 발생할 수 있습니다.


## Perplexity Agent API 전환

2026년 11월 기준 Sonar Chat Completions 방식 대신 Agent API를 사용합니다. 기존 `TAK_SCOUT_PERPLEXITY_API_KEY` 환경변수는 그대로 유지합니다. 기본 엔드포인트는 `/v1/agent`이며 `/v1/responses`와 동일한 API 표면입니다. 원시 HTTP 호출에서는 Perplexity 마이그레이션 가이드에 따라 `/v1/agent`를 사용합니다. 응답 텍스트는 `output[]`의 `message` / `output_text` 항목에서 읽고, 출처는 `search_results` 출력 항목의 `results[].url`에서 추출합니다.
