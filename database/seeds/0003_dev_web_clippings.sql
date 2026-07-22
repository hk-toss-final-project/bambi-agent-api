-- 이 파일은 scripts/generate_web_clipping_seed.py가 dummy/clippings에서 생성한다.
-- 직접 수정하지 말고 원본 Markdown을 바꾼 뒤 Generator를 다시 실행한다.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL app.access_scope = 'system';

DELETE FROM agent.agent_job_attempts
WHERE job_id IN (
    'ecbd990d-fd2c-534b-b8ca-c4f6b147cfb5',
    '2a30aed2-a7bf-5e99-872d-00a0db75deee',
    'e6445fbc-66e3-5324-9e22-5c2170fbb2b8',
    '3d210ceb-1ff5-5b68-ac5e-d32683e72ccd',
    'a5e3fd9d-9d64-58aa-a7c5-00fe1c76bfc8',
    'd20ce88a-50ae-5918-8b26-ac253c992fe4',
    '1fa84a47-90aa-5e53-a18a-a8c0abe9514d',
    'aebc6368-807f-523b-a38d-b52ae12192e3',
    '635b290b-e40d-5efa-996e-706b6bec54ab',
    '5bf75415-9e99-5572-9990-4d056c1880cf',
    '94f8fbe5-dc35-5306-9fed-6da7c1a7fcdd',
    '6dd27e13-6147-560d-a148-f991daadc7ed',
    'a4b4940b-3992-5271-b26d-8d50cbe911fb',
    '7dbb5e19-69c3-5dca-b5bf-86c6cb0d3835',
    '210b9531-f35a-5c85-91ae-2dbdf082f493',
    '4c8ad9ce-cc34-5f69-a9c6-7c67618ec3ff',
    '1910418f-3e0d-5376-892b-e48fcdc8fd66',
    '886f57fb-266d-5b05-befe-9f6cb20e6acf',
    'c2fcaf08-275d-50f2-8e63-e487fb530287',
    '51defb75-4ac1-51e7-a7c2-1f0ce9c634b1'
);

-- 같은 원본으로 이전에 생성한 LLM Wiki 결과 중 Citation이 참조하지 않는 문서를 제거한다.
DELETE FROM agent.wiki_documents AS document
WHERE document.id IN (
    SELECT version.document_id
    FROM agent.wiki_document_versions AS version
    WHERE version.created_by_job_id IN (
        'ecbd990d-fd2c-534b-b8ca-c4f6b147cfb5',
    '2a30aed2-a7bf-5e99-872d-00a0db75deee',
    'e6445fbc-66e3-5324-9e22-5c2170fbb2b8',
    '3d210ceb-1ff5-5b68-ac5e-d32683e72ccd',
    'a5e3fd9d-9d64-58aa-a7c5-00fe1c76bfc8',
    'd20ce88a-50ae-5918-8b26-ac253c992fe4',
    '1fa84a47-90aa-5e53-a18a-a8c0abe9514d',
    'aebc6368-807f-523b-a38d-b52ae12192e3',
    '635b290b-e40d-5efa-996e-706b6bec54ab',
    '5bf75415-9e99-5572-9990-4d056c1880cf',
    '94f8fbe5-dc35-5306-9fed-6da7c1a7fcdd',
    '6dd27e13-6147-560d-a148-f991daadc7ed',
    'a4b4940b-3992-5271-b26d-8d50cbe911fb',
    '7dbb5e19-69c3-5dca-b5bf-86c6cb0d3835',
    '210b9531-f35a-5c85-91ae-2dbdf082f493',
    '4c8ad9ce-cc34-5f69-a9c6-7c67618ec3ff',
    '1910418f-3e0d-5376-892b-e48fcdc8fd66',
    '886f57fb-266d-5b05-befe-9f6cb20e6acf',
    'c2fcaf08-275d-50f2-8e63-e487fb530287',
    '51defb75-4ac1-51e7-a7c2-1f0ce9c634b1'
    )
    UNION
    SELECT version.document_id
    FROM agent.wiki_document_versions AS version
    JOIN agent.wiki_document_sources AS source_link
      ON source_link.wiki_document_version_id = version.id
    WHERE source_link.source_document_version_id IN (
        '19c0e199-dbaf-55bb-b0a0-f66a5fe2dc06',
    'cda80c02-05ca-5dd9-bd32-efed2282e604',
    '34061cbd-0b49-5005-9f40-960fab0a07fd',
    '48bf8490-ccd5-58e0-a107-d5f420403a9d',
    '18a337a3-b153-5f59-9f4a-5b7a34aec6c4',
    'c2e9e879-bce6-550d-a450-2edbba833a2b',
    '904c18f9-bd6b-5194-bbac-ac1b4d99db57',
    '2a3accae-e4de-5b9a-8b93-7124c4a43c69',
    '74f990c5-6ff7-51ae-b52e-feb27f85dbb6',
    'd64c529c-c116-5fde-aa18-13f612d83177',
    '9c80d01d-fcb5-53c5-b3e4-15475d616bcb',
    'c38832b0-82a1-5a46-8d64-a032851f64cc',
    'b81b1a08-b452-5d0f-802a-f3e057b0fd10',
    '5839f933-0f1e-5725-b1ee-4b8b6bc9daf1',
    'f41a0e0f-b365-50be-9e45-8bbf719b01b4',
    '67cd85c7-a26e-5a47-bc1c-721dc4e797e1',
    '46de6572-7a89-53c3-bb05-f17be9e4b881',
    '3ad29bdd-8eb9-5456-ab23-d199712788cf',
    '3dde7d81-7e29-574e-a8a9-9cab9108c967',
    '2da2e793-94b4-5d5e-93b3-d16bce40372e'
    )
)
AND NOT EXISTS (
    SELECT 1
    FROM agent.wiki_document_versions AS version
    JOIN agent.citations AS citation
      ON citation.document_version_id = version.id
    WHERE version.document_id = document.id
)
AND NOT EXISTS (
    SELECT 1
    FROM agent.wiki_document_versions AS version
    JOIN agent.wiki_chunks AS chunk
      ON chunk.document_version_id = version.id
    JOIN agent.citations AS citation
      ON citation.chunk_id = chunk.id
    WHERE version.document_id = document.id
);

DELETE FROM agent.user_interest_profiles
WHERE user_id = 'mock-clipping-user';

DELETE FROM agent.wiki_versions
WHERE user_id = 'mock-clipping-user';

