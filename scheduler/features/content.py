"""기능 구현 모듈.

SCH-012 기능의 실제 구현 위치를 제공한다.

콘텐츠 생성 스케줄(구 SCH-011)은 service 계층 스케줄러가 사용자 지정
시각에 SVC-008 멱등 등록으로 담당하기로 결정되어 Agent 명세에서 제거했다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sch_012(request: FeatureRequest) -> FeatureResult:
    """[SCH-012] 추천 갱신 스케줄.

    사용자별 추천 후보 갱신 작업을 등록한다.
    """
    raise NotImplementedError("[SCH-012] 기능 구현이 필요합니다.")
