-- 온보딩 정식 Topic의 결정론적 Wiki 컨텍스트와 사용자 추가 키워드의
-- 구조화 컨텍스트 캐시를 저장하고, 사용자별 활성 온보딩 원본을 하나로 제한한다.

BEGIN;

CREATE TABLE agent.onboarding_topic_contexts (
    taxonomy_version text NOT NULL,
    topic_id text NOT NULL,
    locale text NOT NULL DEFAULT 'ko-KR',
    canonical_name text NOT NULL,
    node_kind text NOT NULL DEFAULT 'concept'
        CHECK (node_kind IN ('entity', 'concept')),
    subtype text NOT NULL DEFAULT 'field',
    definition text NOT NULL,
    key_characteristics jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(key_characteristics) = 'array'),
    applications jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(applications) = 'array'),
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(aliases) = 'array'),
    related_topic_ids jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(related_topic_ids) = 'array'),
    content_version integer NOT NULL DEFAULT 1 CHECK (content_version > 0),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (taxonomy_version, topic_id, locale)
);

CREATE INDEX ix_onboarding_topic_contexts_enabled
    ON agent.onboarding_topic_contexts (taxonomy_version, locale, topic_id)
    WHERE enabled;

CREATE TABLE agent.user_custom_topic_contexts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    original_keyword text NOT NULL,
    normalized_keyword text NOT NULL,
    locale text NOT NULL DEFAULT 'ko',
    context_signature text NOT NULL CHECK (length(context_signature) = 64),
    canonical_name text NOT NULL,
    node_kind text NOT NULL CHECK (node_kind IN ('entity', 'concept')),
    subtype text NOT NULL,
    definition text NOT NULL,
    key_characteristics jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(key_characteristics) = 'array'),
    applications jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(applications) = 'array'),
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(aliases) = 'array'),
    search_terms jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(search_terms) = 'array'),
    possible_meanings jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(possible_meanings) = 'array'),
    resolution_kind text NOT NULL
        CHECK (resolution_kind IN (
            'taxonomy_alias', 'existing_wiki', 'llm_generated', 'generic_fallback'
        )),
    confidence numeric(5, 4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    model_name text,
    prompt_version text,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, user_id)
);

CREATE UNIQUE INDEX uq_user_custom_topic_contexts_active
    ON agent.user_custom_topic_contexts (
        user_id, normalized_keyword, locale, context_signature
    )
    WHERE status = 'active';

CREATE INDEX ix_user_custom_topic_contexts_lookup
    ON agent.user_custom_topic_contexts (
        user_id, normalized_keyword, locale, updated_at DESC
    )
    WHERE status = 'active';

-- 과거 구현은 선택이 바뀔 때마다 새 Head를 만들었다. 최신 Head만 활성으로 남기고
-- 나머지는 이력 보존용 superseded 상태로 전환한 뒤 활성 Head 유일성을 강제한다.
WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY namespace_key
            ORDER BY updated_at DESC, created_at DESC, id DESC
        ) AS position
    FROM agent.user_source_documents
    WHERE source_type = 'onboarding_seed'
      AND status = 'active'
      AND deleted_at IS NULL
)
UPDATE agent.user_source_documents AS document
SET
    status = 'superseded',
    deleted_at = COALESCE(deleted_at, clock_timestamp()),
    updated_at = clock_timestamp()
FROM ranked
WHERE document.id = ranked.id
  AND ranked.position > 1;

CREATE UNIQUE INDEX uq_user_source_documents_active_onboarding_seed
    ON agent.user_source_documents (namespace_key)
    WHERE source_type = 'onboarding_seed'
      AND status = 'active'
      AND deleted_at IS NULL;

INSERT INTO agent.onboarding_topic_contexts (
    taxonomy_version, topic_id, locale, canonical_name, node_kind, subtype,
    definition, key_characteristics, applications, aliases, related_topic_ids,
    content_version
) VALUES
('1.0.0-draft', 'ai_ml', 'ko-KR', 'AI·머신러닝', 'concept', 'field',
 '데이터에서 패턴을 학습해 예측·생성·의사결정을 수행하는 인공지능 기술과 그 활용을 다루는 분야다.',
 '["생성형 AI와 LLM", "모델 학습과 추론", "AI 에이전트", "책임 있는 AI"]',
 '["콘텐츠 생성", "업무 자동화", "검색과 추천", "소프트웨어 개발 지원"]',
 '["AI & Machine Learning", "인공지능", "머신러닝"]', '["programming", "data_cloud", "security"]', 1),
