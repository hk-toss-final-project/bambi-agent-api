"""변경점 추적 토글이 기존 리포트 그래프에 미치는 영향을 검증한다.

가장 중요한 것은 **토글 OFF 회귀**다 — 꺼진 요청은 지금까지와 완전히 같은
generate 경로를 타야 하고, change_history 노드는 아예 실행되지 않아야 한다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agent import graph as agent_graph
from shared.report_models import GeneratedReportContent, ReportContextDocument


class _FakeConnection:
    """transaction 문맥만 제공하는 Connection Test Double."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """빈 Transaction 문맥을 제공한다."""
        yield


def _context() -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference="G1",
        document_version_id="ver-G1",
        chunk_id="chunk-G1",
        namespace_key="global",
        title="기사",
        content="본문",
        url=None,
        score=0.5,
    )


def _delta_content() -> GeneratedReportContent:
    """델타 경로가 만든 보고서를 흉내낸다."""
    return GeneratedReportContent(
        title="반도체 변경점",
        summary="요약 [G1]",
        body="## Overview\n\n브리핑 [G1]",
        citation_references=("G1",),
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch, order: list[str]) -> dict[str, Any]:
    """조사·검색·생성·검토·저장 경계를 모두 대체한다."""
    captured: dict[str, Any] = {}

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """RLS Scope 설정을 생략한다."""

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[Any]:
        """개인 Wiki·풀 검색을 고정 문서 한 건으로 대체한다."""
        return [_context()]

    async def fake_prag_006(contexts: list[Any]) -> list[Any]:
        """맥락화 단계를 통과시킨다."""
        return contexts

    async def fake_freshness(connection: Any, ids: Any) -> dict[str, Any]:
        """풀 신선도 조회를 생략한다."""
        return {}

    def fake_generate(**kwargs: Any) -> GeneratedReportContent:
        """기존 생성 경로 호출을 기록한다."""
        order.append("generate")
        return GeneratedReportContent(
            title="일반 리포트",
            summary="요약",
            body="본문 [G1]",
            citation_references=("G1",),
        )

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 단계에 들어간 본문과 실제 델타 사용 여부를 기록한다."""
        order.append("persist")
        captured["generated"] = kwargs["generated"]
        captured["change_history_used"] = kwargs.get("change_history_used")
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(agent_graph, "select_pool_documents", lambda *a, **k: [])
    monkeypatch.setattr(agent_graph, "select_personal_documents", lambda docs: list(docs))
    monkeypatch.setattr(agent_graph, "is_pool_relevant", lambda *a, **k: True)
    monkeypatch.setattr(agent_graph, "is_pool_sufficient", lambda *a, **k: True)
    monkeypatch.setattr(agent_graph, "select_generation_context", lambda *a, **k: [_context()])
    monkeypatch.setattr(agent_graph, "generate_report_content_with_quality", fake_generate)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: False)
    monkeypatch.setattr(agent_graph, "resolve_topic_intent", lambda *args: "news")
    monkeypatch.setattr(agent_graph, "embed_wiki_queries", lambda queries: {})
    monkeypatch.setattr(agent_graph, "critic_enabled", lambda: False)
    monkeypatch.setattr(agent_graph, "change_history_available", lambda: True)
    return captured


def _run(*, change_history_enabled: bool) -> dict[str, object]:
    """리포트 그래프를 고정 입력으로 실행한다."""
    return asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="반도체",
            content_type="article",
            language="ko",
            model="test-model",
            change_history_enabled=change_history_enabled,
        )
    )


def test_toggle_off_keeps_the_existing_generate_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """토글이 꺼지면 델타 경로는 아예 실행되지 않는다(회귀 0)."""
    order: list[str] = []
    captured = _patch_common(monkeypatch, order)

    async def fail_if_called(connection: Any, **kwargs: Any) -> dict[str, Any]:
        """델타 경로가 불리면 테스트를 실패시킨다."""
        raise AssertionError("토글이 꺼졌는데 변경점 추적이 실행됐습니다.")

    monkeypatch.setattr(agent_graph, "chg_001", fail_if_called)

    result = _run(change_history_enabled=False)

    assert order == ["generate", "persist"]
    assert captured["generated"].title == "일반 리포트"
    assert result == {"content_candidate_id": "candidate-1"}
    assert captured["change_history_used"] is False


