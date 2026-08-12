# Wiki Builder · Report Builder 모델 비교 (재검증판)

> LLM 벤치마크 · bambi-agent-api · 2026-08-11 (재검증) · 브랜치 `experiment/llm-eval-langsmith`

`WIKI_LLM_MODEL`·`REPORT_LLM_MODEL` 기본값(gpt-4o-mini)이 최선인지 확인되지 않은 상태였다. 개인 Wiki 분류
(`classify_source_for_wiki`)와 리포트 생성(`generate_report_content`) 두 기능을 4개 후보 모델로 각각 실행해
정확도·지연시간·비용을 비교하고, LangSmith 트레이싱까지 함께 붙였다. 최초 12·10개 케이스로 1차 실행한 뒤,
케이스를 20·18개로 늘려 **재검증까지 마쳤다** — 아래 수치는 재검증판 기준이다.

## 한눈에 보기

| 항목 | 값 |
|---|---|
| 총 실행 비용 | $1.67 (재검증 8회 합산, 20+18 케이스 × 4모델) |
| 최저 정확도 | 60.0% — gpt-4o-mini · 위키 (20개 중 8개 오분류) |
| 최고 지연시간 | 54.9s — gpt-5 · 위키 (gpt-4.1 대비 약 9.5배, 정확도는 동일) |
| **권장 모델** | **gpt-4.1** (위키·리포트 공통) — gpt-5와 정확도 동률·근접, 비용·지연 훨씬 낮음 |

---

## 01. 배경

`WIKI_LLM_MODEL`, `REPORT_LLM_MODEL` 기본값(`gpt-4o-mini`)이 실제로 최선의 선택인지 확인이 안 된 상태였다.
모델 후보(gpt-4o-mini / gpt-4.1-mini / gpt-4.1 / gpt-5)를 같은 데이터셋으로 돌려 정확도·지연시간·비용을 비교했다.

## 02. 준비 작업

### LangSmith 트레이싱

`bambi-agent-api/.env`에 아래 값을 추가해 LangGraph/LangChain 실행이 LangSmith 대시보드로 자동 전송되도록
설정했다 (코드 수정 없이 환경변수만으로 동작).

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=<발급받은 키>
LANGCHAIN_PROJECT=bambi-wiki-report-eval
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

`.env.example`에는 값 없이 키 이름만 추가(AGENTS.md 시크릿 규칙 준수).

이어서 벤치 스크립트가 LLM을 호출할 때마다 `bench:wiki_builder`·`model:gpt-4.1-mini` 같은 태그를 LangSmith
Run에 자동으로 남기도록 했고, `--langsmith-experiment` 옵션을 추가해 `dataset.jsonl` 케이스를 LangSmith
Dataset으로 동기화하고 모델별 Experiment로 기록하도록 확장했다. LangSmith → **Tracing**에서 모델별 필터링이,
**Datasets & Experiments**에서 모델 간 나란한 비교가 가능하다.

**트레이스 분석 결과.** 기록된 Experiment의 Run 수를 LangSmith API로 직접 조회해 확인했다
(`Client.list_runs`). 모든 Experiment에서 **Run 수 = 케이스 수, 에러 0건** — 재시도가 한 번도 발생하지
않았다. `classify_source_for_wiki`·`generate_report_content` 모두 내부에서 `complete()`를 **정확히 1회**만
호출하는 단일 LLM 호출 구조라, 애초에 "노드별 병목"이 존재하지 않는다 — 전체 지연시간이 곧 그 LLM 호출
하나의 지연시간이다. 케이스별 지연시간 분포(p50 대비 max)는 최대 2배 정도 벌어져 있어 일부 느린 개별 호출은
있지만, 구조적 병목이 아니라 Provider 쪽 응답 변동으로 보인다.

### 벤치 하네스 신설

기존 `bench/topic_intent` 컨벤션을 따라 두 벤치를 새로 만들었다. 최초 12·10개 케이스로 1차 비교를 돌린 뒤,
통계적 신뢰도를 높이기 위해 각각 20·18개로 늘려 재검증했다(도구·개념 경계, 기존 항목 매칭, 영어 소스,
관심사 Bundle 다중 이웃, score 기반 근거 우선순위 등 다루지 못했던 경계 케이스 보강).

| 디렉터리 | 대상 함수 | 케이스 수 |
|---|---|---|
| `bench/wiki_builder/` | `classify_source_for_wiki` (`agent/wiki_builder/features/classification.py`) | 20 |
| `bench/report_builder/` | `generate_report_content` (`agent/report_builder/features/generation.py`) | 18 |

