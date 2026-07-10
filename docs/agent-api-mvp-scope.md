# Agent API MVP 개발 범위

> 이 문서는 전체 기능 명세의 고유 ID를 그대로 사용하며, MVP에서 구현할 항목만 선별한 범위 문서입니다.

## MVP 목표

- 사용자가 선택한 데이터로 개인 LLM Wiki를 구성한다.
- 개인 Wiki 데이터를 기반으로 사용자 관심사를 분류한다.
- Naver API, NewsAPI, GDELT 데이터를 정기적으로 수집한다.
- 개인 Wiki와 최신 수집 데이터를 결합해 밤비 콘텐츠를 생성한다.
- 생성 결과를 service-api 및 service-worker가 사용할 수 있도록 제공한다.

## 1. Service API 연동

| ID | 기능 | 설명 |
|---|---|---|
| SVC-001 | 사용자 컨텍스트 전달 | 서비스 사용자 설정을 Agent 컨텍스트로 전달한다. |
| SVC-002 | 웹 클리핑 처리 요청 | 클리핑 데이터를 개인 Wiki 처리 작업으로 전달한다. |
| SVC-003 | URL 처리 요청 | 입력된 URL을 개인 Wiki 처리 작업으로 전달한다. |
| SVC-004 | 위키마킹 처리 요청 | 사용자가 선택한 콘텐츠의 Wiki 편입을 요청한다. |
| SVC-008 | 콘텐츠 생성 요청 | 밤비의 콘텐츠 생성을 요청한다. |
| SVC-013 | Agent Job 상태 조회 | 비동기 작업 상태를 조회한다. |
| SVC-014 | Agent 결과 조회 | 생성 및 처리 결과를 Agent API에서 조회한다. |

## 2. 사용자 개인 LLM Wiki

| ID | 기능 | 설명 |
|---|---|---|
| PWIKI-002 | 개인 Wiki 문서 생성 | 사용자가 선택한 데이터를 Wiki 문서로 변환한다. |
| PWIKI-003 | 개인 Wiki 문서 조회 | 사용자의 Wiki 문서 목록과 상세 내용을 조회한다. |
| PWIKI-005 | 개인 Wiki 문서 삭제 | 사용자가 제거한 데이터를 Wiki 검색 대상에서 제외한다. |
| PWIKI-008 | Wiki 문서 중복 제거 | 동일하거나 유사한 개인 Wiki 문서를 중복 제거한다. |
| PWE-001 | 개인 Wiki 문서 Chunking | Wiki 문서를 의미 단위 Chunk로 분할한다. |
| PWE-004 | Embedding 생성 | 개인 Wiki Chunk의 Vector를 생성한다. |
| PWE-005 | Embedding 저장 | 사용자별 Vector 검색 저장소에 Embedding을 저장한다. |
| PRAG-003 | Hybrid Search | Keyword와 Vector 검색 결과를 결합한다. |
| PRAG-006 | 개인 Wiki Context 구성 | LLM 입력에 사용할 개인 Wiki Context를 구성한다. |
| PRAG-007 | Citation 연결 | 생성 결과와 참조한 개인 Wiki 문서를 연결한다. |

## 3. DB 기반 관심사 분류

| ID | 기능 | 설명 |
|---|---|---|
| INT-001 | 관심사 Topic 추출 | 개인 Wiki와 사용자 행동에서 관심 주제를 추출한다. |
| INT-002 | 관심사 Category 분류 | 관심사를 서비스의 분류 체계에 매핑한다. |
| INT-005 | 관심사 점수 계산 | 사용자 행동 강도와 최신성을 기반으로 점수를 계산한다. |
| INT-011 | 관심사 프로필 재계산 | Wiki 변경 시 관심사 구조와 점수를 다시 계산한다. |

## 4. 외부 데이터 자동 수집

