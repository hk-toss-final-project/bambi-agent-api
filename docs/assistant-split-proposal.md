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

### Step 2 — 선별 추출 — ✅ **완료 (2026-07-27)**
clustering·scoring·dedup·outcomes·embeddings를 `agent/selection`으로 이동, 이력 경계를 Protocol로 주입. assistant 그래프의 select 노드와 report_builder의 컨텍스트 선별(report_006 자리)이 같은 함수를 쓰게 한다.
- 효과: "선별 지능"이 두 소비자에 공식 공유. dedup 이력 맥락 분리 완성.
- 주의: AGENTS.md 규칙 9(facade), 규칙 8(선별에 LLM 요약 포함 시 bench).
- 구현 메모(2026-07-27):
  - 선별 임계값의 단일 소유자를 `agent/selection/features/config.py`로 옮겼다.
    수집 창(`COLLECT_WINDOW_DAYS`)·저장 경로처럼 선별과 무관한 값은 비서 쪽
    `agent/assistant/features/config.py`에 남겼다 — 소유 기준은 "누가 이 값을
    바꿔야 선별 결과가 바뀌는가"다.
  - **이력 경계는 `DedupHistory` Protocol 주입으로 바꿨다.** `record_report_items`는
    저장소를 받지 못하면 기록하지 않는다(기본값이 `None`). Step 0의
    `record_history` 플래그는 "기록하지 말라고 말해야" 안전했지만, 이제는
    **저장소를 건네야만 기록된다** — 기본 상태가 안전한 쪽이다. 비서는
    `storage.get_store()`를 넘기고, 리포트 생성 경로는 넘기지 않는다.
  - 조회(`load_recent_report_items`)도 저장소를 받아야 동작한다. 다만 조회는 이력을
    바꾸지 않으므로 비서 파이프라인에서는 `record_history`와 무관하게 저장소를
    넘겨 기존 동작(이미 본 소식 제외)을 유지했다.
  - LLM 호출이 선별에 새로 들어가지 않았으므로(전부 결정론적 수치 판단) 규칙 8의
    벤치마크 대상은 아니다. 그래프의 노드·엣지도 그대로라 규칙 10의 `/dev/graphs`
    레지스트리 갱신도 불필요했다.
  - report_builder가 이 라이브러리를 실제로 소비하는 것은 Step 3이다. 이번 단계는
    **공용 라이브러리를 세우고 비서를 그 위로 옮긴 것**까지다.

### Step 3 — report_builder를 풀 소비로 전환 — ✅ **완료 (2026-07-28)**
`collect_live_context`(그래프 중첩 호출) 제거 → load_context = 풀 조회 + 콜드 키워드 on-demand(타임아웃 短) + selection 선별.
- 효과: 리뷰의 P0 #4(lease 잠식) 완화, P1 순차 병목 대폭 축소, L 참조 대부분이 version_id 있는 G로 바뀌어 P0 #7(계약 드리프트) 단순화.
- 주의: agent-contract.md citation 절 갱신과 같은 PR로. /dev/graphs 레지스트리·가드 테스트 갱신(규칙 10). report_generation bench 재실행(규칙 8).

#### 완료 실측 (2026-07-28)

| 주제 | 이전(실시간 수집 전량) | 이후(풀 우선) | 본문 인용 표기 |
|---|---|---|---|
| 코스피 | 30~40초 | **12.7초** | P1 + G1·G2·G5 |
| 리센느 | — | **11.2초** | P4·P5 + G2·G4·G5 |
| Anthropic | 50.5초 | 35.6초 | P + L 4건 (풀이 잡음이라 수집 경로) |

풀 근거가 실제 인용되고 내용도 구체적이다.

