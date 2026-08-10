"""Service 개인 Wiki 원천 접수 기능 구현과 미구현 기능 Scaffold."""

from typing import Protocol

from app.schemas.mvp import (
    AcceptedJobResponse,
    ContentMarkDeletionRequest,
    ContentMarkRequest,
    FeedbackSignalsRequest,
    FeedbackSignalsResponse,
    UrlWikiSourceRequest,
    WebClippingRequest,
)
from shared.contracts import FeatureRequest, FeatureResult


class WikiSourceSubmissionService(Protocol):
    """개인 Wiki 원천 접수에 필요한 애플리케이션 서비스 경계."""

    async def submit_web_clipping(
        self, *, user_id: str, payload: WebClippingRequest, request_id: str
    ) -> AcceptedJobResponse:
        """웹 클리핑 원천을 Wiki 처리 작업으로 접수한다."""
        ...

    async def submit_url_source(
        self, *, user_id: str, payload: UrlWikiSourceRequest, request_id: str
    ) -> AcceptedJobResponse:
        """URL 원천을 Wiki 처리 작업으로 접수한다."""
        ...

    async def submit_content_mark(
        self, *, user_id: str, payload: ContentMarkRequest, request_id: str
    ) -> AcceptedJobResponse:
        """북마크한 리포트(작성자 무관)를 Wiki 처리 작업으로 접수한다."""
        ...

    async def delete_content_mark(
        self, *, user_id: str, payload: ContentMarkDeletionRequest, request_id: str
    ) -> AcceptedJobResponse:
        """북마크 원본 연결 해제와 Wiki 재구성을 접수한다."""
        ...

    async def submit_feedback_signals(
        self, *, user_id: str, payload: FeedbackSignalsRequest, request_id: str
    ) -> FeedbackSignalsResponse:
        """행동 신호 Batch를 관심사 반영 이벤트로 접수한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_002(
    service: WikiSourceSubmissionService,
    *,
    user_id: str,
    payload: WebClippingRequest,
    request_id: str,
) -> AcceptedJobResponse:
    """[SVC-002] 웹 클리핑 처리 요청.

    클리핑 데이터를 개인 Wiki 처리 작업으로 전달한다.
    """
    return await service.submit_web_clipping(
        user_id=user_id, payload=payload, request_id=request_id
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_003(
    service: WikiSourceSubmissionService,
    *,
    user_id: str,
    payload: UrlWikiSourceRequest,
    request_id: str,
) -> AcceptedJobResponse:
    """[SVC-003] URL 처리 요청.

    입력된 URL을 개인 Wiki 처리 작업으로 전달한다.
    """
    return await service.submit_url_source(
        user_id=user_id, payload=payload, request_id=request_id
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_004(
    service: WikiSourceSubmissionService,
    *,
    user_id: str,
    payload: ContentMarkRequest,
    request_id: str,
) -> AcceptedJobResponse:
    """[SVC-004] 북마크(위키마킹) 처리 요청.

    사용자가 북마크한 리포트의 Wiki 편입을 요청한다. 내 리포트와 피드에서 본
    다른 사용자의 리포트를 구분하지 않고 content_id로 동일하게 편입한다.
    """
    return await service.submit_content_mark(
        user_id=user_id, payload=payload, request_id=request_id
    )


async def svc_004_delete(
    service: WikiSourceSubmissionService,
    *,
    user_id: str,
    payload: ContentMarkDeletionRequest,
    request_id: str,
) -> AcceptedJobResponse:
    """[SVC-004] 북마크 해제 후 활성 원본 기준 Wiki 재구성을 요청한다."""
    return await service.delete_content_mark(
        user_id=user_id, payload=payload, request_id=request_id
    )


async def svc_005(request: FeatureRequest) -> FeatureResult:
    """[SVC-005] 콘텐츠 상호작용 전달.

    콘텐츠와의 대화와 수정 결과를 전달한다.
    """
    raise NotImplementedError("[SVC-005] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_006(
    service: WikiSourceSubmissionService,
    *,
    user_id: str,
    payload: FeedbackSignalsRequest,
    request_id: str,
) -> FeedbackSignalsResponse:
    """[SVC-006] 사용자 피드백 전달.

    좋아요, 숨김, 신고 등의 신호를 전달하고 관심사 재계산을 시도한다.
    """
    return await service.submit_feedback_signals(
        user_id=user_id, payload=payload, request_id=request_id
    )


async def svc_007(request: FeatureRequest) -> FeatureResult:
    """[SVC-007] 개인 Wiki 재구성 요청.

    특정 사용자의 Wiki 재구성을 요청한다.
    """
    raise NotImplementedError("[SVC-007] 기능 구현이 필요합니다.")
