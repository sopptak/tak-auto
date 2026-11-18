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
- 게시 자동화는 승인 대기열을 통해서만 실행됩니다. 외부 게시 전에 사람의 승인과 플랫폼 게시 어댑터 설정이 필요하며, 기본 설정에서는 외부 게시가 비활성화되어 있습니다.

### 비용 및 제한
- Render 무료 인스턴스는 서버 절전 및 영구 디스크 미지원 제약이 있습니다. Starter와 Persistent Disk는 상시 실행과 파일 보존이 필요할 때만 비용을 확인한 뒤 선택하세요.
- Render 계정 연결, 비밀 환경변수 입력, 유료 서비스 생성은 계정 소유자가 직접 승인해야 합니다. 이 저장소 변경만으로 실제 서비스가 자동 생성되거나 공개 주소가 발급되는 것은 아닙니다.
- Perplexity 호출은 트렌드 조사 1회, 키워드 콘텐츠 생성 1회 이상이므로 API 사용료가 발생할 수 있습니다.

## 승인 기반 게시 대기열
- 생성된 초안에서 플랫폼과 한국시간 예약 시각을 지정해 운영자가 승인하면, 대기열이 `data/tak_auto_publishing_queue.json`에 저장됩니다. 기존 trend와 preview 저장 파일은 변경하지 않습니다.
- 웹 서버의 예약 작업자가 30초마다 예약 시각이 된 작업을 확인합니다. Render Persistent Disk를 사용하는 경우 재시작 뒤에도 대기열과 플랫폼별 게시 이력이 유지됩니다.
- 중복 방지 키는 콘텐츠 ID, 플랫폼, 게시 본문을 기준으로 결정적으로 계산합니다. 같은 항목을 다시 승인해도 새 작업이 만들어지지 않습니다.
- 실패 작업은 1분, 2분 간격으로 최대 3회 시도하며, 작업별 오류와 상태를 대시보드에 남깁니다. 성공 이력은 플랫폼, 콘텐츠 ID, 외부 게시 ID, 게시 시각별로 보관합니다.
- 외부 API가 요청을 받았는지 불분명한 경우는 자동 재시도하지 않고 `needs_review`로 멈춥니다. 작업 직전 상태를 디스크에 기록해 서버가 중단되어도 자동 중복 게시를 피합니다.
- `needs_review` 작업은 계정에서 게시 여부를 확인한 뒤, 외부 게시 ID로 완료 이력을 기록하거나 미게시 확인을 남기고 남은 시도 횟수 안에서 재예약할 수 있습니다.
- 실제 게시 기능은 Render 설정에서도 `TAK_AUTO_PUBLISHING_ENABLED=false`로 고정되어 있습니다. `true`와 `TAK_AUTO_PUBLISHER=모듈:함수`를 함께 명시한 경우에만 worker가 게시 어댑터를 호출합니다.
- `content_engine.trend_publishers:publish`는 Threads 텍스트, YouTube Shorts MP4, Instagram Reels, TikTok Direct Post MP4 어댑터를 제공합니다. Threads는 암호화된 OAuth 저장소의 `threads_content_publish` 권한을 우선 사용하고, 필요하면 기존 `THREADS_ACCESS_TOKEN` 환경변수를 사용할 수 있습니다. 대시보드의 **쇼츠 영상 파일 등록**에서 완성 MP4(최대 100MB)를 영구 디스크에 업로드하면 YouTube Shorts는 서버 파일 경로를 사용하고 Instagram Reels는 게시 시점에 48시간 HMAC 서명 HTTPS URL을 발급합니다. 미리보기 생성기는 영상 대본·장면 구성까지 담당하며 MP4 렌더링 자체는 별도이므로, 영상 편집/렌더링을 완료한 MP4를 등록해야 합니다. Threads·YouTube Shorts·Instagram Reels·TikTok Direct Post는 웹 예약 어댑터가 있습니다. TikTok은 video.publish 권한과 앱 Direct Post 승인이 필요하며, Facebook은 준비 중이고 네이버 블로그는 수동 게시입니다.
- 게시 대시보드에는 예약 상태, 시도 횟수, 오류, 플랫폼별 게시 이력이 표시됩니다. `TAK_AUTO_PUBLISHING_ENABLED`를 설정하지 않으면 대시보드에 비활성 상태로 표시되고 예약 작업은 외부 API를 호출하지 않습니다.
- 독립 worker 실행이 필요하면 `py scripts/run_publishing_queue.py --once`를 사용합니다. 지속 확인은 `py scripts/run_publishing_queue.py --watch`를 사용합니다. 웹 서버는 같은 persistent data 디렉터리를 쓰는 예약 작업자를 기본으로 시작합니다.