```
코스피  "7월 28일 코스피는 미국 반도체주 급락 여파로 5% 이상 하락하며 매도
        사이드카가 발동됐다. 오전 10시 13분경 서킷브레이커가 발동되어 20분간
        매매가 중단되었다. 장중 6,038.27까지 내려앉으며…"
리센느  "SBS '인기가요', MBC '쇼! 음악중심'에서 1위 … 멤버 미나미는 트와이스
        사나와 '냉터뷰'에서 만남 … 카사베르디·CU·도미노 피자 모델로 발탁"
```

`Anthropic`은 풀 점수가 잡음 수준이라 필터가 걸러내고 실시간 수집으로 갔다 —
**판정이 양방향으로 작동함**을 확인한 사례다.

##### ⚠️ 미달성 — "L 참조가 G로 바뀐다"는 효과는 아직 나지 않았다

이 Step의 명시된 효과 중 하나가 **L 참조 대부분이 version_id 있는 G로 바뀌어
P0 #7(계약 드리프트)이 단순해진다**는 것이었다. 실측 결과 **그 효과는 없다.**

풀 문서를 근거로 쓴 실행의 저장된 citation을 보면 여전히 URL 기반이다.

```
[코스피] 최신 실행 — 저장된 citation
  document_version_id 있음   1건  (개인 Wiki '서킷 브레이커')
  document_version_id 없음   3건  (풀 기사 3건 — 프롬프트에서는 G로 표기됐다)
```

프롬프트 표기(`G1`)와 저장 형태(`L`)가 갈린다. 풀 문서 식별자는 `gsrc:<UUID>`인데
`citations.document_version_id`는 `wiki_document_versions`를 가리키는 컬럼이라
그대로 넣을 수 없기 때문으로 보인다.

따라서 **P0 #7은 여전히 열려 있다.** `agent-contract.md` citation 절을 갱신하려면
먼저 이 저장 경로를 정해야 한다 — 캐시 문서용 참조 컬럼을 추가할지, `gsrc:` 식별자를
계약에 정식으로 편입할지.

##### 규칙 점검

- **규칙 10(/dev/graphs)**: 갱신 불필요. `load_context` 노드 내부 로직만 바뀌었고
  노드·엣지 구조는 그대로다.
- **규칙 8(bench)**: `bench/report_generation` 재실행 완료(10/10, 회귀 없음,
  [결과](../bench/report_generation/results/2026-07-28_gpt-4.1-mini.md)). 다만 이
  벤치마크는 근거를 데이터셋에서 고정 주입하므로 **Step 3를 측정하지 못한다.**
  파이프라인 전체를 도는 벤치마크는 별도 과제다(데이터셋 변경이라 승인 필요).
- **agent-contract.md citation 절**: 미갱신. 위 "미달성" 절대로 저장 형태가 아직
  URL 기반이라, 계약을 고치기 전에 캐시 문서 참조를 어떻게 저장할지부터 정해야 한다.

##### 착수 후 드러난 것 — 진짜 병목은 조회가 아니라 근거 품질이었다

풀 검색·필터·판정을 다 붙이고도 리포트가 풀 근거를 **인용하지 않았다**. 세 번
잘못 짚은 뒤 네 번째에 원인을 찾았다.

| 가설 | 결과 |
|---|---|
| 문서가 길어서 LLM이 무시 | ❌ |
| 마이그레이션 0008이 청킹을 없애서 | ❌ |
| 팀원 구조 변경 탓 | ❌ |
| **Jina Reader 원문을 정제하지 않아 사이트 메뉴가 근거로 들어감** | ✅ |

62,000자짜리 '코스피 서킷브레이커' 기사의 앞부분이 통째로 메뉴였다. 정제기
(`clean_article_body`)는 **이미 있었고 리포트 경로에서만 쓰지 않았다.**

정제를 붙인 뒤에도 메뉴가 아주 긴 매체(톱스타뉴스 7,221자, 뉴스투데이 24,169자)는
본문에 닿기 전에 잘렸다. 기사 제목이 본문 머리에 나오는 성질을 이용해 시작점을
찾도록 고쳤다(`article_body_offset`, 매칭 12/12).

