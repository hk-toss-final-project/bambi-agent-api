# LLM Wiki Vault 구조 명세

> **출처**: Obsidian vault `wiki/`의 실제 파일 55개와 `wiki/schema/config.md`를 분석해 정리했다.
> **목적**: 이 저장소의 `agent/wiki_builder/`가 생성해야 할 Vault 산출물의 목표 포맷을 기술한다.
> **상태**: 관찰 기록. 아직 구현과 합의된 계약이 아니다. §7의 차이 항목은 사용자 결정이 필요하다.

## 0. 전체 폴더 레이아웃

```text
wiki/
├── entities/        # 개체 페이지 (사람·조직·제품·장소 등)
├── concepts/        # 개념 페이지 (이론·방법·분야·용어 등)
├── sources/         # 원본(클리핑/노트) 1건당 요약 페이지 1개
├── schema/
│   └── config.md    # 아래 모든 규칙의 원본(governing spec)
├── index.md         # 전 페이지 자동 생성 디렉터리
└── log.md           # ingest/lint 오퍼레이션 append 로그
```

동작 모델: **source 1건이 ingest되면** LLM이 그 원본에서 entity·concept 페이지를 추출/생성하고, source 요약 페이지를 만들고, `index.md`와 `log.md`를 갱신한다. 페이지 종류는 3개(entity/concept/source)이고, index/log/schema는 이들을 관리하는 메타 파일이다.

---

## 1. 페이지 타입별 구조

세 타입은 frontmatter 키를 공유한다. 실측 빈도(총 55개 페이지):
`generation_complete` 57, `updated`/`type`/`tags`/`created`/`aliases` 각 55, `sources` 47, `source_file`/`contentHash` 각 8.

> `schema/config.md`의 템플릿과 실제 파일에 차이가 있다. 아래 표는 **실측 기준**이며, config.md에만 정의된 필드는 `config` 로 표기했다. 모델링 시 실측을 기본으로 두고 config-only 필드는 optional로 둔다.

### 1-1. Entity 페이지 (`entities/*.md`)

| 키 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `type` | `"entity"` 리터럴 | ✅ | 반드시 정확히 `entity` |
| `created` | ISO date | ✅ | 최초 생성일. 시스템이 채움(LLM 금지). merge 시 더 오래된 값 유지 |
| `updated` | ISO date | ✅ | 항상 현재 날짜로 시스템이 덮어씀 |
| `sources` | wiki-link 배열 | ✅ | 유래한 source 페이지들. append-only |
| `tags` | enum 배열 | ✅ | entity 서브타입 1개: `person`·`organization`·`project`·`product`·`event`·`place`·`other` |
| `aliases` | 문자열 배열 | optional | 번역·약어·다른 표기. append-only |
| `reviewed` | bool | `config` | true면 사람이 검증·보호. 이후 기존 내용 보존, 신규만 append |
| `generation_complete` | bool | 실측 | 생성 완료 플래그 |

**본문 섹션(순서 고정)**
1. `## Basic Information` — Type, Source 파일 링크
2. `## Description` — 3~6문장, 구체 사실, 양방향 링크
3. `## Related Entities` — `[[entities/…]]` (없으면 `(No related entities)`)
4. `## Related Concepts` — `[[concepts/…]]` (없으면 `(No related concepts)`)
5. `## Mentions in Source` — 원문 인용(§3)

### 1-2. Concept 페이지 (`concepts/*.md`)

Frontmatter는 entity와 동일하되 둘만 다름:
- `type`: `"concept"` 리터럴
- `tags`: concept 서브타입 enum — `theory`·`method`·`field`·`phenomenon`·`standard`·`term`·`other`

**본문 섹션(순서 고정)**
1. `## Definition` — 간결한 정의
2. `## Key Characteristics` — 정의적 특성 bullet
3. `## Applications` — 실제 활용 시나리오
4. `## Related Concepts` — `[[concepts/…]]`
5. `## Related Entities` — `[[entities/…]]`
6. `## Mentions in Source` — 원문 인용(§3)

> 실측 concept 파일은 본문에 `# 페이지명` H1이 하나 더 붙은 경우가 있다(entity는 없음). 파서는 선택적 H1을 허용해야 한다.

### 1-3. Source 페이지 (`sources/*.md`)

원본 1건 → 요약 페이지 1개. **파일명**: `슬러그_해시6자리.md` (예: `양양-검색-결과_4efb0d.md`).

| 키 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `type` | `"source"` 리터럴 | ✅ | |
| `created` / `updated` | ISO date | ✅ | 시스템이 채움 |
| `source_file` | wiki-link | 실측 | 원본 링크. 예: `[[Clippings/양양 검색 결과.md]]` |
| `tags` | 문자열 배열 | ✅ | **원본 노트 frontmatter에서 상속**(예: `clippings`). LLM이 추출 개념명으로 덮어쓰면 안 됨 |
| `aliases` | 문자열 배열 | optional | 번역·대체 제목 |
| `contentHash` | 문자열 | 실측 | 원본 내용 해시. 예: `20c2-bb30eb38` |
| `generation_complete` | bool | 실측 | |

