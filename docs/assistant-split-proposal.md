# Assistant 분해 제안 (Draft)

> 상태: **분해 방향 팀 확인 완료(2026-07-27)** · 작성일 2026-07-26
> 배경: [langgraph-agents-review-2026-07-26.md](langgraph-agents-review-2026-07-26.md)의 리뷰와
> "관심사 기반 수집 루프 미연결" 확인(INT-001 ↛ global-collector, 수집 경로 이중화)에 따른 후속 설계.
> 원칙: 그래프를 합치는 것이 아니라 **assistant가 겸직 중인 책임을 소유자에게 돌려주는 것.**

## 팀 확인 (2026-07-27) — assistant의 위상 정정

이 문서 초안은 assistant를 **"기능 ID 체계 밖의 별도 제품 라인"**으로 전제하고 썼다.
팀 확인 결과 **그 전제는 사실과 다르다.**

- assistant의 기능(데이터 수집 → 임베딩·유사도 검색 → 리포트 생성 → 뷰어)은 원래
  **스캐폴드 구조에서 각자 소유자가 있던 역할**이며, 별도 제품으로 기획된 것이 아니다.
  팀을 나눠 개발하면서 한곳에 모인 결과다.
- 따라서 **분해 방향(Step 1~3)은 구조상 맞다**는 점이 확인됐다.
- 다만 **웹 UI는 assistant에 남긴다.** 남기는 이유는 "독립 제품이라서"가 아니라
  **분리된 기능을 한 번에 실행하고 눈으로 확인하는 테스트 뷰어**로 쓰기 위해서다.
  (실제로 임계값 보정·클러스터링·품질 루프 검증이 모두 이 화면으로 이뤄졌다.)

이 정정에 따라 아래 본문의 "브리핑 제품"은 **"테스트 뷰어"**로 읽는다. 결론(잔류
대상 목록)은 같지만 근거가 다르므로, Step 3에서 "프로덕션 경로(report_builder)가
테스트 뷰어를 호출하지 않는다"는 점이 더 분명한 근거를 갖는다.

---

## 1. 진단 — assistant는 지금 4개 책임을 겸직한다

`agent/assistant/features/`의 실제 파일을 책임 단위로 해부하면:

| 책임 | 파일 | 성격 | 정당한 소유자 |
|---|---|---|---|
| ① 수집 (fetch) | youtube.py(검색·자막) · feeds.py(Google News RSS + Jina) · reddit.py · dates.py(날짜 정규화) | 키워드 → 원시 아이템. 네트워크 I/O | **수집 워커** (infrastructure/sources + global-collector) |
| ② 선별 (select) | embeddings.py · clustering.py · scoring.py · dedup.py · outcomes.py · summarize.py | 원시 아이템 → 순위·중복제거된 근거 집합. 결정론 + LLM 요약 | **공용 라이브러리** (브리핑·리포트 둘 다 소비) |
| ③ 테스트 뷰어 | graph.py(plan·reformulate·write_report) · report.py(워터폴 Markdown) · stocks.py(주가 차트) · web UI · history.py의 클릭/노출 이력 | 분리된 기능을 한 번에 실행·확인하는 개발용 화면 | **assistant 잔류** |
| ④ 이력 (storage) | storage.py · history.py의 수집 이력 | 개인화 기억. ②의 dedup 입력이자 ③의 노출 기록 | **분리** — 수집 dedup 이력은 ②로, 클릭/노출 이력은 ③으로 |

문제는 이 4개가 `assist_daily_agent` 단일 진입점 뒤에 묶여 있어서, report_builder가 ①+②만 필요한데 ③+④의 부작용(보고서 생성, 이력 기록)까지 함께 실행된다는 것이다. 동시에 ①은 global-collector 워커와 소스가 겹친다(Google News RSS 이중 수집).

## 2. 목표 구조 — 4책임의 재배치

```
[수집]   infrastructure/sources/connectors  ← youtube·reddit provider 이식, RSS는 기존 col_001로 일원화
         └─ global-collector 워커(키워드) → G 풀(namespace='global', content_status 2단계)
         └─ 동기 진입점(콜드 키워드 on-demand용, 타임아웃·이력 기록 없음)

[선별]   agent/selection (신설, facade + features)
         └─ 임베딩 필터 → 클러스터링 → 스코어링 → dedup → (요약)
         └─ 이력 저장소는 Protocol 주입, record_history 플래그로 기록 여부를 호출자가 결정
         └─ 소비자 2: assistant 브리핑, report_builder 컨텍스트 선별

[브리핑] agent/assistant (잔류, 축소)
         └─ 그래프: plan → select(=selection 호출) → reformulate 루프 → write_report
         └─ report.py 워터폴 · stocks.py 차트 · web UI · 클릭/노출 이력

[리포트] agent/report_builder
         └─ load_context = G 풀 조회(prag_003) + 콜드 키워드만 on-demand 수집 + selection 선별
         └─ assistant 그래프 중첩 호출(collect_live_context) 제거
```

