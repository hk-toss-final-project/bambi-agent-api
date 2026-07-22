"""Wiki Build 계획 정규화 기능과 미구현 문서 처리 Scaffold."""

from collections.abc import Sequence

from agent.wiki_builder.features.planning import build_wiki_plan
from agent.wiki_builder.models import WikiClassification
from shared.contracts import FeatureRequest, FeatureResult
from shared.wiki_models import ExistingWikiEntry, WikiBuildPlan, WikiRelationPlan


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_003(
    *,
    source_title: str,
    source_url: str | None,
    source_tags: Sequence[str],
    source_content_hash: str,
    source_size_bytes: int,
    classification: WikiClassification,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
    generated_at: str,
    model: str,
    existing_relations: Sequence[WikiRelationPlan] = (),
) -> WikiBuildPlan:
    """[WBA-003] Wiki 문서 정규화.

    입력 데이터를 개인 Wiki 문서 구조로 정리한다.
    """
    return build_wiki_plan(
        source_title=source_title,
        source_url=source_url,
        source_tags=source_tags,
        source_content_hash=source_content_hash,
        source_size_bytes=source_size_bytes,
        classification=classification,
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
        generated_at=generated_at,
        model=model,
        existing_relations=existing_relations,
    )


async def wba_004(request: FeatureRequest) -> FeatureResult:
    """[WBA-004] Wiki 문서 중복 제거.

    동일하거나 유사한 사용자 지식을 제거한다.
    """
    raise NotImplementedError("[WBA-004] 기능 구현이 필요합니다.")


async def wba_005(request: FeatureRequest) -> FeatureResult:
    """[WBA-005] Wiki 문서 병합.

    관련 문서와 메모를 하나의 지식으로 통합한다.
    """
    raise NotImplementedError("[WBA-005] 기능 구현이 필요합니다.")
