# LLM Wiki Navigator 설계

> 상태: **구현 승인됨 (2026-08-10)**
>
> 목적: Report Builder와 다른 Consumer Agent가 개인 LLM Wiki의 저장 구조를
> 직접 알지 않고도 Page를 찾고, 읽고, Link를 따라가며, 출처가 보존된 Context를
> 받을 수 있는 표준 Read Interface를 정의한다.

## 1. 책임 경계

Navigator는 LLM Wiki의 Read API다. 최종 답변이나 리포트를 생성하지 않는다.

```text
Reader / Report Agent
  → Locate (후보 Page 최대 30개)
  → Consumer가 Seed Page 선택
  → Read
  → Traverse
  → Context Packet
  → Consumer가 최종 추론·작성
```

Navigator의 책임은 다음과 같다.

- Logical Index에서 관련 Page 후보를 회수한다.
- Consumer가 선택한 정확한 Page Version과 관련 Chunk를 읽는다.
- 검증된 Wiki 관계를 제한된 깊이로 순회한다.
- Page·관계·원본 출처·탐색 Trace를 구조화된 Context Packet으로 조립한다.

Navigator는 다음을 하지 않는다.

- 최종 답변·리포트 생성
- 최신 사실 여부 판단
- Wiki 관계를 새로운 사실이나 인과관계로 확대
- Locate 후보 중 최종 Seed Page 선택

## 2. Connection과 비동기 계약

모든 내부 Navigator DB 함수는 호출자가 보유한
`AsyncConnection[dict[str, Any]]`을 첫 인자로 받는 `async def` 함수다.
Navigator가 별도 Pool이나 Connection을 만들지 않는다.

개인 Wiki RLS는 `SET LOCAL` 기반이므로 각 공개 Read 호출은 전달받은 Connection의
짧은 Transaction 안에서 `set_personal_wiki_scope()`를 적용한 뒤 조회한다. Reader
LLM이나 Embedding Provider 호출은 DB Transaction 밖에서 수행한다. Tool Loop가
`search → read → links`를 나누어 호출하면 각 호출마다 같은 Connection을 재사용하고
RLS Scope를 다시 설정한다.

## 3. Locate 계약

`index.md`는 현재 Build 반환 Artifact이므로 Navigator는 다음 DB 테이블에서 같은
의미의 Logical Index를 읽는다.

- `wiki_versions`, `wiki_version_documents`
- `wiki_documents`, `wiki_document_versions`
- `wiki_chunks`, `wiki_embeddings`

Report Builder용 후보 상한은 기본·최대 30개다. Consumer가 이 후보에서 Seed를
고르기 전에는 Page를 15개 이하로 다시 자르지 않는다.

초기 Locate 정렬은 제목·별칭 exact match, 제목·요약·본문 Keyword/Trigram,
Chunk FTS, Vector 순위를 결정적 RRF로 결합한다. Graph degree, 관심사 score,
이웃 수, organization 여부와 관계 중심성은 초기 후보 절단에 사용하지 않는다.
Degree는 Consumer가 Seed를 고른 뒤 동일 조건의 이웃 탐색 순서를 보조하는
Metadata로만 전달할 수 있다.

후보는 합산 점수뿐 아니라 exact·keyword·vector 순위 등 점수 구성과
`document_id`, `document_version_id`, 종류, 제목, 별칭, 요약, Vault 경로,
갱신 시각을 함께 반환한다.

## 4. Read와 Traverse 계약

Read는 Consumer가 선택한 `document_version_id`를 직접 읽는다. 현재 Head 제목을
다시 검색하지 않는다. Page의 summary, `normalized_content`, 관련 Chunk와 Version
시각을 반환한다.

Traverse 기본값은 1홉이며 최대 2홉, 최대 Page 6개, 최대 Chunk 12개다. Cycle과
중복 Page를 제거한다. 다음 조건을 만족하는 관계만 순회한다.

- 관계 `status = 'active'`
- 관계와 Support의 `review_status <> 'rejected'`
- active Support 존재
- 사용자 Namespace 일치
- provenance와 confidence 품질 Gate 통과

관계 방향, 유형, confidence, provenance, rationale와 active support evidence는
원래 의미를 보존한다. `associated_with`나 `related_concept`를 인과관계로 확대하지
않는다.

## 5. Source 시간 계약

Context Packet의 각 Source는 다음 시간을 포함한다.

- `saved_at`: `wiki_source_events.occurred_at` 우선, 없으면 원본 Version
  `created_at`
- `saved_at_source`: `event_occurred_at` 또는 `version_created_at`
- `stored_at`: `user_source_document_versions.created_at`
- `published_at`: 외부 Source 게시 시각
- `clipped_on`: 클리퍼가 전달한 저장 날짜

"최근에 관심을 보였는가"는 Wiki Build 시각이나 외부 게시 시각이 아니라
`saved_at`을 기준으로 판단한다.

## 6. Context Packet

Navigator는 다음 구조의 `WikiNavigationPacket`을 반환한다.