핵심 이동 원칙 세 가지:

1. **수집은 저장(풀)을 향하고, 요청 경로는 풀을 읽는다.** 신선도는 워커 주기가 담당하고, 풀에 없는 콜드 키워드만 타임아웃 있는 동기 수집으로 보충한다.
2. **선별은 "이력을 읽되, 기록 여부는 호출자가 결정"하는 순수 경계로.** 브리핑은 기록하고, 리포트 생성은 기록하지 않는다(이력 오염 차단). dedup 이력에 소비 맥락(briefing/report) 차원을 추가한다.
3. **assistant는 테스트 뷰어만 남긴다.** 재구성 루프와 워터폴 보고서는 브리핑의 품질 장치이므로 잔류. 단 "재구성"의 의미는 (풀 재검색 → 부족 시 on-demand 수집 요청)으로 바뀐다.

## 3. 파일별 이동 매핑

| 현재 (agent/assistant/features/) | 이동 후 | 비고 |
|---|---|---|
| feeds.py 중 RSS 수집 | 삭제 → `connectors`의 기존 `col_001`(GoogleNewsRss) 재사용 | 이중 수집 해소 |
| feeds.py 중 Jina 정제 | `infrastructure/sources/processing` | global-content(Jina fetcher) 워커와 동일 계열 |
| youtube.py | `connectors`에 YouTube provider 신설 (검색=수집 단계, 자막=fetcher 단계) | COL-* ID 부여 여부 팀 협의 |
| reddit.py | `connectors`에 Reddit provider 신설 | 〃 |
| dates.py | `infrastructure/sources/processing` | gsp_*와 합류 |
| embeddings.py · clustering.py · scoring.py · dedup.py · outcomes.py | `agent/selection` 신설 | facade(api.py) + features 규칙 준수 |
| summarize.py | `agent/selection` (요약은 선별의 마지막 단계) 또는 `agent/llm` 헬퍼 | 요약 시점 결정 필요 (§5-1) |
| pipeline.py | 해체 — 수집부는 sources 호출로, 선별부는 selection으로 | 현재 결정론 설계라 분해 용이 |
| storage.py 수집 이력 · history.py 수집 이력 | `agent/selection` 소유 (Protocol 뒤) | purpose(briefing/report) 컬럼 추가 |
| history.py 클릭/노출 이력 · stocks.py · report.py · graph.py · service.py · web UI | assistant 잔류 | 테스트 뷰어 |

## 4. 단계별 마이그레이션 (각 단계 독립 배포 가능, 리스크 낮은 순)

### Step 0 — 즉효 패치 (반나절, 구조 변경 없음) — ✅ **완료 (2026-07-27)**
`assist_daily_agent`에 `record_history=False`, `include_report=False` 옵션을 추가하고 `collect_live_context`가 그것으로 호출.
- 효과: 이력 오염 즉시 차단(리뷰 P1), weekly 폴백 LLM 낭비 제거. 그래프 중첩은 아직 유지.
- 검증: tests의 live_sources·pipeline mock 테스트 갱신.
- 구현 메모: `record_history=False`여도 **이력 읽기는 유지**한다 — `first_seen`이 발행일
  확정 폴백에 쓰이므로 읽기까지 막으면 날짜 로직이 깨진다. 쓰기만 건너뛴다.
  회귀 테스트 3종 추가(플래그 전달 확인, 이력 미증가, 기본값 True 유지).
  자세한 내용은 [keyword-assistant.md](keyword-assistant.md) "소비 맥락 플래그" 절 참조.

### Step 1 — 수집 일원화 — ✅ **완료 (2026-07-27)**
RSS를 col_001 재사용으로 교체하고 YouTube·Reddit provider를 connectors로 이식. assistant는 connectors를 import해서 사용(동작 동일). global-collector가 5개 소스(GDELT·Naver·GoogleNews·YouTube·Reddit)를 키워드로 수집 가능해짐.
- 효과: 수집 코드 단일 소유, G 풀의 소스 커버리지 확대.
- 주의: youtube-search-python의 httpx 핀(<0.28) 의존성이 sources 계층으로 따라감.
- 구현 메모(2026-07-27): httpx 핀은 **이미 pyproject 전역 제약**이었고 공용 커넥터(`latest.py`·`url.py`)가 이미 httpx를 쓰고 있어, 이식으로 새로 생긴 제약은 없다.
  뉴스 RSS는 이 단계 이전에 이미 공용 Provider로 전환돼 있었다. 이번에 옮긴 것은
  **YouTube·Reddit 검색**이며, `YouTubeSearchProvider`·`RedditSearchProvider`로
  `LatestInformationProvider` 규약을 따른다. 자막 조회·요약은 소비 단계 관심사라
  비서에 남겼다(뉴스가 목록 수집 → Jina 본문 확보로 나뉜 것과 같은 분리).
  비서의 `search_videos`·`search_posts`는 겉모습을 유지한 채 Provider에 위임하므로
  파이프라인 동작은 동일하다.

