# TAK AUTO — Performance(성과) 데이터 운영 가이드

이 문서는 사람(티몽)이 성과 데이터 기능을 실제로 운영할 때 참고하는 문서다.
날짜가 붙은 `docs/6-01_*.md`/`docs/6-02_*.md`는 "그 세션에 무엇을 조사/구현했는지"를
기록한 작업 로그이고, 이 문서는 "지금 이 기능을 어떻게 쓰는지"를 정리한 operations
문서다 - 기능이 바뀌면 이 문서를 갱신한다(작업 로그는 과거 시점 그대로 둔다).

## 1. Performance 데이터가 무엇인지

TAK AUTO는 콘텐츠를 KNOWLEDGE → MEDIA → 사람 승인 → 발행까지 자동/반자동으로 진행한다.
Performance는 그 다음 단계다: **이미 발행된 콘텐츠가 실제로 얼마나 반응을 얻었는지**
(조회수, 좋아요 등)를 시간에 따라 기록하는 계층이다.

```
KNOWLEDGE → MEDIA → HUMAN REVIEW → PUBLISH PREPARATION → PUBLISH → PERFORMANCE → (사람이 본다)
```

Performance는 **콘텐츠를 자동으로 만들거나 고치지 않는다.** 숫자를 모아서 사람이
볼 수 있게 보여주는 것까지만 한다(11장/12장에서 이 경계를 다시 강조한다).

## 2. PerformanceRecord 구조

`content_engine/performance/models.py`의 `PerformanceRecord`. 콘텐츠 1건의
**특정 시점** 성과 스냅샷 1건을 표현한다(현재값 하나를 덮어쓰는 게 아니다 - 6장).

| 필드 | 설명 |
|---|---|
| `content_id` | archive/발행 이력의 content_id(이미 계산된 값을 그대로 받음) |
| `knowledge_id` | 원본 KNOWLEDGE ID |
| `platform` | `threads` / `youtube` / `blog` |
| `published_at` | 원본이 실제로 발행된 시각(불변) |
| `metric_collected_at` | **이 스냅샷을 수집한 시각** - 이 값이 다르면 같은 콘텐츠라도 별도 스냅샷으로 계속 쌓인다 |
| `metrics` | `{"views": 850, "likes": 12}`처럼 플랫폼마다 다른 지표를 담는 dict(정수만 허용) |
| `source` | `threads_api` / `youtube_api` / `manual` / `migration_baseline` - 8장 참고 |
| `title` | 콘텐츠 제목(선택, 화면 표시용) |
| `external_id` | 플랫폼별 원본 식별자(threads media id / youtube video id / blog url) |
| `raw` | collector가 받은 원본 응답(정규화 이전, 감사용, 선택) |

## 3. Threads 성과 수집 방법

```bash
python3 scripts/collect_performance.py --platform threads \
    --content-id content-abc123 --knowledge-id knowledge-xyz \
    --published-at 2026-09-15T00:00:00+00:00 \
    --external-id <threads_post_id> \
    --confirm-live
```

- `--external-id`는 `data/threads_publish_log.json`의 `threads_post_id`(Threads media id)다.
- 실제로 `THREADS_ACCESS_TOKEN`이 필요하고, 공식 media insights 엔드포인트
  (`GET /{threads-media-id}/insights`, `views`/`likes`/`replies`/`reposts`/`quotes`/`shares`)를 호출한다.
- **`--confirm-live`를 반드시 함께 줘야 한다**(9장 안전 규칙).

## 4. YouTube 성과 수집 방법

```bash
python3 scripts/collect_performance.py --platform youtube \
    --content-id content-abc123 --knowledge-id knowledge-xyz \
    --published-at 2026-09-15T00:00:00+00:00 \
    --external-id <video_id> \
    --confirm-live
```

- `--external-id`는 `data/youtube_publish_log.json`의 `video_id`다.
- `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN`이 필요하고,
  `videos.list(part=statistics)`(`viewCount`/`likeCount`/`commentCount`)를 호출한다.
- 이 CLI 실행 시 넘기는 `--content-id`/`--knowledge-id`는 **업로드 시점에
  `scripts/upload_youtube_short.py --content-id ... --knowledge-id ...`로 이미
  기록해 둔 값과 같아야 한다**(8장 - 업로드 이력과 별개로 사람이 다시 입력하는
  것이므로, 실수로 다른 값을 넣으면 성과가 엉뚱한 KNOWLEDGE에 연결된다).

