"""개인화 보고서 생성.

세 갈래 입력을 하나의 계약(report_context)으로 받아 개인화된 Markdown 보고서를
생성한다:

  ① settings   : user_context_snapshots에서 온 설정(언어·플랜·차단·개인화 여부)
  ② knowledge  : 개인 LLM Wiki의 관련 기존 지식(prag_006 결과 등, 팀원 소유)
  ③ fresh      : 우리 비서가 모은 최신 자료(유튜브·뉴스·레딧)

①과 ②는 아직 다른 팀/DB가 채우므로, 이 모듈은 그 구현이 아니라 "입력 dict의 모양"에만
의존한다. 없으면 기본값·빈 값으로 동작해 ③(최신 자료)만으로도 보고서가 나온다. 나중에
어댑터로 ①·②를 채우면 개인화가 강해진다.
"""

from __future__ import annotations

from agent.assistant.summarize import complete

# ①settings 기본값. user_context_snapshots 어댑터가 붙기 전까지 사용한다.
_DEFAULT_SETTINGS: dict[str, object] = {
    "preferred_language": "ko",
    "plan": "free",
    "personalization_enabled": True,
    "blocked_interest_ids": [],
    "blocked_source_ids": [],
}

_SYSTEM_PROMPT = (
    "너는 개인화된 일간 정보 보고서를 쓰는 한국어 비서다. "
    "제공된 자료에 있는 내용만 사용하고, 없는 사실을 지어내지 않는다. "
    "자료가 부족하면 부족하다고 솔직히 적는다. "
    "출력은 Markdown이며 다음 두 부분으로 구성한다: "
    "(1) '## 핵심 요약' — 오늘 알아야 할 내용을 6~9개 불릿으로 충실히 정리한다. "
    "각 불릿은 사실뿐 아니라 배경·맥락·수치·상반된 관점까지 한두 문장으로 담아 "
    "구체적으로 쓴다. 여러 자료에서 겹치는 흐름은 종합하고, 엇갈리는 부분은 함께 적는다. "
    "(2) '## 나에게 적용하면' — 이 내용이 사용자에게 어떤 의미인지, 어떤 기회·리스크가 "
    "있는지, 무엇을 하면 좋을지를 4~6개 불릿으로 구체적이고 실천적으로 쓴다. "
    "각 항목은 '왜 그런지' 이유까지 덧붙인다. "
    "그 외 개요·서론·맺음말 같은 군더더기 섹션은 넣지 않는다. 출처 URL은 본문에 넣지 않는다."
)


def _language_name(code: str) -> str:
    """언어 코드를 프롬프트에 쓸 이름으로 변환한다."""
    return {"ko": "한국어", "en": "영어", "ja": "일본어"}.get(code, code)


def _format_fresh(fresh: dict[str, object]) -> str:
    """③최신 자료(유튜브·뉴스·레딧)를 프롬프트용 텍스트로 정리한다."""
    lines: list[str] = []

    youtube = list(fresh.get("youtube") or [])
    if youtube:
        lines.append("[YouTube 영상 요약]")
        for item in youtube:
            body = item.get("summary") or item.get("note") or ""
            lines.append(f"- {item.get('title')}: {body}")

    articles = list(fresh.get("articles") or [])
    if articles:
        lines.append("\n[뉴스 기사]")
        for item in articles:
            lines.append(f"- {item.get('title')}: {item.get('snippet') or ''}")

    reddit = list(fresh.get("reddit") or [])
    if reddit:
        lines.append("\n[Reddit 게시글 요약]")
        for item in reddit:
            body = item.get("summary") or item.get("note") or ""
            lines.append(f"- {item.get('title')}: {body}")

    return "\n".join(lines).strip()


# 보고서에 표시할 출처 최대 개수.
_MAX_SOURCES = 5


def _collect_sources(fresh: dict[str, object], max_sources: int = _MAX_SOURCES) -> list[dict[str, str]]:
    """최신 자료에서 실제 URL이 있는 출처를 모아 상위 max_sources개만 남긴다.

    LLM이 URL을 지어내지 못하도록, 수집한 자료의 실제 url을 코드에서 직접 모아
    보고서 하단 출처 목록에 붙인다. 조회수·추천수 같은 참여 지표를 수집하지 않으므로
    '영향력'은 각 소스가 이미 정렬돼 있는 관련도·최신순을 근사로 사용한다. 한쪽
    소스가 목록을 독점하지 않도록 유형(뉴스·YouTube·Reddit)을 번갈아 뽑는다.
    """
    buckets: list[list[dict[str, str]]] = []
    seen: set[str] = set()
    # 편집·검증을 거친 뉴스를 우선 노출한다.
    for key, label in [("articles", "뉴스"), ("youtube", "YouTube"), ("reddit", "Reddit")]:
        bucket: list[dict[str, str]] = []
        for item in list(fresh.get(key) or []):
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            bucket.append({"label": label, "title": str(item.get("title") or url), "url": url})
        buckets.append(bucket)

    # 유형을 라운드로빈으로 번갈아 뽑아 다양성을 확보한다.
    sources: list[dict[str, str]] = []
    index = 0
    while len(sources) < max_sources and any(index < len(b) for b in buckets):
        for bucket in buckets:
            if index < len(bucket) and len(sources) < max_sources:
                sources.append(bucket[index])
        index += 1
    return sources


