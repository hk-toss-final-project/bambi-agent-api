# LLM 기능 벤치마크

대부분 `tests/`와 달리 실제 Provider를 호출하므로 자동 테스트나 CI에서 실행하지
않습니다. 각 실행기는 케이스별 결과, 지연시간, 토큰과 전달받은 단가 기준 예상
비용을 `results/`에 기록합니다. 실행 전에는 반드시 예상 호출 수와 비용 승인을
받습니다. `bench/ondemand_navigation/`처럼 Provider를 사용하지 않는 결정적 실행기는
비용 승인 없이 실행할 수 있으며 결과에 `Token·비용: 0`을 명시합니다.

온디맨드 전용 2-hop 정책은 같은 10개 Graph에서 기존 1-hop과 무료로 비교합니다.

```bash
uv run python bench/ondemand_navigation/run.py
```

```bash
uv run python bench/custom_topic_context/run.py --estimate-only
uv run python bench/custom_topic_context/run.py \
  --model gpt-4.1-mini \
  --input-cost-per-million <현재 단가> \
  --output-cost-per-million <현재 단가>
```

Report Builder Reader의 Navigator Tool 선택은 다음처럼 먼저 상한을 확인합니다.

```bash
uv run python bench/wiki_navigation/run.py --estimate-only
uv run python bench/wiki_navigation/run.py \
  --model gpt-4.1-mini \
  --input-cost-per-million <현재 단가> \
  --output-cost-per-million <현재 단가>
```

OpenAI Batch로 전환한 Wiki Embedding과 비긴급 Report 초안은 각각 다음처럼
예상 호출·Token 상한을 먼저 확인합니다. 실제 실행은 현재 단가를 명시하고 별도
승인을 받은 뒤 진행합니다.

```bash
uv run python bench/wiki_embedding_batch/run.py --estimate-only
uv run python bench/report_batch_generation/run.py --estimate-only
```

개인 Wiki 분류(`classify_source_for_wiki`)와 Report Builder 콘텐츠 생성
(`generate_report_content`)은 각각 다음처럼 먼저 상한을 확인합니다.

```bash
uv run python bench/wiki_builder/run.py --estimate-only
uv run python bench/wiki_builder/run.py \
  --model gpt-4.1-mini \
  --input-cost-per-million <현재 단가> \
  --output-cost-per-million <현재 단가>
```

```bash
uv run python bench/report_builder/run.py --estimate-only
uv run python bench/report_builder/run.py \
  --model gpt-4.1-mini \
  --input-cost-per-million <현재 단가> \
  --output-cost-per-million <현재 단가>
```