('1.0.0-draft', 'programming', 'ko-KR', '개발·프로그래밍', 'concept', 'field',
 '프로그래밍 언어와 프레임워크, 소프트웨어 설계, 테스트와 협업을 통해 제품을 만드는 방법을 다루는 분야다.',
 '["프로그래밍 언어", "프레임워크와 오픈소스", "소프트웨어 설계", "테스트와 유지보수"]',
 '["웹과 앱 개발", "자동화", "오픈소스 기여", "개발 생산성 개선"]',
 '["Software Development", "소프트웨어 개발", "코딩"]', '["ai_ml", "data_cloud", "security"]', 1),
('1.0.0-draft', 'data_cloud', 'ko-KR', '데이터·클라우드', 'concept', 'field',
 '데이터를 수집·저장·처리하는 시스템과 이를 안정적으로 운영하는 클라우드 인프라를 다루는 분야다.',
 '["데이터 파이프라인", "데이터베이스", "클라우드 인프라", "DevOps와 관측성"]',
 '["분석 플랫폼", "서비스 인프라", "데이터 처리 자동화", "확장 가능한 시스템 운영"]',
 '["Data & Cloud", "데이터 엔지니어링", "클라우드 컴퓨팅"]', '["programming", "ai_ml", "security"]', 1),
('1.0.0-draft', 'security', 'ko-KR', '보안·프라이버시', 'concept', 'field',
 '시스템과 데이터를 위협으로부터 보호하고 개인정보를 안전하게 처리하는 기술·정책·사고 대응을 다루는 분야다.',
 '["취약점과 공격", "인증과 접근 제어", "개인정보 보호", "보안 사고 대응"]',
 '["보안 설계", "위협 탐지", "규정 준수", "안전한 데이터 처리"]',
 '["Security & Privacy", "사이버 보안", "정보보호"]', '["programming", "data_cloud", "policy"]', 1),
('1.0.0-draft', 'gadget', 'ko-KR', '가젯·디바이스', 'concept', 'field',
 '스마트폰·컴퓨터·웨어러블 등 개인용 전자기기의 기술 변화와 사용 경험을 다루는 분야다.',
 '["제품 사양", "사용 경험", "생태계와 호환성", "신제품 비교"]',
 '["구매 비교", "업무와 생활 활용", "제품 리뷰", "기기 간 연동"]',
 '["Gadgets & Devices", "전자기기", "디지털 기기"]', '["mobility", "productivity", "ai_ml"]', 1),
('1.0.0-draft', 'mobility', 'ko-KR', '자동차·모빌리티', 'concept', 'field',
 '자동차와 전기차, 자율주행, 배터리, 이동 서비스 등 사람과 물류의 이동 변화를 다루는 분야다.',
 '["전기차", "자율주행", "배터리", "이동 서비스와 인프라"]',
 '["차량 기술 비교", "교통 서비스", "충전 인프라", "모빌리티 산업 분석"]',
 '["Cars & Mobility", "모빌리티", "미래차"]', '["industry", "climate", "gadget"]', 1),

('1.0.0-draft', 'startup', 'ko-KR', '스타트업·창업', 'concept', 'field',
 '새로운 문제와 시장을 발견해 제품·팀·사업 모델을 만들고 성장시키는 창업 활동을 다루는 분야다.',
 '["문제와 시장 검증", "제품 초기화", "투자 유치", "팀과 조직 성장"]',
 '["창업 전략", "사업 모델 설계", "초기 고객 확보", "투자 준비"]',
 '["Startups", "창업", "벤처"]', '["invest", "marketing", "leadership"]', 1),
('1.0.0-draft', 'invest', 'ko-KR', '투자·재테크', 'concept', 'field',
 '주식·채권·ETF·가상자산·연금 등 자산을 목표와 위험 수준에 맞게 운용하는 원리와 시장 정보를 다루는 분야다.',
 '["자산 배분", "위험과 수익", "시장 분석", "장기 재무 계획"]',
 '["포트폴리오 구성", "연금 관리", "기업과 자산 비교", "재무 목표 점검"]',
 '["Investing", "자산관리", "재테크"]', '["economy", "industry", "realestate"]', 1),
