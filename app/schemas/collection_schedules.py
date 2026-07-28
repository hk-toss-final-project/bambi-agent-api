"""수집 스케줄 관리 API의 요청·응답 스키마.

Service가 Agent의 정기 수집 주기를 조정할 때 주고받는 모델을 정의한다
(SCH-017·018·019·020·022).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CollectionScheduleRegisterRequest(BaseModel):
    """수집 스케줄 등록 요청 (SCH-017)."""

    source_key: str = Field(
        min_length=1,
        max_length=128,
        description="Source 식별 Key. 같은 Key로 다시 등록하면 설정을 덮어쓴다",
        examples=["latest-naver"],
    )
    provider: str = Field(
        description="수집 Provider (naver, gdelt, newsapi)",
        examples=["naver"],
    )
    schedule_cron: str = Field(
        description="수집 주기 Cron 식 (UTC 기준)",
        examples=["0 */6 * * *"],
    )
    keywords: list[str] = Field(
        min_length=1,
        description=(
            "수집할 주제 목록. 각 키워드를 **따로** 검색하므로 주제를 한 문자열에 "
            "합치지 않는다"
        ),
        examples=[["코스피", "삼성전자"]],
    )
    display_name: str | None = Field(
        default=None, max_length=200, description="화면에 보일 이름"
    )
    language: str | None = Field(
        default=None, max_length=16, description="검색 언어 힌트", examples=["ko"]
    )
    limit_per_provider: int | None = Field(
        default=None, ge=1, le=100, description="한 번에 수집할 기사 수 (기본 10)"
    )
    daily_max_runs: int | None = Field(
        default=None,
        ge=1,
        description=(
            "하루 최대 수집 실행 횟수. 실행 1회 = 키워드 1개의 외부 API 호출 1회. "
            "무료 한도가 낮은 Provider는 반드시 설정한다"
        ),
    )


class CollectionScheduleUpdateRequest(BaseModel):
    """수집 스케줄 수정 요청 (SCH-018). 넘긴 항목만 변경한다."""

    schedule_cron: str | None = Field(
        default=None, description="새 수집 주기 Cron 식", examples=["0 * * * *"]
    )
    keywords: list[str] | None = Field(
        default=None, min_length=1, description="새 주제 목록 (각각 따로 수집)"
    )
    language: str | None = Field(
        default=None, max_length=16, description="새 검색 언어 힌트"
    )
    limit_per_provider: int | None = Field(
        default=None, ge=1, le=100, description="새 수집 기사 수"
    )
    daily_max_runs: int | None = Field(
        default=None, ge=1, description="새 일일 실행 한도"
    )


class CollectionScheduleResponse(BaseModel):
    """수집 스케줄 하나의 현재 상태."""

    source_key: str = Field(description="Source 식별 Key")
    provider: str = Field(description="수집 Provider")
    display_name: str = Field(description="화면에 보일 이름")
    status: str = Field(description="active(수집함) 또는 paused(중지)")
    schedule_cron: str = Field(description="수집 주기 Cron 식 (없으면 빈 문자열)")
    keywords: list[str] = Field(description="수집할 주제 목록")
    language: str | None = Field(description="검색 언어 힌트")
    limit_per_provider: int = Field(description="한 번에 수집할 기사 수")
    daily_max_runs: int | None = Field(description="하루 최대 실행 횟수 (없으면 무제한)")
    last_started_at: datetime | None = Field(description="마지막 수집 시작 시각")
    runs_today: int = Field(description="오늘 실행 횟수")
    next_run_at: datetime | None = Field(
        description="다음 실행 예정 시각. 한 번도 실행하지 않았으면 null(즉시 대상)"
    )
    cron_valid: bool = Field(
        description="Cron 식을 해석할 수 있는지 여부. false면 Scheduler가 건너뛴다"
    )


class CollectionRunResponse(BaseModel):
    """수집 실행 이력 한 건."""

    run_id: str = Field(description="실행 ID")
    source_key: str = Field(description="Source 식별 Key")
    query: str | None = Field(description="이번 실행에 사용한 검색어")
    status: str = Field(description="running·completed·partial·failed")
    fetched_count: int = Field(description="외부 API가 돌려준 기사 수")
    created_count: int = Field(description="새로 저장한 문서 수")
    duplicate_count: int = Field(description="이미 있어 건너뛴 문서 수")
    failed_count: int = Field(description="저장에 실패한 문서 수")
    error_code: str | None = Field(description="실패 원인 코드")
    started_at: datetime = Field(description="실행 시작 시각")
    completed_at: datetime | None = Field(description="실행 종료 시각")


class CollectionScheduleListResponse(BaseModel):
    """수집 스케줄 목록과 최근 실행 이력 (SCH-022)."""

    schedules: list[CollectionScheduleResponse] = Field(
        description="등록된 수집 스케줄 목록 (중지·주기 미설정 포함)"
    )
    recent_runs: list[CollectionRunResponse] = Field(
        description="최근 수집 실행 이력 (started_at 내림차순)"
    )