- Query와 고정 `wiki_version_id`
- Locate 후보 최대 30개
- 선택·순회 Page와 Page Version·Chunk 발췌
- Page 사이의 방향성 관계와 active Support
- 원본 Source와 저장·게시 시각
- Locate·Read·Traverse Trace, 적용 예산과 중단 사유
- 결과 절단 여부와 장애 폴백 정보

최상위에 `answer`, `report`, 최종 서술 필드를 두지 않는다. Vector Provider 장애는
Keyword Locate로, 관계 조회 장애는 선택 Page Read만으로, 빈 Wiki는 빈 Packet으로
폴백하며 Report Builder의 Global/Live 경로를 막지 않는다.

## 7. Report Builder 연결

Report Builder의 Reader가 Navigator Tool을 사용한다.

1. `wiki_search`로 후보 30개를 받는다.
2. Reader가 질문에 필요한 Seed Page를 선택한다.
3. `wiki_read`와 `wiki_links`로 Page·관계·Source를 읽는다.
4. Navigator가 Wiki Context Packet을 구성한다.
5. 기존 Global/Live Context와 결정적으로 병합한다.
6. Report Builder가 최종 리포트를 생성한다.

기존 `search_pool`은 개인 Wiki와 Global 저장 자료를 혼합하지 않도록 분리한다.
개인 Wiki 조회는 Navigator facade만 사용한다. 관심사 Bundle의 고정 Version은
Navigator Seed로 전달하고, 일반 주제도 같은 Packet 계약을 사용한다.

리포트 생성은 다음 탐색 프로필을 사용한다.

| 프로필 | 적용 경로 | Seed | 깊이별 Page 예산 | 전체 상한 |
|---|---|---:|---|---|
| `DEFAULT_1HOP` | 아침 브리핑·기존 Job | 기존 선택(최대 6, V2 자동 선택은 최대 3) | 1홉, 남은 전체 Page | 6 Page·12 Chunk |
| `ON_DEMAND_2HOP` | 사용자가 고른 단일 주제 온디맨드 | 최대 2 | 1홉 2 + 2홉 2, 앞 단계 미사용분 이월 | 6 Page·12 Chunk |

`ON_DEMAND_2HOP`이 관심사 Bundle Snapshot과 함께 쓰이면 루트 Wiki 문서만
Navigator Seed로 삼는다. Bundle의 1홉 이웃 문서는 Global·Live 검색 키워드로는
유지하지만 탐색 시작점으로 쓰지 않는다. 이웃에서 다시 2홉을 순회해 루트 기준
3홉이 되는 것을 막기 위한 경계다.

Page 후보가 깊이별 예산보다 많으면 관계 confidence를 경로마다 곱한 누적 신뢰도
내림차순으로 고르고 Page·relation ID로 동률을 결정한다. 저신뢰·rejected·support
없는 관계는 기존 Gate에서 제외한다.

## 8. 재시도와 관측

Report Job은 접수 시 활성 Wiki Build Version을 고정한다. 첫 Navigation에서 선택한
Page Version, 관계, Source Version과 탐색 예산은 Job Payload에 Topic별 Snapshot으로
저장한다. 같은 Job의 재시도는 Snapshot을 재사용한다.

Navigation Trace에는 Consumer, Job, Query Hash, Wiki Version, 후보·선택·순회 수,
Vector 폴백, 소요 시간과 중단 사유를 기록한다. 원문 전체나 Secret은 로그에 남기지
않는다.

완료 로그 `event=wiki_navigation_completed`와 Job `research_stats.navigation`에는
프로필, 고정 예산, 깊이별 Page·관계 수, 절단 여부, 폴백 사유와 최종 Wiki Context
문서 수를 남긴다. Topic별 Snapshot도 Page의 `hops`와 실제 예산을 저장해 재시도와
운영 비교가 같은 범위를 보게 한다.

관계 조회 장애로 Seed Page만 사용하는 경우에는
`event=wiki_navigation_relation_traversal_failed` 경고를 남긴다. 이 이벤트는 원문
Query 대신 Query Hash, Wiki Version, Seed 수, 탐색 예산과 오류 유형을 포함하므로
로그 수집기에서 폴백 발생 횟수와 사용자 영향 범위를 집계할 수 있어야 한다.

## 9. 검증

결정적 테스트는 Connection 재사용, RLS Scope, async 계약, 후보 30개, degree 비사용,
exact·alias·Keyword·Vector 결합, Vector 폴백, Version 고정, 1·2홉 Cycle 방지,
rejected/superseded 관계 제외, Source 시간 폴백, Context 예산과 Job 재시도 불변성을
검증한다.

Reader Prompt나 Tool Loop가 변경되면 `bench/wiki_navigation/`에 최소 10개 케이스를
구성하고 실행 전 예상 Token·비용을 고지한다. Seed Recall@30, 선택 Page Precision,
Path Precision, Source 시간 정확도, Citation 정확도, 지연과 Token 비용을 기록한다.

깊이 정책만 변경할 때는 무료 결정적 `bench/ondemand_navigation/`으로 같은 Graph의
1-hop·2-hop Page recall·precision·지연을 먼저 비교한다. 실제 리포트 문장·Citation
품질은 Provider 호출 비용을 고지하고 승인받은 뒤 별도로 측정한다.
