# TAK AUTO Trend Discovery MVP

## 목적

TAK AUTO 1은 특정 업종 전용이 아닌 범용 트렌드 키워드 발굴·콘텐츠 기획 도구다. 경매는 별도 제품인 TAK AUTO 2에서 다룬다. 이 저장소의 기존 경매 조사 코드는 호환성을 위해 보존하지만, 기본 조사 프로필은 general이다.

## 현재 구현

1. 공개 RSS 수집: Google News Korea(전체·기술·비즈니스·과학·엔터테인먼트·건강), BBC Business/Technology, Hacker News, The Verge.
2. 후보 중복 제거와 기존 SCOUT 후보 점수 정렬.
3. 제목·요약의 단어를 기반으로 피드 내부 반복 키워드 집계.
4. 날짜별 키워드 관측 이력 저장.
5. 직전 관측일 대비 반복 건수가 증가한 키워드를 급상승 후보로 표시.
6. 출처 다양성과 언급 건수를 이용한 편집 기회 참고 점수 산출.
7. 매일 오전 8시(KST) GitHub Actions 실행 및 결과 저장.

## 결과 파일

- `data/tak_scout_daily.json`, `data/tak_scout_daily.md`: 오늘 수집한 후보
- `data/tak_auto_trend_daily.json`, `data/tak_auto_trend_daily.md`: TOP 키워드, 상승 후보, 콘텐츠 기회 후보
- `data/tak_auto_trend_history.json`: 날짜별 키워드 관측 이력

로컬 실행:

```bash
python3 scripts/run_scout.py --max 30
python3 scripts/run_trend_report.py
python3 -m unittest discover -s tests -p 'test*.py' -v
```

## 지표의 정확한 의미와 한계

현재 데이터는 등록된 공개 RSS 피드에서 수집된 기사 제목·요약의 반복 횟수다.

- TOP 키워드: 해당 수집분에서 2건 이상 언급된 단어의 반복 횟수와 출처 수
- 급상승 후보: 직전 저장 관측일보다 현재 관측일의 피드 내 언급 건수가 증가한 단어
- 콘텐츠 기회 점수: 피드 내 언급 건수와 출처 수를 이용한 편집 우선순위 휴리스틱

다음 데이터는 현재 수집하지 않는다: 네이버 검색량, Google 검색량, YouTube 조회·검색 트렌드, Threads 반응, 광고 키워드 경쟁도. 따라서 결과를 전체 인터넷 트렌드, 검색량, SNS 인기, 저경쟁 키워드라고 부르지 않는다. 급상승 비교는 수집 피드 구성·수집량 변화의 영향을 받을 수 있다. 관측 이력이 없는 첫 실행에서는 급상승 목록이 비어 있는 것이 정상이다.

## 안전 경계

RSS는 공개 피드만 사용한다. 로그인, 접근 제한 우회, 비공개 데이터 수집을 하지 않는다. 외부 게시 자동화는 수행하지 않으며 콘텐츠는 별도 검토·승인 절차를 거친다. 검색 API 자격 증명이 필요한 공식 데이터 제공자는 키를 임의로 만들거나 커밋하지 않고 별도 어댑터로 추가한다.

## 다음 고도화

- 정식 검색 트렌드 API 및 YouTube Data API 어댑터(사용자 자격 증명·쿼터 필요)
- 출처별 수집량 정규화 및 키워드 구문/동의어 정규화
- 최소 2~4주 데이터 축적 후 안정적인 추세 비교
- 콘텐츠 성과(조회·클릭·체류·전환) 피드백 루프