('1.0.0-draft', 'economy', 'ko-KR', '경제·금융', 'concept', 'field',
 '금리·환율·물가·고용·통화정책처럼 기업과 가계에 영향을 주는 거시경제와 금융 흐름을 다루는 분야다.',
 '["금리와 통화정책", "환율", "물가와 경기", "금융시장"]',
 '["경제 지표 해석", "정책 영향 분석", "시장 환경 이해", "기업 경영 환경 파악"]',
 '["Economy & Finance", "거시경제", "금융경제"]', '["invest", "industry", "policy"]', 1),
('1.0.0-draft', 'industry', 'ko-KR', '산업·기업', 'concept', 'field',
 '주요 산업의 구조와 경쟁, 기업 전략·실적·투자·공급망 변화를 다루는 분야다.',
 '["기업 전략과 실적", "산업 경쟁", "공급망", "인수합병과 투자"]',
 '["기업 분석", "산업 동향 파악", "경쟁 구도 비교", "공급망 위험 점검"]',
 '["Industry & Companies", "기업 분석", "산업 동향"]', '["economy", "invest", "startup"]', 1),
('1.0.0-draft', 'marketing', 'ko-KR', '마케팅·브랜드', 'concept', 'field',
 '고객의 필요를 이해하고 제품과 브랜드의 가치를 전달해 선택과 관계를 만드는 활동을 다루는 분야다.',
 '["고객과 시장 이해", "브랜드 포지셔닝", "채널과 캠페인", "성과 측정"]',
 '["브랜드 전략", "콘텐츠 마케팅", "고객 획득", "리텐션과 그로스"]',
 '["Marketing & Brand", "브랜딩", "그로스 마케팅"]', '["startup", "industry", "social"]', 1),
('1.0.0-draft', 'realestate', 'ko-KR', '부동산', 'concept', 'field',
 '주택과 상업용 부동산의 가격·수요·공급·금융·정책과 실제 거주·투자 의사결정을 다루는 분야다.',
 '["주택 시장", "청약과 거래", "임대차", "부동산 정책과 금융"]',
 '["주거 계획", "지역과 매물 비교", "정책 영향 파악", "부동산 자산 관리"]',
 '["Real Estate", "주택 시장", "부동산 시장"]', '["economy", "invest", "policy"]', 1),

('1.0.0-draft', 'job', 'ko-KR', '커리어·이직', 'concept', 'field',
 '직무 선택과 역량 개발, 채용·이직·면접·보상 협상을 포함한 개인의 경력 이동을 다루는 분야다.',
 '["직무와 역량", "채용 시장", "면접과 포트폴리오", "보상과 경력 전환"]',
 '["이직 준비", "경력 계획", "면접 대비", "개인 브랜드 구축"]',
 '["Career & Job Change", "커리어", "경력 개발"]', '["study", "productivity", "leadership"]', 1),
('1.0.0-draft', 'productivity', 'ko-KR', '생산성·업무도구', 'concept', 'field',
 '시간·정보·업무 흐름을 체계화하고 도구와 자동화를 활용해 더 효과적으로 일하는 방법을 다루는 분야다.',
 '["업무 흐름", "시간과 우선순위", "지식 관리", "도구와 자동화"]',
 '["반복 업무 자동화", "협업 개선", "개인 지식 관리", "집중과 일정 관리"]',
 '["Productivity & Tools", "업무 생산성", "워크플로"]', '["programming", "writing", "leadership"]', 1),
('1.0.0-draft', 'study', 'ko-KR', '공부·학습법', 'concept', 'field',
 '지식을 이해하고 기억하며 실제 문제에 적용하기 위한 학습 전략과 습관을 다루는 분야다.',
 '["학습 목표", "이해와 기억", "연습과 피드백", "학습 습관"]',
 '["자격증 준비", "언어 학습", "온라인 강의 활용", "장기 학습 계획"]',
 '["Learning", "학습법", "공부법"]', '["writing", "productivity", "job"]', 1),