## 5. Blog 성과 수집 방법

네이버는 블로그 조회수를 조회할 수 있는 공식 공개 API를 제공하지 않는다(6-01 조사
결과, 2026-09-20 웹 검색으로 확인). 그래서 Blog는 **항상 사람이 네이버 블로그
관리자 페이지("통계" 메뉴)에서 직접 확인한 숫자를 CLI로 수동 입력**한다:

```bash
python3 scripts/collect_performance.py --platform blog \
    --content-id content-abc123 --knowledge-id knowledge-xyz \
    --published-at 2026-09-15T00:00:00+00:00 \
    --metric views=850 --metric likes=12
```

`--confirm-live`가 필요 없다(애초에 네트워크 호출이 없다). `--metric key=value`를
여러 번 지정할 수 있다.

## 6. Snapshot 개념

같은 `content_id`에 대해 `collect_performance.py`를 여러 날짜에 걸쳐 반복 실행하면,
매번 새 스냅샷이 **추가**된다(덮어쓰지 않는다):

```
Day1: views=100   (metric_collected_at=2026-09-15)
Day3: views=430   (metric_collected_at=2026-09-17)
Day7: views=2,300 (metric_collected_at=2026-09-21)
```

`data/tak_performance.json` 하나에 모든 채널의 스냅샷이 함께 쌓인다(`platform`
필드로 구분 - 채널별 파일 분리하지 않음, archive/threads_review와 동일한 관례).

**중복 방지 규칙(의도된 동작)**: `(content_id, metric_collected_at)` 조합이
이미 저장소에 있으면, `source`가 다르더라도 새로 저장하지 않고 조용히
건너뛴다(idempotent). "같은 순간을 다른 source로 다시 측정해 이전 값을 교정하고
싶다"는 요구가 실제로 생기면 `append_snapshot`에 `overwrite=True` 같은 옵션을
추가하는 것을 검토한다 - 아직 실제로 필요했던 적이 없어 미리 만들지 않았다.

## 7. content_id / knowledge_id 연결 규칙

- **Threads/Blog**: `data/threads_publish_log.json`/`data/blog_publish_log.json`
  (둘 다 `content_engine.publish_history.PublishRecord` 구조)에 처음부터
  `content_id`/`knowledge_id`가 있다 - 성과 수집 시 그대로 가져다 쓰면 된다.
- **YouTube**: 6-02 이전에는 `data/youtube_publish_log.json`에 이 연결 정보가
  전혀 없었다. 6-02부터 `scripts/upload_youtube_short.py`에
  `--content-id`/`--knowledge-id`(둘 다 선택, 둘 다 주거나 둘 다 생략해야 함)를
  추가해 **새로 업로드하는 영상부터** 연결 정보를 남길 수 있다.

## 8. YouTube legacy 데이터 처리

6-02 이전에 업로드된 영상(`data/youtube_publish_log.json`의 기존 기록)은
`content_id`/`knowledge_id`가 없다 - 이 값을 **절대 추측해서 채우지 않는다**.
실제 이 기록이 어떤 KNOWLEDGE에서 나온 영상인지 사람이 직접 확인해야 한다.

`content_engine/performance/migration.py`의 `migrate_youtube_baseline_records()`는
이런 legacy 상황을 위해 `{video_id: (content_id, knowledge_id)}` 매핑을
**호출부가 명시적으로 제공해야만** 변환한다 - 매핑에 없는 video_id는 조용히
건너뛴다. 이 함수는 설계/구현/테스트만 되어 있고, 실제 production
`data/youtube_publish_log.json`에 실행된 적은 없다(6-02 작업 범위 밖 - 실제
실행은 사람이 매핑을 준비한 뒤 별도로 판단).

## 9. dry-run / live 호출 안전 규칙

이 Codespace 환경에는 실제 `THREADS_ACCESS_TOKEN`/`YOUTUBE_CLIENT_ID`/
`YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN`이 환경변수로 이미 존재한다
(6-01에서 확인). `scripts/collect_performance.py`는 이 위험에 대응해 다음
규칙을 따른다(6-02에서 추가):