##### 함께 조정한 값

`POOL_SCORE_FLOOR`를 0.35 → 0.05로 낮췄다. 0.35는 마이그레이션 0008 **이전**
구조(wiki_chunks 청크 기반)에서 잰 값이라 새 구조에서 전부 탈락시켰다(0/20건).
새 구조 실측에서 구간이 뚜렷하게 갈렸다.

```
관련 있음   0.089 ~ 0.098  (풀에 수집한 주제 5개 · 25건)
잡음        0.000          (풀에 없는 주제 5개 · 20건 전부)
```

`ts_rank`는 문서가 길수록 값이 작아진다. 구조가 바뀌면 이 값을 다시 재야 한다.

##### 남은 한계

- 같은 풀 안의 오분류는 못 거른다. '삼성전자' 검색 2위로 "멜론 아이스크림"(0.093)이
  올라왔는데 1위(0.096)와 차이가 작아 상대 비율로도 걸러지지 않는다. 점수 자체의
  해상도 문제라 임계값으로는 풀리지 않는다.
- 정제 후에도 기사 앞에 "다른 공유 찾기", 쇼핑 위젯, 동영상 UI 같은 부스러기가
  수백 자 남는다. 2,000자 안에 본문이 들어오므로 실사용에는 지장이 없다.

#### 범위 정정 (2026-07-28 실측) — 풀 검색은 **이미 구현돼 있다**

> 이 절의 앞선 버전은 "풀 검색 기능을 새로 만들어야 한다"고 적었다. **그 결론은
> 틀렸다.** `content_store.fetch_global_article_texts`(URL 기반 보조 캐시)만 보고
> 판단했는데, 실제로는 `prag_003`이 개인 Wiki와 Global 풀을 **함께 검색**한다.
> 풀이 비어 있는 상태에서 코드만 읽어 내린 오판이었다. 아래는 풀을 채운 뒤 실제로
> 실행해 확인한 내용이다.

**풀 검색은 만들 필요가 없다.** `generation_runtime.py:280`이 두 Scope를 함께 훑고,
`P{n}`/`G{n}` 참조까지 붙여 반환한다.

```sql
WHERE chunk.namespace_key IN (%s, 'global')
  AND chunk.is_searchable
```

실측(2026-07-28) — 풀에 5개 키워드로 48건 수집·43건 본문 확보 후 `prag_003` 직접 호출:

```
[Anthropic]              개인 4 / Global 5
[ChatGPT]                개인 5 / Global 5
[주가]                    개인 5 / Global 5
[Domain-Driven Design]   개인 5 / Global 2
```

어제 리포트에 `G` 참조가 없었던 것은 **기능이 없어서가 아니라 풀이 0건이었기
때문이다.** Global 문서 48건이 청크 91건으로 색인돼 검색 대상이 되어 있다.

##### 그래서 Step 3에 실제로 남는 일

핵심은 **조회 기능이 아니라 실행 순서**다. 현재 `load_context`는 이렇게 돈다.

```
prag_003(개인 + 풀 검색)  →  collect_live_context(인터넷 전량 수집)  →  합침
```

풀에서 이미 5건을 찾아놓고도 **인터넷 수집을 그대로 다 수행한다.** 실행 시간
대부분이 여기서 나온다. Step 3는 "풀 결과가 충분하면 실시간 수집을 건너뛰고,
부족할 때만 콜드 수집"으로 바꾸는 작업이다.

- ✅ 풀 키워드 검색 — **이미 있음** (`prag_003`)
- 남음: `collect_live_context` 무조건 호출 제거, 충분/부족 판정 기준
- 남음: 콜드 경로(타임아웃 있는 동기 수집)

##### 함께 확인된 문제 — 풀 검색에 점수 컷오프가 없다

주제와 무관한 기사가 상위에 섞인다.