def test_toggle_on_replaces_generate_with_the_delta_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """토글이 켜지면 generate 대신 델타 경로가 본문을 만든다.

    조립된 markdown이 review·persist가 읽는 state 키(generated)에 그대로
    들어가야 기존 저장 흐름이 이어진다.
    """
    order: list[str] = []
    captured = _patch_common(monkeypatch, order)

    async def fake_change_history(connection: Any, **kwargs: Any) -> dict[str, Any]:
        """델타 경로가 보고서를 만든 상황을 재현한다."""
        order.append("change_history")
        assert kwargs["topic"] == "반도체"
        assert [document.reference for document in kwargs["contexts"]] == ["G1"]
        return {"generated": _delta_content(), "fact_count": 1}

    monkeypatch.setattr(agent_graph, "chg_001", fake_change_history)

    _run(change_history_enabled=True)

    assert order == ["change_history", "persist"]  # generate는 돌지 않는다
    assert captured["generated"].body.startswith("## Overview")
    assert captured["change_history_used"] is True


def test_server_switch_overrides_the_request_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """서버 차단 스위치가 꺼져 있으면 요청이 켜도 기존 경로로 간다.

    이때 발행되는 change_history_enabled도 반드시 False여야 한다 — 요청
    파라미터만 echo하면 값은 true인데 body는 기존 형식이 나가는 불일치가
    생긴다(2026-08-11 풀스택 피드백으로 발견된 실제 버그).
    """
    order: list[str] = []
    captured = _patch_common(monkeypatch, order)
    monkeypatch.setattr(agent_graph, "change_history_available", lambda: False)
    monkeypatch.setattr(
        agent_graph,
        "chg_001",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("차단 스위치가 무시됐습니다.")),
    )

    _run(change_history_enabled=True)

    assert order == ["generate", "persist"]
    assert captured["change_history_used"] is False


def _patch_per_topic_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """주제마다 서로 다른 근거 문서가 잡히도록 검색 경계를 바꾼다.

    기본 대역은 모든 주제에 같은 문서를 돌려줘서 중복 제거에 걸린다. 주제별
    근거 배정을 확인하려면 주제마다 다른 문서가 나와야 한다.
    """

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[Any]:
        """검색어(주제)마다 다른 근거 문서를 돌려준다."""
        query = str(kwargs["query"])
        document = _context()
        object.__setattr__(document, "reference", f"G-{query}")
        object.__setattr__(document, "document_version_id", f"ver-{query}")
        object.__setattr__(document, "chunk_id", f"chunk-{query}")
        return [document]

    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(
        agent_graph,
        "select_generation_context",
        lambda personal, live, **kwargs: list(personal),
    )