('1.0.0-draft', 'writing', 'ko-KR', '글쓰기·기록', 'concept', 'field',
 '생각과 정보를 명확한 글로 표현하고 메모와 연결을 통해 지식을 축적하는 방법을 다루는 분야다.',
 '["아이디어 구조화", "문장과 서사", "메모와 노트", "지식 연결"]',
 '["업무 문서", "콘텐츠 작성", "개인 기록", "지식 관리 시스템"]',
 '["Writing & Note-taking", "글쓰기", "노트테이킹"]', '["study", "productivity", "book"]', 1),
('1.0.0-draft', 'leadership', 'ko-KR', '리더십·조직문화', 'concept', 'field',
 '사람과 팀이 공동 목표를 달성하도록 방향·의사결정·피드백·협업 환경을 만드는 방법을 다루는 분야다.',
 '["목표와 의사결정", "피드백과 코칭", "협업과 신뢰", "조직 운영"]',
 '["팀 관리", "원온원", "조직문화 설계", "변화 관리"]',
 '["Leadership & Culture", "조직문화", "매니지먼트"]', '["job", "productivity", "startup"]', 1),

('1.0.0-draft', 'space', 'ko-KR', '우주·천문', 'concept', 'field',
 '우주와 천체의 구조·기원·변화를 연구하고 탐사·위성·발사체 기술을 다루는 분야다.',
 '["천체와 우주론", "우주 탐사", "위성과 관측", "발사체와 우주 산업"]',
 '["천문 관측", "위성 서비스", "행성 탐사", "우주 산업 분석"]',
 '["Space & Astronomy", "우주과학", "천문학"]', '["physics_math", "climate", "industry"]', 1),
('1.0.0-draft', 'bio', 'ko-KR', '생명과학·의학', 'concept', 'field',
 '생명체의 구조와 기능, 질병의 원리, 진단·치료 기술과 의학 연구를 다루는 분야다.',
 '["유전자와 세포", "질병 기전", "신약과 임상시험", "생명공학"]',
 '["의학 연구 이해", "바이오 기술", "신약 개발", "건강 기술 평가"]',
 '["Life Science & Medicine", "바이오", "생명과학"]', '["medical", "brain", "nutrition"]', 1),
('1.0.0-draft', 'climate', 'ko-KR', '기후·환경', 'concept', 'field',
 '기후 변화와 생태계, 오염, 에너지 전환 및 인간 활동의 환경 영향을 다루는 분야다.',
 '["기후 변화", "탄소와 에너지", "생태계", "환경 정책과 기술"]',
 '["기후 위험 파악", "에너지 전환", "환경 영향 평가", "지속가능성 전략"]',
 '["Climate & Environment", "기후 환경", "환경과학"]', '["policy", "mobility", "industry"]', 1),
('1.0.0-draft', 'brain', 'ko-KR', '뇌과학·심리', 'concept', 'field',
 '뇌와 신경계, 인지·감정·동기·행동이 형성되는 원리와 심리 연구를 다루는 분야다.',
 '["뇌와 신경계", "인지와 기억", "감정과 동기", "행동과 의사결정"]',
 '["학습 이해", "행동 변화", "정신건강 연구", "사용자 경험 연구"]',
 '["Neuroscience & Psychology", "뇌과학", "심리학"]', '["mental", "study", "bio"]', 1),
('1.0.0-draft', 'physics_math', 'ko-KR', '물리·수학', 'concept', 'field',
 '자연 현상을 설명하는 물리 법칙과 패턴·구조·수량을 연구하는 수학적 사고를 다루는 분야다.',
 '["기초 물리 법칙", "수학적 모델", "양자와 입자", "증명과 문제 해결"]',
 '["과학 모델링", "공학 계산", "데이터 분석", "기초과학 연구"]',
 '["Physics & Math", "물리학과 수학", "기초과학"]', '["space", "ai_ml", "data_cloud"]', 1),

('1.0.0-draft', 'fitness', 'ko-KR', '운동·피트니스', 'concept', 'field',
 '체력·근력·심폐 능력·유연성을 높이고 신체 활동을 지속하는 방법을 다루는 분야다.',
 '["근력 운동", "유산소 운동", "유연성과 움직임", "훈련 계획과 회복"]',
 '["체력 향상", "운동 습관", "종목별 훈련", "부상 예방"]',
 '["Fitness", "운동", "체력 관리"]', '["nutrition", "sleep", "sports"]', 1),
