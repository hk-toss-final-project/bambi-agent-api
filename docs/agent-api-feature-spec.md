# Agent API 기능 명세 목록

> 상세 필드명, API Request/Response Schema, 데이터 플로우를 제외하고 기능 목록만 정리한 문서입니다.

## 1. FastAPI 진입점

| ID | 기능 | 설명 |
|---|---|---|
| SYS-001 | 애플리케이션 초기화 | Agent API 실행에 필요한 설정과 컴포넌트를 초기화한다. |
| SYS-002 | API 라우터 등록 | 내부 API, 외부 API, 관리자 API 라우터를 등록한다. |
| SYS-003 | 환경 설정 로딩 | 환경별 설정과 Secret 참조 정보를 로딩한다. |
| SYS-004 | DB 연결 관리 | Agent DB와 Vector 저장소 연결을 관리한다. |
| SYS-005 | Queue 연결 관리 | Job Queue와 Event Bus 연결을 관리한다. |
| SYS-006 | 외부 Provider 연결 관리 | LLM, Embedding, 이미지 Provider 연결을 관리한다. |
| SYS-007 | 공통 예외 처리 | API 전역의 오류 응답 형식을 통일한다. |
| SYS-008 | 요청 추적 | Request ID와 Trace ID를 생성하고 전달한다. |
| SYS-009 | Liveness Check | Agent API 프로세스 생존 여부를 확인한다. |
| SYS-010 | Readiness Check | DB, Queue, Provider의 요청 처리 가능 상태를 확인한다. |
| SYS-011 | Version 조회 | API와 주요 설정 버전을 반환한다. |
| SYS-012 | Graceful Shutdown | 진행 중 요청을 정리하고 안전하게 종료한다. |

## 2. 내부 API 인증

| ID | 기능 | 설명 |
|---|---|---|
| AUTH-001 | Service API 인증 | service-api의 내부 호출 권한을 검증한다. |
| AUTH-002 | Service Worker 인증 | service-worker의 내부 호출 권한을 검증한다. |
| AUTH-003 | Scheduler 인증 | scheduler의 작업 등록 권한을 검증한다. |
| AUTH-004 | 호출 주체 식별 | service-api, service-worker, scheduler 등 호출 주체를 구분한다. |
| AUTH-005 | Scope 기반 권한 검증 | 호출 주체별 허용 기능 범위를 검증한다. |
| AUTH-006 | 내부 요청 서명 검증 | 내부 요청의 위변조와 재전송을 방지한다. |
| AUTH-007 | 내부 Rate Limit | 내부 호출 주체별 요청량을 제한한다. |
| AUTH-008 | 관리자 Audit Context | 관리자 ID, 변경 사유, Trace 정보를 전달받는다. |

## 3. 사용자 컨텍스트 관리

| ID | 기능 | 설명 |
|---|---|---|
| CTX-001 | 사용자 컨텍스트 등록 | AI 처리에 필요한 최소 사용자 컨텍스트를 등록한다. |
| CTX-002 | 사용자 컨텍스트 갱신 | 관심사, 플랜, 언어 설정 등의 변경을 반영한다. |
| CTX-003 | 사용자 컨텍스트 조회 | Agent 작업에서 사용할 사용자 컨텍스트를 조회한다. |
| CTX-004 | 사용자 컨텍스트 삭제 | 탈퇴 또는 삭제 요청 시 컨텍스트를 제거한다. |
| CTX-005 | 컨텍스트 버전 관리 | 오래된 컨텍스트가 최신 데이터를 덮어쓰지 않도록 관리한다. |
| CTX-006 | 플랜 정보 반영 | 무료·유료 플랜에 따른 Agent 정책을 연결한다. |
| CTX-007 | 선호 언어 반영 | 사용자의 콘텐츠 생성 및 번역 언어를 반영한다. |
| CTX-008 | 개인화 설정 반영 | 개인화 기능 사용 여부를 적용한다. |
| CTX-009 | 차단 관심사 반영 | 사용자가 차단한 관심사를 검색과 생성에서 제외한다. |
| CTX-010 | 차단 출처 반영 | 사용자가 차단한 Source를 추천과 생성에서 제외한다. |
| CTX-011 | 개인정보 최소화 | Agent에 불필요한 개인정보가 저장되지 않도록 제한한다. |

## 4. 사용자 Wiki Source Event

| ID | 기능 | 설명 |
|---|---|---|
| WSE-001 | 웹 클리핑 이벤트 수신 | 사용자가 클리핑한 데이터를 개인 Wiki 반영 후보로 수신한다. |
| WSE-002 | URL 입력 이벤트 수신 | 사용자가 직접 입력한 URL을 개인 Wiki 반영 후보로 수신한다. |
| WSE-003 | 콘텐츠 위키마킹 이벤트 수신 | 선택한 생성 콘텐츠를 개인 Wiki 반영 후보로 수신한다. |
| WSE-004 | 콘텐츠 저장 이벤트 수신 | 사용자가 저장한 콘텐츠를 정책에 따라 처리한다. |
| WSE-005 | 사용자 메모 이벤트 수신 | 문서나 콘텐츠에 작성한 메모를 수신한다. |
| WSE-006 | 생성 콘텐츠 수정 이벤트 수신 | 사용자가 수정한 생성 콘텐츠를 수신한다. |
| WSE-007 | 콘텐츠 대화 이벤트 수신 | 콘텐츠와의 의미 있는 대화 결과를 수신한다. |
| WSE-008 | 사용자 피드백 이벤트 수신 | 좋아요, 숨김, 신고 등 사용자 반응을 수신한다. |
| WSE-009 | Wiki Source 삭제 이벤트 수신 | 사용자가 제거한 Wiki 원천을 반영한다. |
| WSE-010 | Wiki 재구성 요청 수신 | 사용자의 개인 Wiki 재구성 요청을 수신한다. |
| WSE-011 | 이벤트 중복 처리 방지 | 동일 사용자 이벤트의 중복 처리를 방지한다. |
| WSE-012 | Wiki 편입 정책 판단 | 사용자 행동을 Wiki 문서 또는 관심사 신호로 분류한다. |
| WSE-013 | 이벤트 처리 상태 관리 | 수신, 처리 중, 완료, 실패 상태를 관리한다. |
| WSE-014 | 온보딩 관심사 시드 수신 | 회원가입 온보딩에서 고른 Category·Topic을 시드 문서로 합성해 개인 Wiki 반영 후보로 수신한다. |

## 5. User Personal LLM Wiki

| ID | 기능 | 설명 |
|---|---|---|
| PWIKI-001 | 개인 Wiki 생성 | 사용자별 개인 LLM Wiki 영역을 생성한다. |
| PWIKI-002 | 개인 Wiki 문서 생성 | 사용자가 선택한 데이터를 Entity·Concept·Schema Wiki 문서로 변환한다. |
| PWIKI-003 | 개인 Wiki 문서 조회 | 사용자의 Wiki 문서 목록·상세 내용과 Entity·Concept 관계 Graph를 조회한다. |
| PWIKI-004 | 개인 Wiki 문서 수정 | 사용자 메모와 수정 내용을 Wiki 문서에 반영한다. |
| PWIKI-005 | 개인 Wiki 문서 삭제 | 사용자가 제거한 데이터를 Wiki 검색 대상에서 제외한다. |
| PWIKI-006 | 개인 Wiki 문서 버전 관리 | 각 Markdown 문서 변경 이력과 Wiki Build별 문서 Version·파일 경로 구성을 관리한다. |
| PWIKI-007 | Wiki 문서 출처 추적 | 클리핑·URL 원본 출처와 Entity·Concept 문서 간 관계를 기록한다. |
| PWIKI-008 | Wiki 문서 중복 제거 | 동일하거나 유사한 개인 Wiki 문서를 중복 제거한다. |
| PWIKI-009 | Wiki 문서 병합 | 유사한 사용자 지식을 하나의 문서나 주제로 병합한다. |
| PWIKI-010 | Wiki 문서 요약 | 긴 문서를 개인 Wiki용 요약 문서로 구성한다. |
| PWIKI-011 | Wiki 문서 정규화 | 문서 형식과 메타 정보를 공통 구조로 변환한다. |
| PWIKI-012 | 개인 Wiki 사용자 격리 | 다른 사용자의 개인 Wiki에 접근하지 못하도록 격리한다. |
| PWIKI-013 | 개인 Wiki 초기화 | 사용자 원본·Version을 영구 삭제하고 Source Event의 개인정보를 비식별화하며 개인 LLM Wiki 파생 데이터와 진행 중인 Build를 계정 단위로 초기화한다. |

## 6. 개인 Wiki Chunk 및 Embedding

| ID | 기능 | 설명 |
|---|---|---|
| PWE-001 | 개인 Wiki 문서 Chunking | Wiki 문서를 의미 단위 Chunk로 분할한다. |
| PWE-002 | Chunk 저장 | 생성된 Chunk를 문서 버전과 연결해 저장한다. |
| PWE-003 | Chunk Metadata 관리 | 관심사, 출처, 문서 버전 등의 정보를 관리한다. |
| PWE-004 | Embedding 생성 | 개인 Wiki Chunk의 Vector를 생성한다. |
| PWE-005 | Embedding 저장 | 사용자별 Vector 검색 저장소에 Embedding을 저장한다. |
| PWE-006 | Embedding 갱신 | 문서 변경 시 관련 Embedding을 갱신한다. |
| PWE-007 | Embedding 재생성 | 모델 또는 Chunk 정책 변경 시 재생성한다. |
| PWE-008 | Vector Namespace 분리 | 사용자별 Vector 검색 범위를 분리한다. |
| PWE-009 | 불필요 Chunk 제거 | 광고, 메뉴, 반복 문구 등 검색에 불필요한 Chunk를 제거한다. |
| PWE-010 | 삭제 Vector 반영 | 문서 삭제 시 관련 Vector도 검색 대상에서 제거한다. |

## 7. 개인 Wiki 검색 및 RAG

| ID | 기능 | 설명 |
|---|---|---|
| PRAG-001 | Keyword Search | 개인 Wiki에서 키워드 기반 검색을 수행한다. |
| PRAG-002 | Vector Search | 개인 Wiki에서 의미 유사도 검색을 수행한다. |
| PRAG-003 | Hybrid Search | Keyword와 Vector 검색 결과를 결합한다. |
| PRAG-004 | 검색 결과 Reranking | 사용자 관심사와 요청 목적을 기준으로 결과를 재정렬한다. |
| PRAG-005 | 사용자 관심사 기반 검색 | 관심사 프로필을 검색 조건에 반영한다. |
| PRAG-006 | 개인 Wiki Context 구성 | LLM 입력에 사용할 개인 Wiki Context를 구성한다. |
| PRAG-007 | Citation 연결 | 생성 결과와 참조한 개인 Wiki 문서를 연결한다. |
| PRAG-008 | 검색 로그 저장 | 검색 Query, 결과, 점수와 사용 Agent를 기록한다. |
| PRAG-009 | 검색 품질 평가 | 개인 Wiki 검색 결과의 적합성을 평가한다. |

