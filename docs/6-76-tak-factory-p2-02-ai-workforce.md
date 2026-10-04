# TAK AUTO P2-02 — AI Workforce Foundation + Tool Registry

## 1. 목적과 설계 결정

P2-01 R&D Radar + IDEA VAULT를 유지하면서 12개 역할 기반 AI Agent, 16개 도구 후보, agent 간 Task contract, 라우팅, 사람 승인 gate의 내부 기반을 만든다. 이번 단계는 registry와 작업 상태를 기록하는 구조이며 Agent 추론·자동 실행이나 외부 adapter는 만들지 않는다.

기준 시작 SHA는 P2-01 완료 commit `d8f84175d231623e29aae3ffaba8e86ec774134e`이다. 공통 Task/Agent Registry와 Content/Marketing DNA schema는 없었다. `content_engine.money.MoneyStore`의 `tasks`는 플랫폼별 기회·보상·시간을 기록하는 도메인 모델이므로 AI 업무 계약으로 재사용하지 않았다. P1 workflow, publishing gate, Production Archive와 P2-01 `tak_rnd` 모델·저장·CLI는 변경하지 않는다.

Registry 정의는 사람이 검토하기 쉬운 JSON, runtime 계약은 dataclass, task 상태는 별도 JSON 배열에 둔다. 쓰기는 임시 파일 후 atomic replace를 사용한다. 기존 production data migration은 없다.

## 2. 12명 조직도와 Agent Registry

| ID | Agent / 역할 | 주요 책임 | 다음 협업 |
|---|---|---|---|
| AGENT-01 | TAK CEO / AI General Manager | 전략, 업무 배분·우선순위, 충돌 조정, 결과 종합, human approval 판단, 다음 업무 생성 | 전체 부서 조정 |
| AGENT-02 | R&D Radar / 소재발굴팀장 | Threads·YouTube·웹·AI·자동화·마케팅·수익화·해외·경쟁자 사례, 포맷 발견 | AGENT-03 |
| AGENT-03 | Market & Case Analyst / 시장·사례 분석가 | 성공 원인, Hook·구조·engagement·댓글·공유·트래픽·수익화·재현성, DNA 원천 관찰 | AGENT-04, AGENT-08, AGENT-12 |
| AGENT-04 | Content Strategist / 콘텐츠 전략가 | IDEA 우선순위, 플랫폼·포맷·시리즈화, 1 Idea → Multi Content | AGENT-05~09 |
| AGENT-05 | Content Writer / 콘텐츠 작가 | Threads·Shorts script·Blog·Hook·CTA·브랜드 스타일 | AGENT-06~09 |
| AGENT-06 | Shorts Producer / 쇼츠 제작팀 | 15/30/60초, scene·video hook·caption·B-roll·TTS·thumbnail·variants | AGENT-07~09, AGENT-12 |
| AGENT-07 | Global Localization / 글로벌 콘텐츠팀 | 영어·스페인어·일본어·중국어 등 hook·사례·표현·CTA·문화 맥락 현지화 | AGENT-08~09 |
| AGENT-08 | Marketing / 마케팅팀 | hook·traffic·click·CTA·conversion·viral·상품 연결·Marketing DNA | AGENT-09, AGENT-12 |
| AGENT-09 | PR & Distribution / 홍보·게시팀 | Threads·YouTube·Blog 게시 준비, 플랫폼별 전략·예약 계획 | AGENT-12; 기존 gate 필수 |
| AGENT-10 | Engineering / 개발팀 | Agent infrastructure·API·data·DB·dashboard·integration·test·maintenance | AGENT-11 |
| AGENT-11 | Operations & Automation / 운영·자동화팀 | pipeline·workflow·schedule·retry·idempotency·장애·자동화 후보 | AGENT-02, AGENT-09, AGENT-12 |
| AGENT-12 | Data & Performance Analyst / 데이터·성과분석팀 | Threads·Shorts·Blog 성과, engagement·retention·conversion, DNA 제안, 다음 전략 | AGENT-01, AGENT-03, AGENT-04 |

