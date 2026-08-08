<!-- 현행 개발 문서와 보관 문서의 경계를 안내하는 문서. -->

# 문서 안내

`docs/` 루트에는 현재 구현의 기준이거나 아직 결정이 필요한 문서만 둡니다.
완료된 구현 계획, 특정 시점의 코드 리뷰, 일회성 검증 절차는
[`archive/`](archive/README.md)에 보관합니다.

## 현행 기준 문서

| 구분 | 문서 | 역할 |
|---|---|---|
| 기능 | [Agent API 기능 명세](agent-api-feature-spec.md) | 기능 ID와 전체 범위의 기준 |
| 범위 | [Agent API MVP 개발 범위](agent-api-mvp-scope.md) | MVP 대상과 구현 현황 |
| API | [FastAPI MVP API](fastapi-mvp-api.md) | 요청·응답 및 처리 흐름 계약 |
| 구조 | [프로젝트 구조](project-structure.md) | 기능 ID와 패키지·facade 매핑 |
| 연동 | [Service 연동 가이드](service-integration-guide.md) | service-api·service-worker 호출 계약 |
| 연동 | [Agent 연동 계약 & Gateway 설계](agent-contract.md) | 외부 팀 협의 사항과 남은 결정 |
| DB | [Agent DB 설계](agent-db-design.md) | 데이터 경계와 운영 원칙 |
| DB | [Agent DB 테이블 카탈로그](agent-db-table-catalog.md) | 테이블 책임과 관계 |
| DB | [Agent DB 컬럼 사전](agent-db-column-dictionary.md) | 물리 컬럼 계약 |

## 검토·결정 중인 설계

| 문서 | 현재 성격 |
|---|---|
| [LLM Wiki Vault 구조](llm-wiki-vault-structure.md) | 관찰 기반 산출물 형식과 구현 차이 |
| [LLM Wiki Builder P0~P3 개선](wiki-builder-p0-p3-improvement.md) | 후보 회수·Relation Linker·관계 이력·Lint·Embedding·Graph Gate 구현 기준과 운영 한계 |
| [Wiki 그래프 기반 검색어 확장](wiki-graph-query-expansion.md) | 기존 1-hop 실측과 품질 Gate 기반 2-hop PPR 운영 계약 |
| [지식 파이프라인·관심사·구독](wiki-interest-subscription-design.md) | 팀 결정이 남은 데이터 흐름 설계 |
| [비서 UI 제거 안내](assistant-ui-removal.md) | 제거 시점이 남은 정리 계획 |
| [관심사 범주 묶음 리포트](interest-bundle-report-design.md) | 구현 승인된 활성 관심사·Wiki 1홉 기반 리포트 설계 |

## 정리 기준

- 완료된 작업의 계획서·인수인계 메모는 구현 기준으로 사용하지 않고 보관합니다.
- 날짜가 고정된 리뷰와 실측 자료는 해당 시점의 기록으로 보관합니다.
- 특정 브랜치·테스트 수에 의존하는 일회성 검증서는 보관합니다.
- 현행 계약이나 미결정 사항이 남은 문서는 루트에 유지합니다.