## 8. 사용자 관심사 분류

| ID | 기능 | 설명 |
|---|---|---|
| INT-001 | 관심사 Topic 추출 | 개인 Wiki와 사용자 행동에서 관심 주제를 추출한다. |
| INT-002 | 관심사 Category 분류 | 관심사를 서비스의 분류 체계에 매핑한다. |
| INT-003 | 관심사 계층 구성 | 상위 관심사와 세부 관심사 구조를 구성한다. |
| INT-004 | 관심사 간 관계 구성 | 서로 관련된 관심사 간 연결 관계를 생성한다. |
| INT-005 | 관심사 점수 계산 | 사용자 행동 강도와 최신성을 기반으로 점수를 계산한다. |
| INT-006 | 관심사 Confidence 계산 | 추론된 관심사의 신뢰도를 계산한다. |
| INT-007 | 관심사 근거 추적 | 관심사를 만든 Wiki 문서와 사용자 행동을 연결한다. |
| INT-008 | 관심사 시간 감쇠 | 오래된 관심사의 가중치를 점진적으로 낮춘다. |
| INT-009 | 비선호 관심사 반영 | 숨김, 차단, 신고 등의 부정 신호를 반영한다. |
| INT-010 | 관심사 프로필 버전 관리 | 관심사 프로필의 변경 이력을 관리한다. |
| INT-011 | 관심사 프로필 재계산 | Wiki 변경 시 관심사 구조와 점수를 다시 계산한다. |
| INT-012 | 관심사 범주 묶음 구성 | 활성 관심사와 근거 Wiki 문서의 1홉 연결 노드를 리포트 검색 범주로 구성한다. |

## 9. Personal Wiki Builder Agent

| ID | 기능 | 설명 |
|---|---|---|
| WBA-001 | Incremental Wiki Build | 새로 추가된 사용자 데이터만 개인 Wiki에 반영한다. |
| WBA-002 | Full Wiki Rebuild | 전체 개인 Wiki를 재분류하고 재구성한다. |
| WBA-003 | Wiki 문서 정규화 | 입력 데이터를 개인 Wiki 문서 구조로 정리한다. |
| WBA-004 | Wiki 문서 중복 제거 | 동일하거나 유사한 사용자 지식을 제거한다. |
| WBA-005 | Wiki 문서 병합 | 관련 문서와 메모를 하나의 지식으로 통합한다. |
| WBA-006 | Wiki 관심사 분류 | 개인 Wiki 문서를 관심사별로 분류한다. |
| WBA-007 | Wiki 관심사 구조 재구성 | 관심사 계층과 관계를 다시 구성한다. |
| WBA-008 | Wiki Summary 생성 | 관심사 그룹별 개인 Wiki 요약을 생성한다. |
| WBA-009 | Interaction Memory 생성 | 사용자와 콘텐츠의 의미 있는 대화를 지식으로 정리한다. |
| WBA-010 | 오래된 Memory 압축 | 누적된 상호작용 Memory를 압축하고 병합한다. |
| WBA-011 | Wiki 재임베딩 | 변경된 문서와 구조의 Embedding을 갱신한다. |
| WBA-012 | Wiki 버전 생성 | 재구성된 Wiki 상태를 새 버전으로 저장한다. |
| WBA-013 | Wiki 변경점 생성 | 이전 버전과 변경된 내용을 기록한다. |
| WBA-014 | Wiki 품질 검증 | 중복, 누락, 잘못된 분류 여부를 확인한다. |
| WBA-015 | Wiki 삭제 반영 | 삭제된 사용자 원천과 파생 데이터를 제거한다. |
| WBA-016 | Wiki Build 완료 이벤트 | 개인 Wiki 갱신 완료 사실을 이벤트로 발행한다. |
| WBA-017 | 외부 데이터 자동 편입 차단 | 자동 수집 자료가 사용자 선택 없이 개인 Wiki에 들어가지 않도록 한다. |
| WBA-018 | Claude 작성 Wiki 항목 저장 | MCP로 받은 Claude 분류 결과를 기존 Build 파이프라인으로 검증·저장한다. |

## 10. Global Source 관리

| ID | 기능 | 설명 |
|---|---|---|
| GS-001 | Global Source 등록 | 외부 수집 Source를 등록한다. |
| GS-002 | Global Source 조회 | 등록된 Source와 설정을 조회한다. |
| GS-003 | Global Source 수정 | Source의 수집 설정을 변경한다. |
| GS-004 | Global Source 삭제 | 사용하지 않는 Source를 제거한다. |
| GS-005 | Global Source 활성화 | Source 수집을 활성화한다. |
| GS-006 | Global Source 비활성화 | Source 수집을 일시 중지한다. |
| GS-007 | 수집 주기 설정 | Source별 수집 실행 주기를 설정한다. |
| GS-008 | 수집 키워드 설정 | 검색 API와 Source별 수집 키워드를 설정한다. |
| GS-009 | 수집 언어 설정 | 수집할 콘텐츠 언어를 설정한다. |
| GS-010 | 수집 카테고리 설정 | 수집할 주제와 카테고리를 설정한다. |
| GS-011 | 외부 API 인증정보 연결 | Source 호출에 필요한 Secret을 연결한다. |
| GS-012 | Source 사용량 제한 관리 | 외부 API별 호출량과 Quota를 관리한다. |

## 11. Global Source Collector

| ID | 기능 | 설명 |
|---|---|---|
| COL-001 | RSS 수집 | 등록된 RSS Feed에서 신규 콘텐츠를 수집한다. |
| COL-002 | Naver API 수집 | 설정된 키워드로 Naver API 데이터를 수집한다. |
| COL-003 | GDELT 수집 | 글로벌 뉴스와 이벤트 데이터를 수집한다. |
| COL-004 | NewsAPI 수집 | 뉴스 기사와 관련 메타데이터를 수집한다. |
| COL-005 | SNS 수집 | 허용된 SNS 공개 데이터를 수집한다. |
| COL-006 | 블로그 수집 | 블로그와 공개 게시글 데이터를 수집한다. |
| COL-007 | DART 수집 | 기업 공시 데이터를 수집한다. |
| COL-008 | KRX 수집 | 시장 및 종목 관련 데이터를 수집한다. |
| COL-009 | GitHub 수집 | Repository, Release, Issue, README 등을 수집한다. |
| COL-010 | arXiv 수집 | 논문 메타데이터, 초록, 본문을 수집한다. |
| COL-011 | 직접 URL 수집 | 관리자가 지정한 URL의 데이터를 수집한다. |
| COL-012 | 사용자 정의 Source 수집 | 추가된 외부 API와 Source Connector를 실행한다. |

## 12. Global Source 정제 및 저장

| ID | 기능 | 설명 |
|---|---|---|
| GSP-001 | Raw 데이터 저장 | 외부 Source에서 받은 원본 데이터를 저장한다. |
| GSP-002 | HTML 본문 추출 | HTML 페이지에서 주요 본문을 추출한다. |
| GSP-003 | PDF 본문 추출 | PDF 문서에서 텍스트와 구조를 추출한다. |
| GSP-004 | API 응답 정규화 | Source별 응답을 공통 문서 구조로 변환한다. |
| GSP-005 | 문서 언어 감지 | 수집된 문서의 언어를 판별한다. |
| GSP-006 | 문서 중복 제거 | 동일 URL과 유사 문서를 중복 제거한다. |
| GSP-007 | 문서 품질 필터링 | 스팸, 빈 문서, 깨진 콘텐츠를 제외한다. |
| GSP-008 | 문서 버전 관리 | 외부 문서 변경 이력을 관리한다. |
| GSP-009 | Global 문서 Chunking | Global Source 문서를 검색 가능한 Chunk로 분할한다. |
| GSP-010 | Global 문서 Embedding | Global Source 검색용 Vector를 생성한다. |
| GSP-011 | Global Vector Index 관리 | Global Source 전용 Vector Index를 관리한다. |
| GSP-012 | Source 신뢰도 관리 | Source별 품질과 신뢰도 정보를 관리한다. |
| GSP-013 | 수집 이력 관리 | 수집 실행 결과와 신규·중복·실패 건수를 기록한다. |
| GSP-014 | 오래된 데이터 보존 정책 | 수집 데이터의 보존과 만료 정책을 적용한다. |
| GSP-015 | 개인 Wiki 자동 반영 금지 | 수집 데이터를 사용자 선택 없이 개인 Wiki에 반영하지 않는다. |

## 13. Global Discovery 및 Trend

| ID | 기능 | 설명 |
|---|---|---|
| DISC-001 | 신규 자료 탐지 | 이전 수집 이후 새롭게 추가된 자료를 탐지한다. |
| DISC-002 | 트렌드 Topic 탐지 | 수집 데이터에서 새롭게 부상하는 주제를 탐지한다. |
| DISC-003 | 유사 문서 클러스터링 | 같은 사건이나 주제를 다루는 문서를 그룹화한다. |
| DISC-004 | 뉴스 이벤트 클러스터링 | 관련 뉴스들을 하나의 이벤트 단위로 구성한다. |
| DISC-005 | 최신성 점수 계산 | 문서와 이벤트의 최신성 점수를 계산한다. |
| DISC-006 | 중요도 점수 계산 | 확산도와 관련성을 기반으로 중요도를 계산한다. |
| DISC-007 | 출처 다양성 평가 | 여러 Source가 동일 사실을 다루는지 평가한다. |
| DISC-008 | 사용자 관심사 매칭 | Global Source와 개인 관심사를 매칭한다. |
| DISC-009 | 콘텐츠 생성 후보 생성 | 리포트 생성기가 사용할 최신 자료 후보를 생성한다. |
| DISC-010 | 추천 후보 생성 | 사용자에게 추천할 외부 콘텐츠 후보를 생성한다. |
| DISC-011 | 중복 후보 제거 | 이미 처리했거나 유사한 후보를 제거한다. |
| DISC-012 | 트렌드 후보 저장 | 탐지된 트렌드와 관련 문서를 저장한다. |

## 14. LLM 공통 기능

