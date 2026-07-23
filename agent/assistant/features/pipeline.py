"""일간 수집→선별→통합요약 파이프라인 오케스트레이터.

명세의 처리 순서를 구현한다:

  수집(기존 소스, 최근 N일) → 날짜 추출 → 기초 필터(스팸/짧은 글/URL 중복)
  → 임베딩 → 유사도 필터 → 클러스터링 → 스코어링
  → 최근 7일 보고서와 중복 검사 → 임계값 판정
  → [통과] 클러스터 통합 요약 생성 (Daily)
  → [미달] 워터폴 폴백 (주간 트렌드 → 에버그린)
  → 보고서 아이템 임베딩을 중복 방지 이력에 저장

수집 소스는 기존 그대로(Google News RSS, YouTube, Reddit) 유지하고, 이 모듈은
"수집 후 선별"만 담당한다. 각 단계에서 제외된 문서와 사유를 log에 남겨 임계값
튜닝에 쓸 수 있게 한다. 스코어링·중복 제거는 scoring/dedup 모듈에 분리돼 있어
나중에 wiki 저장소가 붙어도 재사용할 수 있다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from agent.assistant.features import clustering, config, dedup, feeds, history, reddit, scoring, youtube
from agent.assistant.features.dates import extract_published
from agent.assistant.features.embeddings import embed_texts
from agent.assistant.features.summarize import complete

logger = logging.getLogger("agent.assistant.features.pipeline")

# 수집 단계에서 소스별로 확보할 후보 풀 크기.
_NEWS_POOL = 30
_YOUTUBE_POOL = 18
_REDDIT_POOL = 10

# 통합 요약 프롬프트에 넣을 클러스터 문서당 최대 문자 수.
_SUMMARY_DOC_CHARS = 1500

_CLUSTER_SUMMARY_SYSTEM = (
    "너는 여러 문서를 하나의 인사이트로 통합 요약하는 한국어 비서다. "
    "제공된 문서들에 있는 내용만 사용하고, 없는 사실을 지어내지 않는다."
)


def _exclude(log: dict[str, object], stage: str, doc: dict[str, object], reason: str) -> None:
    """문서 제외 사실을 파이프라인 로그와 로거에 남긴다."""
    entry = {
        "stage": stage,
        "reason": reason,
        "title": str(doc.get("title") or ""),
        "url": str(doc.get("url") or ""),
    }
    exclusions = log.setdefault("exclusions", [])
    assert isinstance(exclusions, list)
    exclusions.append(entry)
    logger.info("제외[%s/%s] %s (%s)", stage, reason, entry["title"], entry["url"])


def _news_documents(keyword: str, now: datetime) -> list[dict[str, object]]:
    """Google News RSS에서 후보 문서를 수집한다 (날짜 추출 전 원시 상태)."""
    entries = feeds.fetch_feed_entries(feeds.build_news_feed_url(keyword))
    unique = feeds.deduplicate(entries)[:_NEWS_POOL]
    docs: list[dict[str, object]] = []
    for entry in unique:
        title = str(entry.get("title") or "")
        url = str(entry.get("link") or "")
        snippet = feeds._clean_text(entry, None, 500)
        docs.append(
            {
                "source_type": "news",
                "title": title,
                "url": url,
                "url_key": feeds.canonical_url(url),
                "text": f"{title}\n{snippet}".strip(),
                "published_ts": entry.get("published_ts", 0),
                "published_raw": entry.get("published", ""),
                # url은 Google News 리다이렉트 주소라 도메인이 전부 news.google.com이다.
                # 소스 신뢰도는 원본 발행처 URL로 판정해야 한다.
                "source_url": entry.get("source_url", ""),
                "source_name": entry.get("source_name", ""),
            }
        )
    return docs


def _youtube_documents(keyword: str, now: datetime, window_hours: float) -> list[dict[str, object]]:
    """YouTube 검색에서 후보 문서를 수집한다. 상대 시간을 발행일 근사치로 환산한다."""
    pool = youtube.search_videos(keyword, limit=_YOUTUBE_POOL)
    docs: list[dict[str, object]] = []
    for video in pool:
        age_hours = youtube._relative_age_hours(str(video.get("published_time") or ""))
        if age_hours is None or age_hours > window_hours:
            continue
        title = str(video.get("title") or "")
        url = str(video.get("url") or "")
        video_id = str(video.get("video_id") or "")
        # canonical_url은 query를 제거하므로 watch URL(?v=...)이 전부 같은 key로
        # 뭉개져 첫 영상 외에는 중복으로 오판된다. 유튜브는 영상 식별자가 query에
        # 있으므로 video_id 기반 key를 써서 영상별로 구분한다.
        url_key = f"https://www.youtube.com/watch?v={video_id}" if video_id else feeds.canonical_url(url)
        docs.append(
            {
                "source_type": "youtube",
                "title": title,
                "url": url,
                "url_key": url_key,
                "text": f"{title}\n{video.get('channel') or ''}".strip(),
                "published_ts": (now - timedelta(hours=age_hours)).timestamp(),
                "published_raw": str(video.get("published_time") or ""),
                "video_id": video.get("video_id"),
                "thumbnail_url": video.get("thumbnail_url"),
            }
        )
    return docs


def _reddit_documents(keyword: str, now: datetime, window_hours: float) -> list[dict[str, object]]:
    """Reddit 검색에서 후보 문서를 수집한다."""
    posts = reddit.search_posts(
        keyword, limit=_REDDIT_POOL, max_age_hours=window_hours, reference_now=now
    )
    docs: list[dict[str, object]] = []
    for post in posts:
        title = str(post.get("title") or "")
        url = str(post.get("url") or "")
        body = str(post.get("body") or "")
        docs.append(
            {
                "source_type": "reddit",
                "title": title,
                "url": url,
                "url_key": feeds.canonical_url(url),
                "text": f"{title}\n{body[:500]}".strip(),
                "published_ts": post.get("published_ts", 0),
                "published_raw": str(post.get("published") or ""),
                "body": body,
            }
        )
    return docs


# 수집을 시도하는 소스 수(뉴스·YouTube·Reddit). "몇 개가 실패했는지"를 판단할 때
# 분모로 쓴다. 소스를 늘리면 이 값도 함께 늘어난다.
SOURCE_COUNT = 3


def collect_documents(
    keyword: str,
    *,
    now: datetime,
    window_hours: float,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """세 소스(뉴스·YouTube·Reddit)에서 후보 문서를 모은다.

    소스별 실패를 격리해, 한 소스가 실패해도 나머지 문서는 그대로 반환한다.
    실패는 사람이 읽는 문자열이 아니라 {source, error} 구조로 돌려준다 — 호출자가
    "외부 장애인지, 검색어가 나쁜 건지"를 문자열 파싱 없이 판정할 수 있어야
    재시도 여부를 올바르게 정할 수 있기 때문이다.

    Returns:
        (문서 목록, 실패 목록[{source, error}])
    """
    docs: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    collectors = (
        ("뉴스", lambda: _news_documents(keyword, now)),
        ("YouTube", lambda: _youtube_documents(keyword, now, window_hours)),
        ("Reddit", lambda: _reddit_documents(keyword, now, window_hours)),
    )
    for label, collector in collectors:
        try:
            docs.extend(collector())
        except Exception as error:
            failures.append({"source": label, "error": f"{type(error).__name__}: {error}"})
    return docs, failures


def _resolve_dates(
    docs: list[dict[str, object]],
    *,
    user_id: str,
    keyword: str,
    now: datetime,
) -> None:
    """각 문서의 발행일을 폴백 체인으로 확정하고 first_seen을 기록한다 (제자리 수정).

    발행일 추출이 전부 실패하면 first_seen(최초 발견 시각)을 발행일 대용으로 쓴다.
    본문 HTML은 수집 단계에서 확보하지 않으므로 pubDate → URL 패턴 → first_seen
    순으로 동작한다(메타태그·본문 파싱 단계는 HTML이 있을 때만 작동한다).
    """
    for doc in docs:
        published, method = extract_published(
            published_ts=doc.get("published_ts"),  # type: ignore[arg-type]
            html=str(doc.get("html") or ""),
            url=str(doc.get("url") or ""),
        )
        first_seen = history.record_collected(
            user_id,
            keyword,
            str(doc.get("url_key") or ""),
            str(doc.get("title") or ""),
            str(doc.get("url") or ""),
            first_seen=now,
        )
        doc["first_seen"] = first_seen
        if published is None:
            published, method = first_seen, "first_seen"
        doc["published"] = published
        doc["published_method"] = method


def _basic_filter(
    docs: list[dict[str, object]],
    *,
    now: datetime,
    window_hours: float,
    log: dict[str, object],
) -> list[dict[str, object]]:
    """기초 필터: URL 중복(당일·과거 수집분)·짧은 글·수집 창 밖 문서를 제외한다."""
    today = now.date()
    seen_keys: set[str] = set()
    kept: list[dict[str, object]] = []
    for doc in docs:
        url_key = str(doc.get("url_key") or "")
        if not url_key:
            _exclude(log, "basic_filter", doc, "no_url")
            continue
        if url_key in seen_keys:
            _exclude(log, "basic_filter", doc, "duplicate_url")
            continue
        first_seen = doc.get("first_seen")
        if isinstance(first_seen, datetime) and first_seen.date() < today:
            # 이전 실행에서 이미 수집한 URL은 재수집하지 않는다.
            _exclude(log, "basic_filter", doc, "url_already_collected")
            continue
        if len(str(doc.get("text") or "")) < config.MIN_DOC_CHARS:
            _exclude(log, "basic_filter", doc, "too_short")
            continue
        published = doc.get("published")
        if isinstance(published, datetime) and published < now - timedelta(hours=window_hours):
            # 몇 년 전 문서 등 수집 창 밖 문서를 차단한다.
            _exclude(log, "basic_filter", doc, "outside_window")
            continue
        seen_keys.add(url_key)
        kept.append(doc)
    return kept


def _cluster_context_text(cluster_docs: list[dict[str, object]]) -> str:
    """클러스터 문서들을 통합 요약 프롬프트에 넣을 텍스트로 정리한다."""
    lines: list[str] = []
    for index, doc in enumerate(cluster_docs, start=1):
        text = str(doc.get("text") or "")[:_SUMMARY_DOC_CHARS]
        lines.append(f"[문서 {index}] ({doc.get('source_type')}) {text}")
    return "\n\n".join(lines)


def summarize_cluster(
    keyword: str,
    cluster_docs: list[dict[str, object]],
    model: str = "gpt-4.1-mini",
) -> str:
    """같은 클러스터의 문서들을 하나의 아티클로 통합 요약한다.

    개별 요약 대신 클러스터 전체를 컨텍스트로 주고, 공통 맥락을 하나의
    인사이트로 정리하게 한다.
    """
    user_prompt = (
        f"주제: {keyword}\n\n"
        "아래 문서들은 같은 이슈를 다루는 것으로 묶인 문서들이다. "
        "이 문서들의 공통 맥락을 하나의 인사이트로 요약하라. "
        "한국어 두세 문장의 줄글로 쓰고, 문서 간 차이(추가 정보·상반된 관점)가 있으면 "
        "한 문장으로 덧붙여라.\n\n" + _cluster_context_text(cluster_docs)
    )
    return complete(_CLUSTER_SUMMARY_SYSTEM, user_prompt, model=model)


def _build_clusters(
    docs: list[dict[str, object]],
    doc_embeddings: list[list[float]],
    similarities: list[float],
    *,
    now: datetime,
    cold_start: bool,
) -> list[dict[str, object]]:
    """클러스터링과 스코어링을 수행해 클러스터 목록을 만든다.

    각 클러스터는 대표 문서(최고 final_score)와 대표 점수(클러스터 내 최고
    final_score), cluster_boost가 반영된 멤버 점수를 가진다.
    """
    groups = clustering.greedy_clusters(doc_embeddings)
    clusters: list[dict[str, object]] = []
    for group in groups:
        boost = scoring.cluster_boost(len(group))
        members: list[dict[str, object]] = []
        for index in group:
            doc = docs[index]
            score = scoring.score_document(
                doc, similarities[index], boost=boost, now=now, cold_start=cold_start
            )
            members.append({**doc, "score": score, "embedding": doc_embeddings[index]})
        representative = max(members, key=lambda m: m["score"]["final_score"])
        clusters.append(
            {
                "members": members,
                "representative": representative,
                "size": len(members),
                "final_score": representative["score"]["final_score"],
            }
        )
    return clusters


def _weekly_trend_items(
    user_id: str,
    keyword: str,
    *,
    now: datetime,
) -> list[dict[str, object]]:
    """주간 트렌드 폴백: 최근 WEEKLY_TREND_DAYS일 수집분 중 최고 점수 이슈를 고른다."""
    cutoff = now - timedelta(days=config.WEEKLY_TREND_DAYS)
    entries = history.get_collected_entries(user_id, keyword)
    candidates: list[dict[str, object]] = []
    for url_key, entry in entries.items():
        try:
            first_seen = datetime.fromisoformat(str(entry.get("first_seen") or ""))
        except ValueError:
            continue
        if first_seen < cutoff:
            continue
        score = entry.get("score")
        if score is None:
            continue
        candidates.append(
            {
                "url_key": url_key,
                "title": str(entry.get("title") or ""),
                "url": str(entry.get("url") or ""),
                "score": float(score),  # type: ignore[arg-type]
                "first_seen": first_seen,
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[: config.MAX_DAILY_ITEMS]


def run_daily(
    keyword: str,
    user_id: str,
    *,
    model: str = "gpt-4.1-mini",
    reference_now: datetime | None = None,
    search_query: str | None = None,
) -> dict[str, object]:
    """일간 파이프라인 전체를 실행하고 보고서 소재를 반환한다.

    Args:
        keyword: 사용자 관심 토픽. 이력·중복 제거의 키이자 유사도 채점 기준이다.
        user_id: 사용자 식별자
        model: 통합 요약에 쓸 OpenAI 모델
        reference_now: "지금" 기준 시각(테스트용). 생략하면 실제 현재 시각.
        search_query: 수집기(뉴스·YouTube·Reddit)에 실제로 던질 검색어. 생략하면
            keyword를 그대로 쓴다. 에이전트가 결과가 빈약할 때 검색어를 재구성해
            넘기더라도, 이력·중복·유사도는 여전히 keyword(토픽) 기준으로 판단해
            개인화·중복 방지 일관성이 유지된다(검색만 넓히고 채점은 토픽 기준).

    Returns:
        {
          keyword, user_id, mode("daily"|"weekly"|"evergreen"), cold_start,
          items: [ {title, summary, sources, published, score, reason, status,
                    cluster_size} ... ]   # weekly면 {title, url, score}, evergreen이면 []
          log: {collected, exclusions: [{stage, reason, title, url}], ...},
          errors: [str]
        }
    """
    normalized = keyword.strip()
    if not normalized:
        raise ValueError("키워드가 비어 있습니다.")
    normalized_user = user_id.strip()
    if not normalized_user:
        raise ValueError("사용자 식별자가 비어 있습니다.")
    # 수집에 쓸 검색어는 토픽과 다를 수 있다(에이전트 재구성). 비면 토픽으로 되돌린다.
    query = (search_query or "").strip() or normalized

    now = reference_now or datetime.now(UTC)
    window_hours = config.collect_window_hours()
    log: dict[str, object] = {"exclusions": [], "search_query": query}

    # 콜드 스타트 판정은 수집 기록(first_seen 기록)이 일어나기 전에 해야 한다.
    cold_start = not history.has_collect_history(normalized_user, normalized)
    log["cold_start"] = cold_start

    # 1. 수집 (기존 소스, 최근 N일). 검색은 query로, 채점은 topic(normalized) 기준.
    docs, source_failures = collect_documents(query, now=now, window_hours=window_hours)
    # 실패는 구조(log)와 사람이 읽는 문장(errors) 양쪽에 남긴다. 앞의 것은 재시도
    # 판정용, 뒤의 것은 화면 표시용이다.
    errors = [
        f"{failure['source']} 수집 실패: {failure['error']}" for failure in source_failures
    ]
    log["source_attempted"] = SOURCE_COUNT
    log["source_failures"] = [failure["source"] for failure in source_failures]
    log["collected"] = len(docs)

    # 2. 날짜 추출 (+ first_seen 기록)
    _resolve_dates(docs, user_id=normalized_user, keyword=normalized, now=now)

    # 3. 기초 필터 (스팸/짧은 글/URL 중복/수집 창 밖)
    docs = _basic_filter(docs, now=now, window_hours=window_hours, log=log)
    log["after_basic_filter"] = len(docs)

    # 4. 임베딩 (토픽 + 문서를 한 번에)
    daily_clusters: list[dict[str, object]] = []
    if docs:
        try:
            vectors = embed_texts([normalized] + [str(doc.get("text") or "") for doc in docs])
        except Exception as error:
            # 임베딩(OpenAI) 장애도 "검색어가 나쁨"이 아니라 외부 장애다. 재시도
            # 판정이 문자열을 파싱하지 않도록 구조화된 플래그로도 남긴다.
            log["embedding_failed"] = True
            errors.append(f"임베딩 실패: {type(error).__name__}: {error}")
            vectors = []
        if vectors:
            topic_embedding, doc_embeddings = vectors[0], vectors[1:]

            # 5. 유사도 필터 (이번 실행 최고 유사도에 상대적인 컷)
            from agent.assistant.features.embeddings import cosine_similarity

            scored = [
                (doc, embedding, cosine_similarity(topic_embedding, embedding))
                for doc, embedding in zip(docs, doc_embeddings, strict=True)
            ]
            # 컷을 이번 실행의 최고 유사도로부터 계산한다. 키워드마다 유사도 스케일이
            # 달라 고정 임계값으로는 어떤 키워드가 통째로 탈락하기 때문이다.
            sim_cutoff = config.similarity_cutoff(max(s for _, _, s in scored))
            log["similarity_cutoff"] = round(sim_cutoff, 4)

            filtered_docs: list[dict[str, object]] = []
            filtered_embeddings: list[list[float]] = []
            similarities: list[float] = []
            for doc, embedding, sim in scored:
                if sim < sim_cutoff:
                    _exclude(
                        log,
                        "similarity_filter",
                        doc,
                        f"low_similarity({sim:.2f} < {sim_cutoff:.2f})",
                    )
                    continue
                filtered_docs.append(doc)
                filtered_embeddings.append(embedding)
                similarities.append(sim)
            log["after_similarity_filter"] = len(filtered_docs)

            # 6. 클러스터링 + 7. 스코어링
            clusters = _build_clusters(
                filtered_docs, filtered_embeddings, similarities, now=now, cold_start=cold_start
            )
            log["clusters"] = len(clusters)

            # 수집 이력에 점수를 기록해 주간 트렌드 폴백에서 쓸 수 있게 한다.
            for cluster in clusters:
                for member in cluster["members"]:
                    history.record_collected(
                        normalized_user,
                        normalized,
                        str(member.get("url_key") or ""),
                        str(member.get("title") or ""),
                        str(member.get("url") or ""),
                        first_seen=member.get("first_seen"),  # type: ignore[arg-type]
                        score=member["score"]["final_score"],
                    )

            # 8. 최근 7일 보고서와 중복 검사
            history_items = dedup.load_recent_report_items(
                normalized_user, normalized, now=now, exclude_today=True
            )
            for cluster in clusters:
                rep = cluster["representative"]
                status, matched, sim = dedup.check_duplicate(
                    rep["embedding"],
                    rep.get("published") if isinstance(rep.get("published"), datetime) else None,
                    history_items,
                )
                cluster["dup_status"] = status
                if status == dedup.STATUS_DUPLICATE:
                    matched_title = str((matched or {}).get("title") or "")
                    _exclude(
                        log,
                        "dedup",
                        rep,
                        f"already_reported({sim:.2f}, 기존: {matched_title[:30]})",
                    )

            survivors = [c for c in clusters if c["dup_status"] != dedup.STATUS_DUPLICATE]

            # 9. 임계값 판정 (미달 아이템을 억지로 채우지 않는다)
            # 유사도와 같은 이유로 상대 기준을 쓴다. final_score는 similarity를
            # 곱해 만들므로 유사도 스케일 차이를 그대로 물려받기 때문이다.
            if survivors:
                pub_cutoff = config.publish_cutoff(max(c["final_score"] for c in survivors))
                log["publish_cutoff"] = round(pub_cutoff, 4)
                for cluster in survivors:
                    if cluster["final_score"] < pub_cutoff:
                        _exclude(
                            log,
                            "threshold",
                            cluster["representative"],
                            f"below_threshold({cluster['final_score']:.2f} < {pub_cutoff:.2f})",
                        )
                daily_clusters = sorted(
                    (c for c in survivors if c["final_score"] >= pub_cutoff),
                    key=lambda c: c["final_score"],
                    reverse=True,
                )[: config.MAX_DAILY_ITEMS]

    # 10. 워터폴 판정과 아이템 조립
    if daily_clusters:
        mode = "daily"
        items = []
        for cluster in daily_clusters:
            rep = cluster["representative"]
            published = rep.get("published")
            try:
                summary = summarize_cluster(normalized, cluster["members"], model=model)
            except Exception as error:
                errors.append(f"통합 요약 실패: {type(error).__name__}: {error}")
                summary = str(rep.get("text") or "")[:300]
            status = "업데이트" if cluster.get("dup_status") == dedup.STATUS_UPDATE else "신규"
            items.append(
                {
                    "title": str(rep.get("title") or ""),
                    "summary": summary,
                    "sources": [
                        {
                            "title": str(m.get("title") or ""),
                            "url": str(m.get("url") or ""),
                            "source_type": str(m.get("source_type") or ""),
                        }
                        for m in cluster["members"]
                    ],
                    "published": published.isoformat() if isinstance(published, datetime) else "",
                    "published_method": str(rep.get("published_method") or ""),
                    "score": round(cluster["final_score"], 4),
                    "score_detail": rep["score"],
                    "reason": (
                        f"final_score {cluster['final_score']:.2f} ≥ 기준 "
                        f"{log.get('publish_cutoff')} (클러스터 {cluster['size']}건)"
                    ),
                    "status": status,
                    "cluster_size": cluster["size"],
                    "url_key": str(rep.get("url_key") or ""),
                    "embedding": rep["embedding"],
                }
            )
        # 11. 보고서 아이템 임베딩을 중복 방지 이력에 저장 (같은 url_key는 덮어씀)
        dedup.record_report_items(normalized_user, normalized, items, now=now)
        # 반환 아이템에서 임베딩은 제거한다 (보고서 렌더링에 불필요).
        for item in items:
            item.pop("embedding", None)
    else:
        weekly = _weekly_trend_items(normalized_user, normalized, now=now)
        if weekly:
            mode = "weekly"
            items = weekly
        else:
            mode = "evergreen"
            items = []

    log["mode"] = mode
    logger.info(
        "파이프라인 완료: keyword=%s mode=%s items=%d 제외=%d",
        normalized,
        mode,
        len(items),
        len(log["exclusions"]),  # type: ignore[arg-type]
    )
    return {
        "keyword": normalized,
        "user_id": normalized_user,
        "mode": mode,
        "cold_start": cold_start,
        "items": items,
        "log": log,
        "errors": errors,
    }