('1.0.0-draft', 'nutrition', 'ko-KR', '식단·영양', 'concept', 'field',
 '음식과 영양소가 건강·에너지·신체 구성에 미치는 영향과 지속 가능한 식습관을 다루는 분야다.',
 '["영양소", "식사 구성", "혈당과 대사", "식습관과 지속 가능성"]',
 '["균형 식단", "운동 영양", "식품 선택", "생활 습관 관리"]',
 '["Nutrition & Diet", "영양", "식단 관리"]', '["fitness", "medical", "food"]', 1),
('1.0.0-draft', 'mental', 'ko-KR', '멘탈·스트레스', 'concept', 'field',
 '스트레스와 감정 상태를 이해하고 회복력과 마음 건강을 돌보는 일반적 방법을 다루는 분야다.',
 '["스트레스 반응", "감정 조절", "회복 탄력성", "마음챙김과 지원 체계"]',
 '["스트레스 관리", "번아웃 예방", "감정 기록", "도움 요청 판단"]',
 '["Mental Health", "정신건강", "마음 건강"]', '["brain", "sleep", "productivity"]', 1),
('1.0.0-draft', 'sleep', 'ko-KR', '수면·회복', 'concept', 'field',
 '수면의 질과 생체 리듬, 피로 회복 및 일상에서 회복을 지원하는 습관을 다루는 분야다.',
 '["수면 주기", "생활 리듬", "수면 환경", "피로와 회복"]',
 '["수면 습관 점검", "회복 루틴", "교대 생활 관리", "운동 후 회복"]',
 '["Sleep & Recovery", "수면 건강", "회복 관리"]', '["mental", "fitness", "medical"]', 1),
('1.0.0-draft', 'medical', 'ko-KR', '질환·의료정보', 'concept', 'field',
 '질환의 일반적 정보와 예방·검진, 의료 서비스와 제도를 이해하기 위한 정보를 다루는 분야다.',
 '["질환과 증상 정보", "예방과 검진", "의약품 안전", "의료 서비스와 정책"]',
 '["의료 정보 이해", "검진 준비", "진료 체계 파악", "공중보건 정보 확인"]',
 '["Medical Information", "의료정보", "건강 정보"]', '["bio", "policy", "mental"]', 1),

('1.0.0-draft', 'korea', 'ko-KR', '국내 이슈', 'concept', 'field',
 '한국에서 벌어지는 정치·행정·경제·사회·지역 사건과 공공 의제를 다루는 분야다.',
 '["정치와 행정", "사회 현안", "사건과 안전", "지역과 공공 의제"]',
 '["국내 뉴스 맥락 파악", "정책 영향 이해", "지역 이슈 확인", "사회 변화 추적"]',
 '["Korea News", "국내 뉴스", "한국 이슈"]', '["policy", "social", "media"]', 1),
('1.0.0-draft', 'world', 'ko-KR', '국제 정세', 'concept', 'field',
 '국가 간 외교·안보·무역·분쟁과 국제기구의 움직임을 통해 세계 질서의 변화를 다루는 분야다.',
 '["외교와 안보", "국제 분쟁", "무역과 제재", "국제기구와 협력"]',
 '["국가 관계 이해", "지정학 위험 파악", "무역 환경 분석", "국제 사건 추적"]',
 '["World Affairs", "국제 관계", "지정학"]', '["economy", "policy", "industry"]', 1),
('1.0.0-draft', 'policy', 'ko-KR', '정책·제도', 'concept', 'field',
 '정부와 공공기관이 사회 문제를 해결하기 위해 만드는 법·규제·제도와 그 영향을 다루는 분야다.',
 '["법과 규제", "정책 형성", "제도 변화", "이해관계자와 영향"]',
 '["법 개정 추적", "규제 영향 분석", "공공 서비스 이해", "정책 비교"]',
 '["Policy & Regulation", "공공정책", "법과 제도"]', '["korea", "social", "economy"]', 1),
