# 온디맨드 Wiki 1-hop·2-hop 결정적 비교

- 실행일: 2026-08-12
- 모델·Provider: 없음(결정적 WNAV-003 경로)
- Token·비용: 0
- 성공: 10/10
- 평균 Page Recall: 1-hop 0.693 → 2-hop 1.000
- 평균 Page Precision: 1-hop 0.980 → 2-hop 1.000
- Recall 개선 케이스: 9/10
- 평균 순회 지연: 1-hop 0.026ms → 2-hop 0.028ms

| 케이스 | 성공 | 1-hop 문서 | 2-hop 문서 | Recall | Precision |
|---|---:|---:|---:|---:|---:|
| simple-chain | Y | 2 | 3 | 0.67→1.00 | 1.00→1.00 |
| incoming-chain | Y | 2 | 3 | 0.67→1.00 | 1.00→1.00 |
| two-branches | Y | 3 | 5 | 0.60→1.00 | 1.00→1.00 |
| confidence-gate | Y | 2 | 3 | 0.67→1.00 | 1.00→1.00 |
| cycle-safe | Y | 2 | 3 | 0.67→1.00 | 1.00→1.00 |
| hop1-quota | Y | 5 | 6 | 0.67→1.00 | 0.80→1.00 |
| seed-budget-carry | Y | 4 | 6 | 0.67→1.00 | 1.00→1.00 |
| cumulative-confidence | Y | 4 | 6 | 0.67→1.00 | 1.00→1.00 |
| no-second-hop-regression | Y | 2 | 2 | 1.00→1.00 | 1.00→1.00 |
| two-seed-chains | Y | 4 | 6 | 0.67→1.00 | 1.00→1.00 |

이 수치는 정책·순회 로직만 비교한 micro benchmark다. 실제 사용자 Wiki의 DB
왕복, Report LLM 지연, Citation 정확도 개선을 뜻하지 않는다. Provider 품질 비교는
같은 온디맨드 주제 최소 10개를 1-hop·2-hop으로 각각 생성해야 하므로 비용 승인 후
별도로 실행한다.
