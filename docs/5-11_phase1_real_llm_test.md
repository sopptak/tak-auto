# 5-11 Phase 1 — 실제 LLM 통합 테스트 보고서

## 1. 목적

승인 완료된 `docs/5-11_phase1_implementation.md`(Phase 1 구현)를 대상으로, 코드
수정 없이 **실제 LLM**을 붙여 `generate_threads_draft.py`가 approved KNOWLEDGE →
실제 LLM 재작성 → rotation 선정 → `ThreadsPendingDraft` 생성 → pending JSON
저장까지 실제로 동작하는지 검증한다.

**금지 사항(전부 준수)**: 코드 수정 금지, commit 금지, push 금지, 실제 Threads
발행 금지, 운영 data 파일 변경 금지, 기존(운영) pending 파일 사용 금지.

## 2. 테스트 준비

- **대상 KNOWLEDGE**: `knowledge-da6ddf5aa459`(경험형, "57화) 개발을 모르는 내가
  앱을 만들다") — approved 5건 중 1건 선택. 문체 판단(티몽 스타일 근접도)에
  가장 유의미한 경험형 콘텐츠를 골랐다.
- **운영 데이터 격리**: `git show origin/main:data/tak_brain_knowledge.json`,
  `git show origin/main:data/threads_publish_log.json`을 각각 `/tmp` 스크래치
  디렉터리로 복사해서만 사용했다 — 로컬 작업 트리의 `data/`와 실제 원격
  저장소 모두 읽기조차 직접 하지 않고, 읽기 전용 스냅샷만 참조했다.
  (`origin/main`을 쓴 이유: 로컬 `data/tak_brain_knowledge.json`은 이번 대화와
  무관한 별개 작업으로 이미 미커밋 상태라, "실제 운영" 데이터를 더 정확히
  반영하는 `origin/main` 버전을 대신 사용했다.)
- **pending 파일**: 운영 파일(`data/tak_threads_pending.json`, 애초에 존재하지도
  않음)을 전혀 사용하지 않고, 전용 임시 경로(`/tmp/.../pending.json`)만 사용.
- **실제 LLM 환경변수**: `TAK_MEDIA_LLM_API_KEY`는 환경에 이미 설정된 값을
  그대로 사용했고, `TAK_MEDIA_LLM_ENDPOINT`/`TAK_MEDIA_LLM_MODEL`은 이번
  프로세스에만 `https://api.openai.com/v1/chat/completions` / `gpt-4o-mini`로
  설정했다(Phase 4-2/4-3 실제 LLM 테스트와 동일 방법론 — 값을 코드나 파일에
  남기지 않고 실행 시점 환경변수로만 전달).

## 3. 실행 명령

```
TAK_MEDIA_LLM_ENDPOINT="https://api.openai.com/v1/chat/completions" \
TAK_MEDIA_LLM_MODEL="gpt-4o-mini" \
python3 scripts/generate_threads_draft.py \
  --knowledge <scratch>/knowledge.json \
  --history <scratch>/history.json \
  --pending <scratch>/pending.json \
  --id knowledge-da6ddf5aa459
```

## 4. 실행 결과 로그

```
TAK BRAIN: 승인 KNOWLEDGE 1건 확인
TAK MEDIA: 배치 실행 중 (콘텐츠 생성 + LLM 재작성 + 검증)...
TAK MEDIA 완료: 총 Draft 9건 (valid 5, rejected 4, error 0)
Threads 초안 생성 완료 (검수 대기): content_id=content-6de1e17342ba9642 KNOWLEDGE=knowledge-da6ddf5aa459
EXIT_CODE=0
```

## 5. 확인 항목 1~13

### 5-1. 실제 LLM 호출 성공 여부
**성공.** 9회 실제 LLM 호출(Blog 1 + Shorts 3 + Threads 5) 전부 응답 수신,
`LLMConfigurationError`/`LLMResponseError` 없음, exit code 0.

### 5-2~5-3. 생성된 Threads 초안 — 제목/본문 원문 그대로

**제목**: 나의 앱 제작 여정에서 얻은 교훈

**본문** (439자, Threads 500자 제한 이내):

> 아이디어를 앱으로 만들려면 개발자에게 부탁해야 한다고 생각했지만, 코딩을
> 모르는 상태에서 직접 구현해야 했다. 처음에는 막막했지만, ChatGPT를 통해
> 아이디어를 기획하고 필요한 명령어를 정리했다. 그러면서 '나만의 골프기록'
> 앱을 제작하기 시작했고, 비공식 테스트에 테스터 12명이 참여해 14일 이상의
> 테스트 기간을 거쳤다. 제작 중 문제가 생기면 다시 질문하고 수정과 테스트를
> 반복했다. 이 과정을 통해 코딩을 몰라도 새로움을 배우고 문제를 수정할 수
> 있다는 경험을 얻었다. "코딩을 몰라도 완벽하게 알고 시작할 때까지 기다리지
> 않고, 만들면서 배우고 문제가 생기면 수정할 수 있다는 경험을 얻었다." 나만의
> 앱 제작을 위해 AI 도구를 활용하고, 반복적인 수정과 사용자 테스트를 거치니
> 비개발자도 가능함을 깨달았다. 이렇게 코딩의 벽을 넘고, 실제 결과물을
> 창출할 수 있었다.

### 5-4~5-7. 메타데이터

| 필드 | 값 |
|---|---|
| `knowledge_id` | `knowledge-da6ddf5aa459` |
| `content_id` | `content-6de1e17342ba9642` |
| `source_url` | `https://blog.naver.com/tmong2/224407187378?fromRss=true&trackingCode=rss` |
| `evidence_unit_ids` | `["problem:1", "lesson:1"]` |
| `ai_rewritten_title` | 위 제목과 동일 |
| `ai_rewritten_body` | 위 본문과 동일 |

### 5-8~5-10. 상태 확인

- **`final_title` / `final_body`**: 둘 다 `null` ✅ (승인 전이므로)
- **`status`**: `"pending"` ✅
- **`edited_by_user`**: `false` ✅

### 5-11~5-13. 안전 확인

- **실제 Threads API 호출 여부**: **없음** — `ThreadsClient`가 `generate_threads_draft.py`에
  import되지 않으며, 결과 레코드의 `threads_post_id`도 `null`.
- **PublishHistory 변경 여부**: **없음** — 실행 전/후 임시 history 파일을
  `diff`한 결과 **완전히 동일**(바이트 단위 일치, "IDENTICAL - untouched").
- **실제 운영 data 변경 여부**: **없음** — `git status --short data/` 결과
  이번 테스트로 인한 변경이 전혀 없고(기존에 있던 무관한
  `data/tak_brain_knowledge.json` 미커밋 변경만 그대로 유지), 운영 경로
  `data/tak_threads_pending.json`도 생성되지 않았다(전부 `/tmp` 임시 경로만
  사용).

## 6. 전체 테스트 재실행

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 406 tests in 12.691s
OK
```

**406/406 PASS** — 실제 LLM 테스트 실행 전후로 기존 테스트에 영향 없음.

## 7. 최종 git status

```
modified: .gitignore, content_engine/__init__.py, generator.py, llm_provider.py,
          rewrite.py, data/tak_brain_knowledge.json, tak_scout/__init__.py,
          tests/test_content_engine.py, tests/test_media_batch.py
```

전부 이번 테스트 이전부터 있던 무관한 변경사항이며, 이번 실제 LLM 테스트로
새로 추가되거나 변경된 추적 대상 파일은 없다. commit/push는 수행하지 않았다.

## 8. 문체 관찰 (참고용, 최종 판단은 티몽 몫)

- 사실관계(테스터 12명, 14일 등 숫자)는 원문과 일치하게 보존됨.
- 원본 규칙기반 초안의 3인칭 인용체("작성자는 ~고 적었습니다")와 달리 1인칭
  경험담 톤으로 자연스럽게 이어짐.
- 다만 원문 문장("코딩을 몰라도 완벽하게...")이 본문 중간에 큰따옴표로 그대로
  한 번 더 인용되어 약간 반복되는 느낌이 있음 — Validator는 이를 "원문 근거
  보존"으로 정상 처리하지만, 문장 흐름상 다듬을 여지가 있어 보임.

## 9. 결론

Phase 1이 실제 LLM과 실제(읽기 전용으로 격리된) 운영 KNOWLEDGE로 정상 동작함을
확인했다. 실제 Threads 게시, `PublishHistory` 변경, 운영 데이터 변경은 전혀
없었고, 생성된 pending draft는 설계 문서(5-11)가 요구한 모든 필드와 상태
조건(`status=pending`, `final_*=None`, `edited_by_user=false`)을 정확히
충족했다. 406개 전체 테스트도 영향 없이 그대로 통과했다.