def test_multi_topic_request_runs_a_delta_per_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주제가 여럿이면 주제마다 델타를 돌리고 한 본문으로 합친다.

    비교축이 (user_id, topic)이라 한 축으로 묶으면 주제별 변화가 구분되지
    않는다 — 대표 문자열 하나에 서로 다른 주제의 팩트가 섞여 쌓인다.
    """
    order: list[str] = []
    captured = _patch_common(monkeypatch, order)
    _patch_per_topic_documents(monkeypatch)
    calls: list[tuple[str, list[str]]] = []

    async def fake_change_history(connection: Any, **kwargs: Any) -> dict[str, Any]:
        """주제별 호출을 기록하고 그 주제의 델타 보고서를 돌려준다."""
        topic = str(kwargs["topic"])
        references = [document.reference for document in kwargs["contexts"]]
        calls.append((topic, references))
        reference = references[0]
        return {
            "generated": GeneratedReportContent(
                title=f"{topic} 변경점",
                summary=f"{topic} 요약",
                body=f"## Overview\n\n{topic} 브리핑 [{reference}]",
                citation_references=(reference,),
            ),
            "fact_count": 1,
            "input_tokens": 10,
        }

    monkeypatch.setattr(agent_graph, "chg_001", fake_change_history)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 브리핑",
            topics=["반도체", "환율"],
            content_type="article",
            language="ko",
            model="test-model",
            change_history_enabled=True,
        )
    )

    # 대표 문자열("오늘의 브리핑")이 아니라 실제 주제로 비교축이 잡혀야 한다.
    assert [topic for topic, _ in calls] == ["반도체", "환율"]
    assert calls[0][1] == ["G1"]
    assert calls[1][1] == ["G2"]
    body = captured["generated"].body
    assert "## 반도체" in body and "## 환율" in body
    assert order == ["persist"]  # generate는 돌지 않는다
    assert captured["change_history_used"] is True


def test_multi_topic_delta_keeps_going_when_one_topic_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주제 하나가 실패해도 나머지 주제로 보고서를 만든다.

    한 주제 때문에 브리핑 전체가 기존 생성으로 되돌아가면 손해가 더 크다.
    """
    order: list[str] = []
    captured = _patch_common(monkeypatch, order)
    _patch_per_topic_documents(monkeypatch)

    async def flaky_change_history(connection: Any, **kwargs: Any) -> dict[str, Any]:
        """첫 주제만 실패시킨다."""
        topic = str(kwargs["topic"])
        if topic == "반도체":
            raise RuntimeError("delta down")
        reference = kwargs["contexts"][0].reference
        return {
            "generated": GeneratedReportContent(
                title=f"{topic} 변경점",
                summary=f"{topic} 요약",
                body=f"## Overview\n\n{topic} 브리핑 [{reference}]",
                citation_references=(reference,),
            ),
            "fact_count": 1,
        }

    monkeypatch.setattr(agent_graph, "chg_001", flaky_change_history)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 브리핑",
            topics=["반도체", "환율"],
            content_type="article",
            language="ko",
            model="test-model",
            change_history_enabled=True,
        )
    )

    assert order == ["persist"]
    # 살아남은 주제가 하나여도 다주제 요청이었으므로 감싸고 헤딩을 내린다
    # (2026-08-11 풀스택 피드백: 살아남은 주제 수에 따라 구조가 갈리면 안 됨).
    generated = captured["generated"]
    assert generated.title.startswith("오늘의 브리핑 요약")
    assert "## 환율" in generated.body
    assert "### Overview" in generated.body


def test_multi_topic_delta_falls_back_when_every_topic_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """모든 주제의 델타가 실패하면 기존 생성 경로로 되돌아간다."""
    order: list[str] = []
    captured = _patch_common(monkeypatch, order)
    _patch_per_topic_documents(monkeypatch)

    async def broken_change_history(connection: Any, **kwargs: Any) -> dict[str, Any]:
        """모든 주제를 실패시킨다."""
        raise RuntimeError("delta down")

    monkeypatch.setattr(agent_graph, "chg_001", broken_change_history)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 브리핑",
            topics=["반도체", "환율"],
            content_type="article",
            language="ko",
            model="test-model",
            change_history_enabled=True,
        )
    )

    assert order == ["generate", "persist"]
    assert captured["generated"].title == "일반 리포트"
    assert captured["change_history_used"] is False


def test_delta_failure_falls_back_to_the_existing_generate_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """델타 경로가 실패해도 발행을 막지 않고 기존 생성으로 되돌아간다.

    이때도 change_history_enabled는 False로 나가야 한다 — 실제로는
    generate()가 만든 기존 형식 본문이 나갔기 때문이다.
    """
    order: list[str] = []
    captured = _patch_common(monkeypatch, order)

    async def broken_change_history(connection: Any, **kwargs: Any) -> dict[str, Any]:
        """델타 경로 장애를 재현한다."""
        order.append("change_history")
        raise RuntimeError("delta down")

    monkeypatch.setattr(agent_graph, "chg_001", broken_change_history)

    _run(change_history_enabled=True)

    assert order == ["change_history", "generate", "persist"]
    assert captured["generated"].title == "일반 리포트"
    assert captured["change_history_used"] is False