`build_incremental_wiki`/`rebuild_full_wiki`, `report_001~010` 같은 전체 오케스트레이션 진입점은 DB
트랜잭션에 깊게 의존해 벤치로 스텁하기 어려워, **실제 LLM 품질을 좌우하는 단일 함수**를 직접 호출하는
방식을 택했다.

```bash
uv run python bench/wiki_builder/run.py --estimate-only
uv run python bench/wiki_builder/run.py \
  --model gpt-4.1-mini --input-cost-per-million 0.40 --output-cost-per-million 1.60
uv run python bench/wiki_builder/run.py --model gpt-4.1-mini --langsmith-experiment

uv run python bench/report_builder/run.py --estimate-only
uv run python bench/report_builder/run.py \
  --model gpt-4.1-mini --input-cost-per-million 0.40 --output-cost-per-million 1.60
uv run python bench/report_builder/run.py --model gpt-4.1-mini --langsmith-experiment
```

**bench/report_generation/과의 중복 — 결론: 통합하지 않고 둘 다 유지.** `bench/report_generation/`은 main에
이미 커밋돼 있고 **2026-08-11 실측 실패 3건**(personal-only-signal, long-context, citation-boundary)이
들어있는 회귀 방지용 벤치다. 반면 `bench/report_builder/`는 이번 작업에서 만든 **모델 간 비교 전용** 벤치로,
`ReportContextDocument` 스키마(namespace_key·context_role·score 등)를 그대로 반영해 더 현실적인 근거 구조를
쓴다. 실측 실패 케이스를 지우거나 두 데이터셋을 합치는 건 이미 커밋된 팀 자산을 건드리는 일이라 사용자 승인
없이 진행하지 않았다 — 대신 역할을 분리해서 문서화한다: **report_generation = 회귀 방지**,
**report_builder = 모델 비교**.

## 03. 위키 분류 결과 (`classify_source_for_wiki` · 20 cases)

| 모델 | 정확도 | 평균 지연시간 | 입력/출력 토큰 | 예상 비용 |
|---|---:|---:|---|---:|
| gpt-4o-mini (기존 기본값) | 60.00% (12/20) | 4.31s | 24,832 / 6,186 | $0.0074 |
| gpt-4.1-mini | 80.00% (16/20) | 9.20s | 24,832 / 12,319 | $0.0296 |
| **gpt-4.1** | **90.00% (18/20)** | 5.76s | 24,832 / 13,133 | $0.1547 |
| gpt-5 | **90.00% (18/20)** | 54.95s | 24,812 / 89,581 | $0.9268 |

## 04. 리포트 생성 결과 (`generate_report_content` · 18 cases)

| 모델 | 정확도 | 평균 지연시간 | 입력/출력 토큰 | 예상 비용 |
|---|---:|---:|---|---:|
| gpt-4o-mini (기존 기본값) | 94.44% (17/18) | 3.42s | 23,622 / 3,929 | $0.0059 |
| gpt-4.1-mini | 94.44% (17/18) | 5.45s | 23,622 / 5,928 | $0.0189 |
| **gpt-4.1** | 94.44% (17/18) | **2.87s** | 23,622 / 5,133 | $0.0883 |
| gpt-5 | **100.00% (18/18)** | 27.60s | 23,604 / 40,876 | $0.4383 |

원본 실행 결과: `bench/wiki_builder/results/2026-08-11_*.md`, `bench/report_builder/results/2026-08-11_*.md`

## 05. 결론 및 권장

- **gpt-4o-mini는 재검증에서도 위키 분류 정확도가 가장 낮았다** (60.00%, 20개 중 8개 오분류) — 1차 결과
  (66.67%)보다 오히려 더 낮게 나와, 약점이 표본 노이즈가 아니라 실제 경향임을 재확인했다.
- **gpt-4.1이 gpt-5와 정확도가 동률·근접하면서 비용·지연시간은 훨씬 낮다.** 위키 분류에서 둘 다 90.00%로
  동률인데 gpt-4.1은 5.76초·$0.155, gpt-5는 54.95초·$0.927 — 지연 9.5배, 비용 6배 차이. 리포트 생성에서도
  gpt-4.1(94.44%, 2.87초)이 gpt-5(100.00%, 27.60초)에 근접한 정확도를 훨씬 적은 지연시간으로 낸다.
- **gpt-4.1-mini는 재검증에서 순위가 밀렸다.** 위키 분류 정확도 80.00%로 gpt-4.1(90.00%)에 못 미치고,
  지연시간(9.20초)은 오히려 gpt-4.1(5.76초)보다 길었다 — 1차 결과에서의 "균형점" 포지션이 표본이 늘어나며
  뒤집혔다.