INSERT INTO agent.user_context_snapshots (
    id,
    user_id,
    context_version,
    plan,
    preferred_language,
    personalization_enabled,
    attributes
) VALUES (
    'c2cc48ec-c2bd-5960-bc28-c2e2310bb7d8',
    'mock-clipping-user',
    1,
    'free',
    'ko',
    true,
    '{"seed":true,"source":"dummy/clippings"}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    plan = EXCLUDED.plan,
    preferred_language = EXCLUDED.preferred_language,
    personalization_enabled = EXCLUDED.personalization_enabled,
    attributes = EXCLUDED.attributes;

INSERT INTO agent.agent_jobs (
    id,
    feature_id,
    job_type,
    user_id,
    idempotency_key,
    status,
    progress,
    payload,
    retryable,
    scheduled_at
) VALUES
    (
        'ecbd990d-fd2c-534b-b8ca-c4f6b147cfb5',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_f4b6cd1ce13b$dummy-clipping-15500a59e7991fdc$seed_f4b6cd1ce13b$,
        'queued',
        0,
        $seed_37d48ed3faaf${"content_format":"markdown","seed":true,"source_document_id":"d931d233-ab2c-5db9-bed4-62d3bc9b2eda","source_document_version_id":"19c0e199-dbaf-55bb-b0a0-f66a5fe2dc06","source_event_id":"dummy-clipping-15500a59e7991fdc","source_event_row_id":"bb1bece7-496d-54e2-978b-d93b5d7a1f83"}$seed_37d48ed3faaf$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '2a30aed2-a7bf-5e99-872d-00a0db75deee',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_6a581e78638a$dummy-clipping-ea76873a77dbdc4a$seed_6a581e78638a$,
        'queued',
        0,
        $seed_03aa1f831995${"content_format":"markdown","seed":true,"source_document_id":"838a6107-36c0-5c9c-a868-d69d35900f00","source_document_version_id":"cda80c02-05ca-5dd9-bd32-efed2282e604","source_event_id":"dummy-clipping-ea76873a77dbdc4a","source_event_row_id":"47c42f80-5a6b-5024-a8fd-63db68cb3b66"}$seed_03aa1f831995$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        'e6445fbc-66e3-5324-9e22-5c2170fbb2b8',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_9f7143726fa9$dummy-clipping-cba1e0c7afcb8817$seed_9f7143726fa9$,
        'queued',
        0,
        $seed_94fbb3c5b4ec${"content_format":"markdown","seed":true,"source_document_id":"1cea6d42-3b5d-5015-bb32-0958a7751657","source_document_version_id":"34061cbd-0b49-5005-9f40-960fab0a07fd","source_event_id":"dummy-clipping-cba1e0c7afcb8817","source_event_row_id":"7a0fda6a-88f6-520a-b6ff-a45cdef2eec4"}$seed_94fbb3c5b4ec$::jsonb,
        true,
        '2026-07-14T00:00:00Z'::timestamptz
    ),
    (
        '3d210ceb-1ff5-5b68-ac5e-d32683e72ccd',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_bef32affdd15$dummy-clipping-ee2eab4f35a2124a$seed_bef32affdd15$,
        'queued',
        0,
        $seed_a238d9aee05c${"content_format":"markdown","seed":true,"source_document_id":"4d038e7b-ba87-5191-8b39-3f8031c29156","source_document_version_id":"48bf8490-ccd5-58e0-a107-d5f420403a9d","source_event_id":"dummy-clipping-ee2eab4f35a2124a","source_event_row_id":"1ffdcc29-4e8e-5d49-9215-1a9f16465da8"}$seed_a238d9aee05c$::jsonb,
        true,
        '2026-07-14T00:00:00Z'::timestamptz
    ),
    (
        'a5e3fd9d-9d64-58aa-a7c5-00fe1c76bfc8',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_b0a0469189d5$dummy-clipping-982cfa5551fe4d2d$seed_b0a0469189d5$,
        'queued',
        0,
        $seed_85fadbf292d6${"content_format":"markdown","seed":true,"source_document_id":"34d3e582-ae77-5771-8ea9-a3b5c97b9c16","source_document_version_id":"18a337a3-b153-5f59-9f4a-5b7a34aec6c4","source_event_id":"dummy-clipping-982cfa5551fe4d2d","source_event_row_id":"b33e13cf-f6a3-5576-b6bc-42739ede5d41"}$seed_85fadbf292d6$::jsonb,
        true,
        '2026-07-14T00:00:00Z'::timestamptz
    ),
    (
        'd20ce88a-50ae-5918-8b26-ac253c992fe4',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_0fcb7fb9e15e$dummy-clipping-b23c6cd7d698dd14$seed_0fcb7fb9e15e$,
        'queued',
        0,
        $seed_8d4c91cd0cc0${"content_format":"markdown","seed":true,"source_document_id":"de6a9b37-5768-58b3-810d-abda084d2b09","source_document_version_id":"c2e9e879-bce6-550d-a450-2edbba833a2b","source_event_id":"dummy-clipping-b23c6cd7d698dd14","source_event_row_id":"81a4db80-87f3-5d28-aed7-cc2fcad723ac"}$seed_8d4c91cd0cc0$::jsonb,
        true,
        '2026-07-14T00:00:00Z'::timestamptz
    ),
    (
        '1fa84a47-90aa-5e53-a18a-a8c0abe9514d',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_9a53ccd76a7f$dummy-clipping-11217e97399022d9$seed_9a53ccd76a7f$,
        'queued',
        0,
        $seed_f36a4fbf95c0${"content_format":"markdown","seed":true,"source_document_id":"ab13f7cb-6ba9-564c-b34a-d1fceb12705f","source_document_version_id":"904c18f9-bd6b-5194-bbac-ac1b4d99db57","source_event_id":"dummy-clipping-11217e97399022d9","source_event_row_id":"c54ea45c-c83a-55b1-93c3-1c33e2088a04"}$seed_f36a4fbf95c0$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        'aebc6368-807f-523b-a38d-b52ae12192e3',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_0561f66919db$dummy-clipping-b8e4b739e6b4909e$seed_0561f66919db$,
        'queued',
        0,
        $seed_f9d0712a44c6${"content_format":"markdown","seed":true,"source_document_id":"639fd91e-b8fa-5942-85bb-b8a019c9d119","source_document_version_id":"2a3accae-e4de-5b9a-8b93-7124c4a43c69","source_event_id":"dummy-clipping-b8e4b739e6b4909e","source_event_row_id":"aacc66c8-bd08-538c-92dd-ed48cf4ccc50"}$seed_f9d0712a44c6$::jsonb,
        true,
        '2026-07-14T00:00:00Z'::timestamptz
    ),
    (
        '635b290b-e40d-5efa-996e-706b6bec54ab',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_94ec8b477fe2$dummy-clipping-e60fb02284261b52$seed_94ec8b477fe2$,
        'queued',
        0,
        $seed_501aca05db5f${"content_format":"markdown","seed":true,"source_document_id":"40f5b175-c9a5-59d1-9717-46f0028fad92","source_document_version_id":"74f990c5-6ff7-51ae-b52e-feb27f85dbb6","source_event_id":"dummy-clipping-e60fb02284261b52","source_event_row_id":"85811c74-af42-51c9-88d5-bd8eba1cda29"}$seed_501aca05db5f$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '5bf75415-9e99-5572-9990-4d056c1880cf',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_715aecd2b737$dummy-clipping-2fc623f295edc07a$seed_715aecd2b737$,
        'queued',
        0,
        $seed_9846a26187f6${"content_format":"markdown","seed":true,"source_document_id":"61290dc1-93ec-56a7-b355-8819789fc957","source_document_version_id":"d64c529c-c116-5fde-aa18-13f612d83177","source_event_id":"dummy-clipping-2fc623f295edc07a","source_event_row_id":"57084f6e-f865-546f-b0bb-728eaa11c029"}$seed_9846a26187f6$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '94f8fbe5-dc35-5306-9fed-6da7c1a7fcdd',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_806e143cce0d$dummy-clipping-935a44a5d1cb030a$seed_806e143cce0d$,
        'queued',
        0,
        $seed_bf651905790d${"content_format":"markdown","seed":true,"source_document_id":"25ecb002-f4bb-5d66-8cd1-b3118a29f8ac","source_document_version_id":"9c80d01d-fcb5-53c5-b3e4-15475d616bcb","source_event_id":"dummy-clipping-935a44a5d1cb030a","source_event_row_id":"8c8e0bf2-c481-55d4-96ac-481efc187443"}$seed_bf651905790d$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '6dd27e13-6147-560d-a148-f991daadc7ed',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_34173b4f2f06$dummy-clipping-0c39a40bed6d8c61$seed_34173b4f2f06$,
        'queued',
        0,
        $seed_aaaf9a0f4586${"content_format":"markdown","seed":true,"source_document_id":"0bfbb68b-c8e7-59b7-9a6b-adf2121c0772","source_document_version_id":"c38832b0-82a1-5a46-8d64-a032851f64cc","source_event_id":"dummy-clipping-0c39a40bed6d8c61","source_event_row_id":"fcad5d17-b851-5886-8d7d-67047bfa449e"}$seed_aaaf9a0f4586$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        'a4b4940b-3992-5271-b26d-8d50cbe911fb',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_3e44961988fe$dummy-clipping-66018330df862f3e$seed_3e44961988fe$,
        'queued',
        0,
        $seed_61d9beb3a390${"content_format":"markdown","seed":true,"source_document_id":"5d34c777-ca37-5f5e-a864-1b291a570190","source_document_version_id":"b81b1a08-b452-5d0f-802a-f3e057b0fd10","source_event_id":"dummy-clipping-66018330df862f3e","source_event_row_id":"6569ed28-6823-57c5-b6ca-4f9639853376"}$seed_61d9beb3a390$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '7dbb5e19-69c3-5dca-b5bf-86c6cb0d3835',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_95db23f4eb18$dummy-clipping-571dcf2d00209d28$seed_95db23f4eb18$,
        'queued',
        0,
        $seed_2330c6eade11${"content_format":"markdown","seed":true,"source_document_id":"656b3542-e4b4-561f-bb56-4ade092f4424","source_document_version_id":"5839f933-0f1e-5725-b1ee-4b8b6bc9daf1","source_event_id":"dummy-clipping-571dcf2d00209d28","source_event_row_id":"d52848b0-00d8-537c-8374-2eff4387e010"}$seed_2330c6eade11$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '210b9531-f35a-5c85-91ae-2dbdf082f493',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_967a76630a76$dummy-clipping-c3b665f5bb54714d$seed_967a76630a76$,
        'queued',
        0,
        $seed_1678b8412487${"content_format":"markdown","seed":true,"source_document_id":"5c696747-a0ed-508b-af47-e87924d92bbc","source_document_version_id":"f41a0e0f-b365-50be-9e45-8bbf719b01b4","source_event_id":"dummy-clipping-c3b665f5bb54714d","source_event_row_id":"bcb9e0e9-5929-558d-ac50-31db821c2cc0"}$seed_1678b8412487$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '4c8ad9ce-cc34-5f69-a9c6-7c67618ec3ff',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_01ebc6a600ee$dummy-clipping-2f6e04cc5e8bec59$seed_01ebc6a600ee$,
        'queued',
        0,
        $seed_539e3ff8d526${"content_format":"markdown","seed":true,"source_document_id":"3789bb84-6808-500e-9119-71ea492f8b47","source_document_version_id":"67cd85c7-a26e-5a47-bc1c-721dc4e797e1","source_event_id":"dummy-clipping-2f6e04cc5e8bec59","source_event_row_id":"9be68322-fd31-5461-b646-1080d3a1cb5d"}$seed_539e3ff8d526$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '1910418f-3e0d-5376-892b-e48fcdc8fd66',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_2ecedafa881d$dummy-clipping-94b56135fdb927d5$seed_2ecedafa881d$,
        'queued',
        0,
        $seed_81c8111168ed${"content_format":"markdown","seed":true,"source_document_id":"84b00575-9e43-511e-b41f-86323629107c","source_document_version_id":"46de6572-7a89-53c3-bb05-f17be9e4b881","source_event_id":"dummy-clipping-94b56135fdb927d5","source_event_row_id":"2671bc10-843b-5616-9a70-cf9a3a2451a1"}$seed_81c8111168ed$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '886f57fb-266d-5b05-befe-9f6cb20e6acf',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_c343fb8be3c3$dummy-clipping-3dfb8e4802edd050$seed_c343fb8be3c3$,
        'queued',
        0,
        $seed_56ee3256a568${"content_format":"markdown","seed":true,"source_document_id":"5aba7f3d-13ab-5627-b748-0d8b1f122e6f","source_document_version_id":"3ad29bdd-8eb9-5456-ab23-d199712788cf","source_event_id":"dummy-clipping-3dfb8e4802edd050","source_event_row_id":"9cd8b5da-6a11-5ecf-ad78-163db49cab69"}$seed_56ee3256a568$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        'c2fcaf08-275d-50f2-8e63-e487fb530287',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_e294e313a02b$dummy-clipping-4065b5877a3d05ed$seed_e294e313a02b$,
        'queued',
        0,
        $seed_7f9befbb7f73${"content_format":"markdown","seed":true,"source_document_id":"3622c1fd-a240-5868-b398-47248ac6885f","source_document_version_id":"3dde7d81-7e29-574e-a8a9-9cab9108c967","source_event_id":"dummy-clipping-4065b5877a3d05ed","source_event_row_id":"c9d8fee5-8d8c-58be-adc0-7e57f9e2bb0d"}$seed_7f9befbb7f73$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    ),
    (
        '51defb75-4ac1-51e7-a7c2-1f0ce9c634b1',
        'SVC-002',
        'personal_wiki_build',
        'mock-clipping-user',
        $seed_3f4e0a48228c$dummy-clipping-bc44da5502350938$seed_3f4e0a48228c$,
        'queued',
        0,
        $seed_793b1b0023c0${"content_format":"markdown","seed":true,"source_document_id":"056c80ef-0b54-501f-8091-90759dce9888","source_document_version_id":"2da2e793-94b4-5d5e-93b3-d16bce40372e","source_event_id":"dummy-clipping-bc44da5502350938","source_event_row_id":"c4ede23f-0c69-566b-ae1f-42dce315e96d"}$seed_793b1b0023c0$::jsonb,
        true,
        '2026-07-15T00:00:00Z'::timestamptz
    )
ON CONFLICT (id) DO UPDATE SET
    status = 'queued',
    progress = 0,
    payload = EXCLUDED.payload,
    result = NULL,
    error_code = NULL,
    error_message = NULL,
    retryable = true,
    attempt_count = 0,
    queue_message_id = NULL,
    locked_at = NULL,
    locked_by = NULL,
    lease_expires_at = NULL,
    started_at = NULL,
    completed_at = NULL,
    scheduled_at = EXCLUDED.scheduled_at,
    updated_at = clock_timestamp();

INSERT INTO agent.wiki_source_events (
    id,
    user_id,
    source_event_id,
    source_type,
    job_id,
    occurred_at,
    source_url,
    payload,
    status
) VALUES
    (
        'bb1bece7-496d-54e2-978b-d93b5d7a1f83',
        'mock-clipping-user',
        $seed_f4b6cd1ce13b$dummy-clipping-15500a59e7991fdc$seed_f4b6cd1ce13b$,
        'web_clipping',
        'ecbd990d-fd2c-534b-b8ca-c4f6b147cfb5',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_15500a59e799$https://claude.ai/chat/c29532f0-2fe7-4913-853a-1bb009bb7fca$seed_15500a59e799$,
        $seed_49eff34cbfa9${"seed":true,"source_document_id":"d931d233-ab2c-5db9-bed4-62d3bc9b2eda","source_document_version_id":"19c0e199-dbaf-55bb-b0a0-f66a5fe2dc06","source_filename":"dummy/clippings/DDD 아키텍처의 의존성 도식.md"}$seed_49eff34cbfa9$::jsonb,
        'received'
    ),
    (
        '47c42f80-5a6b-5024-a8fd-63db68cb3b66',
        'mock-clipping-user',
        $seed_6a581e78638a$dummy-clipping-ea76873a77dbdc4a$seed_6a581e78638a$,
        'web_clipping',
        '2a30aed2-a7bf-5e99-872d-00a0db75deee',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_ea76873a77db$https://wikidocs.net/blog/@Allen/18213/$seed_ea76873a77db$,
        $seed_64722c022b76${"seed":true,"source_document_id":"838a6107-36c0-5c9c-a868-d69d35900f00","source_document_version_id":"cda80c02-05ca-5dd9-bd32-efed2282e604","source_filename":"dummy/clippings/Obsidian Obsidian Web Clipper 사용법  웹을 내 지식 시스템으로 만드는 가장 쉬운 방법.md"}$seed_64722c022b76$::jsonb,
        'received'
    ),
    (
        '7a0fda6a-88f6-520a-b6ff-a45cdef2eec4',
        'mock-clipping-user',
        $seed_9f7143726fa9$dummy-clipping-cba1e0c7afcb8817$seed_9f7143726fa9$,
        'web_clipping',
        'e6445fbc-66e3-5324-9e22-5c2170fbb2b8',
        '2026-07-14T00:00:00Z'::timestamptz,
        $seed_cba1e0c7afcb$https://obsidian.md/clipper$seed_cba1e0c7afcb$,
        $seed_059751cd966d${"seed":true,"source_document_id":"1cea6d42-3b5d-5015-bb32-0958a7751657","source_document_version_id":"34061cbd-0b49-5005-9f40-960fab0a07fd","source_filename":"dummy/clippings/Obsidian Web Clipper.md"}$seed_059751cd966d$::jsonb,
        'received'
    ),
    (
        '1ffdcc29-4e8e-5d49-9215-1a9f16465da8',
        'mock-clipping-user',
        $seed_bef32affdd15$dummy-clipping-ee2eab4f35a2124a$seed_bef32affdd15$,
        'web_clipping',
        '3d210ceb-1ff5-5b68-ac5e-d32683e72ccd',
        '2026-07-14T00:00:00Z'::timestamptz,
        $seed_ee2eab4f35a2$https://www.langchain.com/blog/introducing-openwiki-an-open-source-agent-for-repo-documentation$seed_ee2eab4f35a2$,
        $seed_0f241cf301e5${"seed":true,"source_document_id":"4d038e7b-ba87-5191-8b39-3f8031c29156","source_document_version_id":"48bf8490-ccd5-58e0-a107-d5f420403a9d","source_filename":"dummy/clippings/OpenWiki Open Source Repo Documentation for Coding Agents.md"}$seed_0f241cf301e5$::jsonb,
        'received'
    ),
    (
        'b33e13cf-f6a3-5576-b6bc-42739ede5d41',
        'mock-clipping-user',
        $seed_b0a0469189d5$dummy-clipping-982cfa5551fe4d2d$seed_b0a0469189d5$,
        'web_clipping',
        'a5e3fd9d-9d64-58aa-a7c5-00fe1c76bfc8',
        '2026-07-14T00:00:00Z'::timestamptz,
        $seed_982cfa5551fe$https://discuss.pytorch.kr/t/openwiki-cli/11089$seed_982cfa5551fe$,
        $seed_a342fdddfb91${"seed":true,"source_document_id":"34d3e582-ae77-5771-8ea9-a3b5c97b9c16","source_document_version_id":"18a337a3-b153-5f59-9f4a-5b7a34aec6c4","source_filename":"dummy/clippings/OpenWiki 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구.md"}$seed_a342fdddfb91$::jsonb,
        'received'
    ),
    (
        '81a4db80-87f3-5d28-aed7-cc2fcad723ac',
        'mock-clipping-user',
        $seed_0fcb7fb9e15e$dummy-clipping-b23c6cd7d698dd14$seed_0fcb7fb9e15e$,
        'web_clipping',
        'd20ce88a-50ae-5918-8b26-ac253c992fe4',
        '2026-07-14T00:00:00Z'::timestamptz,
        $seed_b23c6cd7d698$https://www.threads.com/@choi.openai/post/DaXiCeaDZhN/video-openwiki%EA%B0%80-%EB%82%98%EC%99%94%EC%8A%B5%EB%8B%88%EB%8B%A4-github-%EB%A0%88%ED%8F%AC%EB%A5%BC-%EB%84%A3%EC%9C%BC%EB%A9%B4-%EC%BD%94%EB%93%9C%EA%B0%80-%EB%B0%94%EB%80%94-%EB%95%8C%EB%A7%88%EB%8B%A4-%EA%B0%B1%EC%8B%A0%EB%90%98%EB%8A%94-%EB%AC%B8%EC%84%9C-%EC%82%AC%EC%9D%B4%ED%8A%B8%EB%A5%BC-%EC%9E%90%EB%8F%99-%EC%83%9D%EC%84%B1%ED%95%98%EB%8A%94-%EC%98%A4%ED%94%88%EC%86%8C%EC%8A%A4-%EB%8F%84%EA%B5%AC%EC%9E%85%EB%8B%88%EB%8B%A4%EC%9E%90%EB%8F%99-%EC%9C%84%ED%82%A4-%EC%9E%90/$seed_b23c6cd7d698$,
        $seed_f727c2d35745${"seed":true,"source_document_id":"de6a9b37-5768-58b3-810d-abda084d2b09","source_document_version_id":"c2e9e879-bce6-550d-a450-2edbba833a2b","source_filename":"dummy/clippings/Post by @choi.openai on Threads.md"}$seed_f727c2d35745$::jsonb,
        'received'
    ),
    (
        'c54ea45c-c83a-55b1-93c3-1c33e2088a04',
        'mock-clipping-user',
        $seed_9a53ccd76a7f$dummy-clipping-11217e97399022d9$seed_9a53ccd76a7f$,
        'web_clipping',
        '1fa84a47-90aa-5e53-a18a-a8c0abe9514d',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_11217e973990$https://ui.shadcn.com/$seed_11217e973990$,
        $seed_918a6ec01783${"seed":true,"source_document_id":"ab13f7cb-6ba9-564c-b34a-d1fceb12705f","source_document_version_id":"904c18f9-bd6b-5194-bbac-ac1b4d99db57","source_filename":"dummy/clippings/The Foundation for your Design System.md"}$seed_918a6ec01783$::jsonb,
        'received'
    ),
    (
        'aacc66c8-bd08-538c-92dd-ed48cf4ccc50',
        'mock-clipping-user',
        $seed_0561f66919db$dummy-clipping-b8e4b739e6b4909e$seed_0561f66919db$,
        'web_clipping',
        'aebc6368-807f-523b-a38d-b52ae12192e3',
        '2026-07-14T00:00:00Z'::timestamptz,
        $seed_b8e4b739e6b4$https://github.com/langchain-ai/openwiki$seed_b8e4b739e6b4$,
        $seed_52aca9d9021b${"seed":true,"source_document_id":"639fd91e-b8fa-5942-85bb-b8a019c9d119","source_document_version_id":"2a3accae-e4de-5b9a-8b93-7124c4a43c69","source_filename":"dummy/clippings/langchain-aiopenwiki OpenWiki is a CLI that writes and maintains agent documentation for your codebase..md"}$seed_52aca9d9021b$::jsonb,
        'received'
    ),
    (
        '85811c74-af42-51c9-88d5-bd8eba1cda29',
        'mock-clipping-user',
        $seed_94ec8b477fe2$dummy-clipping-e60fb02284261b52$seed_94ec8b477fe2$,
        'web_clipping',
        '635b290b-e40d-5efa-996e-706b6bec54ab',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_e60fb0228426$https://www.chosun.com/culture-life/culture_general/2026/07/13/VJWQQKP2N5GH3CGADQJMQ6FIYE/$seed_e60fb0228426$,
        $seed_5c1764e522a6${"seed":true,"source_document_id":"40f5b175-c9a5-59d1-9717-46f0028fad92","source_document_version_id":"74f990c5-6ff7-51ae-b52e-feb27f85dbb6","source_filename":"dummy/clippings/‘역주행 신화’ 리센느, 멜론 채팅 라이브 역대 걸그룹 1위.md"}$seed_5c1764e522a6$::jsonb,
        'received'
    ),
    (
        '57084f6e-f865-546f-b0bb-728eaa11c029',
        'mock-clipping-user',
        $seed_715aecd2b737$dummy-clipping-2fc623f295edc07a$seed_715aecd2b737$,
        'web_clipping',
        '5bf75415-9e99-5572-9990-4d056c1880cf',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_2fc623f295ed$https://www.chosun.com/economy/money/2026/07/15/YYV6MVPHKRHFFOVELDGPNQBV64/$seed_2fc623f295ed$,
        $seed_2253a94694ba${"seed":true,"source_document_id":"61290dc1-93ec-56a7-b355-8819789fc957","source_document_version_id":"d64c529c-c116-5fde-aa18-13f612d83177","source_filename":"dummy/clippings/“삼전닉스 레버리지 탓에 주가 요동” 美·日·대만도 비판.md"}$seed_2253a94694ba$::jsonb,
        'received'
    ),
    (
        '8c8e0bf2-c481-55d4-96ac-481efc187443',
        'mock-clipping-user',
        $seed_806e143cce0d$dummy-clipping-935a44a5d1cb030a$seed_806e143cce0d$,
        'web_clipping',
        '94f8fbe5-dc35-5306-9fed-6da7c1a7fcdd',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_935a44a5d1cb$https://news.hada.io/$seed_935a44a5d1cb$,
        $seed_cae090ccc169${"seed":true,"source_document_id":"25ecb002-f4bb-5d66-8cd1-b3118a29f8ac","source_document_version_id":"9c80d01d-fcb5-53c5-b3e4-15475d616bcb","source_filename":"dummy/clippings/개발기술스타트업 뉴스 서비스.md"}$seed_cae090ccc169$::jsonb,
        'received'
    ),
    (
        'fcad5d17-b851-5886-8d7d-67047bfa449e',
        'mock-clipping-user',
        $seed_34173b4f2f06$dummy-clipping-0c39a40bed6d8c61$seed_34173b4f2f06$,
        'web_clipping',
        '6dd27e13-6147-560d-a148-f991daadc7ed',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_0c39a40bed6d$https://www.google.com/search?q=%EC%9D%B4%EB%8D%94%EB%A6%AC%EC%9B%80&oq=%EC%9D%B4%EB%8D%94%EB%A6%AC%EC%9B%80&gs_lcrp=EgZjaHJvbWUyBggAEEUYOdIBCTE2MTlqMGoxNagCCLACAfEF80GR0NxDd3E&sourceid=chrome&source=chrome.rb&ie=UTF-8$seed_0c39a40bed6d$,
        $seed_3c579ccdd35e${"seed":true,"source_document_id":"0bfbb68b-c8e7-59b7-9a6b-adf2121c0772","source_document_version_id":"c38832b0-82a1-5a46-8d64-a032851f64cc","source_filename":"dummy/clippings/검색결과 1.md"}$seed_3c579ccdd35e$::jsonb,
        'received'
    ),
    (
        '6569ed28-6823-57c5-b6ca-4f9639853376',
        'mock-clipping-user',
        $seed_3e44961988fe$dummy-clipping-66018330df862f3e$seed_3e44961988fe$,
        'web_clipping',
        'a4b4940b-3992-5271-b26d-8d50cbe911fb',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_66018330df86$https://www.google.com/search?q=%EC%A3%BC%EA%B0%80&oq=%EC%A3%BC%EA%B0%80&gs_lcrp=EgZjaHJvbWUyBggAEEUYOTIMCAEQABhDGIAEGIoFMgwIAhAAGEMYgAQYigUyDAgDEAAYQxiABBiKBTIMCAQQABhDGIAEGIoFMgYIBRAAGAMyDAgGEAAYQxiABBiKBTINCAcQABiDARixAxiABDINCAgQABiDARixAxiABDIHCAkQABiABNIBCTQ0NDFqMGoxNagCALACAA&sourceid=chrome&source=chrome.rb&ie=UTF-8$seed_66018330df86$,
        $seed_d4e403c4b7ff${"seed":true,"source_document_id":"5d34c777-ca37-5f5e-a864-1b291a570190","source_document_version_id":"b81b1a08-b452-5d0f-802a-f3e057b0fd10","source_filename":"dummy/clippings/검색결과.md"}$seed_d4e403c4b7ff$::jsonb,
        'received'
    ),
    (
        'd52848b0-00d8-537c-8374-2eff4387e010',
        'mock-clipping-user',
        $seed_95db23f4eb18$dummy-clipping-571dcf2d00209d28$seed_95db23f4eb18$,
        'web_clipping',
        '7dbb5e19-69c3-5dca-b5bf-86c6cb0d3835',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_571dcf2d0020$https://news.kbs.co.kr/news/pc/view/view.do?ncd=8609715$seed_571dcf2d0020$,
        $seed_b927c2abcee6${"seed":true,"source_document_id":"656b3542-e4b4-561f-bb56-4ade092f4424","source_document_version_id":"5839f933-0f1e-5725-b1ee-4b8b6bc9daf1","source_filename":"dummy/clippings/리센느 역주행…중소 아이돌 생존경쟁.md"}$seed_b927c2abcee6$::jsonb,
        'received'
    ),
    (
        'bcb9e0e9-5929-558d-ac50-31db821c2cc0',
        'mock-clipping-user',
        $seed_967a76630a76$dummy-clipping-c3b665f5bb54714d$seed_967a76630a76$,
        'web_clipping',
        '210b9531-f35a-5c85-91ae-2dbdf082f493',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_c3b665f5bb54$https://chatgpt.com/c/6a56c707-5e64-83ee-9a74-10f2289af0f3$seed_c3b665f5bb54$,
        $seed_8eb10f4f2037${"seed":true,"source_document_id":"5c696747-a0ed-508b-af47-e87924d92bbc","source_document_version_id":"f41a0e0f-b365-50be-9e45-8bbf719b01b4","source_filename":"dummy/clippings/무료 PostgreSQL 툴 추천.md"}$seed_8eb10f4f2037$::jsonb,
        'received'
    ),
    (
        '9be68322-fd31-5461-b646-1080d3a1cb5d',
        'mock-clipping-user',
        $seed_01ebc6a600ee$dummy-clipping-2f6e04cc5e8bec59$seed_01ebc6a600ee$,
        'web_clipping',
        '4c8ad9ce-cc34-5f69-a9c6-7c67618ec3ff',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_2f6e04cc5e8b$https://claude.ai/chat/33e15f12-94a0-4091-b513-4bfaaa684ffa$seed_2f6e04cc5e8b$,
        $seed_ca6af02143a2${"seed":true,"source_document_id":"3789bb84-6808-500e-9119-71ea492f8b47","source_document_version_id":"67cd85c7-a26e-5a47-bc1c-721dc4e797e1","source_filename":"dummy/clippings/선분으로 정다각형 찾기.md"}$seed_ca6af02143a2$::jsonb,
        'received'
    ),
    (
        '2671bc10-843b-5616-9a70-cf9a3a2451a1',
        'mock-clipping-user',
        $seed_2ecedafa881d$dummy-clipping-94b56135fdb927d5$seed_2ecedafa881d$,
        'web_clipping',
        '1910418f-3e0d-5376-892b-e48fcdc8fd66',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_94b56135fdb9$https://www.youtube.com/watch?v=4DQP7bVU41M$seed_94b56135fdb9$,
        $seed_ab229ef34723${"seed":true,"source_document_id":"84b00575-9e43-511e-b41f-86323629107c","source_document_version_id":"46de6572-7a89-53c3-bb05-f17be9e4b881","source_filename":"dummy/clippings/실적이 이렇게 좋은데, 주가는 왜 빠져요.md"}$seed_ab229ef34723$::jsonb,
        'received'
    ),
    (
        '9cd8b5da-6a11-5ecf-ad78-163db49cab69',
        'mock-clipping-user',
        $seed_c343fb8be3c3$dummy-clipping-3dfb8e4802edd050$seed_c343fb8be3c3$,
        'web_clipping',
        '886f57fb-266d-5b05-befe-9f6cb20e6acf',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_3dfb8e4802ed$https://www.digitalasset.works/news/articleView.html?idxno=41973$seed_3dfb8e4802ed$,
        $seed_3ff694d7d888${"seed":true,"source_document_id":"5aba7f3d-13ab-5627-b748-0d8b1f122e6f","source_document_version_id":"3ad29bdd-8eb9-5456-ab23-d199712788cf","source_filename":"dummy/clippings/이더리움, 한달 만에 1880달러 - 디지털애셋 (Digital Asset).md"}$seed_3ff694d7d888$::jsonb,
        'received'
    ),
    (
        'c9d8fee5-8d8c-58be-adc0-7e57f9e2bb0d',
        'mock-clipping-user',
        $seed_e294e313a02b$dummy-clipping-4065b5877a3d05ed$seed_e294e313a02b$,
        'web_clipping',
        'c2fcaf08-275d-50f2-8e63-e487fb530287',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_4065b5877a3d$https://www.index.go.kr/unity/potal/main/EachDtlPageDetail.do?idx_cd=1080$seed_4065b5877a3d$,
        $seed_4e8171ac8a12${"seed":true,"source_document_id":"3622c1fd-a240-5868-b398-47248ac6885f","source_document_version_id":"3dde7d81-7e29-574e-a8a9-9cab9108c967","source_filename":"dummy/clippings/지표서비스  e-나라지표.md"}$seed_4e8171ac8a12$::jsonb,
        'received'
    ),
    (
        'c4ede23f-0c69-566b-ae1f-42dce315e96d',
        'mock-clipping-user',
        $seed_3f4e0a48228c$dummy-clipping-bc44da5502350938$seed_3f4e0a48228c$,
        'web_clipping',
        '51defb75-4ac1-51e7-a7c2-1f0ce9c634b1',
        '2026-07-15T00:00:00Z'::timestamptz,
        $seed_bc44da550235$https://www.perplexity.ai/search/2126347d-f9ed-431f-8ee8-92033f3831e2$seed_bc44da550235$,
        $seed_c29a47f45b9d${"seed":true,"source_document_id":"056c80ef-0b54-501f-8091-90759dce9888","source_document_version_id":"2da2e793-94b4-5d5e-93b3-d16bce40372e","source_filename":"dummy/clippings/토스 플레이스 api 키 발급받고싶어.md"}$seed_c29a47f45b9d$::jsonb,
        'received'
    )
ON CONFLICT (id) DO UPDATE SET
    job_id = EXCLUDED.job_id,
    occurred_at = EXCLUDED.occurred_at,
    source_url = EXCLUDED.source_url,
    payload = EXCLUDED.payload,
    status = 'received',
    retry_count = 0,
    error_code = NULL,
    error_message = NULL,
    processed_at = NULL,
    updated_at = clock_timestamp();

INSERT INTO agent.user_source_documents (
    id,
    user_id,
    namespace_key,
    source_type,
    canonical_url,
    status,
    current_version,
    content_hash,
    metadata
) VALUES
    (
        'd931d233-ab2c-5db9-bed4-62d3bc9b2eda',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_15500a59e799$https://claude.ai/chat/c29532f0-2fe7-4913-853a-1bb009bb7fca$seed_15500a59e799$,
        'active',
        1,
        '8c58b84d3954cc622cdad6aebaaf3cbb495365c141a0f869673f4813c0b8eb2b',
        $seed_55e54e0ccd81${"seed":true,"source_filename":"dummy/clippings/DDD 아키텍처의 의존성 도식.md"}$seed_55e54e0ccd81$::jsonb
    ),
    (
        '838a6107-36c0-5c9c-a868-d69d35900f00',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_ea76873a77db$https://wikidocs.net/blog/@Allen/18213/$seed_ea76873a77db$,
        'active',
        1,
        'b6075b81e14ca5fc191b0f8340685c6fdc8ac046001b7a5aeec347ac6dfdf828',
        $seed_8741d8d9f6e3${"seed":true,"source_filename":"dummy/clippings/Obsidian Obsidian Web Clipper 사용법  웹을 내 지식 시스템으로 만드는 가장 쉬운 방법.md"}$seed_8741d8d9f6e3$::jsonb
    ),
    (
        '1cea6d42-3b5d-5015-bb32-0958a7751657',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_cba1e0c7afcb$https://obsidian.md/clipper$seed_cba1e0c7afcb$,
        'active',
        1,
        '19be6eeb4a69a4eaab9b3d0580c12bc29826e964ed3533c2d9c28e0e6dfb9aaa',
        $seed_d013a716982f${"seed":true,"source_filename":"dummy/clippings/Obsidian Web Clipper.md"}$seed_d013a716982f$::jsonb
    ),
    (
        '4d038e7b-ba87-5191-8b39-3f8031c29156',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_ee2eab4f35a2$https://www.langchain.com/blog/introducing-openwiki-an-open-source-agent-for-repo-documentation$seed_ee2eab4f35a2$,
        'active',
        1,
        '349afe60129ef007c57b26c88782b67aca6d12d36986d869edafdfc8f04cec03',
        $seed_7acf2ff41a9c${"seed":true,"source_filename":"dummy/clippings/OpenWiki Open Source Repo Documentation for Coding Agents.md"}$seed_7acf2ff41a9c$::jsonb
    ),
    (
        '34d3e582-ae77-5771-8ea9-a3b5c97b9c16',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_982cfa5551fe$https://discuss.pytorch.kr/t/openwiki-cli/11089$seed_982cfa5551fe$,
        'active',
        1,
        '4753c14a7beaa640eb22461b383cc5022b808ca3e2f412f0a3458991573f7b2d',
        $seed_d737379d9c3f${"seed":true,"source_filename":"dummy/clippings/OpenWiki 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구.md"}$seed_d737379d9c3f$::jsonb
    ),
    (
        'de6a9b37-5768-58b3-810d-abda084d2b09',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_b23c6cd7d698$https://www.threads.com/@choi.openai/post/DaXiCeaDZhN/video-openwiki%EA%B0%80-%EB%82%98%EC%99%94%EC%8A%B5%EB%8B%88%EB%8B%A4-github-%EB%A0%88%ED%8F%AC%EB%A5%BC-%EB%84%A3%EC%9C%BC%EB%A9%B4-%EC%BD%94%EB%93%9C%EA%B0%80-%EB%B0%94%EB%80%94-%EB%95%8C%EB%A7%88%EB%8B%A4-%EA%B0%B1%EC%8B%A0%EB%90%98%EB%8A%94-%EB%AC%B8%EC%84%9C-%EC%82%AC%EC%9D%B4%ED%8A%B8%EB%A5%BC-%EC%9E%90%EB%8F%99-%EC%83%9D%EC%84%B1%ED%95%98%EB%8A%94-%EC%98%A4%ED%94%88%EC%86%8C%EC%8A%A4-%EB%8F%84%EA%B5%AC%EC%9E%85%EB%8B%88%EB%8B%A4%EC%9E%90%EB%8F%99-%EC%9C%84%ED%82%A4-%EC%9E%90/$seed_b23c6cd7d698$,
        'active',
        1,
        '4b4ce3ad0d986042691b4a8f3fdd42a38dafff98f4fdcfca7a542dd46cb1b8f3',
        $seed_4f32a21893df${"seed":true,"source_filename":"dummy/clippings/Post by @choi.openai on Threads.md"}$seed_4f32a21893df$::jsonb
    ),
    (
        'ab13f7cb-6ba9-564c-b34a-d1fceb12705f',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_11217e973990$https://ui.shadcn.com/$seed_11217e973990$,
        'active',
        1,
        '69afac7bbbdf790da2f59037a945d492e4ce5f42de8c96500564c6759858f6f0',
        $seed_83c934574608${"seed":true,"source_filename":"dummy/clippings/The Foundation for your Design System.md"}$seed_83c934574608$::jsonb
    ),
    (
        '639fd91e-b8fa-5942-85bb-b8a019c9d119',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_b8e4b739e6b4$https://github.com/langchain-ai/openwiki$seed_b8e4b739e6b4$,
        'active',
        1,
        '869909181cc3e93700f848a755b28c7c6b701e4a40ac274a127b00d8888b2f9e',
        $seed_6958af094914${"seed":true,"source_filename":"dummy/clippings/langchain-aiopenwiki OpenWiki is a CLI that writes and maintains agent documentation for your codebase..md"}$seed_6958af094914$::jsonb
    ),
    (
        '40f5b175-c9a5-59d1-9717-46f0028fad92',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_e60fb0228426$https://www.chosun.com/culture-life/culture_general/2026/07/13/VJWQQKP2N5GH3CGADQJMQ6FIYE/$seed_e60fb0228426$,
        'active',
        1,
        'faa7ac636bbc30a4d9279c5079b8e7ee915094ba3df4465a1bf24fbab3f71646',
        $seed_f395a11e738e${"seed":true,"source_filename":"dummy/clippings/‘역주행 신화’ 리센느, 멜론 채팅 라이브 역대 걸그룹 1위.md"}$seed_f395a11e738e$::jsonb
    ),
    (
        '61290dc1-93ec-56a7-b355-8819789fc957',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_2fc623f295ed$https://www.chosun.com/economy/money/2026/07/15/YYV6MVPHKRHFFOVELDGPNQBV64/$seed_2fc623f295ed$,
        'active',
        1,
        '17d9ac3f8e753dd714d6e52f98b9acc739d2fbff37a922bc13e5cf928f92ae93',
        $seed_701faee1bade${"seed":true,"source_filename":"dummy/clippings/“삼전닉스 레버리지 탓에 주가 요동” 美·日·대만도 비판.md"}$seed_701faee1bade$::jsonb
    ),
    (
        '25ecb002-f4bb-5d66-8cd1-b3118a29f8ac',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_935a44a5d1cb$https://news.hada.io/$seed_935a44a5d1cb$,
        'active',
        1,
        'ce78dbc89ffbd2db89a45ac63e4b6591bb7a8130a7c515bfc0c1edcd9cd8564b',
        $seed_f60cc4b72586${"seed":true,"source_filename":"dummy/clippings/개발기술스타트업 뉴스 서비스.md"}$seed_f60cc4b72586$::jsonb
    ),
    (
        '0bfbb68b-c8e7-59b7-9a6b-adf2121c0772',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_0c39a40bed6d$https://www.google.com/search?q=%EC%9D%B4%EB%8D%94%EB%A6%AC%EC%9B%80&oq=%EC%9D%B4%EB%8D%94%EB%A6%AC%EC%9B%80&gs_lcrp=EgZjaHJvbWUyBggAEEUYOdIBCTE2MTlqMGoxNagCCLACAfEF80GR0NxDd3E&sourceid=chrome&source=chrome.rb&ie=UTF-8$seed_0c39a40bed6d$,
        'active',
        1,
        'af01352e701b194737feb745f3ba5da38fb94d2af1a820d703bea0ed0e97be62',
        $seed_37cdccdcbc29${"seed":true,"source_filename":"dummy/clippings/검색결과 1.md"}$seed_37cdccdcbc29$::jsonb
    ),
    (
        '5d34c777-ca37-5f5e-a864-1b291a570190',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_66018330df86$https://www.google.com/search?q=%EC%A3%BC%EA%B0%80&oq=%EC%A3%BC%EA%B0%80&gs_lcrp=EgZjaHJvbWUyBggAEEUYOTIMCAEQABhDGIAEGIoFMgwIAhAAGEMYgAQYigUyDAgDEAAYQxiABBiKBTIMCAQQABhDGIAEGIoFMgYIBRAAGAMyDAgGEAAYQxiABBiKBTINCAcQABiDARixAxiABDINCAgQABiDARixAxiABDIHCAkQABiABNIBCTQ0NDFqMGoxNagCALACAA&sourceid=chrome&source=chrome.rb&ie=UTF-8$seed_66018330df86$,
        'active',
        1,
        '6e45ac5e83a3e3f2336317b13db330cceda2cbfb6f618f859f7a8dae39b2d0cc',
        $seed_22313513c5f7${"seed":true,"source_filename":"dummy/clippings/검색결과.md"}$seed_22313513c5f7$::jsonb
    ),
    (
        '656b3542-e4b4-561f-bb56-4ade092f4424',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_571dcf2d0020$https://news.kbs.co.kr/news/pc/view/view.do?ncd=8609715$seed_571dcf2d0020$,
        'active',
        1,
        'd3d43356ddc92758840d65208fc0b1c45ae953d420f9a02cd6ad6c4c9aa6e003',
        $seed_09b8ea87872e${"seed":true,"source_filename":"dummy/clippings/리센느 역주행…중소 아이돌 생존경쟁.md"}$seed_09b8ea87872e$::jsonb
    ),
    (
        '5c696747-a0ed-508b-af47-e87924d92bbc',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_c3b665f5bb54$https://chatgpt.com/c/6a56c707-5e64-83ee-9a74-10f2289af0f3$seed_c3b665f5bb54$,
        'active',
        1,
        'c1eaceb47543d0d1aa815c15481e4a217a0831ca6973fd661186633ac672e625',
        $seed_8735a2abb882${"seed":true,"source_filename":"dummy/clippings/무료 PostgreSQL 툴 추천.md"}$seed_8735a2abb882$::jsonb
    ),
    (
        '3789bb84-6808-500e-9119-71ea492f8b47',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_2f6e04cc5e8b$https://claude.ai/chat/33e15f12-94a0-4091-b513-4bfaaa684ffa$seed_2f6e04cc5e8b$,
        'active',
        1,
        '91869d10a9b22f5a68af7e203050feddce9f6aa3965f6d85eac41d6c152b89c1',
        $seed_adbd38dacc2f${"seed":true,"source_filename":"dummy/clippings/선분으로 정다각형 찾기.md"}$seed_adbd38dacc2f$::jsonb
    ),
    (
        '84b00575-9e43-511e-b41f-86323629107c',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_94b56135fdb9$https://www.youtube.com/watch?v=4DQP7bVU41M$seed_94b56135fdb9$,
        'active',
        1,
        'b9117119ae03444e8e99ad13929a0ae6de65c90a5d0a0f706cc44e3305a50ce6',
        $seed_30d94e467a17${"seed":true,"source_filename":"dummy/clippings/실적이 이렇게 좋은데, 주가는 왜 빠져요.md"}$seed_30d94e467a17$::jsonb
    ),
    (
        '5aba7f3d-13ab-5627-b748-0d8b1f122e6f',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_3dfb8e4802ed$https://www.digitalasset.works/news/articleView.html?idxno=41973$seed_3dfb8e4802ed$,
        'active',
        1,
        'a94eff93a3815679ca46da7ab0d65fd2e22d6f2288d8f5f10b409509a0b00dcc',
        $seed_54e37cec4ba4${"seed":true,"source_filename":"dummy/clippings/이더리움, 한달 만에 1880달러 - 디지털애셋 (Digital Asset).md"}$seed_54e37cec4ba4$::jsonb
    ),
    (
        '3622c1fd-a240-5868-b398-47248ac6885f',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_4065b5877a3d$https://www.index.go.kr/unity/potal/main/EachDtlPageDetail.do?idx_cd=1080$seed_4065b5877a3d$,
        'active',
        1,
        '49b3e1d3fe26cb541e3dbe3f6b7ff4d37239c86769af7737b019f4e9f13789b6',
        $seed_df0ed420e130${"seed":true,"source_filename":"dummy/clippings/지표서비스  e-나라지표.md"}$seed_df0ed420e130$::jsonb
    ),
    (
        '056c80ef-0b54-501f-8091-90759dce9888',
        'mock-clipping-user',
        'user/mock-clipping-user',
        'web_clipping',
        $seed_bc44da550235$https://www.perplexity.ai/search/2126347d-f9ed-431f-8ee8-92033f3831e2$seed_bc44da550235$,
        'active',
        1,
        '1f168d801858d8ca8c1242551a2294f0a21869e28be3a5ce64390608f0da0047',
        $seed_0d3603f86744${"seed":true,"source_filename":"dummy/clippings/토스 플레이스 api 키 발급받고싶어.md"}$seed_0d3603f86744$::jsonb
    )
ON CONFLICT (id) DO UPDATE SET
    canonical_url = EXCLUDED.canonical_url,
    status = 'active',
    current_version = 1,
    content_hash = EXCLUDED.content_hash,
    metadata = EXCLUDED.metadata,
    deleted_at = NULL,
    updated_at = clock_timestamp();

INSERT INTO agent.user_source_document_versions (
    id,
    source_document_id,
    namespace_key,
    source_event_id,
    version,
    title,
    author,
    published_at,
    clipped_on,
    description,
    tags,
    raw_content,
    content_format,
    content_hash,
    object_uri,
    source_metadata
) VALUES
    (
        '19c0e199-dbaf-55bb-b0a0-f66a5fe2dc06',
        'd931d233-ab2c-5db9-bed4-62d3bc9b2eda',
        'user/mock-clipping-user',
        'bb1bece7-496d-54e2-978b-d93b5d7a1f83',
        1,
        $seed_9b83b4b263ef$DDD 아키텍처의 의존성 도식$seed_9b83b4b263ef$,
        NULL,
        NULL,
        '2026-07-15'::date,
        $seed_25ae90236627$Claude conversation with 6 messages$seed_25ae90236627$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_8c58b84d3954$**You**

DDD 아키텍쳐에서 의존에 관한 내용을 도식으로 설명해줘.

---

**Claude**

DDD(Domain-Driven Design) 아키텍처의 의존성 구조를 도식으로 설명해드리겠습니다.

---

**You**

그럼 모듈 내에서 A 모듈이 B 모듈에 의존할 때 어떤 계층에서 의존 해야하나?

---

**Claude**

DDD에서 모듈 간 의존성은 **Application Layer** 에서 처리하는 것이 원칙입니다. 도식으로 설명해드리겠습니다.

---

**You**

그럼 application 계층에 있는 dto간 의존 관계가 발생한 경우 각 모듈이 의존하면 강한 결합이 발생하게 되는데 이게 좋은 아키텍쳐인가 아닌가?

---

**Claude**

좋은 질문입니다! DTO 간 의존으로 인한 강한 결합은 **좋지 않은 아키텍처** 입니다. 더 나은 방법들을 도식으로 설명해드리겠습니다.$seed_8c58b84d3954$,
        'markdown',
        '8c58b84d3954cc622cdad6aebaaf3cbb495365c141a0f869673f4813c0b8eb2b',
        NULL,
        $seed_4cb5d069ccc0${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/DDD 아키텍처의 의존성 도식.md"}$seed_4cb5d069ccc0$::jsonb
    ),
    (
        'cda80c02-05ca-5dd9-bd32-efed2282e604',
        '838a6107-36c0-5c9c-a868-d69d35900f00',
        'user/mock-clipping-user',
        '47c42f80-5a6b-5024-a8fd-63db68cb3b66',
        1,
        $seed_559f16ac8c7c$[Obsidian] Obsidian Web Clipper 사용법 : 웹을 내 지식 시스템으로 만드는 가장 쉬운 방법$seed_559f16ac8c7c$,
        NULL,
        NULL,
        '2026-07-15'::date,
        $seed_35dab2a14cdf$Obsidian Web Clipper 사용법: 웹을 내 지식 시스템으로 만드는 가장 쉬운 방법  웹 서핑을 하다 보면 저장하고 싶은 글, GitHub 문서, 논문, 유튜브 영상 등을 자주 발견하게 됩니다.  하지만 대부분은 브라우저 북마크에 저장한 뒤 다시 찾지 못하거나, 저장한 사실…$seed_35dab2a14cdf$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_b6075b81e14c$## Obsidian Web Clipper 사용법: 웹을 내 지식 시스템으로 만드는 가장 쉬운 방법

웹 서핑을 하다 보면 저장하고 싶은 글, GitHub 문서, 논문, 유튜브 영상 등을 자주 발견하게 됩니다.

하지만 대부분은 브라우저 북마크에 저장한 뒤 다시 찾지 못하거나, 저장한 사실조차 잊어버리는 경우가 많습니다.

이 문제를 해결해 주는 도구가 바로 **Obsidian Web Clipper** 입니다.

Obsidian Web Clipper는 단순한 웹 페이지 저장 도구가 아닙니다. 웹 콘텐츠를 Markdown 형식으로 변환하여 Obsidian Vault에 저장하고, 이를 개인 Knowledge Base로 축적할 수 있도록 도와줍니다.

AI 시대의 개인 지식관리(PKM, Personal Knowledge Management)를 구축하고 싶다면 가장 먼저 알아야 할 도구 중 하나입니다.

---

## Obsidian Web Clipper란?

Obsidian Web Clipper는 웹페이지를 Obsidian에 직접 저장할 수 있는 공식 브라우저 확장 프로그램입니다.

기존 북마크는 단순히 링크만 저장하지만, Obsidian Web Clipper는 웹 콘텐츠 자체를 Markdown 문서로 변환하여 보관합니다.

따라서 웹사이트가 삭제되거나 URL이 변경되더라도 중요한 정보를 안전하게 보존할 수 있습니다.

또한 템플릿 기능을 활용하면 제목, 요약, 태그, 작성일, 출처 URL 등을 자동으로 정리하여 저장할 수 있습니다.

---

## Obsidian Web Clipper 설치 및 사용법

Obsidian Web Clipper 사용법은 매우 간단합니다.

| 단계 | 작업 | 설명 |
| --- | --- | --- |
| 1 | Obsidian Web Clipper 설치 | Chrome 또는 Edge 브라우저에 Obsidian Web Clipper 확장 프로그램을 설치합니다. |
| 2 | Obsidian 실행 | Obsidian Vault를 실행하고 저장할 위치를 준비합니다. |
| 3 | 저장할 웹페이지 열기 | 블로그 글, GitHub 문서, 뉴스 기사, 논문 등 저장하고 싶은 웹페이지를 엽니다. |
| 4 | Web Clipper 클릭 | 브라우저 우측 상단의 Obsidian Web Clipper 아이콘을 클릭합니다. |
| 5 | 템플릿 선택 후 저장 | 원하는 템플릿을 선택한 뒤 Clip 버튼을 누르면 Markdown 파일이 Obsidian Vault에 저장됩니다. |

![](https://static.wikidocs.net/images/blog/18213/image_202606061446.png)

몇 초 만에 웹 콘텐츠가 검색 가능한 지식 자산으로 변환됩니다.

---

## Obsidian Web Clipper로 저장할 수 있는 콘텐츠

Obsidian Web Clipper는 거의 모든 웹 콘텐츠를 수집할 수 있습니다.

![](https://static.wikidocs.net/images/blog/18213/image_202606061449_rV2LCbw.png)

특히 제목, 태그, URL, 작성자 정보, 요약 등을 자동으로 추출하여 체계적으로 관리할 수 있다는 점이 큰 장점입니다.

---

## 북마크보다 Obsidian Web Clipper가 좋은 이유

| 구분 | 일반 북마크 | Obsidian Web Clipper |
| --- | --- | --- |
| 저장 방식 | 링크(URL)만 저장 | Markdown 파일로 저장 |
| 검색 기능 | 내용 검색 불가 | 전문(full-text) 검색 가능 |
| 재활용성 | 낮음 (재사용 어려움) | 높음 (노트 기반 재구성 가능) |
| 정보 유지 | 시간이 지나면 맥락 소실 | 장기 Knowledge Base 구축 가능 |
| 구조화 | 없음 | 태그 자동 생성, 템플릿 적용 |
| 확장성 | 제한적 | AI 활용, 지식 연결 가능 |
| 활용 목적 | 단순 링크 저장 | 지식 축적 / 연구 / 분석 |

![](https://static.wikidocs.net/images/blog/18213/image_202606061450.png)

결과적으로 단순 저장이 아니라 지식 축적이 가능해집니다.

---

## LLM Wiki 워크플로우에서 Obsidian Web Clipper 활용하기

최근 AI 워크플로우에서는 Obsidian Web Clipper를 지식 수집 레이어로 활용하는 사례가 늘고 있습니다.

대표적인 흐름은 다음과 같습니다.

![](https://static.wikidocs.net/images/blog/18213/image_202606061451.png)

이 구조에서는 인터넷 정보가 단순 참고 자료가 아니라 AI가 검색하고 활용할 수 있는 개인 데이터베이스로 발전합니다.

---

## AI 시대에 Obsidian Web Clipper가 중요한 이유

AI의 성능은 결국 어떤 컨텍스트를 제공하느냐에 따라 달라집니다.

좋은 정보를 발견할 때마다 Obsidian Web Clipper로 저장하고, 이를 LLM Wiki에 정리하면 시간이 지날수록 자신만의 지식 그래프(Knowledge Graph)가 성장하게 됩니다.

이렇게 축적된 정보는 단순 검색을 넘어 AI Agent의 장기 기억(Long-Term Memory) 역할까지 수행할 수 있습니다.

즉, 인터넷을 소비하는 것이 아니라 인터넷을 자산화하는 것입니다.

---

## 결론

Obsidian Web Clipper의 진짜 가치는 웹페이지 저장 기능이 아닙니다.

핵심은 인터넷 정보를 개인 Knowledge Base에 편입하여 장기적으로 활용 가능한 지식 자산으로 만드는 데 있습니다.

결국 Obsidian Web Clipper는

**"웹을 읽는 도구"가 아니라**  
**"웹을 내 지식 시스템에 편입하는 도구"입니다.**

개인 지식관리(PKM), LLM Wiki, AI Agent 구축에 관심이 있다면 지금 바로 사용해 볼 만한 필수 도구입니다.$seed_b6075b81e14c$,
        'markdown',
        'b6075b81e14ca5fc191b0f8340685c6fdc8ac046001b7a5aeec347ac6dfdf828',
        NULL,
        $seed_5f10b139b772${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/Obsidian Obsidian Web Clipper 사용법  웹을 내 지식 시스템으로 만드는 가장 쉬운 방법.md"}$seed_5f10b139b772$::jsonb
    ),
    (
        '34061cbd-0b49-5005-9f40-960fab0a07fd',
        '1cea6d42-3b5d-5015-bb32-0958a7751657',
        'user/mock-clipping-user',
        '7a0fda6a-88f6-520a-b6ff-a45cdef2eec4',
        1,
        $seed_4a750e646f90$Obsidian Web Clipper$seed_4a750e646f90$,
        NULL,
        NULL,
        '2026-07-14'::date,
        $seed_920d88a1c660$Highlight and capture web pages in your favorite browser. Save anything and everything with just one click.$seed_920d88a1c660$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_19be6eeb4a69$## Save the web.

Capture

## Easily capture pages and metadata to durable files you can read offline.

Templates allow you to customize how web pages are saved to your vault.

**Articles.** including citations and footnotes.

**Recipes.** with ingredients, steps, and nutrition.

**References.** for books, movies, or podcasts.

**Academic papers.** including code and math.

**Custom templates.** for your favorite sites.

Highlight

## Highlight the web.

Easily highlight important passages you want to save to Obsidian. Your highlights are always visible, so you can revisit them when you return to a page.

**Highlight.** text, images, and blocks of content.

**Clip.** your highlights to Obsidian in one click.

Features

## Bring the web to your personal knowledge base.

Web Clipper is free, [open source](https://github.com/obsidianmd/obsidian-clipper), and packed with useful features that make your favorite browser a sharper tool.

Stay private

All your clipped content is stored locally in your Obsidian vault. Your thoughts are yours.

No lock-in

Your clips are saved to durable Markdown files. All your highlights and settings are exportable to JSON.

Hotkeys

Speed up your workflow with keyboard shortcuts to quickly add content to your vault.

Auto-apply templates

Set up rules to automatically apply the right template based on the website you’re clipping from.

Extract anything

Capture any data from the page: meta tags, Schema.org variables, and even element selectors.

Manipulate page data

Powerful [templating features](https://obsidian.md/help/web-clipper) allow you to modify page data before it’s saved to your vault.$seed_19be6eeb4a69$,
        'markdown',
        '19be6eeb4a69a4eaab9b3d0580c12bc29826e964ed3533c2d9c28e0e6dfb9aaa',
        NULL,
        $seed_2c254838cfbb${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/Obsidian Web Clipper.md"}$seed_2c254838cfbb$::jsonb
    ),
    (
        '48bf8490-ccd5-58e0-a107-d5f420403a9d',
        '4d038e7b-ba87-5191-8b39-3f8031c29156',
        'user/mock-clipping-user',
        '1ffdcc29-4e8e-5d49-9215-1a9f16465da8',
        1,
        $seed_2cb2cef4045d$OpenWiki: Open Source Repo Documentation for Coding Agents$seed_2cb2cef4045d$,
        $seed_cb59e9dc5143$[[Brace Sproul]]$seed_cb59e9dc5143$,
        '2026-07-02T00:00:00Z'::timestamptz,
        '2026-07-14'::date,
        $seed_908416df41f4$OpenWiki generates and maintains codebase documentation so coding agents can find the repo context they need without loading everything into one instruction file.$seed_908416df41f4$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_349afe60129e$Today we're releasing OpenWiki, an open source agent and CLI for generating and maintaining documentation for codebases.

Agents write better code when they understand the repo they're working in. They need to know where key logic lives, how files connect, and which patterns the codebase expects. Good documentation gives agents that context, which leads to more informed code changes and fewer avoidable mistakes.

The problem is that documentation is hard to keep current. Writing the initial docs takes time, and updating them every time the code changes is even harder. In large repos with frequent PRs, docs can fall out of date quickly.

OpenWiki handles that work automatically. It creates a wiki for your repo, connects that wiki to your coding agent, and keeps it updated as your code changes.

## Why wikis for agents

We were inspired by existing work around codebase wikis, including [DeepWiki](https://deepwiki.com/), [AutoWiki](https://docs.factory.ai/cli/features/wiki/overview), and [Karpathy’s LLM Wiki](https://x.com/karpathy/status/2040470801506541998) concept. The shared idea is simple. A wiki gives humans and agents a structured way to understand a codebase without forcing all context into one giant file.

That matters because most coding agents already read files like `AGENTS.md` or `CLAUDE.md` for instructions. Those files are useful, but they’re not the right place to store hundreds of pages of repo documentation. They should point the agent toward the right context, then let the agent retrieve what it needs.

OpenWiki follows that model. It generates a repo wiki, then updates your agent instruction files with a reference to that wiki. From there, your coding agent can discover and use the docs automatically.

## Getting started

OpenWiki is designed to be easy to run from the command line.

Install it with npm:

```python
npm install -g openwiki
```

then run:

```python
openwiki --init
```
![](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a45549cd89555f7e03154f8_image%20(49).png)

The init command asks for a model provider and API key, then generates documentation for your repo.

OpenWiki supports both open and closed model providers, including OpenRouter, Fireworks, Baseten, OpenAI, and Anthropic. By default, it uses OpenRouter with an open model, but you can configure the provider that works best for your setup.

Because OpenWiki is built on top of [DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview), it also supports tracing to [LangSmith](https://langsmith.com/). If you provide a LangSmith API key, OpenWiki will trace runs to a LangSmith project so you can inspect exactly what the agent did while generating or updating your docs.

## How OpenWiki connects to your coding agent

After generating the wiki, OpenWiki updates your repo’s agent instruction files. If your repo uses `AGENTS.md`, `CLAUDE.md`, or both, OpenWiki adds a reference to the generated wiki and explains when the agent should use it.

We chose this approach because putting the entire wiki inside an instruction file would add too much context. In a large repo, the wiki can span hundreds of files. Loading all of that into every agent run would be wasteful and hard to maintain.

A short reference works better. Your coding agent already reads the instruction file. Once OpenWiki adds the reference, the agent can find the wiki when it needs repo context, without requiring you to change your workflow.

## Keeping the wiki up to date

Generating docs once is useful. Keeping them current is where OpenWiki becomes more valuable.

OpenWiki includes a [GitHub Action that can run on a schedule](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.yml), for example once a day. The action runs OpenWiki with the update flag. OpenWiki checks which commits landed since the last run, uses git diffs to understand what changed, then updates the wiki with the relevant context.

That means the workflow can run in the background. As your codebase changes, OpenWiki updates the documentation. Your coding agent keeps picking up the latest wiki through the existing instruction file reference.

## Built for codebases first

This first release focuses on wikis for codebases. The goal is to make it easier for agents to understand the repos they work in, without asking developers to manually write and maintain detailed docs.

Over time, we think the OpenWiki concept can apply more broadly. Agents need durable context for many kinds of work, not just coding. Codebase documentation is the first use case, but the same pattern can help agents maintain useful context across other workflows too.

## Try it

OpenWiki is open source and available now.

You can install it, run `openwiki --init`, and generate a wiki for your repo in a few minutes.

Check out the repo here: [https://github.com/langchain-ai/openwiki](https://github.com/langchain-ai/openwiki)

## ⚠️ Potential Contradiction

**Source claim**: 문서화는 수동으로 작성하고 유지 관리하기 어렵다.

**Existing view**: OpenWiki는 코드 변경에 따라 문서를 자동으로 업데이트하는 메커니즘을 제공한다.

**Resolution suggestion**: 문서화의 유지 관리가 어렵다는 문제를 해결하기 위해 자동화된 업데이트 시스템(GitHub Action)을 도입했다.

---
*Flagged: 2026-07-14*$seed_349afe60129e$,
        'markdown',
        '349afe60129ef007c57b26c88782b67aca6d12d36986d869edafdfc8f04cec03',
        NULL,
        $seed_8c24ce88cc92${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/OpenWiki Open Source Repo Documentation for Coding Agents.md"}$seed_8c24ce88cc92$::jsonb
    ),
    (
        '18a337a3-b153-5f59-9f4a-5b7a34aec6c4',
        '34d3e582-ae77-5771-8ea9-a3b5c97b9c16',
        'user/mock-clipping-user',
        'b33e13cf-f6a3-5576-b6bc-42739ede5d41',
        1,
        $seed_14446983e597$OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구$seed_14446983e597$,
        $seed_c3effe3d3d3d$[[9bow]]$seed_c3effe3d3d3d$,
        '2026-07-06T00:00:00Z'::timestamptz,
        '2026-07-14'::date,
        $seed_94b7322db4f4$OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구1302×930 70.8 KB OpenWiki 소개 OpenWiki는 코드베이스의 문서를 자동으로 작성하고 최신 상태로 유지하는 CLI 도구로, 사람보다 코딩 에이전$seed_94b7322db4f4$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_4753c14a7bea$[![OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구](https://discuss.pytorch.kr/uploads/default/optimized/3X/f/2/f2272699ade92ca8fe4b369690c8979074ba3e1a_2_1028x734.png)

OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구1302×930 70.8 KB

](https://discuss.pytorch.kr/uploads/default/original/3X/f/2/f2272699ade92ca8fe4b369690c8979074ba3e1a.png "OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구")

## OpenWiki 소개

OpenWiki는 코드베이스의 문서를 자동으로 작성하고 최신 상태로 유지하는 CLI 도구로, 사람보다 코딩 에이전트가 읽는 것을 우선 목표로 설계되었습니다. LangChain과 LangGraph를 개발해 온 langchain-ai 조직이 공개했으며, 문서 생성부터 갱신, 에이전트 연동까지 명령 몇 개로 이어지는 구성이 특징입니다. 본 게시물에서는 OpenWiki의 동작 방식과 설치, 사용법을 정리합니다.

코딩 에이전트가 낯선 코드베이스에서 작업을 시작하면 매번 저장소 구조를 탐색하며 맥락을 다시 쌓아야 합니다. 잘 정리된 문서가 있으면 이 비용이 크게 줄지만, 사람이 손으로 쓰는 문서는 코드 변경을 따라가지 못하고 금세 낡아버립니다. OpenWiki는 이 문제를 LLM이 문서를 직접 쓰고 갱신하는 방식으로 접근합니다.

동작 방식은 단순합니다. 저장소에 위키가 없으면 `openwiki/` 디렉토리에 초기 문서를 생성하고, 이미 있으면 저장소 변경 사항을 반영해 문서를 갱신합니다. 여기에 하루 한 번 문서 업데이트 PR을 자동으로 여는 GitHub Action 예시까지 제공해, 문서가 코드를 따라가도록 만드는 순환 구조를 갖추고 있습니다.

[![OpenWiki의 문서화 흐름 요약, 설치부터 자동 갱신까지 4단계](https://discuss.pytorch.kr/uploads/default/optimized/3X/9/b/9bd956b619b726c640fa1f5dd617303fc6a0e5b8_2_1028x685.jpeg)

OpenWiki의 문서화 흐름 요약, 설치부터 자동 갱신까지 4단계1536×1024 241 KB

](https://discuss.pytorch.kr/uploads/default/original/3X/9/b/9bd956b619b726c640fa1f5dd617303fc6a0e5b8.jpeg "OpenWiki의 문서화 흐름 요약, 설치부터 자동 갱신까지 4단계")

## OpenWiki와 코딩 에이전트의 연동

OpenWiki가 다른 문서 생성 도구와 구별되는 지점은 에이전트 연동을 기본 동작으로 둔다는 점입니다. 실행하면 `AGENTS.md` 또는 `CLAUDE.md` 파일에 *"컨텍스트를 검색할 때 이 위키를 참조하라"* 는 안내를 자동으로 추가하고, 해당 파일이 없으면 새로 만들어 줍니다. 코딩 에이전트가 저장소에 진입했을 때 OpenWiki가 만든 문서를 컨텍스트 소스로 활용하도록 이어주는 것입니다.

첫 대화형 실행에서는 추론(inference) 제공자와 API 키, 사용할 LLM을 설정합니다. OpenRouter, Fireworks, Baseten, OpenAI, Anthropic을 기본 지원하고, GLM 5.2나 Kimi K2.6, Sonnet 5 같은 모델이 미리 정의되어 있으며 제공자별로 커스텀 모델 ID도 지정할 수 있습니다. LangSmith API 키를 설정하면 OpenWiki 실행 과정을 LangSmith 추적 프로젝트로 남길 수도 있습니다. 설정과 시크릿은 로컬의 `~/.openwiki/.env` 에 저장됩니다.

## OpenWiki 설치 및 사용법

npm으로 전역 설치한 뒤 초기화 명령으로 시작합니다.

```bash
npm install -g openwiki
openwiki --init
```

이후 사용법은 목적에 따라 나뉩니다. 인자 없이 실행하면 대화형 CLI가 열리고, 기본적으로 실행이 끝나도 세션이 유지되어 후속 요청을 이어서 보낼 수 있습니다.

```bash
# 대화형 CLI 시작
openwiki

# 초기 요청과 함께 시작
openwiki "Please generate documentation for this repository"

# 한 번 실행하고 종료 (비대화형)
openwiki -p "Summarize what you can do"

# 기존 문서 갱신
openwiki --update
```

문서를 자동으로 최신 상태로 유지하려면 저장소의 `.github/workflows/` 에 [openwiki-update.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.yml?utm_source=pytorchkr&ref=pytorchkr) 예시 워크플로우를 추가합니다. 하루 한 번 문서 업데이트 PR을 자동으로 열어줍니다.

## OpenWiki의 라이선스

OpenWiki는 [MIT 라이선스](https://github.com/langchain-ai/openwiki/blob/main/LICENSE?utm_source=pytorchkr&ref=pytorchkr)로 공개되어 있어 개인 및 상업적 목적으로 자유롭게 사용할 수 있습니다.

## ![:github:](https://discuss.pytorch.kr/uploads/default/original/2X/7/70a6220c603eed42089b4f67366225849e119e20.svg?v=15 ":github:") OpenWiki GitHub 저장소

[github.com](https://github.com/langchain-ai/openwiki?utm_source=pytorchkr&ref=pytorchkr)

![](https://discuss.pytorch.kr/uploads/default/optimized/3X/1/6/16500e39818583dcac74a3934b89095503bfbc2d_2_695x347.png)

### [GitHub - langchain-ai/openwiki: OpenWiki is a CLI that writes and maintains agent...](https://github.com/langchain-ai/openwiki?utm_source=pytorchkr&ref=pytorchkr)

OpenWiki is a CLI that writes and maintains agent documentation for your codebase.

## 더 읽어보기

- [DeepWiki-Open: GitHub, GitLab 등의 저장소로부터 대화형 Wiki를 생성하는 오픈소스 DeepWiki 프로젝트](https://discuss.pytorch.kr/t/deepwiki-open-github-gitlab-wiki-deepwiki/7782)
- [Understand-Anything: 코드베이스를 인터랙티브 지식 그래프로 변환하는 Claude Code 플러그인](https://discuss.pytorch.kr/t/understand-anything-claude-code/9418)
- [Tutorial-Codebase-Knowledge, GitHub 저장소를 튜토리얼로 변환하는 도구 (feat. The Pocket)](https://discuss.pytorch.kr/t/tutorial-codebase-knowledge-github-feat-the-pocket/6827)
- [Wrinkl: AI가 프로젝트의 맥락을 파악하고, 코드 및 문서를 일관성있게 작성하도록 돕는 AI 맥락 관리 시스템](https://discuss.pytorch.kr/t/wrinkl-ai-ai/7217)

  
  

---

*이 글은 GPT 모델로 정리한 글을 바탕으로 한 것으로, 원문의 내용 또는 의도와 다르게 정리된 내용이 있을 수 있습니다. 관심있는 내용이시라면 원문도 함께 참고해주세요! 읽으시면서 어색하거나 잘못된 내용을 발견하시면 덧글로 알려주시기를 부탁드립니다.* ![:hugs:](https://discuss.pytorch.kr/images/emoji/fluentui/hugs.png?v=15 ":hugs:")

[![:pytorch:](https://discuss.pytorch.kr/uploads/default/original/2X/f/fa98c2196c22febe7475e503792febf39ba7a0de.svg?v=15 ":pytorch:")파이토치 한국 사용자 모임![:south_korea:](https://discuss.pytorch.kr/images/emoji/fluentui/south_korea.png?v=15 ":south_korea:")](https://pytorch.kr/)이 정리한 이 글이 유용하셨나요? [회원으로 가입](https://discuss.pytorch.kr/signup)하시면 주요 글들을 이메일![:love_letter:](https://discuss.pytorch.kr/images/emoji/fluentui/love_letter.png?v=15 ":love_letter:")로 보내드립니다! [텔레그램(Telegram)](https://t.me/pytorchkr?utm_source=pytorchkr&ref=pytorchkr)이나 [Slack/Discord/Teams/Dooray/GoogleChat 등](https://discuss-noti.pytorch.kr/)으로도 새 글 알림을 받으실 수 있습니다. ![:smiley:](https://discuss.pytorch.kr/images/emoji/fluentui/smiley.png?v=15 ":smiley:")

![:wrapped_gift:](https://discuss.pytorch.kr/images/emoji/fluentui/wrapped_gift.png?v=15 ":wrapped_gift:") 아래![:down_right_arrow:](https://discuss.pytorch.kr/images/emoji/fluentui/down_right_arrow.png?v=15 ":down_right_arrow:")쪽에 좋아요![:+1:](https://discuss.pytorch.kr/images/emoji/fluentui/+1.png?v=15 ":+1:")를 눌러주시면 새로운 소식들을 정리하고 공유하는데 힘이 됩니다~ ![:star_struck:](https://discuss.pytorch.kr/images/emoji/fluentui/star_struck.png?v=15 ":star_struck:")$seed_4753c14a7bea$,
        'markdown',
        '4753c14a7beaa640eb22461b383cc5022b808ca3e2f412f0a3458991573f7b2d',
        NULL,
        $seed_1929539495ee${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/OpenWiki 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구.md"}$seed_1929539495ee$::jsonb
    ),
    (
        'c2e9e879-bce6-550d-a450-2edbba833a2b',
        'de6a9b37-5768-58b3-810d-abda084d2b09',
        'user/mock-clipping-user',
        '81a4db80-87f3-5d28-aed7-cc2fcad723ac',
        1,
        $seed_4e6911b340fc$Post by @choi.openai on Threads$seed_4e6911b340fc$,
        $seed_0dcae95b01a5$[[@choi.openai]]$seed_0dcae95b01a5$,
        '2026-07-04T00:00:00Z'::timestamptz,
        '2026-07-14'::date,
        $seed_923a1fa0e394$2026-07-04$seed_923a1fa0e394$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_4b4ce3ad0d98$OpenWiki가 나왔습니다. GitHub 레포를 넣으면 코드가 바뀔 때마다 갱신되는 문서 사이트를 자동 생성하는 오픈소스 도구입니다.

자동 위키 자체는 DeepWiki가 먼저 열었습니다. OpenWiki가 다른 건 계속 갱신된다는 점인데요. 문서를 사람이 손으로 유지하는 게 아니라 소스에서 파생돼 빌드처럼 다시 만들어지게 해서, 코드는 바뀌는데 문서만 낡는 문제를 구조적으로 막습니다.

더 큰 그림은 이게 Vercel의 eve('에이전트용 Next.js') 쇼케이스라는 점입니다. 웹앱은 durable 에이전트를 소비할 뿐이고, 코드 분석·위키 생성은 백그라운드 잡으로 돌아가며 Neon에 상태, Blob에 산출물을 쌓습니다. 에이전트가 파생물을 만들어 신선하게 유지하는 앱의 표준형인 거죠.

다만 자동 문서는 코드가 무엇을 하는지는 잘 적어도, 왜 그렇게 짰는지(설계 의도·트레이드오프)는 못 채웁니다. 그 부분은 여전히 사람 몫입니다.

![](https://scontent-icn2-1.cdninstagram.com/v/t51.71878-15/731146899_1358833566346811_6460150986012505888_n.jpg?stp=dst-jpg_e15_tt6&_nc_cat=107&ig_cache_key=MzkzMzc2MjUwMzIwMTEwMTkwMQ%3D%3D.3-ccb7-5&ccb=7-5&_nc_sid=58cdad&efg=eyJ2ZW5jb2RlX3RhZyI6IkZFRUQueHBpZHMuNjQwLnNkci52aWRlb19kZWZhdWx0X2NvdmVyX2ZyYW1lLkMyIn0%3D&_nc_ohc=EdoNTDSNL_wQ7kNvwHTOR_k&_nc_oc=AdqUfvzknYoXxqKCfHzukbgH79x-pnnKnVbROzLXMkyLdTVK2aIfB_TbtuP1T65qjfA&_nc_ad=z-m&_nc_cid=0&_nc_zt=23&_nc_ht=scontent-icn2-1.cdninstagram.com&_nc_gid=chXCC85SKIiEkZOewZQO0g&_nc_ss=7a22e&oh=00_AQDaGFEY0Rx3r0E__9uMae3r2wwPV_iWHKZoSVDCMXzhbA&oe=6A5B8B86)

> **@choi.openai**
> 
> 2026-07-04
> 
> [https://www.threads.com/@choi.openai/post/DaXiCeaDZhN](https://www.threads.com/@choi.openai/post/DaXiCeaDZhN)

---

작성자

주소 : [openwiki.sh](https://openwiki.sh/)

[![OpenWiki](https://external-icn2-1.xx.fbcdn.net/emg1/v/t13/14656174560766953965?stp=dst-src&url=https%3A%2F%2Fopenwiki-omega.labs.vercel.dev%2Fopengraph-image%3Feb0d357496591030&utld=vercel.dev&_nc_gid=chXCC85SKIiEkZOewZQO0g&_nc_oc=AdoKna2j6F24iP-J7v7RhOAIJfTHdzF5klnQogRZnHqMq2z27c_2npP2mm5PEjiLqQk&ccb=13-1&oh=06_Q3_BAfVNAsqj5OP7AK1V4f1EFp9KPb288a1MB20DnWTuBgFQ&oe=6A57AD45&_nc_sid=1d65fc)](https://openwiki.sh/)

> **@choi.openai**
> 
> 2026-07-04
> 
> [https://www.threads.com/@choi.openai/post/DaXiDrtjVx3](https://www.threads.com/@choi.openai/post/DaXiDrtjVx3)$seed_4b4ce3ad0d98$,
        'markdown',
        '4b4ce3ad0d986042691b4a8f3fdd42a38dafff98f4fdcfca7a542dd46cb1b8f3',
        NULL,
        $seed_096b32e75937${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/Post by @choi.openai on Threads.md"}$seed_096b32e75937$::jsonb
    ),
    (
        '904c18f9-bd6b-5194-bbac-ac1b4d99db57',
        'ab13f7cb-6ba9-564c-b34a-d1fceb12705f',
        'user/mock-clipping-user',
        'c54ea45c-c83a-55b1-93c3-1c33e2088a04',
        1,
        $seed_5ce9f1ddb009$The Foundation for your Design System$seed_5ce9f1ddb009$,
        $seed_39b2cf78b1f2$[[shadcn]]$seed_39b2cf78b1f2$,
        NULL,
        '2026-07-15'::date,
        $seed_5413f78f85e4$A set of beautifully designed components that you can customize, extend, and build on. Start here then make it your own. Open Source. Open Code.$seed_5413f78f85e4$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_69afac7bbbdf$A set of beautifully designed components that you can customize, extend, and build on. Start here then make it your own. Open Source. Open Code.

[Build Your Own](https://ui.shadcn.com/create?preset=b27GcrRo)

BadgeSecondary

Savings Targets

Active milestones for 2024 across your portfolio. Monitor how close you are to each savings goal.

You have not met your targets for this year.

Dec

Jan

Feb

Mar

Apr

Upcoming

May 2024Scheduled

Savings Plan

AcceleratedRecurring

Net Royalties$1,248.75

Processing Fee-$37.46

Total Ready to Claim$1,211.29 USD

Once your bank is connected, balances over $10.00 are automatically eligible for monthly distribution on the 15th of each month.

Scan to connect your mobile device

Open the Ledger mobile app and scan this code to link your device.

Morning, shadcn!

What are we working on today? Press send to start a new conversation

Demo is read only. Press send to send messages.$seed_69afac7bbbdf$,
        'markdown',
        '69afac7bbbdf790da2f59037a945d492e4ce5f42de8c96500564c6759858f6f0',
        NULL,
        $seed_5166fe1448eb${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/The Foundation for your Design System.md"}$seed_5166fe1448eb$::jsonb
    ),
    (
        '2a3accae-e4de-5b9a-8b93-7124c4a43c69',
        '639fd91e-b8fa-5942-85bb-b8a019c9d119',
        'user/mock-clipping-user',
        'aacc66c8-bd08-538c-92dd-ed48cf4ccc50',
        1,
        $seed_0ea8711eae38$langchain-ai/openwiki: OpenWiki is a CLI that writes and maintains agent documentation for your codebase.$seed_0ea8711eae38$,
        NULL,
        NULL,
        '2026-07-14'::date,
        $seed_acd7c07342a0$OpenWiki is a CLI that writes and maintains agent documentation for your codebase. - langchain-ai/openwiki$seed_acd7c07342a0$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_869909181cc3$## 오픈위키

OpenWiki는 코드베이스 또는 목적 기억을 위한 에이전트 위키를 작성하고 유지 관리하는 CLI 도구입니다. 에이전트에 특화되어 개발되었으며, 내장 커넥터 또는 Git 저장소를 통해 로컬 지식 소스를 가져와 로컬 위키로 통합할 수 있습니다.

[![오픈위키](https://raw.githubusercontent.com/langchain-ai/openwiki/main/static/openwiki.png)](https://raw.githubusercontent.com/langchain-ai/openwiki/main/static/openwiki.png)

## 설치하다

```
npm install -g openwiki
```

Windows에서는 OpenWiki를 Node.js 패키지 관리자(예: `npm` 또는 ) 를 사용하여 설치하는 것이 좋습니다 `pnpm`.

```
npm install -g openwiki
# or
pnpm add -g openwiki
```

`bun install -g openwiki` OpenWiki의 체크포인트 종속성 컴파일로 되돌아갈 수 있습니다 `better-sqlite3`. 이 방법을 사용하기 전에 Visual Studio 빌드 도구를 C++ 데스크톱 개발 워크로드와 함께 설치하십시오. Bun은 기본적으로 설치된 패키지의 수명 주기 스크립트를 실행하지 않으므로 해당 네이티브 종속성 빌드가 시작되기 전에 패키지 수준 경고를 표시할 수 없습니다.

## 빠른 시작

OpenWiki를 코드 모드로 초기화하고, 모델과 API 키를 구성한 다음, 문서를 생성하세요.

```
openwiki --init
```

오픈위키에는 두 가지 모드가 있습니다.

- **개인 모드는** `~/.openwiki/wiki` 로컬 저장소, Gmail, Notion, 웹 검색, Hacker News, X/Twitter와 같은 구성된 소스에서 로컬 개인 두뇌 위키를 구축합니다.
- **코드 모드는** `openwiki/` 현재 코드베이스에 대한 저장소 문서를 생성합니다.

코드 모드에서 실행하세요. 로컬 개인 브레인 위키를 사용 `openwiki --init` 하려면 또는 를 사용 하세요.`openwiki --update` `openwiki personal --init` `openwiki personal --update`

문서가 항상 최신 상태로 유지되도록 하려면 Git 공급자의 CI 워크플로를 추가하여 문서 업데이트와 함께 PR 또는 병합 요청이 자동으로 생성되도록 하세요.

- GitHub Actions: [openwiki-update.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.yml) 파일을. 으로 복사합니다 `.github/workflows/openwiki-update.yml`.
- GitLab CI: [openwiki-update.gitlab-ci.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.gitlab-ci.yml)`.gitlab-ci.yml` 파일을 GitLab 파이프라인 에 복사하거나 기존 파이프라인에 포함시키세요.
- Bitbucket Pipelines: [openwiki-update.bitbucket-pipelines.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.bitbucket-pipelines.yml) 파일을 복사한 `bitbucket-pipelines.yml` 다음, `openwiki-update` 저장소 설정 > 파이프라인 > 일정에서 사용자 지정 파이프라인을 예약하세요.

GitHub Actions에서 저장소 문서를 생성하려면 \`git add.git action\`을 사용하세요. CI 환경에서 `openwiki code --update --print` 실행할 필요는 없습니다. 워크플로에 필요한 공급자 및 모델 환경 변수가 제공되면 문서가 아직 존재하지 않는 경우 자동으로 초기 문서를 생성 합니다.`--init` `--update` `openwiki/`

## 용법

현재 저장소에 대해 코드 모드로 대화형 CLI를 시작합니다.

```
openwiki
```

OpenWiki를 처음 시작할 때 다음 요청을 입력하세요.

```
openwiki "Please generate documentation for this repository"
```

대신 대화형 로컬 개인 두뇌를 시작하세요:

```
openwiki personal
```

명령어 하나만 실행하고 종료하세요:

```
openwiki -p "Summarize what you can do"
```

OpenWiki 초기화:

```
openwiki --init
```

로컬 개인 두뇌 위키를 초기화합니다:

```
openwiki personal --init
```

저장소 코드 문서 업데이트:

```
openwiki --update
```

로컬 개인 두뇌 위키를 업데이트하세요:

```
openwiki personal --update
```

먼저 구성된 로컬 커넥터를 가져올 수 있는 업데이트를 실행하십시오.

```
openwiki personal --update "Refresh the wiki from configured connectors"
```

도움말 보기:

```
openwiki --help
```

채팅에서 다음 명령어를 사용하여 `/api-key` 현재 공급자 API 키를 업데이트하고 `/langsmith-key` LangSmith 추적 자격 증명을 업데이트하거나 삭제할 수 있습니다. 두 명령어 모두 마스크된 프롬프트를 사용합니다.

커넥터 제공업체를 인증합니다.

```
openwiki auth slack
openwiki auth gmail
openwiki auth x
openwiki auth notion
```

Slack OAuth용 ngrok 터널을 시작하세요:

```
openwiki ngrok start
```

이 명령은 임의의 HTTPS 포워딩 URL로 ngrok을 시작합니다. OpenWiki는 ngrok의 로컬 검사 API를 읽고, URL에 를 추가한 후 자동으로 `/callback` 저장합니다 `OPENWIKI_HTTPS_OAUTH_REDIRECT_URI`. 출력된 콜백 URL을 Slack에 등록하세요. 고정된 ngrok 도메인을 사용하는 경우, 를 실행하세요 `openwiki ngrok start https://<your-ngrok-domain>`. X/Twitter 및 Gmail 인증은 해당 HTTPS 재정의를 무시하고 로컬 루프백 콜백을 계속 사용합니다 `http://127.0.0.1:53682/callback`.

Bare는 `openwiki` 현재 저장소에 대해 코드 모드로 실행됩니다. `openwiki/` 위키가 존재하지 않는 경우 초기 저장소 문서를 생성합니다. `openwiki personal` 로컬 범용 위키에는 를 사용하십시오 `~/.openwiki/wiki/`. 기본적으로 CLI는 실행 후 계속 열려 있으므로 후속 메시지를 보낼 수 있습니다. 최종 어시스턴트 출력을 인쇄하는 일회성 비대화형 실행에는 `-p` 또는 를 사용하십시오.`--print`

기본 코드 모드로 실행하고 저장소 문서를 기반으로 작업합니다. 위치 모드를 사용 `openwiki --init` 하거나 로컬 개인 브레인 위키를 초기화 또는 업데이트할 수 있습니다.`openwiki --update` `personal` `--mode personal`

On each `code` run, `openwiki` maintains both an `AGENTS.md` and a `CLAUDE.md` at the repository root, adding prompting that instructs your coding agent to reference the wiki when searching for context. Each file is created if it does not already exist. If a file is present, OpenWiki only rewrites its own `<!-- OPENWIKI:START -->…<!-- OPENWIKI:END -->` block and leaves the rest of your content untouched (appending the block the first time). The scheduled GitHub Actions workflow includes these files, along with the workflow itself, in the documentation pull request.

On the first interactive run, OpenWiki will have you configure your inference provider, API key, and LLM. You will also be able to set a LangSmith API key to trace your OpenWiki runs to a LangSmith tracing project named "openwiki" (optional).

These configuration options and secrets will be saved to `~/.openwiki/.env` on your local machine.

## Local Connectors

OpenWiki's first-run onboarding offers connector setup for local Git repositories, Notion, Gmail, X/Twitter, Web Search, and Hacker News. During an ingestion run, deterministic connector tools write raw data and manifests under `~/.openwiki/connectors/<connector>/raw/`, then source-specific agent runs synthesize the local wiki under `~/.openwiki/wiki/` from those local files.

You can configure the same connector more than once. For example, add one Web Search source for AI research and another for NBA news; OpenWiki stores them as separate source instances such as `web-search-1` and `web-search-2`. Run all instances with `openwiki ingest all`, all instances for one connector with `openwiki ingest web-search`, or one instance with `openwiki ingest web-search-2`.

- `git-repo` reads configured local repository paths and writes compact manifests.
- `x` uses the X API directly with OAuth user-context credentials for home timeline, user posts, mentions, bookmarks, and list posts.
- `notion` targets the hosted Notion MCP server, so users should authenticate through Notion OAuth instead of pasting a Notion token into OpenWiki.
- `google` uses the Gmail API directly with OAuth user credentials to fetch recent mail, with room to add Drive, Calendar, and other Google providers later.
- `web-search` uses Tavily through LangChain and requires `TAVILY_API_KEY`.
- `hackernews` uses public Hacker News feed and search APIs, with no credentials required.

Connector secrets are referenced by env var name and stored in `~/.openwiki/.env`; connector config files should never contain raw secret values.

`openwiki auth <provider>` runs a local browser OAuth flow, saves returned tokens into `~/.openwiki/.env`, creates connector config when possible, and discovers MCP tools for MCP-backed providers. Slack and Gmail require app client credentials to already be set in that file; Notion uses dynamic client registration for hosted MCP; X uses OAuth 2.0 with PKCE. After `openwiki auth gmail`, the Google connector can ingest Gmail directly with no MCP transport setup.

`openwiki auth configure <provider>` and `openwiki auth tools <provider>` are advanced/retry commands for regenerating connector config or inspecting live MCP tools.

First-run onboarding also lets users choose a wiki template, customize its scope, and save per-source ingestion notes and source schedules in `~/.openwiki/onboarding.json`. The global personal wiki instructions are saved in `~/.openwiki/INSTRUCTIONS.md`. On macOS, source schedules are installed as user LaunchAgents under `~/Library/LaunchAgents/` and write logs under `~/.openwiki/logs/`.

See the OpenWiki operations docs for credential storage and provider setup notes.

## Customizing

OpenWiki supports OpenAI (with an API key or a ChatGPT login), OpenRouter, Fireworks, Baseten, NVIDIA NIM, an OpenAI-compatible provider, and Anthropic out of the box. The onboarding default is OpenAI with `gpt-5.6-terra`, and each inference provider also includes pre-defined model options plus support for custom model IDs.

### Alternative base URLs

To route the Anthropic provider at an alternative, Anthropic-compatible endpoint (for example a self-hosted or proxied gateway) instead of the default API, set `ANTHROPIC_BASE_URL` alongside `ANTHROPIC_API_KEY`:

```
OPENWIKI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=https://your-gateway.example.com/anthropic
```

### OpenAI-compatible endpoints

The `openai-compatible` provider targets any OpenAI-compatible chat-completions endpoint via a required base URL. This can be used for OpenAI-compatible LLM endpoints like those exposed by a LiteLLM gateway when it is used as a gateway — letting you reach whatever upstream providers the gateway fronts through a single OpenAI-shaped API. Set the model ID to whatever name the gateway exposes:

```
OPENWIKI_PROVIDER=openai-compatible
OPENAI_COMPATIBLE_API_KEY=your-gateway-key
OPENAI_COMPATIBLE_BASE_URL=https://your-gateway.example.com/v1
OPENWIKI_MODEL_ID=your-gateway-model-name
```

The `openai-chatgpt` provider calls OpenAI's Codex backend using your ChatGPT subscription instead of a metered API key. Model usage draws on your ChatGPT Plus/Pro/Team plan's included Codex usage rather than per-token API billing. It serves the same model list as the `openai` provider.

Instead of pasting an API key, run the setup wizard and complete a browser login:

```
OPENWIKI_PROVIDER=openai-chatgpt openwiki code --init
# or
OPENWIKI_PROVIDER=openai-chatgpt openwiki personal --init
```

The wizard opens `https://auth.openai.com` in your browser (and also prints the URL for headless/SSH use, where you can open it on another machine — or paste the redirect URL back into the terminal to finish without a callback). After you sign in with your ChatGPT account, OpenWiki captures the OAuth callback, shows the signed-in email and plan, and then continues to model and LangSmith selection just like the other providers. It stores the resulting access token, refresh token, expiry, account id, email, and plan in `~/.openwiki/.env` (`OPENAI_CHATGPT_ACCESS_TOKEN`, `OPENAI_CHATGPT_REFRESH_TOKEN`, `OPENAI_CHATGPT_EXPIRES_AT`, `OPENAI_CHATGPT_ACCOUNT_ID`, `OPENAI_CHATGPT_EMAIL`, `OPENAI_CHATGPT_PLAN`). These are managed for you — the access token is refreshed automatically when it expires, so you normally never edit them by hand. Treat the refresh token like a password.

Base URLs (and all credentials) can be set in your environment or stored in `~/.openwiki/.env`.

### Provider retry attempts

OpenWiki uses LangChain's built-in retry handling for transient provider errors. To override the number of retries after the first provider request, set `OPENWIKI_PROVIDER_RETRY_ATTEMPTS`:

```
OPENWIKI_PROVIDER_RETRY_ATTEMPTS=3
```

The value must be a positive integer. If the value is unset, OpenWiki defaults to 3 retries.

추가되었으면 하는 추론 제공자 또는 모델이 있다면 PR을 열어주세요!

## 기여하기

기여를 환영합니다! PR을 열기 전에 [CONTRIBUTING.md](https://github.com/langchain-ai/openwiki/blob/main/CONTRIBUTING.md) 파일을 꼭 읽어주세요. 저희는 PR의 범위를 하나의 변경 사항으로 엄격하게 제한하고 있으며, 관련 없는 변경 사항을 묶어 제출하는 PR은 분할 요청과 함께 닫힐 수 있습니다.$seed_869909181cc3$,
        'markdown',
        '869909181cc3e93700f848a755b28c7c6b701e4a40ac274a127b00d8888b2f9e',
        NULL,
        $seed_3d17e0a05463${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/langchain-aiopenwiki OpenWiki is a CLI that writes and maintains agent documentation for your codebase..md"}$seed_3d17e0a05463$::jsonb
    ),
    (
        '74f990c5-6ff7-51ae-b52e-feb27f85dbb6',
        '40f5b175-c9a5-59d1-9717-46f0028fad92',
        'user/mock-clipping-user',
        '85811c74-af42-51c9-88d5-bd8eba1cda29',
        1,
        $seed_7da9d036bb24$‘역주행 신화’ 리센느, 멜론 채팅 라이브 역대 걸그룹 1위$seed_7da9d036bb24$,
        $seed_68839bb9ca4e$[[조선일보]]$seed_68839bb9ca4e$,
        '2026-07-13T00:00:00Z'::timestamptz,
        '2026-07-15'::date,
        $seed_f9061bb8f862$역주행 신화 리센느, 멜론 채팅 라이브 역대 걸그룹 1위  유행어 거제 야~호 이후 리센느 검색수 6550배 증가    역주행 신화 중소돌의 기적 리센느가 역대급 팬덤 화력과 화제성을 선보이고 있다. 뮤직 플랫폼 멜론의 실시간 소통 서비스 뮤직웨이브에서 진행된 리센느의$seed_f9061bb8f862$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_faa7ac636bbc$![그룹 리센느/ 사진제공=더뮤즈엔터테인먼트](https://www.chosun.com/resizer/v2/GQYTIMBSGNSDON3CMIZGMOLGGI.jpg?auth=f4c0b9a83ce321c9003ac3e738d4a05ad50afd98bb4c04b761507e58ae6d6e45&width=616)

그룹 리센느/ 사진제공=더뮤즈엔터테인먼트

‘역주행 신화’ ‘중소돌의 기적’ 리센느가 역대급 팬덤 화력과 화제성을 선보이고 있다. 뮤직 플랫폼 멜론의 실시간 소통 서비스 ‘뮤직웨이브’에서 진행된 리센느의 라이브 채팅 이벤트가 최대 동시 접속자 수 기준 역대 걸그룹 중 1위를 차지했다고 13일 밝혔다.

지난 8일 오후 6시 30분부터 7시 30분까지 진행된 리센느의 뮤직웨이브 라이브 채팅 이벤트는 뮤직웨이브 전체 채널 중 아티스트 중복을 제외한 기준으로 동시 접속자 수 역대 7위를 기록했다. 걸그룹 중에서는 1위에 해당하는 성적이다. 멜론 측은 “뮤직웨이브에서 재생되는 음악은 모두 멜론 차트에 그대로 반영되는 만큼, 이날 이벤트는 리센느의 ‘러브 어택(LOVE ATTACK)’이 같은 날 오후 10시 멜론 TOP100 1위에 등극한 것에 적지 않은 영향을 미쳤을 것으로 분석된다”고 밝혔다. 멜론 뮤직웨이브는 다양한 주제와 아티스트 이름을 내건 채널에서 실시간으로 재생되는 음악을 함께 청취하며 채팅까지 즐길 수 있는 서비스다.

특히 멜론에 따르면 걸그룹 리센느를 검색한 이용자 수가 이들의 유행어 ‘거제 야-호’가 탄생한 이후 65배 이상 늘어난 것으로 나타났다. 지난달 4일 기준 멜론에서 리센스를 검색한 이용자 수는 ‘거제 야-호’가 포함된 유튜브 영상이 업로드된 지난 3월 20일 대비 6550% 증가했다.

![리센느(방송화면 갈무리)](https://www.chosun.com/resizer/v2/GBRDQMTCGIYTOYJRMEZTOMDCG4.jpg?auth=cffe9388f81de174d27f2cc9208573806850bac20aaa0aec1d807700c7784610&width=616)

리센느(방송화면 갈무리)

![리센느/멜론 뮤직 웨이브](https://www.chosun.com/resizer/v2/SYJ4N7DXUFB3PIT46TMJ4JVDVQ.png?auth=9291c165feef30fe6d14e2e2c9cf5c7c88a7f08eb6b5d5c11f2b1e3be1f923d3&width=616)

리센느/멜론 뮤직 웨이브

리센스는 미나미, 리브, 제나, 원이, 메이 5인으로 구성된 걸그룹으로 2024년 3월 데뷔했다. ‘중소돌’이 그렇듯 회사 대표가 1000만원으로 설립해 발로 뛰며 팀을 키웠고, 물이 새고 에어컨도 나오지 않던 지하 연습실에서 실력을 키우며 특히 거제 출신 원이의 사투리가 물씬 담긴 유튜브를 통해 자신들의 이야기를 고스란히 전달하며 진정성과 성장 서사를 얻었다.

‘거제 야호’는 거제 출신 멤버 원이가 유튜브에서 일본에서 유행한 패션 스타일인 ‘갸루’(Girl·걸의 일본식 발음) 콘셉트인 영상에서 “너 이러고 거제 가면 거제 시민들에게 혼나 진짜”라고 하자 일본인 멤버 미나미가 “거제 야호!”라고 외친 한마디가 올봄 최고의 밈(Meme·온라인 유행 콘텐츠)으로 부상하며 화제가 됐다. 이후 이들의 대표곡 ‘러브 어택’은 여름에 어울리는 시원한 사운드와 귓가에 맴도는 멜로디로 역주행하며 멜론 차트 1위까지 점령했다.

최근에는 이들의 유튜브에 등장하는 ‘무섭노’의 사투리 ‘노’ 어미가 고(故) 노무현 전 대통령을 조롱하는 이른바 ‘일베 용어’라는 일부의 지적으로 논란에 휩싸이자, 거제시까지 나서 “사투리가 맞다”고 공식 발표하는 등 각종 화제의 중심이 되기도 했다.

문화부 '대중문화팀'을 이끌고 있습니다. 럭셔리 섹션 '더부티크'도 맡고 있습니다.$seed_faa7ac636bbc$,
        'markdown',
        'faa7ac636bbc30a4d9279c5079b8e7ee915094ba3df4465a1bf24fbab3f71646',
        NULL,
        $seed_b8244542882f${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/‘역주행 신화’ 리센느, 멜론 채팅 라이브 역대 걸그룹 1위.md"}$seed_b8244542882f$::jsonb
    ),
    (
        'd64c529c-c116-5fde-aa18-13f612d83177',
        '61290dc1-93ec-56a7-b355-8819789fc957',
        'user/mock-clipping-user',
        '57084f6e-f865-546f-b0bb-728eaa11c029',
        1,
        $seed_f61ce9279cb1$“삼전닉스 레버리지 탓에 주가 요동” 美·日·대만도 비판$seed_f61ce9279cb1$,
        $seed_68839bb9ca4e$[[조선일보]]$seed_68839bb9ca4e$,
        '2026-07-14T00:00:00Z'::timestamptz,
        '2026-07-15'::date,
        $seed_bff2055d1ce3$삼전닉스 레버리지 탓에 주가 요동 美·日·대만도 비판 글로벌 반도체株 교란 주범 지적 코스피 급변동에 증시 충격 받자 레버리지 살상력 증명 섬뜩해 SK하이닉스와 삼성전자의 레버리지지렛대가 부러졌다. 대만의 유명 경제 평론가 셰진허謝金河 차이신미디어그룹 이사장은 13일$seed_bff2055d1ce3$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_17d9ac3f8e75$![2024년 서울에서 열린 제26회 반도체 전시회(SEDEX 2024)에 전시된 SK하이닉스 제품./로이터 연합뉴스](https://www.chosun.com/resizer/v2/CPA2FSHSHNN3NI4GEX5JEQ2XKE.jpg?auth=77adc2399259eb40267cba25f84b6689f449f1377ad9f2d70a9d855a4f012289&width=616)

2024년 서울에서 열린 제26회 반도체 전시회(SEDEX 2024)에 전시된 SK하이닉스 제품./로이터 연합뉴스

“SK하이닉스와 삼성전자의 레버리지(지렛대)가 부러졌다.”

대만의 유명 경제 평론가 셰진허(謝金河) 차이신미디어그룹 이사장은 13일 페이스북에 한국 대표 반도체주 투자에 대해 비판적인 글을 실었다. 이날 대만 증시는 TSMC의 호실적으로 상승이 예상됐으나 SK하이닉스, 삼성전자가 10%대 폭락한 충격을 받아 1% 상승하는 데 그쳤기 때문이다. 셰 이사장이 그 이유로 지적한 건 ‘2배 레버리지 상품’이다. 그는 “메모리 반도체의 펀더멘털은 아직 큰 문제가 없지만, 이번 폭락으로 2배 레버리지 상품의 살상력이 실제로 증명됐다”고 말했다. 그는 “SK하이닉스는 폭락의 여파로 삼성전자에 이어 일본 키옥시아까지 떨어지며 연쇄적으로 한·일 증시의 폭락을 견인했다”고 했다. 이날 SK하이닉스는 1996년 상장 이후 최대 낙폭(-15.37%)을 기록했고, 일본 키옥시아도 13% 하락 마감했다.

<iframe frameborder="0" src="https://c40d04b5b9b7d31bf1a9aba6b7d5e78a.safeframe.googlesyndication.com/safeframe/1-0-45/html/container.html" title="서드 파티 광고 콘텐츠" width="336" height="280" allow="private-state-token-redemption;attribution-reporting" aria-label="광고"></iframe>

충격파는 태평양을 건너 미국 시장에까지 미쳤다. 13일 뉴욕 증시에서는 SK하이닉스 주식예탁증서(ADR)가 9% 넘게 폭락했다. 미국 반도체주 샌디스크(-12.6%), 마이크론(-4.3%), AMD(-4.2%) 등도 일제히 하락했다.

![그래픽=백형선](https://www.chosun.com/resizer/v2/H3HAQNNDDBHWZFY5T2ZPQXT2RQ.jpg?auth=8228024157e9f8d5d697a0f87d9d4701dbad98fb48319968f36da6c5ca232ad1&width=616)

그래픽=백형선

◇미국·일본·대만도 흔드는 레버리지 상품

최근 외신에서 가장 많이 보이는 단어 중 하나는 삼성전자·SK하이닉스의 ‘변동성(volatility)’이다. 과거 반도체 주식의 움직임은 ‘미국 증시→아시아 증시’ 방향이었지만, 지금은 삼성전자, SK하이닉스 등 메모리 반도체 ‘투 톱’이 있는 한국 증시에서 출발해 ‘아시아 증시→미국 증시’ 방향으로 영향을 주고 있기 때문이다. 이런 상황에서 5월 27일 삼성전자·SK하이닉스의 주가 움직임에 2배 베팅할 수 있는 소위 ‘삼전닉스 단일상품 레버리지 상품’이 국내에서 출시됐다. 이후 코스피가 극심한 변동성에 휩싸이고, 이 영향으로 글로벌 반도체 주식 시장이 흔들리고 있는 것에 대한 비판이 거세지는 양상이다. 14일도 삼성전자·SK하이닉스는 폭락과 폭등을 거듭하는 ‘V’ 자 움직임을 보이며 각각 3.4%, 3.7% 상승 마감했는데, 일본 키옥시아(2.98%), 대만 TSMC(-0.82%)도 주가가 비슷한 모양으로 움직였다.

![13일 서울 중구 우리은행 본점 딜링룸 전광판에 코스피 종가가 나오고 있다. 이날 코스피는 전거래일 대비 669.01포인트(8.95%) 하락한 6806.93, 코스닥은 전일 대비 38.07포인트(4.55%) 하락한 799.36로 마감했다. 삼성전자는 10.7% 급락한 254,500원에, SK하이닉스 15.37% 급락한 1,845,000원에 거래를 마쳤다. /뉴스1](https://www.chosun.com/resizer/v2/MHEIDPEBC5JCHMAVGS7ESCVNOI.JPG?auth=c2fd85a05e051be8fb4128f56d5f0a2e6215fd9666cd603cd83a4b0a45a91743&width=616)

13일 서울 중구 우리은행 본점 딜링룸 전광판에 코스피 종가가 나오고 있다. 이날 코스피는 전거래일 대비 669.01포인트(8.95%) 하락한 6806.93, 코스닥은 전일 대비 38.07포인트(4.55%) 하락한 799.36로 마감했다. 삼성전자는 10.7% 급락한 254,500원에, SK하이닉스 15.37% 급락한 1,845,000원에 거래를 마쳤다. /뉴스1

일본 니혼게이자이신문은 지난 10일 ‘레버리지 ETF(상장지수펀드) 급팽창, 운용자산 8조엔이 시장 교란’이라는 기사에서 “단일종목 레버리지 상품이 시장을 교란하고 있다”며 “이 소용돌이 중심에 있는 것이 바로 SK하이닉스”라고 보도했다. 미국 블룸버그는 ‘전 세계 시장을 흔드는 한국의 레버리지 ETF’라는 제목의 팟캐스트에서, 개인 투자 열풍과 AI발 반도체 수요가 단일종목 레버리지 ETF라는 형태로 결합했다고 진단했다. 글로벌 투자은행 바클레이스의 알렉산더 알트만 글로벌 주식 전술전략 총괄은 “이들 레버리지 ETF가 만들어내는 일일 추가 매수·매도 규모가 섬뜩하다(terrifying)”며 “한국에서 개인 투자자가 레버리지 상품에 과도하게 노출된 상황이 밤잠을 설치게 한다”고 했다.

<iframe frameborder="0" src="https://c40d04b5b9b7d31bf1a9aba6b7d5e78a.safeframe.googlesyndication.com/safeframe/1-0-45/html/container.html" title="서드 파티 광고 콘텐츠" width="336" height="280" allow="private-state-token-redemption;attribution-reporting" aria-label="광고"></iframe>

◇미 금융당국도 수년째 경고

미국 금융당국도 이미 수년 전부터 단일종목 레버리지 상품이 개인투자자는 물론 금융 시스템 전반에도 위험을 초래할 수 있다고 경고해 왔다.

<iframe frameborder="0" src="https://c40d04b5b9b7d31bf1a9aba6b7d5e78a.safeframe.googlesyndication.com/safeframe/1-0-45/html/container.html" title="서드 파티 광고 콘텐츠" width="336" height="280" allow="private-state-token-redemption;attribution-reporting" aria-label="광고"></iframe>

14일 금융권에 따르면 미국 증권거래위원회(SEC)는 주식 한 종목만 추종하는 단일종목 레버리지 상품의 출시가 추진되던 2021년부터 해당 상품의 위험성을 지속적으로 경고해왔다. 게리 겐슬러 당시 SEC 의장은 그해 10월 “법적으로 상장이 가능하다는 사실이 모든 투자자에게 적합한 상품이라는 의미는 아니다”라며 “이 상품은 개인투자자뿐 아니라 전문투자자에게도 상당한 위험을 초래할 수 있다”고 경고했다. 이어 “시장 변동성이 커지면 금융 시스템 전반의 위험으로 이어질 수 있다”고 우려했다. 이후 운용사들이 2022년 7월부터 SEC 승인을 우회해서 단일종목 레버리지 상품들을 내자, 민간 자율규제기구인 금융산업규제기구(FINRA)가 증권사 등이 일반 개인 투자자에게 구조가 복잡한 이런 상품을 권유·추천하는 행위를 엄격하게 제한하는 식으로 규제하고 있다.

구독수

### 631

금융위원회, 금융감독원 등을 출입하고 있다. 은행과 보험, 카드 등 금융업권 전반을 취재한다. 367회·404회 이달의 기자상(경제보도 부문)을 수상했다.$seed_17d9ac3f8e75$,
        'markdown',
        '17d9ac3f8e753dd714d6e52f98b9acc739d2fbff37a922bc13e5cf928f92ae93',
        NULL,
        $seed_214be983ef3f${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/“삼전닉스 레버리지 탓에 주가 요동” 美·日·대만도 비판.md"}$seed_214be983ef3f$::jsonb
    ),
    (
        '9c80d01d-fcb5-53c5-b3e4-15475d616bcb',
        '25ecb002-f4bb-5d66-8cd1-b3118a29f8ac',
        'user/mock-clipping-user',
        '8c8e0bf2-c481-55d4-96ac-481efc187443',
        1,
        $seed_29439fb79af3$개발/기술/스타트업 뉴스 서비스$seed_29439fb79af3$,
        NULL,
        '2026-07-14T00:00:00Z'::timestamptz,
        '2026-07-15'::date,
        $seed_c2d147fc8eb6$개발 뉴스, 기술 관련 새소식, 스타트업 정보와 노하우, 세상의 재미난 것들을 좋아하는 사람들을 위한 뉴스 사이트. 이메일 뉴스레터/X(Twitter)/Slack용 봇으로 구독 가능 GeekNews에서 개발, 기술, AI, 오픈소스, 스타트업 뉴스를 함께 읽고, 매일 업데이트되는 새…$seed_c2d147fc8eb6$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_ce78dbc89ffb$1

## [이해가 새로운 병목이다](https://www.geoffreylitt.com/2026/07/02/understanding-is-the-new-bottleneck.html)

(geoffreylitt.com)

[에이전트가 작성한 코드가 사람 주변에 계속 쌓이는 상황에서 개발 속도를 제한하는 요소는 코드 생성 능력이 아니라 시스템을 따라가며 다음 변화...](https://news.hada.io/topic?id=31429)

31 points by [GN⁺](https://news.hada.io/@neo) | [댓글 2개](https://news.hada.io/topic?id=31429&go=comments)

2

## [이봐, 신입, 우린 당신에게 주어진 일이나 끝내라고 채용한 게 아니야](https://newsletter.kentbeck.com/p/hey-n00b-we-didnt-hire-you-to-complete)

(newsletter.kentbeck.com)

[신입(N00b) 엔지니어의 가치는 완료한 작업 수가 아니라, 장차 주변 사람의 생산성까지 높이는 엔지니어로 성장할 가능성에서 결정됨 선임 엔지니...](https://news.hada.io/topic?id=31420)

31 points by [GN⁺](https://news.hada.io/@neo) | [댓글 5개](https://news.hada.io/topic?id=31420&go=comments)

3

## [Hexana - JetBrains의 WebAssembly 및 바이너리 분석 도구](https://jetbrains.github.io/hexana/)

(jetbrains.github.io)

[.wasm 파일의 구조 분석/편집/실행/디버깅을 지원하며 JetBrains 플러그인과 VS Code 확장으로 제공 두 제품이 하나의 Kotlin Multiplatform 코어...](https://news.hada.io/topic?id=31445)

2 points by [xguru](https://news.hada.io/@xguru) | [댓글과 토론](https://news.hada.io/topic?id=31445&go=comments)

4

## [Papermake - Typst 기반의 셀프 호스팅 가능한 PDF 문서 생성 서버](https://github.com/rkstgr/papermake)

(github.com/rkstgr)

[Papermake는 Typst 템플릿을 이용하여 PDF를 생성하는 HTTP 기반 문서 생성 서버임. 목적 Typst 템플릿의 중앙 집중식 관리 REST API를 통한 PDF...](https://news.hada.io/topic?id=31432)

11 points by [regentag](https://news.hada.io/@regentag) | [댓글과 토론](https://news.hada.io/topic?id=31432&go=comments)

5

## [FOSS for All, 국내 오픈소스 소액 지원 사업 시작](https://forum.fossforall.org/t/foss-for-all-microgrants-2026/105)

(forum.fossforall.org)

[올해 FOSS for All(포스포올)이 처음으로 선보이는 Microgrants 지원 사업에 함께할 오픈소스 프로젝트와 커뮤니티를 모집합니다. Microgrants 지...](https://news.hada.io/topic?id=31436)

6 points by [guesswhat](https://news.hada.io/@guesswhat) | [댓글과 토론](https://news.hada.io/topic?id=31436&go=comments)

6

## [컴퓨터과학 학위는 죽지 않았다](https://spectrum.ieee.org/computer-science-degree-isnt-dead)

(spectrum.ieee.org)

[최근 미국 CS 졸업자의 실업률은 6.1%로 높지만, 실업률/불완전고용/초기 소득을 함께 평가하면 CS와 컴퓨터공학은 여전히 노동시장 성과가 우수한...](https://news.hada.io/topic?id=31421)

12 points by [GN⁺](https://news.hada.io/@neo) | [댓글 8개](https://news.hada.io/topic?id=31421&go=comments)

7

## [2026년에 왜 코드를 작성하는가](https://softwaredoug.com/blog/2026/07/09/write-code)

(softwaredoug.com)

[소프트웨어 엔지니어의 역할은 코드 생산을 넘어 소프트웨어 팩토리를 구축·유지하는 일로 확장됐지만, 시스템을 이해하고 개선하려면 여전히 직접...](https://news.hada.io/topic?id=31411)

14 points by [GN⁺](https://news.hada.io/@neo) | [댓글 4개](https://news.hada.io/topic?id=31411&go=comments)

8

## [고객 이탈을 막는법: 10년간 내가 배운 모든 것](https://www.youtube.com/watch?v=vdCi2GAQA_Y)

(youtube.com)

[구독 비즈니스의 고객 이탈률(churn) 은 제품 품질만이 아니라 시장·고객군·사용 빈도에 크게 좌우되며, 오래 남는 고객을 찾아 그들에게 맞춰 제...](https://news.hada.io/topic?id=31384)

28 points by [GN⁺](https://news.hada.io/@neo) | [댓글과 토론](https://news.hada.io/topic?id=31384&go=comments)

9

## [Show GN: 대한민국 제도 100개를 한장씩 체계도로 만들었습니다.](https://news.hada.io/topic?id=31313)

(hosungseo.github.io)

[AI리터러시를 조금 다른 방향으로 고민해봤습니다. 일반인이 AI를 배우는 것이 아니라 AI를 통해서 다른 전문 영역의 리터러시를 높이는 것입니다....](https://news.hada.io/topic?id=31313)

87 points by [hosungseo2026](https://news.hada.io/@hosungseo2026) | [댓글 29개](https://news.hada.io/topic?id=31313&go=comments)

10

## [GeekNews로 어쩌다가 취업하기](https://throneinvest.ai/)

(throneinvest.ai)

[대학교 4학년 학기 중, 저는 투자 AI 프로덕트 Cresco를 개발했고 예상치 못한 결과로 이어졌습니다. 5년간 주식 투자를 하며 종목 발굴과 분석의...](https://news.hada.io/topic?id=31434)

6 points by [sungmin330](https://news.hada.io/@sungmin330) | [댓글 2개](https://news.hada.io/topic?id=31434&go=comments)

11

## [MS 깃허브 개인 액세스 토큰(PAT) 대량 유출…경찰 수사 착수](https://www.mt.co.kr/society/2026/07/14/2026071410063885156)

(mt.co.kr)

[경찰청 국가수사본부가 GitHub 계정의 접속 권한(개인 액세스 토큰, PAT) 다수가 외부로 유출된 사실을 확인하고 수사에 나섰다. 유출된 정보는 Gi...](https://news.hada.io/topic?id=31444)

1 point by [awbrg789](https://news.hada.io/@awbrg789) | [댓글과 토론](https://news.hada.io/topic?id=31444&go=comments)

12

## [데이터 품질에 관하여 - 기본 원리](https://pivotal.substack.com/p/on-data-quality-1-basics)

(substack.com/pivotal)

[데이터에는 타고난 품질이 없으며, 특정 사용 사례에서 데이터가 만들어내는 가치가 커질수록 품질이 높다고 평가할 수 있음 데이터 품질은 개별...](https://news.hada.io/topic?id=31428)

9 points by [GN⁺](https://news.hada.io/@neo) | [댓글과 토론](https://news.hada.io/topic?id=31428&go=comments)

13

## [코드베이스를 완전히 이해하지 못해도 괜찮은 이유](https://www.seangoedecke.com/in-defense-of-not-understanding-your-codebase/)

(seangoedecke.com)

[수천만 줄에 이르는 대규모 시스템은 누구도 전체를 머릿속에 담을 수 없으므로, 엔지니어는 부분적으로 정확한 이해만으로도 효과적으로 작업할...](https://news.hada.io/topic?id=31377)

23 points by [GN⁺](https://news.hada.io/@neo) | [댓글 3개](https://news.hada.io/topic?id=31377&go=comments)

14

## [Precursor: 전체 세션에서 에이전트 행동을 탐지하는 Cloudflare 시스템](https://blog.cloudflare.com/introducing-precursor/)

(blog.cloudflare.com)

[로그인·가입·결제 같은 개별 검증 지점만으로는 실제 브라우저와 JavaScript를 활용하는 자동화를 가려내기 어려워지자, Cloudflare는 전체 사용자...](https://news.hada.io/topic?id=31437)

2 points by [GN⁺](https://news.hada.io/@neo) | [댓글 1개](https://news.hada.io/topic?id=31437&go=comments)

15

## [외부 루프를 소유하라](https://addyo.substack.com/p/own-the-outer-loop)

(substack.com/addyo)

[에이전트가 조사·구현·검증을 반복하는 내부 실행 루프를 맡더라도, 엔지니어는 배포 여부를 결정하고 결과에 책임지는 외부 루프를 소유해야 함...](https://news.hada.io/topic?id=31372)

17 points by [GN⁺](https://news.hada.io/@neo) | [댓글과 토론](https://news.hada.io/topic?id=31372&go=comments)

16

## [책을 더 많이 읽는 방법](https://scotto.me/blog/2026-07-12-how-to-read-more-books/)

(scotto.me)

[몇 년간 주 1권가량 읽을 수 있었던 비결은 별도의 독서 시간을 확보하는 대신, 스마트폰이나 화면을 보던 자투리 시간을 책 읽기로 바꾼 데 있음...](https://news.hada.io/topic?id=31382)

16 points by [GN⁺](https://news.hada.io/@neo) | [댓글 3개](https://news.hada.io/topic?id=31382&go=comments)

17

## [‘인터넷의 아버지’ Vint Cerf, 은퇴](https://techcrunch.com/2026/06/30/the-father-of-the-internet-is-finally-retiring/)

(techcrunch.com)

[인터넷의 기반인 TCP/IP 공동 설계자 Vint Cerf가 20년 넘게 몸담은 Google에서 다음 주 퇴임하며 기술계 경력을 마무리함 83세인 Cerf는 Robert K...](https://news.hada.io/topic?id=31410)

7 points by [GN⁺](https://news.hada.io/@neo) | [댓글 2개](https://news.hada.io/topic?id=31410&go=comments)

18

## [Zig 창시자는 진실을 말하지만, Antropic은 허풍을 떨고 있다.](https://raymyers.org/post/zed-creator-calls-spade-a-spade/)

(raymyers.org)

[Anthropic이 소프트웨어 엔지니어링의 종말을 미래 가치로 내세우는 가운데, Bun의 Zig→Rust 전환도 AI가 엔지니어링을 대체할 수 있다는 홍보 서...](https://news.hada.io/topic?id=31406)

7 points by [GN⁺](https://news.hada.io/@neo) | [댓글 4개](https://news.hada.io/topic?id=31406&go=comments)

19

## [AI 에이전트 시대의 새로운 SaaS 플레이북](https://www.thevccorner.com/p/the-new-saas-playbook-ai-agent-era)

(thevccorner.com)

[소프트웨어 제작 비용이 0에 가까워지면서 기능과 UI는 빠르게 복제 가능한 상품이 되고, SaaS의 가치는 소프트웨어 포장 아래의 희소 자산으로 이...](https://news.hada.io/topic?id=31387)

14 points by [GN⁺](https://news.hada.io/@neo) | [댓글과 토론](https://news.hada.io/topic?id=31387&go=comments)

20

## [AgentsView - 여러 AI 코딩 에이전트의 세션 검색/분석/비용 추적 도구](https://github.com/kenn-io/agentsview)

(github.com/kenn-io)

[Claude Code, Codex, Cursor, Gemini CLI, OpenCode 등 다양한 코딩 에이전트의 세션을 자동 수집 대화 검색, 토큰/비용 통계, 활동 분석, 변경 파...](https://news.hada.io/topic?id=31370)

14 points by [xguru](https://news.hada.io/@xguru) | [댓글 1개](https://news.hada.io/topic?id=31370&go=comments)$seed_ce78dbc89ffb$,
        'markdown',
        'ce78dbc89ffbd2db89a45ac63e4b6591bb7a8130a7c515bfc0c1edcd9cd8564b',
        NULL,
        $seed_afaeb4d119f6${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/개발기술스타트업 뉴스 서비스.md"}$seed_afaeb4d119f6$::jsonb
    ),
    (
        'c38832b0-82a1-5a46-8d64-a032851f64cc',
        '0bfbb68b-c8e7-59b7-9a6b-adf2121c0772',
        'user/mock-clipping-user',
        'fcad5d17-b851-5886-8d7d-67047bfa449e',
        1,
        $seed_7cfea5451a7c$검색결과$seed_7cfea5451a7c$,
        NULL,
        NULL,
        '2026-07-15'::date,
        NULL,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_af01352e701b$## 환율 계산기

[주식 시장 요약](https://www.google.com/finance?sa=X&ved=2ahUKEwistaaXxNOVAxVee_UHHeGlEkYQ6M8CegQIHxAG) > 이더

2,796,485.50KRW

팔로우

−16,815.96 (0.60%)오늘지난 5일지난 1개월지난 6개월연간 누계지난해지난 5년전체 기간7월 15일 오전 1:27 UTC ·

[면책조항](https://www.google.com/intl/ko-KR/googlefinance/disclaimer/)

1일

5일

1개월

6개월

연중

1년

5년

최대

의견[이더에 대해 자세히 알아보기](https://www.google.com/finance/quote/ETH-KRW?sa=X&ved=2ahUKEwistaaXxNOVAxVee_UHHeGlEkYQ-fUHegQIHxAw)

주요 뉴스

[![](data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBwgHBgkIBwgKCgkLDRYPDQwMDRsUFRAWIB0iIiAdHx8kKDQsJCYxJx8fLT0tMTU3Ojo6Iys/RD84QzQ5OjcBCgoKDQwNGg8PGjclHyU3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3N//AABEIAKwBPAMBIgACEQEDEQH/xAAcAAACAgMBAQAAAAAAAAAAAAAAAQIDBAUGBwj/xAA9EAABAwIEBAQDBQYGAwEAAAABAAIDBBEFEiExBkFRYRMicYEykaEUI0KxwQczUnLR4RVigqLw8SVTskP/xAAZAQEAAwEBAAAAAAAAAAAAAAAAAQIDBAX/xAArEQACAwABAwIFBAMBAAAAAAAAAQIDESEEEjEiQRMyUZGxBRRCcSNhgRX/2gAMAwEAAhEDEQA/APWkIQuo4AQhCAEIQgwEIQgwEIQhIIQhACEJ2QCQnZFkAkJ2RZAJCdkWQCQnZFkAkJ2RZAJCdkWQCQnZJAGyE0kAIQhACEIQjAQhCDAQhCAEIQgBClZFkJEhOyLIBWRZNCaBWRZNCaAsiyEJoCyLIQmkhZCEKACEJoBIXNcR8SS4TWObBG2dkHhGohtZwa/PYg3/AMhH/em7wvEqXFqKOsoZRJC/nzaeYI5EdFZxkl3ewwykIQqgEIQgBCEIAQmkgBFk0kAWRZCanQKyCEITSBWRZNCaBWQmhNAkAJ2RZARQpWRZACE0KCRITshAJCaEAkJoQCQmhAJCaEAkJoQAkmmgOMghlfx9VTyQxuppwaZ4drma2NhufR1x7lYOK083CmNGtwBt6aUXmo812S5dHZejhv7+oW7oIxLjss4O95B75h/RVcVRAGOpkL/AcRnyH4HfxDvv8l0xfqS9sI1LybvBMYo8boW1dDJmbs9h+KN3QhZ68uqKfE+HMS/xLD8pc7V7G/u6pm9wBse3uOa73h7HqPHqIT0rrSD97CT5oz37d1S2rt9UfBY2iEIWJAIQhAHJJNCASk0ZnAE2CSEAEWKEIQCQmhAJCaEAk9kIQCQmhAJCaEAITQoAkJoQAhCEJBCE0AjvohNCASE0IBITQgEk92RjnHkCVJYuKOyYdUuG/hkD30UrlkM0WDscK9ridTBI42/mZ/RbSupW1lDJA/ZwtfoeR+axcHj8okt/+IHz1WzZrcdQtZP1aVw5XB44sTopsGxFp8WmJMZ/E0dR6HT0IWgmoq3h/F2yxO8Oq1ySgeSobzBHXqP133/EMcmGYpT4rTjQ6PA5nmPcfkt7V0tHjWHNbIM8MgD43jRzTyIPIrfv7efZk0zcGPAMcp8Yp7ssyoaPvIr3t3HULarzWvocRwatjkbP9/m+7qGtAEh6H/Mfr679hw7j0eKx+FNlirWDzx30d/mb27clz2V5zHwdNlaa74ePwbpCaFkYCQpEWtqEkAkJoQCQmhAJCaEArITQgEkmhCBITQgEhNCkDQmhQSKyLJoQCsiyaEArITQgEhNCASE0IBITQgEtXxLN4OFOPN8kbfbML/RbVaDi0uf/AIdANpKh2b0DHfqQrQ5kiJeDKw1uSAt/hs35LLGhBHJUUY+6kPWQq9S/JCMPFqJtdRTU2lyLsPRw2Wk4PrXMfLhk+jm3fFf/AHN9jr810L5BHI/O7QgOHPtb6fVchirHtxj7bh7XscHB4c9hAL+Y9/1K2qXfFwZnN49OtxGgp8SpH0tWzNG8W03HcLgq/DazCa5od+9ac0FU1tvE9Tyd+f59LFiPEj7f+Kgt1JLfzKzxVzyPbTytibUuF/CDQ4j2D9vVIuVax8o6KbXGWoq4a4gGJMFPV5Y6sezZPTv2XQLicXwudkv2ml+wUxzEyF0paB6WBsb3XTYDPPU4ZFLUyMleb2kYCA8dRf8APnuspxS9SL2utv0P/hsEIQszMSE0IQJCaEAkJoQCQmhAKyLJoQCshNCASE0IAQpIUEkUWTTQnBWRZNCDBWRZNCDBWRZNCDBWRZNCDBWRZNCDBLm+IZP/ADeGxk7a7X3N9enwfVdKtRjuAQ4v4cnjy01RHbJLGAdjexB3F1etpS5KyTa4KI8QZHBJGwsbM1xJEhs1ozEBxP1sq6aodUyfeV8BA3DXc+zR+rnLlcX4c4tpGvmgkjxIt+DwXiN1u7T+hK56PiDiOGf7HLRSQzt/BUPe157jNqR3C6lTGfySKxk4r1I9SxV7IIoJYJS98cwMkdv3jNnC23O49FRxNVUsuFOZBM1z2kOZkFwNdddhoTpuuVw3GcXawGSRzHnUslcHtPobXHyRKRi1WWMEVPVEXc3Nma705tv9UXTyjJNsl2VSWG6nqsVraXxGyNpqS2Vroz55HcwOd/kO601biAwSAU9G37RiM4LshOluZI6DoTrb1VmO4lT8P0LRmM07gfBhcdL83W5Db8lqcG4cxTHMRifJVv8Ask0Ylq6mN1rg/gaOpFhtoPkt4QjGLlP5TJzbyMTK4ZwWu4pxE1eLTPfhdM6wYPKyZ4/CB/COfy629Nknp6Z0MT3tYZHZImfxG2wHosGvrcP4awlrnNZDTwtyQxNsM1tmi65fDquuxHiDDqqqvknkcYw34WMa0m3zN7/9Llm5Xty8JGiSgjvErJoXKaYKyLJoQYKyLJoQYKyLJoQYKyLJoQYKyLJoQYRQpIQYRQpIQhghNFlBIkKVkWQkihSsiyAihSsiyAimnZFkAOdmttoEk7IsgEhOyLIBJKVkWQYcRiPFGN4RXvpquggqWt1b4YdG57erdSCPqOYUJONsNrqYMxHBpZI9y37uQD5kLscQoIMQp3Q1DLg7HmCuGxTCp8PeQ+NtQBoA8XD29gdLrspVVixrkxslKP8ARcH8M1kIdR1ktK47Mdd4Htqbe60uKYcJHxzUs1NVSwuzRSU0zc7f9BId8rq04HhtVSh0VP4cTjYiN1gHdLcj2sPda1/DUsLj9jrpGs/9cgNh/wA9F1wgl4n9+TF9vujZyYXLxJTvoGNmhkmaBI90ZBh21N/y5rtIY8K4N4fjgafCpadtm5jdzzbfuea84gp8Yw+dhYS6IbugNnN9hbX/AJotjVwVGLtpG18z3ygGzfGLiLg69CfhNtuvNZ3VOTWy9JpW4xRtJqJnFcuHVtS97s333hX8scZtlFuu5PcrcwFreIaClj0YyCSQDoNllYLh7MOoY4msDSGgEdLDZU0EYdxN4hJu2itb/V/dc3dw0vCJb2SbOgQnZFlym4kJ2RZAJJSsiyASSlZFkBFFlKyLICKFKyLICKFKy12MYxR4RAJKqTV3wsG7kLQrlOXbFazPVEtZSwvLJaiNrhyLlwlZx1VHN4LI4gdrakD1XHVWNSzTvkfKS5xuSSoUbJPIo9Wv9LUV3dRNRPdUJoU6eSJCaE0CQmgkAEk2A3JTQJC5vH+LoMNjP2WH7S8G184DQfTf6BcpS8e4jJO90j4spNwzILN7dVdVya1I66+jsmt8Hp6FytJxtSSGFs0JYXfG4G9vZbuhxrD6+Yw004dIPwnS/os9It6K+r5omehSQp05SKEwQ4XaQR1CajR4Ipp2Qp0CVFXTRVcJilbccj0PVZCE0hpPhnC11HUYNiHjRgPD25Xxn4Z2/wBQshkFPiUH2jDXDTR8LzYtPTsex+i6quooK+mdBUtzMPTQg9QeRXnOKGThbHIHTyva+Z2UTMb5ahnLONrjQXGu3Jd1U/i8fy/Jzyh2efBl1dO97HQuBY7TMLWcAqzJFTVtJWQva9jXNz5driwcPkQt5Vsjx/CnxwvMVQBcea1j07tOy4rDnyME9HO0tcDnDXaFrho4fL/5W9bc099vKKOEVHT0ysqIqaHNI8NzEMZ3cdgsTChfHqw/wQtbf1sf0XESYnVVuNYZBM67Y3RNY35An1JBW7wniWGmxPiGSqyWgqWwwtZ8TyAb3XLOp1wZ1Rqdk4Rhy2dyhecVHG1aanPG4MYDowDRZeH8fEVIbXxtMLtCYxYt791yxjN+x6tn6VfXHueHeJrGosQo69uakqI5dL2adR7bqc9ZTU8jY5qiNkjvha51iVB5/wAOe5nJahSQmlCKFKyjI5sbHPebNaLknko0JaNLdcVxPxa1sbqWg0cTZ0l9bdFrOG+MG4fJJFXue+ndrcalp/opipSXclwel/5lvw+5+foekOcGtJcQANSSsemrqSqe5lNURSObu1rrkLz7i7jeGsp/suGl7YT+8e4WLuw7LiocZqKWZlRTzPjeNnNNjZbw6eclpkumgo/5Hkvx/Z61jvFTcLqTFHTGdjPjdmtr0C83x3G2YpWTVDvGa523iSA2HICwFvRaetxSaWW7nkl3MlYVVJZ5IOnPuuirps5kdLsp6fFV5+pKapc+QR5teqxZJmNeQ65PW6qu6STyaHqsplOzLq3MeZdouyMMXB51t8rJa2fSTKiF8hjZNG543aHgkeysXjclPNFI19JiVNUNds4Ocw+4I0+azafinGMPzU9S+YAt+GQ38vVrv1C8n4Ms4O+XQR/jL78HqU1TTwfvp4o/53hv5rX1PEWFwRPk+0iQM/8AWLhx6B231XmkjqWpAkgrZqecm7nyjxSfQ3FlzuM1FbFXfZqqZ0hAu11yQ5vUX5K9fT97zSLekhQtnp6FinHpBtSuZG3ozzvPqSLD2DvVcfjHFlfiOYOqZPC/gzae65675Zw1ht1PRTlZGxuWK7tLtv8A83XbDpq4MxfULtyuOGXLVyykPlJJIsXdVhkujkJb7KttQcl7nXcdVbG5szXG1g3mea6O2KMXdN+5a2vc0gg8tuizMMxuWlrI5oyC9rgQD2WomZzBKoYcryTos5UxZvDr7ku1vUen1P7RKqSnDYRFHMNy1pN/mtJPxbiNXDllrZCMxJF7fkuR8ezco9Qe6sJzNBjNj0WP7SHsaVdXGt8RR6XwXxIYqtlJUSXhmNruPwu5Fejr5xhqXRODmnXouzwf9olbRweFUZahrRZvi3zD3XNb0sk/Shf8PqX3xaT9z1tC8rb+0bEM5e4RZTs3Jt6Kmp/aHic8jfAkEIAsQGA6/JZft7foZftHud6PWkLgsB45kkzHE8roWjWQANI9uahJ+0XLO7LTRmK+gLtQPVUdc0/BZfp9reLPuegWWBjWEUmNUD6OujzRu1a4aOY7k5p5ELQ1HGcJw7OxhgqXjQSa5R10/VcueL6iCOVn+JVLi+40aPpe9khGbexJX6fY4tz4MSZ2J8GYqyjrpc0BOalqz8LhzDh06jcbi6zMcdFXvZilG0snJDZ4bi4dawItuCNNOy5rFcfkraR9E4ufDmzkyOzvzdcx/TRYmB4uaZ4p6y5i2B/hHbt25fn7NacslL5vyeZfQqn6XqOswyLx8ewqVouDLqe1iR+RXK1FYft+JvB/eV87h6Zv7L0nh/DGMYyuM4mjF5IXNO977/MryCXxA5rnggyZpLfzOJVU1NywjpJyqsTXsZhq3EE8gq453SSgXsNz6LGafuZL89lBjy11hzRQSPSn1VkvLNzHiM9LOTBK5p3aQbFT/wAXmmlc50j3vI1JNytQ5xM+nJVve4VRfHoTroquqLe4Wh11taxM7rDOOMRogG+P4jLfDIMwC6ag/aHA9jTWU4B5mM7/ADXkcxucw5726oD35CWlZT6OMvBZ9VVN/wCSCPZqjjyjaQYGAtHxB5sfay0PEXHpq6V1NTQ+C11szi+5PZebuqZdBc3US5ztST6qkOjx8ku7poY64cmfU17nvLiblx0WLNUOBa3MczuSpByOBcNvomzWR0r9CR5V1qtLhI57Ortm9bLJ5C0Bp1JVD3m1r6DZQzuL72vrshzCSGt1cTsFphzObZbmzwh34mFUF5e4gag6hZUkHhxZXSW01DQpUkcd/KB6u5oVehTReGMzhr06JSB5cSL+6vzZyRoCOShY8iy3dXRC4MqjqnSOAJNiLDstnDiOUeDVMEkV75Xcu46ey52jeW5ch21WfI/xbX0vsehWE61JHfR1Uo8vlM3cuGMfTifCJnvsdYpSLgnkCLD0vuoQYheJ1JiEF4jo+KUEFvcX1ae61NNWT0hd4bnNuC1zeoO49FfHj0oAY9+do2DwHAfNc0q5L/Z6FXUVz43j6MnW4U+GlfJRSCoh5FjbOb/MP12VuCUcNN58SgbJKBYQyjRvqOvZRmx6YxHw8jHu0zMja0n1IF1hRVDsjrk3PXmr9tkoeo586eu308r6Gwr8BFZK+bBm7/FTZtR/Lfcdt/Vc/wCDLG4tOZpaSC1wsQeYW7pK0sILXEE99lmT/Z8UAdM4RVOg8YC+Yf5hz9d/VIWuHpn4LX9DGxOzp/sc4x5uBc9weScsIffWx6rfN4ep3C4xSPxD8LfBOUnub6fJa2roqjD3tFXGGh/wua4ODvQhdELq5vEzzbenuqWzi0axzHN0cFdTxk6klTkALQRt3UQ61gbLUw0Jxdhd0+iVP5iHvN+islLXN1sBbXXVY0OcOytOnbRBpZM4eJ5kMBNy5wBG7VZHAG+d5u48+ix6lpa4NDso6hQyVLC8VZv4bHEm3sFCOo8Kzgbuve5Vb2MjysZpfe25TEJOrvK3pzKr2miukudMl1bLUPJc9xG56lUuJDS87nQa7KV2sGVgBP8AD/VUv+8dlzaDcpGCj4JnfOz5mKxzEE6dU3tDwLEhjeY6qZZsPhYPmUWMnlb8I+isZ+Tr+A8V1OFVL3GJ2rATpf07/wBFznE8TafGZoGgjwWtZb6/qsFsz6WpbNC9zHN5hFZUzV9XJUVDs0shBc63a36Kvb6tMY1uM99ipo8jjfdKIhpuR81N4uA0aBVSDzW6KcN9JZiCSOabAcxda/JRaDe3NXBpAGm3I80SK6SyZY9RqVXFqDbQhWPc5oDhtzFtlXlDnF8Z1HLqrENlMhGYZevJZLW7Fx2Gg6LHAu/NoDfkFddziQ1py9bKCNIMs9znH4R1UjGZTmLg0cr81bHTZI7yuA52/qk8BxBeSGDbumFkQiiAuSRp0Te4AtEQsTuean4gLPDY0NG1lQwFswu0lwQeCyq0ZrvbROA2a0A62UajY31udFFwMGQnUdVBOk4H/eucSLjRHii5ztBN91S17bv7nRBY0nzvs7oBdBo6U5bk8is93mjabgP+hWFI0RvAbsdbK2U/AeyrvAg8LS9xHmF7fMLFnaTZ7QO6yGm7DfkN1HcFCzKWPJGp1WQ/903LuqWgX2SLiH780fgiMsLhISM2xG4VjapzNQVVLoA/mVRLo7RZSgn5OmvqJ18pm2bWnI0kndbXD6ikqh4GIhzqZ7gHFp1b3GhXMSE+COyy6Nx8B6zlWlyjrXWSsj2T5TNrUxYZRVb4JqSqGR1i01IP1y6gjW6ugpMErntYG1VNIfhDZMzXdPwkgquRorcAqJqjzS0rY/DfzsXZbHtrf191pKaaRt3NeQdr35K0dkuG9OdquE+2UeDf1fDFQJHNpJWz5eV7n/bcfO3otRNTVFG/JPA6P+fY+nIpQ1ErJGlryCDoV0eDYzWyyRU1VL9pgfIA6OfzjcD1HspdlkFsuS0ulrmthwc2Zd2E3O6xXvvoNl6txXwTg0NNJUUsctPI2J0h8J9g4jsRb5WXlQADb9leq+Nq1HnzrcQiyNu5x1PTUlWHzWIuwcyd1DOY2tDQBfdK51NytyonygWZENSpxtazS2Z+5KqgaHSHl6K14Akaz8PRQCE7rPAvum+1gwctVKdoIFwqI9c1+SkaSc0PjN9OhUYDcf2Vkxs1oGgIUI/KxxCDQcQHa6WUWsL35z5RZSYM3ndqU2uL5chNh2QaMBrBYf3VjNNx7KE33QszSygy5cSSbkKRoSPIdYnMD0SjY5t3XsOgVjGtvsnYF+vIXUEEHSRxkXaXOKZkcTt5/wALOQ7lQBJLnn4gbDsiQ5IyG89zzKrpJNkjQ12Y55BzOoUKl2YNfqmWNYzQbqtziWOHLop8Et8FlNZt32v3KlLlkdnjJDhy5FDvJA0DnbdJsYNOH3IJcmkaVSHNICb+ibvEl0Og5LPwqjiq66KCQuDXusS06rosXweiwstbBEZCfxSuJP0sFlO6MHjN6Onsu+U5OGnDRfn1I19lY1sbRYRA9+q28MrDdr6ancLc4wPyWY3AaOpY2W8seYfCxwsPmCU+NH3RpPorIryf/9k=)](https://www.digitalasset.works/news/articleView.html?idxno=41973)

[디지털애셋](https://www.digitalasset.works/news/articleView.html?idxno=41973)

[

이더리움, 한달 만에 1880달러

60분 전

](https://www.digitalasset.works/news/articleView.html?idxno=41973)[뉴스 더보기](https://www.google.com/search?newwindow=1&sca_esv=53ab19e28dc03dd8&sxsrf=APpeQnuXy3hpecUaMJ0hU-Py8q7C2E24gA:1784078997762&q=%EC%9D%B4%EB%8D%94%EB%A6%AC%EC%9B%80&tbm=nws&source=univ&tbo=u&sa=X&ved=2ahUKEwistaaXxNOVAxVee_UHHeGlEkYQt8YBKAd6BAgbEAw)

## 웹 검색결과

### [이더리움 - ethereum.org의 완벽한 가이드](https://ethereum.org/ko/)

ethereum.org

https://ethereum.org ›...

ethereum.org

https://ethereum.org ›...

*이더리움은 화폐와 새로운 형태의 애플리케이션을 위한 글로벌 탈중앙화된 플랫폼* 입니다. 이더리움에서는 자신의 자산, 데이터, 신원을 직접 통제할 수 있습니다.

### [이더리움 시세 | Ethereum - 이더리움 가격 (ETH 암호화폐)](https://kr.investing.com/crypto/ethereum)

Investing.com 한국어

https://kr.investing.com › crypto › ethereum

Investing.com 한국어

https://kr.investing.com › crypto › ethereum

Ethereum - *이더리움* 은/는 디지털 암호화폐의 한 형태로, ETH 코인이라고도 합니다. 이 페이지에서는 Ethereum - *이더리움* 의 실시간 가격, 1,875.96로 마감된 종가, 암호...

### [이더리움](https://www.upbit.com/exchange/CRIX.UPBIT.KRW-ETH)

업비트

https://www.upbit.com › CRIX.UPBIT.KRW-ETH

업비트

https://www.upbit.com › CRIX.UPBIT.KRW-ETH

*이더리움 시세, 이더리움 가격, 이더리움 거래, 이더리움 정보* 등 이더리움의 모든 것, 가장 신뢰받는 디지털 자산 거래소 업비트에서 확인해보세요.

### [이더리움-ETH/ETH/KRW | 시세 확인 및 거래 | 거래소](https://www.bithumb.com/react/trade/order/ETH-KRW)

빗썸

https://www.bithumb.com › react › trade › order › ETH...

빗썸

https://www.bithumb.com › react › trade › order › ETH...

*이더리움(Ethereum*)은 분산 응용 애플리케이션 플랫폼으로서, 가상자산을 통한 분산형 스마트 계약의 실행뿐만 아니라 신규 가상자산을 개발할 수 있는 환경을 제공합니다.

### [가상화폐 비트코인과 이더리움](https://www.etri.re.kr/webzine/20170811/sub04.html)

한국전자통신연구원

https://www.etri.re.kr › webzine › sub04

한국전자통신연구원

https://www.etri.re.kr › webzine › sub04

*비트코인 이후 많은 블록체인 기반의 전자화폐가 생겨났으며 대표적으로 이더리움이 있다*. 이더리움은 비트코인의 단점들을 보완하고 튜링 완전한 컴퓨팅 기능을 넣음...

### [이더리움 초보자 가이드](https://www.ledger.com/ko/academy/%EC%9D%B4%EB%8D%94%EB%A6%AC%EC%9B%80-%EC%B4%88%EB%B3%B4%EC%9E%90-%EA%B0%80%EC%9D%B4%EB%93%9C)

Ledger

https://www.ledger.com ›... › 암호화폐

Ledger

https://www.ledger.com ›... › 암호화폐

이더리움에 대해 배우고 싶지만 어디서부터 시작해야 할지 막막한가요? Ledger에서 여러분의 여정을 돕고자 *이더리움 초보자 가이드* 를 준비했습니다!

### [이더리움이란? - 뜻 & 정의 | KB의 생각](https://kbthink.com/dictionary/view.html?dictId=KED-00013440)

KB Think

https://kbthink.com › 경제·금융 용어사전

KB Think

https://kbthink.com › 경제·금융 용어사전

이더리움. Ethereum. *2014년 캐나다인 비탈리크 부테린이 개발한 가상화폐*. 단위로 이더(ETH)을 쓴다. 계약서, 전자투표, e-mail 등 다양한 프로그램에 적용할 수 있는...

### [이더리움: 종합 학습 가이드](https://ethereum.org/ko/learn/)

ethereum.org

https://ethereum.org › learn

ethereum.org

https://ethereum.org › learn

*이더리움* 은 우리 삶의 다양한 영역을 개선할 수 있는 새로운 제품과 서비스의 탄생을 이끌었습니다. 금융 도구와 디지털 소유권부터 거버넌스와 과학에 이르기까지 사용...

### [톰 리 "이더리움, 화폐 역할 본격화"…로빈후드 체인 효과에...](https://www.news1.kr/finance/blockchain-fintech/6226604)

뉴스1

https://www.news1.kr › finance › blockchain-fintech

뉴스1

https://www.news1.kr › finance › blockchain-fintech

2일 전 — (서울=뉴스1) 황지현 기자 = 로빈후드의 레이어2(L2) 블록체인 '로빈후드 체인' 출범을 계기로 *이더리움(ETH)이 실사용 가치가 다시 주목받고 있다*.$seed_af01352e701b$,
        'markdown',
        'af01352e701b194737feb745f3ba5da38fb94d2af1a820d703bea0ed0e97be62',
        NULL,
        $seed_dc30162c101d${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/검색결과 1.md"}$seed_dc30162c101d$::jsonb
    ),
    (
        'b81b1a08-b452-5d0f-802a-f3e057b0fd10',
        '5d34c777-ca37-5f5e-a864-1b291a570190',
        'user/mock-clipping-user',
        '6569ed28-6823-57c5-b6ca-4f9639853376',
        1,
        $seed_7cfea5451a7c$검색결과$seed_7cfea5451a7c$,
        NULL,
        NULL,
        '2026-07-15'::date,
        NULL,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_6e45ac5e83a3$## 웹 검색결과

### [돈쭐 내주자 응원 쏟아지더니…주가 폭등 상한가 터졌다](https://www.hankyung.com/article/2026071447646)

한국경제

https://www.hankyung.com › article

한국경제

https://www.hankyung.com › article

12시간 전 — 7월부터 *주가* 1000원 미만 동전주 상장폐지 제도가 강화된 가운데 일부 저가주가 불기둥을 세웠다. 액면병합과 자사주 매입 등 상장 유지를 위한 자구책을...

주요 뉴스

[![](data:image/jpeg;base64,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)](https://www.yna.co.kr/view/AKR20260715007900072)

[연합뉴스](https://www.yna.co.kr/view/AKR20260715007900072)

[

바클레이스 "SK하이닉스 ADR 2배로 상승 여력"…주가 20%대 급등

5시간 전

](https://www.yna.co.kr/view/AKR20260715007900072)

[![](data:image/jpeg;base64,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)](https://www.mt.co.kr/world/2026/07/15/2026071509164834435)

[머니투데이](https://www.mt.co.kr/world/2026/07/15/2026071509164834435)

[

"美 SK하닉 목표주가 330달러…2028년까지도 공급부족" - 머니투데이

49분 전

](https://www.mt.co.kr/world/2026/07/15/2026071509164834435)

[![](data:image/jpeg;base64,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)](https://www.2news.co.kr/news/articleView.html?idxno=15928)

[https://www.2news.co.kr/](https://www.2news.co.kr/news/articleView.html?idxno=15928)

[

SK하이닉스 주가 급등에 SK그룹주 동반 상승

24분 전

](https://www.2news.co.kr/news/articleView.html?idxno=15928)[IBM 뉴스](https://www.google.com/search?q=%EC%A3%BC%EA%B0%80&newwindow=1&sca_esv=53ab19e28dc03dd8&tbm=nws&sxsrf=APpeQnuxu5AGPIgWEIA5x26i0ABSbrt8Hw:1784078312071&story=Gh8IjAEaGgoTc3RvcnlfbGFiZWxfcGFydGlhbBIDSUJNMjEKJ6Py2fXlyqS65QGm4ay56uyR1roBwfSj_-Ws5M8U1MC3iJyX9vi0ARCf-IPEERgFcgIQAQ&fcs=AF4cvB6_IDzx5LwyYQ9xmjjE1q1KGtLy3w&sa=X&ved=2ahUKEwjLkavQwdOVAxXohVYBHdNkL4UQjcEJegQIKhAD)[뉴스 더보기](https://www.google.com/search?newwindow=1&sca_esv=53ab19e28dc03dd8&sxsrf=APpeQnuxu5AGPIgWEIA5x26i0ABSbrt8Hw:1784078312071&q=%EC%A3%BC%EA%B0%80&tbm=nws&source=univ&tbo=u&sa=X&ved=2ahUKEwjLkavQwdOVAxXohVYBHdNkL4UQt8YBKAd6BAggEAw)

## Web results

### [국내증시 - 네이버 금융 - NAVER](https://finance.naver.com/sise/)

네이버 증권

https://finance.naver.com › sise

네이버 증권

https://finance.naver.com › sise

이 페이지에 관한 정보가 없습니다.

[이유 알아보기](https://support.google.com/webmasters/answer/7489871?hl=ko)

### [KRX Data Marketplace - 한국거래소](https://data.krx.co.kr/)

KRX Data Marketplace

https://data.krx.co.kr

KRX Data Marketplace

https://data.krx.co.kr

1콘텐트리중앙, 1,976, 456, +30.00%, 38. 2STX그린로지스, 2,540, 586, +29.99%, 18. 3기가레인, 7,760, 1,790, +29.98%, 66. 4위닉스, 4,445, 1,025, +29.97%, 79.

### [주가는 어떻게 결정되는가? | click 경제교육](https://eiec.kdi.re.kr/material/clickView.do?click_yymm=201201&cidx=1652)

KDI 경제교육

https://eiec.kdi.re.kr › material › clickView

KDI 경제교육

https://eiec.kdi.re.kr › material › clickView

위와 같은 사전적 정의를 인용하면 주가란 *주식시장에서 형성되는 시세에 따라 결정되는 주식의 가격* 이라고 할 수 있다. 가격은 상품의 교환가치를 나타내어 매수자와...

### [e-나라지표 — 주가지수(코스닥 종합지수)](https://www.index.go.kr/unity/potal/main/EachDtlPageDetail.do?idx_cd=1080)

지표누리

https://www.index.go.kr › main › EachDtlPageDetail

지표누리

https://www.index.go.kr › main › EachDtlPageDetail

지표설명. □ *주가* 지수 및 코스닥종합지수 개념 및 의의 ㅇ *주가* 지수 및 코스닥 종합지수란 한국거래소에 상장 및 등록되어 있는 주식의 시장가격을 토대로 작성되며,...

### [주가정보 | 롯데그룹 IR정보](https://lotte.co.kr/ir/inc.do?tab=table_0)

Lotte Group

https://lotte.co.kr › inc

Lotte Group

https://lotte.co.kr › inc

주식정보 - 현재가, 전일대비, 등락률, 거래량 등 주식정보를 제공합니다. 현재가, 24,050. 전일대비, + 1,100. 등락률, +4.79%. 시가, 23,000. 고가, 24,150.

동영상[\[속보\] 반도체 급락하는데 애플 주가는 '사상 최고'…시총 두달새...](https://www.youtube.com/watch?v=7LQ8aSxClZo)

[YouTube 연합뉴스TV

19시간 전

](https://www.youtube.com/watch?v=7LQ8aSxClZo)[SK하이닉스, ADR과 반대로 급락…코스피 '여기까지' 떨어진다...](https://www.youtube.com/watch?v=OVAJjKZMGEc)

[YouTube 한국경제TV

1일 전

](https://www.youtube.com/watch?v=OVAJjKZMGEc)["주가 재평가 시작된다" 앞으로 1달 뒤 역대급 기회 시작된다...](https://www.youtube.com/watch?v=rbAvOn0SJcA)

[YouTube 머니인사이드

6일 전

](https://www.youtube.com/watch?v=rbAvOn0SJcA)[모두 보기](https://www.google.com/search?newwindow=1&sca_esv=53ab19e28dc03dd8&udm=7&sxsrf=APpeQnuxu5AGPIgWEIA5x26i0ABSbrt8Hw:1784078312071&q=%EC%A3%BC%EA%B0%80&sa=X&ved=2ahUKEwjLkavQwdOVAxXohVYBHdNkL4UQ8ccDKAJ6BAhXEAQ)

## 웹 검색결과

### [다음 금융](https://finance.daum.net/)

다음 금융

https://finance.daum.net

다음 금융

https://finance.daum.net

랭킹 · 한탑. +29.98% · 엑사이엔씨. +29.94% · 캠시스. +29.93% · 엔피. +29.90% · 미래생명자원. +29.84%.

### [실시간 주가 지수 정보](https://alphasquare.co.kr/home/market-indicator?factor=index)

알파스퀘어

https://alphasquare.co.kr › 홈 › 시장지표

알파스퀘어

https://alphasquare.co.kr › 홈 › 시장지표

*실시간 주가 지수 정보*; 코스닥 로고 코스닥, 783.98, ▽ 15.38; 상해 로고 상해, 3,949.71, △ 35.92; 나스닥 로고 나스닥, 25,873.18, ▽ 408.43; S&P500 로고 S&P500...

관련 질문$seed_6e45ac5e83a3$,
        'markdown',
        '6e45ac5e83a3e3f2336317b13db330cceda2cbfb6f618f859f7a8dae39b2d0cc',
        NULL,
        $seed_a969e237fc41${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/검색결과.md"}$seed_a969e237fc41$::jsonb
    ),
    (
        '5839f933-0f1e-5725-b1ee-4b8b6bc9daf1',
        '656b3542-e4b4-561f-bb56-4ade092f4424',
        'user/mock-clipping-user',
        'd52848b0-00d8-537c-8374-2eff4387e010',
        1,
        $seed_45e19dac3b97$리센느 역주행…중소 아이돌 생존경쟁$seed_45e19dac3b97$,
        $seed_2d8b2a6c808a$[[이승종]]$seed_2d8b2a6c808a$,
        '2026-07-13T00:00:00Z'::timestamptz,
        '2026-07-15'::date,
        $seed_55c15f5ee00e$[앵커] 요즘 케이팝 시장에서 중소 기획사 그룹인 '리센느'가 역주행 신화를 쓰며 연일 화젭니다. 대형 기...$seed_55c15f5ee00e$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_d3d43356ddc9$## 기사 본문 영역

[뉴스 9](https://news.kbs.co.kr/news/pc/program/program.do?bcd=0001)

#### 리센느 역주행…중소 아이돌 생존경쟁

*입력 2026.07.13 (22:16)* *수정 2026.07.14 (08:03)*

앵커

요즘 케이팝 시장에서 중소 기획사 그룹인 '리센느'가 역주행 신화를 쓰며 연일 화젭니다.  
  
대형 기획사의 자본력 없이 이끌어낸 값진 성공인데, 이런 사례가 갈수록 더 드문 일이 되고 있다고 합니다.  
  
이승종 기자가 취재했습니다.  

리포트

중소 아이돌 그룹의 기적으로 불리는 '리센느'.  
  
2년 전 발매한 '러브 어택'이 최근 국내 대표 음원 사이트인 멜론 차트에서 1위를 차지했습니다.  
  
발매 당시 9백위권이었던 노래가 2년 만에 역주행 신화를 쓴 겁니다.  
  
\[리센느: "너무 갑자기 됐잖아요 1위가. 우리 예상도 못하고 그런 시간에."\]  
  
자본이 부족한 리센느가 홍보를 위해 선택한 건 돈이 들지 않는 라이브 방송.  
  
2백 회 가량의 자체 라이브를 진행했고, 이른바 '거제 야호' 영상이 큰 인기를 끌며 단숨에 대세 아이돌로 떠올랐습니다.  
  
\[리센느: "거제 야호. (거제 야호?)"\]  
  
\[거제시: "거제 야호."\]  
  
하지만, 대형 기획사의 자본력이 성공의 척도가 된 요즘, 리센느의 성공은 이례적으로 꼽힙니다.  
  
중소 기획사의 평균 제작비는 대형 기획사의 29분의 1 수준으로 올해 상반기 발매 첫 1주일 동안 백만 장 이상 판매고를 거둔 14개 팀 가운데, 중소 기획사는 2곳뿐이었습니다.  
  
\[김진우/'RBW' 대표: "대기업들은 앨범 한 장에 백억도 써요 지금, 한 장에. 그러면 전부 이 대기업에서 나오는 아티스트들만 살아남을 확률이 높아지는 거예요."\]  
  
리센느는 정치권까지 가세한 일베 억측으로 한때 큰 위기를 맞는 등 중소아이돌은 악성 루머에도 노출돼 있습니다.  
  
케이팝 시장의 양극화 목소리가 나오는 가운데, 정부는 지속가능한 K팝의 성장을 위해 음악 제작비에 대한 세액공제 제도 도입 등을 검토하고 있습니다.  
  
KBS 뉴스 이승종입니다.  
  
촬영기자:심규일/영상편집:양다운/그래픽:김성일 최창준/화면제공:더뮤즈엔터테인먼트, 거제시, 유튜브 '리센느'

■ 제보하기  
▷ 카카오톡: 'KBS제보' 검색, 채널 추가  
▷ 전화: 02-781-1234, 4444  
▷ 이메일: kbs1234@kbs.co.kr  
▷ 유튜브, 네이버, 다음에서도 KBS뉴스를 구독해주세요!

![이승종](https://news.kbs.co.kr/images/news/reporter/e088ce1b8d5b9bcf57916a733e5ff5e3.jpg) [이승종 기자](https://news.kbs.co.kr/news/pc/reporter/reporter.do?rcd=31373)

#### 이 기사가 좋으셨다면

#### 오늘의 핫 클릭

실시간 뜨거운 관심을 받고 있는 뉴스

[![[단독] 부산경찰청 간부급 경찰관 ‘미성년 성범죄’ 입건…직위해제](https://news.kbs.co.kr/data/fckeditor/new/image/2026/07/15/323351784073808391.jpg)](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611138)

[\[단독\] 부산경찰청 간부급 경찰관 ‘미성년 성범죄’ 입건…직위해제](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611138)[![최고 빅매치 승자는 스페인, 16년만 우승 도전](https://news.kbs.co.kr/data/news/2026/07/15/20260715_uLQAPM.jpg)

최고 빅매치 승자는 스페인, 16년만 우승 도전

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8610991)[![내년도 최저임금 1만700원…올해보다 3.7% 올라](https://news.kbs.co.kr/data/news/title_image/newsmp4/newsplaza_p1/2026/07/15/70_8610980.jpg)

내년도 최저임금 1만700원…올해보다 3.7% 올라

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8610980)[![영끌·빚투족 ‘이자 폭탄’ 터지나…내일 금리 인상 유력](https://news.kbs.co.kr/data/news/2026/07/15/20260715_OJs05V.jpg)

영끌·빚투족 ‘이자 폭탄’ 터지나…내일 금리 인상 유력

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611001)[![서대문 아파트 뒷산서 바위 떨어져…차량 2대 파손](https://news.kbs.co.kr/data/fckeditor/vod/2026/07/15/174091784077703302.png)

서대문 아파트 뒷산서 바위 떨어져…차량 2대 파손

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611218)[![“집은 있는데 현금이 없다?”…고령층 돈 가뭄 해법은?](https://news.kbs.co.kr/data/news/2026/07/15/20260715_PDjyXy.jpg)

“집은 있는데 현금이 없다?”…고령층 돈 가뭄 해법은?

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611002)[![왜 서울의 집은 늘 부족할까? - 공급 딜레마①](https://news.kbs.co.kr/data/fckeditor/new/image/2026/07/14/306621783993431796.png)

왜 서울의 집은 늘 부족할까? - 공급 딜레마①

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611004)[![기네스 기록 도전?…6살 손녀 운전시킨 인도 경찰, 정직 처분 ](https://news.kbs.co.kr/data/news/title_image/newsmp4/newsplaza/2026/07/15/180_8611046.jpg)

기네스 기록 도전?…6살 손녀 운전시킨 인도 경찰, 정직 처분

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611046)

#### 이 기사에 대한 의견을 남겨주세요.

#### 헤드라인

[![코스피 급등에 매수 사이드카 발동…‘7천피’ 회복하며 상승세](https://news.kbs.co.kr/data/layer/904/2026/07/20260715_aiJf0E.jpg)](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611137)

[코스피 급등에 매수 사이드카 발동…‘7천피’ 회복하며 상승세](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611137)[![[단독] 부산경찰청 간부급 경찰관 ‘미성년 성범죄’ 입건…직위해제](https://news.kbs.co.kr/data/fckeditor/new/image/2026/07/15/323351784073808391.jpg)

\[단독\] 부산경찰청 간부급 경찰관 ‘미성년 성범죄’ 입건…직위해제

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611138)[![6월 취업자 수 증가세 전환…<br>청년 고용률 26개월 연속 감소](https://news.kbs.co.kr/data/layer/904/2026/07/20260715_NykrhF.jpg)

6월 취업자 수 증가세 전환…청년 고용률 26개월 연속 감소

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8611089)[![최고 빅매치 승자는 스페인…<br>16년만 우승 도전](https://news.kbs.co.kr/data/layer/904/2026/07/20260715_4Zw4ee.jpg)

최고 빅매치 승자는 스페인…16년만 우승 도전

](https://news.kbs.co.kr/news/pc/view/view.do?ncd=8610991)

<iframe frameborder="0" src="https://7ba407248b6c0702b4e5a046bec56878.safeframe.googlesyndication.com/safeframe/1-0-45/html/container.html" title="서드 파티 광고 콘텐츠" width="250" height="250" allow="private-state-token-redemption;attribution-reporting" aria-label="광고"></iframe>

#### 많이 본 뉴스

각 플랫폼에서 최근 1시간 동안 많이 본  
KBS 기사를 제공합니다.

- - [1
		“어항에 갇힌 것 같아요”…장마철 필수 가전 제습기, 효율 높이는 사용법은?
		](https://news.kbs.co.kr/news/view.do?ncd=8610470)
		- [2
		뒤에서 ‘퍽’ 치고, 온도는 40도?…서울 지하철 부럽다는 외국인들 보니
		](https://news.kbs.co.kr/news/view.do?ncd=8609816)
		- [3
		\[단독\] 개표소 ‘무단침입’ 당시 정문 CCTV 공개…전날에도 3명 ‘무단 침입’
		](https://news.kbs.co.kr/news/view.do?ncd=8610722)
		- [4
		\[단독\] ‘1,500원 특수절도’ 송치한 경찰…“둘이 함께 먹어 합동 절취”
		](https://news.kbs.co.kr/news/view.do?ncd=8610718)
		- [5
		내년도 최저임금 시간당 1만 700원…올해보다 3.7% 인상
		](https://news.kbs.co.kr/news/view.do?ncd=8610889)
		- [6
		\[크랩\] “독도는 명확한 한국 영토”…미 기밀문서 직접 찾아낸 교수님 직접 만나봄
		](https://news.kbs.co.kr/news/view.do?ncd=8609546)
- - [1
		“집은 있는데 현금이 없다?”…고령층 돈 가뭄 해법은? \[잇슈 머니\]
		](https://news.kbs.co.kr/news/view.do?ncd=8611002)
		- [2
		최고 빅매치 승자는 스페인, 16년만 우승 도전
		](https://news.kbs.co.kr/news/view.do?ncd=8610991)
		- [3
		영끌·빚투족 ‘이자 폭탄’ 터지나…내일 금리 인상 유력 \[잇슈 머니\]
		](https://news.kbs.co.kr/news/view.do?ncd=8611001)
		- [4
		왜 서울의 집은 늘 부족할까? - 공급 딜레마①
		](https://news.kbs.co.kr/news/view.do?ncd=8611004)
		- [5
		강한 비바람에 수도권 곳곳 정전…서울 하천 출입 순차적 재개
		](https://news.kbs.co.kr/news/view.do?ncd=8611009)
		- [6
		기네스 기록 도전?…6살 손녀 운전시킨 인도 경찰, 정직 처분 \[잇슈 SNS\]
		](https://news.kbs.co.kr/news/view.do?ncd=8611046)
- - [1
		4강 토너먼트프랑스 vs 스페인 / KBS 2026 북중미 월드컵 2026.07.15.
		](https://www.youtube.com/watch?v=JfDGfdjB7dQ)
		- [2
		\[이슈\] 오늘도 중국산 에어컨 끄고 출근하다가 "아! 한국"..."살아남거나 40℃ 견디거나" 미국·유럽의 생존 고투/2026년 7월 14일(화)/KBS
		](https://www.youtube.com/watch?v=nUrh8wRHypA)
		- [3
		태풍 '바비'로 중국 동북부 폭우…남부는 40도 폭염 #shorts / KBS
		](https://www.youtube.com/watch?v=v49ihy2euzA)
		- [4
		\[단독\] ‘1,500원 특수절도’ 송치한 경찰…“둘이 함께 먹어 합동 절취” \[9시 뉴스\] / KBS 2026.07.14.
		](https://www.youtube.com/watch?v=yXHlF9WHOyw)
		- [5
		월드컵 최고 '빅매치' 스페인 '완벽한 조직력' #shorts / KBS
		](https://www.youtube.com/watch?v=QwmoFV4tZIg)
		- [6
		1,500원 아이스크림 나눠 먹은 장애인들, '특수절도' 송치 #shorts / KBS
		](https://www.youtube.com/watch?v=oC1ox1WjqYM)$seed_d3d43356ddc9$,
        'markdown',
        'd3d43356ddc92758840d65208fc0b1c45ae953d420f9a02cd6ad6c4c9aa6e003',
        NULL,
        $seed_f79db4504399${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/리센느 역주행…중소 아이돌 생존경쟁.md"}$seed_f79db4504399$::jsonb
    ),
    (
        'f41a0e0f-b365-50be-9e45-8bbf719b01b4',
        '5c696747-a0ed-508b-af47-e87924d92bbc',
        'user/mock-clipping-user',
        'bcb9e0e9-5929-558d-ac50-31db821c2cc0',
        1,
        $seed_868183981b40$무료 PostgreSQL 툴 추천$seed_868183981b40$,
        NULL,
        NULL,
        '2026-07-15'::date,
        $seed_49c1efa73282$ChatGPT conversation with 6 messages$seed_49c1efa73282$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_c1eaceb47543$PostgreSQL 위주라면 무료에서는 사실 **DBeaver Community** 가 거의 표준입니다. DataGrip에서 넘어오는 사람들도 가장 많이 선택합니다. [^1]

추천 순위는 다음과 같습니다.

### 1\. DBeaver Community ⭐⭐⭐⭐⭐ (가장 추천)

- 무료 + 오픈소스
- Windows / macOS / Linux 지원
- PostgreSQL뿐 아니라 MySQL, MariaDB, MSSQL, SQLite 등 대부분 지원
- SQL 자동완성
- ERD
- 데이터 편집
- Export/Import
- SSH Tunnel 지원

**장점**

- DataGrip와 가장 비슷한 느낌
- 기능이 매우 많음
- 회사에서도 많이 사용

**단점**

- Java 기반이라 조금 무거움

---

### 2\. Beekeeper Studio ⭐⭐⭐⭐☆

- 무료 버전 존재
- UI가 매우 깔끔
- PostgreSQL 개발하기 편함
- 빠름

**장점**

- DataGrip보다 가벼움
- UI가 현대적

**단점**

- 무료 버전은 일부 고급 기능 제한

[^2]

---

### 3\. DbGate ⭐⭐⭐⭐☆

- 완전 무료
- 오픈소스
- PostgreSQL 포함 다양한 DB 지원

**장점**

- 웹버전도 있음
- 가볍고 빠름

**단점**

- DataGrip만큼 세련되진 않음

[^3]

---

### 4\. pgAdmin 4 ⭐⭐⭐☆☆

PostgreSQL 공식 GUI입니다.

**장점**

- PostgreSQL 기능 지원이 가장 완전
- 무료

**단점**

- UI가 오래된 느낌
- 느리다는 평가가 많음

[^4]

---

### 5\. VS Code + PostgreSQL Extension ⭐⭐⭐⭐☆

이미 VS Code를 많이 사용한다면 의외로 만족도가 높습니다.

- SQL 작성
- 테이블 조회
- 결과 확인
- Git과 함께 작업하기 편함

---

## 만약 코딩이 목적이라면

너처럼 **NestJS + PostgreSQL + Git** 위주로 개발한다면 개인적으로는

> **DBeaver Community > Beekeeper Studio > VS Code Extension**

순으로 추천합니다.

특히 DBeaver는 SQL 자동완성, 스키마 탐색, ERD, 데이터 수정까지 DataGrip에서 자주 쓰는 기능을 대부분 무료로 제공합니다. [^1]

### DataGrip와 비교하면

| 기능 | DataGrip | DBeaver Community |
| --- | --- | --- |
| SQL 자동완성 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐☆ |
| ERD | ✅ | ✅ |
| 데이터 편집 | ✅ | ✅ |
| PostgreSQL | ✅ | ✅ |
| Git 연동 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 가격 | 유료 | 무료 |

내 추천은 **DBeaver Community** 입니다. DataGrip에 가장 가까운 사용 경험을 무료로 제공하고, PostgreSQL 개발 환경에서도 가장 무난한 선택입니다.

---

datagrip은 무료인가?

---

예전에는 **아니었습니다.** DataGrip은 30일 체험판 이후 유료 구독이 필요했고 Community Edition도 없었습니다.

하지만 **2025년부터 정책이 변경** 되어 현재는 다음과 같습니다.

- ✅ **비상업적(Non-commercial) 용도는 무료**
	- 개인 공부
		- 취미 프로젝트
		- 자기계발
		- 상업적 이익이 없는 오픈소스 기여
		- 콘텐츠 제작 등
- ❌ **상업적 용도는 유료**
	- 회사 업무
		- 프리랜서 유료 프로젝트
		- 수익을 창출하는 개발 업무 [^5]

즉, 너처럼:

- 개인 PostgreSQL 공부
- 개인 프로젝트
- GitHub에 공개하는 오픈소스 개발

이라면 **무료 라이선스로 사용할 수 있습니다.** [^5]

반면, 회사에서 업무용으로 PostgreSQL을 관리하거나 상업 프로젝트를 개발한다면 유료 라이선스가 필요합니다. [^5]

개인적으로는 **DataGrip을 무료로 사용할 수 있는 조건이라면 DBeaver보다 DataGrip을 추천** 합니다. SQL 자동완성, 리팩터링, 탐색 기능이 더 뛰어나고 PostgreSQL 개발 경험도 매우 좋습니다.

---

라이센스 없어도 무료임?

---

네. 다만 **"라이선스가 전혀 없어도"** 는 아니고, **무료 라이선스를 활성화해야 합니다.**

현재 DataGrip은 다음과 같습니다.

- ✅ 비상업적 사용이라면 **무료**
- ✅ JetBrains 계정만 있으면 활성화 가능
- ✅ 별도의 결제는 필요 없음
- ❌ 그냥 설치만 하고 계속 사용하는 것은 불가능

처음 설치하면:

1. 30일 체험판이 시작되거나
2. **Non-commercial use(비상업적 사용)** 를 선택하여 무료 라이선스를 활성화합니다. [^6]

무료 라이선스는:

- JetBrains 계정 로그인 필요
- 1년 단위로 발급되며 조건을 충족하면 자동 갱신
- 기능은 유료 버전과 동일합니다. [^6]

즉, **제품 키를 구매할 필요는 없지만, 무료 라이선스 등록은 해야 합니다.** 그냥 아무 인증 없이 영구적으로 사용하는 방식은 아닙니다. [^6]

[^1]: [alternativeto.net](https://alternativeto.net/software/datagrip/?license=free&utm_source=chatgpt.com)

[^2]: [wiki.postgresql.org](https://wiki.postgresql.org/wiki/PostgreSQL_Clients?utm_source=chatgpt.com)

[^3]: [dbgate.io](https://www.dbgate.io/alternatives/datagrip/?utm_source=chatgpt.com)

[^4]: [queryplane.com](https://queryplane.com/blog/best-pgadmin-alternatives/?utm_source=chatgpt.com)

[^5]: [jetbrains.com](https://www.jetbrains.com/datagrip/buy/?utm_source=chatgpt.com)

[^6]: [jetbrains.com](https://www.jetbrains.com/help/datagrip/register.html?utm_source=chatgpt.com)$seed_c1eaceb47543$,
        'markdown',
        'c1eaceb47543d0d1aa815c15481e4a217a0831ca6973fd661186633ac672e625',
        NULL,
        $seed_e2bd8985bd48${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/무료 PostgreSQL 툴 추천.md"}$seed_e2bd8985bd48$::jsonb
    ),
    (
        '67cd85c7-a26e-5a47-bc1c-721dc4e797e1',
        '3789bb84-6808-500e-9119-71ea492f8b47',
        'user/mock-clipping-user',
        '9be68322-fd31-5461-b646-1080d3a1cb5d',
        1,
        $seed_7a0a8a899ae6$선분으로 정다각형 찾기$seed_7a0a8a899ae6$,
        NULL,
        NULL,
        '2026-07-15'::date,
        $seed_6bba8a7708b3$Claude conversation with 4 messages$seed_6bba8a7708b3$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_91869d10a9b2$**You**

꼭지점에서 특정 규칙으로 이어진 선분 속에서 모든 정다각형을 발견할 수 있는데 이게 어떻게 가능한지 증명해봐.

---

**Claude**

좋은 질문이에요. 먼저 "특정 규칙"을 정확히 정식화할게요. 이건 보통 **별 그리기 규칙** 이라 부르는 것입니다:

> 원 위에 $n$ 개의 점을 같은 간격으로 놓고(정 $n$ 각형의 꼭짓점), 한 점에서 출발해 **매번 정확히 $k$ 칸씩 건너뛰며** 선분으로 잇는다.

이 단순한 규칙 하나에서 모든 정다각형(그리고 정별다각형)이 나오고, **그 외의 도형은 절대 나오지 않는다** 는 것이 증명할 명제입니다.

### 정리

$n \ge 3$ , $1 \le k \le n-1$ 에 대해 $d = \gcd(n,k)$ , $m = n/d$ , $k^{'} = k / d$ 라 하자. 그러면:

1. 경로는 정확히 $m$ 번의 점프 후 처음으로 닫힌다.
2. 경로가 지나는 점들은 같은 원에 내접하는 **정 $m$ 각형의 꼭짓점 전체** 와 일치한다.
3. 그려진 도형은 정다각형이다 — $k' \equiv \pm 1 \pmod m$ 이면 볼록 정 $m$ 각형, 아니면 정별다각형 $\{m/k'\}$ .
4. 역으로 임의의 정 $m$ 각형과 임의의 별다각형 $\{m/k'\}$ 는 적절한 $n, k$ 로 얻어진다.

### 증명

**설정.** 평면을 복소평면과 동일시하고 꼭짓점을 $V_t = \omega^t$ ($\omega = e^{2\pi i/n}$ )로 둡니다. $V_0 = 1$ 에서 출발하면 $j$ 번째 방문점은 $P_j = \omega^{jk}$ 입니다.

**1단계 — 닫히는 시점은 gcd가 결정한다.** 경로가 출발점으로 돌아오는 조건은 $P_j = P_0$ , 즉 $n \mid jk$ 입니다. $n = dm$ , $k = d k^{'}$ 로 쓰면 $\gcd(m, k') = 1$ 이고,

$$
n \mid jk \iff dm \mid jdk' \iff m \mid jk' \iff m \mid j
$$

마지막 동치는 $\gcd(m,k')=1$ 이라서 성립합니다(유클리드 보조정리). 따라서 최초 닫힘은 정확히 $j = m$ 일 때이고, 경로는 $m$ 개의 선분으로 이루어진 닫힌 다각형입니다.

**2단계 — 방문 집합은 정 $m$ 각형의 꼭짓점이다.** 방문한 꼭짓점 번호의 집합은 $\mathbb{Z}_n$ 에서 $k$ 가 생성하는 부분군 $\langle k \rangle = \{jk \bmod n\}$ 입니다. 여기서 핵심은 **베주 항등식**: 어떤 정수 $a, b$ 에 대해 $d = an + bk$ 이므로 $d \equiv bk \pmod n$ , 즉 $d \in \langle k \rangle$ . 역으로 $d \mid k$ 이므로 $\langle k \rangle \subseteq \langle d \rangle$ . 따라서

$$
\langle k \rangle = \langle d \rangle = \{0,\ d,\ 2d,\ \dots,\ (m-1)d\}
$$

이 번호들에 대응하는 점은 $\omega^{jd} = e^{2\pi i \cdot jd/n} = e^{2\pi i j/m}$ — 정확히 $m$ 차 단위근 전체, 즉 정 $m$ 각형의 꼭짓점입니다. (출발점을 $V_1, V_2, \dots$ 로 바꾸면 같은 정 $m$ 각형의 회전 복사본이 나오고, 전체 그림은 $d$ 개의 복사본으로 분해됩니다 — 잉여류가 $d$ 개이기 때문이죠.)

**3단계 — 왜 "정(正)"다각형인가: 회전 대칭.** $\zeta = e^{2\pi i/m}$ 로 두면 $P_j = \zeta^{jk'}$ 입니다. 원점 중심 각 $2\pi k'/m$ 회전 $R(z) = \zeta^{k'}z$ 를 생각하면

$$
R(P_j) = P_{j+1}
$$

즉 회전 $R$ 하나가 모든 꼭짓점을 다음 꼭짓점으로, 모든 변 $[P_j, P_{j+1}]$ 을 다음 변 $[P_{j+1}, P_{j+2}]$ 로 보냅니다. $R$ 은 등거리변환이므로 **모든 변의 길이가 같고** (등변), 각 꼭짓점에서 두 변이 이루는 각도 배치도 $R$ 에 의해 다음 꼭짓점으로 그대로 옮겨지므로 **모든 내각이 같습니다** (등각). 등변 + 등각이 정다각형의 정의입니다. $k^{'} = 1$ 또는 $m-1$ 이면 이웃끼리 잇는 볼록 정 $m$ 각형, $2 \le k' \le m-2$ 이면 자기교차하는 정별다각형 $\{m/k'\}$ (역시 등변·등각이며 대칭군은 동일하게 정이면체군 $D_m$ )입니다.

**4단계 — 완전성과 배타성.** 임의의 $m \ge 3$ 에 대해 $n = m$ , $k = 1$ 이면 곧바로 볼록 정 $m$ 각형입니다. 더 흥미롭게는, $m \mid n$ 인 아무 $n$ 에서 $k = n/m$ 을 잡으면 $d = n/m$ 이 되어 정 $m$ 각형이 회전된 $d$ 개의 복사본으로 등장합니다 — 즉 **정 $n$ 각형의 대각선 그물 안에는 $n$ 의 모든 약수 $m \ge 3$ 에 대한 정 $m$ 각형이 전부 숨어 있습니다.** 별다각형 $\{m/k'\}$ 는 $n = m$ , $k = k^{'}$ 로 얻습니다. 그리고 1~3단계에 의해 이 규칙으로는 정다각형/정별다각형 이외의 것은 절대 나오지 않으므로, 이 구성이 만드는 도형의 집합은 정다각형 전체 집합과 **정확히 일치** 합니다. $\blacksquare$

### 본질: 왜 이 규칙이어야 하는가

"매번 $k$ 칸"이라는 규칙은 곧 **고정된 회전 하나를 반복 적용하는 것** 입니다. 그런데 정다각형의 정의적 특징이 바로 "유한 순환 회전군의 한 궤도(orbit)"라는 것이므로, 이 구성은 정다각형을 낳을 수밖에 없고 정다각형만 낳습니다. 경계 사례가 이를 더 선명하게 보여줍니다: 회전각 $\theta$ 가 $2\pi$ 의 **무리수배** 이면 궤도는 영원히 닫히지 않고 원 위에 조밀하게 퍼집니다(크로네커–바일). 즉,

$$
\text{닫힘} \iff \theta/2\pi \in \mathbb{Q} \iff \text{정다각형}
$$

구체 예로 $n = 12$ 를 보면: $k=1$ 은 정12각형, $k=2$ 는 정육각형 2개, $k=3$ 은 정사각형 3개, $k=4$ 는 정삼각형 4개, $k=5$ 는 별다각형 $\{12/5\}$ , $k=6$ 은 퇴화(지름들). 12의 약수 3, 4, 6, 12가 전부 등장하죠. 아래에서 직접 $n$ 과 $k$ 를 조절하며 $\gcd$ 가 결과를 결정하는 걸 확인해보세요.

---

**You**

기존에 이걸 증명한 사람이 있어?

---

**Claude**

네, 이건 이미 고전 수학으로 확립된 결과예요. 다만 한 사람이 한 번에 증명한 "아무개의 정리"가 아니라, 여러 세기에 걸쳐 층위별로 증명이 쌓인 케이스입니다.

**현상 자체의 발견은 중세까지 올라갑니다.** 오각별(펜타그램)은 피타고라스 학파부터 알려져 있었지만, 정별다각형을 처음으로 체계적으로 연구한 사람은 14세기의 토머스 브래드워딘(Thomas Bradwardine)이고, 이후 케플러가 이어받았습니다. 브래드워딘은 다각형의 변을 연장하는 방식으로 별다각형을 상세히 연구한 최초의 인물이었고, 케플러는 1619년 저서 Harmonices Mundi에서 이를 더 발전시켰죠. 다만 이 시기는 "이런 도형들이 존재하고 이런 성질을 가진다"는 탐구에 가까웠습니다. [Wikipedia + 2](https://en.wikipedia.org/wiki/Star_polygon)

**제가 위에서 증명한 바로 그 명제 — 등간격 점을 일정 간격으로 건너뛰며 잇는 구성과 서로소 조건에 의한 완전한 분류 — 의 공식적인 최초 증명자는 루이 푸앵소(Louis Poinsot)입니다.** 그의 「다각형과 다면체에 관한 논고(Mémoire sur les polygones et les polyèdres)」는 1809년 7월 24일 프랑스 과학아카데미에 발표되어 1810년 에콜 폴리테크니크 저널에 출판되었는데, 여기서 원 위에 등간격으로 분포한 n개의 점에서 시작해 매번 중심각 2π/n의 d배만큼 떨어진 점을 선택하는 구성으로 정다각형 {n/d}를 정의했습니다. 그리고 핵심 분류 정리, 즉 m과 서로소인 정수 a에 대해 원둘레의 a/m을 받치는 현이 m각형의 변이 되며, m개 꼭짓점에 대해 m과 서로소인 수의 개수만큼 서로 다른 종(種)의 다각형이 존재한다는 것을 증명했어요. 이게 정확히 제가 gcd로 증명한 내용입니다. 재미있는 점은 푸앵소가 별다각형을 만든 방식이 철사 하나를 매번 같은 각도로 꺾어서 도형이 닫힐 때까지 반복하는 것이었다는 건데 — 이건 제가 3단계에서 쓴 "고정 회전의 반복" 논증 그 자체죠. [Cnrs + 3](https://images.math.cnrs.fr/freeze/Une-geometrie-de-l-ordre-et-de-la-situation-au-XIXe-siecle-Polygones-et-theorie.html)

한 가지 역사적 각주: 사실 푸앵소보다 40년 앞선 1769~70년에 마이스터(A.L.F. Meister)가 일반 다각형 이론을 먼저 제시했고, 그륀바움(Branko Grünbaum)이 이 우선권 문제와 정의상의 논쟁({6/2} 같은 비서로소 경우를 어떻게 볼 것인가)을 다룬 논문을 쓰기도 했습니다. 즉 "무엇을 정다각형으로 인정할 것인가"라는 정의 논쟁은 20세기까지도 이어졌어요.

**제가 쓴 증명 스타일(단위근 + 순환군 + 베주 항등식)은 현대적 재포장입니다.** 순환군 $\mathbb{Z}_n$ 의 부분군 구조는 가우스의 정수론(1801) 이후 19세기 군론에서 정리된 것이고, {p/q} 기호 체계는 슐레플리(Schläfli)와 콕세터(Coxeter)를 거치며 표준화되었습니다. 오늘날 이 명제는 콕세터의 *Regular Polytopes* (1948) 같은 표준 문헌에 실려 있고, 추상대수학 교재에서는 "순환군의 부분군 분류"의 기하학적 응용 연습문제로 나오는 수준의 확립된 내용이에요. 마지막에 언급한 무리수 회전각의 조밀성 부분은 크로네커(1884)와 바일(1909–16)의 등분포 정리로 별도로 증명되어 있습니다. [arxiv](https://arxiv.org/pdf/1612.09295)

여담으로, 이 이야기의 3차원 버전 — "정별다면체는 정확히 4개뿐이다" — 도 같은 논고에서 출발합니다. 푸앵소가 1809년 케플러의 별 도형들을 재발견하고 2개를 추가로 발견한 뒤, 3년 후 코시(Cauchy)가 대칭성 개념을 이용해 이 4개가 전부임을 증명했죠. 평면에서는 무한 가족이 나오지만 3차원에서는 4개로 끝난다는 대비가 꽤 아름답습니다. [Wikipedia](https://en.wikipedia.org/wiki/List_of_polyhedral_stellations)$seed_91869d10a9b2$,
        'markdown',
        '91869d10a9b22f5a68af7e203050feddce9f6aa3965f6d85eac41d6c152b89c1',
        NULL,
        $seed_10bcd16836b1${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/선분으로 정다각형 찾기.md"}$seed_10bcd16836b1$::jsonb
    ),
    (
        '46de6572-7a89-53c3-bb05-f17be9e4b881',
        '84b00575-9e43-511e-b41f-86323629107c',
        'user/mock-clipping-user',
        '2671bc10-843b-5616-9a70-cf9a3a2451a1',
        1,
        $seed_5b39d9246ae6$실적이 이렇게 좋은데, 주가는 왜 빠져요?$seed_5b39d9246ae6$,
        $seed_b2d59a67f0fe$[[슈카월드]]$seed_b2d59a67f0fe$,
        '2026-07-13T00:00:00Z'::timestamptz,
        '2026-07-15'::date,
        $seed_66ef3e343c81$0:00 검은 월요일6:54 삼성전자 2분기 잠정실적 발표13:22 SK하이닉스 ADR 상장 가격은?21:19 미 상무 장관 "삼성과 SK하이닉스를 미국으로"$seed_66ef3e343c81$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_b9117119ae03$![](https://www.youtube.com/watch?v=4DQP7bVU41M)

0:00 검은 월요일  
6:54 삼성전자 2분기 잠정실적 발표  
13:22 SK하이닉스 ADR 상장 가격은?  
21:19 미 상무 장관 "삼성과 SK하이닉스를 미국으로"

## Transcript

### Black Monday

**0:03** · \[음악\] 아, 오늘 또 가장 중요한 주제죠.

**0:08** · 관심 많으실 거예요. 삼성전자 최적 발표가 지난주에 있었고요. SK하이스 ADR 상장 또한 지난주에 있었습니다. 굉장히 중요한 주였어요.

**0:18** · SK ADR 상장 어떻게 됐을까?

**0:20** · 한번 그 얘기를 풀어 보도록 하겠습니다. 여러분들 다 아시겠지만 코스피는 9천을 돌파한 다음에 올라가지 못하고 쭉 지금 어느 정도 하락세를 막고 있습니다. 코스피스가 7,475 뭐 많이 내려왔죠. 보시면 알겠지만 중간에 -5% -5% 두

**0:38** · 번이나 큰 하락을 지난주에 겪으면서 굉장히 어려움을 겪었던게 지난주였다고 할 수 있습니다. 조금 차트가이 주봉이거든요. 아 야야 여기 며칠봉이지? 6 60일봉인가? 밟았다 하자. 밟았다 \[웃음\] 하자. 고점 대비 한 20% 정도 밀렸어요. 좀 밀려 갖고 지난주 지진난 주 역시 계속 좀 어려움을 많이 겪고 있죠.

**0:59** · 살짝 차트로는 꺾였는데이 정도에서 이제 하다가 이렇게 올라가는 모습을 보여 줘야 될 텐데 걱정이 좀 많이 되고 있죠. 삼성전자와 하이닉스도 최근의 주가가 뭐 0 좀 뭐 많이 올랐으니까 이해 하는데 사무원자 고점이 38만 원인데 현재가 28만6,500원. 고점 대비 한 25% 조정을 받았습니다. SKS스가 고점이 300만인데 현재가 220만 원 언절이 대충 고점 대비 역시 한 26% 조정을 받았습니다. 두 종목 모두 한 25% 조정을 받았다.이 정도 조정을 받았으니까 좀 갈법도 한데 지난주에는 변동성만 컸죠.

**1:32** · 놀랍게도 지난주에도 서킷 브레이커가 발동됐습니다. 화요일 매도 서킷 브레이커. 수요일은 매도 사이드카.

**1:38** · 금요일은 매수 사이드카. 사이드카는 이제 뉴스가 아니에요. 매주 나와.

**1:42** · 매주 나와. 매주 나오는게 무슨 뉴스야? 새롭지 않아.데 서킷 브레이커 정도는 좀 새로운데 서킷 브레이커까지 발동된게 지난주죠. 7월 들어서 약간의 걱정이 생기고 있어요.

**1:51** · 그게 뭐냐? 여러분들이 주식을 사기 위해서 넣어 놓는 대기 자금이라고 할 수 있는 투자자 예탁금이 증권회사 계좌에 넣는 투자자 예탁금이 좀 꺾이고 있어요. 한창 투자액금 주식 열풍이불어 쭉 올라가다가 최근 한 달 사이에 거의 30조원이 감소했습니다.

**2:07** · 그니까 최근에 주가가 밀릴 때 투자타이 빠졌어.

**2:11** · 당연히 밀리니까 빠진 거긴 한데 뭔가 시장이 세함을 느끼고 아니면이 정도 먹었으면 됐다. 나는 내 집 마련해야지라고 집사러 가신 분들이 30조원이 돼요. 집사러 가신 분들이 많기를 기원드립니다. 내진말랑 축하드립니다. 예타금이 30조가 줄었어요. 게다가 연초 이후 계속 늘었던 신용 거래 장고 빚서 하는 분들 역시 줄었어요. 물론 여기는 이제 자기의 의지로 줄인 분과 아니면은 자기 줄이기 싫었는데 증권사

**2:38** · 놈들이 떼찌됐찌 하면서 창에다 던진 반대 매매가 들어가서 그렇게 하지만 뭐 주식이 밀려서 그런지 한 이원 정도가 줄었습니다. 한마디로 대기 자금 살 수 있는 대기 자금들이 개인들의 여력이 좀 주는게 아니냐라는 걱정들이 많이 있는게 사실이고 그리고 외국인 순 매수를 보면 최근 1년 누적이에요. 여기서부터 누적인데 외국인이 최근 1년 사에 거의 150조원을 팔았어요. 개인과 기관이

**3:02** · 각각 70조원, 60조원 정도 샀습니다. 근데 기관이라 그래도 여기는 뭐 ETF나 퇴직연금 이런게 들어가기 때문에 개인의 비중이 높아요. 그니까 거의 개인이 100조원 이상을 받았어. 최근 1년 사이에 다 알고 있죠? 외국인이 팔고 개인이 받았습니다. 그런데이 표를 자세히 보시면 개인이 처음부터 받은게 아니라 어느 순간에 굉장히 급격하게 받은 걸 알 수 있습니다.이 최근 1년 누적이에요. 외국인 누적 순매서 개인 누적 순매수. 외군이 조금씩 팔 때는 뭐 사고 팔고 사고 팔고 하다가 어느 순간부터 급속도로 팔고 나갔고 어느 순간부터 급속도로 받았어요.

**3:35** · 이게 언제냐? 5월 7일입니다.

**3:37** · 여기기 지점이 이때부터 개인 수매수 88조, 기간 수매수 17조가 잡혔고 외국인이 이때부터 100조를 팔았어요. 대충한 106조. 그럼요 날짜가 언제냐? 5월 6일은 코스피가 7,을 돌파한 날입니다. 요거 요거 요거 장대. 요게 월 주킬이에요.

**3:53** · 그다음 날은 요기가 월 7일입니다.

**3:56** · 7천을 돌파하고 장대항 본격적으로 상승하는구나 하고여 위에서 100조를 받은 거예요.이 위로 올라가면서 이제 여기 팔기 시작하죠. 100조를 던졌어요. 요거를 조금 더 예쁘게 그려보면 대충 100조인데 개인으로 잡힌 것만 치겠습니다. 뭐 ETF나 기관도 17조가 있기 때문에 100조가 넘을 텐데 여기가 월 7일이고 종가가 요날입니다.요 위에서 잡힌 개인 순수가 88조예요.

**4:21** · 물론 뭐 종목들이 있으니까 뭐 E 잡힌게 다 손익 분기점이라고 얘기할 순 없지만 어쨌건 지수상으로 보면 5월 7일 코스피 종가가 7,490입니다. 이때부터 이제 외국인들이 이렇게 팔고 개인들이 이렇게 사는 입이 벌어지는 순 매수 매도가 나오는데 그 위가 여기거든요.

**4:38** · 7,500위. 지금 코스피 종가가 7,475예요.

**4:42** · 야씨 잠깐. 자, 좀 물론 이게 조금씩 변동폭이시험 이렇게 삼각형 무슨 뭐 산수화를 그리지 크고 있기 때문에 다음 변동폭은 반드시 이래야 됩니다. 물론 제가 이런 얘기하니까 옛날 제 어떤 직원이 올라라 올라라 하면 오르냐라고 씨 저한테 한 적이

**4:59** · 있었는데 어쨌건이 위에서 우리는 거의 100조를 받았어요. 지금 그런 상황이고 당연히 그렇기 때문에 수급 불안감이라는게 안 나올 수가 없는 상황이죠. 그래서 밀렸다고 생각을 많이 하고 기업 실적이 좋은 건 알겠어.이 이 누가 받아줄 건지 문제가 있는 거죠. 그니까 외국인 순매수가 이제 서서히 돌아오고 있는 거 같고 팔만큼 팔았어. 제 생각에는 외국인들도 이제 파는게 줄어들 거 같아요. 왜냐면 얘들도이 위에서 많이

**5:23** · 팔았거든. 많이 팔고 지금 떨어져 왔기 때문에 아까 제 보여 드렸죠.요 요 지점이요 지점이에요. 그 지점에 거의 왔기 때문에 본격적으로 팔기 시작한 가격에 와서 좀 들지 않을까라고 개인적으로 저 기대를 하고 있어요. 외국인들도 순매수를 좀 팔만큼 팔았으니까 돌아올 때가 되지 않냐 생각하는데 그건 좀 더 봐야겠죠. 그 희망 상황일 뿐이고 결론적으로는 만약에 그런 매수가 들어오지 않으면 지금 누가 받아줄 것인지에 대한 의문이 생기죠. 물론 반도체로 번 돈이 굉장히 커요. 근데 이거는 막 300조 500조를 벌 거다. 뭐 이런 말들이 나오잖아요.

**5:56** · 근데 이거는 미래잖아. 시간이 남았어요. 지금 우린 1분기, 2분기 지나고 있는데 앞으로 한 분기에 100조씩 버는 거, 3분기에도 100조, 4분기에도 100조 뭐 이렇게 벌고 내년에도 막 300조 버는 거 좋은데 그건 미래고 주식은 이미 미래 현금으로를 당겼거든.

**6:11** · 그래서 여기 9천까지 올렸어요. 9, 7천 시가 총액 2,조 3000건제 SK닉스 2,400조 이렇게 올렸단 말이에요. 그리고 우린 거기서 100조를 사고 팔았어요. 그리고 100조가 나갔어. 외국인이 자금 기준으로 150조가 순수하게 빠졌죠.

**6:25** · 그러면 일단 개인 자금 150조가 그걸 메워서 들어왔는데 반도체로 번돈이 국내로 유입돼서 낙수가로 쫙 퍼지면서 우리들한테 세금이 됐건 뭐가 됐건 뭐 아니면 내주머니에 들어와서 이렇게 우리가 이제 부자가 되면 상관이 없는데 아직 그건 미래니까 되긴 되겠지만 지금 당장 수급에서 시장이 이제 의문을 갖는 거죠. 이제 누가 받아 줄 거냐. 물론 그래서 지금까지 밀렸고라고 생각을 하죠.

**6:49** · 앞으로는 이렇게 올라오지 않을까 여기 들어오면서 기대를 하고 있긴 한데 자 이런 상황에서 이런 우리의 불안한 마음을 그래서 예탁금도 즐거하잖아요.

### Samsung Electronics Announces Q2 Preliminary Earnings

**6:58** · 만져줄 삼성현재 2분기 실적 발표가 있었습니다. 잠정 실적을 발표해요.

**7:03** · 연결 기준 매출 171조 영업 이익 89.4조 \[웃음\] 89.4조 사조 한 분기입니다. 한 분기 상반기도 아니고 정말 듣도 보도 못한 숫자가 지켰습니다. 전년 동기 대비 영업 이익이 18810%가 증가했어요. 슈카 친구들이 증가한게 아니고요. 삼성전자 우리나라 시가총 1위 기업이 영업 이익이 1800% 늘었습니다. 18배 늘었다는 거예요.

**7:29** · 얼마니까? 만 한면 5 6조 벌다가 90단 말입니다. 이번에 삼성 면자가 한 분기에 번 실적은 지난 2023년 2024년 2025년 3년 합산 영업 이익보다 큽니다. 한 분기가 아마 올해 번 거 다 합치면은 역대 삼성전자가 번 돈을 다 합쳐도 안 될걸. 올해 뭐 3분기에도 100조 얘기하잖아. 100조 넘는다.

**7:50** · 4분기도 100조라고 치면 그거만 해도 지금 얼마니까? 300 40조 되니까 삼성전자가 역사 내내 50년 60년 역사에 아마 이돈 못 벌었을 것 같아. 한 분기가 지난 3년보다 크다. 그게 이번 분기 영업이라 할 수 있고요. 89조원은 민간기업 역대 1분기 최대 영업 이익이익에 가까울 겁니다. 이거보다 많이 번 기업을 본 적이 없어요.

**8:13** · 아람코 정도 있는데 여긴 구경 기업이니까 아람코 정도를 빼면 89조는 엔비디아가 최고 많이 벌 때보다 우리가 많이 벌었어요.

**8:21** · 엔비디아가 1분기 82조 벌었거든요.

**8:22** · 엔비디아보다 많이 벌어. 애플보다 우리가 많이 벌었습니다. 주가는 좀 이상하지만 엄청난 돈이고 그리고 저 89조도 여러분 다 들어셨겠지만 성과급 충단금을 뺀 값입니다.

**8:33** · 지난번에 그 노사합비를 성가급 계약은 거 있잖아요. 그걸 안 빼면 옛날에 안 빼고 발표했잖아요. 안 빼고 발표했다기보다 훨씬 작게 발표했죠.

**8:41** · 그걸 고려하지 않으면 영업 이익이 110조야.

**8:44** · 110조. 100조 넘는 영업 이익기 입에 찍힐 수 있었어. 왜냐면 이번에 1분기, 2분기, 상반기 두 개 분기의 성과급 충단금 20조를 한꺼번에 반영했기 때문에 이게 내려간 겁니다. 음. 내려가서 89조. 아유 못 벌었다. 110조 벌 수 있었는데 아유 부진했다. 89조. 놀랍게도 제가 농담처럼 이렇게 얘기했는데 시장을 진짜 부진했다고 생각한 거 같아요. 세계 넘버원의 영업 이익을 찍었는데 실적 발표 당일날 -9.6%를 찍었습니다.

**9:13** · 제가 아침에 89조를 보고 기분이 흥해서 아무런 문제가 없겠구먼. 어, 하고 천천히 쉬고 뭐 놀다가 보니까 -9%였어요.

**9:22** · 다음날 -8.25%를 찍었습니다.

**9:26** · 물론 뭐 기적의 단어 선반형이라는게 있지만 해도 해도 너무한 거 아니냐.

**9:30** · 그래서 개인적으로 그렇게 야, 이거는 실적 때문에 밀리는게 아니라 그래서 아까 수급 같은 거를 이제 야, 수급이 꼬여서 그런 건가? 누가 들어와 줘야 되는데 그런 생각을 하는게 이거는 영업 이익 때문에 밀리는 거 같지 않다. 최소 아무리 선반정이어도 어, 적당히 해야지.

**9:43** · 적당히. 아니면 혹시 글로벌 주식이 폭락해서 그런 거냐? 지수 폭락은 사실상 유즘 대한민국만의 이슈입니다.

**9:52** · 나스닥은 뭐 3.3%요.

**9:55** · 뭐 \[웃음\] 밀린게 없어. SP도 밀린게 없어요. 조금 밀렸다가 요렇게 하다 렇게 있으니까 니케는 좀 밀렸는데 올라가면 여기서 물론 이렇게 빠지면 모르겠지만 뭐 한 5% 6% 뭐 이거는 뭐 밀렸다고 얘기하면 뭐 하지? 뭐 이렇게 가는 거니까 이렇게 글로벌에는 이슈는 아니다. 자, 그러면 이거 혹시 그 저 커버그 메타 메타가 데이터 세터 남는다고 해서 이것 때문에 지금 코스피 팍팍 밀린 거 아니냐? 이거서 쭉 갈 수 있는데 내인놈 저커버그 적커버그가 제 말을 들었는지 지난주에 반성문을 썼습니다.

**10:23** · 항의문을 항의문 저는 억울합니다.

**10:26** · 제가 한 말은 메타에 제시되는 금액이 워낙 높기 때문에 경우에 따라서 메타가 사용하는 대신에 임대하는 방식이 더 나올 수도 있다는 말이에요. 우리가 AI 클라우드가 남아서 대회해 준다는 말이 아니라 워낙 비싸게 사용해 준다고 하니까 야 그럼 내가 사용하는 것보다 파는게 더 많이 남겠다라는 뜻으로 얘기를 했는데 어 제가 한 말은 어제까지나 메타가 이미 과잉 생산 오버빌트를 했다.

**10:50** · AI 데이터 센터 아니면은 남는 컴퓨팅 파워가 있다. 그런 뜻은 절대 아니다.라고 얘기를 하셨죠. 그러면 오를법도 한데 빠질 때는 급힌게 되고 빠지더니 아니 빠질 때는 뭐 메타가 오버빌트 반도체가 남아 돌아가서 빠지되더니 아니라고 저렇게 얘기하시는데 안 올라오는 꼬락선이가 이게 아닙니다.

**11:10** · 하여튼 그래서 모든 건 다 핑계니까음 하여튼 그래서 메타가 남는 컴퓨팅 파워가 있다는게 절대 아니라고 항변을 했고요. 업계에서 저거벅은 이렇게 얘기했습니다. 컴퓨트인 자원이 너무 많다고 보는 사람은 지금 아무도 없을 것이다. 메타는 현재 보유한 모든 자원을 활용하고 있다. 다만 워낙에 비싸게 빌려간다는 사람들이 있으니까 그럼 수익분들로 야, 저 정도 비싸게 주면 빌려줄 법도 하네. 차라리 새로지는게 낫겠네라고 생각을 해서

**11:34** · 빌러줄 수 있다라는 얘기를 한 거다라고 얘기를 했죠. 그러면서 진실성을 보이기 위해서 실제로 캐나다의 1GW급 대규모 AI 데이터 센터를 추가로 지켰다는 내용도 발표했습니다. 만약에 오버빌트됐으면 또 지울 필요가 없잖아요. 캐나다 엘버타의 메타가 1GW 최대 13조원 무려 33번째 데이터 센터라고 합니다. 얘네 데센트 진짜 많구나.

**11:56** · 33개를 갖고 있어. 데이터 센터를.음 뭐 어마어마한 규모만 갖추테니까 왕공까지는 한 2, 3년이 걸릴 예정이라고 하는데 캐나다의 대규모 리세트 진다고 발표했고요. 실제로 더 확장하고 내년까지 컴퓨팅 파워를 더 크게 늘리고 그리고 지금 메타 최대 이슈 자체 AI칩 오늘 얘가 갖고 오진 않았지만 TSMC하고 손잡아서 AI 자체 AI 칩을 만들 예정입니다라고 또 발표를 했죠.

**12:19** · 그러면 저 메타가 얘기를 빠진 거 같진 않고 그럼 역시 외국인들인가?

**12:23** · 실제로 외국인들을 보면은 최근 한 달 삼성전자 웨스크이닉스를 42조원 팔았어요. 그리고 형님들이 41조를 받았습니다. 최근 한 달 삼성전스가 밀린 큰 가장 큰 이유가 사실 이거죠. 외국인들이 팔았고 우리가 받았다. 40일조 받았어. 41조

**12:41** · 많이를 받았는데 그래서 개인적인 생각이 야 그러면 이걸 왜 이렇게 파냐? 물론 리벨 수도 있겠지만 혹시 너들 그 SKIS ADR 살려고 이거 돈 빼는 거 아닌가? 어차피 미국 시장에서 나스닥에서 SKX ADR를 살 거니까 한국에 있는 본주를 팔고 어 이놈들이 싸게 살려고 밀고 미국에서 ADR를 산 거 아니냐라는 이런 합리적인 의심을 할 수 있죠.

**13:02** · 예. 원래 그 손해를 보면 별 생각이 다르게 돼 있다. 제기고요. 요즘에 하두 깨지다 보니까 이제 별의 별 생각이 다 드는데 여기까지 간 거죠.

**13:11** · 이놈들 희망회로 돌리는 겁니다. 저 나스닥에 가서 저거 살려고 판 거 아닌가 그러면 상장했으니까 이제 다시 사나? 이제 다시 사는 건가 하는 요런 생각을 하게 되죠. 실제로 SK이닉스는 지난주 금요일 날 미국 나스닥의 ADR를 상장했습니다. 상장 가격은 149달러였어요. 본주 기준으로 225만 원으로 상장을 했고 총 발행 주수가 대충 1억 7,790만 주 40조 발행 공모

### What Is the SK Hynix ADR Listing Price?

**13:39** · 총액이 265억 달러예요. 한마디로 주식을 팔아서 받는 돈이 40조 ADR 한 주는 보통 주입니다. 분로 보시면 되니까 가격 그렇게 보시면 되고이 40조를 모집을 한다는게 얼마나 큰 금액이냐면 외국 기업 IPO 역사상 최대 금액이라고 합니다. 알리바가 2014년 뭐 옛날이긴 하지 12년 전에 조달한 금액이 250억 달러인데 그걸 넘는 265억 달러를 공모했으니까 외국 기업의 미오사상 최대 규모의 돈을 40조를 미국에서 당긴 겁니다.

**14:09** · 미국에서이 돈보다 더 큰 돈을 당긴 외국 기업은 없다. 그리고 저거를 당긴 날 여러분들 보셨죠?

**14:14** · 월스트리트의 태극기와이 하이스가 쫙 도배가 됐습니다. 커.

**14:20** · 그니까 미국 월가에서도 굉장히 큰 IP예요. 거래량도 뭐 압도적인 아마 1일를 찍었을걸요. 저날은 사실은 저 월스트리트와 나스닥이 SK 하인스를 덮혔어. 가장 큰 IPO라고 할 수 있고요. 게다가 40조는 미국 증시 역사상 두 번째로 큰 자금 조달이라고 합니다. 어, 이건 제가 신기해서 여러분 찾아봤는데 맞는 거 같아요.

**14:41** · 이번 ADR 상장은 스페이스 X에이 있어서이어서 역대 두 번째로 큰 주식 매각 사례다. 시가 총액은 더 큰게 있을 수 있어도 실제로 주식을 판게 40조 넘는 경우 잘 없습니다.

**14:50** · SKS 신가 초액도 엄청나요. 거의 뭐 1,600조, 1700조 하잖아.

**14:55** · 세계 12 뭐 15위권 기업이기 때문에 그 정도 큰 기업이 지금 40조를 매각을 한 거죠. 게다가 미국 ADR IP 역사상 최초로 할증 상장을 했어요. 보통 40조 정도를 IPO라면 좀 할인 상장을 합니다.이 정도 파는데 좀 깎아 줘야 사지.

**15:12** · 할증에서 누가 사겠니라고 생각하지만 인기가 많아서 할증 상장을 했죠.

**15:16** · 가격을 본주보다 조금 높게 상장을 했다. 그런데도 장이 많이 몰렸다는 거고요. 그런데 저 ADR를 상장하니까 이런 생각을 하는 사람들이 많았다는 겁니다. ADR을 매수하고 하이닉스 본주를 매도하는게 아주 당연한 선택이다.

**15:31** · 그게 사실은 같은 거라고 할 수 있는데 같은게 아니죠. ADR을 매수하고 하이닉스 본주를 매도하는 그런 거래가 많이 있었다는 거죠.

**15:38** · 자, 왜냐면 왜 그러겠습니까? 불과 2점 아까 몇 %라고요? 9% 할증 발행했어요. 근데 하이닉스 정도 되면 미국에 상장된 SK 하이닉스 ADR과 한국에 상장된 하이닉스 본주 중에서 뭐가 더 비싸지겠습니까?

**15:54** · 상식적으로 뭘 더 갖고 싶어요?

**15:56** · 외국인 투자자들 입장에서 어 좀 있다 얘기했지만 당연히 미국 시장에 상장된 ADR이 더 반인들이 보기에 매력이 있을 수밖에 없기 때문에 그러면 같은 거 하면은 본주 팔고 AR 사는게 당연한 거 아니냐 이런 얘기를 하는 거죠. 실제로 투자자들은 하이스 ADR 사고 하이스 본지를 판다고 많이 생각을 한다.

**16:15** · 왜냐면은 ADR이 앞으로 더욱 높은 가격에 거래될 가능성이 높기 때문이다. 그럼 ADR이 왜 높은 가격에 거래가 되나? 똑같은 건데 ADR의 가격이 높고 한국 본주가 가격이 낮으면 이거 차익거리 하면 되잖아요. 가격이 높은 걸 팔고 세라고 가격이 낮은 걸 사면 두 개가 똑같은 건데 그거 버는 거 아닙니까?

**16:34** · 높은 걸 팔고 낮은 걸 사면.

**16:36** · 그렇죠. 자, 그런데 안 되는게 하나 있습니다. 미국 ADR 보유자는 ADR을 팔고 ADR로 한국 증시에 와서 SK 하이스의 본주를 받을 수 있어요. ADR이 있으면 한국 본주로 받을 수 있습니다. 그래서 만약에 한국 본주의 가격이 더 비싸. 미국에 ADR이 싸. 그럼 이걸 싼 걸 팔고 비싼 거 주세요 하면은 차익거래로 벌 수 있어요. 근데 문제는 한국에서

**17:01** · 미국으로 가는게 쉽지 않습니다. 한국 본주를 들고 있다가 예를 들면 SKX가 200만 원이야. 근데 미국 ADR 보니까 250만 원이야. 말이 안 되잖아요. 같은 건데. 그러면 나는 한국 주식을 미국 ADR 250만 원짜리 바꿔 주면 50만 원 남죠. 그 가서 어 저 이거 ADR로 바꿔 주세요 하면 안 된나 잘 안 돼요. 이론적으로 되는데 ADR 총수가 정해져 있기 때문에 뭐 이런저런 규제도 있고 여기가 누군가가 이걸 반대로 해 줘야 되는 거야.

**17:29** · 누군가가 근데 해 주겠냐고 좀 50만 원이 비싼데 그게 많이 없다는 거죠.

**17:36** · 물론 여기가 이제 누가 뭐 팔고 뭐 들어오거나 그런 수요가 있을 수 있지만 잘 없어서 1 방향이기 때문에 당연히 여기서는 일로 갈 수 있는데 여기서 일로 못 간다고 하면은 프리미엄이 미국 ADR에 더 많이 생길 수밖에 없지 않냐라는 얘기를 하는 거고 열리면 대표적으로 ADR이 있는 기업 TSMC가 있습니다.

**17:54** · TSMC는 현재 본주와 ADR의 프리미엄 차이가 얼마냐? 16%예요.

**17:59** · 많이 나요. 지금 SKS가 이번에 2.5%인가 전체 주식에 그거만 나스닥게 상장했죠. TSFC는 훨씬 많은 지분이 나스닥이겠습니다.

**18:06** · 그런데도 차이가 많이 나요. 16% 16%의 차이가 나고 있고 이렇게 되는 이유는 당연하게 대만도 똑같아요. 기본적으로이 전환을 규제해. 대만 본주로 받는 거는 가능한데 본주를 다시 신규 ADR로 가는 걸 규제합니다. 총량이 제약이 있기 때문에 이게 어렵기 때문에 역시 16%에 차이가 있다고 할 수 있고 우리나라도 아마 쉽지 않을 거예요.

**18:28** · 방금 얘기드렸듯이 실제로이 SKS가 제출한 증권 선거에 써 있을 수 있습니다. 미국인들이 ADR을 한국 보통주로 바꾼다면 다시 ADR로 바꿀 수 없을 수도 있다. 그걸 참고하고 투자해라라고 적어 놨어요. 명시적으로 적어 놨어요. 미국인들아 너희가 250 들고 있는 여기가 조금 좋아 보인다고 일로 다시 들어오면은 거꾸로는 안 될 수도 있다. 들어올 때는 마음대로지만 나갈 때는 아니기 때문에 기자가 될 수 있습니다.

**18:53** · 그래서 AD의 총수가 한 개가 있어서 거래는 쉽지 않을 수 있고요. 자, 그럼 돌아와서 SKS ADR은 얼마로 마감됐냐? 장중 한 때 미쳐 갖고 177달러 가면서 아 월요일날 우리나라 시장 너무 좋겠다고 생각했는데 쭉 밀려 갖고 168달러

**19:10** · 플러스 12%로 마감했습니다. 본주 기준 252만 원이에요. 야 그러면 SK스 내일 12% 오르는구나 그러기를 강력하게 원하는데 이게 프리미엄 차이가 이제 몇 퍼센트에 따라 다르겠죠.음 음 다르겠어서 이게 한 막 20% 막 이렇게 올라갔으면 월요일 날 조금 많이 기대할 법한데 어쨌건 상승했어요. 어쨌건 상승했기 때문에 기대를 하곤 있지만 어디까지가 프리미어일지를 이제 한번 봐야겠죠.

**19:36** · 자, 그리고이 얘기도 많이 하더라고요. ADR은 본주에 악재냐 호재냐.

**19:41** · 미국 시장 접근성이 낮다한 이후로 마이크론데이 너무 저평가 받았는데 ADR 상장을 통해서 접근성이 강화됐으니까 리레이팅 될 수 있는 거 아니냐? 호재 아니냐? 아니면 반대로 아니 이게 유상증자와 같은 거니까 주익수가 늘었으니까 악재 않냐?

**19:54** · 아니면 별다른 영향이 없지 않냐?

**19:56** · 진짜 개인적인 생각엔 전 개인적으로 진짜 호자로 생각합니다. 개인적으로는 아니 글로벌 자금이 쉽게 접근할 수 있는 통로가 생긴 것만으로도 나쁘지 않을 수 있다. 물론 이제 미국 ADR만 쭉 올라가고 한국에 있는 거는 뭐 프리미엄 벽차가 엄청나게 벌어질 수도 있겠지만 어쨌건 이게 끌고 올라가 주는 것만으로도 우리가 지금 수급에 지금 떨고 있는데 이쪽에 지금 완전히 외면 받아 갖고 야 돈 안 들어오냐 이러고 있는 것보단

**20:20** · 개인적으로는 뭐 코제이라고 생각하는데 전환이 크게 어렵다면 ADR만 쭉 올라갈 수 있죠. 프리미엄이 20% 이렇게 버릴 수 있다고 보긴 하는데 하지만 호재가 아닌가 생각을 하고 다만 지난주에 이슈가 됐던 레포트 중에 우리 BNK 최정권에서 나온 레포트가 ADR 발행은 중립적이고 원주 밸리에이션은 달라지지 않을 전망이다. 그리고요 레포트가 SKS

**20:41** · 보유 의견을 했습니다. 보유라는 거는 우리나라 기준으로는 지금 현재 주가보다 목표 주가를 낮췄기 때문에 약간 셀에 가깝죠. 셀 \[웃음\] 레포트 가까운게 나왔는데네 레포트 그렇고 다른 레포트들은 대부분 다 훨씬이 올린 레포트도 많이 나왔어요. 그중에 이제 독특하게 보유 의견이 나와서 제가 한번 보여 드리면 이런 얘기를 합니다. 빅테크들의 향후 투자 속도 조절 가능성이 높아지고 있다. 그러면 앞으로 미래의 실적 전망은 지금보다 내려가지 않겠냐?

**21:08** · 최근 주가 급락은 수요 두사를 반영할 수 있고 연마리 이후 실종 모멘텀이 꺾이면은 내년 이후에 밸루에이션은 좀 부담이 될 수도 있다라는 데포트가 나와서 좀 화제가 좀 됐었죠. 자, 여기에다가 추가된게 있었는데 최근에 미국 상무장관이 한국 기업들을 언급한 일이 있었습니다. 나는 마이크론의 경쟁사인 삼성과 SK스를 미국으로 데려와 공장을 짓게 하고 싶다.

### U.S. Commerce Secretary: "Samsung and SK Hynix to the U.S."

**21:30** · 갑자기 얘기했는데 얘기는 왜 해놨냐?

**21:33** · 지난 7월 9일 마이크로는 미국 건국 250주년 기념일에 2,500억 달러 투자를 발표했습니다. 우리나라는 저기 뭐 선남권 800조 무슨 뭐 4,000조 대규모 투자 발표했죠.

**21:44** · 우리나라도 투자 발표했듯이 마이크론도 대규모 투자를 발표했어요. 매물리 칩 수요를 충족하기 위해서 미국의 2,500억 달러를 투자하겠다.

**21:52** · 그러면서 세계한 건 2035년까지 10년 안에 디램의 40%를 미국에서 만들겠다. 본인들이 생산한 디램 기존에 2천억 달러 투자 계획이 있었는데 500억 달러를 추가한 겁니다. 마이클 CEO는 이렇게 얘기했습니다. 이번 주는 9만 개 이상의 일제를 창출하고 미래를 만들어 갈 최첨단 기술이 미국에서 개반될 수 있도록 지원을 하겠다라고 얘기했고 러트닉 상부장관이 이거를 극찬을 한 겁니다. 놀라운 기업들이 미국에 대규모 추를 하고 있고 마이크로는 그중에서 단연 독보이는 기업이다.

**22:19** · 그러면서 아까 전에 얘기했던 나는 삼성과 SK스를 미국으로 데려와서 공장을 짓게 하고 싶다라고 얘기를 한 건데 사실 약간 불안한 측면이 있죠.

**22:29** · 마이클이 미국의 선두에서 있고 러튼이게 한 얘기입니다. 다른 회사들은 질투할 것이고 결국 따라올 수밖에 없을 것이다. 그까 뭔가 살짝살짝 압박을 주고 있는데이 미국 상무부 장관의 말이 꼭 가볍게만 들리지 않는게 이런 일이 있으면 절대 안 되겠지만 일본 니케 시문에서 이런 내용이 나왔다 그러죠. 삼성근자가 뭐 물가 저항, 중국 위험 이런 것도 있지만 트럼프 행정부의 반독점 규제

**22:52** · 일본이니까 이런 얘기를 한다고 생각합니다. 일본이 옛날에 미도체 협정 이런 거 맺었거든요. 너무 영업 이익이 올라가고 3계사가 지금 한 7, 80% 이상을 갖고 있으니까 트렁정부가 여기에 대해서 칼을 뽑을 수도 있지 않냐?

**23:05** · 저는 아니라고 생각을 하고 이런 일이 있어서도 안 된다고 생각하는데 1986년 1991년 9명은 미 반도체 협정입니다. 당시에 일본이 반도체 세계 시장 점유율이 50%까지 늘었어요. 미국이 많이 떨어졌죠.

**23:17** · 디랭 같은 경우에 미국 시장 점유율이 20%까지 급락합니다. 교전 70%였는데 반면에 일본의 점유율이 75%까지 올라갔어요. 근데 그때는 지금하고 좀 달라. 그때는 미국이 일본이 반도체를 덤피간다고 주장했어요. 너무 싸게 들어와서 애들이 점유를 높았다. 그래서 가격 한재를 도입합니다. 덤핑 방지. 덤핑 방지. 근데 지금 가격이 너무 높아서 문제죠. 그리고 일본 내 자기네 미국 반도체 쿼터제 같은 걸 만들어요.

**23:42** · 외산 반도체 쿼터제를 만들었는데이 덤핑 방지에 걸려서 일본 반도체들이 어려움을 겪고 이제 우리나라 반도체가 커지고 뭐 이런 것들이 이제 펼쳐 있죠. 지금하고 다르다. 그렇다고 뭐 이거를 자본주의 시장에서 가격 상한제 같은 걸 할 것 같진 않아서 지금과는 다르지만 어쨌건 미국 기업들이 대단히

**23:59** · 불만을 표하는게 많기 때문에이 주의깊게 봐야겠죠. 또 그래서 기자가 물어봤습니다. 아니 상무장관님 얼마 전에 애플이 중국 반도체 기업들과 접선하면서 중국산 메모리치 구매한다는데 이거 어떻게 생각하십니까? 그랬더니 대답하지 않았어요. 애플 관련 질문에는 대답하지 않고 넘어가는 일이 있었습니다. 그래서 자꾸 아 우리 공장을 원한다고 공장을 원하실 것 같으니까 보내 줬습니다. 뭐를 보내줬냐면 공장 대신에 주식을 보내줬다. 가은 셈 치시면 된다.

**24:27** · 주식을 가지고 있으면 공장을 가진 거 똑같다. 자 하니스가 많이 벌면 미국인들이 돈을 버는 거야. 아니 약간 2.5% 주식 있잖아. 하이스가 많이 벌면 마치 마이크론처럼 아니 뭐 쿠팡도 우리나라에서 벌고 미국에 상장하니까 미국교이라고 막 해주더만 우리도 여기 있지만 어쨌건 미국 주식이 있으니까 이걸 많이 사시면 올라올 수 있는 거죠. 돈을 버시면 되는 거고 그리고 참고로 이쪽에서 끝이 아닙니다. 무슨 소리냐?

**24:50** · 추가적으로 상장할 가능성도 있어요.

**24:52** · 이게 몇 배더라? 아마 2.5%보다 굉장히 많은 배수를 추가적으로 상장할 수 있는 걸 이미 처음에 신청선을 때 그걸 다 넣어 놨어요. 그 사실은 더 상장할 수도 있다. 만약에 ADR 가격이 굉장히 높이 올라가고 우리나라하고 프리미엄이 벌어진다든지 아니면 뭐 미국에서 더 많이 요청하다든지 하면은 미국 나스닥에 더 많이 상장할 수 있겠죠. 실제로 TSMC도 그렇게 했거든요.

**25:13** · 2.5%가 아니라 뭐 3%, 4%, 5% 뭐 이렇게 갈 수도 있는데 자 그러면은 이걸 사시면 됩니다. 미국 정부가 SK 주식을 좀 사셔서 사셔서 주주가 되고 뭐요? 미국분들도 주주가 되시면 그죠. 그죠 그죠. 공작은 한국에 있지만은 그 열매를 이제 같이 나눠 먹는 그런게 되면은 딱 좋지 않을까 생각을 합니다. 요즘에 주식 시장이 항상 어려운데음 뭐 한 25배 조정 받았으니까 다음 주에는 좋은 시장에 와서 모두가 다 웃고 돈도 많이 벌고 여름 휴가도 시원하게 갈 수 있는 그런 시작이 되기를 한번 기원해 보겠습니다. 습니다.$seed_b9117119ae03$,
        'markdown',
        'b9117119ae03444e8e99ad13929a0ae6de65c90a5d0a0f706cc44e3305a50ce6',
        NULL,
        $seed_b413a65ec0a3${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/실적이 이렇게 좋은데, 주가는 왜 빠져요.md"}$seed_b413a65ec0a3$::jsonb
    ),
    (
        '3ad29bdd-8eb9-5456-ab23-d199712788cf',
        '5aba7f3d-13ab-5627-b748-0d8b1f122e6f',
        'user/mock-clipping-user',
        '9cd8b5da-6a11-5ecf-ad78-163db49cab69',
        1,
        $seed_4fc545bf0883$이더리움, 한달 만에 1880달러 - 디지털애셋 (Digital Asset)$seed_4fc545bf0883$,
        $seed_62ebea31cde9$[[박범수]]$seed_62ebea31cde9$,
        '2026-07-15T00:00:00Z'::timestamptz,
        '2026-07-15'::date,
        $seed_7c405db3a8f7$시가총액 2위 가상자산(디지털자산) ETH(이더리움)가 한달 만에 1880달러(약 280만원)대에 거래됐다.이더리움은 15일 오전 9시 22분 코인마켓캡에서 전날$seed_7c405db3a8f7$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_a94eff93a381$![이더리움. 출처=Shubham's Web3/ Unsplash](https://cdn.digitalasset.works/news/photo/202607/41973_43534_2653.jpg)

이더리움. 출처=Shubham's Web3/ Unsplash

시가총액 2위 가상자산(디지털자산) ETH(이더리움)가 한달 만에 1880달러(약 280만원)대에 거래됐다.

이더리움은 15일 오전 9시 22분 코인마켓캡에서 전날보다 5.86% 오른 약 1882.52달러(약 280만5000원)에 거래됐다.

이더리움이 1880달러대에서 거래된 건 지난 6월 3일 이후 한달 만이다.

이날 미국 6월 소비자물가지수(CPI)가 전년 동기 대비 3.5% 올라 시장 예상치(3.8%)를 밑돌아 금리인상 우려가 완화되면서 디지털자산시장 전반 가격이 상승했다. 통상 금리인상 우려 완화는 유동성 확대 기대로 이어져 디지털자산 등 위험자산 가격 상승을 이끈다.

[![텔레그램_260311](https://cdn.digitalasset.works/bannerpop/uploads/image/1773196502405750903.jpg)](https://t.me/+SF3ef-HDZxA5NzJl)

Keyword

[#이더리움](https://www.digitalasset.works/news/articleList.html?sc_area=K&sc_word=%EC%9D%B4%EB%8D%94%EB%A6%AC%EC%9B%80&view_type=sm) [#CPI](https://www.digitalasset.works/news/articleList.html?sc_area=K&sc_word=CPI&view_type=sm)

저작권자 © 디지털애셋 (Digital Asset) 무단전재 및 재배포, AI학습 및 활용 금지

Related News

- [\[ETH레터\] 비탈릭, '이더리움 검증인 상태 데이터 축소' 제안](https://www.digitalasset.works/news/articleView.html?idxno=41936)
- [\[ETH레터\] 이더리움코리아, 정부·기관 위한 이더리움 안내서 공개](https://www.digitalasset.works/news/articleView.html?idxno=41814)

[모바일버전](https://www.digitalasset.works/news/articleView.html?idxno=41973)$seed_a94eff93a381$,
        'markdown',
        'a94eff93a3815679ca46da7ab0d65fd2e22d6f2288d8f5f10b409509a0b00dcc',
        NULL,
        $seed_dbdb89273134${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/이더리움, 한달 만에 1880달러 - 디지털애셋 (Digital Asset).md"}$seed_dbdb89273134$::jsonb
    ),
    (
        '3dde7d81-7e29-574e-a8a9-9cab9108c967',
        '3622c1fd-a240-5868-b398-47248ac6885f',
        'user/mock-clipping-user',
        'c9d8fee5-8d8c-58be-adc0-7e57f9e2bb0d',
        1,
        $seed_ec2fb08fe674$지표서비스 | e-나라지표$seed_ec2fb08fe674$,
        NULL,
        NULL,
        '2026-07-15'::date,
        NULL,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_49b3e1d3fe26$이 누리집은 대한민국 공식 전자정부 누리집입니다.

- 국무총리직속기관
- 금융위원회
	- 개인정보보호위원회
		- 공정거래위원회
		- 국가데이터처
		- 국민권익위원회
		- 기획예산처
		- 식품의약품안전처
		- 인사혁신처
		- 지식재산처
- [주가지수-코스닥 종합지수](#)
	- 가계신용 동향
		- 기업공개실적
		- 기업자금조달 현황
		- 보험회사 수입보험료 규모
		- 보험회사 자산 현황
		- 보험회사 지급여력비율
		- 상장회사수, 시가총액
		- 상호저축은행 BIS자기자본비율
		- 상호저축은행 고정이하여신비율
		- 시가총액 대비 투신편입 주식, 채권 비중
		- 시장금리 추이
		- 신용보증 규모
		- 신용카드 이용실적
		- 신용카드사 조정자기자본비율
		- 신협순자본 비율
		- 어음부도율
		- 외국인 증권투자 현황
		- 유상증자 실적
		- 은행 총자산이익률(ROA)
		- 은행BIS 기준자기자본비율
		- 은행고정이하여신비율
		- 은행의 기업 및 가계대출 연체대출채권 비율
		- 은행의 대손충당금 적립률(Coverage Ratio)
		- 주가지수-코스닥 종합지수
		- 증권회사 영업용 순자본 비율
		- 채권발행/유통현황
		- 코스피 200 선물 거래 추이
		- 펀드 수탁고
		- 회사채 발행규모

이미지 인쇄 파일다운로드 URL복사

**주가지수-코스닥 종합지수** 32

### 그래프

(단위:p)

주가지수 추이

코스피 지수

코스닥 지수

출처: 한국거래소「증권선물」

### 통계표

<iframe title="입력통계표" src="https://www.index.go.kr/unity/potal/eNara/sub/showStblGams3.do?stts_cd=108001&amp;idx_cd=1080&amp;freq=Y&amp;period=N" height="336"></iframe>

### 의미분석

#### 지표설명

■ 주가지수 및 코스닥종합지수 개념 및 의의  
  
ㅇ 주가지수 및 코스닥 종합지수란 한국거래소에 상장 및 등록되어 있는 주식의 시장가격을 토대로 작성되며, 전반적인 주가의 동향을 가장 잘 나타내주는 대표적인 지수  
  
ㅇ 지수의 산출은 기준시점의 주가수준을 주가지수의 경우 100,코스닥 종합지수의 경우 1,000으로 하여 비교시점의 주가변동을 시가총액 방식으로 측정하게 되는데 현재의 주가지수 및 코스닥 종합지수는 각각 1980년 1월 4일, 1996년 7월1일을 기준시점으로 하여 산출  
  
※ 시가총액방식 주가지수 = 비교시점의 주식 시가총액 / 기준시점의 주식 시가총액 x 100  
  
■ 주가지수 및 코스닥종합지수 지표의의 및 활용도  
  
ㅇ 전반적인 주가의 동향을 신속하게 파악할 수 있는 합리적인 투자분석지표로서, 수치해석방법은 1980년 1월 4일 이후 특정시점의 주가지수가 1,000이었다고 한다면 당시 주식시장의 시가총액은 1980년 1월 4일의 10배가 됨을 의미  
  

#### 유의사항

o 시가총액의 규모가 큰 일부 대형주의 등락이 전체 주가지수의 변동에 영향을 미쳐 시장의 전반적인 흐름을 반영하지 못하는 경우가 있음  

### 관련용어

**코스피지수:** 유가증권시장에 상장된 보통주를 기준으로 산출하는 시가총액식 주가지수- 1980년 1월 4일을 100으로 하여 산출

**코스닥지수:** 코스닥시장에 상장된 보통주를 기준으로 산출하는 시가총액식 주가지수- 1996년 7월 1일을 1,000으로 하여 산출

### 지표정보

**담당 부서 및 연락처:** 금융위원회, 자본시장과, 02-2100-2658

**최근 갱신일:** 2025-09-24(입력예정일: 2026-05-01)

**자료 출처:** 한국거래소 홈페이지

**공표 주기:** 생산주기(일), 관리주기(월)

### 정책정보

**주요정책자료**

| 번호 | 제목 | 등록일 |
| --- | --- | --- |
| 12 | 코스피 주가지수(2024년 하반기~2025년 상반기).xlsx | 2025-09-23 |
| 11 | 코스닥 주가지수(2024년 하반기~2025년 상반기).xlsx | 2025-09-23 |
| 10 | 코스닥 주가지수 (2020년 상반기).xls | 2020-08-12 |
| 9 | 코스피 주가지수 (2020년 상반기).xls | 2020-08-12 |
| 8 | 코스닥 주가지수(2019년).xls | 2020-02-03 |
| 7 | 코스피 주가지수(2019년).xls | 2020-02-03 |
| 6 | 코스피 주가지수(2018년).xls | 2019-01-14 |
| 5 | 코스닥 주가지수(2018년).xls | 2019-01-14 |
| 4 | 코스피 주가지수(2017년).xls | 2018-01-18 |
| 3 | 코스닥 주가지수(2017년).xls | 2018-01-18 |
| 2 | 코스피 주가지수(2017년 상반기).xls | 2017-08-30 |
| 1 | 코스닥 주가지수(2017년 상반기).xls | 2017-08-30 |

### 의견 및 질문

전체 8

현재 페이지 1/1

검색

| 번호 | 제목 |
| --- | --- |
| 1 | 신규 주식상장시 주가지수의 변화 |
| 2 | 신규 주식상장시 주가지수의 변화 |
| 3 | 2021년11월 코스닥지수 데이터 오타 |
| 4 | 2021년11월 코스닥지수 데이터 오타 |
| 5 | 안녕하세요 지수의 산출 관련하여 질문을 드립니다. |
| 6 | 안녕하세요 지수의 산출 관련하여 질문을 드립니다. |
| 7 | 산업의 성장과 주가 지수는 비례하나요? |
| 8 | 산업의 성장과 주가 지수는 비례하나요? |

글쓰기

1

현재 보고계신 지표서비스 내용에 어느정도 만족하시나요? 의견이 있으시면 자유롭게 작성하여 주세요. (한글 50자 이내)

- 0

0/50 평가하기

**평가자 정보**

ㆍ지표 서비스 관련 질문은 \[참여마당 > 질문과 답변(Q&A)\] 게시판을 이용해주세요.  
ㆍ제출한 평가내용을 수정 원하시면, \[여기\]를 클릭하여 주세요.$seed_49b3e1d3fe26$,
        'markdown',
        '49b3e1d3fe26cb541e3dbe3f6b7ff4d37239c86769af7737b019f4e9f13789b6',
        NULL,
        $seed_7768bfa7cdca${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/지표서비스  e-나라지표.md"}$seed_7768bfa7cdca$::jsonb
    ),
    (
        '2da2e793-94b4-5d5e-93b3-d16bce40372e',
        '056c80ef-0b54-501f-8091-90759dce9888',
        'user/mock-clipping-user',
        'c4ede23f-0c69-566b-ae1f-42dce315e96d',
        1,
        $seed_a1dfd7fbcf1d$토스 플레이스 api 키 발급받고싶어$seed_a1dfd7fbcf1d$,
        NULL,
        NULL,
        '2026-07-15'::date,
        $seed_56a1481847ac$Perplexity is a free AI-powered answer engine that provides accurate, trusted, and real-time answers to any question.$seed_56a1481847ac$,
        ARRAY[$seed_0a29fd363993$clippings$seed_0a29fd363993$]::text[],
        $seed_1f168d801858$"토스 플레이스 API"로 검색했을 때 명확한 API 키 발급 방법이 나오지 않았습니다. 아마 다음 중 하나일 것 같아요:

1. **토스페이먼츠 (결제) API** 를 찾으시는 경우
2. **토스플레이스 (POS 단말기)** 의 개발자 연동을 찾으시는 경우
3. **Google Places API** 와 혼동하셨을 가능성

가장 일반적인 경우인 **토스페이먼츠 결제 API 키** 발급 방법을 알려드릴게요:

## 토스페이먼츠 API 키 발급 방법docs.tosspayments+1

1. **개발자센터 가입**
	- URL: https://developers.tosspayments.com [developers.tosspayments](https://developers.tosspayments.com/)
		- 이메일 주소만으로 회원가입 가능 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
2. **전자결제 신청** (실제 결제 연동 시)
	- 신청 전에는 개발 연동 체험 상점의 **테스트 키** 만 확인 가능 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
		- 테스트 키: 실제 결제가 일어나지 않아 개발 연동 시 유용 [tosspayments](https://www.tosspayments.com/blog/articles/29831)
3. **API 키 확인**
	- 상점관리자 → 좌측 하단 **개발자 센터** 클릭 [tosspayments](https://www.tosspayments.com/blog/articles/29831)
		- 개발자센터 좌측 메뉴 → **API 키** 메뉴 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
		- 클라이언트 키 (SDK 초기화) 와 시크릿 키 (API 호출) 복사 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
4. **테스트 키 예시** (사업자 등록 전 사용 가능) [inflearn](https://www.inflearn.com/community/questions/1253630/%ED%86%A0%EC%8A%A4-%ED%8E%98%EC%9D%B4%EB%A8%BC%EC%B8%A0-%EA%B2%B0%EC%A0%9C%EC%9C%84%EC%A0%AF-%EC%97%B0%EB%8F%99-api-%ED%82%A4-%EB%B9%84%ED%99%9C%EC%84%B1%ED%99%94)
	```
	text
	clientKey: test_gck_docs_Ovk5rk1EwkEbP0W43n07xlzm
	secretKey: test_gsk_docs_OaPz8L5KdmQXkzRz3y47BMw6
	```

---

혹시 찾으시는 것이 **토스플레이스 (POS 단말기)** 의 특정 API라면, [https://tossplace.com/sector/plugin](https://tossplace.com/sector/plugin) 에서 개발 연동 가이드를 다운로드하거나 담당자와 연락해야 할 것 같아요.[tossplace](https://tossplace.com/sector/plugin)

어떤 API를 연동하려는 건가요? (예: 결제, POS 단말기 연동, 다른 서비스)

후속 조치

검색Computer

모델$seed_1f168d801858$,
        'markdown',
        '1f168d801858d8ca8c1242551a2294f0a21869e28be3a5ce64390608f0da0047',
        NULL,
        $seed_2b56346331a3${"frontmatter_format":"obsidian_web_clipper","seed":true,"source_filename":"dummy/clippings/토스 플레이스 api 키 발급받고싶어.md"}$seed_2b56346331a3$::jsonb
    )
ON CONFLICT (id) DO UPDATE SET
    source_event_id = EXCLUDED.source_event_id,
    title = EXCLUDED.title,
    author = EXCLUDED.author,
    published_at = EXCLUDED.published_at,
    clipped_on = EXCLUDED.clipped_on,
    description = EXCLUDED.description,
    tags = EXCLUDED.tags,
    raw_content = EXCLUDED.raw_content,
    content_format = EXCLUDED.content_format,
    content_hash = EXCLUDED.content_hash,
    object_uri = EXCLUDED.object_uri,
    source_metadata = EXCLUDED.source_metadata;

COMMIT;
