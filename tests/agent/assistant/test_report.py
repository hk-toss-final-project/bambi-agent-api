"""개인화 보고서 생성(report) 검증. 실제 LLM은 호출하지 않는다."""

from agent.assistant import report


def test_build_report_context_fills_defaults() -> None:
    """settings·knowledge를 주지 않으면 기본값·빈 값으로 채운다."""
    context = report.build_report_context("전고체", {"youtube": [{"title": "영상"}]})

    assert context["keyword"] == "전고체"
    assert context["settings"]["preferred_language"] == "ko"
    assert context["settings"]["plan"] == "free"
    assert context["knowledge"] == []
    assert context["fresh"]["youtube"] == [{"title": "영상"}]


def test_build_report_context_merges_partial_settings() -> None:
    """일부 설정만 주면 나머지는 기본값으로 병합한다."""
    context = report.build_report_context(
        "전고체", {}, settings={"plan": "paid", "preferred_language": "en"}
    )
    assert context["settings"]["plan"] == "paid"
    assert context["settings"]["preferred_language"] == "en"
    assert context["settings"]["personalization_enabled"] is True  # 기본값 유지


def test_generate_report_passes_language_and_depth_to_prompt(monkeypatch) -> None:
    """설정의 언어·플랜이 프롬프트에 반영된다."""
    captured: dict[str, str] = {}

    def fake_complete(system_prompt, user_prompt, model="gpt-4.1-mini"):
        captured["user_prompt"] = user_prompt
        return "# 보고서\n- 내용"

    monkeypatch.setattr(report, "complete", fake_complete)

    context = report.build_report_context(
        "전고체 배터리",
        {"articles": [{"title": "기사1", "snippet": "요지"}]},
        settings={"plan": "paid", "preferred_language": "en"},
    )
    result = report.generate_report(context)

    assert result == "# 보고서\n- 내용"
    assert "영어" in captured["user_prompt"]
    assert "paid" in captured["user_prompt"]
    assert "기사1" in captured["user_prompt"]


def test_generate_report_uses_knowledge_only_when_personalized(monkeypatch) -> None:
    """개인화가 켜져 있을 때만 Wiki 기존 지식을 프롬프트에 포함한다."""
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        report, "complete", lambda s, u, model="gpt-4.1-mini": captured.setdefault("u", u) or "ok"
    )

    knowledge = [{"title": "내 위키 메모", "summary": "이미 아는 내용"}]

    on = report.build_report_context("주제", {}, knowledge=knowledge, settings={"personalization_enabled": True})
    report.generate_report(on)
    assert "내 위키 메모" in captured["u"]

    captured.clear()
    off = report.build_report_context("주제", {}, knowledge=knowledge, settings={"personalization_enabled": False})
    report.generate_report(off)
    assert "내 위키 메모" not in captured["u"]
    assert "개인화가 꺼져" in captured["u"]


def test_generate_report_requests_apply_to_me_section(monkeypatch) -> None:
    """시스템 프롬프트가 '나에게 적용하면' 섹션과 짧은 구성을 지시한다."""
    captured: dict[str, str] = {}

    def fake_complete(system_prompt, user_prompt, model="gpt-4.1-mini"):
        captured["system"] = system_prompt
        return "ok"

    monkeypatch.setattr(report, "complete", fake_complete)
    report.generate_report(report.build_report_context("주제", {}))

    assert "나에게 적용하면" in captured["system"]
    assert "핵심 요약" in captured["system"]


def test_generate_report_appends_real_source_urls(monkeypatch) -> None:
    """수집 자료의 실제 URL이 본문 아래 '출처' 섹션으로 붙는다(중복 제거)."""
    monkeypatch.setattr(report, "complete", lambda s, u, model="gpt-4.1-mini": "## 핵심 요약\n- 내용")

    fresh = {
        "youtube": [{"title": "영상A", "url": "https://youtu.be/a"}],
        "articles": [
            {"title": "기사B", "url": "https://news.com/b"},
            {"title": "기사B중복", "url": "https://news.com/b"},  # 같은 URL은 한 번만
        ],
        "reddit": [{"title": "글C", "url": "https://reddit.com/c"}],
    }
    result = report.generate_report(report.build_report_context("주제", fresh))

    assert "## 출처" in result
    assert "(https://youtu.be/a)" in result
    assert "(https://news.com/b)" in result
    assert "(https://reddit.com/c)" in result
    assert result.count("https://news.com/b") == 1  # 중복 URL은 한 번만


def test_collect_sources_caps_at_five_and_diversifies(monkeypatch) -> None:
    """출처는 최대 5개이며, 한 유형이 독점하지 않도록 유형을 번갈아 뽑는다."""
    fresh = {
        "youtube": [{"title": f"v{i}", "url": f"https://youtu.be/{i}"} for i in range(5)],
        "articles": [{"title": f"n{i}", "url": f"https://news.com/{i}"} for i in range(5)],
        "reddit": [{"title": f"r{i}", "url": f"https://reddit.com/{i}"} for i in range(5)],
    }
    sources = report._collect_sources(fresh)

    assert len(sources) == 5
    labels = {s["label"] for s in sources}
    assert labels == {"뉴스", "YouTube", "Reddit"}  # 세 유형이 모두 포함됨


def test_generate_report_can_skip_sources(monkeypatch) -> None:
    """include_sources=False면 URL이 있어도 출처 섹션을 붙이지 않는다."""
    monkeypatch.setattr(report, "complete", lambda s, u, model="gpt-4.1-mini": "## 핵심 요약\n- 내용")

    fresh = {"articles": [{"title": "기사", "url": "https://news.com/b"}]}
    result = report.generate_report(report.build_report_context("주제", fresh), include_sources=False)

    assert "## 출처" not in result
    assert "https://news.com/b" not in result


def test_generate_report_omits_sources_when_none(monkeypatch) -> None:
    """URL이 없는 자료만 있으면 출처 섹션을 붙이지 않는다."""
    monkeypatch.setattr(report, "complete", lambda s, u, model="gpt-4.1-mini": "본문")

    result = report.generate_report(report.build_report_context("주제", {"articles": [{"title": "제목만"}]}))

    assert "## 출처" not in result


def test_generate_report_notes_when_no_fresh_content(monkeypatch) -> None:
    """수집된 최신 자료가 없으면 프롬프트에 그 사실을 명시한다."""
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        report, "complete", lambda s, u, model="gpt-4.1-mini": captured.setdefault("u", u) or "ok"
    )

    report.generate_report(report.build_report_context("주제", {}))

    assert "수집된 최신 자료가 없습니다" in captured["u"]