### Step 2 — 선별 추출
clustering·scoring·dedup·outcomes·embeddings를 `agent/selection`으로 이동, 이력 경계를 Protocol로 주입. assistant 그래프의 select 노드와 report_builder의 컨텍스트 선별(report_006 자리)이 같은 함수를 쓰게 한다.
- 효과: "선별 지능"이 두 소비자에 공식 공유. dedup 이력 맥락 분리 완성.
- 주의: AGENTS.md 규칙 9(facade), 규칙 8(선별에 LLM 요약 포함 시 bench).

### Step 3 — report_builder를 풀 소비로 전환
`collect_live_context`(그래프 중첩 호출) 제거 → load_context = 풀 조회 + 콜드 키워드 on-demand(타임아웃 短) + selection 선별.
- 효과: 리뷰의 P0 #4(lease 잠식) 완화, P1 순차 병목 대폭 축소, L 참조 대부분이 version_id 있는 G로 바뀌어 P0 #7(계약 드리프트) 단순화.
- 주의: agent-contract.md citation 절 갱신과 같은 PR로. /dev/graphs 레지스트리·가드 테스트 갱신(규칙 10). report_generation bench 재실행(규칙 8).

### Step 4 — 관심사 루프 연결 (별도 트랙, Service 협의 필요)
global-collector를 CLI 배치에서 job_type 워커로 승격하고, Service가 INT-001/011 관심 topic으로 수집 Job을 발행. 리포트 생성 스케줄도 같은 관심사로.
- 효과: "wiki 개념어 → 수집 → 리포트"의 제품 루프가 처음으로 닫힘.
- 소유권: 스케줄·정책은 Service Layer(CLAUDE.md 원칙) — 우석(통합 오너·LLM팀 협의 창구) 통해 협의.

## 5. 결정이 필요한 사항

1. **요약 시점** — 자막·본문 LLM 요약을 수집 시(풀에 저장, 비용 선지불·재사용) vs 소비 시(신선, 매번 비용). 제안: 원문/자막 확보는 fetcher 단계, LLM 요약은 소비 시 + 결과를 풀 metadata에 캐시.
2. **이력 분리 방식** — `assistant_collected_documents`에 purpose 컬럼 추가 vs 별도 테이블. 제안: 컬럼 추가(마이그레이션 최소).
3. **selection의 위치** — `agent/selection` vs `domain/selection`. AI 파생 로직이므로 agent/ 제안. 팀 컨벤션 합의 필요.
4. **기능 ID 부여** — assistant는 명세상 "기능 ID 없는 별도 제품 라인"으로 적혀 있었으나(2026-07-27 정정: 실제로는 테스트 뷰어), sources로 이식되는 수집기는 COL-*/GSP-* 체계에 편입되는 것이 자연스러움. 명세 문서 갱신 동반.
5. **재구성 루프의 새 정의** — 풀 조회 기반에서 "검색어 재구성"이 무엇을 다시 하는가(풀 재검색만? on-demand 수집 트리거까지?). 브리핑 품질 요구 수준에 따라 결정.

## 6. 이 분해가 해소하는 기존 리뷰 항목

| 리뷰 항목 | 해소 단계 |
|---|---|
| P1 — 비서 개인화 이력 오염 | Step 0에서 즉시 |
| P2(하향) — weekly 폴백 LLM 낭비 | Step 0 |
| P1 — load_context 완전 순차 처리 | Step 3 (풀 조회로 전환) |
| P0 #4 — lease 초과·이중 실행 위험 | Step 3 (중첩 그래프 제거로 실행 시간 단축) |
| P0 #7 — agent-contract L citation 드리프트 | Step 3 (L 축소·G화와 함께 계약 갱신) |
| 수집 경로 이중화 (RSS 양쪽 수집) | Step 1 |
| 관심사 루프 미연결 (INT-001 ↛ collector) | Step 4 |

## 7. 건드리지 않는 것 (비목표)

- assistant 그래프와 report_builder 그래프의 병합 — 하지 않는다. 소비 맥락(브리핑 vs 리포트)이 다르므로 그래프는 각자 유지.
- 테스트 뷰어(워터폴 보고서·stocks 차트·UI)의 기능 변경 — 없음.
- pgvector 재도입, LLM 의미 판정 등 품질 고도화 — 이 문서 범위 밖(리뷰 P1 참조).
