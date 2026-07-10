"""Agent Worker 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_001(request: FeatureRequest) -> FeatureResult:
    """[WORKER-001] Global Source Collector Worker.

    외부 데이터를 수집하고 Global Source Pool에 저장한다.
    """
    raise NotImplementedError("[WORKER-001] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_002(request: FeatureRequest) -> FeatureResult:
    """[WORKER-002] Personal Wiki Builder Worker.

    사용자 선택 데이터를 개인 Wiki로 구성한다.
    """
    raise NotImplementedError("[WORKER-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_003(request: FeatureRequest) -> FeatureResult:
    """[WORKER-003] Bambi Generation Worker.

    개인화 콘텐츠를 생성한다.
    """
    raise NotImplementedError("[WORKER-003] 기능 구현이 필요합니다.")


async def worker_004(request: FeatureRequest) -> FeatureResult:
    """[WORKER-004] Content Quality Worker.

    생성 콘텐츠의 품질과 안전성을 평가한다.
    """
    raise NotImplementedError("[WORKER-004] 기능 구현이 필요합니다.")


async def worker_005(request: FeatureRequest) -> FeatureResult:
    """[WORKER-005] Summary Worker.

    요약 작업을 수행한다.
    """
    raise NotImplementedError("[WORKER-005] 기능 구현이 필요합니다.")


async def worker_006(request: FeatureRequest) -> FeatureResult:
    """[WORKER-006] Translation Worker.

    번역 작업을 수행한다.
    """
    raise NotImplementedError("[WORKER-006] 기능 구현이 필요합니다.")


async def worker_007(request: FeatureRequest) -> FeatureResult:
    """[WORKER-007] Media Worker.

    이미지와 시각 자료를 생성한다.
    """
    raise NotImplementedError("[WORKER-007] 기능 구현이 필요합니다.")


async def worker_008(request: FeatureRequest) -> FeatureResult:
    """[WORKER-008] Recommendation Worker.

    사용자별 추천 후보를 생성한다.
    """
    raise NotImplementedError("[WORKER-008] 기능 구현이 필요합니다.")


async def worker_009(request: FeatureRequest) -> FeatureResult:
    """[WORKER-009] Embedding Worker.

    문서와 Chunk의 Embedding을 생성한다.
    """
    raise NotImplementedError("[WORKER-009] 기능 구현이 필요합니다.")


async def worker_010(request: FeatureRequest) -> FeatureResult:
    """[WORKER-010] Reindex Worker.

    Embedding 모델 변경 시 재색인한다.
    """
    raise NotImplementedError("[WORKER-010] 기능 구현이 필요합니다.")


async def worker_011(request: FeatureRequest) -> FeatureResult:
    """[WORKER-011] Cleanup Worker.

    만료 데이터와 오래된 로그를 정리한다.
    """
    raise NotImplementedError("[WORKER-011] 기능 구현이 필요합니다.")


async def worker_012(request: FeatureRequest) -> FeatureResult:
    """[WORKER-012] Event Publisher Worker.

    Outbox 이벤트를 Integration Event Bus로 발행한다.
    """
    raise NotImplementedError("[WORKER-012] 기능 구현이 필요합니다.")
