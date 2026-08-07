# 관심사 범주 묶음 리포트 설계

> 상태: **구현 승인 · 개발 중 (2026-08-07)**
>
> 목적: 활성 LLM Wiki 관심사 하나와 그 관심사에 직접 연결된 Wiki 노드를
> 하나의 검색 범주로 묶어, 특정 관심분야 리포트의 검색과 생성을 개인화한다.

## 1. 범위 정의

이 문서에서 **관심사 범주 묶음**은 Service taxonomy Category가 아니다.
현재 활성 관심 프로필의 관심사 하나를 루트로 삼고, 그 관심사의 근거 Wiki
문서에서 1홉으로 연결된 Entity·Concept 노드를 관련 관점으로 묶은 것이다.

```text
코스피 (활성 관심사)
├─ 코스닥시장 (entity_relation)
└─ 서킷 브레이커 (applies_concept)
```

온보딩의 `selected_category_ids`·`selected_topic_ids`는 사용자가 처음 선언한
taxonomy 선택이고, 이 기능이 받는 `interest_id`는 Wiki Build 후 INT-011이 만든
현재 활성 `user_interests.id`다. 둘은 같은 ID 공간이 아니다.

## 2. 요청 계약

기존 단일 키워드 요청은 그대로 유지한다. 관심분야 리포트는
`generation_scope=INTEREST_BUNDLE`과 현재 활성 `interest_id`를 보낸다.

```json
{
  "idempotency_key": "interest-bundle:2026-08-07:user-1:interest-1",
  "generation_scope": "INTEREST_BUNDLE",
  "interest_id": "현재 활성 관심사 UUID",
  "content_type": "interest_news_card",
  "report_type": "ON_DEMAND"
}
```

- `SINGLE_TOPIC`은 기존 `topic`을 필수로 사용한다.
- `INTEREST_BUNDLE`은 `interest_id`를 필수로 사용하고 `topics`를 받지 않는다.
- `topics`는 서로 독립된 여러 주제를 한 장에 담는 기존 경로로 남긴다. 연결
  노드를 `topics`로 전달해 독립 섹션으로 만들지 않는다.
- Agent는 요청 접수 시 활성 프로필·사용자 소속·차단 여부를 검증한다.
- 비활성·퇴역 프로필의 `interest_id`는 접수하지 않는다.

## 3. 묶음 구성 정책 (INT-012)

루트 Wiki 노드는 관심사 제목 문자열이 아니라 `interest_evidence.document_id`로
찾는다. 제목 변경과 동의어 표기에도 같은 근거 노드를 안정적으로 가리키기 위해서다.

연결 노드 선정 규칙:

1. 개인 Namespace의 활성 Entity·Concept만 사용한다.
2. 삭제된 노드와 `organization` domain은 제외한다.
3. 관계는 양방향 1홉만 따른다.
4. 관계 가중치 내림차순으로 정렬하고 최대 2개를 사용한다.
5. 관계 가중치가 같으면 공동 출현 원문 수, 이웃 degree, 제목 순으로 정렬한다.
6. 이웃이 없으면 루트 관심사 하나만으로 정상 생성한다.

접수 시 확정한 묶음은 Profile Version과 함께 Job Payload에 스냅샷으로 저장한다.
Worker가 실행될 때 프로필이 바뀌어도 재시도 결과가 달라지지 않게 한다.

## 4. 검색·생성 정책

개인 Wiki와 Global 풀은 루트와 연결 키워드 각각으로 검색한다. 결과는 URL 또는
실제 문서 ID로 중복 제거하고, 병합 후 Citation 참조 번호를 다시 부여한다.

- 루트 키워드 근거를 우선한다.
- 연결 키워드 결과는 루트 관심사 관련성 검사를 통과해야 한다.
- 생성 Context 전체 상한은 기존 12건을 유지한다.
- 저장 자료가 부족할 때만 루트+연결 키워드로 실시간 수집을 한 번 수행한다.
- Researcher가 켜져 있어도 확정된 연결 키워드를 반드시 먼저 검색한다.
- 생성 프롬프트는 루트를 핵심 관심사, 연결 노드를 보조 관점으로 설명한다.
  연결 노드를 서로 독립된 관심사 섹션으로 취급하지 않는다.

## 5. 발행 메타데이터

기존 `tags` 의미는 바꾸지 않고 루트 관심사 문자열 하나를 유지한다. 다음 필드를
추가해 Service가 생성 근거를 추적할 수 있게 한다.

```json
{
  "generation_scope": "INTEREST_BUNDLE",
  "source_interest_id": "관심사 UUID",
  "interest_profile_id": "프로필 UUID",
  "bundle_keywords": ["코스피", "코스닥시장", "서킷 브레이커"]
}
```

## 6. 실패와 비용 경계

- 활성 관심사가 아니면 `ACTIVE_INTEREST_REQUIRED`로 접수를 거절한다.
- 이웃 조회 실패·이웃 없음은 루트 단일 검색으로 폴백한다.
- Wiki 연결 키워드는 기본 2개로 제한하고 기존 검색 확장 스위치로 비활성화할 수
  있게 한다.
- 실시간 수집을 키워드별로 따로 호출하지 않는다. 하나의 호출에 보조 검색어로
  전달해 Worker Lease와 외부 API 비용을 통제한다.

## 7. 검증

일반 테스트는 LLM 호출 없이 다음을 검증한다.

- 활성 Profile·사용자 소속·차단 관심사 검증
- 근거 문서 ID 기반 1홉 조회와 organization 제외
- 결정적 정렬·상한·고립 노드 폴백
- Job Payload 스냅샷과 Worker 전달
- Researcher 활성·비활성 양쪽의 동일한 묶음 검색
- 다중 검색 결과의 문서 중복 제거와 Citation 참조 재부여
- 발행 Snapshot의 범주 메타데이터

실제 LLM 벤치마크는 `bench/interest_bundle_report/`에 최소 10개 케이스를 두고,
비용을 먼저 고지한 뒤 실행한다. 범주 커버리지·루트 집중도·Citation 정확성·지연·
토큰 비용을 기록한다.
