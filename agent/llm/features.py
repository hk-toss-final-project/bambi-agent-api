"""LLM 공통 기능 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_001(request: FeatureRequest) -> FeatureResult:
    """[LLM-001] Text Completion.

    일반 텍스트 생성 요청을 처리한다.
    """
    raise NotImplementedError("[LLM-001] 기능 구현이 필요합니다.")


async def llm_002(request: FeatureRequest) -> FeatureResult:
    """[LLM-002] Chat Completion.

    대화형 생성 요청을 처리한다.
    """
    raise NotImplementedError("[LLM-002] 기능 구현이 필요합니다.")


async def llm_003(request: FeatureRequest) -> FeatureResult:
    """[LLM-003] Structured Output.

    정해진 Schema 형식으로 결과를 생성한다.
    """
    raise NotImplementedError("[LLM-003] 기능 구현이 필요합니다.")


async def llm_004(request: FeatureRequest) -> FeatureResult:
    """[LLM-004] Tool Calling.

    Wiki 검색과 외부 도구 호출을 수행한다.
    """
    raise NotImplementedError("[LLM-004] 기능 구현이 필요합니다.")


async def llm_005(request: FeatureRequest) -> FeatureResult:
    """[LLM-005] Function Calling.

    정의된 내부 함수를 호출하고 결과를 활용한다.
    """
    raise NotImplementedError("[LLM-005] 기능 구현이 필요합니다.")


async def llm_006(request: FeatureRequest) -> FeatureResult:
    """[LLM-006] 모델 라우팅.

    작업 성격과 플랜에 맞는 모델을 선택한다.
    """
    raise NotImplementedError("[LLM-006] 기능 구현이 필요합니다.")


async def llm_007(request: FeatureRequest) -> FeatureResult:
    """[LLM-007] Provider 라우팅.

    사용 가능한 LLM Provider를 선택한다.
    """
    raise NotImplementedError("[LLM-007] 기능 구현이 필요합니다.")


async def llm_008(request: FeatureRequest) -> FeatureResult:
    """[LLM-008] Fallback 모델.

    주 모델 실패 시 대체 모델을 사용한다.
    """
    raise NotImplementedError("[LLM-008] 기능 구현이 필요합니다.")


async def llm_009(request: FeatureRequest) -> FeatureResult:
    """[LLM-009] Token Budget 관리.

    작업과 플랜별 Token 사용량을 제한한다.
    """
    raise NotImplementedError("[LLM-009] 기능 구현이 필요합니다.")


async def llm_010(request: FeatureRequest) -> FeatureResult:
    """[LLM-010] Context Builder.

    개인 Wiki와 Global Source Context를 구성한다.
    """
    raise NotImplementedError("[LLM-010] 기능 구현이 필요합니다.")


async def llm_011(request: FeatureRequest) -> FeatureResult:
    """[LLM-011] Citation Builder.

    생성 결과와 사용한 출처를 연결한다.
    """
    raise NotImplementedError("[LLM-011] 기능 구현이 필요합니다.")


async def llm_012(request: FeatureRequest) -> FeatureResult:
    """[LLM-012] 응답 캐싱.

    재사용 가능한 LLM 결과를 캐시한다.
    """
    raise NotImplementedError("[LLM-012] 기능 구현이 필요합니다.")


async def llm_013(request: FeatureRequest) -> FeatureResult:
    """[LLM-013] 호출 Retry.

    일시적인 Provider 오류를 재시도한다.
    """
    raise NotImplementedError("[LLM-013] 기능 구현이 필요합니다.")


async def llm_014(request: FeatureRequest) -> FeatureResult:
    """[LLM-014] 호출 Timeout.

    LLM 요청의 최대 실행 시간을 제한한다.
    """
    raise NotImplementedError("[LLM-014] 기능 구현이 필요합니다.")


async def llm_015(request: FeatureRequest) -> FeatureResult:
    """[LLM-015] 사용량 기록.

    모델 호출량과 Token 사용량을 기록한다.
    """
    raise NotImplementedError("[LLM-015] 기능 구현이 필요합니다.")


async def llm_016(request: FeatureRequest) -> FeatureResult:
    """[LLM-016] 비용 기록.

    Provider와 작업별 예상 비용을 기록한다.
    """
    raise NotImplementedError("[LLM-016] 기능 구현이 필요합니다.")


async def llm_017(request: FeatureRequest) -> FeatureResult:
    """[LLM-017] 안전성 검사.

    입력과 출력의 정책 위반 여부를 확인한다.
    """
    raise NotImplementedError("[LLM-017] 기능 구현이 필요합니다.")


async def llm_018(request: FeatureRequest) -> FeatureResult:
    """[LLM-018] Prompt Injection 방어.

    외부 문서의 명령을 시스템 지시와 분리한다.
    """
    raise NotImplementedError("[LLM-018] 기능 구현이 필요합니다.")


async def llm_019(request: FeatureRequest) -> FeatureResult:
    """[LLM-019] Provider 추상화.

    Provider 교체가 가능하도록 공통 인터페이스를 제공한다.
    """
    raise NotImplementedError("[LLM-019] 기능 구현이 필요합니다.")
