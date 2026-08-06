"""변경점 추적 에이전트가 변화를 얼마나 정확히 가려내는지 실제 LLM으로 측정한다.

측정 대상은 다섯 가지다.

    판정 정확도  : 신규·갱신·중복을 기대대로 갈랐는가
    ID 정합성    : 갱신일 때 **올바른 과거 팩트**를 가리켰는가(오매칭 포함)
    인용 마커    : Compose·Impact 서술에 유효한 참조 마커가 붙었는가
                   (마커가 없으면 뒤의 Critic이 빈 검토를 통과시킨다)
    날짜 정형화  : 모호한 표현을 규칙대로 절대 날짜로 바꿨는가
    잡음         : 주제와 무관한 자료에서 팩트를 뽑지 않았는가

**실제 agent-db에 연결해 SQL을 그대로 실행한다.** 예전에는 DB 호출을 전부
메모리 대역으로 갈아끼웠는데, 그 탓에 과거 팩트 조회가 **항상 0건**을 돌려주는
버그가 이 벤치를 판정 정확도 1.000으로 통과했다(2026-08-06). 조회 SQL이 한 번도
실행되지 않았기 때문이다. 그래서 대역을 걷어냈다 — DB가 없으면 조용히 대체하지
않고 즉시 실패한다.

재현성은 **케이스별 사용자 격리**로 확보한다. 케이스마다 전용 사용자
(`bench-change-history:<케이스 id>`)를 쓰고, 시작 전에 그 사용자의 델타 데이터를
지운 뒤 `base_facts`를 실제 테이블에 심는다. 그래서 몇 번을 돌려도 같은 상태에서
출발하고, "2일 연속 실행" 케이스는 1일차가 **DB에 저장한** 팩트를 2일차가 진짜
Base로 삼는다. 실행이 끝나면 데이터를 지운다(`--keep-data`로 남길 수 있다).

`--mode both`를 쓰면 Compose와 Impact를 **한 호출로 합친 변형**을 같은
데이터셋으로 함께 돌려, 분리 설계가 값을 하는지 품질·비용으로 비교한다.

비용이 발생하므로 --confirm-cost를 명시해야 실행된다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import selectors
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]

# 저장소 어디서 실행하든 프로젝트 모듈을 찾게 한다(다른 벤치마크와 같은 방식).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# OPENAI_API_KEY를 .env에서 읽는다.
load_dotenv(PROJECT_ROOT / ".env")

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from agent.change_history.features import graph as graph_module  # noqa: E402
from agent.change_history.features.compose import (  # noqa: E402
    ComposeOutcome,
    TimelineDraft,
    describe_facts_for_writing,
)
from agent.change_history.features.dates import DATE_RULES_PROMPT  # noqa: E402
from agent.change_history.features.impact import ImpactOutcome  # noqa: E402
from agent.llm.api import complete_with_usage, strip_json_fence  # noqa: E402
from infrastructure.persistence.api import (  # noqa: E402
    list_change_history_facts,
    persist_change_history_run,
    set_personal_wiki_scope,
)
from infrastructure.persistence.features.change_history_facts import (  # noqa: E402
    BASE_FACT_LIST_LIMIT,
)
from shared.change_history_models import NEW, NewChangeHistoryFact  # noqa: E402
from shared.report_models import ReportContextDocument  # noqa: E402

DATASET = ROOT / "dataset.jsonl"
_CITATION_REF = re.compile(r"\[([PGL]\d+)\]")

# 벤치 전용 사용자 ID 접두사. 실제 사용자 데이터와 섞이지 않게 하고, 정리할 때
# 이 접두사로 한 번에 지울 수 있게 한다.
BENCH_USER_PREFIX = "bench-change-history:"

# Compose와 Impact를 한 호출로 합친 변형. 프로덕션 코드에는 없고 비교용으로만
# 쓴다 — "분리한 설계가 실제로 값을 하는가"를 같은 데이터셋으로 재는 것이 목적이다.
MERGED_SYSTEM_PROMPT = (
    "너는 오늘의 변화를 정리해 브리핑을 쓰고, 그 파급효과까지 함께 분석하는 작성자다.\n"
    "\n"
    "네 가지를 한 번에 만든다.\n"
    "1. overview — 과거 맥락 위에 오늘의 변화가 얹히도록 융합한 종합 브리핑.\n"
    "2. timeline — 팩트마다 언제의 일인지 절대 날짜로 정리한 항목들.\n"
    "3. implications — 이 변화가 시장·산업·트렌드에 주는 파급효과.\n"
    "4. actions — 독자가 지금 취할 만한 행동 지침 (최대 5개).\n"
    "\n"
    "인용 규칙(반드시 지킨다):\n"
    "- 팩트에서 가져온 내용을 서술할 때는 그 팩트의 참조 ID를 대괄호로 붙인다.\n"
    '  예: "B사가 양산을 연기했습니다 [G2]"\n'
    "- 참조 ID는 주어진 팩트 목록에 있는 것만 쓴다.\n"
    "\n"
    + DATE_RULES_PROMPT
    + "\n"
    "JSON 객체 하나로만 답한다.\n"
    '{"title":"...","summary":"...","overview":"...",'
    '"timeline":[{"fact_index":0,"date":"YYYY-MM-DD 또는 빈 문자열",'
    '"precision":"day|month|quarter|half|year|unknown","description":"..."}],'
    '"implications":"...","actions":["..."]}\n'
)


def load_cases() -> list[dict[str, Any]]:
    """JSONL 벤치마크 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def to_context(entry: dict[str, Any]) -> ReportContextDocument:
    """케이스의 근거 항목을 생성용 Context 문서로 만든다."""
    return ReportContextDocument(
        reference=str(entry["reference"]),
        document_version_id=f"ver-{entry['reference']}",
        chunk_id=f"chunk-{entry['reference']}",
        namespace_key="global",
        title=str(entry["title"]),
        content=str(entry["content"]),
        url=None,
        score=1.0,
    )


