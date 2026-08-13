"""개인 Wiki Source Event 수신 기능."""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.schemas.mvp import WebClippingRequest


@dataclass(frozen=True, slots=True)
class OnboardingSeedDocument:
    """온보딩 선택에서 합성한 개인 Wiki 시드 문서.

    Attributes:
        source_event_id: 선택 내용으로 만든 멱등 이벤트 ID (같은 선택이면 같은 값)
        title: 시드 원본 문서 제목
        content: LLM Wiki Build가 읽을 Frontmatter 포함 Markdown 본문
        topics: 합성에 사용한 관심 주제 라벨 목록
        metadata: 안정 ID·taxonomy 버전 등 근거 메타데이터
    """

    source_event_id: str
    title: str
    content: str
    topics: tuple[str, ...]
    metadata: dict[str, object]


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wse_001(payload: WebClippingRequest) -> WebClippingRequest:
    """[WSE-001] 웹 클리핑 이벤트 수신.

    사용자가 클리핑한 데이터를 개인 Wiki 반영 후보로 수신한다.
    """
    if not payload.content.strip():
        raise ValueError("WSE-001 웹 클리핑 본문은 비어 있을 수 없습니다.")
    return payload


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wse_014(
    signup_interests: Sequence[Mapping[str, object]],
    *,
    interest_taxonomy_version: str | None = None,
    selected_category_ids: Sequence[str] = (),
    selected_topic_ids: Sequence[str] = (),
    preferred_language: str = "ko",
) -> OnboardingSeedDocument | None:
    """[WSE-014] 온보딩 관심사 시드 수신.

    회원가입 온보딩에서 고른 Category·Topic을 개인 Wiki 반영 후보인 시드
    Markdown 문서로 결정론적으로 합성한다. 실제 저장 근거가 아직 없는 신규
    사용자의 콜드스타트를 위해, 이 시드를 기존 Wiki Build 파이프라인에 태워
    Entity·Concept 노드를 만들고 관심사 프로필(INT-011)이 파생되게 한다. 시드는
    실제 저장 근거보다 낮은 가중치를 받으므로(INT-005) 저장이 쌓이면 자연히 밀린다.

    Args:
        signup_interests: `category`(문자열)와 `topics`(문자열 목록)를 담은 온보딩 선택 묶음
        interest_taxonomy_version: 선택 ID를 해석할 관심사 분류체계 버전
        selected_category_ids: 온보딩에서 고른 Category 안정 ID 목록
        selected_topic_ids: 온보딩에서 고른 Topic 안정 ID 목록
        preferred_language: 사용자 추가 키워드 컨텍스트 생성 언어

    Returns:
        합성한 시드 문서. 유효한 선택이 없으면 None.
    """
    groups: list[tuple[str, tuple[str, ...]]] = []
    labels: list[str] = []
    custom_labels: list[str] = []
    for interest in signup_interests:
        category = str(interest.get("category") or "").strip()
        raw_topics = interest.get("topics")
        topics = tuple(
            topic
            for item in (raw_topics if isinstance(raw_topics, (list, tuple)) else ())
            if (topic := str(item).strip())
        )
        if not category and not topics:
            continue
        groups.append((category, topics))
        labels.extend(topics or ([category] if category else []))
        if not category:
            custom_labels.extend(topics)
    if not groups:
        return None

    # 선택 내용으로 멱등 키를 만든다 — 같은 선택은 같은 시드, 바뀌면 새 시드.
    checksum_source = "|".join(
        [
            interest_taxonomy_version or "",
            preferred_language,
            "onboarding-context-v1",
            *(f"{category}>{','.join(topics)}" for category, topics in groups),
            *selected_category_ids,
            *selected_topic_ids,
        ]
    )
    checksum = hashlib.sha256(checksum_source.encode("utf-8")).hexdigest()[:16]
    source_event_id = f"onboarding-seed:{checksum}"

    title = "온보딩 관심 주제 시드"
    body_lines = [
        "---",
        "source: onboarding_seed",
        f"taxonomy_version: {interest_taxonomy_version or ''}",
        "---",
        "",
        f"# {title}",
        "",
        "사용자가 회원가입 온보딩에서 아래 주제에 관심이 있다고 선택했다.",
        "",
    ]
    for category, topics in groups:
        heading = category or topics[0]
        body_lines.append(f"## {heading}")
        if category and topics:
            body_lines.append(f"- 세부 관심 주제: {', '.join(topics)}")
        body_lines.append("")
    content = "\n".join(body_lines).strip() + "\n"

    metadata: dict[str, object] = {
        "seed": True,
        "interest_taxonomy_version": interest_taxonomy_version,
        "selected_category_ids": list(selected_category_ids),
        "selected_topic_ids": list(selected_topic_ids),
        "labels": labels,
        "custom_labels": custom_labels,
        "preferred_language": preferred_language,
        "context_contract_version": 1,
    }
    return OnboardingSeedDocument(
        source_event_id=source_event_id,
        title=title,
        content=content,
        topics=tuple(labels),
        metadata=metadata,
    )
