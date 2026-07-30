"""개발 Seed 생성기의 사용자별 데이터 격리를 테스트한다."""

from scripts.generate_web_clipping_seed import (
    DEFAULT_INPUT_DIR,
    MOCK_USER_ID,
    SEED_USER_IDS,
    _seed_identifiers,
    load_clippings,
    render_seed,
)
from scripts.generate_user_url_seed import (
    DEFAULT_INPUT_PATH as USER_URL_INPUT_PATH,
    MOCK_USER_ID as USER_URL_MOCK_USER_ID,
    SEED_USER_IDS as USER_URL_SEED_USER_IDS,
    _user_deterministic_uuid as user_url_deterministic_uuid,
    render_seed as render_user_url_seed,
)

USER_URL = "https://n.news.naver.com/article/437/0000501311?cds=news_media_pc"


def test_web_clipping_seed_preserves_mock_ids_and_isolates_user_28() -> None:
    """기존 Mock UUID를 유지하면서 사용자 28에는 별도 UUID를 생성하는지 검증한다."""
    clipping = load_clippings(DEFAULT_INPUT_DIR)[0]
    mock_identifiers = _seed_identifiers(clipping, MOCK_USER_ID)
    user_28_identifiers = _seed_identifiers(clipping, "28")

    assert str(mock_identifiers.job_id) == "ecbd990d-fd2c-534b-b8ca-c4f6b147cfb5"
    mock_ids = {
        mock_identifiers.job_id,
        mock_identifiers.event_id,
        mock_identifiers.source_document_id,
        mock_identifiers.source_version_id,
    }
    user_28_ids = {
        user_28_identifiers.job_id,
        user_28_identifiers.event_id,
        user_28_identifiers.source_document_id,
        user_28_identifiers.source_version_id,
    }
    assert mock_ids.isdisjoint(user_28_ids)


def test_web_clipping_seed_renders_each_development_user_namespace() -> None:
    """웹 클리핑 Seed가 대상 사용자별 Row와 Namespace를 렌더링하는지 검증한다."""
    clipping = load_clippings(DEFAULT_INPUT_DIR)[0]
    rendered = render_seed([clipping], DEFAULT_INPUT_DIR)

    assert SEED_USER_IDS == (MOCK_USER_ID, "28")
    for user_id in SEED_USER_IDS:
        identifiers = _seed_identifiers(clipping, user_id)

        assert f"'{user_id}'" in rendered
        assert f"'user/{user_id}'" in rendered
        assert str(identifiers.job_id) in rendered
        assert str(identifiers.event_id) in rendered
        assert str(identifiers.source_document_id) in rendered
        assert str(identifiers.source_version_id) in rendered


def test_user_url_seed_preserves_mock_ids_and_isolates_user_28() -> None:
    """기존 URL Mock UUID를 유지하면서 사용자 28에는 별도 UUID를 생성하는지 검증한다."""
    mock_event_id = user_url_deterministic_uuid(
        "event", USER_URL, USER_URL_MOCK_USER_ID
    )
    user_28_event_id = user_url_deterministic_uuid("event", USER_URL, "28")

    assert str(mock_event_id) == "10060410-dddc-5eb4-81a6-f8a454e65b24"
    assert user_28_event_id != mock_event_id


def test_user_url_seed_renders_each_development_user_namespace() -> None:
    """사용자 URL Seed가 대상 사용자별 Event와 문서 Head를 렌더링하는지 검증한다."""
    rendered = render_user_url_seed([USER_URL], USER_URL_INPUT_PATH)

    assert USER_URL_SEED_USER_IDS == (USER_URL_MOCK_USER_ID, "28")
    for user_id in USER_URL_SEED_USER_IDS:
        event_id = user_url_deterministic_uuid("event", USER_URL, user_id)
        document_id = user_url_deterministic_uuid("document", USER_URL, user_id)

        assert f"'{user_id}'" in rendered
        assert f"'user/{user_id}'" in rendered
        assert str(event_id) in rendered
        assert str(document_id) in rendered