def database_dsn() -> str:
    """벤치가 사용할 agent-db 접속 문자열을 읽는다.

    **없으면 즉시 실패한다.** 예전 이 벤치는 DB 호출을 전부 메모리 대역으로
    갈아끼웠는데, 그 탓에 실제 SQL이 한 번도 실행되지 않아 조회가 항상 0건을
    돌려주는 버그를 통과시켰다(2026-08-06). 조용히 대역으로 내려앉는 경로를
    두지 않는다.
    """
    dsn = os.getenv("AGENT_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit(
            "AGENT_DATABASE_URL이 없습니다. 이 벤치마크는 실제 agent-db에 연결해야 "
            "합니다(로컬은 `docker compose up -d`로 띄웁니다)."
        )
    return dsn


def bench_user_id(case_id: str) -> str:
    """케이스별로 격리된 벤치 전용 사용자 ID를 만든다.

    케이스마다 사용자를 나눠야 앞 케이스가 저장한 팩트가 뒤 케이스의 Base로
    새어 들어가지 않는다(실행 순서에 따라 결과가 바뀌면 회귀 비교가 무의미해진다).
    """
    return f"{BENCH_USER_PREFIX}{case_id}"


async def reset_case_data(connection: Any, *, user_id: str) -> None:
    """이 벤치 사용자의 델타 데이터를 지워 매 실행을 같은 상태에서 시작한다.

    갱신 링크(supersedes_fact_id)를 먼저 끊는다 — 자기참조 FK가 남아 있으면
    팩트 삭제가 막힌다.
    """
    async with connection.transaction():
        await connection.execute(
            "UPDATE agent.change_history_facts SET supersedes_fact_id = NULL "
            "WHERE user_id = %s",
            (user_id,),
        )
        await connection.execute(
            "DELETE FROM agent.change_history_facts WHERE user_id = %s", (user_id,)
        )
        await connection.execute(
            "DELETE FROM agent.change_history_runs WHERE user_id = %s", (user_id,)
        )


async def seed_base_facts(
    connection: Any,
    *,
    user_id: str,
    topic: str,
    entries: list[dict[str, Any]],
    reference_date: date,
) -> dict[str, str]:
    """케이스가 정의한 과거 팩트를 **실제 테이블에** 심는다.

    데이터셋은 팩트를 'f1' 같은 상징적 ID로 적지만 실제 ID는 저장 시점에 정해진다.
    그래서 {데이터셋 ID: 실제 UUID} 대응표를 돌려주고, 채점이 이 표로 기대
    updates_fact_id를 해석한다.
    """
    if not entries:
        return {}
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        persisted = await persist_change_history_run(
            connection,
            user_id=user_id,
            topic=topic,
            # 어제 실행이 남긴 Base라는 뜻으로 기준일 하루 전에 심는다.
            reference_date=reference_date - timedelta(days=1),
            facts=[
                NewChangeHistoryFact(
                    subject=str(entry["subject"]),
                    attribute=str(entry["attribute"]),
                    fact_value=str(entry["fact_value"]),
                    statement=str(entry["statement"]),
                    verdict=NEW,
                )
                for entry in entries
            ],
            is_first_run=True,
        )
    return dict(zip([str(entry["id"]) for entry in entries], persisted.fact_ids))


