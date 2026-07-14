"""시청 이력 저장소(history) 검증. 실제 데이터 파일을 건드리지 않도록 임시 경로를 쓴다."""

from agent.assistant import history


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
