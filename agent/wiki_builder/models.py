"""개인 LLM Wiki Builder 값 객체의 하위 호환 재노출.

실제 정의는 shared.wiki_models로 이동했다. agent 계층 내부와 테스트가
기존 import 경로(agent.wiki_builder.models)를 유지할 수 있게 하는 shim이다.
"""

from shared.wiki_models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    GeneratedArtifact,
    InterestCandidate,
    WikiBuildPlan,
    WikiClassification,
    WikiDocumentPlan,
    WikiRelationPlan,
)

__all__ = [
    "ConceptClassification",
    "EntityClassification",
    "ExistingWikiEntry",
    "GeneratedArtifact",
    "InterestCandidate",
    "WikiBuildPlan",
    "WikiClassification",
    "WikiDocumentPlan",
    "WikiRelationPlan",
]