- `--platform threads`/`--platform youtube`는 **`--dry-run` 또는
  `--confirm-live` 중 하나를 반드시 지정해야 한다.** 둘 다 없으면 아무 것도
  하지 않고(클라이언트조차 만들지 않고) 오류로 종료한다.
- `--dry-run`: 네트워크 호출도, 저장도 하지 않는다. 무엇을 할지만 출력한다.
- `--confirm-live`: 실제 API를 호출한다(자격증명 필요).
- **GitHub Actions 환경(`GITHUB_ACTIONS=true`)에서는 `--confirm-live`를 줘도
  거부된다.** 이 CLI를 호출하는 workflow는 아직 없지만, 나중에 실수로
  연결되더라도 안전하도록 미리 막아둔다.
- `--platform blog`는 네트워크 호출이 없으므로 이 규칙의 적용을 받지 않는다.

`scripts/publish_threads.py`/`scripts/upload_youtube_short.py`(기존 발행 스크립트)는
이 규칙을 적용하지 않는다 - "`--dry-run` 없으면 실제 호출"이라는 기존 운영 방식을
6-02에서 바꾸지 않았다(변경 범위를 `collect_performance.py`로 한정).

## 10. /performance 화면 사용법

```bash
python3 scripts/run_scout_dashboard.py
```

로 Dashboard를 띄운 뒤 브라우저에서 `/performance`로 접속(또는 메인 화면
`📈 Performance` 링크). content_id별로:

- 제목, platform, 발행 시각, 최근 수집 시각
- 최근 metrics / 이전 metrics
- 대표 지표(`views`가 있으면 `views`, 없으면 실제 존재하는 metric 중 첫 번째)의
  전체 시계열 추이(`100 → 430 → 2,300` 형태 텍스트)
- 최초 스냅샷 대비 변화량(`views +750`처럼 표시, 없는 metric은 0으로 채우지 않고 생략)
- 스냅샷 개수

를 보여준다. **읽기 전용**이다 - 이 화면에서 아무 것도 저장/수정할 수 없다
(POST 라우트가 없다). 첫 스냅샷의 `source`가 `migration_baseline`이면 화면에
경고 문구가 함께 뜬다 - 그 변화량은 실제 성과 비교가 아니라는 뜻이다.

## 11. 향후 SCOUT와 연결할 때 지켜야 할 원칙

`tak_scout/scoring.py`(SCOUT SCORE, A~E 5개 차원)에 성과 신호를 추가한다면:

- `score_candidate()`(순수 함수: 같은 입력 → 같은 결과) 안에 직접 넣지 않는다 -
  성과는 후보 텍스트의 속성이 아니라 외부 상태이기 때문이다.
- `rank_candidates()`를 감싸는 별도의 선택적 레이어로 추가하는 것을 권장한다.
- **점수에 자동으로 합산하지 않는다.** 먼저 "이 category/domain의 과거 성과가
  어땠는지"를 참고 정보로만 보여주고, 사람이 몇 번 보고 타당하다고 판단한 뒤에나
  자동 반영을 고려한다.

## 12. 사람의 판단 없이 성과 데이터를 자동으로 콘텐츠 전략에 반영하지 않는다는 원칙

이것이 이 기능 전체를 관통하는 가장 중요한 원칙이다:

```
허용:
PERFORMANCE → DATA → HUMAN REVIEW → STRATEGY DECISION

금지(이번 단계에서 만들지 않음):
PERFORMANCE → SCOUT SCORE → CONTENT GENERATION (자동)
```

- 성과가 좋은 주제/형식/채널이 발견되어도, AI가 자동으로 사용자(티몽)의 전문
  분야나 의견, 문체를 성과를 이유로 수정하지 않는다.
- `content_engine/performance/` 어디에도 TAK BRAIN(`tak_brain/`)이나
  `tak_scout/scoring.py`를 import/수정하는 코드가 없다 - 의도적으로 그렇게
  만들지 않았다.
- 이 원칙을 바꾸려면(예: 성과 신호를 SCOUT SCORE에 실제로 반영) 사람이 먼저
  `/performance` 화면에서 데이터를 충분히 축적/검토한 뒤 별도로 명시적인 결정을
  내려야 한다 - 코드가 스스로 그 결정을 내리지 않는다.
