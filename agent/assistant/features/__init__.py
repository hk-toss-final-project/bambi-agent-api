"""키워드 비서 기능 구현 패키지.

수집(feeds·youtube·reddit), 날짜 추출(dates), 임베딩(embeddings), 스코어링
(scoring), 클러스터링(clustering), 중복 제거(dedup), 원인 분류(outcomes),
선별 파이프라인(pipeline), 리서치 에이전트 그래프(graph), 보고서(report),
오케스트레이션(service)을 담는다.

외부 계층은 이 패키지를 직접 참조하지 않고 상위의 `api.py` facade를 통해
기능을 호출한다.
"""
