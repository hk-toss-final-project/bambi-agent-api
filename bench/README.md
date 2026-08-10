# LLM 기능 벤치마크

`tests/`와 달리 실제 Provider를 호출하므로 자동 테스트나 CI에서 실행하지 않습니다.
각 실행기는 케이스별 결과, 지연시간, 토큰과 전달받은 단가 기준 예상 비용을
`results/`에 기록합니다. 실행 전에는 반드시 예상 호출 수와 비용 승인을 받습니다.

```bash
uv run python bench/custom_topic_context/run.py --estimate-only
uv run python bench/custom_topic_context/run.py \
  --model gpt-4.1-mini \
  --input-cost-per-million <현재 단가> \
  --output-cost-per-million <현재 단가>
```
