"""모든 API 영역에서 재사용하는 공통 요청과 응답 스키마."""

from pydantic import BaseModel, Field


class RequestContextSchema(BaseModel):
    """내부 요청의 호출 주체와 추적 정보를 담는 스키마."""

    request_id: str = Field(description="요청을 식별하는 고유 ID")
    trace_id: str | None = Field(
        default=None, description="분산 추적에 사용하는 Trace ID"
    )
    actor_id: str | None = Field(default=None, description="호출 주체 식별자")
    user_id: str | None = Field(default=None, description="기능 대상 사용자 식별자")


class FeatureRequestSchema(BaseModel):
    """상세 스키마 확정 전 기능 호출에 사용하는 공통 요청 모델."""

    context: RequestContextSchema = Field(description="요청 공통 컨텍스트")
    payload: dict[str, object] = Field(
        default_factory=dict, description="기능별 입력 데이터"
    )


class FeatureResponseSchema(BaseModel):
    """상세 스키마 확정 전 기능 결과에 사용하는 공통 응답 모델."""

    feature_id: str = Field(description="실행한 명세 기능 ID")
    data: dict[str, object] = Field(
        default_factory=dict, description="기능별 결과 데이터"
    )


class ErrorResponseSchema(BaseModel):
    """API 전역에서 사용하는 공통 오류 응답 모델."""

    code: str = Field(description="프로그램에서 식별 가능한 오류 코드")
    message: str = Field(description="사용자에게 전달할 안전한 오류 메시지")
    request_id: str | None = Field(default=None, description="오류가 발생한 요청 ID")
    retryable: bool = Field(default=False, description="동일 요청의 재시도 가능 여부")
    details: list[dict[str, object]] = Field(
        default_factory=list, description="검증 실패 등 세부 오류 목록"
    )