```
[Anthropic] → "암호화폐 버리고 AI로?…코인베이스 CEO"      score 0.061
[ChatGPT]  → "HK이노엔 케이캡, NSAIDs 관련 궤양 예방 3상"  score 0.076
[DDD]      → "[박준성의 SW] 에이전트 코딩, SW공학에 기반"   score 0.884
```

점수 자체는 변별력이 있다(0.06 vs 0.88). 하한선 없이 Scope별 상위 N건을 그대로
반환하는 것이 문제다. 풀 소비로 전환하면 이 자료가 곧바로 생성 근거가 되므로,
`agent/selection`의 상대 컷오프(`similarity_cutoff`) 방식을 적용할 후보다.

##### 부수 확인

- `--keywords`는 쉼표 목록을 **하나의 검색어로 이어붙인다**
  (`global_source_collector.py:109`의 `" ".join(...)`). 여러 주제를 모으려면 주제마다
  워커를 따로 실행해야 한다 — Step 4의 Job 발행 설계에서 전제할 것.
- 개념형 키워드는 풀에서도 약하다. `Domain-Driven Design`으로 수집한 10건이 DDD와
  무관한 AI 기사였다(Naver 뉴스가 영문 기술 용어에 취약).
- 풀과 비서의 소스 구성이 다르다(풀=Naver 한국 매체, 비서=Google News RSS·YouTube·
  Reddit 글로벌). 비서 쪽 URL은 리다이렉트 주소라 `canonical_url` 매칭도 성립하지
  않아, `fetch_global_article_texts`의 본문 재사용은 실측에서 0건이었다. 풀 소비로
  전환하면 이 경로의 중요도는 낮아진다.

### Step 4 — 관심사 루프 연결 (별도 트랙, Service 협의 필요)
global-collector를 CLI 배치에서 job_type 워커로 승격하고, Service가 INT-001/011 관심 topic으로 수집 Job을 발행. 리포트 생성 스케줄도 같은 관심사로.
- 효과: "wiki 개념어 → 수집 → 리포트"의 제품 루프가 처음으로 닫힘.
- 소유권: 스케줄·정책은 Service Layer(CLAUDE.md 원칙) — 우석(통합 오너·LLM팀 협의 창구) 통해 협의.

#### 착수 전 선결 조건 (2026-07-28 실측) — 수집 **품질**이 먼저다

**풀을 키우는 것만으로는 Step 3가 발동하지 않는다.** 관심사 20개를 모두 수집해
풀을 48건 → 128건(2.7배)으로 늘렸으나, 풀 검색 점수는 그대로였다.

```
             풀 48건    풀 128건
Anthropic    0.076  →   0.091     (절대 하한 0.35에 여전히 한참 못 미침)
```

내용을 보면 이유가 명확하다. `Anthropic`으로 수집한 문서가 Anthropic 기사가 아니다.

```
· Slow Letter: July 22, 2026 - 슬로우뉴스
· AI 시대의 국제안보, 한국의 전략은 무엇인가?
· Microsoft Unveils A.I. Cybersecurity Tools
```

**원인: Naver 뉴스가 영문 고유명사를 찾지 못한다.** 한국 매체는 "앤트로픽"으로
표기하므로 `Anthropic`으로는 매칭되지 않고, 대신 'AI'가 포함된 무관한 기사가
수집된다. 같은 이유로 `Domain-Driven Design` 수집분 10건도 전부 DDD와 무관했다.

키워드 20개 수집 결과를 성격별로 나누면 다음과 같다.

| 유형 | 예 | 결과 |
|---|---|---|
| 한국어 | 주가 · ADR 상장 | 정상 수집 |
| 영문 고유명사 | Anthropic · ChatGPT · Cloudflare | 수집은 되나 **무관한 기사** |
| 영문 도구·프로젝트명 | AutoWiki · DBeaver Community · DeepAgents · DTO(Data Transfer Object) | **0건** |

