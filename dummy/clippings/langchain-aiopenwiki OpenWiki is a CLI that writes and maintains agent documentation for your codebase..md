---
title: "langchain-ai/openwiki: OpenWiki is a CLI that writes and maintains agent documentation for your codebase."
source: "https://github.com/langchain-ai/openwiki"
author:
published:
created: 2026-07-14
description: "OpenWiki is a CLI that writes and maintains agent documentation for your codebase. - langchain-ai/openwiki"
tags:
  - "clippings"
---
## 오픈위키

OpenWiki는 코드베이스 또는 목적 기억을 위한 에이전트 위키를 작성하고 유지 관리하는 CLI 도구입니다. 에이전트에 특화되어 개발되었으며, 내장 커넥터 또는 Git 저장소를 통해 로컬 지식 소스를 가져와 로컬 위키로 통합할 수 있습니다.

[![오픈위키](https://raw.githubusercontent.com/langchain-ai/openwiki/main/static/openwiki.png)](https://raw.githubusercontent.com/langchain-ai/openwiki/main/static/openwiki.png)

## 설치하다

```
npm install -g openwiki
```

Windows에서는 OpenWiki를 Node.js 패키지 관리자(예: `npm` 또는 ) 를 사용하여 설치하는 것이 좋습니다 `pnpm`.

```
npm install -g openwiki
# or
pnpm add -g openwiki
```

`bun install -g openwiki` OpenWiki의 체크포인트 종속성 컴파일로 되돌아갈 수 있습니다 `better-sqlite3`. 이 방법을 사용하기 전에 Visual Studio 빌드 도구를 C++ 데스크톱 개발 워크로드와 함께 설치하십시오. Bun은 기본적으로 설치된 패키지의 수명 주기 스크립트를 실행하지 않으므로 해당 네이티브 종속성 빌드가 시작되기 전에 패키지 수준 경고를 표시할 수 없습니다.

## 빠른 시작

OpenWiki를 코드 모드로 초기화하고, 모델과 API 키를 구성한 다음, 문서를 생성하세요.

```
openwiki --init
```

오픈위키에는 두 가지 모드가 있습니다.

- **개인 모드는** `~/.openwiki/wiki` 로컬 저장소, Gmail, Notion, 웹 검색, Hacker News, X/Twitter와 같은 구성된 소스에서 로컬 개인 두뇌 위키를 구축합니다.
- **코드 모드는** `openwiki/` 현재 코드베이스에 대한 저장소 문서를 생성합니다.

코드 모드에서 실행하세요. 로컬 개인 브레인 위키를 사용 `openwiki --init` 하려면 또는 를 사용 하세요.`openwiki --update` `openwiki personal --init` `openwiki personal --update`

문서가 항상 최신 상태로 유지되도록 하려면 Git 공급자의 CI 워크플로를 추가하여 문서 업데이트와 함께 PR 또는 병합 요청이 자동으로 생성되도록 하세요.

- GitHub Actions: [openwiki-update.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.yml) 파일을. 으로 복사합니다 `.github/workflows/openwiki-update.yml`.
- GitLab CI: [openwiki-update.gitlab-ci.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.gitlab-ci.yml)`.gitlab-ci.yml` 파일을 GitLab 파이프라인 에 복사하거나 기존 파이프라인에 포함시키세요.
- Bitbucket Pipelines: [openwiki-update.bitbucket-pipelines.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.bitbucket-pipelines.yml) 파일을 복사한 `bitbucket-pipelines.yml` 다음, `openwiki-update` 저장소 설정 > 파이프라인 > 일정에서 사용자 지정 파이프라인을 예약하세요.

GitHub Actions에서 저장소 문서를 생성하려면 \`git add.git action\`을 사용하세요. CI 환경에서 `openwiki code --update --print` 실행할 필요는 없습니다. 워크플로에 필요한 공급자 및 모델 환경 변수가 제공되면 문서가 아직 존재하지 않는 경우 자동으로 초기 문서를 생성 합니다.`--init` `--update` `openwiki/`

## 용법

현재 저장소에 대해 코드 모드로 대화형 CLI를 시작합니다.

```
openwiki
```

OpenWiki를 처음 시작할 때 다음 요청을 입력하세요.

```
openwiki "Please generate documentation for this repository"
```

대신 대화형 로컬 개인 두뇌를 시작하세요:

```
openwiki personal
```

명령어 하나만 실행하고 종료하세요:

```
openwiki -p "Summarize what you can do"
```

OpenWiki 초기화:

```
openwiki --init
```

로컬 개인 두뇌 위키를 초기화합니다:

```
openwiki personal --init
```

저장소 코드 문서 업데이트:

```
openwiki --update
```

로컬 개인 두뇌 위키를 업데이트하세요:

```
openwiki personal --update
```

먼저 구성된 로컬 커넥터를 가져올 수 있는 업데이트를 실행하십시오.

```
openwiki personal --update "Refresh the wiki from configured connectors"
```

도움말 보기:

```
openwiki --help
```

채팅에서 다음 명령어를 사용하여 `/api-key` 현재 공급자 API 키를 업데이트하고 `/langsmith-key` LangSmith 추적 자격 증명을 업데이트하거나 삭제할 수 있습니다. 두 명령어 모두 마스크된 프롬프트를 사용합니다.

커넥터 제공업체를 인증합니다.

```
openwiki auth slack
openwiki auth gmail
openwiki auth x
openwiki auth notion
```

Slack OAuth용 ngrok 터널을 시작하세요:

```
openwiki ngrok start
```

이 명령은 임의의 HTTPS 포워딩 URL로 ngrok을 시작합니다. OpenWiki는 ngrok의 로컬 검사 API를 읽고, URL에 를 추가한 후 자동으로 `/callback` 저장합니다 `OPENWIKI_HTTPS_OAUTH_REDIRECT_URI`. 출력된 콜백 URL을 Slack에 등록하세요. 고정된 ngrok 도메인을 사용하는 경우, 를 실행하세요 `openwiki ngrok start https://<your-ngrok-domain>`. X/Twitter 및 Gmail 인증은 해당 HTTPS 재정의를 무시하고 로컬 루프백 콜백을 계속 사용합니다 `http://127.0.0.1:53682/callback`.

Bare는 `openwiki` 현재 저장소에 대해 코드 모드로 실행됩니다. `openwiki/` 위키가 존재하지 않는 경우 초기 저장소 문서를 생성합니다. `openwiki personal` 로컬 범용 위키에는 를 사용하십시오 `~/.openwiki/wiki/`. 기본적으로 CLI는 실행 후 계속 열려 있으므로 후속 메시지를 보낼 수 있습니다. 최종 어시스턴트 출력을 인쇄하는 일회성 비대화형 실행에는 `-p` 또는 를 사용하십시오.`--print`

기본 코드 모드로 실행하고 저장소 문서를 기반으로 작업합니다. 위치 모드를 사용 `openwiki --init` 하거나 로컬 개인 브레인 위키를 초기화 또는 업데이트할 수 있습니다.`openwiki --update` `personal` `--mode personal`

On each `code` run, `openwiki` maintains both an `AGENTS.md` and a `CLAUDE.md` at the repository root, adding prompting that instructs your coding agent to reference the wiki when searching for context. Each file is created if it does not already exist. If a file is present, OpenWiki only rewrites its own `<!-- OPENWIKI:START -->…<!-- OPENWIKI:END -->` block and leaves the rest of your content untouched (appending the block the first time). The scheduled GitHub Actions workflow includes these files, along with the workflow itself, in the documentation pull request.

On the first interactive run, OpenWiki will have you configure your inference provider, API key, and LLM. You will also be able to set a LangSmith API key to trace your OpenWiki runs to a LangSmith tracing project named "openwiki" (optional).

These configuration options and secrets will be saved to `~/.openwiki/.env` on your local machine.

## Local Connectors

OpenWiki's first-run onboarding offers connector setup for local Git repositories, Notion, Gmail, X/Twitter, Web Search, and Hacker News. During an ingestion run, deterministic connector tools write raw data and manifests under `~/.openwiki/connectors/<connector>/raw/`, then source-specific agent runs synthesize the local wiki under `~/.openwiki/wiki/` from those local files.

You can configure the same connector more than once. For example, add one Web Search source for AI research and another for NBA news; OpenWiki stores them as separate source instances such as `web-search-1` and `web-search-2`. Run all instances with `openwiki ingest all`, all instances for one connector with `openwiki ingest web-search`, or one instance with `openwiki ingest web-search-2`.

- `git-repo` reads configured local repository paths and writes compact manifests.
- `x` uses the X API directly with OAuth user-context credentials for home timeline, user posts, mentions, bookmarks, and list posts.
- `notion` targets the hosted Notion MCP server, so users should authenticate through Notion OAuth instead of pasting a Notion token into OpenWiki.
- `google` uses the Gmail API directly with OAuth user credentials to fetch recent mail, with room to add Drive, Calendar, and other Google providers later.
- `web-search` uses Tavily through LangChain and requires `TAVILY_API_KEY`.
- `hackernews` uses public Hacker News feed and search APIs, with no credentials required.

Connector secrets are referenced by env var name and stored in `~/.openwiki/.env`; connector config files should never contain raw secret values.

`openwiki auth <provider>` runs a local browser OAuth flow, saves returned tokens into `~/.openwiki/.env`, creates connector config when possible, and discovers MCP tools for MCP-backed providers. Slack and Gmail require app client credentials to already be set in that file; Notion uses dynamic client registration for hosted MCP; X uses OAuth 2.0 with PKCE. After `openwiki auth gmail`, the Google connector can ingest Gmail directly with no MCP transport setup.

`openwiki auth configure <provider>` and `openwiki auth tools <provider>` are advanced/retry commands for regenerating connector config or inspecting live MCP tools.

First-run onboarding also lets users choose a wiki template, customize its scope, and save per-source ingestion notes and source schedules in `~/.openwiki/onboarding.json`. The global personal wiki instructions are saved in `~/.openwiki/INSTRUCTIONS.md`. On macOS, source schedules are installed as user LaunchAgents under `~/Library/LaunchAgents/` and write logs under `~/.openwiki/logs/`.

See the OpenWiki operations docs for credential storage and provider setup notes.

## Customizing

OpenWiki supports OpenAI (with an API key or a ChatGPT login), OpenRouter, Fireworks, Baseten, NVIDIA NIM, an OpenAI-compatible provider, and Anthropic out of the box. The onboarding default is OpenAI with `gpt-5.6-terra`, and each inference provider also includes pre-defined model options plus support for custom model IDs.

### Alternative base URLs

To route the Anthropic provider at an alternative, Anthropic-compatible endpoint (for example a self-hosted or proxied gateway) instead of the default API, set `ANTHROPIC_BASE_URL` alongside `ANTHROPIC_API_KEY`:

```
OPENWIKI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=https://your-gateway.example.com/anthropic
```

### OpenAI-compatible endpoints

The `openai-compatible` provider targets any OpenAI-compatible chat-completions endpoint via a required base URL. This can be used for OpenAI-compatible LLM endpoints like those exposed by a LiteLLM gateway when it is used as a gateway — letting you reach whatever upstream providers the gateway fronts through a single OpenAI-shaped API. Set the model ID to whatever name the gateway exposes:

```
OPENWIKI_PROVIDER=openai-compatible
OPENAI_COMPATIBLE_API_KEY=your-gateway-key
OPENAI_COMPATIBLE_BASE_URL=https://your-gateway.example.com/v1
OPENWIKI_MODEL_ID=your-gateway-model-name
```

The `openai-chatgpt` provider calls OpenAI's Codex backend using your ChatGPT subscription instead of a metered API key. Model usage draws on your ChatGPT Plus/Pro/Team plan's included Codex usage rather than per-token API billing. It serves the same model list as the `openai` provider.

Instead of pasting an API key, run the setup wizard and complete a browser login:

```
OPENWIKI_PROVIDER=openai-chatgpt openwiki code --init
# or
OPENWIKI_PROVIDER=openai-chatgpt openwiki personal --init
```

The wizard opens `https://auth.openai.com` in your browser (and also prints the URL for headless/SSH use, where you can open it on another machine — or paste the redirect URL back into the terminal to finish without a callback). After you sign in with your ChatGPT account, OpenWiki captures the OAuth callback, shows the signed-in email and plan, and then continues to model and LangSmith selection just like the other providers. It stores the resulting access token, refresh token, expiry, account id, email, and plan in `~/.openwiki/.env` (`OPENAI_CHATGPT_ACCESS_TOKEN`, `OPENAI_CHATGPT_REFRESH_TOKEN`, `OPENAI_CHATGPT_EXPIRES_AT`, `OPENAI_CHATGPT_ACCOUNT_ID`, `OPENAI_CHATGPT_EMAIL`, `OPENAI_CHATGPT_PLAN`). These are managed for you — the access token is refreshed automatically when it expires, so you normally never edit them by hand. Treat the refresh token like a password.

Base URLs (and all credentials) can be set in your environment or stored in `~/.openwiki/.env`.

### Provider retry attempts

OpenWiki uses LangChain's built-in retry handling for transient provider errors. To override the number of retries after the first provider request, set `OPENWIKI_PROVIDER_RETRY_ATTEMPTS`:

```
OPENWIKI_PROVIDER_RETRY_ATTEMPTS=3
```

The value must be a positive integer. If the value is unset, OpenWiki defaults to 3 retries.

추가되었으면 하는 추론 제공자 또는 모델이 있다면 PR을 열어주세요!

## 기여하기

기여를 환영합니다! PR을 열기 전에 [CONTRIBUTING.md](https://github.com/langchain-ai/openwiki/blob/main/CONTRIBUTING.md) 파일을 꼭 읽어주세요. 저희는 PR의 범위를 하나의 변경 사항으로 엄격하게 제한하고 있으며, 관련 없는 변경 사항을 묶어 제출하는 PR은 분할 요청과 함께 닫힐 수 있습니다.