## 게시 계정 연결 현황
- 대시보드에서 YouTube, TikTok, Instagram, Threads, Facebook 페이지, 네이버 블로그의 인증 정보 설정 여부, 표시 계정명, 설정된 토큰 만료 시각을 카드 형태로 확인합니다. 비밀 토큰 원문은 화면에 표시하지 않습니다.
- 인증 정보가 등록되어 있다는 표시만으로 실제 계정 인증이 검증된 것은 아닙니다. 카드에는 연결 설정 여부와 계정 확인 여부를 구분합니다. 계정명은 플랫폼별 `*_USERNAME`, `*_CHANNEL_NAME`, `*_PAGE_NAME` 환경변수로, 선택 만료 시각은 각 플랫폼의 `*_ACCESS_TOKEN_EXPIRES_AT` ISO 8601 환경변수로 표시합니다.
- YouTube와 Threads 카드의 **계정 연결 확인** 버튼은 운영자가 눌렀을 때만 공식 프로필 API를 조회합니다. 성공한 계정 이름과 확인 시각은 영구 디스크에 보관하고 24시간 뒤 재확인을 요구합니다. 이 동작은 조회만 하며 게시하지 않습니다.
- TikTok·Instagram·Facebook의 실제 계정 검증 UI는 아직 준비되지 않았습니다. 이 카드는 설정 정보만 표시하며, API에 연결되지 않았음을 명시합니다.
- YouTube OAuth refresh token은 액세스 토큰을 자동 갱신합니다.
- 네이버 블로그는 자동 계정 연결 대신 수동 게시로 표시합니다. 네이버 블로그 글쓰기 Open API는 종료됐고 블로그 앱 URL Scheme도 지원 종료되어, 대시보드가 계정 비밀번호로 자동 게시를 시도하지 않습니다.
- Instagram/TikTok은 앱 승인·계정 권한과 영상 파일 준비가 필요합니다. YouTube Shorts도 승인된 MP4가 있어야 합니다. 이들 adapter가 설정되지 않으면 queue worker는 게시하지 않습니다.
- 기본 페이지 조회는 외부 플랫폼 API를 호출하지 않습니다. YouTube/Threads의 계정 연결 확인 버튼을 누를 때만 각 공식 프로필 API를 조회합니다. 토큰 원문은 화면·로그·확인 결과 파일에 저장하지 않고, API 오류는 안전한 요약만 표시합니다.


## Perplexity Agent API 전환

2026년 11월 기준 Sonar Chat Completions 방식 대신 Agent API를 사용합니다. 기존 `TAK_SCOUT_PERPLEXITY_API_KEY` 환경변수는 그대로 유지합니다. 기본 엔드포인트는 `/v1/agent`이며 `/v1/responses`와 동일한 API 표면입니다. 원시 HTTP 호출에서는 Perplexity 마이그레이션 가이드에 따라 `/v1/agent`를 사용합니다. 응답 텍스트는 `output[]`의 `message` / `output_text` 항목에서 읽고, 출처는 `search_results` 출력 항목의 `results[].url`에서 추출합니다.


## 게시 이력과 성과 수집 연결

새 트렌드 미리보기는 결정적인 `knowledge_id`(`trend-preview-<keyword hash>`)를 보존한다. 승인 시 각 플랫폼 작업 payload에 `_knowledge_id`와 첫 번째 원문 `_source_url`을 전달하며, 게시 대기열의 성공 이력은 다음 메타데이터를 남긴다.

- `content_id`: 플랫폼별 게시 작업의 고유 ID
- `knowledge_id`: 원본 트렌드 KNOWLEDGE ID
- `platform`: 실제 게시 채널
- `remote_id`: 플랫폼이 반환한 게시물/영상 ID
- `published_at`: 게시 완료 시각
- `source_url`, `title`: 원문 및 콘텐츠 제목

Threads와 Facebook의 게시 어댑터 이력에도 KNOWLEDGE ID, 출처 URL, 제목을 함께 보존한다. YouTube Shorts 등 다른 어댑터는 공통 게시 대기열 이력을 성과 추적의 기준으로 사용한다.

### 게시 이력에서 Threads/YouTube 성과 대상 선택

게시 대기열에 성공 이력이 생긴 뒤, `content_id`를 사용해 수동으로 ID를 다시 입력하지 않고 수집 대상을 지정할 수 있다.

```bash
# 대상 확인만 수행: 네트워크 호출 및 파일 저장 없음
python scripts/collect_performance.py \
  --queue-content-id <published-content-id> \
  --dry-run

# 실제 API 조회 및 성과 스냅샷 저장: 운영자가 명시적으로 승인한 경우에만
python scripts/collect_performance.py \
  --queue-content-id <published-content-id> \
  --confirm-live
```

현재 자동 API 수집은 Threads와 YouTube Shorts만 지원한다. Facebook, Instagram Reels, TikTok의 성과 API 수집은 별도 권한·지표 검증 후 추가한다. `--confirm-live` 없이 실제 API 호출은 거부되며, dry-run은 성과 저장소를 변경하지 않는다.


### 성과 수집 운영 주의사항

- 게시 대기열의 `content_id`는 플랫폼별·게시 작업별 식별자다. Threads 2개 초안은 서로 다른 두 개의 ID를 가지므로 각 게시 이력을 따로 추적한다.
- Threads 실측에는 `THREADS_ACCESS_TOKEN`과 Meta 앱에서 승인된 `threads_manage_insights` 권한이 필요하다.
- YouTube 실측에는 `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`이 필요하다.
- `--confirm-live`는 실제 외부 API 조회를 수행한다. 먼저 `--dry-run`으로 대상과 원격 ID를 확인하고, 운영자가 승인한 경우에만 실제 조회를 실행한다.
- 게시 성공만으로 성과 수집이 자동 실행되지는 않는다. 게시 이력을 근거로 명시적으로 수집 명령을 실행해야 하며, 수집된 스냅샷은 기존 `data/tak_performance.json`에 append-only로 저장된다.


### 주제별 성과 확인

콘텐츠 미리보기 카드의 KNOWLEDGE ID 링크는 공통 Performance Dashboard를 해당 원본 주제로 필터링해 연다.

```text
/performance?knowledge_id=<trend-preview-id>
```

같은 KNOWLEDGE에서 파생된 Threads와 YouTube 게시물은 한 화면에서 각각 별도 카드로 확인한다. 플랫폼별 조회수·반응을 임의로 합산하거나 서로 다른 측정 기준을 직접 비교하지 않는다. 성과 스냅샷이 아직 없으면 해당 주제의 미수집 상태를 표시한다. Dashboard는 읽기 전용이며 수집이나 게시를 실행하지 않는다.
