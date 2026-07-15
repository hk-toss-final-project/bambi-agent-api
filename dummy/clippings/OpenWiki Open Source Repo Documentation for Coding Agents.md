---
title: "OpenWiki: Open Source Repo Documentation for Coding Agents"
source: "https://www.langchain.com/blog/introducing-openwiki-an-open-source-agent-for-repo-documentation"
author:
  - "[[Brace Sproul]]"
published: 2026-07-02
created: 2026-07-14
description: "OpenWiki generates and maintains codebase documentation so coding agents can find the repo context they need without loading everything into one instruction file."
tags:
  - "clippings"
---
Today we're releasing OpenWiki, an open source agent and CLI for generating and maintaining documentation for codebases.

Agents write better code when they understand the repo they're working in. They need to know where key logic lives, how files connect, and which patterns the codebase expects. Good documentation gives agents that context, which leads to more informed code changes and fewer avoidable mistakes.

The problem is that documentation is hard to keep current. Writing the initial docs takes time, and updating them every time the code changes is even harder. In large repos with frequent PRs, docs can fall out of date quickly.

OpenWiki handles that work automatically. It creates a wiki for your repo, connects that wiki to your coding agent, and keeps it updated as your code changes.

## Why wikis for agents

We were inspired by existing work around codebase wikis, including [DeepWiki](https://deepwiki.com/), [AutoWiki](https://docs.factory.ai/cli/features/wiki/overview), and [Karpathy’s LLM Wiki](https://x.com/karpathy/status/2040470801506541998) concept. The shared idea is simple. A wiki gives humans and agents a structured way to understand a codebase without forcing all context into one giant file.

That matters because most coding agents already read files like `AGENTS.md` or `CLAUDE.md` for instructions. Those files are useful, but they’re not the right place to store hundreds of pages of repo documentation. They should point the agent toward the right context, then let the agent retrieve what it needs.

OpenWiki follows that model. It generates a repo wiki, then updates your agent instruction files with a reference to that wiki. From there, your coding agent can discover and use the docs automatically.

## Getting started

OpenWiki is designed to be easy to run from the command line.

Install it with npm:

```python
npm install -g openwiki
```

then run:

```python
openwiki --init
```
![](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a45549cd89555f7e03154f8_image%20(49).png)

The init command asks for a model provider and API key, then generates documentation for your repo.

OpenWiki supports both open and closed model providers, including OpenRouter, Fireworks, Baseten, OpenAI, and Anthropic. By default, it uses OpenRouter with an open model, but you can configure the provider that works best for your setup.

Because OpenWiki is built on top of [DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview), it also supports tracing to [LangSmith](https://langsmith.com/). If you provide a LangSmith API key, OpenWiki will trace runs to a LangSmith project so you can inspect exactly what the agent did while generating or updating your docs.

## How OpenWiki connects to your coding agent

After generating the wiki, OpenWiki updates your repo’s agent instruction files. If your repo uses `AGENTS.md`, `CLAUDE.md`, or both, OpenWiki adds a reference to the generated wiki and explains when the agent should use it.

We chose this approach because putting the entire wiki inside an instruction file would add too much context. In a large repo, the wiki can span hundreds of files. Loading all of that into every agent run would be wasteful and hard to maintain.

A short reference works better. Your coding agent already reads the instruction file. Once OpenWiki adds the reference, the agent can find the wiki when it needs repo context, without requiring you to change your workflow.

## Keeping the wiki up to date

Generating docs once is useful. Keeping them current is where OpenWiki becomes more valuable.

OpenWiki includes a [GitHub Action that can run on a schedule](https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.yml), for example once a day. The action runs OpenWiki with the update flag. OpenWiki checks which commits landed since the last run, uses git diffs to understand what changed, then updates the wiki with the relevant context.

That means the workflow can run in the background. As your codebase changes, OpenWiki updates the documentation. Your coding agent keeps picking up the latest wiki through the existing instruction file reference.

## Built for codebases first

This first release focuses on wikis for codebases. The goal is to make it easier for agents to understand the repos they work in, without asking developers to manually write and maintain detailed docs.

Over time, we think the OpenWiki concept can apply more broadly. Agents need durable context for many kinds of work, not just coding. Codebase documentation is the first use case, but the same pattern can help agents maintain useful context across other workflows too.

## Try it

OpenWiki is open source and available now.

You can install it, run `openwiki --init`, and generate a wiki for your repo in a few minutes.

Check out the repo here: [https://github.com/langchain-ai/openwiki](https://github.com/langchain-ai/openwiki)

## ⚠️ Potential Contradiction

**Source claim**: 문서화는 수동으로 작성하고 유지 관리하기 어렵다.

**Existing view**: OpenWiki는 코드 변경에 따라 문서를 자동으로 업데이트하는 메커니즘을 제공한다.

**Resolution suggestion**: 문서화의 유지 관리가 어렵다는 문제를 해결하기 위해 자동화된 업데이트 시스템(GitHub Action)을 도입했다.

---
*Flagged: 2026-07-14*