즉 현재 유일하게 살아 있는 소스(Naver)는 관심사의 상당 부분을 커버하지 못한다.
GDELT는 429(IP 차단)로 죽어 있는데, 원래 그 역할(글로벌 영문 뉴스)을 맡는 소스다.

**이 상태로 자동화하면 잡음 풀이 자동으로 쌓일 뿐이다.**

##### 조치 (2026-07-28) — 소스 구성으로 해결했다

> 이 절의 앞선 버전은 해법으로 **검색어 표기 변환**(`Anthropic` → `앤트로픽`,
> Wiki `metadata.aliases` 재사용)을 제안했다. **두 전제 모두 확인 결과 틀렸다.**
>
> - `metadata.aliases`는 **한 건도 채워져 있지 않다**(개인 Wiki 문서 전수 조회).
> - 한글 표기가 더 낫지도 않다. Naver에서 직접 비교한 결과 `앤트로픽`은 "미국판
>   AI 국부펀드 논란", `클라우드플레어`는 엔비디아 기사를 반환해 **영문 표기보다
>   나빴다.** 개선된 것은 `챗GPT` 하나뿐이었다.
>
> 표기 문제가 아니라 **소스 구성 문제**였다.

실제 원인은 둘이었고, 각각 조치했다.

**(1) Naver 정렬을 하나만 썼다.** `sort=date`는 신선하지만 부정확하고, `sort=sim`은
정확하지만 낡았다. 어느 쪽을 골라도 손해다.

| 키워드 | sort | 검색어 관련 | 평균 경과일 |
|---|---|---|---|
| Cloudflare | date | 3/10 | 7.1일 |
| Cloudflare | sim | 9/10 | **190.2일** |
| Anthropic | date | — (제목상 무관) | 0.2일 |
| Anthropic | sim | — (제목상 정확) | 1.1일 |

→ `NaverNewsProvider.search`가 **두 정렬을 모두 조회하고 URL로 중복 제거**하도록
바꿨다(실측: Cloudflare 10건 → 19건). 최종 순위는 수집기가 정하지 않는다.
`agent/selection`이 유사도 × 신선도로 판정하므로 낡았지만 정확한 기사와 신선하지만
무관한 기사가 각각 제 축에서 감점된다. 수집 단계는 후보를 넓게 확보하는 데만 집중한다.

**(2) `google_news`는 철회했다가 URL 디코딩으로 되살렸다.**

> 경과: 검색 정확도만 보고 기본에 넣었다가 → 본문 확보가 전부 실패해 철회 →
> `googlenewsdecoder`로 원본 URL을 복원해 재도입했다. 같은 날 세 번 바뀌었으므로
> 아래에 판단 근거를 전부 남긴다.

검색 정확도만 보면 Naver보다 확연히 낫다.

```
Naver(date)  'Cloudflare' → "Morgan Stanley Downgrades Adobe"     무관
google_news  'Cloudflare' → "Cloudflare Is Growing 28%" 외 5건 전부 정확
```

그래서 기본값에 넣었으나(`gdelt,naver,google_news`), **수집 2단계인 본문 채우기가
전부 실패했다.** Jina Reader가 `news.google.com` 리다이렉트 URL에서 403을 반환한다.

```
JINA_HTTP_403   google_news 수집분 111건 전원
```

리다이렉트는 HTTP로 풀리지 않는다. 실측한 세 방법이 모두 막혔다.

- `follow_redirects=True` — 최종 URL이 여전히 `news.google.com`(JS로 이동)
- 응답 HTML 파싱 — 외부 링크가 `lh3.googleusercontent.com` 이미지뿐
- RSS `<source url>` — 언론사 **홈페이지** 주소지 기사 주소가 아니다

**본문 없이 저장된 내용도 근거로 쓸 수 없다.** 길이는 215~704자로 비어 있지 않지만
내용이 "같은 사건을 다룬 여러 매체의 제목 나열"이다.

