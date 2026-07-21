"""노출 이력 저장소(history) 검증. 실제 데이터 파일을 건드리지 않도록 임시 경로를 쓴다."""

from agent.assistant.features import history


def test_record_and_get_watched_ids(tmp_path, monkeypatch) -> None:
    """기록한 영상 ID가 조회에 그대로 나온다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "watch_history.json")

    assert history.get_watched_video_ids("minji", "전고체 배터리") == set()
    assert history.has_watch_history("minji", "전고체 배터리") is False

    history.record_watch("minji", "전고체 배터리", "v1", "제목1", "https://youtu.be/v1")
    history.record_watch("minji", "전고체 배터리", "v2", "제목2", "https://youtu.be/v2")

    watched = history.get_watched_video_ids("minji", "전고체 배터리")
    assert watched == {"v1", "v2"}
    assert history.has_watch_history("minji", "전고체 배터리") is True


def test_history_is_isolated_per_user_and_keyword(tmp_path, monkeypatch) -> None:
    """다른 사용자·다른 키워드의 시청 이력은 서로 섞이지 않는다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "watch_history.json")

    history.record_watch("minji", "전고체 배터리", "v1", "제목", "url")
    history.record_watch("yuri", "전고체 배터리", "v2", "제목", "url")
    history.record_watch("minji", "양자컴퓨터", "v3", "제목", "url")

    assert history.get_watched_video_ids("minji", "전고체 배터리") == {"v1"}
    assert history.get_watched_video_ids("yuri", "전고체 배터리") == {"v2"}
    assert history.get_watched_video_ids("minji", "양자컴퓨터") == {"v3"}


def test_keyword_lookup_is_case_and_space_insensitive(tmp_path, monkeypatch) -> None:
    """대소문자·공백 차이가 있어도 같은 키워드로 인식한다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "watch_history.json")

    history.record_watch("minji", "  Solid State Battery  ", "v1", "제목", "url")

    assert history.get_watched_video_ids("minji", "solid state battery") == {"v1"}


def test_record_watch_ignores_missing_ids(tmp_path, monkeypatch) -> None:
    """user_id나 video_id가 없으면 아무것도 기록하지 않는다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "watch_history.json")

    history.record_watch("", "키워드", "v1", "제목", "url")
    history.record_watch("minji", "키워드", "", "제목", "url")

    assert not (tmp_path / "watch_history.json").exists()


def test_record_and_get_reported_article_keys(tmp_path, monkeypatch) -> None:
    """기록한 기사 정규 URL이 조회에 그대로 나온다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_ARTICLE_HISTORY_PATH", tmp_path / "article_history.json")

    assert history.get_reported_article_keys("minji", "코스피") == set()

    history.record_reported_article("minji", "코스피", "https://a.com/1", "기사1", "https://a.com/1?utm=x")
    history.record_reported_article("minji", "코스피", "https://b.com/2", "기사2", "https://b.com/2")

    assert history.get_reported_article_keys("minji", "코스피") == {"https://a.com/1", "https://b.com/2"}


def test_article_history_is_isolated_per_user_and_keyword(tmp_path, monkeypatch) -> None:
    """다른 사용자·다른 키워드의 기사 보고 이력은 서로 섞이지 않는다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_ARTICLE_HISTORY_PATH", tmp_path / "article_history.json")

    history.record_reported_article("minji", "코스피", "https://a.com/1", "제목", "url")
    history.record_reported_article("yuri", "코스피", "https://b.com/2", "제목", "url")
    history.record_reported_article("minji", "환율", "https://c.com/3", "제목", "url")

    assert history.get_reported_article_keys("minji", "코스피") == {"https://a.com/1"}
    assert history.get_reported_article_keys("yuri", "코스피") == {"https://b.com/2"}
    assert history.get_reported_article_keys("minji", "환율") == {"https://c.com/3"}


def test_article_history_does_not_touch_watch_history(tmp_path, monkeypatch) -> None:
    """기사 보고 이력은 시청 이력과 별도 파일에 저장된다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "watch_history.json")
    monkeypatch.setattr(history, "_ARTICLE_HISTORY_PATH", tmp_path / "article_history.json")

    history.record_reported_article("minji", "코스피", "https://a.com/1", "제목", "url")

    assert (tmp_path / "article_history.json").exists()
    assert not (tmp_path / "watch_history.json").exists()


def test_record_reported_article_ignores_missing_ids(tmp_path, monkeypatch) -> None:
    """user_id나 url_key가 없으면 아무것도 기록하지 않는다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_ARTICLE_HISTORY_PATH", tmp_path / "article_history.json")

    history.record_reported_article("", "키워드", "https://a.com/1", "제목", "url")
    history.record_reported_article("minji", "키워드", "", "제목", "url")

    assert not (tmp_path / "article_history.json").exists()
