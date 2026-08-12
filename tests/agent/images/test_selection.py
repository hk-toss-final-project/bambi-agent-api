"""실제 인용 출처 기반 리포트 대표 이미지 선택을 검증한다."""

import asyncio

from agent.images.api import ImageSelectionRequest, img_013, select_report_cover_image


def _asset(
    reference: str,
    *,
    namespace_key: str = "global",
    image_url: str = "https://cdn.example/cover.jpg",
) -> dict[str, object]:
    """테스트용 이미지 후보를 만든다."""
    return {
        "reference": reference,
        "namespace_key": namespace_key,
        "image_url": image_url,
        "source_url": f"https://news.example/{reference}",
        "source_title": f"출처 {reference}",
    }


def test_select_report_cover_image_uses_only_cited_source() -> None:
    """검색됐어도 실제 인용되지 않은 문서는 대표 이미지 후보가 아니다."""
    selected = select_report_cover_image(
        assets=[_asset("G1"), _asset("G2")],
        citation_references=["G2"],
        body="두 번째 자료를 사용한다 [G2]",
    )

    assert selected is not None
    assert selected.reference == "G2"


def test_select_report_cover_image_prefers_external_source() -> None:
    """개인 Wiki가 먼저 인용돼도 외부 기사 이미지가 있으면 이를 우선한다."""
    selected = select_report_cover_image(
        assets=[
            _asset("P1", namespace_key="user/1"),
            _asset("G1", namespace_key="global"),
        ],
        citation_references=["P1", "G1"],
        body="개인 맥락 [P1]과 최신 기사 [G1]",
    )

    assert selected is not None
    assert selected.reference == "G1"


def test_select_report_cover_image_rejects_unsafe_url() -> None:
    """data·javascript URL은 발행 대표 이미지가 될 수 없다."""
    selected = select_report_cover_image(
        assets=[_asset("G1", image_url="javascript:alert(1)")],
        citation_references=["G1"],
        body="본문 [G1]",
    )

    assert selected is None


def test_select_report_cover_image_skips_http_source_for_next_citation() -> None:
    """첫 인용 출처가 HTTP 이미지만 가지면 다음 인용 출처의 HTTPS 이미지를 쓴다."""
    selected = select_report_cover_image(
        assets=[
            _asset("G1", image_url="http://legacy.example/cover.jpg"),
            _asset("G2", image_url="https://cdn.example/next-cover.jpg"),
        ],
        citation_references=["G1", "G2"],
        body="첫 출처 [G1]와 다음 출처 [G2]를 함께 인용한다.",
    )

    assert selected is not None
    assert selected.reference == "G2"
    assert selected.url == "https://cdn.example/next-cover.jpg"


def test_select_report_cover_image_rejects_page_chrome_asset() -> None:
    """배너·아이콘 같은 사이트 UI 자산은 최종 발행 후보에서도 제외한다."""
    selected = select_report_cover_image(
        assets=[_asset("G1", image_url="https://menu.example/news/banner/ad.jpg")],
        citation_references=["G1"],
        body="본문 [G1]",
    )

    assert selected is None


def test_select_report_cover_image_rejects_ai_widget_icon() -> None:
    """AI 검색 위젯의 애니메이션 아이콘은 최종 커버 후보에서도 제외한다."""
    selected = select_report_cover_image(
        assets=[
            _asset(
                "G1",
                image_url="https://cdn.example/images/aichat/global_ani.png",
            )
        ],
        citation_references=["G1"],
        body="본문 [G1]",
    )

    assert selected is None


def test_img_013_returns_nullable_cover_payload() -> None:
    """IMG-013 facade는 선택 결과를 기존 FeatureResult 계약으로 반환한다."""
    result = asyncio.run(
        img_013(
            ImageSelectionRequest(
                assets=[_asset("L1", namespace_key="live-source")],
                citation_references=["L1"],
                body="본문 [L1]",
            )
        )
    )

    assert result.feature_id == "IMG-013"
    assert result.data["cover_image"]["reference"] == "L1"  # type: ignore[index]
