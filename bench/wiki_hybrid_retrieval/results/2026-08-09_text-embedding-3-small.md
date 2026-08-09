# 개인 Wiki Hybrid 검색 벤치마크

- 실행 시각(UTC): 2026-08-09T14:34:04.296431+00:00
- Embedding 모델: `text-embedding-3-small` (1536 dimensions)
- 구현 버전(커밋): `c5e63ce+dirty`
- Recall 성공: 10/10 (100.0%)
- 평균 Embedding 지연: 912ms
- 추정 입력 토큰: 2030
- 추정 비용: $0.000041 ($0.02/1M tokens)
- 이전 결과: 없음(최초 실행)

| 케이스 | 결과 | 기대 | Vector top-3 | RRF top-3 | 지연(ms) |
|---|---:|---|---|---|---:|
| ko-weather-damage | PASS | heatwave | heatwave, dolphin, stock | heatwave, seoul, dolphin | 4824 |
| ko-typhoon-dolphin | PASS | dolphin | dolphin, heatwave, weather | dolphin, weather, heatwave | 729 |
| ko-onboarding-weather | PASS | heatwave, weather | weather, heatwave, seoul | weather, seoul, heatwave | 807 |
| ko-market-volatility | PASS | breaker | breaker, kosdaq, kospi | breaker, kospi, kosdaq | 419 |
| mixed-llm-wiki | PASS | graph, wiki | wiki, graph, entity | wiki, entity, graph | 512 |
| en-graph-retrieval | PASS | retrieval | retrieval, resolution, database | retrieval, database, resolution | 126 |
| ambiguous-agent | PASS | agent | agent, travel, model | agent, insurance, travel | 441 |
| long-distributed-query | PASS | consensus, distributed | consensus, distributed, observability | distributed, observability, consensus | 445 |
| semantic-hbm | PASS | hbm | hbm, semiconductor, battery | semiconductor, packaging, hbm | 385 |
| mixed-climate-datacenter | PASS | carbon, datacenter | datacenter, carbon, climate | datacenter, climate, carbon | 437 |
