# Global 수집 스케줄링 — 구현 인수인계 메모 (Step 4)

> 상태: **구현 대기 (담당자 배정됨)** · 작성 2026-07-28
> 관련: [assistant-split-proposal.md](assistant-split-proposal.md) Step 4
> 이 문서는 원래 Service 팀 협의안으로 썼으나, **스케줄러를 우리 서버에서 돌리는
> 것으로 결정**되어 구현 인수인계 자료로 다시 정리했다.

## 1. 결정된 설계

```
우리 서버가 스케줄러를 직접 돌린다 (서버 시작 시 자동 실행)
service-api는 주기만 API로 조정한다
```

앞선 초안은 "스케줄·정책은 Service Layer 소유이므로 Service가 Job을 발행해 달라"는
전제였다. **그 전제는 폐기됐다.** Service 팀 착수를 기다리지 않아도 되는 쪽이 낫다는
판단이다.

## 2. 구현 범위

| | 항목 | 상태 |
|---|---|---|
| ① | `SCH-002`/`003`/`004` 구현 (`scheduler/features/collection.py` 전부 `NotImplementedError`) | ❌ |
| ② | 서버 시작 시 스케줄러 자동 실행 | ❌ |
| ③ | 수집 → Jina Reader 본문 캐싱 → `global_source_documents` 적재 | ✅ **완료 (2026-07-28)** |
| ④ | service-api가 주기를 조정할 API 엔드포인트 | ❌ |

③은 이미 동작한다. 현재 적재 상태:

```
agent.global_source_documents   260건
  fetched  249건 (평균 본문 22,741자)
  failed    11건 (유료 구독·접근 차단)
```

리포트가 이 테이블에서 근거를 꺼내 쓰는 것까지 검증됐다(Step 3). 남은 것은
**자동 실행**뿐이다.

## 3. ⚠️ 착수 전에 알아야 할 것

2026-07-28에 수동으로 12회 실행하며 부딪힌 지점들이다.

### 3.1 `keywords`는 하나의 검색어로 합쳐진다

```python
# workers/features/global_source_collector.py:109
query = " ".join(keyword.strip() for keyword in keywords if keyword.strip())
```

관심사 20개를 한 번에 넘기면 `"코스피 삼성전자 멜론 …"` 단일 질의가 되어 **0건**이
나온다. **주제마다 따로 실행**해야 한다.

```python
# 잘못
await worker_001(keywords=["코스피", "삼성전자"], ...)   # → 0건

# 올바름
for topic in topics:
    await worker_001(keywords=[topic], ...)
```

### 3.2 본문 채우기 배치 상한은 100이다

```python
# infrastructure/persistence/features/global_source.py:217
if not 1 <= limit <= 100:
    raise ValueError("Global 기사 Claim limit은 1에서 100 사이여야 합니다.")
```

260건을 채우려면 100씩 나눠 여러 번 호출한다.

### 3.3 Provider별 소요 시간이 다르다

| Provider | 특성 |
|---|---|
| `naver` | 최신순·관련도순 두 번 호출(중복 제거) — 키워드당 약 19건 |
| `google_news` | URL 디코딩에 **약 1.2초/건** — 키워드당 12초쯤 추가 |
| `gdelt` | **현재 429(IP 차단)로 죽어 있음** — SCH-003을 구현해도 지금은 안 돈다 |

주기를 정할 때 google_news 디코딩 시간을 감안한다. 키워드 12개면 수집만 3~5분이다.

### 3.4 `newsapi`(SCH-004)는 키가 없다

`.env`에 `NEWSAPI_KEY`가 없어 구현해도 동작하지 않는다. 발급 여부를 먼저 정한다.

### 3.5 SCH-001(RSS)이 범위에서 빠져 있다

현재 `google_news` Provider가 RSS 기반이라 실질적으로 SCH-001에 해당한다. 002/003/004만
구현하면 **영문 키워드에서 가장 잘 동작하는 소스가 스케줄에서 빠진다.**

실측: `Cloudflare` 수집 시 Naver는 10건 중 관련 3건, google_news는 5건 전부 관련.

→ 명세 ID가 아니라 **실제 동작하는 Provider 기준**(naver·google_news·gdelt)으로
맞추는 것을 제안한다.

## 4. 아직 정해지지 않은 것

### 4.1 대상 키워드

명세에는 "정기 등록한다"만 있고 대상이 없다.

| 후보 | 우려 |
|---|---|
| 관심사 전체 | 사용자가 늘면 외부 API 호출이 비례해 증가 |
| 관심사 상위 N개 | N을 정해야 함 |
| 고정 목록(설정) | 개인화가 안 됨 |

2026-07-28에 degree 전달 버그가 수정되어 **관심사 점수가 변별력을 갖는다.**

```
OpenWiki 1.000 · SK하이닉스 0.782 · Obsidian Web Clipper 0.682 · 레버리지 상품 0.638 …
```

다만 관심사에 도구·계정명이 섞인다(`choi.openai`, `Blob`). 실측에서 20개 중 4개가
0건이었다. **`AutoWiki`처럼 실제로 뉴스가 없는 정상 키워드도 있어, 0건을 곧바로
오류로 보면 안 된다.**

### 4.2 사용자별 vs 전역

Global 풀은 소유자가 없는 공유 캐시다. 사용자 A의 관심사로 수집한 문서를 B도 쓴다.
같은 키워드를 여러 사용자가 가질 때 중복 발행할지, 합집합으로 한 번만 돌릴지.

중복 발행해도 `canonical_url` 충돌로 저장은 중복되지 않지만 외부 API 호출은 낭비된다.

### 4.3 주기

토픽 성격에 따라 다르게 가는 것을 제안한다. Agent는 이미 개념형/뉴스형을 판정하고
있다(`agent/assistant/features/topic_intent.py`, Wiki `document_kind` 기반).

```
뉴스형(코스피·삼성전자)   짧게 — 당일 소식이 중요하다
개념형(DDD·API 키 발급)   길게 — 몇 달 전 자료도 유효하다
```

## 5. 왜 필요한가 — 실측

풀이 채워졌을 때와 아닐 때의 차이다.

```
코스피 리포트
  풀 있음   12.7초 · 근거에 당일 급락·서킷브레이커 발동 사실 포함
  풀 없음   30~40초 · 실시간 수집 경로

리센느 리포트
  풀 있음   11.2초 · 음악방송 1위·브랜드 모델 발탁 등 구체적 사실
```

지금은 수동으로 채운 날만 빠르고, 다음 날이면 풀이 늙어 원래대로 돌아간다.
**Step 3의 성과가 하루짜리인 이유가 이것이다.**

판정은 양방향으로 작동한다. `Anthropic`은 풀 자료가 잡음 수준이어서 필터가 걸러내고
실시간 수집으로 갔다 — 풀이 있다고 무조건 쓰지 않는다.

## 6. 이 작업과 별개로 열려 있는 항목

- GDELT 429(IP 차단) 복구 — 복구되면 영문 커버리지가 한 겹 두꺼워진다.
- 풀 문서를 근거로 써도 citation이 URL 기반(`L`)으로 저장된다.
  `agent-contract.md` citation 절 갱신의 선행 조건이다.