('1.0.0-draft', 'social', 'ko-KR', '사회·노동', 'concept', 'field',
 '노동·일자리·인구·복지·불평등 등 공동체의 구조와 사람들의 삶에 영향을 주는 사회 문제를 다루는 분야다.',
 '["노동과 일자리", "인구 변화", "불평등", "복지와 사회 안전망"]',
 '["사회 지표 해석", "노동 환경 이해", "복지 제도 파악", "인구 변화 추적"]',
 '["Society & Labor", "사회 문제", "노동 이슈"]', '["policy", "korea", "leadership"]', 1),
('1.0.0-draft', 'media', 'ko-KR', '미디어·언론', 'concept', 'field',
 '뉴스와 콘텐츠가 생산·유통·소비되는 방식과 플랫폼, 여론, 정보 신뢰성을 다루는 분야다.',
 '["저널리즘", "플랫폼 유통", "여론 형성", "팩트체크와 정보 신뢰"]',
 '["뉴스 검증", "미디어 산업 분석", "정보 소비 습관", "플랫폼 변화 추적"]',
 '["Media & Journalism", "언론", "저널리즘"]', '["korea", "world", "marketing"]', 1),

('1.0.0-draft', 'movie_drama', 'ko-KR', '영화·드라마', 'concept', 'field',
 '영화와 드라마의 작품·창작자·산업·유통 플랫폼과 감상 문화를 다루는 분야다.',
 '["작품과 서사", "감독과 배우", "제작과 배급", "극장과 OTT"]',
 '["신작 탐색", "작품 해석", "산업 동향 파악", "감상 목록 관리"]',
 '["Film & TV", "영상 콘텐츠", "영화와 드라마"]', '["webtoon_anime", "music", "art_design"]', 1),
('1.0.0-draft', 'music', 'ko-KR', '음악', 'concept', 'field',
 '음악 작품과 아티스트, 장르, 공연, 음원 유통과 팬 문화를 다루는 분야다.',
 '["앨범과 곡", "아티스트와 장르", "공연과 페스티벌", "음원 산업"]',
 '["신보 탐색", "공연 정보 확인", "장르 이해", "플레이리스트 구성"]',
 '["Music", "음악 콘텐츠"]', '["movie_drama", "art_design", "media"]', 1),
('1.0.0-draft', 'book', 'ko-KR', '책·문학', 'concept', 'field',
 '책과 문학 작품, 작가, 출판 산업, 서평과 독서 문화를 다루는 분야다.',
 '["작품과 작가", "장르와 주제", "출판과 유통", "서평과 독서 경험"]',
 '["신간 탐색", "독서 목록 관리", "작품 해석", "출판 동향 파악"]',
 '["Books & Literature", "도서", "문학"]', '["writing", "art_design", "media"]', 1),
('1.0.0-draft', 'game', 'ko-KR', '게임', 'concept', 'field',
 '디지털 게임의 작품·플레이 경험·기술·업데이트·커뮤니티와 산업을 다루는 분야다.',
 '["게임 디자인", "플랫폼과 장르", "업데이트와 운영", "e스포츠와 커뮤니티"]',
 '["신작 탐색", "공략과 플레이 개선", "게임 산업 분석", "업데이트 추적"]',
 '["Games", "비디오 게임", "게임 산업"]', '["webtoon_anime", "gadget", "industry"]', 1),
('1.0.0-draft', 'webtoon_anime', 'ko-KR', '웹툰·애니', 'concept', 'field',
 '웹툰·만화·애니메이션 작품과 창작자, 연재·제작 구조, 원작 IP 확장을 다루는 분야다.',
 '["작품과 캐릭터", "연재와 제작", "플랫폼", "원작 IP와 미디어 확장"]',
 '["신작 탐색", "연재 일정 추적", "작품 해석", "IP 산업 분석"]',
 '["Webtoon & Anime", "웹툰과 애니메이션", "만화"]', '["movie_drama", "game", "art_design"]', 1),
('1.0.0-draft', 'art_design', 'ko-KR', '예술·디자인', 'concept', 'field',
 '미술·전시·건축·시각·제품·사용자 경험 디자인의 창작과 감상, 사회적 맥락을 다루는 분야다.',
 '["미술과 전시", "시각과 제품 디자인", "건축과 공간", "UX와 디자인 방법"]',
 '["전시 탐색", "디자인 사례 연구", "창작 영감", "사용자 경험 개선"]',
 '["Art & Design", "예술과 디자인", "디자인"]', '["movie_drama", "book", "home"]', 1),