| ID | 기능 | 설명 |
|---|---|---|
| LLM-001 | Text Completion | 일반 텍스트 생성 요청을 처리한다. |
| LLM-002 | Chat Completion | 대화형 생성 요청을 처리한다. |
| LLM-003 | Structured Output | 정해진 Schema 형식으로 결과를 생성한다. |
| LLM-004 | Tool Calling | Wiki 검색과 외부 도구 호출을 수행한다. |
| LLM-005 | Function Calling | 정의된 내부 함수를 호출하고 결과를 활용한다. |
| LLM-006 | 모델 라우팅 | 작업 성격과 플랜에 맞는 모델을 선택한다. |
| LLM-007 | Provider 라우팅 | 사용 가능한 LLM Provider를 선택한다. |
| LLM-008 | Fallback 모델 | 주 모델 실패 시 대체 모델을 사용한다. |
| LLM-009 | Token Budget 관리 | 작업과 플랜별 Token 사용량을 제한한다. |
| LLM-010 | Context Builder | 개인 Wiki와 Global Source Context를 구성한다. |
| LLM-011 | Citation Builder | 생성 결과와 사용한 출처를 연결한다. |
| LLM-012 | 응답 캐싱 | 재사용 가능한 LLM 결과를 캐시한다. |
| LLM-013 | 호출 Retry | 일시적인 Provider 오류를 재시도한다. |
| LLM-014 | 호출 Timeout | LLM 요청의 최대 실행 시간을 제한한다. |
| LLM-015 | 사용량 기록 | 모델 호출량과 Token 사용량을 기록한다. |
| LLM-016 | 비용 기록 | Provider와 작업별 예상 비용을 기록한다. |
| LLM-017 | 안전성 검사 | 입력과 출력의 정책 위반 여부를 확인한다. |
| LLM-018 | Prompt Injection 방어 | 외부 문서의 명령을 시스템 지시와 분리한다. |
| LLM-019 | Provider 추상화 | Provider 교체가 가능하도록 공통 인터페이스를 제공한다. |

## 15. Prompt 관리

| ID | 기능 | 설명 |
|---|---|---|
| PROMPT-001 | Prompt Template 생성 | Agent 기능별 Prompt Template을 생성한다. |
| PROMPT-002 | Prompt Template 조회 | 등록된 Prompt Template을 조회한다. |
| PROMPT-003 | Prompt Template 수정 | Prompt 내용을 새 버전으로 수정한다. |
| PROMPT-004 | Prompt Template 삭제 | 사용하지 않는 Prompt Template을 비활성화한다. |
| PROMPT-005 | Prompt Version 생성 | 변경된 Prompt를 독립된 버전으로 저장한다. |
| PROMPT-006 | Prompt Version 조회 | Prompt의 전체 버전 이력을 조회한다. |
| PROMPT-007 | 활성 Prompt 전환 | 운영에 사용할 Prompt 버전을 선택한다. |
| PROMPT-008 | Prompt 테스트 | 샘플 입력으로 Prompt 결과를 테스트한다. |
| PROMPT-009 | Prompt 롤백 | 이전 Prompt 버전으로 되돌린다. |
| PROMPT-010 | Prompt 변경 이력 | 변경자와 변경 사유를 기록한다. |
| PROMPT-011 | Prompt A/B Test | 여러 Prompt의 품질과 비용을 비교한다. |

## 16. Model Config 관리

| ID | 기능 | 설명 |
|---|---|---|
| MODEL-001 | Model Config 생성 | 모델 실행 설정을 생성한다. |
| MODEL-002 | Model Config 조회 | 작업별 모델 설정을 조회한다. |
| MODEL-003 | Model Config 수정 | 모델 파라미터와 실행 정책을 수정한다. |
| MODEL-004 | Model Config 삭제 | 사용하지 않는 설정을 비활성화한다. |
| MODEL-005 | 작업별 모델 정책 | 요약, 번역, 생성 등 작업별 모델을 설정한다. |
| MODEL-006 | 플랜별 모델 정책 | 무료와 유료 플랜의 모델 사용 정책을 설정한다. |
| MODEL-007 | Provider별 모델 정책 | Provider별 우선순위와 사용 조건을 설정한다. |
| MODEL-008 | 모델 Fallback 정책 | 모델 장애 시 대체 모델 순서를 관리한다. |
| MODEL-009 | Model Config 버전 | 설정 변경 이력을 버전으로 관리한다. |
| MODEL-010 | Provider 활성화 | 특정 Provider의 사용을 활성화한다. |
| MODEL-011 | Provider 비활성화 | 장애나 정책에 따라 Provider 사용을 중단한다. |

## 17. Retrieval 설정 관리

| ID | 기능 | 설명 |
|---|---|---|
| RET-001 | Keyword Search 설정 | 키워드 검색 방식과 가중치를 설정한다. |
| RET-002 | Vector Search 설정 | Vector 검색 방식과 Threshold를 설정한다. |
| RET-003 | Hybrid Search 설정 | Keyword와 Vector 검색 결합 정책을 설정한다. |
| RET-004 | Top-K 설정 | 검색 결과로 사용할 문서 수를 설정한다. |
| RET-005 | Reranking 설정 | 검색 결과 재정렬 모델과 정책을 설정한다. |
| RET-006 | Chunk 설정 | 문서 분할 크기와 중첩 기준을 설정한다. |
| RET-007 | Embedding 설정 | Embedding 모델과 버전을 설정한다. |
| RET-008 | Citation 설정 | 출처 표시와 검증 정책을 설정한다. |
| RET-009 | Personal Wiki 검색 범위 | 개인 Wiki 검색 깊이와 범위를 설정한다. |
| RET-010 | Global Source 검색 범위 | Global Source 검색 깊이와 범위를 설정한다. |
| RET-011 | 플랜별 Retrieval 정책 | 무료와 유료 플랜의 검색 범위를 다르게 설정한다. |

## 18. 리포트 생성기 (Report Builder)

| ID | 기능 | 설명 |
|---|---|---|
| REPORT-001 | 콘텐츠 생성 요청 | 사용자와 주제에 맞는 콘텐츠 생성 요청을 처리한다. |
| REPORT-002 | 콘텐츠 생성 계획 | 검색 범위, 콘텐츠 구조, 모델을 결정한다. |
| REPORT-003 | 사용자 컨텍스트 조회 | 생성에 필요한 사용자 설정과 플랜을 조회한다. |
| REPORT-004 | 개인 Wiki 검색 | 사용자의 관심사와 기존 지식을 검색한다. |
| REPORT-005 | Global Source 검색 | 최신 외부 자료와 근거를 검색한다. |
| REPORT-006 | 생성 자료 선별 | 콘텐츠 생성에 사용할 자료를 선별한다. |
| REPORT-007 | 콘텐츠 제목 생성 | 콘텐츠 목적에 맞는 제목을 생성한다. |
| REPORT-008 | 콘텐츠 요약 생성 | 피드와 미리보기에 사용할 요약을 생성한다. |
| REPORT-009 | 콘텐츠 본문 생성 | 플랜과 유형에 맞는 본문을 생성한다. |
| REPORT-010 | 콘텐츠 태그 생성 | 콘텐츠 검색과 추천에 사용할 태그를 생성한다. |
| REPORT-011 | 콘텐츠 Citation 생성 | 본문 주장과 참조한 자료를 연결한다. |
| REPORT-012 | 사용자 개인화 적용 | 관심사, 언어, 비선호 설정을 반영한다. |
| REPORT-013 | 기존 콘텐츠 중복 검사 | 기존 생성 콘텐츠와 유사성을 검사한다. |
| REPORT-014 | 콘텐츠 품질 평가 | 생성 결과의 관련성, 정확성, 유용성을 평가한다. |
| REPORT-015 | 콘텐츠 안전성 평가 | 생성 결과의 정책 위반 여부를 검사한다. |
| REPORT-016 | 콘텐츠 재생성 | 품질 기준을 충족하지 못한 결과를 재생성한다. |
| REPORT-017 | 콘텐츠 버전 관리 | 생성과 수정 결과를 버전으로 관리한다. |
| REPORT-018 | 생성 콘텐츠 후보 저장 | 발행 전 콘텐츠를 agent-db에 저장한다. |
| REPORT-019 | 발행 가능 상태 전환 | 품질 기준을 통과한 콘텐츠를 발행 가능 상태로 변경한다. |
| REPORT-020 | 콘텐츠 완료 이벤트 | 생성 완료 사실을 Integration Event로 발행한다. |
| REPORT-021 | 자동 Wiki 편입 금지 | 생성된 콘텐츠를 사용자 선택 없이 개인 Wiki에 넣지 않는다. |

Report Builder가 소비하는 관심사 범주 묶음은 사용자 관심사 영역의 `INT-012`가
구성한다. 활성 관심사 하나와 근거 Wiki 문서의 1홉 연결 노드를 스냅샷으로 묶어
REPORT-004·005·006·009에 전달한다.

### 18-1. 변경점 추적 (Change History)

요청 토글이 켜졌을 때 REPORT-008/009(콘텐츠 생성)를 대체하는 경로다. 직전
보고서 시점 이후의 변화를 신규·갱신으로 갈라 하나의 통합 보고서로 만든다.
토글이 꺼져 있으면 이 절의 기능은 전혀 실행되지 않는다.

| ID | 기능 | 설명 |
|---|---|---|
| CHG-001 | 변경점 추적 오케스트레이션 | Supervisor가 상태를 보고 워커 경로와 재작업을 결정한다. |
| CHG-002 | 팩트 추출·과거 대조 | 오늘 자료에서 팩트를 뽑고 도구로 과거 기록과 대조해 신규·갱신·중복을 가른다. |
| CHG-003 | 종합 브리핑·타임라인 생성 | 정제된 팩트로 과거 맥락을 잇는 브리핑과 절대 날짜 타임라인을 만든다. |
| CHG-004 | 파급효과·행동 지침 추론 | 정제된 팩트로 시장·트렌드 파급효과와 행동 지침을 추론한다. |
| CHG-005 | 델타 정합성 검증 | 갱신 대상 팩트 ID의 실재·소속, 타임라인 날짜 타당성, 서술의 인용 마커 존재를 코드로 검증한다. |
| CHG-006 | 델타 보고서 조립 | 검증을 통과한 출력에 섹션 헤더를 붙여 단일 markdown으로 조립한다. |

## 19. 생성 콘텐츠 유형

| ID | 기능 | 설명 |
|---|---|---|
| CTYPE-001 | 개인 관심사 뉴스 카드 | 사용자 관심사에 맞는 최신 뉴스 카드를 생성한다. |
| CTYPE-002 | 기술 트렌드 카드 | 기술 동향과 개발 생태계 변화를 요약한다. |
| CTYPE-003 | 논문 요약 카드 | 논문의 핵심 내용과 시사점을 정리한다. |
| CTYPE-004 | 금융 및 공시 카드 | 기업 공시와 시장 데이터를 기반으로 콘텐츠를 생성한다. |
| CTYPE-005 | 북마크 요약 카드 | 사용자가 저장한 자료를 요약한다. |
| CTYPE-006 | 관심사별 큐레이션 | 관련 콘텐츠를 주제별로 묶어 제공한다. |
| CTYPE-007 | 일간 브리핑 | 사용자 관심사에 대한 일간 업데이트를 생성한다. |
| CTYPE-008 | 주간 리포트 | 일주일간의 주요 변화와 자료를 정리한다. |
| CTYPE-009 | 심층 분석 콘텐츠 | 배경과 비교, 시사점을 포함한 긴 콘텐츠를 생성한다. |
| CTYPE-010 | 기존 콘텐츠 후속 콘텐츠 | 이전 콘텐츠의 후속 변화와 업데이트를 생성한다. |
| CTYPE-011 | 사용자 질문 기반 콘텐츠 | 사용자의 질문을 중심으로 맞춤 콘텐츠를 생성한다. |
| CTYPE-012 | 추천 콘텐츠 묶음 | 관련 콘텐츠를 하나의 추천 묶음으로 구성한다. |

