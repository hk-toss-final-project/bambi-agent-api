# tests/ — 테스트 코드

pytest 기반 단위/통합 테스트 디렉터리입니다.

여기의 테스트는 **LLM API를 실제로 호출하지 않습니다.** 항상 무료로, 빠르게, 결정적으로 통과해야 합니다.
LLM이 필요한 부분은 mock으로 대체하고, 실제 LLM 품질 평가는 `bench/`에서 합니다.

## 실행

```bash
uv run pytest              # 전체 실행
uv run pytest tests/agent  # 특정 디렉터리만
uv run pytest -k <키워드>   # 이름으로 필터링
```

## 디렉터리 구조

소스 구조를 그대로 미러링합니다.

```
tests/
  conftest.py       # 공통 픽스처 (mock LLM, 테스트 클라이언트 등)
  agent/            # agent/ 코드 테스트
    test_graph.py
    nodes/
      test_<노드이름>.py
  app/              # app/ 코드 테스트
    routers/
      test_<라우터이름>.py
```

- 테스트 파일명은 `test_<대상파일이름>.py`로 맞춥니다.

## 작성 규칙

- **LLM 호출 금지**: LLM 클라이언트는 conftest의 mock 픽스처로 대체합니다. 네트워크가 끊긴 환경에서도 전체 테스트가 통과해야 합니다.
- **단위별 테스트**: 기능을 구현하면 같은 작업 단위 안에서 테스트를 함께 작성합니다. (루트 `AGENTS.md` 2번 규칙)
- **구현 모듈 미러링**: `api.py` facade가 아니라 `features/` 실제 구현 파일의 경로를 따라 테스트 파일을 배치합니다. 예: `domain/personal_wiki/documents/features/commands.py`는 `tests/domain/personal_wiki/documents/features/test_commands.py`에서 검증합니다.
- **API 테스트**: 엔드포인트는 FastAPI의 `TestClient`로 요청/응답을 검증합니다. 정상 응답뿐 아니라 검증 실패(422), 에러 응답도 확인합니다.
- **경계 케이스 포함**: 빈 입력, 긴 입력, 잘못된 타입 등 실패 경로를 함께 테스트합니다.
- **테스트도 코드 규칙을 따릅니다**: 파일 상단 한국어 주석, 테스트 함수에 무엇을 검증하는지 한국어 docstring을 작성합니다.
- 실제 API 키가 테스트 코드나 픽스처에 들어가지 않도록 합니다. 필요하면 가짜 값(`"test-key"`)을 사용합니다.
