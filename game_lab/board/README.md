# CHOICE100 BOARD — G0/G1 코어

QUIZ → REWARD(주사위 특권) → DICE → BOARD → 칸(도시·교역·탐험·사건·보너스·퀴즈) → 다음 QUIZ.
설계·결과: `docs/6-66-choice100-board-game-core.md`. 금융 선택형 게임(`../choice100/`)과는 별도 폴더다(그 게임은 그대로).

## 실행

```
py -m http.server 8790 --bind 127.0.0.1 -d game_lab
# 세계사 보드: http://127.0.0.1:8790/board/world/
# 금융 선택100: http://127.0.0.1:8790/choice100/
```

## 구조

| 파일 | 역할 |
|---|---|
| `engine.js` | 규칙(DOM 없음, 도메인 모름). 브라우저 `window.Choice100Board`, Node `require` |
| `renderer.js` | 화면(`Choice100BoardRenderer.boot(root, dataUrl)`), 키보드 1~4 / → |
| `world/world.json` | 세계사 데이터: 퀴즈 15(출처·확인일), 보드 24칸, 교역품, 엔딩 |
| `world/index.html` | 페이지·CSS(390px 우선) |
| `sim.js` | 자동 플레이어: `node sim.js world/world.json 100` (전략 4 × 정답률 3 × 100판). stdout만 |
| `test/board.test.js` | `node --test game_lab/board/test/board.test.js` |

기록은 `../choice100/analytics.js`(이 브라우저 localStorage만)를 같이 쓴다.
주사위는 조작하지 않는다: 매 굴림 `1 + floor(rng × 6)`, 기본 rng는 `crypto.getRandomValues`. 정답 보상은 홀짝 **선언권**이며 적중 확률은 3/6이다.