## 20. 플랜별 콘텐츠 차등화

| ID | 기능 | 설명 |
|---|---|---|
| PLAN-001 | 무료 플랜 생성 정책 | 짧고 핵심적인 콘텐츠 생성 정책을 적용한다. |
| PLAN-002 | 유료 플랜 생성 정책 | 상세한 분석과 근거를 포함한 생성 정책을 적용한다. |
| PLAN-003 | 플랜별 모델 선택 | 플랜에 따라 사용할 LLM 모델을 선택한다. |
| PLAN-004 | 플랜별 Token Budget | 플랜별 입력과 출력 Token 범위를 제한한다. |
| PLAN-005 | 플랜별 Retrieval 범위 | 개인 Wiki와 Global Source 검색 깊이를 차등화한다. |
| PLAN-006 | 플랜별 콘텐츠 길이 | 무료와 유료 콘텐츠의 길이를 다르게 설정한다. |
| PLAN-007 | 플랜별 콘텐츠 상세도 | 배경 설명, 비교, 시사점의 깊이를 조정한다. |
| PLAN-008 | 플랜별 Citation 범위 | 제공할 출처의 수와 상세도를 차등화한다. |
| PLAN-009 | 플랜별 이미지 생성 | 플랜에 따라 이미지 기능을 제공하거나 제한한다. |
| PLAN-010 | 플랜별 재생성 횟수 | 품질 개선을 위한 재생성 횟수를 설정한다. |
| PLAN-011 | 플랜별 생성 빈도 | 정기 생성과 요청 가능 횟수를 차등화한다. |
| PLAN-012 | 플랜별 사용량 제한 | Agent 기능별 사용 가능량을 제한한다. |

## 21. 콘텐츠 품질 관리

| ID | 기능 | 설명 |
|---|---|---|
| QUALITY-001 | 관련성 평가 | 사용자 관심사와 생성 목적의 일치도를 평가한다. |
| QUALITY-002 | 정확성 평가 | 생성 내용이 참조 자료와 일치하는지 평가한다. |
| QUALITY-003 | 근거 충족 평가 | 주요 주장에 충분한 근거가 있는지 평가한다. |
| QUALITY-004 | Citation 평가 | 출처 연결의 정확성과 충분성을 평가한다. |
| QUALITY-005 | 최신성 평가 | 사용된 정보가 콘텐츠 목적에 충분히 최신인지 평가한다. |
| QUALITY-006 | 중복성 평가 | 기존 콘텐츠와 과도하게 유사한지 평가한다. |
| QUALITY-007 | 가독성 평가 | 문장과 구조가 읽기 쉬운지 평가한다. |
| QUALITY-008 | 완성도 평가 | 콘텐츠 구조와 내용이 완결되었는지 평가한다. |
| QUALITY-009 | 유용성 평가 | 사용자에게 실질적인 가치가 있는지 평가한다. |
| QUALITY-010 | 과도한 추론 검사 | 근거를 넘어선 추론과 과장을 검사한다. |
| QUALITY-011 | Hallucination 검사 | 원문에 없는 정보 생성 가능성을 검사한다. |
| QUALITY-012 | 플랜 정책 적합성 | 생성 결과가 해당 플랜의 형식과 범위에 맞는지 확인한다. |
| QUALITY-013 | 품질 미달 재생성 | 품질 기준 미달 시 콘텐츠를 다시 생성한다. |
| QUALITY-014 | 품질 미달 발행 차단 | 최소 품질 기준을 충족하지 못한 콘텐츠의 발행을 차단한다. |

## 22. 요약 기능

| ID | 기능 | 설명 |
|---|---|---|
| SUM-001 | URL 요약 | URL 본문을 수집하고 요약한다. |
| SUM-002 | 개인 Wiki 문서 요약 | 사용자 Wiki 문서를 관심사 중심으로 요약한다. |
| SUM-003 | Global Source 문서 요약 | 외부 수집 문서의 핵심을 요약한다. |
| SUM-004 | 생성 콘텐츠 요약 | 생성된 긴 콘텐츠를 짧게 요약한다. |
| SUM-005 | 한 줄 요약 | 콘텐츠의 핵심을 한 줄로 표현한다. |
| SUM-006 | 카드 요약 | 피드 카드에 사용할 짧은 설명을 생성한다. |
| SUM-007 | 상세 요약 | 배경과 맥락을 포함한 상세 요약을 생성한다. |
| SUM-008 | 핵심 포인트 추출 | 주요 내용을 항목 단위로 추출한다. |
| SUM-009 | 계층형 요약 | Chunk 요약을 결합해 전체 요약을 생성한다. |
| SUM-010 | 관심사 기반 요약 | 사용자가 관심 있는 관점에 맞춰 요약한다. |
| SUM-011 | Citation 포함 요약 | 요약 내용에 참조한 출처를 연결한다. |
| SUM-012 | 요약 품질 평가 | 누락, 왜곡, 과장 여부를 검사한다. |

## 23. 번역 기능

| ID | 기능 | 설명 |
|---|---|---|
| TR-001 | 문서 번역 | 전체 문서를 지정 언어로 번역한다. |
| TR-002 | 요약 번역 | 생성된 요약을 지정 언어로 번역한다. |
| TR-003 | 카드 번역 | 카드 제목, 요약, 본문을 번역한다. |
| TR-004 | 생성 콘텐츠 번역 | 리포트 생성기가 생성한 콘텐츠를 다른 언어로 번역한다. |
| TR-005 | 다국어 콘텐츠 생성 | 하나의 자료에서 언어별 콘텐츠 버전을 생성한다. |
| TR-006 | 사용자 선호 언어 반영 | 사용자의 기본 언어 설정을 번역에 적용한다. |
| TR-007 | 도메인 용어집 반영 | 기술, 금융 등 분야별 용어를 일관되게 번역한다. |
| TR-008 | Citation 유지 | 번역 후에도 원문 출처 연결을 유지한다. |
| TR-009 | 번역 품질 평가 | 오역, 누락, 고유명사 오류를 검사한다. |
| TR-010 | 언어별 버전 관리 | 콘텐츠의 언어별 버전을 관리한다. |

## 24. 이미지 자료 생성

| ID | 기능 | 설명 |
|---|---|---|
| IMG-001 | 콘텐츠 이미지 생성 | 콘텐츠에 사용할 대표 이미지를 생성한다. |
| IMG-002 | 썸네일 생성 | 피드 카드용 썸네일을 생성한다. |
| IMG-003 | 콘텐츠 삽화 생성 | 본문 이해를 돕는 삽화를 생성한다. |
| IMG-004 | 인포그래픽 생성 | 핵심 정보를 시각 자료로 구성한다. |
| IMG-005 | 차트 이미지 생성 | 구조화된 데이터를 차트로 생성한다. |
| IMG-006 | 다이어그램 생성 | 개념과 관계를 도식화한다. |
| IMG-007 | 이미지 Prompt 생성 | 콘텐츠를 이미지 생성 Prompt로 변환한다. |
| IMG-008 | 이미지 안전성 검사 | 생성 이미지의 정책 위반 여부를 검사한다. |
| IMG-009 | 이미지 품질 평가 | 관련성, 해상도, 텍스트 오류를 평가한다. |
| IMG-010 | 이미지 재생성 | 품질 기준을 충족하지 못한 이미지를 다시 생성한다. |
| IMG-011 | 이미지 저장 | 생성된 이미지를 Object Storage에 저장한다. |
| IMG-012 | 콘텐츠 이미지 연결 | 이미지 Asset을 생성 콘텐츠와 연결한다. |
| IMG-013 | 대표 이미지 선택 | 여러 Asset 중 대표 이미지를 선택한다. |
| IMG-014 | 이미지 Alt Text 생성 | 접근성을 위한 이미지 설명을 생성한다. |
| IMG-015 | 이미지 출처 관리 | 외부 이미지 사용 시 출처를 기록한다. |
| IMG-016 | 이미지 라이선스 관리 | 이미지 사용 권한과 라이선스를 관리한다. |
| IMG-017 | 플랜별 이미지 제한 | 플랜별 생성 횟수와 기능 범위를 제한한다. |

## 25. 추천 기능

| ID | 기능 | 설명 |
|---|---|---|
| REC-001 | 관심사 기반 추천 | 사용자 관심사 프로필에 맞는 콘텐츠를 추천한다. |
| REC-002 | 개인 Wiki 기반 추천 | 사용자가 저장한 지식과 유사한 자료를 추천한다. |
| REC-003 | Global Source 기반 추천 | 최신 외부 자료 중 관련성이 높은 것을 추천한다. |
| REC-004 | 유사 콘텐츠 추천 | 현재 보고 있는 콘텐츠와 유사한 콘텐츠를 추천한다. |
| REC-005 | 최신 콘텐츠 추천 | 최근 수집되거나 생성된 콘텐츠를 추천한다. |
| REC-006 | 트렌드 콘텐츠 추천 | 사용자 관심사와 연결된 트렌드를 추천한다. |
| REC-007 | 생성 콘텐츠 추천 | 다른 사용자의 공개 생성 콘텐츠를 추천한다. |
| REC-008 | 북마크 기반 추천 | 사용자의 저장 콘텐츠를 기반으로 추천한다. |
| REC-009 | 추천 점수 계산 | 관련성, 최신성, 품질, 다양성을 계산한다. |
| REC-010 | 추천 이유 생성 | 추천된 이유를 사용자에게 설명한다. |
| REC-011 | 추천 다양성 조정 | 특정 관심사에만 편중되지 않도록 조정한다. |
| REC-012 | 추천 신선도 조정 | 오래된 콘텐츠의 추천 우선순위를 조정한다. |
| REC-013 | 중복 추천 제거 | 이미 본 콘텐츠와 유사한 추천을 제거한다. |
| REC-014 | 비선호 반영 | 숨김, 차단, 신고 정보를 추천에서 반영한다. |
| REC-015 | 추천 후보 저장 | 추천 계산 결과를 agent-db에 저장한다. |
| REC-016 | 추천 완료 이벤트 | 추천 결과 준비 완료를 이벤트로 발행한다. |
| REC-017 | 사용자 피드백 반영 | 추천 결과에 대한 사용자 반응을 학습 신호로 반영한다. |
| REC-018 | 추천 A/B Test | 추천 알고리즘과 정책을 비교한다. |
| REC-019 | 자동 Wiki 편입 금지 | 추천만으로 개인 Wiki에 콘텐츠를 추가하지 않는다. |

