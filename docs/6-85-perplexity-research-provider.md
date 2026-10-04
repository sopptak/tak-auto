# 6-85 Perplexity Research Provider 연결

> Perplexity는 **조사/근거 수집 Provider**다. 콘텐츠를 생성하지 않는다. 결과는 탁멍의 경험/판단 KNOWLEDGE와 분리된 "검증 전 Research Evidence"이고, 사람이 검토하기 전에는 생성 입력이 되지 않는다.

코드: `content_engine/marketing/brief_research.py`(신규), `content_engine/marketing/research_tasks.py`(`research_idea` 오류 처리), CLI: `scripts/marketing_brief.py research`
재사용: `content_engine/providers/`(`ResearchProvider`, `PerplexityResearchProvider`, `MockResearchProvider`, registry), `content_engine/research_bridge.research_to_knowledge`
테스트: `tests/test_marketing_research_provider.py`(20), 기존 `tests/test_providers.py`
관련: [6-79](6-79-ai-marketing-intelligence.md), [6-80](6-80-marketing-brief-to-content.md), [6-83](6-83-marketing-knowledge-linking.md), [6-84](6-84-marketing-operational-e2e.md), [providers.md](providers.md)

## 1. 목적

`draft --research`는 아이디어에서 **새 브리프를 만들 때만** 조사했다. 6-85는 이미 있는 MarketingBrief에 Perplexity 조사를 붙인다. 흐름은 브리프/아이디어의 research query → Perplexity → 구조화된 근거 → pending Research KNOWLEDGE → 사람이 검토하는 근거다.

## 2. Architecture (새 Provider/모델을 만들지 않음)

조사 결과 표현과 Perplexity adapter는 cdc71a2(provider abstraction)에 이미 있었다. 6-85는 이를 MarketingBrief에 연결한다.

```
MarketingBrief(+ IdeaCandidate.research_query)
  → research_tasks: idea_query + 8개 aspect 질의(build_queries)
  → ResearchProvider.research(query, max_results)       # mock | perplexity
  → ResearchResult(provider, query, created_at, sources[title,url,snippet,domain,published_at,rank], request_id)
  → ResearchBundle.evidence → EvidenceItem(kind="research", provider, aspect, url, title, snippet)
  → ResearchBundle.knowledge_records → research_to_knowledge → KnowledgeRecord(pending, verification_required=True)
  → brief_research.research_brief (미리보기) → apply_brief_research (+ KNOWLEDGE append) (--write)
```

요청 필드와 기존 모델의 대응:

| 요청 필드 | 기존 모델 |
|---|---|
| provider / query | `ResearchResult.provider`, `.query`, `EvidenceItem.provider` |
| collected_at | `ResearchResult.created_at`, `KnowledgeRecord.created_at` |
| title / summary / evidence / source_url | `ResearchSource.title`/`.snippet`/`.url` → `EvidenceItem`. KNOWLEDGE는 `factual_information`, `evidence`, `source_url` |
| verification_required | `KnowledgeRecord.verification_required=True`, `inference_method="external_research"` |
| confidence | 근거 수준 `EvidenceItem`에는 없다. 브리프 `confidence`(근거 양/다양성), 제안 confidence(최대 0.6) |
| metadata | `ResearchResult.metadata`, `request_id`. 브리프/KNOWLEDGE에는 저장하지 않음 |

## 3. Provider interface

`ResearchProvider.research(query, domains=None, recency=None, max_results=5) -> ResearchResult`(기존 시그니처). 요청서의 `context` 인자는 domains/recency/max_results로 대신한다. 새 인터페이스를 만들지 않았다.

## 4. Perplexity adapter (`content_engine/providers/perplexity.py`, 기존)

- Search API(`POST https://api.perplexity.ai/search`)를 표준 라이브러리 urllib로 호출한다.
- 키는 `PERPLEXITY_API_KEY` 환경변수에서만 읽는다. 오류 메시지에는 변수명만 나오고 값은 나오지 않는다(기존 테스트 `test_error_messages_never_contain_the_key`).
- 응답 정규화는 `results[]`를 `ResearchSource`로 변환한다. raw 응답은 저장하지 않는다. `request_id`도 브리프/KNOWLEDGE에 남지 않는다(테스트).
- 오류 매핑:

| 상황 | 예외 | 마케팅 계층 처리 |
|---|---|---|
| 키 없음 | `ProviderNotConfiguredError` | 즉시 중단, 아무것도 쓰지 않음(CLI exit 2) |
| HTTP 401/403 | `ProviderAuthError` | 즉시 중단(이후 aspect 호출 안 함) |
| HTTP 그 외 오류 / 네트워크·timeout | `ProviderRequestError` | 그 aspect만 `errors`에 기록하고 나머지 계속 |
| JSON 아님 / `results` 없음 / url 없는 결과 | `ProviderResponseError` | 그 aspect만 `errors`에 기록. url 없는 근거는 들어오지 않음 |

