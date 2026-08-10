-- 개인 LLM Wiki 초기화 이벤트를 기록하고 취소된 Build의 지연 저장을 차단한다.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.wiki_source_events
    DROP CONSTRAINT wiki_source_events_source_type_check;

ALTER TABLE agent.wiki_source_events
    ADD CONSTRAINT wiki_source_events_source_type_check
        CHECK (source_type IN (
            'web_clipping', 'url', 'content_mark', 'content_save', 'memo',
            'edit', 'conversation', 'feedback', 'delete', 'rebuild',
            'onboarding_seed', 'reset'
        ));

CREATE FUNCTION agent.reject_cancelled_wiki_build()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.created_by_job_id IS NOT NULL AND EXISTS (
        SELECT 1
        FROM agent.agent_jobs AS job
        WHERE job.id = NEW.created_by_job_id
          AND job.job_type = 'personal_wiki_build'
          AND job.status = 'cancelled'
    ) THEN
        RAISE EXCEPTION '취소된 Personal Wiki Build는 결과를 저장할 수 없습니다.'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER reject_cancelled_wiki_build_before_version_write
    BEFORE INSERT OR UPDATE OF created_by_job_id
    ON agent.wiki_document_versions
    FOR EACH ROW EXECUTE FUNCTION agent.reject_cancelled_wiki_build();

INSERT INTO agent.schema_migrations (version, description)
VALUES (18, 'Reset personal LLM Wiki and reject cancelled build writes');

COMMIT;
