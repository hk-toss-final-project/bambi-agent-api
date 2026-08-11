# Wiki Read V2 결정적 Seed 벤치마크

- 실행일: 2026-08-11
- 모델·Provider: 없음(결정적 코드 경로)
- Token·비용: 0
- 성공: 10/10 (100.0%)
- 평균 Page Precision: 0.900

| 케이스 | 성공 | 선택 Page | Precision |
|---|---:|---|---:|
| rank30_exact | Y | samsung | 1.000 |
| hardware_change | Y | current_gpu, past_gpu | 1.000 |
| recent_interest | Y | agents | 1.000 |
| evergreen_personal | Y | typing | 1.000 |
| english_query | Y | samsung_hbm | 1.000 |
| mixed_language | Y | vram | 1.000 |
| ambiguous_apple | Y | android_ai, apple_ai | 0.500 |
| no_relevant_wiki | Y | - | 1.000 |
| multi_page_relation | Y | agents, rag | 1.000 |
| source_recency | Y | datagrip_old, dbeaver_recent | 0.500 |