**본문 섹션**
1. `## Source` — `Original file:` 링크, `Ingested:` 날짜
2. `## Core Content` (config: `## Summary`) — 2~4문장 요약, 인라인 `[[entities/…|표시명]]` 포함
3. `## Key Entities` (config: `## Key Points`) — 생성된 `[[entities/…]]` 목록
4. `## Key Concepts` (config: `## Mentioned Pages`) — `[[concepts/…]]` 목록

---

## 2. 메타 파일 구조

### 2-1. `index.md` — 자동 생성 디렉터리 (frontmatter 없음)

```text
# Wiki Index
> Auto-generated knowledge base directory
> Note: 백틱 안 텍스트는 alias(대체명·약어·번역)

## Entities
- [[entities/<slug>|<표시명>]] `aliases: A, B, C` - type: entity

## Concepts
- [[concepts/<slug>|<표시명>]] `aliases: …` - type: concept

## Sources
- [[sources/<slug_hash>|<표시명>]] `aliases: …`
```

- 섹션 3개: `## Entities`, `## Concepts`, `## Sources` — **Schema 섹션 없음, 개수 표기 없음**
- 각 줄: `- [[경로|표시명]]` + 선택적 `` `aliases: …` `` + 선택적 `` - type: … ``
- alias 없는 페이지는 백틱 블록 생략
- 일부 줄은 `` `generation_complete: true` `` 같은 다른 메타가 붙음 → 백틱 안을 `key: value` 자유 필드로 취급

### 2-2. `log.md` — 오퍼레이션 append 로그 (frontmatter 없음)

```text
<!-- llm-wiki-log-header-start -->
# Wiki Operation Log
(안내 문구)
---

## [YYYY-MM-DD HH:MM] ingest | <제목> · <소요초>s · <모델> · <크기>KB

**Created pages**：[[sources/…]], [[entities/…]], [[concepts/…]]

**Updated pages**：
```

블록 1건의 필드: 타임스탬프, 오퍼레이션(`ingest`/`lint`/maintenance), 대상 제목, 메트릭(소요 초·모델명·원본 KB), `Created pages`/`Updated pages` wiki-link 목록.
**구분자가 전각 콜론 `：`** 인 점에 주의.

### 2-3. `schema/config.md` — governing 설정

frontmatter: `version`(int), `updated`(date), `auto_suggestion_count`(int).
본문은 위 모든 규칙의 사람이 읽는 원본. **자동 생성 산출물이 아니라 사람이 편집하는 입력(설정)이다.**

---

## 3. Mentions in Source 포맷

```text
- "원어 그대로의 인용문 (선택적 번역)" — [[source-name|display-name]]
```
- 인용은 **반드시 verbatim** — 요약·의역·번역 금지
- source wiki-link 필수(머지 시 인용 출처 추적용)
- 같은 source의 여러 인용은 같은 블록에 개행으로 나열
- (실측 주의) 링크가 `[[|]]`로 비어 있는 깨진 케이스 존재 → 파서는 빈 링크를 허용/경고 처리

---

## 4. 공통 값 규칙 (enum·상수화 대상)

- **type**: `entity` | `concept` | `source`
- **entity 서브타입(tags)**: `person` `organization` `project` `product` `event` `place` `other`
- **concept 서브타입(tags)**: `theory` `method` `field` `phenomenon` `standard` `term` `other`
- **source 종류**(config): `document` `conversation` `note`
- **날짜**: `created`/`updated`는 시스템이 채움. LLM 값 신뢰 금지. created는 merge 시 older 유지, updated는 항상 현재
- **파일명**: 소문자-하이픈 슬러그. entity/concept 이름은 **원어 보존, 절대 번역 금지**
- **wiki-link**: 풀 경로 `[[entities/slug|표시명]]` / `[[concepts/slug|표시명]]`
- **유지보수 임계값**: stale = 90일 무갱신, contradiction 심각도 = `warning`|`conflict`|`error`, orphan = 인바운드 링크 0, missing = `[[링크]]`는 있으나 파일 없음

---

## 5. 머지·중복 정책

- `sources` 배열: append, 덮어쓰기 금지
- `aliases`: append, 기존 값 보존
- `reviewed: true`: 기존 내용 전부 보존, 진짜 신규만 append
- 모순: 양쪽 다 출처와 함께 보존, `## Contradictions` 섹션에 기록
- `NO_NEW_CONTENT`: 원본이 새 정보를 안 주면 이 신호 반환
- source `tags`: 원본 노트 값 상속만, LLM 개념명으로 오염 금지

---

## 6. 코드 생성 시 권장 산출물

1. **enum**: `PageType`, `EntitySubtype`, `ConceptSubtype`, `SourceKind`
2. **페이지 모델**: `EntityPage`, `ConceptPage`, `SourcePage` (공통 base + frontmatter 모델 분리)
3. **메타 모델**: `WikiIndex`(3 섹션 + 엔트리), `WikiLog`(헤더 + 오퍼레이션 블록), `SchemaConfig`
4. **값객체**: `WikiLink`(경로+표시명), `Mention`(인용문+번역?+source 링크)
5. **직렬화**: 모델 → 마크다운 렌더러 + Vault 파일 → 모델 파서(round-trip). 기존 `wiki/` 파일로 파서 검증 가능
6. **검증기**: tags 서브타입 화이트리스트, 섹션 순서, 빈 링크/깨진 링크 감지

