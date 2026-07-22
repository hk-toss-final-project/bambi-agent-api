-- 키워드 비서 이력을 로컬 JSON 파일에서 PostgreSQL로 옮긴다.
--
-- 비서는 개인화를 위해 "이 사용자에게 무엇을 이미 보여줬는지"를 기억해야 하는데,
-- 그동안 data/*.json 파일에 저장했다. 파일 방식은 서버를 여러 대로 늘릴 수 없고,
-- 재배포 시 유실되며, 파일 전체를 읽고 통째로 덮어써서 동시 요청에 취약했다.
--
-- 임베딩은 wiki_embeddings와 같은 vector(1536) 규격을 쓴다(text-embedding-3-small).
-- 파일 방식은 1.6MB 전체를 읽어 파이썬에서 코사인을 계산했지만, 여기서는 최근 N일
-- 행만 DB가 골라 준다.

BEGIN;

-- 1) 수집 이력 — 같은 URL 재수집 방지와 first_seen(발행일 대용) 보관.
CREATE TABLE agent.assistant_collected_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    keyword_normalized text NOT NULL,
    url_key text NOT NULL,
    title text NOT NULL DEFAULT '',
    url text NOT NULL DEFAULT '',
    -- 최초 발견 시각. 재수집해도 덮어쓰지 않는다(새 문서로 오인하지 않기 위해).
    first_seen timestamptz NOT NULL,
    -- 이번 실행에서 계산한 final_score. 주간 트렌드 폴백이 최고 점수 이슈를 고를 때 쓴다.
    score double precision,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (user_id, keyword_normalized, url_key)
);

CREATE INDEX ix_assistant_collected_recent
    ON agent.assistant_collected_documents (user_id, keyword_normalized, first_seen DESC);

-- 2) 보고 이력 — 같은 기사가 다음 리포트에 반복해서 실리는 것을 막는다.
CREATE TABLE agent.assistant_reported_articles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    keyword_normalized text NOT NULL,
    url_key text NOT NULL,
    title text NOT NULL DEFAULT '',
    url text NOT NULL DEFAULT '',
    reported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (user_id, keyword_normalized, url_key)
);

-- 3) 시청 이력 — 사용자가 실제로 클릭한 영상만 기록한다(단순 노출은 제외).
CREATE TABLE agent.assistant_watched_videos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    keyword_normalized text NOT NULL,
    video_id text NOT NULL,
    title text NOT NULL DEFAULT '',
    url text NOT NULL DEFAULT '',
    watched_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (user_id, keyword_normalized, video_id)
);

-- 4) 보고서 임베딩 — 최근 N일 보고 아이템과 유사도를 비교해 중복 소식을 제외한다.
CREATE TABLE agent.assistant_report_embeddings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    keyword_normalized text NOT NULL,
    url_key text NOT NULL,
    title text NOT NULL DEFAULT '',
    embedding vector(1536) NOT NULL,
    reported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (user_id, keyword_normalized, url_key)
);

-- 최근 N일 조회가 유일한 접근 패턴이다.
CREATE INDEX ix_assistant_report_embeddings_recent
    ON agent.assistant_report_embeddings (user_id, keyword_normalized, reported_at DESC);

INSERT INTO agent.schema_migrations (version, description)
VALUES (7, 'Move keyword assistant history from local JSON files to PostgreSQL');

COMMIT;
