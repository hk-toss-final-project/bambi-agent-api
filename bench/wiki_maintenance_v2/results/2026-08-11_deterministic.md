# Wiki Maintenance V2 결정적 계획 벤치마크

- 실행일: 2026-08-11
- 모델·Provider: 없음(결정적 코드 경로)
- Token·비용: 0
- 성공: 10/10 (100.0%)

| 케이스 | 기대 | 실제 | 성공 |
|---|---|---|---:|
| healthy_snapshot | noop | noop | Y |
| missing_embeddings_only | repair_derivatives | repair_derivatives | Y |
| source_deleted_event | full_rebuild | full_rebuild | Y |
| no_active_sources | full_rebuild | full_rebuild | Y |
| missing_active_snapshot | full_rebuild | full_rebuild | Y |
| missing_activation_time | full_rebuild | full_rebuild | Y |
| legacy_snapshot_without_metrics | full_rebuild | full_rebuild | Y |
| source_newer_than_snapshot | full_rebuild | full_rebuild | Y |
| quality_error | full_rebuild | full_rebuild | Y |
| duplicate_documents | full_rebuild | full_rebuild | Y |