## 26. Agent Job 관리

| ID | 기능 | 설명 |
|---|---|---|
| JOB-001 | Agent Job 생성 | 비동기 Agent 작업을 생성하고 Queue에 등록한다. |
| JOB-002 | Agent Job 조회 | 작업의 상태와 진행률을 조회한다. |
| JOB-003 | Agent Job 목록 조회 | 유형, 사용자, 상태별 작업 목록을 조회한다. |
| JOB-004 | Agent Job 취소 | 취소 가능한 작업을 중단한다. |
| JOB-005 | Agent Job 재시도 | 실패한 작업을 다시 실행한다. |
| JOB-006 | Agent Job 진행률 관리 | 긴 작업의 단계와 진행률을 기록한다. |
| JOB-007 | Agent Job 결과 연결 | 완료된 작업과 결과 데이터를 연결한다. |
| JOB-008 | Agent Job 로그 조회 | 작업 실행 과정과 오류 로그를 조회한다. |
| JOB-009 | Agent Job Timeout | 작업별 최대 실행 시간을 적용한다. |
| JOB-010 | Agent Job Idempotency | 동일 요청으로 작업이 중복 실행되지 않도록 한다. |
| JOB-011 | Agent Job 우선순위 | 중요도에 따라 작업 처리 순서를 조정한다. |
| JOB-012 | Agent Job Dead Letter | 반복 실패 작업을 별도 Queue로 격리한다. |

## 27. Agent Worker

| ID | 기능 | 설명 |
|---|---|---|
| WORKER-001 | Global Source Collector Worker | 외부 데이터를 수집하고 Global Source Pool에 저장한다. |
| WORKER-002 | Personal Wiki Builder Worker | 저장된 클리핑 Markdown을 Job Batch로 처리해 개인 Wiki Chunk·Embedding·관심사를 갱신한다. |
| WORKER-003 | Report Builder Generation Worker | 개인화 콘텐츠를 생성한다. |
| WORKER-004 | Content Quality Worker | 생성 콘텐츠의 품질과 안전성을 평가한다. |
| WORKER-005 | Summary Worker | 요약 작업을 수행한다. |
| WORKER-006 | Translation Worker | 번역 작업을 수행한다. |
| WORKER-007 | Media Worker | 이미지와 시각 자료를 생성한다. |
| WORKER-008 | Recommendation Worker | 사용자별 추천 후보를 생성한다. |
| WORKER-009 | Embedding Worker | 문서와 Chunk의 Embedding을 생성한다. |
| WORKER-010 | Reindex Worker | Embedding 모델 변경 시 재색인한다. |
| WORKER-011 | Cleanup Worker | 만료 데이터와 오래된 로그를 정리한다. |
| WORKER-012 | Event Publisher Worker | Outbox 이벤트를 Integration Event Bus로 발행한다. |

## 28. Worker 공통 기능

| ID | 기능 | 설명 |
|---|---|---|
| WC-001 | Queue Job Consume | 설정된 Batch 크기만큼 실행 가능한 작업을 가져온다. |
| WC-002 | Job Claim | 여러 Worker가 중복 실행하지 않도록 작업 Batch를 Lease와 함께 점유한다. |
| WC-003 | Worker Heartbeat | Worker의 생존 상태와 처리 중인 Claim Lease를 갱신한다. |
| WC-004 | Worker 상태 조회 | Worker별 실행 상태와 처리량을 조회한다. |
| WC-005 | 작업 진행률 기록 | 장시간 작업의 처리 단계를 기록한다. |
| WC-006 | Retry 정책 | 재시도 가능한 개별 작업을 Backoff 후 Queue로 되돌린다. |
| WC-007 | Exponential Backoff | 재시도 간격을 점진적으로 증가시킨다. |
| WC-008 | Dead Letter Queue | 반복 실패 작업을 격리한다. |
| WC-009 | Idempotency 처리 | 중복 작업 실행에도 동일 결과를 보장한다. |
| WC-010 | 작업 중복 방지 | 동일 Resource에 대한 동시 작업을 방지한다. |
| WC-011 | 작업 Timeout | 지정된 시간 이상 실행되는 작업을 종료한다. |
| WC-012 | 작업 취소 | 취소 요청이 들어온 작업을 중단한다. |
| WC-013 | Concurrency 제어 | Batch Claim 크기와 실제 작업·LLM 호출 동시 실행 수를 독립적으로 제한한다. |
| WC-014 | 외부 API Rate Limit | 외부 Source와 Provider의 호출 제한을 준수한다. |
| WC-015 | Graceful Shutdown | 진행 중 작업을 정리하고 안전하게 종료한다. |
| WC-016 | Worker 로그 | 작업 실행과 오류 정보를 기록한다. |
| WC-017 | Trace Context 전달 | API 요청부터 Worker와 Provider까지 추적 정보를 유지한다. |

## 29. Scheduler

| ID | 기능 | 설명 |
|---|---|---|
| SCH-001 | RSS 수집 스케줄 | RSS Source 수집 작업을 정기 등록한다. |
| SCH-002 | Naver API 수집 스케줄 | Naver API 수집 작업을 정기 등록한다. |
| SCH-003 | GDELT 수집 스케줄 | GDELT 수집 작업을 정기 등록한다. |
| SCH-004 | NewsAPI 수집 스케줄 | NewsAPI 수집 작업을 정기 등록한다. |
| SCH-005 | DART 수집 스케줄 | DART 수집 작업을 정기 등록한다. |
| SCH-006 | KRX 수집 스케줄 | KRX 수집 작업을 정기 등록한다. |
| SCH-007 | GitHub 수집 스케줄 | GitHub 수집 작업을 정기 등록한다. |
| SCH-008 | arXiv 수집 스케줄 | arXiv 수집 작업을 정기 등록한다. |
| SCH-009 | 사용자 Wiki 재구성 스케줄 | 변경이 누적된 사용자의 Wiki를 재구성한다. |
| SCH-010 | 사용자 관심사 재계산 | 개인 Wiki 변경에 따라 관심사 프로필을 재계산한다. |
| SCH-012 | 추천 갱신 스케줄 | 사용자별 추천 후보 갱신 작업을 등록한다. |
| SCH-013 | Embedding 재색인 | Embedding 모델 변경에 따른 재색인을 등록한다. |
| SCH-014 | 로그 정리 스케줄 | 보존 기간이 지난 로그를 정리한다. |
| SCH-015 | 오래된 데이터 정리 | 만료된 Source와 생성 후보를 정리한다. |
| SCH-016 | API 사용량 초기화 | 주기별 API Quota 사용량을 초기화한다. |
| SCH-017 | 스케줄 등록 | 새로운 정기 작업을 등록한다. |
| SCH-018 | 스케줄 수정 | 기존 작업의 실행 주기를 변경한다. |
| SCH-019 | 스케줄 중지 | 정기 작업 실행을 일시 중지한다. |
| SCH-020 | 스케줄 재개 | 중지된 정기 작업을 다시 활성화한다. |
| SCH-021 | 스케줄 수동 실행 | 관리자가 정기 작업을 즉시 실행한다. |
| SCH-022 | 스케줄 이력 조회 | 스케줄별 실행 결과와 상태를 조회한다. |
| SCH-023 | 실패 스케줄 재실행 | 실패한 정기 작업을 다시 실행한다. |

> 콘텐츠 생성 스케줄(구 SCH-011)은 service 계층 스케줄러가 담당한다(2026-07-20
> 결정). 사용자 지정 생성 시간의 원천 데이터가 service-db에 있으므로, service
> 스케줄러가 그 시각에 SVC-008 `POST /generations`를 멱등 호출하거나
> `scheduled_at`으로 예약 등록한다. Agent Scheduler는 수집·정리 등 내부 정기
> 작업만 담당한다.

## 30. Queue 및 Integration Event

| ID | 기능 | 설명 |
|---|---|---|
| QUEUE-001 | Agent 내부 작업 Queue | Agent Worker에 비동기 작업 명령을 전달한다. |
| QUEUE-002 | 작업 유형별 Queue | 수집, Wiki, 생성, 미디어 작업을 분리한다. |
| QUEUE-003 | 우선순위 Queue | 긴급도에 따라 작업 처리 순서를 조정한다. |
| QUEUE-004 | 재시도 Queue | 재처리가 필요한 작업을 관리한다. |
| QUEUE-005 | Dead Letter Queue | 반복 실패 작업을 별도로 관리한다. |
| QUEUE-006 | 작업 지연 실행 | 지정 시간 이후 실행할 작업을 예약한다. |
| QUEUE-007 | Queue Backlog 관리 | 대기 작업 수와 처리 속도를 관리한다. |
| EVT-001 | User Wiki Updated 이벤트 | 개인 Wiki 갱신 완료 사실을 전달한다. |
| EVT-002 | User Interest Updated 이벤트 | 사용자 관심사 프로필 갱신을 전달한다. |
| EVT-003 | Global Source Collected 이벤트 | 외부 Source 수집 완료 사실을 전달한다. |
| EVT-004 | Content Ready 이벤트 | 발행 가능한 콘텐츠가 준비되었음을 전달한다. |
| EVT-005 | Content Generation Failed 이벤트 | 콘텐츠 생성 실패 사실을 전달한다. |
| EVT-006 | Recommendation Ready 이벤트 | 추천 후보가 준비되었음을 전달한다. |
| EVT-007 | Image Asset Ready 이벤트 | 이미지 Asset 생성 완료를 전달한다. |
| EVT-008 | Event Schema Version 관리 | 이벤트 구조의 버전을 관리한다. |
| EVT-009 | Event Idempotency | 동일 이벤트의 중복 처리를 방지한다. |
| EVT-010 | Event Retry | 전달 실패 이벤트를 재전송한다. |
| EVT-011 | Event Dead Letter | 반복 실패 이벤트를 격리한다. |
| EVT-012 | Event Outbox | DB 저장과 이벤트 발행의 일관성을 보장한다. |
| EVT-013 | Event 처리 결과 ACK | Consumer의 처리 성공과 실패를 기록한다. |

## 31. Service API 연동