전체 필드(`agent_id`, name, department, role, mission, responsibilities, inputs/outputs, allowed/forbidden actions, upstream/downstream, `human_approval_required`, status, version)는 `data/tak_ai_agents.json`에 있다. `load_agents()`는 AGENT-01~12의 정확한 수, unique ID, graph 참조, action 충돌을 검사한다. forbidden actions는 선언적 제한이며 이번 버전에는 Agent 실행기가 없다.

## 3. Task Contract와 Routing

`Task`는 `task_id`, `created_at`, `created_by`, `assigned_to`, `department`, `task_type`, `priority`, `input_refs`, `output_refs`, `status`, `approval_required`, `approval_status`, `parent_task_id`, `retry_count`, `result_summary`, `error`와 capability/action 보조 필드를 가진다. `data/tak_ai_tasks.json`에 append/update 상태로 저장한다. 참조는 `rnd:<id>`, `idea:<id>`, `content:<id>`, `performance:<id>` 문자열 convention을 쓴다.

| task_type | 담당 |
|---|---|
| `rnd_discovery`, `rnd_analysis`, `market_case_analysis` | AGENT-03 |
| `idea_strategy` | AGENT-04 |
| `content_writing` | AGENT-05 |
| `shorts_production` | AGENT-06 |
| `localization` | AGENT-07 |
| `marketing_strategy` | AGENT-08 |
| `publish_preparation` | AGENT-09 |
| `engineering` | AGENT-10 |
| `automation` | AGENT-11 |
| `performance_analysis` | AGENT-12 |
| `executive_coordination` | AGENT-01 |

Task status는 `PENDING`, `ASSIGNED`, `RUNNING`, `WAITING_INPUT`, `WAITING_APPROVAL`, `COMPLETED`, `FAILED`, `CANCELLED`다. assignment/상태 전이는 검증하고 parent는 존재하는 task만 허용한다. 실패 후 재할당 시 retry count를 증가시킨다. 생성/route/status는 계획과 기록만 수행하며 작업 내용을 외부에서 실행하지 않는다.

대표 흐름은 R&D item → `rnd_discovery`/AGENT-03 → 사람이 기존 P2-01 `promote_rnd_to_idea()` 실행 → `idea_strategy`/AGENT-04 → `content_writing`/AGENT-05 → `shorts_production`/AGENT-06 → 콘텐츠 게시 후 별도 `performance_analysis`/AGENT-12 → `executive_coordination`/AGENT-01이다. Task `input_refs`/`output_refs`와 `parent_task_id`로 lineage를 잇는다. Task 상태 변화 자체가 P2-01 IDEA를 자동 생성하거나 Performance API를 호출하지 않는다.

## 4. Human Approval Gate

다음 requested action은 승인 필요로 강제한다: Threads 게시, YouTube upload, 외부 write, 유료 API, 비용 발생, 광고 집행, 계정 권한 변경, secret read/change, 파괴적·비가역 data 변경. AGENT-01과 AGENT-09로 라우팅되는 작업도 registry 선언에 따라 승인 대기 상태가 된다.

approval 상태는 `NOT_REQUIRED`, `PENDING`, `APPROVED`, `REJECTED`다. 승인 필요 작업은 `WAITING_APPROVAL`에 머물고 `APPROVED` 전에 `RUNNING`이나 `COMPLETED`로 바꿀 수 없다. 일반 Task status 명령으로 승인 대기 상태를 우회할 수 없고 거절은 `CANCELLED`가 된다. 승인 기록도 외부 작업을 실행하지 않는다. 향후 publisher를 연계할 때 기존 publishing gate를 별도로 반드시 통과해야 한다.

## 5. Tool Registry와 Agent 연결

`data/tak_ai_tools.json`에는 요청된 16개 후보만 있으며 모두 `CANDIDATE`다. 후보의 API availability와 browser requirement는 확인 전이므로 `null`, 비용은 `unknown`, 승인 필요는 보수적으로 `true`다. 연결되거나 실행 가능한 것으로 표시하지 않는다.