url 없는 결과에 대한 정책: 기존 provider 계약(`test_malformed_responses`)은 엄격하다. 결과 하나라도 url이 없으면 그 응답 전체를 거부한다. 6-85는 이 계약을 바꾸지 않았다. 따라서 출처 URL이 없는 근거는 저장될 수 없고, 다른 aspect는 영향을 받지 않는다.

## 5. Query → Evidence 흐름

- 질의: 브리프의 `idea_id`로 아이디어를 찾으면 `idea.research_query` + 아이디어 제목 기준 aspect 질의(`research_idea`)를 쓴다. 찾지 못하면 `brief.topic` 기준 aspect 질의(`run_research_tasks`)를 쓴다. 새 질의 구조를 만들지 않았다.
- `--aspect`로 8개 중 일부만 조사할 수 있다(비용 절감).
- 중복 제거: `EvidenceItem.evidence_id`(kind/provider/aspect/url/title/snippet의 해시)로 브리프에 이미 있는 근거와 이번 조사 안의 중복을 제외한다. 같은 url이라도 aspect가 다르면 별개의 근거다.
- 6-85 수정: `research_idea`는 `idea_query` 실패를 aspect와 같은 규칙으로 처리한다. 설정/인증 오류는 즉시 올리고, 그 외에는 `errors["idea_query"]`에 남긴다. 전에는 idea_query 한 번의 실패로 조사 전체가 중단됐다.

## 6. verification_required 정책

- Research KNOWLEDGE는 항상 `knowledge_review_status="pending"`, `verification_required=True`, `knowledge_type="research"`다. `research_brief`가 저장 전에 이 계약을 다시 확인한다.
- 자동 승인하지 않는다. 같은 id가 이미 있으면 덮어쓰지 않으므로, 사람이 이미 승인한 레코드를 pending으로 되돌리지 않는다(테스트).
- Research KNOWLEDGE는 `brief.knowledge_ids`(생성 입력)에 **연결하지 않는다**. 생성 입력은 사람이 승인한 경험/판단 KNOWLEDGE를 `knowledge add`로 연결한다(6-83). 연구 KNOWLEDGE에는 생성기 입력 필드(experience/problem/action/lesson…)도 없다(6-84 발견 4).
- 브리프에는 근거(`evidence`)만 추가한다. `confidence`는 다시 계산하되 내려가지 않는다(`max`). `status`, `knowledge_ids`, `content_ids`, `media_generations`는 그대로다.
- **approved 브리프에는 쓰지 않는다.** 근거는 생성 프롬프트(`marketing_guidance`의 `[근거(검증 전)]`)에 들어간다. approved 브리프에 검토하지 않은 근거를 붙이면 재승인 없이 생성 입력이 바뀌어 승인 게이트를 우회하게 된다.
  - 조사가 필요하면 `set`으로 수정해 draft로 전환한 뒤 조사하고 다시 승인한다.
  - rejected 브리프도 쓰지 않는다.
  - 미리보기는 두 경우 모두 가능하다.

## 7. CLI

```
python scripts/marketing_brief.py research BRIEF_ID --provider mock                        # 미리보기
python scripts/marketing_brief.py research BRIEF_ID --provider perplexity --aspect customer_problem
python scripts/marketing_brief.py --write research BRIEF_ID --provider perplexity --max-results 5
```

- `--provider`는 **필수**다. 기존 registry 기본값("키가 있으면 perplexity")에 기대지 않으므로, 실제 API는 `perplexity`를 명시할 때만 호출된다.
- 미리보기도 조사 자체는 실행한다(perplexity면 실제 읽기 전용 API 호출, 비용 발생). 파일은 쓰지 않는다.
- 출력:
  - 질의 기준(아이디어/topic)
  - aspect별 질의와 출처 수 또는 실패 사유
  - 새 근거 / 중복 제외 수
  - 신규·기존 KNOWLEDGE 후보 수와 id
  - 저장 불가 사유
- 종료 코드:

| 상황 | 동작 | 종료 코드 |
|---|---|---|
| 정상 | 미리보기 또는 저장 | 0 |
| 새 결과 없음(모두 중복) | 변경 없음 | 0 |
| 모든 조사 실패, 설정/인증 오류, approved/rejected 브리프에 `--write` | 아무것도 쓰지 않음 | 2 |

- 운영 순서 예:

```
research BRIEF --provider perplexity → --write → review_knowledge.py --pending/--show
→ suggest(근거 인용형 제안) → suggestion accept / set → approve → knowledge add(경험 KNOWLEDGE) → generate …
```

## 8. 환경변수

| 변수 | 용도 |
|---|---|
| `PERPLEXITY_API_KEY` | Perplexity 인증. 코드/파일/로그에 저장하거나 출력하지 않는다 |
| `TAK_RUN_INTEGRATION=1` | 기존 live 테스트(`tests/test_providers.py::PerplexityIntegrationTests`)를 실행할 때만 사용 |

`TAK_RESEARCH_PROVIDER`(registry 기본 선택)는 `research` 명령에서 쓰지 않는다(`--provider` 필수).

