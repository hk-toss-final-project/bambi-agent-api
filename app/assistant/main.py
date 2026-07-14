"""키워드 비서 웹 UI 전용 FastAPI 앱.

이 앱은 Agent API 서버(app.main:app)와 **별도의 프로세스·포트**로 실행되는
프론트 페이지 전용 애플리케이션이다. API 서버는 순수 API만 제공하고, 사람이
브라우저로 접속하는 비서 화면은 이 앱이 담당한다.

실행:
    uv run uvicorn app.assistant.main:app --port 8100
"""

from dotenv import load_dotenv
from fastapi import FastAPI

from app.assistant.web import assistant_router

# 자막·게시글 요약(OpenAI)에 필요한 OPENAI_API_KEY 등을 .env에서 로드한다.
load_dotenv()


def create_web_app() -> FastAPI:
    """키워드 비서 웹 UI만 제공하는 FastAPI 앱을 생성한다.

    API 문서(openapi/docs/redoc)는 이 프론트 앱에서 노출하지 않는다.
    """
    application = FastAPI(
        title="키워드 비서 AI",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.include_router(assistant_router)
    return application


app = create_web_app()