('1.0.0-draft', 'travel', 'ko-KR', '여행', 'concept', 'field',
 '목적지와 이동·숙박·일정·현지 경험을 계획하고 이해하는 여행 정보를 다루는 분야다.',
 '["목적지와 계절", "교통과 숙박", "일정과 예산", "현지 문화와 안전"]',
 '["여행 계획", "항공과 숙소 비교", "현지 활동 탐색", "여행 기록"]',
 '["Travel", "여행 정보"]', '["food", "world", "writing"]', 1),
('1.0.0-draft', 'food', 'ko-KR', '음식·요리', 'concept', 'field',
 '식재료와 조리법, 음식 문화, 외식 경험과 맛을 만드는 원리를 다루는 분야다.',
 '["식재료", "조리법과 기술", "음식 문화", "외식과 맛집"]',
 '["레시피 활용", "식재료 선택", "맛집 탐색", "음식 기록"]',
 '["Food & Cooking", "요리", "음식"]', '["nutrition", "travel", "home"]', 1),
('1.0.0-draft', 'sports', 'ko-KR', '스포츠', 'concept', 'field',
 '경기·리그·선수·전술·기록과 스포츠 산업 및 팬 문화를 다루는 분야다.',
 '["경기와 기록", "선수와 팀", "전술과 훈련", "리그와 스포츠 산업"]',
 '["경기 일정과 결과 확인", "팀과 선수 추적", "전술 이해", "스포츠 관람"]',
 '["Sports", "스포츠 경기"]', '["fitness", "media", "industry"]', 1),
('1.0.0-draft', 'fashion_beauty', 'ko-KR', '패션·뷰티', 'concept', 'field',
 '의류·스타일·화장품·피부 관리와 브랜드 및 시즌별 소비 트렌드를 다루는 분야다.',
 '["스타일과 의류", "화장품과 성분", "피부 관리", "브랜드와 트렌드"]',
 '["제품 비교", "스타일링", "스킨케어 루틴", "시즌 트렌드 파악"]',
 '["Fashion & Beauty", "패션과 뷰티", "스타일"]', '["marketing", "art_design", "home"]', 1),
('1.0.0-draft', 'home', 'ko-KR', '홈·인테리어', 'concept', 'field',
 '주거 공간의 배치·가구·조명·수납·살림을 통해 생활 환경을 개선하는 방법을 다루는 분야다.',
 '["공간 배치", "가구와 조명", "정리와 수납", "살림과 유지관리"]',
 '["집 꾸미기", "수납 개선", "가구 선택", "생활 공간 관리"]',
 '["Home & Interior", "인테리어", "홈 스타일링"]', '["realestate", "art_design", "productivity"]', 1),
('1.0.0-draft', 'pet', 'ko-KR', '반려동물', 'concept', 'field',
 '반려동물의 건강·행동·훈련·영양·생활 환경과 보호자의 책임을 다루는 분야다.',
 '["건강과 예방", "행동과 훈련", "영양과 용품", "생활 환경과 복지"]',
 '["일상 돌봄", "훈련 계획", "건강 신호 관찰", "용품 선택"]',
 '["Pets", "반려동물 돌봄", "펫"]', '["medical", "nutrition", "home"]', 1);

ALTER TABLE agent.onboarding_topic_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.user_custom_topic_contexts ENABLE ROW LEVEL SECURITY;

CREATE POLICY onboarding_topic_context_read ON agent.onboarding_topic_contexts
    FOR SELECT USING (true);
CREATE POLICY onboarding_topic_context_write ON agent.onboarding_topic_contexts
    FOR ALL USING (agent.has_system_scope()) WITH CHECK (agent.has_system_scope());
CREATE POLICY user_custom_topic_context_isolation ON agent.user_custom_topic_contexts
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

CREATE TRIGGER set_onboarding_topic_contexts_updated_at
    BEFORE UPDATE ON agent.onboarding_topic_contexts
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_user_custom_topic_contexts_updated_at
    BEFORE UPDATE ON agent.user_custom_topic_contexts
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

INSERT INTO agent.schema_migrations (version, description)
VALUES (19, 'Seed contextual onboarding topics and custom topic cache');

COMMIT;