| ID | 후보 | Category | 추천 Agent |
|---|---|---|---|
| TOOL-01 | Apify | research | AGENT-02 |
| TOOL-02 | Firecrawl | research | AGENT-02, AGENT-03 |
| TOOL-03 | Krea | image | AGENT-06 |
| TOOL-04 | Runway | video | AGENT-06, AGENT-07 |
| TOOL-05 | Descript | video | AGENT-06, AGENT-07 |
| TOOL-06 | OpusClip | video | AGENT-06, AGENT-07 |
| TOOL-07 | ElevenLabs | audio | AGENT-06, AGENT-07 |
| TOOL-08 | Metricool | distribution | AGENT-03, AGENT-08, AGENT-09, AGENT-12 |
| TOOL-09 | AgentMail | operations | AGENT-11 |
| TOOL-10 | Fireflies | operations | AGENT-11 |
| TOOL-11 | Recraft | image | AGENT-06 |
| TOOL-12 | ClickUp | operations | AGENT-11 |
| TOOL-13 | Make | automation | AGENT-08, AGENT-11 |
| TOOL-14 | Air | media | AGENT-06, AGENT-11 |
| TOOL-15 | Synthesia | video | AGENT-06, AGENT-07 |
| TOOL-16 | VEED | video | AGENT-06, AGENT-07 |

각 Tool은 `tool_id`, name, category, provider, purpose, assigned_agents, input/output type, capabilities, `api_available`, `browser_required`, `cost_type`, `approval_required`, status, version을 가진다. `validate_tool_registry()`는 16개 ID, unique ID, agent 참조, status, capability를 검사한다.

Agent의 기존 사내 기능 연결은 candidate vendor tool과 섞지 않고 `recommended_internal_resources`로 표시한다: Writer/Global의 TAK AUTO LLM provider, Distribution의 기존 Threads·YouTube gate, Operations의 GitHub Actions, Performance의 기존 collector 등이다. 이 이름은 새 API 연결을 뜻하지 않는다.

`select_tools_for_task(task)`는 담당 Agent와 필요한 capability가 겹치는 registry 후보를 찾고 approval 상태를 반환한다. 결과의 `executable`은 항상 false이며 adapter/API 호출은 없다. TASK가 연결된 도구 상태더라도 실행기는 범위 밖이다.

## 6. Content DNA와 Marketing DNA

두 schema 모두 `content_id`를 통해 나중에 콘텐츠/성과와 연결하며 측정되지 않은 값은 `null`로 둔다. 분석 엔진·성과 점수화는 구현하지 않는다.

- Content DNA: `hook_type`, `structure_type`, `length`, `pacing`, `information_density`, `question_usage`, `controversy`, `storytelling`, `how_to`, `timeline`, `listicle`, `case_study`, `before_after`, `curiosity`, `emotional_trigger`, `cta_type`, 그리고 platform/language/format.
- Marketing DNA: `curiosity_hook`, `discovery`, `click`, `share`, `comment`, `conversion`, `free_trial`, `product_connection`, `community_spread`, `cta`, `funnel_stage`, platform/language.
- Content DNA는 콘텐츠가 왜 소비되는지, Marketing DNA는 사람이 왜 발견·클릭·공유·전환하는지에 대한 관찰 interface다.

## 7. P2-01과 Aside 확장

P2-01의 R&D/IDEA 타입과 저장소는 변경하지 않았다. R&D reference를 Analyst Task에 넣고, 기존 P2-01 승격 API가 만든 `idea_id`를 output/input reference로 이어 Strategist Task를 생성한다. P2-01의 종료 상태/priority 제외 동작은 그대로 둔다.

Aside는 브라우저 실행 계층으로 남는다. Aside가 public-source capture JSON을 내보내고, 향후 입력 adapter가 기존 `scripts/tak_rnd.py import-rnd` 경계를 호출하는 방식이 확장 후보이다. 이번 변경은 Aside, browser, Threads, YouTube, Metricool 또는 기타 외부 API를 호출하지 않는다.

## 8. CLI

저장소 루트에서 실행한다. 테스트용 다른 task store는 명령 앞에 `--task-store /tmp/tasks.json`을 둔다.

