# TAK SCOUT Perplexity MVP 실행 안내 (Windows)

이 문서는 Windows 10/11 + PowerShell에서 현재 Perplexity 조사 MVP를 직접 확인하는 절차입니다. 실행 결과와 API 사용료는 로컬 환경 및 Perplexity 계정 설정에 따라 달라집니다.

## 1. 준비물
- Git for Windows
- Python 3.11 이상
- Perplexity API 키
- 인터넷 연결

버전 확인:
```powershell
py --version
git --version
```

## 2. 기능 브랜치 내려받기

처음 받는 PC:
```powershell
git clone --branch feature/perplexity-research-provider https://github.com/sopptak/tak-auto.git
cd tak-auto
```

이미 저장소가 있다면 먼저 변경사항을 확인하고 브랜치를 전환합니다.
```powershell
git status
git switch feature/perplexity-research-provider
git pull origin feature/perplexity-research-provider
```
커밋하지 않은 변경사항이 있으면 먼저 커밋하거나 별도 보관하세요. 작업 중인 파일을 무작정 덮어쓰지 마세요.

## 3. SCOUT 후보 생성

대시보드는 오늘의 SCOUT 후보 파일이 있어야 시작됩니다. 등록된 공개 RSS를 읽어 후보를 생성합니다.
```powershell
py scripts/run_scout.py
```
생성 파일:
- data/tak_scout_daily.json — 대시보드 후보 데이터
- data/tak_scout_daily.md — 사람이 읽는 후보 목록

RSS 수집이 실패하면 터미널의 source별 오류를 확인하세요. 조사 기능을 시험하기 전에 후보가 최소 1건 생성됐는지 확인해야 합니다.

## 4. Perplexity API 키 설정

현재 PowerShell 창에서만 키를 설정합니다. 따옴표 안에 실제 API 키를 넣으세요.
```powershell
$env:TAK_SCOUT_PERPLEXITY_API_KEY = "여기에_실제_API_키"
```
이 설정은 현재 PowerShell 세션에만 적용됩니다. 키를 소스 코드, JSON, 문서 또는 GitHub commit에 입력하지 마세요. 화면 공유나 로그에 키가 노출되지 않도록 주의하세요.

선택적으로 모델을 지정할 수 있습니다.
```powershell
$env:TAK_SCOUT_PERPLEXITY_MODEL = "sonar-pro"
```

## 5. 대시보드 실행

```powershell
py scripts/run_scout_dashboard.py
```
브라우저에서 http://127.0.0.1:8000 을 엽니다.

SCOUT 후보 카드의 'Perplexity 조사'를 누르면 실시간 조사 요청이 발생합니다. 이때 API 사용량 또는 비용이 발생할 수 있습니다. 페이지를 여는 것만으로 조사 요청을 보내지는 않습니다.

## 6. 결과 확인 및 검토

'심층 조사 결과'에서 답변, 인용 URL, 품질 점수와 경고를 확인합니다. 인용 URL을 직접 열어 핵심 주장과 원문 날짜를 확인한 뒤 'TAK BRAIN 검토 초안 만들기'를 사용할 수 있습니다.

생성된 KNOWLEDGE는 pending 상태입니다. 사람이 검토하고 승인하기 전에는 승인 자료가 아니며, 자동 승인이나 자동 게시로 이어지지 않습니다.

로컬 산출물:
- data/tak_scout_research.json
- data/tak_scout_research.md
- data/tak_brain_knowledge.json

이 데이터 파일들은 기본적으로 Git 추적 대상이 아닙니다. 실제 원문·조사결과·API 키를 GitHub에 올리지 마세요.

## 7. 종료 및 문제 해결
- 대시보드 종료: 실행 중인 PowerShell 창에서 Ctrl+C
- data/tak_scout_daily.json 없음: 3단계 SCOUT 수집부터 실행
- Perplexity 기능 비활성: 같은 PowerShell 창에서 API 키를 설정한 뒤 대시보드를 다시 시작
- 포트 8000 사용 중: py scripts/run_scout_dashboard.py --port 8001 실행 후 http://127.0.0.1:8001 접속
- Python 명령 문제: py --version으로 설치 여부와 버전 확인

## 품질 판정의 한계

현재 품질 게이트는 응답 존재, 원문 URL·발행일·조사 시각, 인용 URL 수와 도메인 수 등 기록 완전성 및 출처 흔적을 확인합니다. 인용 페이지를 실제로 열어 주장을 검증하거나, 인용문이 주장에 부합하는지 또는 출처가 독립적인지 판단하지 않습니다. 높은 점수도 사실 검증 완료를 의미하지 않습니다.

법률·금융·정책·세금·수치가 포함된 콘텐츠는 공식 1차 자료와 원문을 사람이 확인한 뒤 사용하세요. 이 MVP는 자동 승인, 자동 게시, 운영 배포를 수행하지 않습니다.