| ID | 기능 | 설명 |
|---|---|---|
| COL-002 | Naver API 수집 | 설정된 키워드로 Naver API 데이터를 수집한다. |
| COL-003 | GDELT 수집 | 글로벌 뉴스와 이벤트 데이터를 수집한다. |
| COL-004 | NewsAPI 수집 | 뉴스 기사와 관련 메타데이터를 수집한다. |
| GSP-004 | API 응답 정규화 | Source별 응답을 공통 문서 구조로 변환한다. |
| GSP-006 | 문서 중복 제거 | 동일 URL과 유사 문서를 중복 제거한다. |
| GSP-015 | 개인 Wiki 자동 반영 금지 | 수집 데이터를 사용자 선택 없이 개인 Wiki에 반영하지 않는다. |
| SCH-002 | Naver API 수집 스케줄 | Naver API 수집 작업을 정기 등록한다. |
| SCH-003 | GDELT 수집 스케줄 | GDELT 수집 작업을 정기 등록한다. |
| SCH-004 | NewsAPI 수집 스케줄 | NewsAPI 수집 작업을 정기 등록한다. |

## 5. 콘텐츠 생성 에이전트 밤비

| ID | 기능 | 설명 |
|---|---|---|
| BAMBI-001 | 콘텐츠 생성 요청 | 사용자와 주제에 맞는 콘텐츠 생성 요청을 처리한다. |
| BAMBI-004 | 개인 Wiki 검색 | 사용자의 관심사와 기존 지식을 검색한다. |
| BAMBI-005 | Global Source 검색 | 최신 외부 자료와 근거를 검색한다. |
| BAMBI-008 | 콘텐츠 요약 생성 | 피드와 미리보기에 사용할 요약을 생성한다. |
| BAMBI-009 | 콘텐츠 본문 생성 | 플랜과 유형에 맞는 본문을 생성한다. |
| BAMBI-011 | 콘텐츠 Citation 생성 | 본문 주장과 참조한 자료를 연결한다. |
| BAMBI-012 | 사용자 개인화 적용 | 관심사, 언어, 비선호 설정을 반영한다. |
| BAMBI-018 | 생성 콘텐츠 후보 저장 | 발행 전 콘텐츠를 agent-db에 저장한다. |
| BAMBI-020 | 콘텐츠 완료 이벤트 | 생성 완료 사실을 Integration Event로 발행한다. |
| BAMBI-021 | 자동 Wiki 편입 금지 | 생성된 콘텐츠를 사용자 선택 없이 개인 Wiki에 넣지 않는다. |

## 6. Worker 및 서비스 반영

| ID | 기능 | 설명 |
|---|---|---|
| WORKER-001 | Global Source Collector Worker | 외부 데이터를 수집하고 Global Source Pool에 저장한다. |
| WORKER-002 | Personal Wiki Builder Worker | 사용자 선택 데이터를 개인 Wiki로 구성한다. |
| WORKER-003 | Bambi Generation Worker | 개인화 콘텐츠를 생성한다. |
| SW-001 | Content Ready 이벤트 수신 | 발행 가능한 콘텐츠 이벤트를 소비한다. |
| SW-004 | Publish Snapshot 조회 | Agent API에서 서비스 저장용 콘텐츠를 조회한다. |
| SW-007 | service-db 콘텐츠 Upsert | 콘텐츠 발행본을 service-db에 저장하거나 갱신한다. |
| SW-009 | 발행 완료 ACK | service-db 반영 완료를 Agent API에 알린다. |

## MVP 제외 범위

- 내부 서버 인증 및 세부 권한
- 자체 API Key와 External Agent API
- MCP Server
- 번역 및 이미지 생성
- 별도의 추천 Agent
- 고급 관심사 Graph
- Personal Wiki 전체 재구성 및 Memory 압축
- 다중 평가 Agent와 고급 사실 검증
- Prompt 및 추천 A/B Test
- 고급 메시징 패턴과 자동 확장

## ID 관리 원칙

- 기능 ID는 전체 기능 명세에서만 생성한다.
- MVP 문서는 전체 기능 ID 중 구현 대상을 선별해 참조한다.
- MVP 이후 기능을 구현할 때도 기존 기능 ID를 그대로 사용한다.
- 여러 기능을 개발 작업으로 묶을 때만 별도의 Epic 또는 Milestone ID를 사용한다.