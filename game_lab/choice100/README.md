# 선택100 (CHOICE100) — V2 프로토타입

TAK GAME FACTORY 첫 실험(6-64 G1 → 6-65 V2, 40선택). 설계는 `docs/6-64-choice100-finance-g1.md`·`docs/6-65-choice100-game-feel-v2.md`, 후보 전략은 `docs/6-63-game-factory-candidate-strategy.md`.
이 폴더는 production·MONEY와 분리돼 있다. 폴더째 지워도 TAK AUTO 핵심 기능에 영향이 없다.

## 실행

```
py -m http.server 8790 --bind 127.0.0.1 -d game_lab/choice100
# 브라우저: http://127.0.0.1:8790/
```

서버·로그인·광고·결제 없음. 정적 파일만 쓴다(`fetch`로 JSON을 읽기 때문에 file:// 대신 로컬 서버로 연다).

## 구조

| 파일 | 역할 |
|---|---|
| `engine.js` | 게임 규칙(DOM 없음, 도메인 모름). 브라우저 `window.Choice100`, Node `require` |
| `renderer.js` | 화면(`window.Choice100Renderer.boot(root, dataUrl)`) - 같은 화면 결과, 키보드 1~4 선택 / → 다음 |
| `analytics.js` | 로컬 플레이 기록(이 브라우저 localStorage만, 서버 전송 없음) |
| `data/finance.json` | 금융 게임 내용: 변수·규칙·10챕터·40시나리오·엔딩·플레이 스타일 |
| `index.html` | 페이지와 CSS(모바일 우선) |
| `sim.js` | 자동 플레이어(밸런스 점검): `node sim.js data/finance.json 400 100` (무작위 400 + 전략별 변형 100). 결과는 화면에만 출력 — 성과 데이터 아님 |
| `test/engine.test.js` | 엔진 테스트(`node --test game_lab/choice100/test/engine.test.js`) |

다른 게임(한국사·한자)은 `data/*.json`을 새로 만들고 `index.html`의 데이터 경로만 바꾼다. 엔진은 고치지 않는다.

## 시나리오 추가(41~100)

`data/finance.json`의 `scenarios`에 같은 형식으로 추가하고, 마지막 시나리오의 `next`를 새 id로 바꾼다.
나중에 돌아오는 선택은 `set_flags` + 다른 시나리오의 `triggers`(켜기만 하고 돌아오지 않는 flag는 검증 오류).
데이터를 바꾸면 `version`과 `index.html`의 `?v=`를 올린다(옛 저장·캐시 무효화).
`chapters[n].status`를 `playable`로 바꾼다. `node --test …`와 `py -m unittest tests.test_6_64_choice100`이 형식·연결·도달 가능성을 검사한다.

본 게임은 금융 의사결정 학습을 위한 가상 시뮬레이션이며 실제 금융상품·투자·대출에 대한 조언이 아니다.