- **리포트 생성은 gpt-4o-mini·gpt-4.1-mini·gpt-4.1 세 모델이 94.44%로 동률이지만, gpt-4.1이 지연시간이
  가장 짧다**(2.87초, 세 모델 중 최저) — 정확도가 같다면 속도로 고르는 게 합리적이다.

### 권장 변경안 (재검증 후 확정)

```
WIKI_LLM_MODEL=gpt-4.1      # gpt-5와 정확도 동률(90.00%), 비용 1/6·지연 1/9.5
REPORT_LLM_MODEL=gpt-4.1    # 동률 정확도(94.44%) 중 최저 지연시간(2.87초)
```

1차 결과에서는 gpt-4.1-mini를 위키 분류 균형점으로 권했지만, 케이스를 20개로 늘려 재검증하니 gpt-4.1이
정확도·지연시간 모두에서 gpt-4.1-mini를 앞섰다 — 표본이 작을 때는 순위가 뒤집힐 수 있다는 걸 보여주는
사례이기도 하다. **두 기능 모두 gpt-4.1 하나로 통일**하는 게 가장 단순하고 근거가 명확한 선택이다. gpt-5는
정확도 우위가 없거나(위키) 미미한 수준(리포트 +5.56%p)인데 비용·지연이 6~10배라 실서비스 기본값으로는
여전히 부적합하다고 판단 — "정확도 최우선" 고품질 온디맨드 경로(P1 이후)가 생기면 그때 재검토한다.

## 06. 한계

- **✅ 케이스 수 — 해결.** 12개·10개 → 20개·18개로 늘려 재검증했다. gpt-4.1-mini의 위키 분류 순위가 실제로
  뒤집히는 등(1차 2위 → 재검증 3위) 표본 확대가 결론을 바꿀 만큼 유효했다. 다만 20·18개도 여전히 통계적으로
  크지 않은 표본이라 — **신뢰 구간은 좁아졌지만 완전히 사라지지는 않았다.**
- **부분 해결 — 데이터셋은 여전히 새로 작성한 것이다.** 이번 재검증에서도 실사용 저장 데이터가 아니라 직접
  작성한 케이스를 썼다 — 이건 실제 프로덕션 트래픽 없이는 근본적으로 해결할 수 없는 한계라 "해결됨"으로
  표시하지 않는다. 실사용 데이터 기반 검증은 여전히 다음 단계로 남아있다.
- **✅ LangSmith 트레이스 분석 — 해결.** 02 준비 작업 섹션에 결과를 담았다: 모든 Experiment에서 Run 수 =
  케이스 수, 에러 0건이었고, 두 함수 모두 단일 LLM 호출 구조라 애초에 "노드별 병목"이 존재하지 않는다는 걸
  확인했다.

## 07. 다음 단계

1. **✅ 완료.** `bambi-agent-api/.env`·`.env.example`의 `WIKI_LLM_MODEL`/`REPORT_LLM_MODEL`을 재검증 결과에
   맞춰 `gpt-4.1`로 갱신했다. **단, `bambi-build`(배포용 docker-compose)는 별도 저장소·팀 공용 인프라
   자산이라 이 세션에서는 건드리지 않았다** — `bambi-build/.env.example`과 `docker-compose.yml`의 기본값
   (gpt-4o-mini)이 여전히 남아있어, 실제 배포 반영은 별도 PR로 진행해야 한다.
2. **✅ 완료(통합하지 않기로 결정).** `bench/report_builder/`와 `bench/report_generation/`은 역할이 다르다고
   판단해 둘 다 유지한다 — 02 준비 작업 섹션 참고.
3. **✅ 완료.** LangSmith API로 Run 수·에러·지연 분포를 직접 조회해 확인했다 — 02 준비 작업 섹션 참고. 단,
   이번에 늘어난 20·18개 케이스는 아직 LangSmith Dataset에 재동기화하지 않았다(기존 12·10개로 생성된
   Dataset이 남아있음) — 필요하면 `bambi-wiki-builder-classify`/`bambi-report-builder-generate` Dataset을
   삭제 후 `--langsmith-experiment`로 재생성한다.
4. **✅ 완료.** 케이스를 12·10개 → 20·18개로 늘려 재검증했고, 그 결과 권장 모델이 gpt-4.1-mini에서 gpt-4.1로
   바뀌었다.
5. **미완료 — 실사용 데이터 기반 재검증.** 지금까지 두 차례 모두 직접 작성한 합성 케이스였다. 실제 저장
   데이터로 만든 케이스가 있어야 이 벤치의 신뢰도를 한 단계 더 높일 수 있다.

---

*이번 재검증까지 포함한 총 API 비용은 약 $2.63 (1차 $0.93 + LangSmith 태그 검증 재실행 약 $0.03 + 재검증
$1.67)*
