"""Swagger UI와 OpenAPI 문서의 메타데이터 및 테마 전환 기능."""

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

OPENAPI_DESCRIPTION = """
LangGraph 기반 에이전트를 제공하는 Bambi Agent API입니다.

현재 MVP는 `service-api`와 `service-worker`가 호출하는 내부 API를 제공합니다.
내부 인증이 적용되기 전까지 API와 Swagger UI를 외부 네트워크에 노출하지 마세요.
""".strip()

OPENAPI_TAGS = [
    {
        "name": "system",
        "description": "프로세스 상태, 준비 상태와 애플리케이션 버전을 확인합니다.",
    },
    {
        "name": "service-api",
        "description": "Service API가 사용자 컨텍스트와 Agent Job을 관리할 때 사용합니다.",
    },
    {
        "name": "service-worker",
        "description": (
            "Service Worker가 발행 Snapshot을 단건·Batch로 조회하고 "
            "처리 결과를 전달할 때 사용합니다."
        ),
    },
]

DEVELOPMENT_OPENAPI_TAGS = [
    {
        "name": "dev-jobs",
        "description": "등록된 Agent Job을 개발 환경에서 즉시 실행합니다.",
    },
    {
        "name": "dev-wiki",
        "description": "Personal Wiki Builder를 개발 환경에서 직접 검증합니다.",
    },
    {
        "name": "dev-interests",
        "description": "개인 Wiki 기반 관심 키워드를 즉시 재계산합니다.",
    },
    {
        "name": "dev-global",
        "description": "관심 키워드로 최신 외부 자료를 수집하고 Global 문서로 저장합니다.",
    },
    {
        "name": "dev-bambi",
        "description": "개인 Wiki와 Global 최신 자료로 Bambi 콘텐츠를 즉시 생성합니다.",
    },
    {
        "name": "dev-scenarios",
        "description": "원본 저장부터 Bambi 콘텐츠까지 전체 흐름을 한 요청으로 실행합니다.",
    },
]


def build_openapi_tags(*, include_development: bool) -> list[dict[str, str]]:
    """실행 환경에 맞는 OpenAPI Tag 목록을 새 목록으로 반환한다."""
    tags = [dict(tag) for tag in OPENAPI_TAGS]
    if include_development:
        tags.extend(dict(tag) for tag in DEVELOPMENT_OPENAPI_TAGS)
    return tags

SWAGGER_UI_PARAMETERS: dict[str, bool | str] = {
    "displayRequestDuration": True,
    "filter": True,
    "operationsSorter": "method",
    "tagsSorter": "alpha",
}