```bash
python3 scripts/tak_workforce.py agent list
python3 scripts/tak_workforce.py agent show AGENT-03
python3 scripts/tak_workforce.py tool list
python3 scripts/tak_workforce.py tool show TOOL-01
python3 scripts/tak_workforce.py task create --type rnd_discovery --input-ref rnd-radar-123
python3 scripts/tak_workforce.py task list
python3 scripts/tak_workforce.py task route task-<id>
python3 scripts/tak_workforce.py tool select task-<id>
python3 scripts/tak_workforce.py task status task-<id> --status RUNNING
python3 scripts/tak_workforce.py task approval task-<id> --decision APPROVED
python3 scripts/tak_workforce.py task show task-<id>
```

## 9. 테스트·제한·로드맵

신규 registry/Task/CLI/DNA/P2 integration, P2-01, P1, publishing, 전체 regression 결과는 아래 완료 기록에 적었다. 전체 실행에서 발생한 기존 Linux Noto 폰트 관련 실패와 신규 실패를 분리했다. 외부 서비스 호출·게시·업로드·결제·광고·secret 접근은 실행하지 않았다.

| 단계 | 범위 | 상태 |
|---|---|---|
| P2-01 | R&D Radar + IDEA VAULT | DONE |
| P2-02 | AI Workforce + Tool Registry | DONE |
| P2-03 | R&D Radar → Aside research adapter | NEXT |
| P2-04 | Content DNA Engine | Planned |
| P2-05 | Marketing DNA Engine | Planned |
| P2-06 | 1 Idea → Multi Content Engine | Planned |
| P2-07 | Shorts Factory | Planned |
| P2-08 | Global Localization Factory | Planned |
| P2-09 | Auto Publishing Orchestrator | Planned |
| P2-10 | Performance Learning Loop | Planned |
| P2-11 | TAK AUTO Control Center | Planned |
| P3 | Semi-autonomous AI Workforce | Planned |

### 완료 기록

- 시작 SHA: `d8f84175d231623e29aae3ffaba8e86ec774134e`
- 종료 SHA (기능 구현 commit): commit 후 기록
- Branch: `p2-02-ai-workforce`
- 종료 HEAD (보고서 반영 commit): commit 후 기록
- Agent: **12**; Tool: **16**, 모두 `CANDIDATE`
- 변경 파일: `.gitignore`, `data/tak_ai_agents.json`, `data/tak_ai_tools.json`, `data/tak_ai_tasks.json`, `tak_workforce/__init__.py`, `tak_workforce/models.py`, `tak_workforce/registry.py`, `tak_workforce/tasks.py`, `scripts/tak_workforce.py`, `tests/test_workforce_registry.py`, `tests/test_workforce_tasks.py`, `tests/test_workforce_dna.py`, `tests/test_workforce_cli.py`, `tests/test_workforce_p2_integration.py`, 본 문서.
- Task model/routing/approval: 상태 저장과 검증을 구현; task execution adapter 미구현.
- 신규 Workforce suite: **22 passed, 16 subtests passed**.
- P2-01 R&D Radar/IDEA Vault regression: **15 passed**; 통합 test는 기존 P2-01 API 사용.
- P1 Performance regression: **119 passed**.
- Publishing safety/Production Archive regression: **130 passed**.
- 전체 `tests/`: **1,782 passed, 31 failed, 118 skipped, 313 subtests passed, 1 warning**. 기존 실패 31건은 모두 Linux에서 Windows 전용 `C:/Windows/Fonts/NotoSansKR-VF.ttf`가 없는 `tests/test_6_55_shorts_studio.py`의 실패와 후속 대시보드 연결 종료다. 이번 변경 신규 실패는 **0건**이다. warning은 기존 `TestUploadAnnotation` pytest collection 경고다.
- Push: 별도 `p2-02-ai-workforce` branch만 push, main 직접 push 금지.
- 미완료: Agent runtime, tool adapter/API 연결, DNA 분석기, 자동 promotion/publication, Aside integration.
- 다음 권장: task/approval contract를 운영 검토하고 P2-03 public research adapter를 설계한다.