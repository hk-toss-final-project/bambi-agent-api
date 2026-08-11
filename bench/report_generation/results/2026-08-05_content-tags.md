# Report Builder 생성 벤치마크 — 2026-08-05, gpt-4.1-mini

## 실행 배경

REPORT-010(콘텐츠 태그 생성)을 구현하면서 **생성 프롬프트를 수정**했다. 별도
LLM 호출을 두지 않고 본문 생성 응답에 `tags`를 함께 받는 방식이라, 프롬프트에
규칙 한 항목과 JSON 필드 하나가 늘었다. 프롬프트가 바뀌면 본문 품질이 조용히
달라질 수 있으므로 재실행한다(AGENTS.md 규칙 8).

| 항목 | 값 |
|---|---|
| 실행 날짜 | 2026-08-05 |
| 모델 | `gpt-4.1-mini` (temperature 0.3, 공유 클라이언트 기본값) |
| 데이터셋 | `dataset.jsonl` 10케이스 (변경 없음) |
| 프롬프트 | `report_builder_system.md` — 규칙 7 추가, JSON에 `tags` 추가 |
| 비용 | 1회 실행 ≈ **$0.01** |
| 결론 | **회귀 없음.** 10/10 통과, 인용 구성 동일. |

## 결과

| 지표 | 07-28 | **08-05** |
|---|---|---|
| 통과 | 10/10 | **10/10** |
| 인용 구성 | 전 케이스 P1·G1 | **전 케이스 P1·G1** |

케이스별 지연(ms): 2001 ~ 4007.

## 태그가 실제로 나오는지 별도 확인

`run.py`는 태그를 출력하지 않으므로(이번 변경 이전에 작성됨) 직접 호출로
확인했다.

```
주제: 의존성 구조
근거: P1 의존성 구조 / G1 DDD와 계층 분리

제목: 의존성 구조와 계층 분리의 중요성
인용: ('P1', 'G1')
태그: ('의존성 구조', '계층 분리', 'DDD', '의존성 역전')
```

4개, 전부 20자 이내, 본문이 실제로 다룬 주제어다.

**요청 주제(`의존성 구조`)가 태그에 그대로 포함됐다.** 프롬프트는 "요청 주제를
그대로 되풀이하기보다 하위 주제를 적으라"고 하지만 강제하지는 않는다. 협의 시
제시된 예시(`코스피` → `코스피 전망` 포함)도 같은 형태라 결함으로 보지 않는다.
코드에서 요청 주제를 제거할 수도 있으나, 그러면 주제가 곧 핵심어인 리포트에서
가장 중요한 태그가 빠진다.

## 이 벤치마크가 측정하지 못하는 것

07-28 기록의 한계가 그대로다. `run.py`는 `generate_report_content`를 직접 호출하고
근거 문서를 데이터셋에서 주입하므로, 검색·수집·품질 루프는 경로를 지나지 않는다.

이번 변경과 관련해 추가로 측정되지 않는 것:

| 대상 | 측정 |
|---|---|
| 생성 프롬프트 · P1/G1 인용 | ✅ |
| 태그 생성 여부·개수·길이 | ❌ `run.py`가 출력하지 않는다(위에서 수동 확인) |
| `normalize_content_tags` 정리 규칙 | ❌ 단위 테스트 4건이 담당 |
| 발행 페이로드 분리(`generation_topic`·`content_tags`) | ❌ 단위 테스트가 담당 |

**제안**: `run.py`가 케이스별 태그를 함께 출력하고, 개수·길이 위반을 집계하도록
확장하면 다음부터 회귀를 잡을 수 있다. 데이터셋 변경은 필요 없다.

## 관련 단위 테스트

- `test_content_tags_are_parsed_from_the_same_generation_response`
- `test_malformed_tags_do_not_fail_report_generation`
- `test_normalize_content_tags_applies_count_length_and_dedup_rules`
- `test_normalize_content_tags_drops_case_insensitive_duplicates`
- `test_publish_payload_separates_generation_topic_from_content_tags`
