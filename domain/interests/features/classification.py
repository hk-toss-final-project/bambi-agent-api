"""기능 구현 모듈.

INT-002 기능의 실제 구현 위치를 제공한다.

**INT-002는 MVP 범위에서 제외됐다 (2026-08-04 팀 결정).** Category는 온보딩에서
신규 사용자의 관심 방향을 대략 파악하는 용도이며, Wiki에서 추출한 관심 Topic을
다시 Category로 묶을 필요는 없다는 결론이다. 사유와 실측 근거는
`docs/agent-api-mvp-scope.md` §3 참고.

스텁은 향후 재도입에 대비해 유지한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def int_002(request: FeatureRequest) -> FeatureResult:
    """[INT-002] 관심사 Category 분류.

    관심사를 서비스의 분류 체계에 매핑한다.
    """
    raise NotImplementedError("[INT-002] 기능 구현이 필요합니다.")