| ID | 기능 | 설명 |
|---|---|---|
| SVC-001 | 사용자 컨텍스트 전달 | 서비스 사용자 설정을 Agent 컨텍스트로 전달한다. |
| SVC-002 | 웹 클리핑 처리 요청 | 클리핑 Markdown과 Frontmatter를 영속 저장하고 개인 Wiki 처리 Job을 등록한다. |
| SVC-003 | URL 처리 요청 | 입력된 URL을 개인 Wiki 처리 작업으로 전달한다. |
| SVC-004 | 위키마킹 처리 요청 | 사용자가 선택한 콘텐츠의 Wiki 편입을 요청한다. |
| SVC-005 | 콘텐츠 상호작용 전달 | 콘텐츠와의 대화와 수정 결과를 전달한다. |
| SVC-006 | 사용자 피드백 전달 | 좋아요, 숨김, 신고 등의 신호를 전달한다. |
| SVC-007 | 개인 Wiki 재구성 요청 | 특정 사용자의 Wiki 재구성을 요청한다. |
| SVC-008 | 콘텐츠 생성 요청 | 리포트 생성기의 콘텐츠 생성을 요청한다. |
| SVC-009 | 요약 요청 | 문서 또는 URL 요약을 요청한다. |
| SVC-010 | 번역 요청 | 콘텐츠 번역을 요청한다. |
| SVC-011 | 추천 요청 | 사용자별 추천 생성을 요청한다. |
| SVC-012 | 관리자 설정 변경 요청 | Prompt, Model, Source 설정 변경을 요청한다. |
| SVC-013 | Agent Job 상태 조회 | 비동기 작업 상태를 조회한다. |
| SVC-014 | Agent 결과 조회 | 생성 및 처리 결과를 Agent API에서 조회한다. |

## 32. Service Worker 연동

| ID | 기능 | 설명 |
|---|---|---|
| SW-001 | Content Ready 이벤트 수신 | 발행 가능한 콘텐츠 이벤트를 소비한다. |
| SW-002 | Recommendation Ready 이벤트 수신 | 추천 결과 이벤트를 소비한다. |
| SW-003 | Image Asset Ready 이벤트 수신 | 이미지 생성 완료 이벤트를 소비한다. |
| SW-004 | Publish Snapshot 조회 | Agent API에서 단건 Snapshot을 조회하거나 준비된 Snapshot Batch를 Claim한다. |
| SW-005 | 발행 가능 상태 검증 | 콘텐츠가 실제 발행 가능한 상태인지 확인한다. |
| SW-006 | 콘텐츠 Version 검증 | 오래된 콘텐츠 버전이 반영되지 않도록 확인한다. |
| SW-007 | service-db 콘텐츠 Upsert | 콘텐츠 발행본을 service-db에 저장하거나 갱신한다. |
| SW-008 | service-db 피드 Upsert | 발행 콘텐츠를 사용자 피드에 반영한다. |
| SW-009 | 발행 완료 ACK | 단건 또는 Batch의 항목별 service-db 반영 결과를 Agent API에 알린다. |
| SW-010 | 발행 실패 전달 | 항목별 발행 실패 사유와 재시도 가능 여부를 Agent API에 전달한다. |
| SW-011 | 이벤트 중복 처리 방지 | 동일 이벤트·Batch Claim·ACK가 여러 번 반영되지 않도록 한다. |
| SW-012 | 오래된 이벤트 무시 | 최신 버전보다 오래된 이벤트를 무시한다. |
| SW-013 | 콘텐츠 무결성 검증 | 단건 및 Batch의 각 Snapshot Hash와 버전을 확인한다. |

## 33. 발행 콘텐츠 관리

| ID | 기능 | 설명 |
|---|---|---|
| PUB-001 | 발행용 Snapshot 생성 | service-db에 저장할 콘텐츠 형식을 생성한다. |
| PUB-002 | 생성 콘텐츠 조회 | Agent DB의 생성 결과를 조회한다. |
| PUB-003 | 생성 콘텐츠 Version 조회 | 특정 버전의 생성 결과를 조회한다. |
| PUB-004 | 발행 상태 관리 | Snapshot의 Ready, Claimed, Published, Failed 상태와 Claim Lease를 관리한다. |
| PUB-005 | 발행 완료 처리 | Service Worker의 단건·Batch 완료 응답을 항목별로 반영한다. |
| PUB-006 | 발행 실패 처리 | 항목별 실패 사유, 재시도 여부와 다음 실행 시각을 기록한다. |
| PUB-007 | 재발행 처리 | 새로운 콘텐츠 버전을 다시 발행한다. |
| PUB-008 | 콘텐츠 Archive | 더 이상 노출하지 않는 콘텐츠를 보관 상태로 변경한다. |
| PUB-009 | 콘텐츠 Superseded | 새 버전으로 대체된 콘텐츠 상태를 관리한다. |
| PUB-010 | 발행 이력 관리 | 버전과 Batch Claim별 발행 시도·완료·실패 이력을 기록한다. |

## 34. 관리자 기능

| ID | 기능 | 설명 |
|---|---|---|
| ADMIN-001 | Prompt 관리 | Prompt Template과 버전을 관리한다. |
| ADMIN-002 | Model Config 관리 | 모델 실행 설정과 라우팅 정책을 관리한다. |
| ADMIN-003 | Retrieval 설정 관리 | 검색과 RAG 정책을 관리한다. |
| ADMIN-004 | Embedding 설정 관리 | Embedding 모델과 색인 정책을 관리한다. |
| ADMIN-005 | Generation Policy 관리 | 플랜별 콘텐츠 생성 정책을 관리한다. |
| ADMIN-006 | Global Source 관리 | 외부 수집 Source와 설정을 관리한다. |
| ADMIN-007 | 수집 스케줄 관리 | Source별 정기 수집 일정을 관리한다. |
| ADMIN-008 | 수집 작업 수동 실행 | 선택한 Source를 즉시 수집한다. |
| ADMIN-009 | 수집 이력 조회 | Source별 수집 성공과 실패 이력을 조회한다. |
| ADMIN-010 | Global Source 문서 조회 | 수집된 외부 문서를 검수한다. |
| ADMIN-011 | Personal Wiki 상태 조회 | 권한 범위 내에서 사용자 Wiki 처리 상태를 조회한다. |
| ADMIN-012 | Agent Job 조회 | 전체 Agent 작업 상태를 조회한다. |
| ADMIN-013 | Agent Job 재시도 | 실패한 Agent 작업을 다시 실행한다. |
| ADMIN-014 | 생성 콘텐츠 후보 조회 | 발행 전 생성 콘텐츠를 검수한다. |
| ADMIN-015 | 콘텐츠 재생성 | 선택한 콘텐츠를 새로운 설정으로 재생성한다. |
| ADMIN-016 | 콘텐츠 품질 평가 조회 | 품질 점수와 평가 결과를 조회한다. |
| ADMIN-017 | 콘텐츠 안전성 평가 조회 | 안전성 검사 결과를 조회한다. |
| ADMIN-018 | Worker 상태 조회 | Worker의 상태와 처리량을 조회한다. |
| ADMIN-019 | Queue 상태 조회 | Queue 적체와 실패 작업을 조회한다. |
| ADMIN-020 | LLM 사용량 조회 | 모델별 Token 사용량을 조회한다. |
| ADMIN-021 | LLM 비용 조회 | Provider와 기능별 비용을 조회한다. |
| ADMIN-022 | API Key 관리 | 외부 API Key를 발급하고 폐기한다. |
| ADMIN-023 | Agent 로그 조회 | 생성, 검색, 수집 로그를 조회한다. |

## 35. 자체 API Key

| ID | 기능 | 설명 |
|---|---|---|
| KEY-001 | API Key 발급 | 외부 시스템용 API Key를 생성한다. |
| KEY-002 | API Key 조회 | 발급된 Key의 상태와 설정을 조회한다. |
| KEY-003 | API Key 이름 변경 | 관리 편의를 위해 Key 이름을 수정한다. |
| KEY-004 | API Key 비활성화 | Key 사용을 일시 중지한다. |
| KEY-005 | API Key 폐기 | Key를 영구적으로 사용 중지한다. |
| KEY-006 | API Key Rotation | 새 Key를 발급하고 이전 Key를 교체한다. |
| KEY-007 | API Key 만료 설정 | Key의 사용 가능 기간을 설정한다. |
| KEY-008 | API Key Hash 저장 | 원본 Key 대신 안전한 Hash를 저장한다. |
| KEY-009 | API Key Scope 설정 | Key로 사용할 수 있는 기능 범위를 설정한다. |
| KEY-010 | API Key Quota 설정 | 기간별 호출량과 Token 한도를 설정한다. |
| KEY-011 | API Key Rate Limit | 초·분 단위 호출 제한을 적용한다. |
| KEY-012 | API Key 사용량 조회 | 호출량, Token, 비용을 조회한다. |
| KEY-013 | API Key 감사 로그 | 발급, 수정, 폐기 이력을 기록한다. |
| KEY-014 | Personal Wiki 접근 권한 | 특정 사용자의 Wiki에 접근할 수 있는 권한을 연결한다. |

## 36. External Agent API

| ID | 기능 | 설명 |
|---|---|---|
| EXT-001 | 외부 요약 API | 외부 시스템에 문서와 URL 요약 기능을 제공한다. |
| EXT-002 | 외부 번역 API | 외부 시스템에 번역 기능을 제공한다. |
| EXT-003 | 외부 콘텐츠 생성 API | 외부 시스템에서 콘텐츠 생성을 요청할 수 있게 한다. |
| EXT-004 | 외부 Global Search API | Global Source Pool 검색 기능을 제공한다. |
| EXT-005 | 외부 Personal Wiki Search API | 사용자 승인이 있는 개인 Wiki 검색을 제공한다. |
| EXT-006 | 외부 추천 API | 사용자 컨텍스트 기반 추천 기능을 제공한다. |
| EXT-007 | 외부 이미지 생성 API | 외부 시스템에 이미지 생성 기능을 제공한다. |
| EXT-008 | 외부 Job 상태 조회 | 비동기 작업 상태와 결과를 조회한다. |
| EXT-009 | 외부 Webhook Callback | 작업 완료 결과를 외부 시스템에 전달한다. |
| EXT-010 | API Scope 검증 | 요청 기능에 필요한 Scope를 확인한다. |
| EXT-011 | API Quota 검증 | API Key의 사용량 한도를 확인한다. |
| EXT-012 | API Rate Limit | 외부 호출량을 제한한다. |
| EXT-013 | 외부 호출 로그 | 외부 API 요청과 결과를 기록한다. |
| EXT-014 | 외부 사용량 기록 | 외부 고객별 Token과 비용을 기록한다. |

## 37. MCP Server

