---
title: "OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구"
source: "https://discuss.pytorch.kr/t/openwiki-cli/11089"
author:
  - "[[9bow]]"
published: 2026-07-06
created: 2026-07-14
description: "OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구1302×930 70.8 KB OpenWiki 소개 OpenWiki는 코드베이스의 문서를 자동으로 작성하고 최신 상태로 유지하는 CLI 도구로, 사람보다 코딩 에이전"
tags:
  - "clippings"
---
[![OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구](https://discuss.pytorch.kr/uploads/default/optimized/3X/f/2/f2272699ade92ca8fe4b369690c8979074ba3e1a_2_1028x734.png)

OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구1302×930 70.8 KB

](https://discuss.pytorch.kr/uploads/default/original/3X/f/2/f2272699ade92ca8fe4b369690c8979074ba3e1a.png "OpenWiki: 코딩 에이전트를 위한 코드베이스 문서를 작성하고 관리하는 CLI 도구")

## OpenWiki 소개

OpenWiki는 코드베이스의 문서를 자동으로 작성하고 최신 상태로 유지하는 CLI 도구로, 사람보다 코딩 에이전트가 읽는 것을 우선 목표로 설계되었습니다. LangChain과 LangGraph를 개발해 온 langchain-ai 조직이 공개했으며, 문서 생성부터 갱신, 에이전트 연동까지 명령 몇 개로 이어지는 구성이 특징입니다. 본 게시물에서는 OpenWiki의 동작 방식과 설치, 사용법을 정리합니다.

코딩 에이전트가 낯선 코드베이스에서 작업을 시작하면 매번 저장소 구조를 탐색하며 맥락을 다시 쌓아야 합니다. 잘 정리된 문서가 있으면 이 비용이 크게 줄지만, 사람이 손으로 쓰는 문서는 코드 변경을 따라가지 못하고 금세 낡아버립니다. OpenWiki는 이 문제를 LLM이 문서를 직접 쓰고 갱신하는 방식으로 접근합니다.

동작 방식은 단순합니다. 저장소에 위키가 없으면 `openwiki/` 디렉토리에 초기 문서를 생성하고, 이미 있으면 저장소 변경 사항을 반영해 문서를 갱신합니다. 여기에 하루 한 번 문서 업데이트 PR을 자동으로 여는 GitHub Action 예시까지 제공해, 문서가 코드를 따라가도록 만드는 순환 구조를 갖추고 있습니다.

[![OpenWiki의 문서화 흐름 요약, 설치부터 자동 갱신까지 4단계](https://discuss.pytorch.kr/uploads/default/optimized/3X/9/b/9bd956b619b726c640fa1f5dd617303fc6a0e5b8_2_1028x685.jpeg)

OpenWiki의 문서화 흐름 요약, 설치부터 자동 갱신까지 4단계1536×1024 241 KB

](https://discuss.pytorch.kr/uploads/default/original/3X/9/b/9bd956b619b726c640fa1f5dd617303fc6a0e5b8.jpeg "OpenWiki의 문서화 흐름 요약, 설치부터 자동 갱신까지 4단계")

## OpenWiki와 코딩 에이전트의 연동

OpenWiki가 다른 문서 생성 도구와 구별되는 지점은 에이전트 연동을 기본 동작으로 둔다는 점입니다. 실행하면 `AGENTS.md` 또는 `CLAUDE.md` 파일에 *"컨텍스트를 검색할 때 이 위키를 참조하라"* 는 안내를 자동으로 추가하고, 해당 파일이 없으면 새로 만들어 줍니다. 코딩 에이전트가 저장소에 진입했을 때 OpenWiki가 만든 문서를 컨텍스트 소스로 활용하도록 이어주는 것입니다.

첫 대화형 실행에서는 추론(inference) 제공자와 API 키, 사용할 LLM을 설정합니다. OpenRouter, Fireworks, Baseten, OpenAI, Anthropic을 기본 지원하고, GLM 5.2나 Kimi K2.6, Sonnet 5 같은 모델이 미리 정의되어 있으며 제공자별로 커스텀 모델 ID도 지정할 수 있습니다. LangSmith API 키를 설정하면 OpenWiki 실행 과정을 LangSmith 추적 프로젝트로 남길 수도 있습니다. 설정과 시크릿은 로컬의 `~/.openwiki/.env` 에 저장됩니다.

## OpenWiki 설치 및 사용법

npm으로 전역 설치한 뒤 초기화 명령으로 시작합니다.

```bash
npm install -g openwiki
openwiki --init
```

이후 사용법은 목적에 따라 나뉩니다. 인자 없이 실행하면 대화형 CLI가 열리고, 기본적으로 실행이 끝나도 세션이 유지되어 후속 요청을 이어서 보낼 수 있습니다.

```bash
# 대화형 CLI 시작
openwiki

# 초기 요청과 함께 시작
openwiki "Please generate documentation for this repository"

# 한 번 실행하고 종료 (비대화형)
openwiki -p "Summarize what you can do"

# 기존 문서 갱신
openwiki --update
```

문서를 자동으로 최신 상태로 유지하려면 저장소의 `.github/workflows/` 에 [openwiki-update.yml](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.yml?utm_source=pytorchkr&ref=pytorchkr) 예시 워크플로우를 추가합니다. 하루 한 번 문서 업데이트 PR을 자동으로 열어줍니다.

## OpenWiki의 라이선스

OpenWiki는 [MIT 라이선스](https://github.com/langchain-ai/openwiki/blob/main/LICENSE?utm_source=pytorchkr&ref=pytorchkr)로 공개되어 있어 개인 및 상업적 목적으로 자유롭게 사용할 수 있습니다.

## ![:github:](https://discuss.pytorch.kr/uploads/default/original/2X/7/70a6220c603eed42089b4f67366225849e119e20.svg?v=15 ":github:") OpenWiki GitHub 저장소

[github.com](https://github.com/langchain-ai/openwiki?utm_source=pytorchkr&ref=pytorchkr)

![](https://discuss.pytorch.kr/uploads/default/optimized/3X/1/6/16500e39818583dcac74a3934b89095503bfbc2d_2_695x347.png)

### [GitHub - langchain-ai/openwiki: OpenWiki is a CLI that writes and maintains agent...](https://github.com/langchain-ai/openwiki?utm_source=pytorchkr&ref=pytorchkr)

OpenWiki is a CLI that writes and maintains agent documentation for your codebase.

## 더 읽어보기

- [DeepWiki-Open: GitHub, GitLab 등의 저장소로부터 대화형 Wiki를 생성하는 오픈소스 DeepWiki 프로젝트](https://discuss.pytorch.kr/t/deepwiki-open-github-gitlab-wiki-deepwiki/7782)
- [Understand-Anything: 코드베이스를 인터랙티브 지식 그래프로 변환하는 Claude Code 플러그인](https://discuss.pytorch.kr/t/understand-anything-claude-code/9418)
- [Tutorial-Codebase-Knowledge, GitHub 저장소를 튜토리얼로 변환하는 도구 (feat. The Pocket)](https://discuss.pytorch.kr/t/tutorial-codebase-knowledge-github-feat-the-pocket/6827)
- [Wrinkl: AI가 프로젝트의 맥락을 파악하고, 코드 및 문서를 일관성있게 작성하도록 돕는 AI 맥락 관리 시스템](https://discuss.pytorch.kr/t/wrinkl-ai-ai/7217)

  
  

---

*이 글은 GPT 모델로 정리한 글을 바탕으로 한 것으로, 원문의 내용 또는 의도와 다르게 정리된 내용이 있을 수 있습니다. 관심있는 내용이시라면 원문도 함께 참고해주세요! 읽으시면서 어색하거나 잘못된 내용을 발견하시면 덧글로 알려주시기를 부탁드립니다.* ![:hugs:](https://discuss.pytorch.kr/images/emoji/fluentui/hugs.png?v=15 ":hugs:")

[![:pytorch:](https://discuss.pytorch.kr/uploads/default/original/2X/f/fa98c2196c22febe7475e503792febf39ba7a0de.svg?v=15 ":pytorch:")파이토치 한국 사용자 모임![:south_korea:](https://discuss.pytorch.kr/images/emoji/fluentui/south_korea.png?v=15 ":south_korea:")](https://pytorch.kr/)이 정리한 이 글이 유용하셨나요? [회원으로 가입](https://discuss.pytorch.kr/signup)하시면 주요 글들을 이메일![:love_letter:](https://discuss.pytorch.kr/images/emoji/fluentui/love_letter.png?v=15 ":love_letter:")로 보내드립니다! [텔레그램(Telegram)](https://t.me/pytorchkr?utm_source=pytorchkr&ref=pytorchkr)이나 [Slack/Discord/Teams/Dooray/GoogleChat 등](https://discuss-noti.pytorch.kr/)으로도 새 글 알림을 받으실 수 있습니다. ![:smiley:](https://discuss.pytorch.kr/images/emoji/fluentui/smiley.png?v=15 ":smiley:")

![:wrapped_gift:](https://discuss.pytorch.kr/images/emoji/fluentui/wrapped_gift.png?v=15 ":wrapped_gift:") 아래![:down_right_arrow:](https://discuss.pytorch.kr/images/emoji/fluentui/down_right_arrow.png?v=15 ":down_right_arrow:")쪽에 좋아요![:+1:](https://discuss.pytorch.kr/images/emoji/fluentui/+1.png?v=15 ":+1:")를 눌러주시면 새로운 소식들을 정리하고 공유하는데 힘이 됩니다~ ![:star_struck:](https://discuss.pytorch.kr/images/emoji/fluentui/star_struck.png?v=15 ":star_struck:")