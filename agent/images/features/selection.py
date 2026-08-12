"""실제 인용 출처 중 리포트 대표 이미지를 결정론적으로 선택한다."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from infrastructure.sources.connectors.api import is_secure_content_image_url
from shared.contracts import FeatureResult

_CITATION_REFERENCE = re.compile(r"\[([PGL]\d+)\]")


@dataclass(frozen=True, slots=True)
class ReportCoverImage:
    """리포트 상단 이미지와 원문 출처를 함께 보존하는 값 객체."""

    url: str
    source_url: str
    source_title: str
    reference: str

    def to_payload(self) -> dict[str, str]:
        """발행 Snapshot에 바로 넣을 수 있는 JSON 객체로 변환한다."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ImageSelectionRequest:
    """대표 이미지 선택 기능의 형식화된 입력."""

    assets: Sequence[Mapping[str, object]]
    citation_references: Sequence[str]
    body: str


def _http_url(value: object) -> str | None:
    """값이 절대 HTTP(S) URL일 때만 공백을 정리해 반환한다."""
    text = str(value or "").strip()
    if not text or len(text) > 2048:
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return text


def _ordered_references(body: str, citation_references: Sequence[str]) -> list[str]:
    """본문 첫 등장 순서 뒤에 명시 Citation 순서를 붙여 중복 제거한다."""
    ordered: list[str] = []
    for reference in [*_CITATION_REFERENCE.findall(body), *citation_references]:
        value = str(reference).strip()
        if value and value not in ordered:
            ordered.append(value)
    return ordered


def select_report_cover_image(
    *,
    assets: Sequence[Mapping[str, object]],
    citation_references: Sequence[str],
    body: str,
) -> ReportCoverImage | None:
    """리포트가 실제로 인용한 출처 중 대표 이미지 한 건을 고른다.

    본문에서 먼저 언급된 Citation 순서를 기준으로 하되 Global·Live 외부 자료를
    개인 Wiki보다 우선한다. 이미지 URL과 원문 URL이 모두 유효해야 하며, 후보가
    없으면 리포트 생성은 그대로 진행하고 ``None``을 반환한다.

    Args:
        assets: reference·namespace_key·image_url·source_url·source_title 후보
        citation_references: 생성 결과가 검증한 실제 Citation 참조
        body: Citation 첫 등장 순서를 계산할 리포트 Markdown 본문

    Returns:
        선택된 대표 이미지와 출처. 적합한 후보가 없으면 ``None``
    """
    used = set(citation_references)
    assets_by_reference = {
        str(asset.get("reference") or ""): asset
        for asset in assets
        if str(asset.get("reference") or "") in used
    }
    ordered_assets = [
        assets_by_reference[reference]
        for reference in _ordered_references(body, citation_references)
        if reference in assets_by_reference
    ]
    external = [
        asset
        for asset in ordered_assets
        if str(asset.get("namespace_key") or "") in {"global", "live-source"}
    ]
    for asset in [*external, *ordered_assets]:
        image_url = _http_url(asset.get("image_url"))
        source_url = _http_url(asset.get("source_url"))
        reference = str(asset.get("reference") or "").strip()
        if (
            image_url is None
            or not is_secure_content_image_url(image_url)
            or source_url is None
            or not reference
        ):
            continue
        return ReportCoverImage(
            url=image_url,
            source_url=source_url,
            source_title=str(asset.get("source_title") or source_url).strip(),
            reference=reference,
        )
    return None


# MVP: 발행 Snapshot의 실제 인용 출처 대표 이미지를 결정적으로 선택한다.
async def img_013(request: ImageSelectionRequest) -> FeatureResult:
    """[IMG-013] 대표 이미지 선택.

    여러 Asset 중 실제 인용된 외부 출처의 대표 이미지를 선택한다.
    """
    selected = select_report_cover_image(
        assets=request.assets,
        citation_references=request.citation_references,
        body=request.body,
    )
    return FeatureResult(
        feature_id="IMG-013",
        data={"cover_image": selected.to_payload() if selected else None},
    )