| ID | 기능 | 설명 |
|---|---|---|
| MCP-001 | MCP Server 실행 | 외부 Agent 연결을 위한 MCP 서버를 실행한다. |
| MCP-002 | MCP 연결 관리 | MCP Client 연결과 세션을 관리한다. |
| MCP-003 | MCP 인증 | API Key 또는 사용자 권한을 검증한다. |
| MCP-004 | MCP Tool 목록 제공 | 사용 가능한 Tool 목록을 반환한다. |
| MCP-005 | MCP Tool Schema 제공 | 각 Tool의 입력과 출력 Schema를 제공한다. |
| MCP-006 | MCP Tool 실행 | 외부 Agent가 요청한 Tool을 실행한다. |
| MCP-007 | MCP 비동기 Job 지원 | 긴 작업에 Job ID를 반환한다. |
| MCP-008 | MCP 호출 로그 | Tool 호출과 결과를 기록한다. |
| MCP-009 | MCP Scope 검증 | Tool별 필요한 권한을 검증한다. |
| MCP-010 | MCP Quota 적용 | API Key별 호출량과 Token 제한을 적용한다. |
| MCP-011 | MCP 사용자 권한 검증 | Personal Wiki 접근에 사용자 승인이 있는지 확인한다. |

## 38. MCP Tool

| ID | 기능 | 설명 |
|---|---|---|
| MCPTOOL-001 | Personal Wiki 검색 | 승인된 사용자의 개인 Wiki를 검색한다. |
| MCPTOOL-002 | Personal Wiki 문서 조회 | 개인 Wiki의 특정 문서를 조회한다. |
| MCPTOOL-003 | Personal Wiki Source 추가 | 사용자 승인 하에 Wiki Source를 추가한다. |
| MCPTOOL-004 | Global Source 검색 | 공용 Global Source Pool을 검색한다. |
| MCPTOOL-005 | 콘텐츠 요약 | 텍스트, URL, 문서를 요약한다. |
| MCPTOOL-006 | 콘텐츠 번역 | 콘텐츠를 지정한 언어로 번역한다. |
| MCPTOOL-007 | 콘텐츠 생성 | 리포트 생성기 콘텐츠 생성을 요청한다. |
| MCPTOOL-008 | 콘텐츠 추천 | 사용자 관심사 기반 추천을 요청한다. |
| MCPTOOL-009 | 이미지 자료 생성 | 콘텐츠용 이미지 생성을 요청한다. |
| MCPTOOL-010 | Job 상태 조회 | 비동기 Job의 상태를 조회한다. |
| MCPTOOL-011 | Global Source 수동 수집 | 권한이 있는 사용자가 Source 수집을 실행한다. |
| MCPTOOL-012 | Prompt 테스트 | 관리자 권한으로 Prompt를 테스트한다. |
| MCPTOOL-013 | Personal Wiki 구조화 문서 저장 | Claude가 분류한 entity/concept 항목을 검증 후 개인 Wiki에 저장한다. |
| MCPTOOL-014 | Personal Wiki 재빌드 트리거 | 저장된 Source를 서버 LLM 파이프라인으로 재구성하도록 요청한다. |

## 39. Agent DB

| ID | 기능 | 설명 |
|---|---|---|
| DB-001 | 사용자 컨텍스트 저장 | Agent가 사용할 최소 사용자 컨텍스트를 저장한다. |
| DB-002 | Wiki Source Event·사용자 원본 저장 | 개인 Wiki 반영 이벤트와 클리핑 Markdown·Frontmatter 원본 Version을 저장한다. |
| DB-003 | 개인 LLM Wiki 문서 저장 | Worker가 생성한 Entity·Concept·Schema 문서 Version과 원본·문서 관계를 저장한다. |
| DB-004 | 개인 Wiki Chunk 저장 | 개인 Wiki 검색용 Chunk를 저장한다. |
| DB-005 | 개인 Wiki Embedding 저장 | 개인 Wiki의 Vector 데이터를 저장한다. |
| DB-006 | 개인 Wiki Version 저장 | 개인 Wiki Build 버전과 해당 시점의 문서 Version·Vault 경로 구성을 저장한다. |
| DB-007 | 사용자 관심사 저장 | 관심사 프로필, 계층, 관계를 저장한다. |
| DB-008 | Global Source 저장 | 외부 수집 Source와 설정을 저장한다. |
| DB-009 | Global Collection Run 저장 | 수집 실행 결과와 상태를 저장한다. |
| DB-010 | Global 문서 저장 | 수집된 외부 문서를 수집 캐시에 저장한다. |
| DB-011 | Global Chunk 저장 | Global Source 검색용 Chunk를 저장한다. |
| DB-012 | Global Embedding 저장 | Global Source의 Vector 데이터를 저장한다. |
| DB-013 | Global Trend 저장 | 탐지된 트렌드와 문서 그룹을 저장한다. |
| DB-014 | Discovery Candidate 저장 | 생성 및 추천 후보를 저장한다. |
| DB-015 | Generation Request 저장 | 콘텐츠 생성 요청을 저장한다. |
| DB-016 | Generated Content 저장 | 생성 콘텐츠와 버전을 저장한다. |
| DB-017 | Citation 저장 | 생성 콘텐츠와 출처 연결을 저장한다. |
| DB-018 | Content Asset 저장 | 이미지와 기타 Asset 메타데이터를 저장한다. |
| DB-019 | Quality Evaluation 저장 | 콘텐츠 품질 평가 결과를 저장한다. |
| DB-020 | Safety Evaluation 저장 | 콘텐츠 안전성 평가 결과를 저장한다. |
| DB-021 | Recommendation Candidate 저장 | 사용자별 추천 후보를 저장한다. |
| DB-022 | Prompt 저장 | Prompt Template과 버전을 저장한다. |
| DB-023 | Model Config 저장 | 모델 설정과 버전을 저장한다. |
| DB-024 | Retrieval 설정 저장 | 검색과 RAG 설정을 저장한다. |
| DB-025 | Embedding 설정 저장 | Embedding 모델과 정책을 저장한다. |
| DB-026 | Agent Job 저장 | 비동기 작업 상태와 결과를 저장한다. |
| DB-027 | Event Outbox 저장 | 발행 예정 이벤트를 저장한다. |
| DB-028 | API Key 저장 | 외부 API Key와 Scope 정보를 저장한다. |
| DB-029 | Usage Log 저장 | Token, API 호출량, 비용을 저장한다. |
| DB-030 | Audit Log 저장 | 관리자와 외부 접근 이력을 저장한다. |

## 40. Object Storage

| ID | 기능 | 설명 |
|---|---|---|
| OBJ-001 | 원본 Source 저장 | 웹 클리핑은 Markdown 원문을 DB에 보존하고, 수집 HTML 등 대용량 원본만 Object Storage에 저장한다. |
| OBJ-002 | PDF 저장 | 논문과 공시 등의 PDF 원문을 저장한다. |
| OBJ-003 | 외부 API 원본 응답 저장 | 대용량 외부 API 응답을 저장한다. |
| OBJ-004 | 대용량 본문 저장 | DB에 적합하지 않은 긴 텍스트를 저장한다. |
| OBJ-005 | 생성 콘텐츠 원문 저장 | 대용량 생성 콘텐츠를 저장한다. |
| OBJ-006 | LLM Trace 저장 | 전체 Prompt, Completion, Tool Trace를 저장한다. |
| OBJ-007 | 생성 이미지 저장 | 콘텐츠용 생성 이미지를 저장한다. |
| OBJ-008 | 썸네일 저장 | 피드 카드용 썸네일을 저장한다. |
| OBJ-009 | 인포그래픽 저장 | 생성된 인포그래픽 파일을 저장한다. |
| OBJ-010 | 차트 이미지 저장 | 생성된 차트 파일을 저장한다. |
| OBJ-011 | 임시 처리 파일 저장 | 수집과 변환 과정의 임시 파일을 저장한다. |
| OBJ-012 | Object Metadata 관리 | 크기, 형식, Checksum 등의 정보를 관리한다. |
| OBJ-013 | Object 보존 기간 관리 | 파일 유형별 보존 기간을 적용한다. |
| OBJ-014 | Object 삭제 처리 | 삭제 요청과 보존 정책에 따라 파일을 제거한다. |

## 41. 로그 및 모니터링

| ID | 기능 | 설명 |
|---|---|---|
| OBS-001 | API 요청 로그 | Agent API 요청과 응답 상태를 기록한다. |
| OBS-002 | Agent Job 로그 | 비동기 작업의 실행 단계를 기록한다. |
| OBS-003 | Worker 실행 로그 | Worker별 처리 결과와 오류를 기록한다. |
| OBS-004 | Scheduler 실행 로그 | 스케줄 실행과 Job 등록 결과를 기록한다. |
| OBS-005 | Global Source 수집 로그 | Source별 수집 결과와 오류를 기록한다. |
| OBS-006 | Wiki Build 로그 | 개인 Wiki 구성과 재구성 결과를 기록한다. |
| OBS-007 | Generation 로그 | 콘텐츠 생성 과정과 사용 모델을 기록한다. |
| OBS-008 | Retrieval 로그 | 개인 Wiki와 Global Source 검색 결과를 기록한다. |
| OBS-009 | Translation 로그 | 번역 요청과 결과 상태를 기록한다. |
| OBS-010 | Image Generation 로그 | 이미지 생성 요청과 결과를 기록한다. |
| OBS-011 | Recommendation 로그 | 추천 후보와 점수 계산 결과를 기록한다. |
| OBS-012 | Token Usage 로그 | 작업별 입력·출력 Token을 기록한다. |
| OBS-013 | Provider Usage 로그 | 외부 Provider 사용량과 오류를 기록한다. |
| OBS-014 | 비용 추적 | 기능, 사용자, Provider별 비용을 계산한다. |
| OBS-015 | Queue Backlog 모니터링 | 대기 작업과 처리 지연을 감시한다. |
| OBS-016 | Worker Heartbeat 모니터링 | Worker 생존 상태를 감시한다. |
| OBS-017 | 작업 성공률 모니터링 | 작업 유형별 성공률을 집계한다. |
| OBS-018 | 작업 실패율 모니터링 | 실패와 재시도 비율을 집계한다. |
| OBS-019 | 콘텐츠 품질 지표 | 품질 통과, 재생성, 거절 비율을 집계한다. |
| OBS-020 | Wiki 품질 지표 | 중복률, 문서 수, Build 실패율을 집계한다. |
| OBS-021 | 분산 Trace | Service부터 Agent Worker와 Provider까지 추적한다. |
| OBS-022 | 장애 Alert | Queue 적체, Provider 장애, 반복 실패를 알린다. |

## 42. 보안 및 개인정보

