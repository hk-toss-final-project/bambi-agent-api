"""디자인 시안 페이지(/dev/design) 라우터 검증.

시안은 정적 HTML이라 DB·LLM·네트워크 없이 열려야 한다. 레지스트리에 등록한
템플릿 파일이 실제로 존재하는지, 외부 CDN 의존이 새로 들어오지 않았는지
(오프라인·사내망에서도 렌더돼야 한다), 개발 API가 꺼진 환경에서 노출되지
않는지를 확인한다.
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routers.development.design_views import (
    _TEMPLATE_DIR,
    get_design_page,
    list_design_pages,
)


def _dev_client() -> TestClient:
    """개발 라우터가 활성화된 TestClient를 만든다."""
    return TestClient(create_app(Settings(environment="test", enable_dev_agent_api=True)))


def test_registered_templates_exist_and_are_self_contained() -> None:
    """등록된 시안의 템플릿 파일이 존재하고 외부 리소스를 참조하지 않아야 한다."""
    pages = list_design_pages()
    assert pages, "시안이 하나도 등록되지 않았다"

    for page in pages:
        path = _TEMPLATE_DIR / page.template
        assert path.exists(), f"{page.slug}: 템플릿 파일이 없다 ({page.template})"
        markup = path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in markup, f"{page.slug}: 단독으로 열 수 있는 문서가 아니다"
        # 사내망·오프라인에서도 그대로 렌더돼야 하므로 외부 호스트를 참조하면 안 된다.
        for forbidden in ("http://", "https://cdn", "//cdn."):
            assert forbidden not in markup, f"{page.slug}: 외부 리소스 참조({forbidden})"


def test_design_index_lists_every_registered_page() -> None:
    """목록 페이지가 등록된 시안을 모두 링크해야 한다."""
    response = _dev_client().get("/dev/design")

    assert response.status_code == 200
    body = response.text
    for page in list_design_pages():
        assert f"/dev/design/{page.slug}" in body
        assert page.title in body


def test_design_page_returns_template_html() -> None:
    """시안 상세가 템플릿 HTML을 그대로 반환해야 한다."""
    response = _dev_client().get("/dev/design/interest-feedback")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "이거 말고" in response.text


def test_unknown_design_page_returns_404() -> None:
    """등록되지 않은 slug는 404로 응답해야 한다."""
    response = _dev_client().get("/dev/design/nope")

    assert response.status_code == 404
    assert response.json()["code"] == "DESIGN_PAGE_NOT_FOUND"


def test_get_design_page_returns_none_for_unknown_slug() -> None:
    """레지스트리 조회는 없는 slug에 None을 반환한다."""
    assert get_design_page("nope") is None
    assert get_design_page("interest-feedback") is not None


def test_design_pages_hidden_when_dev_api_disabled() -> None:
    """개발 API가 꺼진 환경에서는 시안 경로가 열리면 안 된다."""
    client = TestClient(create_app(Settings(environment="test")))

    assert client.get("/dev/design").status_code == 404