---

## 7. `agent/wiki_builder/` 구현 상태

2026-07-15 개선으로 구현의 의미 모델을 DB 문서화 Wiki에서 **개인
지식 Wiki**로 변경했다. Entity는 사람·조직·프로젝트·제품·사건·장소를,
Concept은 이론·방법·분야·현상·표준·용어를 표현한다.

현재 구현은 Frontmatter, 고정 섹션, 풀 경로 Wiki Link,
`슬러그_해시6.md` source 파일, 3섹션 index, Block 형식 ingest log,
원본 tag 상속, verbatim 인용 검증, 별칭·출처 append-only 병합을
이 문서와 동일한 방향으로 생성한다.

DB MVP 계약에서 `schema/schema.md`는 Graph Snapshot으로 자동 생성하고,
DB 무결성 Hash는 SHA-256 64자를 유지한다. source/index/log는 현재
Build Artifact로 반환하며 실제 Vault 파일 Export는 별도 Adapter 범위다.

### 변경 전 구현과의 차이 기록

변경 전 구현(`vault.py`, `models.py`, `planner.py`, `llm_wiki.py`)은 **이
문서의 포맷과 다른 산출물을 만들었다.** 아래 표는 개선 이전 상태를
기록한 historical note다.

변경 전 구현은 **Agent DB 구조를 문서화하는 위키**였고, 이
문서가 기술한 Vault는 **개인 지식 위키**였다.

| 항목 | 변경 전 구현 (`vault.py`) | 실제 Vault (이 문서) |
|---|---|---|
| entity frontmatter | `title`, `type`, `domain`, `tags: [entity, {domain}]` | `type`, `created`, `updated`, `sources[]`, `tags:[서브타입]`, `aliases[]`, `generation_complete` |
| entity 섹션 | `# 이름` / 역할 / 주요 컬럼 / 관계 / 관련 개념 / 출처 | Basic Information / Description / Related Entities / Related Concepts / Mentions in Source |
| concept frontmatter | `title`, `type`, `tags: [concept]` | + `created`/`updated`/`sources`/`aliases`/`generation_complete`, `tags`는 서브타입 enum |
| concept 섹션 | `> 요약` / 설명(설계·트레이드오프) / 관련 엔티티 / 관련 개념 / 출처 | Definition / Key Characteristics / Applications / Related Concepts / Related Entities / Mentions in Source |
| **schema 방향** | `schema/schema.md` — **자동 생성 산출물** (Entities/Concepts/Relations 목록) | `schema/config.md` — **사람이 편집하는 입력(governing 규칙)** |
| wiki-link | `[[document_key]] 표시명` (경로 없음) | `[[entities/slug\|표시명]]` (풀 경로 + 파이프) |
| index | `_generated_at:_`, `## Entities (n)`, `## Schema` 섹션 있음 | 개수 없음, Schema 섹션 없음, 줄마다 `` `aliases: …` - type: … `` |
| sources 파일명 | `slugify(title)` | `슬러그_해시6.md` |
| sources 섹션 | 이 출처로 생성·갱신된 Entity / Concept | Source / Core Content / Key Entities / Key Concepts |
| log | 한 줄 pipe: `{ts} \| 출처: … \| entity 생성: … \| schema 재생성: 예` | 블록: `## [ts] ingest \| 제목 · 192s · gpt-4o-mini · 13.6KB` + `**Created pages**：` |
| slug | 이모지·`&`·`•` → `-` 로 치환 | 이모지 보존 (`여름-홋카이도-여행-브이로그🪻-…`) |
| content hash | SHA-256 64자 | `contentHash: 20c2-bb30eb38` (2파트 단축형), 파일명 접미사 6자 hex |

### 개선 시 확정한 항목

1. DB 문서화 Wiki가 아닌 개인 지식 Wiki 의미 모델을 사용한다.
2. `schema/schema.md`는 DB MVP의 Build Graph Snapshot으로 유지한다.
3. Entity는 `aliases`·Description·Mentions를 중심으로 표현하고 DB 컬럼 문서화 필드는 제거한다.
4. 이 문서를 개인 Wiki 생성 규칙과 구현 정합성의 기준으로 사용한다.

---

## 부록: 실측 샘플 위치

- vault 루트: `C:\Users\user\OneDrive\Desktop\test`
- entity 예: `wiki/entities/삿포로.md`
- concept 예: `wiki/concepts/일본여행.md`
- source 예: `wiki/sources/양양-검색-결과_4efb0d.md`
- 원본 클리핑 예: `Clippings/양양 검색 결과.md`
- governing 규칙: `wiki/schema/config.md`
- `2026-06-29.md`(데일리 노트)는 빈 파일이라 모델링 대상에서 제외