def _format_sources(sources: list[dict[str, str]]) -> str:
    """출처 목록을 보고서 하단에 붙일 Markdown으로 만든다."""
    if not sources:
        return ""
    lines = ["", "## 출처"]
    for source in sources:
        lines.append(f"- [{source['label']}] [{source['title']}]({source['url']})")
    return "\n".join(lines)


def _format_knowledge(knowledge: list[dict[str, object]]) -> str:
    """②Wiki 기존 지식을 프롬프트용 텍스트로 정리한다."""
    if not knowledge:
        return ""
    lines = ["[사용자가 이미 저장해 둔 관련 지식]"]
    for item in knowledge:
        summary = item.get("summary") or item.get("body") or ""
        lines.append(f"- {item.get('title')}: {summary}")
    return "\n".join(lines)


def build_report_context(
    keyword: str,
    fresh: dict[str, object],
    *,
    settings: dict[str, object] | None = None,
    knowledge: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """보고서 생성 입력(report_context)을 조립한다. 없는 입력은 기본값·빈 값으로 채운다."""
    return {
        "keyword": keyword,
        "settings": {**_DEFAULT_SETTINGS, **(settings or {})},
        "knowledge": knowledge or [],
        "fresh": fresh or {},
    }


def generate_report(
    context: dict[str, object], model: str = "gpt-4.1-mini", *, include_sources: bool = True
) -> str:
    """report_context로 개인화된 Markdown 보고서를 생성한다.

    settings의 언어·플랜·개인화 여부를 프롬프트에 반영하고, Wiki 기존 지식과 최신
    자료를 결합한다. 실제 LLM 호출은 summarize.complete로 위임한다.

    include_sources=False면 출처 섹션을 붙이지 않는다(자료 목록을 화면에 이미
    보여주는 비서 페이지에서 중복을 피하기 위함).
    """
    keyword = str(context.get("keyword") or "")
    settings = dict(context.get("settings") or _DEFAULT_SETTINGS)
    knowledge = list(context.get("knowledge") or [])
    fresh = dict(context.get("fresh") or {})

    language = _language_name(str(settings.get("preferred_language", "ko")))
    plan = str(settings.get("plan", "free"))
    personalized = bool(settings.get("personalization_enabled", True))

    depth = (
        "핵심을 충실히 담되 과하게 길지 않게"
        if plan == "free"
        else "배경·비교·시사점까지 깊이 있게"
    )

    knowledge_text = _format_knowledge(knowledge) if personalized else ""
    fresh_text = _format_fresh(fresh)

    guidance = [
        f"주제: {keyword}",
        f"작성 언어: {language}",
        f"분량·깊이: {depth} (플랜: {plan})",
    ]
    if personalized and knowledge_text:
        guidance.append(
            "사용자가 이미 아는 지식(아래 '저장해 둔 관련 지식')은 중복 설명하지 말고, "
            "새로운 변화와 그 지식의 후속 관점으로 연결하라."
        )
    if not personalized:
        guidance.append("개인화가 꺼져 있으므로 중립적으로 요약하라.")

    user_prompt = (
        "\n".join(guidance)
        + "\n\n"
        + (knowledge_text + "\n\n" if knowledge_text else "")
        + "[이번 보고서에 담을 최신 자료]\n"
        + (fresh_text or "(수집된 최신 자료가 없습니다.)")
        + "\n\n위 자료로 개인화된 일간 보고서를 작성하라. "
        + "출처 URL은 본문에 넣지 마라. 출처는 시스템이 따로 붙인다."
    )

    body = complete(_SYSTEM_PROMPT, user_prompt, model=model)
    if not include_sources:
        return body
    # 실제 수집한 자료의 URL만 코드에서 직접 붙여, LLM이 URL을 지어내지 못하게 한다.
    sources = _format_sources(_collect_sources(fresh))
    return f"{body}\n{sources}".rstrip() if sources else body