async def count_stored_facts(connection: Any, *, user_id: str, topic: str) -> int:
    """이 벤치 사용자·주제에 실제로 저장된 활성 팩트 수를 센다."""
    cursor = await connection.execute(
        "SELECT count(*) AS total FROM agent.change_history_facts "
        "WHERE user_id = %s AND topic = %s AND status = 'active'",
        (user_id, topic),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def count_stored_runs(connection: Any, *, user_id: str, topic: str) -> int:
    """이 벤치 사용자·주제에 기록된 실행 수를 센다(첫 실행 저장 확인용)."""
    cursor = await connection.execute(
        "SELECT count(*) AS total FROM agent.change_history_runs "
        "WHERE user_id = %s AND topic = %s",
        (user_id, topic),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def find_seeded_fact_id(
    connection: Any, *, user_id: str, topic: str, hint: str
) -> str:
    """1일차가 저장한 팩트 중 힌트가 들어간 것의 실제 ID를 찾는다.

    2일차 기대값의 "@day1:<힌트>" 참조를 해석할 때 쓴다.
    """
    facts = await list_change_history_facts(
        connection, user_id=user_id, topic=topic, limit=BASE_FACT_LIST_LIMIT
    )
    lowered = hint.lower()
    for fact in facts:
        haystack = f"{fact.subject} {fact.attribute} {fact.statement}".lower()
        if lowered in haystack:
            return fact.fact_id
    return ""


def install_merged_workers(usage: dict[str, int]) -> None:
    """Compose·Impact를 한 LLM 호출로 합친 변형을 끼워 넣는다(비교용)."""
    cache: dict[str, Any] = {}

    async def merged_compose(**kwargs: Any) -> ComposeOutcome:
        """합친 호출을 실행하고 Overview·타임라인 부분만 돌려준다."""
        facts = list(kwargs["facts"])
        user_prompt = (
            f"주제: {kwargs['topic']}\n"
            f"기준일: {kwargs['reference_date'].isoformat()}\n\n"
            "오늘 확인된 팩트:\n" + describe_facts_for_writing(facts)
        )
        completion = await asyncio.to_thread(
            complete_with_usage,
            MERGED_SYSTEM_PROMPT,
            user_prompt,
            model=kwargs.get("model", "gpt-4.1-mini"),
        )
        usage["input_tokens"] = usage.get("input_tokens", 0) + completion.input_tokens
        usage["output_tokens"] = usage.get("output_tokens", 0) + completion.output_tokens
        usage["calls"] = usage.get("calls", 0) + 1
        try:
            payload = json.loads(strip_json_fence(completion.text))
        except (ValueError, TypeError):
            cache["impact"] = ImpactOutcome(failed=True)
            return ComposeOutcome(failed=True)
        entries = []
        for item in payload.get("timeline") or []:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("fact_index"))
            except (TypeError, ValueError):
                index = -1
            entries.append(
                TimelineDraft(
                    fact_index=index,
                    raw_date=str(item.get("date") or "").strip(),
                    precision=str(item.get("precision") or "unknown"),
                    description=str(item.get("description") or "").strip(),
                )
            )
        cache["impact"] = ImpactOutcome(
            implications=str(payload.get("implications") or "").strip(),
            actions=tuple(str(a) for a in (payload.get("actions") or []) if str(a).strip()),
            failed=not str(payload.get("implications") or "").strip(),
        )
        overview = str(payload.get("overview") or "").strip()
        return ComposeOutcome(
            title=str(payload.get("title") or "").strip(),
            summary=str(payload.get("summary") or "").strip(),
            overview=overview,
            timeline=tuple(entries),
            failed=not overview,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )

    async def merged_impact(**kwargs: Any) -> ImpactOutcome:
        """합친 호출이 이미 만든 파급효과를 돌려준다(추가 호출 없음)."""
        return cache.get("impact") or ImpactOutcome(failed=True)

    graph_module.chg_003 = merged_compose  # type: ignore[assignment]
    graph_module.chg_004 = merged_impact  # type: ignore[assignment]


def restore_split_workers() -> None:
    """분리 설계(기본)를 되돌린다."""
    from agent.change_history.features.compose import chg_003
    from agent.change_history.features.impact import chg_004

    graph_module.chg_003 = chg_003  # type: ignore[assignment]
    graph_module.chg_004 = chg_004  # type: ignore[assignment]


def valid_markers(text: str, contexts: list[ReportContextDocument]) -> set[str]:
    """본문에서 근거 목록에 실제로 있는 인용 마커만 뽑는다."""
    allowed = {context.reference for context in contexts}
    return {ref for ref in _CITATION_REF.findall(text or "") if ref in allowed}


def match_fact(facts: list[Any], hint: str) -> Any | None:
    """subject·attribute·서술에 힌트가 들어 있는 첫 팩트를 찾는다."""
    lowered = hint.lower()
    for item in facts:
        fact = item.fact
        haystack = f"{fact.subject} {fact.attribute} {fact.today_statement}".lower()
        if lowered in haystack:
            return item
    return None


def score_day(
    *,
    expect: dict[str, Any],
    result: dict[str, Any],
    contexts: list[ReportContextDocument],
    stored_facts: int,
    stored_runs: int,
    day1_ids: dict[str, str],
) -> dict[str, Any]:
    """하루치 실행 결과를 기대값과 대조해 채점한다.

    stored_facts·stored_runs는 실행 뒤 **실제 테이블을 세어** 넘긴 값이다.
    저장 여부를 호출 기록이 아니라 DB 상태로 확인해야, 저장 SQL이 실패하는
    회귀를 잡을 수 있다.
    """
    facts = list(result.get("facts") or [])
    body = str(result["generated"].body)
    checks: list[tuple[str, bool]] = []

    checks.append(("no_change", bool(result["no_change"]) == bool(expect["no_change"])))

    for hint in expect.get("new_hints") or []:
        item = match_fact(facts, hint)
        checks.append((f"new:{hint}", item is not None and item.fact.verdict == "new"))

    id_checks: list[tuple[str, bool]] = []
    for expected in expect.get("updated") or []:
        hint = str(expected["hint"])
        item = match_fact(facts, hint)
        checks.append(
            (f"updated:{hint}", item is not None and item.fact.verdict == "updated")
        )
        # 데이터셋은 팩트를 'f1' 같은 상징적 ID로 적지만 실제 ID는 저장 시점에
        # 정해진다. 두 형태 모두 대응표로 실제 UUID로 바꾼 뒤에 비교한다.
        base_id = str(expected["base_id"])
        if base_id.startswith("@day1:"):
            base_id = day1_ids.get(base_id[len("@day1:") :], "")
        else:
            base_id = day1_ids.get(base_id, "")
        id_checks.append(
            (
                f"id:{hint}",
                item is not None
                and bool(base_id)
                and item.fact.updates_fact_id == base_id,
            )
        )

    for hint in expect.get("duplicate_hints") or []:
        # duplicate는 보고서에 쓰이지 않으므로, 통과한 팩트에 없어야 맞다.
        checks.append((f"duplicate:{hint}", match_fact(facts, hint) is None))

    date_checks: list[tuple[str, bool]] = []
    for hint, expected_date in (expect.get("dates") or {}).items():
        item = match_fact(facts, hint)
        actual = item.occurred_on.isoformat() if item and item.occurred_on else ""
        date_checks.append((f"date:{hint}", actual == expected_date))

    noise = [
        hint
        for hint in expect.get("forbidden_hints") or []
        if match_fact(facts, hint) is not None
    ]

    storage_ok = stored_runs > 0 if expect.get("expect_stored") else True

    return {
        "verdict_checks": checks,
        "verdict_pass": sum(1 for _, ok in checks if ok),
        "verdict_total": len(checks),
        "id_checks": id_checks,
        "id_pass": sum(1 for _, ok in id_checks if ok),
        "id_total": len(id_checks),
        "date_checks": date_checks,
        "date_pass": sum(1 for _, ok in date_checks if ok),
        "date_total": len(date_checks),
        "noise": noise,
        "overview_markers": sorted(valid_markers(body.split("## 🔥")[0], contexts)),
        "impact_markers": sorted(
            valid_markers(body.split("## 💡")[-1] if "## 💡" in body else "", contexts)
        ),
        "citations": list(result["generated"].citation_references),
        "quality_outcome": result.get("quality_outcome"),
        "dropped_flags": result.get("dropped_flags"),
        "stored_runs": stored_runs,
        "stored_facts": stored_facts,
        "storage_ok": storage_ok,
        "input_tokens": int(result.get("input_tokens") or 0),
        "output_tokens": int(result.get("output_tokens") or 0),
        "retries": (
            max(0, int(result.get("diff_attempts") or 0) - 1)
            + max(0, int(result.get("compose_attempts") or 0) - 1)
            + max(0, int(result.get("impact_attempts") or 0) - 1)
        ),
    }


async def run_case(
    connection: Any, case: dict[str, Any], model: str, *, keep_data: bool
) -> dict[str, Any]:
    """케이스 하나(필요하면 2일치)를 **실제 DB에 대고** 실행하고 채점한다.

    케이스마다 전용 사용자로 격리하고, 시작 전에 이전 실행 흔적을 지운다 —
    그래야 몇 번을 돌려도 같은 결과가 나와 회귀 비교가 가능하다.
    """
    topic = str(case["topic"])
    user_id = bench_user_id(str(case["id"]))
    reference_date = date.fromisoformat(str(case["reference_date"]))

    await reset_case_data(connection, user_id=user_id)
    base_ids = await seed_base_facts(
        connection,
        user_id=user_id,
        topic=topic,
        entries=list(case.get("base_facts") or []),
        reference_date=reference_date,
    )

    contexts = [to_context(entry) for entry in case["contexts"]]
    started = time.perf_counter()
    result = await graph_module.chg_001(
        connection,
        user_id=user_id,
        job_id="bench-job",
        topic=topic,
        contexts=contexts,
        model=model,
        reference_date=reference_date,
    )
    day1 = score_day(
        expect=case["expect"],
        result=result,
        contexts=contexts,
        stored_facts=await count_stored_facts(connection, user_id=user_id, topic=topic),
        stored_runs=await count_stored_runs(connection, user_id=user_id, topic=topic),
        # 1일차의 기대 ID는 데이터셋이 심은 Base 팩트를 가리킨다.
        day1_ids=base_ids,
    )
    day1["latency_ms"] = int((time.perf_counter() - started) * 1000)

    days = [day1]
    second = case.get("second_day")
    if second:
        # 1일차가 저장한 팩트의 실제 ID를 찾아 둔다(2일차 기대 ID 해석에 쓴다).
        # 저장 ID는 실행 중에 정해지므로 데이터셋에는 "@day1:<힌트>"로만 적혀 있다.
        day1_ids = dict(base_ids)
        for expected in second["expect"].get("updated") or []:
            reference = str(expected["base_id"])
            if not reference.startswith("@day1:"):
                continue
            hint = reference[len("@day1:") :]
            day1_ids[hint] = await find_seeded_fact_id(
                connection, user_id=user_id, topic=topic, hint=hint
            )
        contexts2 = [to_context(entry) for entry in second["contexts"]]
        started2 = time.perf_counter()
        result2 = await graph_module.chg_001(
            connection,
            user_id=user_id,
            job_id="bench-job-2",
            topic=topic,
            contexts=contexts2,
            model=model,
            reference_date=date.fromisoformat(str(second["reference_date"])),
        )
        day2 = score_day(
            expect=second["expect"],
            result=result2,
            contexts=contexts2,
            stored_facts=await count_stored_facts(
                connection, user_id=user_id, topic=topic
            ),
            stored_runs=await count_stored_runs(
                connection, user_id=user_id, topic=topic
            ),
            day1_ids=day1_ids,
        )
        day2["latency_ms"] = int((time.perf_counter() - started2) * 1000)
        days.append(day2)

    if not keep_data:
        await reset_case_data(connection, user_id=user_id)
    return {"id": case["id"], "kind": case["kind"], "days": days}


async def run_cases(
    cases: list[dict[str, Any]], model: str, *, keep_data: bool = False
) -> list[dict[str, Any]]:
    """모든 케이스를 순서대로 실행하고 진행 상황을 출력한다."""
    results: list[dict[str, Any]] = []
    async with await psycopg.AsyncConnection.connect(
        database_dsn(), row_factory=dict_row
    ) as connection:
        for case in cases:
            outcome = await run_case(connection, case, model, keep_data=keep_data)
            results.append(outcome)
            for index, day in enumerate(outcome["days"], start=1):
                marks = []
                marks.append(
                    "판정OK" if day["verdict_pass"] == day["verdict_total"] else "판정미스"
                )
                if day["id_total"]:
                    marks.append(
                        "IDOK" if day["id_pass"] == day["id_total"] else "ID오매칭"
                    )
                if day["date_total"]:
                    marks.append(
                        "날짜OK" if day["date_pass"] == day["date_total"] else "날짜미스"
                    )
                if day["noise"]:
                    marks.append("잡음")
                if not day["overview_markers"]:
                    marks.append("Overview마커없음")
                if day["retries"]:
                    marks.append(f"재작업{day['retries']}")
                suffix = f" day{index}" if len(outcome["days"]) > 1 else ""
                print(
                    f"[{' '.join(marks):<24}] {outcome['id']}{suffix:<8} "
                    f"인용={day['citations']} 저장={day['stored_facts']}건",
                    flush=True,
                )
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """케이스별 결과를 집계 지표로 요약한다."""
    days = [day for result in results for day in result["days"]]
    total = len(days)
    verdict_pass = sum(day["verdict_pass"] for day in days)
    verdict_total = sum(day["verdict_total"] for day in days)
    id_pass = sum(day["id_pass"] for day in days)
    id_total = sum(day["id_total"] for day in days)
    date_pass = sum(day["date_pass"] for day in days)
    date_total = sum(day["date_total"] for day in days)
    with_markers = sum(1 for day in days if day["overview_markers"])
    impact_markers = sum(1 for day in days if day["impact_markers"])
    return {
        "runs": total,
        "verdict_accuracy": round(verdict_pass / verdict_total, 3) if verdict_total else 0.0,
        "verdict_checks": verdict_total,
        "update_id_accuracy": round(id_pass / id_total, 3) if id_total else None,
        "update_id_checks": id_total,
        "date_accuracy": round(date_pass / date_total, 3) if date_total else None,
        "date_checks": date_total,
        "overview_citation_rate": round(with_markers / total, 3) if total else 0.0,
        "impact_citation_rate": round(impact_markers / total, 3) if total else 0.0,
        "noise_runs": sum(1 for day in days if day["noise"]),
        "storage_ok_runs": sum(1 for day in days if day["storage_ok"]),
        "dropped_flag_runs": sum(1 for day in days if day["dropped_flags"]),
        "avg_latency_ms": int(sum(day["latency_ms"] for day in days) / total) if total else 0,
        "input_tokens": sum(day["input_tokens"] for day in days),
        "output_tokens": sum(day["output_tokens"] for day in days),
        "worker_retries": sum(day["retries"] for day in days),
    }


def main() -> int:
    """비용 확인 후 전체 벤치마크를 실행하고 결과를 출력한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument(
        "--mode",
        default="split",
        choices=["split", "merged", "both"],
        help="split=Compose·Impact 분리(기본), merged=한 호출로 합침, both=둘 다",
    )
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="실행 후 벤치 사용자의 델타 데이터를 지우지 않는다(결과를 직접 들여다볼 때)",
    )
    args = parser.parse_args()

    cases = load_cases()
    runs = sum(2 if case.get("second_day") else 1 for case in cases)
    # 실행 1회당 LLM 호출: Diff 1(+도구 왕복) + Compose 1 + Impact 1 ≈ 3~5회.
    dataset_tokens = sum(len(json.dumps(c, ensure_ascii=False)) for c in cases) // 3
    modes = ["split", "merged"] if args.mode == "both" else [args.mode]
    dsn = database_dsn()
    print(
        f"cases={len(cases)}, runs={runs}회/모드, modes={modes}, "
        f"estimated_input_tokens~={dataset_tokens * 4 * len(modes)}"
    )
    print(f"agent-db={dsn.rsplit('@', 1)[-1]} (실제 DB에 연결해 SQL을 그대로 실행합니다)")
    if not args.confirm_cost:
        print("실제 호출을 실행하려면 --confirm-cost를 추가하세요.")
        return 2

    loop_factory = (
        (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
        if sys.platform == "win32"
        else None
    )
    report: dict[str, Any] = {"model": args.model, "modes": {}}
    for mode in modes:
        print(f"\n=== mode={mode} ===")
        if mode == "merged":
            install_merged_workers({})
        else:
            restore_split_workers()
        results = asyncio.run(
            run_cases(cases, args.model, keep_data=args.keep_data),
            loop_factory=loop_factory,
        )
        summary = summarize(results)
        report["modes"][mode] = {"summary": summary, "results": results}
        print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    restore_split_workers()

    (ROOT / "last_run.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
