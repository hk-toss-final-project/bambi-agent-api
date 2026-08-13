<!-- LLM Provider 호출 사용량의 수집·분류·비용·조회 운영 계약을 설명한다. -->

# LLM 사용량 관측과 조회

`agent.usage_logs`는 LLM Provider 요청의 **시도 단위** 이력입니다. 동기 Chat,
Tool loop, Embedding과 OpenAI Batch 결과를 같은 형태로 저장해 업무별 Token,
예상 비용, 성공률, 재시도, 지연시간을 조회할 수 있습니다.

Prompt, 응답 본문, Wiki 원문, Report 본문은 저장하지 않습니다. Batch 결과를
적재할 때도 `llm_batch_items.request_body`, `context`, `result_body`를 사용량
로그로 복사하지 않습니다.

## 조회 축

업무는 `workload_type`, Provider 호출 종류는 `operation`으로 분리합니다.
따라서 Wiki 구축 중 Embedding처럼 두 축을 조합해 조회할 수 있습니다.

| 조회 항목 | workload_type | operation 예시 |
|---|---|---|
| LLM Wiki 구축 | `wiki_build` | `chat_completion`, `tool_completion`, `embedding` |
| LLM Wiki 유지보수 | `wiki_maintenance` | `chat_completion`, `tool_completion`, `embedding` |
| 아침 리포트 생성 | `report_morning` | `chat_completion`, `tool_completion` |
| 온디맨드 리포트 생성 | `report_on_demand` | `chat_completion`, `tool_completion`, `batch_generation` |
| 임베딩 전체 | 모든 업무 | `embedding` |

`personal_wiki_build` Job은 기본적으로 `wiki_build`이며, `trigger`가
`maintenance`이거나 기능이 `WBA-002`이면 `wiki_maintenance`입니다.
`report_generation` Job은 `generation_scope=WIKI_BRIEFING` 또는
`report_type=MORNING_BRIEFING`이면 `report_morning`, 나머지는
`report_on_demand`입니다. 알 수 없는 Job은 `other`로 보존해 누락을 숨기지
않습니다.

## 수집과 비용 계산

- 동기 Chat·Tool·Embedding은 Provider 재시도를 각각 한 Row로 저장합니다.
  같은 논리 호출은 `logical_call_id`, 시도 순서는 `attempt_number`로 묶습니다.
- Worker는 Job 완료와 실패 모두에서 수집한 Row를 한 번에 저장합니다. 사용량
  저장 실패는 본업 결과를 실패시키지 않고 경고 로그로 남깁니다.
- OpenAI Batch는 결과 JSONL의 Item별 Token을 저장합니다. Provider가 Item별
  레이턴시를 주지 않으므로 Batch Row의 `latency_ms`는 `NULL`이며 지연시간
  평균·P95 집계에서 제외합니다.
- 비용은 활성 `model_configs` 가격 버전으로 계산하고 호출 Row의
  `pricing_snapshot`에 단가를 고정합니다. 가격이 없으면 임의로 0원 처리하지
  않고 `estimated_cost=NULL`, `cost_status=unknown`으로 남깁니다.
- 금액은 USD 기준 예상치입니다. 실제 청구액과의 차이는 Provider 청구 내역으로
  별도 대사해야 합니다.

새 모델이나 가격 변경은 기존 설정을 덮어쓰지 않고 새 `model_configs.version`을
활성화하는 방식으로 반영합니다. 공개 가격의 출처 URL과 Batch 할인율도 설정의
`parameters` 및 각 사용량 Row의 Snapshot에 남깁니다.

## 조회 예시

기간·업무·호출 종류·사용자를 선택적으로 필터링하는 애플리케이션 조회는
`infrastructure.persistence.api.summarize_usage_logs`를 사용합니다. 호출자는
조회 전에 해당 요청의 RLS Scope를 설정해야 합니다.

업무별 총량은 다음처럼 확인할 수 있습니다.

```sql
SELECT
    workload_type,
    operation,
    provider,
    model_name,
    count(*) AS calls,
    sum(input_tokens) AS input_tokens,
    sum(output_tokens) AS output_tokens,
    sum(estimated_cost) AS known_cost_usd,
    count(*) FILTER (WHERE cost_status = 'unknown') AS unknown_cost_calls,
    round(avg(latency_ms), 1) AS avg_latency_ms
FROM agent.usage_logs
WHERE occurred_at >= :started_at
  AND occurred_at < :ended_at
GROUP BY workload_type, operation, provider, model_name
ORDER BY workload_type, operation, provider, model_name;
```

Wiki 유지보수 중 임베딩만 조회하려면 두 축을 함께 사용합니다.

```sql
SELECT
    count(*) AS calls,
    sum(input_tokens) AS input_tokens,
    sum(estimated_cost) AS known_cost_usd
FROM agent.usage_logs
WHERE occurred_at >= :started_at
  AND occurred_at < :ended_at
  AND workload_type = 'wiki_maintenance'
  AND operation = 'embedding';
```

재시도와 실패는 논리 호출별로 확인할 수 있습니다.

```sql
SELECT
    logical_call_id,
    max(attempt_number) AS attempts,
    array_agg(status ORDER BY attempt_number) AS attempt_statuses,
    array_agg(error_code ORDER BY attempt_number) AS error_codes
FROM agent.usage_logs
WHERE occurred_at >= :started_at
  AND occurred_at < :ended_at
GROUP BY logical_call_id
HAVING max(attempt_number) > 1
    OR bool_or(status = 'failed');
```

운영 지표에서 `sum(estimated_cost)`만 표시하면 가격 미등록 호출이 빠질 수
있습니다. 따라서 비용과 함께 `unknown_cost_calls`를 항상 노출합니다.
