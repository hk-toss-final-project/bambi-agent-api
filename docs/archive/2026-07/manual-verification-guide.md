# 수동 검증 지침 — Wiki·관심사 신규 기능 (2026-07-27 구현분)

> 대상: `feature/llm-wiki` 브랜치에 구현된 5개 기능을 **Swagger에서 직접 실행하며** 확인하려는 팀원.
> Swagger 기본 사용법은 저장소 [README의 Agent API 서버 + Swagger 절](../../../README.md#2-agent-api-서버--swagger)을 먼저 보세요.
> 자동 검증은 `uv run pytest`(523개, LLM 무호출)로 이미 커버되어 있고, 이 문서는 눈으로 확인하는 절차입니다.

## 0. 무엇을 검증하나

| # | 기능 | 엔드포인트 | LLM 필요 |
|---|---|---|---|
| A | Wiki Build 완료 시 관심사 자동 재계산 (INT-011 훅) | (내부 동작 — Build 후 `GET .../interests`로 확인) | ✅ (Build 자체가 LLM) |
| B | 관심사 수동 재계산 | `POST .../interest-profiles/rebuild` | ❌ |
| C | 행동 신호 수신 + 점수 반영 (SVC-006 + INT-005) | `POST .../feedback-signals` | ❌ |
| D | 위키마킹 (SVC-004) | `POST .../wiki-sources/content-marks` | 접수 ❌ / 편입 처리 ✅ |
| E | Wiki 문서 삭제 (WBA-015) | `POST .../wiki-sources/deletions` | ❌ |

## 1. 준비 (한 번만)

```bash
cd bambi-agent-api && cp .env.example .env
```

`.env`에서 다음을 설정합니다:

- `AGENT_DB_PASSWORD` — 아무 로컬 값
- `ENABLE_DEV_AGENT_API=true` — Build를 Worker 없이 Swagger에서 실행하기 위해 필요
- `DEV_AGENT_API_TOKEN` — 임의 값 (이후 `/dev` 호출 시 `X-Dev-Token` 헤더로 전달)
- `OPENAI_API_KEY` — **시나리오 2(Build 실행)에만** 필요. 실제 과금 발생 (클리핑 1건당 gpt-4o-mini 수 센트 미만)

DB 시작(Migration + 개발 Seed 자동 반영 — `mock-clipping-user`의 클리핑·대기 Job·생성 후보가 들어옵니다):

```bash
cd bambi-agent-api && sh scripts/start_agent_db.sh
```

서버 실행:

```bash
cd bambi-agent-api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Swagger: <http://127.0.0.1:8000/docs> — 이하 모든 호출은 Swagger의 "Try it out"으로 실행합니다. `user_id`는 시드 사용자 **`mock-clipping-user`** 를 씁니다.

## 2. 시나리오 1 — LLM 없이 확인 (B·C·E 접수/멱등/오류 계약)

아직 Build를 안 돌린 상태 기준입니다.

1. **재계산 전제 확인** — `POST /internal/v1/users/mock-clipping-user/interest-profiles/rebuild` body `{}`
   → 활성 Wiki가 없으므로 **409 `ACTIVE_WIKI_REQUIRED`**. (오류 계약 확인)
2. **행동 신호 저장·멱등** — `POST .../feedback-signals`:
   ```json
   {"signals": [
     {"source_event_id": "sig-1", "signal_type": "like", "topics": ["LangGraph"]},
     {"source_event_id": "sig-2", "signal_type": "hide", "topics": ["Crypto"]}
   ]}
   ```
   → **200, `accepted_count: 2`**. 같은 body 재전송 → **`accepted_count: 0`** (멱등).
   `signal_type: "view"`로 바꿔 전송 → **422** (허용 유형: like/unlike/hide/report).
3. **삭제 404** — `POST .../wiki-sources/deletions` body `{"source_event_id": "del-x", "document_id": "없는-id"}`
   → **404 `WIKI_DOCUMENT_NOT_FOUND`**.
4. **위키마킹 접수** — `GET .../generated-contents`로 시드 생성 후보의 `candidate_id`를 확인한 뒤
   `POST .../wiki-sources/content-marks` body `{"source_event_id": "mark-1", "content_id": "<candidate_id>"}`
   → **202 + job_id** (원본 물질화 + Build Job 등록까지 완료. 편입 처리는 시나리오 2에서).
   존재하지 않는 `content_id` → **404 `GENERATED_CONTENT_NOT_FOUND`**.

## 3. 시나리오 2 — E2E (OPENAI_API_KEY 필요)

1. **시드 클리핑 Build 실행** — `/dev` 태그의 `dev_run_pending_wiki_builds` (`X-Dev-Token` 헤더 필수)
   → 시드로 등록된 대기 Job(시나리오 1-4의 위키마킹 Job 포함)이 순차 실행됩니다. 응답에서 Job별 성공 확인.
2. **A. 자동 재계산 훅 확인** — Build 직후 `GET .../interests`
   → **rebuild를 호출한 적 없는데 활성 프로필이 존재**하면 훅이 동작한 것입니다. 서버 로그에도 `관심사 프로필 자동 재계산 완료 (user=..., version=...)`가 남습니다. 응답의 `version`을 메모하세요.
3. **C. 신호가 점수에 반영되는지** — 시나리오 1-2에서 like한 topic이 실제 관심사 목록에 있는 topic이 되도록, `GET .../interests`에서 topic 하나를 골라 `feedback-signals`로 like 2~3건(각각 다른 `source_event_id`) 전송 → `POST .../interest-profiles/rebuild` → 응답에서:
   - 해당 topic의 `score`가 상승(또는 1위로)했는지
   - `evidence.reasons`에 `behavior:like`, `evidence.behavior_boost` > 0 이 있는지
   - `version`이 2단계 확인 값보다 +1 됐는지 (B. 수동 재계산 검증도 겸함)
4. **E. 삭제** — `GET .../wiki/documents`에서 `document_id` 하나 확보 → `POST .../wiki-sources/deletions`
   → **200, `already_deleted: false`, `unsearchable_chunk_count` ≥ 0** → 같은 문서로 재요청(`source_event_id`만 변경) → **`already_deleted: true`** → `GET .../wiki/documents`에 그 문서가 **더 이상 없음** 확인.
5. **D. 위키마킹 편입 결과** — 1번에서 처리된 위키마킹 Job에 대해 `GET /internal/v1/jobs/{job_id}/result`
   → 결과 payload에 `wiki_version_id`·`affected_documents` 존재 = 생성 콘텐츠가 Wiki 문서로 편입됨. `GET .../wiki/documents`에서 리포트 제목 계열 문서가 늘었는지 확인.

## 4. DB로 직접 확인 (선택)

```bash
docker exec -it $(docker ps -qf name=agent-db) psql -U bambi_agent -d bambi_agent
```

```sql
-- 이벤트가 유형별로 쌓였는지 (content_mark / feedback / delete)
SELECT source_type, status, count(*) FROM agent.wiki_source_events
WHERE user_id = 'mock-clipping-user' GROUP BY 1, 2;

-- 프로필 버전 이력 (자동/수동 재계산마다 +1, active는 항상 1개)
SELECT version, status, wiki_version_id, calculated_at
FROM agent.user_interest_profiles WHERE user_id = 'mock-clipping-user' ORDER BY version;

-- 삭제 반영 (soft-delete + Chunk 검색 제외)
SELECT status, deleted_at FROM agent.wiki_documents WHERE id = '<document_id>';
SELECT is_searchable, count(*) FROM agent.wiki_chunks
WHERE namespace_key = 'user/mock-clipping-user' GROUP BY 1;
```

## 5. 자주 걸리는 것

| 증상 | 원인·해결 |
|---|---|
| `/dev` 호출이 404 | `.env`의 `ENABLE_DEV_AGENT_API=true` 후 서버 재시작 (`APP_ENV=local`이어야 함) |
| `/dev` 호출이 401 | `X-Dev-Token` 헤더가 `DEV_AGENT_API_TOKEN`과 다름 |
| rebuild가 409 | 활성 Wiki가 없음 — 시나리오 2-1의 Build를 먼저 실행 |
| 신호 보냈는데 관심사 그대로 | 정상 — 반영은 재계산 시점(다음 Build 또는 rebuild 호출) |
| Build 실행이 실패 | `OPENAI_API_KEY` 미설정이 대부분. Job 오류는 `GET /internal/v1/jobs/{job_id}`의 `error_code` 확인 |

초기화하고 처음부터 다시 하려면 `docker compose down -v` 후 `sh scripts/start_agent_db.sh`.