```
# 리센느, 역주행 '러브어택' 음방 1위… - v.daum.net
  리센느, 역주행 '러브어택' 음방 1위…      v.daum.net
  그룹 리센느, 지상파 음방 잇따라 석권…      news.sbs.co.kr
  리센느, '꿈 이룬' 국민 걸그룹 눈물…        조선일보
  ...
```

사실 정보가 제목뿐인데 **키워드가 반복돼 검색 점수만 높게 나온다.** 리포트가 이걸
근거로 뽑으면 제목만 되풀이하게 된다. 일부 문서는 본문 자리에 또 Google 리다이렉트
링크가 들어 있었다.

→ 일단 기본값을 `gdelt,naver`로 되돌리고 수집된 111건을 풀에서 제거했다(404 →
293건). 정리 기준은 길이가 아니라 `content_status='fetched'`다 — 길이로 판정하면
RSS 요약이 200자를 넘어 본문이 있는 것처럼 보인다.

##### 해결 — URL 디코딩으로 재도입

`googlenewsdecoder`(MIT)가 Google 내부 엔드포인트를 호출해 원본 기사 주소를
복원한다. 프로젝트 의존성으로 추가하기 전에 실측했다.

```
디코딩 정확도   31/31 (6건 + 25건 연속)
속도           1.2초/URL
429            없음 (간격 없이 25회 연속 호출)
```

GDELT가 같은 방식(무료 공개 엔드포인트 반복 호출)으로 IP 차단됐으므로 연속 호출을
따로 확인했다. 수집은 배치 워커라 URL당 1.2초가 리포트 응답 시간에 더해지지는
않는다.

`decode_google_news_url()`을 커넥터에 두고, **실패를 정상 경로로 다룬다.**

```
디코딩 성공 → 원본 URL로 저장 → 본문 확보 가능
디코딩 실패 → 빈 문자열 → 그 기사를 수집에서 제외
```

Google이 방식을 바꾸면 깨질 수 있는 의존이다. 그때 껍데기가 쌓이는 대신 조용히
건너뛰고 로그(`Google News 디코딩 실패로 N건 제외`)로 추적한다. 다른 Provider는
영향을 받지 않으므로 커버리지만 줄어든다.

디코더는 주입 가능하게 뒀다 — 단위 테스트가 Google 내부 엔드포인트를 호출하면
안 되기 때문이다.

전 구간 재검증(2026-07-28):

| 단계 | 철회 시점 | 재도입 후 |
|---|---|---|
| 검색 정확도 | ✅ | ✅ |
| URL 저장 | ❌ 구글 리다이렉트 | ✅ 원본 언론사 주소 |
| 본문 확보 | ❌ 403, 111건 전원 실패 | ✅ 5/5 성공 |

기본값을 `gdelt,naver,google_news`로 되돌렸다.

##### 남은 선결 조건

1. **GDELT 복구** — 여전히 429(IP 차단). 별도 담당자 진행 중이며, 복구되면 영문
   커버리지가 한 겹 더 두꺼워진다.
2. **0건 키워드 처리 방침** — 관심사에 도구·계정명(`choi.openai`, `Blob`)이 섞이는
   것은 INT-001 추출 품질 문제와도 닿아 있다. 수집 Job 발행 전에 거를지, 수집
   실패를 그냥 허용할지 정해야 한다. `AutoWiki`처럼 **실제로 뉴스가 없는** 키워드도
   있어, 0건을 곧바로 오류로 보면 안 된다.

부수적으로, 이번 실측에서 **Step 3의 절대 하한이 의도대로 동작함**이 확인됐다.
풀이 2.7배가 되어도 잡음은 잡음으로 판정해 실시간 수집 경로를 유지했다. 하한이
없었다면 128건 중 잡음 5건으로 리포트를 작성했을 것이다(같은 날 1차 구현에서
실제로 그런 결과가 나왔다).

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