## 9. 실패 처리

- 설정/인증 오류: 첫 호출에서 중단하고 아무것도 쓰지 않는다.
- 일부 aspect 실패: 성공한 aspect만 저장하고 실패 사유를 출력한다.
- 전부 실패: exit 2, 아무것도 쓰지 않는다.
- 저장 순서: 브리프(원자적 `_update`) → KNOWLEDGE(기존 append helper, tmp + replace). 저장 직전에 브리프 게이트(approved/rejected)를 다시 확인한다.

## 10. 테스트

`tests/test_marketing_research_provider.py` 20개, 네트워크 없음. Perplexity는 가짜 transport와 가짜 키 문자열을 쓴다.

| 요구 항목 | 테스트 |
|---|---|
| mock research success | `test_mock_research_success_and_policy` |
| Perplexity response parsing | `test_perplexity_response_parsing`, `test_perplexity_cli_uses_env_key_and_fake_transport` |
| API key missing | `test_api_key_missing`, `test_perplexity_cli_without_key_fails_cleanly`(transport 미호출) |
| HTTP failure / timeout / auth | `test_http_failure_is_recorded_per_aspect`, `test_timeout_is_recorded_per_aspect`, `test_auth_failure_stops_everything`, `test_perplexity_http_error_everywhere_writes_nothing` |
| malformed response / source URL 누락 | `test_malformed_response_and_missing_source_url` |
| duplicate evidence | `test_duplicate_evidence`, CLI 재실행(변경 없음) |
| verification_required / pending / 자동 승인 금지 | `test_mock_research_success_and_policy`, `test_write_saves_evidence_and_pending_knowledge_only` |
| CLI preview no-write / --write | `test_preview_does_not_write`, `test_write_saves_evidence_and_pending_knowledge_only`, `test_provider_is_required` |
| 기존 brief status / knowledge_ids 불변 | `test_apply_adds_only_evidence`, `test_write_saves_…`, `test_draft_research_preserves_other_data_and_lineage` |
| approved/rejected 브리프 보호 | `test_approved_and_rejected_briefs_not_written`, `test_approved_brief_not_written_and_lineage_untouched`, `test_rejected_brief_not_written` |
| 기존 content/media/performance/lineage 불변 | `test_approved_brief_not_written_and_lineage_untouched`, `test_draft_research_preserves_other_data_and_lineage`(파일 SHA 비교) |
| idea_query 실패 비치명 | `test_idea_query_failure_is_not_fatal` |

## 11. 실제 API smoke test

**미실행.** 이 환경에는 `PERPLEXITY_API_KEY`가 설정되어 있지 않다(존재 여부만 확인했고 값은 확인하지 않았다). 키가 있는 환경에서는 아래로 실행할 수 있다.

```
TAK_RUN_INTEGRATION=1 python -m pytest -q tests/test_providers.py -k live      # 기존 read-only live 테스트
python scripts/marketing_brief.py --data-dir <임시 디렉터리> research BRIEF --provider perplexity --aspect customer_problem --max-results 2
```

두 번째 명령은 미리보기라 아무것도 쓰지 않는다. 운영 data에 쓰기 전에 임시 디렉터리에서 먼저 확인한다.

## 12. 다음 단계

- 실제 키로 smoke test(응답 형식/한국어 질의 품질/비용 확인).
- 조사 근거와 제안(`suggest`)의 연결 품질 확인. 지금은 aspect별 첫 출처를 인용한다.
- Research KNOWLEDGE 검토 UX: `review_knowledge.py`에서 research 유형을 구분해 보여 주기(이번 범위 밖, 수정 금지 파일).
- 조사 비용 관리: aspect 8개 × 질의 → 호출 수 제한/캐시.

## 13. 검증 결과 (2026-10-04)

| 항목 | 결과 |
|---|---|
| 신규 테스트 | `tests/test_marketing_research_provider.py` 20 passed. 관련 기존 테스트(marketing/providers/market_demand) 165 passed, 1 skipped(live) |
| 전체 | 2082 passed, 33 failed, 108 skipped(6-84 종료 시 2062 passed / 33 failed) |
| 기존 / 신규 실패 | 33 / 0. 33개는 `test_6_55_shorts_studio.py` 31, `test_second_knowledge_correction_and_generation_pool.py` 2 |
| 금지 파일(52fb0bb 대비) | 변경 없음. `content_engine/providers/*`, `research_bridge.py`도 6-85에서 변경하지 않음 |
| 실제 data | 6-84 시작 전 기록과 SHA-256, mtime이 같음(production archive, performance, knowledge, threads_pending, 기존 pool). 마케팅 파일 없음 |
| `git diff --check` / secret scan | 통과 / 발견 없음. 테스트용 가짜 문자열 `pplx-test-not-a-real-key`만 있음 |
| 실제 Perplexity smoke test | 미실행(`PERPLEXITY_API_KEY` 미설정) |
| 커밋 | 100261d(기능 + 테스트), 문서 커밋 |