SWAGGER_THEME_HEAD = """
<script>
(() => {
  const storageKey = "bambi-swagger-theme";
  let savedTheme = null;
  try {
    savedTheme = window.localStorage.getItem(storageKey);
  } catch (error) {
    savedTheme = null;
  }
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
  const initialTheme = savedTheme === "dark" || savedTheme === "light"
    ? savedTheme
    : systemTheme;
  document.documentElement.dataset.theme = initialTheme;
  document.documentElement.classList.toggle("dark-mode", initialTheme === "dark");
})();
</script>
<style>
:root {
  color-scheme: light;
}

html[data-theme="dark"] {
  color-scheme: dark;
}

#swagger-theme-toggle {
  position: fixed;
  top: 11px;
  right: 18px;
  z-index: 1000;
  min-width: 116px;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
  color: #1e293b;
  font: 600 13px/1.2 sans-serif;
  cursor: pointer;
  box-shadow: 0 2px 8px rgb(15 23 42 / 18%);
}

#swagger-theme-toggle:hover {
  border-color: #64748b;
}

#swagger-theme-toggle:focus-visible {
  outline: 3px solid #60a5fa;
  outline-offset: 2px;
}

html[data-theme="dark"],
html[data-theme="dark"] body {
  background: #0f172a;
}

html[data-theme="dark"] #swagger-theme-toggle {
  border-color: #475569;
  background: #1e293b;
  color: #f8fafc;
  box-shadow: 0 2px 8px rgb(0 0 0 / 45%);
}

html[data-theme="dark"] .swagger-ui,
html[data-theme="dark"] .swagger-ui .info .title,
html[data-theme="dark"] .swagger-ui .info p,
html[data-theme="dark"] .swagger-ui .info li,
html[data-theme="dark"] .swagger-ui .opblock-tag,
html[data-theme="dark"] .swagger-ui .opblock .opblock-summary-description,
html[data-theme="dark"] .swagger-ui .opblock-description-wrapper p,
html[data-theme="dark"] .swagger-ui .response-col_status,
html[data-theme="dark"] .swagger-ui table thead tr td,
html[data-theme="dark"] .swagger-ui table thead tr th,
html[data-theme="dark"] .swagger-ui .parameter__name,
html[data-theme="dark"] .swagger-ui .parameter__type,
html[data-theme="dark"] .swagger-ui .model-title,
html[data-theme="dark"] .swagger-ui .model,
html[data-theme="dark"] .swagger-ui label,
html[data-theme="dark"] .swagger-ui .tab li button.tablinks {
  color: #e2e8f0;
}

html[data-theme="dark"] .swagger-ui a,
html[data-theme="dark"] .swagger-ui .model-toggle::after {
  color: #60a5fa;
}

html[data-theme="dark"] .swagger-ui .topbar {
  background: #020617;
}

html[data-theme="dark"] .swagger-ui .scheme-container,
html[data-theme="dark"] .swagger-ui section.models,
html[data-theme="dark"] .swagger-ui .model-container,
html[data-theme="dark"] .swagger-ui .model-box,
html[data-theme="dark"] .swagger-ui .dialog-ux .modal-ux {
  background: #111827;
  color: #e2e8f0;
  box-shadow: 0 1px 4px rgb(0 0 0 / 55%);
}

html[data-theme="dark"] .swagger-ui section.models,
html[data-theme="dark"] .swagger-ui section.models .model-container,
html[data-theme="dark"] .swagger-ui .dialog-ux .modal-ux,
html[data-theme="dark"] .swagger-ui .dialog-ux .modal-ux-header {
  border-color: #334155;
}

html[data-theme="dark"] .swagger-ui input,
html[data-theme="dark"] .swagger-ui textarea,
html[data-theme="dark"] .swagger-ui select {
  border-color: #475569;
  background: #1e293b;
  color: #f8fafc;
}

html[data-theme="dark"] .swagger-ui .highlight-code > .microlight,
html[data-theme="dark"] .swagger-ui .opblock-body pre.microlight {
  background: #020617 !important;
  color: #e2e8f0 !important;
}

html[data-theme="dark"] .swagger-ui .opblock.opblock-get {
  border-color: #3b82f6;
  background: rgb(59 130 246 / 12%);
}

html[data-theme="dark"] .swagger-ui .opblock.opblock-post {
  border-color: #22c55e;
  background: rgb(34 197 94 / 12%);
}

html[data-theme="dark"] .swagger-ui .opblock.opblock-put {
  border-color: #f59e0b;
  background: rgb(245 158 11 / 12%);
}

html[data-theme="dark"] .swagger-ui .opblock.opblock-delete {
  border-color: #ef4444;
  background: rgb(239 68 68 / 12%);
}

html[data-theme="dark"] .swagger-ui .opblock.opblock-patch {
  border-color: #14b8a6;
  background: rgb(20 184 166 / 12%);
}

@media (max-width: 640px) {
  #swagger-theme-toggle {
    right: 8px;
    min-width: auto;
  }
}
</style>
"""

SWAGGER_THEME_TOGGLE_SCRIPT = """
<script>
(() => {
  const storageKey = "bambi-swagger-theme";
  const toggle = document.createElement("button");
  toggle.id = "swagger-theme-toggle";
  toggle.type = "button";
  toggle.setAttribute("aria-live", "polite");

  const updateToggle = (theme) => {
    const darkModeEnabled = theme === "dark";
    toggle.textContent = darkModeEnabled ? "☀ 라이트 모드" : "☾ 다크 모드";
    toggle.setAttribute("aria-pressed", String(darkModeEnabled));
    toggle.setAttribute(
      "aria-label",
      darkModeEnabled ? "라이트 모드로 전환" : "다크 모드로 전환",
    );
  };

  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark-mode", theme === "dark");
    updateToggle(theme);
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch (error) {
      // 저장소를 사용할 수 없는 브라우저에서도 현재 화면의 테마는 전환한다.
    }
  };

  toggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.dataset.theme;
    applyTheme(currentTheme === "dark" ? "light" : "dark");
  });

  updateToggle(document.documentElement.dataset.theme || "light");
  document.body.appendChild(toggle);
})();
</script>
"""


def build_swagger_ui_html(openapi_url: str, title: str) -> HTMLResponse:
    """다크·라이트 테마 전환 UI를 포함한 Swagger HTML을 생성한다."""
    response = get_swagger_ui_html(
        openapi_url=openapi_url,
        title=title,
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
    )
    html = response.body.decode("utf-8")
    html = html.replace("</head>", f"{SWAGGER_THEME_HEAD}</head>", 1)
    html = html.replace("</body>", f"{SWAGGER_THEME_TOGGLE_SCRIPT}</body>", 1)
    return HTMLResponse(content=html)


def register_swagger_ui(application: FastAPI, docs_url: str = "/docs") -> None:
    """OpenAPI가 활성화된 애플리케이션에 테마 전환 Swagger UI를 등록한다."""
    if application.openapi_url is None:
        return

    application.docs_url = docs_url

    async def swagger_ui(request: Request) -> HTMLResponse:
        """현재 배포 경로를 반영한 Swagger UI HTML을 반환한다."""
        root_path = request.scope.get("root_path", "").rstrip("/")
        return build_swagger_ui_html(
            openapi_url=f"{root_path}{application.openapi_url}",
            title=f"{application.title} - Swagger UI",
        )

    application.add_api_route(
        docs_url,
        swagger_ui,
        include_in_schema=False,
        name="swagger_ui_html",
    )