| ID | 기능 | 설명 |
|---|---|---|
| SEC-001 | Agent API Network 격리 | Internal Agent API를 외부 네트워크에서 차단한다. |
| SEC-002 | Internal API 인증 | 승인된 Service와 Worker만 접근하도록 한다. |
| SEC-003 | 사용자 데이터 격리 | 사용자별 Personal Wiki와 Vector 데이터를 격리한다. |
| SEC-004 | Personal Wiki 접근 제어 | 사용자 본인과 승인된 주체만 접근하도록 한다. |
| SEC-005 | 개인정보 최소 수집 | AI 처리에 필요하지 않은 개인정보를 저장하지 않는다. |
| SEC-006 | 개인정보 제거 | 대화와 문서에서 불필요한 개인정보를 제거한다. |
| SEC-007 | 데이터 암호화 | 전송과 저장 데이터에 암호화를 적용한다. |
| SEC-008 | Secret 관리 | Provider Key와 외부 API Key를 안전하게 관리한다. |
| SEC-009 | 외부 API Key 보호 | API Key 원문을 저장하지 않고 Hash로 관리한다. |
| SEC-010 | Prompt Injection 방어 | 외부 문서의 명령문이 Agent 지시를 변경하지 못하도록 한다. |
| SEC-011 | 생성 결과 안전성 검사 | 정책 위반 콘텐츠의 생성과 발행을 차단한다. |
| SEC-012 | 관리자 권한 검증 | 관리 기능별 세부 관리자 권한을 검증한다. |
| SEC-013 | API Scope 최소 권한 | 외부 Key와 MCP Tool에 최소 권한만 부여한다. |
| SEC-014 | 사용자 삭제 요청 반영 | 탈퇴와 삭제 요청을 Agent 데이터에 반영한다. |
| SEC-015 | Wiki 삭제 전파 | 개인 Wiki 문서와 버전을 삭제하거나 비활성화한다. |
| SEC-016 | Embedding 삭제 전파 | 삭제된 문서의 Vector 데이터를 제거한다. |
| SEC-017 | Cache 삭제 전파 | 삭제된 사용자 데이터의 Cache를 제거한다. |
| SEC-018 | 데이터 보존 기간 관리 | 데이터 유형별 보존과 파기 정책을 적용한다. |
| SEC-019 | 접근 Audit Log | Personal Wiki와 민감 기능 접근 이력을 기록한다. |
| SEC-020 | 관리자 변경 Audit Log | 설정과 정책 변경 내역을 기록한다. |

## 43. 비기능 요구사항

| ID | 기능 | 설명 |
|---|---|---|
| NFR-001 | Eventual Consistency | Service와 Agent 데이터 간 지연된 일관성을 허용한다. |
| NFR-002 | Idempotency | 동일 요청과 이벤트의 중복 처리에도 결과를 안정적으로 유지한다. |
| NFR-003 | Event Schema Versioning | 이벤트 구조 변경을 버전으로 관리한다. |
| NFR-004 | API Schema Versioning | API 구조 변경을 버전으로 관리한다. |
| NFR-005 | 콘텐츠 Version 관리 | 생성 콘텐츠와 발행 콘텐츠의 버전을 관리한다. |
| NFR-006 | Prompt Version 관리 | 생성에 사용한 Prompt 버전을 추적한다. |
| NFR-007 | Model Config Version 관리 | 모델 설정 변경 이력을 추적한다. |
| NFR-008 | Wiki Version 관리 | 개인 Wiki 재구성 이력을 버전으로 관리한다. |
| NFR-009 | 오류 유형 분류 | 재시도 가능한 오류와 불가능한 오류를 구분한다. |
| NFR-010 | Dead Letter 처리 | 반복 실패 작업과 이벤트를 격리한다. |
| NFR-011 | Outbox Pattern | DB 저장과 이벤트 발행의 일관성을 보장한다. |
| NFR-012 | Inbox Pattern | Consumer의 이벤트 중복 처리를 방지한다. |
| NFR-013 | Graceful Degradation | 일부 Provider 장애 시 핵심 기능을 제한적으로 제공한다. |
| NFR-014 | Horizontal Scaling | API와 Worker를 수평 확장할 수 있어야 한다. |
| NFR-015 | Worker Auto Scaling | Queue 적체에 따라 Worker 수를 조정할 수 있어야 한다. |
| NFR-016 | Queue Backpressure | 처리량을 초과하는 작업 유입을 제어한다. |
| NFR-017 | Provider 장애 대응 | 외부 API와 모델 장애 시 Fallback을 적용한다. |
| NFR-018 | 데이터 무결성 | 문서, Chunk, Embedding 간 관계를 일관되게 유지한다. |
| NFR-019 | 콘텐츠 무결성 | 발행본과 Agent 생성본의 버전과 Hash를 검증한다. |
| NFR-020 | 사용자별 데이터 격리 | 모든 개인 데이터 조회에 사용자 범위를 강제한다. |
| NFR-021 | 비용 제한 | 사용자, 플랜, 기능별 최대 비용을 제한한다. |
| NFR-022 | 성능 모니터링 | API와 Worker의 처리 시간과 처리량을 지속적으로 측정한다. |

## 44. MVP 개발 범위

| ID | 기능 | 설명 |
|---|---|---|
| MVP-001 | FastAPI 기본 진입점 | Agent API 실행과 기본 시스템 기능을 구현한다. |
| MVP-002 | Internal API 인증 | Service와 Agent 간 내부 인증을 구현한다. |
| MVP-003 | 사용자 컨텍스트 관리 | Agent용 최소 사용자 컨텍스트를 관리한다. |
| MVP-004 | 웹 클리핑 처리 | 사용자 웹 클리핑을 수신해 Markdown 원문을 영속 저장하고 Wiki Build Job을 등록한다. |
| MVP-005 | URL 입력 처리 | 사용자가 입력한 URL을 개인 Wiki에 반영한다. |
| MVP-006 | 개인 Wiki 문서 구성 | Worker가 클리핑 원본을 바탕으로 Version이 있는 LLM Wiki와 출처 관계를 생성한다. |
| MVP-007 | 개인 Wiki Chunk 및 Embedding | Worker가 생성한 LLM Wiki의 Chunk와 Embedding을 생성·영속 저장한다. |
| MVP-008 | 개인 Wiki 검색 | Keyword, Vector, Hybrid 검색을 구현한다. |
| MVP-009 | 관심사 기본 분류 | 개인 Wiki에서 사용자 관심사를 추출한다. |
| MVP-010 | Personal Wiki Builder | Lease 기반 Worker가 클리핑 Job을 증분 Build하고 상태·재시도를 관리한다. |
| MVP-011 | RSS 수집 | Global Source RSS 수집을 구현한다. |
| MVP-012 | 직접 URL 수집 | 외부 URL Source 수집을 구현한다. |
| MVP-013 | Global Source Pool | 외부 수집 문서 저장과 검색 기반을 구현한다. |
| MVP-014 | 리포트 생성기 텍스트 콘텐츠 생성 | Personal Wiki와 Global Source 기반 생성을 구현한다. |
| MVP-015 | 무료 및 유료 생성 정책 | 플랜별 기본 생성 차등화를 구현한다. |
| MVP-016 | 콘텐츠 품질 평가 | 기본 품질 기준과 재생성을 구현한다. |
| MVP-017 | Content Ready 이벤트 | 생성 결과 완료 이벤트를 구현한다. |
| MVP-018 | Service Worker 발행 연동 | Publish Snapshot Batch Claim, 부분 성공 ACK와 service-db 반영 흐름을 구현한다. |
| MVP-019 | Agent Job 관리 | 클리핑·생성 Job의 PostgreSQL 저장, Batch Claim, Lease, 상태와 재시도를 구현한다. |
| MVP-020 | Retry 및 Dead Letter | 실패 작업 처리 기반을 구현한다. |
| MVP-021 | Prompt 관리 | Prompt Template과 버전 관리를 구현한다. |
| MVP-022 | Model Config 관리 | 작업별 모델 설정 관리를 구현한다. |
| MVP-023 | 기본 로그 및 모니터링 | API, Worker, LLM 사용량 로그를 구현한다. |

## 45. 2차 개발 범위

| ID | 기능 | 설명 |
|---|---|---|
| PH2-001 | 위키마킹 | 다른 사용자의 콘텐츠를 개인 Wiki에 편입한다. |
| PH2-002 | Interaction Memory | 콘텐츠와의 대화를 개인 지식으로 정리한다. |
| PH2-003 | Personal Wiki Full Rebuild | 개인 Wiki 전체 재구성을 구현한다. |
| PH2-004 | 관심사 계층 및 관계 | 사용자 관심사 Graph 구조를 구현한다. |
| PH2-005 | Naver API 수집 | Naver 기반 뉴스와 블로그 수집을 구현한다. |
| PH2-006 | NewsAPI 수집 | NewsAPI 기반 뉴스 수집을 구현한다. |
| PH2-007 | GitHub 수집 | GitHub Repository와 Release 수집을 구현한다. |
| PH2-008 | arXiv 수집 | 논문 수집과 요약 기반을 구현한다. |
| PH2-009 | Global Discovery | 트렌드 탐지와 후보 생성을 구현한다. |
| PH2-010 | 개인화 추천 | Personal Wiki 기반 추천을 구현한다. |
| PH2-011 | 번역 | 콘텐츠 다국어 번역 기능을 구현한다. |
| PH2-012 | 이미지 및 썸네일 | 생성 콘텐츠의 이미지 자료 기능을 구현한다. |
| PH2-013 | 관리자 운영 기능 | Prompt, Source, Job 운영 화면을 지원한다. |
| PH2-014 | 추천 피드백 반영 | 사용자 반응을 추천 점수에 반영한다. |
| PH2-015 | 콘텐츠 재생성 | 사용자와 관리자의 재생성 기능을 구현한다. |

## 46. 3차 개발 범위

| ID | 기능 | 설명 |
|---|---|---|
| PH3-001 | GDELT 수집 | 글로벌 이벤트 데이터 수집을 구현한다. |
| PH3-002 | DART 수집 | 기업 공시 데이터 수집을 구현한다. |
| PH3-003 | KRX 수집 | 시장과 종목 데이터 수집을 구현한다. |
| PH3-004 | SNS 수집 확장 | 지원하는 SNS Source를 확대한다. |
| PH3-005 | 고급 Trend Clustering | 다양한 Source의 이벤트를 정교하게 그룹화한다. |
| PH3-006 | 자체 API Key | 외부 개발자용 API Key 발급을 구현한다. |
| PH3-007 | External Agent API | 외부 시스템용 Agent API를 제공한다. |
| PH3-008 | MCP Server | 외부 Agent용 MCP 기능을 제공한다. |
| PH3-009 | Webhook | 비동기 작업 완료 Callback을 제공한다. |
| PH3-010 | 고급 Quota 관리 | 사용량과 플랜별 제한 정책을 고도화한다. |
| PH3-011 | 고급 비용 관리 | 사용자와 기능별 비용 통제를 고도화한다. |
| PH3-012 | Prompt A/B Test | Prompt 성능 비교 체계를 구현한다. |
| PH3-013 | 추천 A/B Test | 추천 알고리즘 비교 체계를 구현한다. |
| PH3-014 | 다중 LLM Provider 최적화 | 품질, 비용, 속도 기반 Provider 선택을 고도화한다. |
| PH3-015 | 고급 평가 Agent | 생성 콘텐츠의 자동 평가 기능을 고도화한다. |
