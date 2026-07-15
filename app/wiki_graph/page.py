"""Obsidian 스타일 개인 Wiki Graph HTML 페이지.

외부 JavaScript 의존성 없이 SVG 기반 Force Graph, 검색·필터·Zoom·Pan·Drag와
Markdown 상세 패널을 제공한다. 지식 데이터는 PWIKI-003 API에서만 읽는다.
"""

import html
import json


_PAGE_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Bambi Wiki Graph</title>
  <style>
    :root {
      --bg: #17171b;
      --panel: rgba(31, 31, 37, .94);
      --panel-solid: #1f1f25;
      --panel-soft: #27272f;
      --border: #393943;
      --text: #ececf2;
      --muted: #9a99a8;
      --faint: #666572;
      --entity: #62d4bd;
      --concept: #a990ff;
      --accent: #8b78f6;
      --danger: #ff7c8f;
      --shadow: 0 18px 50px rgba(0, 0, 0, .35);
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
    body {
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }
    button, input { font: inherit; }
    button { color: inherit; }
    .shell { display: grid; grid-template-rows: auto 1fr; height: 100%; }
    .topbar {
      min-height: 68px;
      display: flex;
      align-items: center;
      gap: 18px;
      padding: 12px 18px;
      border-bottom: 1px solid var(--border);
      background: rgba(23, 23, 27, .92);
      backdrop-filter: blur(18px);
      z-index: 20;
    }
    .brand { display: flex; align-items: center; gap: 11px; min-width: 192px; }
    .brand-mark {
      width: 34px; height: 34px; display: grid; place-items: center;
      border-radius: 10px; color: white; font-weight: 800; letter-spacing: -.04em;
      background: linear-gradient(145deg, #9d8aff, #6450d8);
      box-shadow: 0 0 26px rgba(139, 120, 246, .28);
    }
    .brand-title { font-weight: 720; letter-spacing: -.025em; }
    .brand-subtitle { color: var(--muted); font-size: 11px; }
    .user-form { flex: 1; display: flex; align-items: center; gap: 8px; max-width: 620px; }
    .input-wrap { position: relative; flex: 1; }
    .input-wrap span { position: absolute; left: 12px; top: 9px; color: var(--faint); }
    input[type="text"], input[type="search"] {
      width: 100%; height: 38px; border-radius: 9px; border: 1px solid var(--border);
      color: var(--text); background: var(--panel-soft); outline: none;
      padding: 0 12px 0 34px; transition: border .15s, box-shadow .15s;
    }
    input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(139,120,246,.15); }
    .button {
      height: 38px; border: 1px solid var(--border); border-radius: 9px;
      padding: 0 14px; background: var(--panel-soft); cursor: pointer;
      transition: transform .12s, border .15s, background .15s;
    }
    .button:hover { border-color: #5b5969; background: #30303a; }
    .button:active { transform: translateY(1px); }
    .button.primary { border-color: transparent; background: var(--accent); font-weight: 650; }
    .button.primary:hover { background: #9b89ff; }
    .top-meta { margin-left: auto; color: var(--muted); font-size: 12px; white-space: nowrap; }
    .workspace { position: relative; min-height: 0; overflow: hidden; }
    .graph-stage {
      position: absolute; inset: 0; overflow: hidden;
      background-color: var(--bg);
      background-image: radial-gradient(rgba(163, 160, 182, .16) .7px, transparent .7px);
      background-size: 22px 22px;
    }
    #graph { width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }
    #graph.is-panning, #graph.is-dragging { cursor: grabbing; }
    .edge { stroke: #5b5968; stroke-width: 1.1; stroke-opacity: .52; transition: opacity .15s; }
    .edge.is-focus { stroke: #b8aaef; stroke-width: 1.8; stroke-opacity: .95; }
    .node { cursor: pointer; outline: none; }
    .node circle { stroke: #17171b; stroke-width: 2.5; transition: opacity .15s, filter .15s; }
    .node.entity circle { fill: var(--entity); }
    .node.concept circle { fill: var(--concept); }
    .node text {
      fill: #d8d7e1; font-size: 11px; font-weight: 570; pointer-events: none;
      paint-order: stroke; stroke: #17171b; stroke-width: 3px; stroke-linejoin: round;
    }
    .node.is-muted { opacity: .13; }
    .node.is-focus circle, .node:focus circle { stroke: white; filter: drop-shadow(0 0 8px rgba(180,165,255,.7)); }
    .node.is-neighbor circle { stroke: #aaa0df; }
    .toolbar {
      position: absolute; left: 16px; top: 16px; z-index: 8; width: min(330px, calc(100% - 32px));
      padding: 12px; border: 1px solid var(--border); border-radius: 13px;
      background: var(--panel); box-shadow: var(--shadow); backdrop-filter: blur(16px);
    }
    .search-row { display: flex; gap: 8px; }
    .search-row .input-wrap { min-width: 0; }
    .filters { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 10px; }
    .check { display: flex; align-items: center; gap: 7px; color: var(--muted); cursor: pointer; user-select: none; }
    .check input { accent-color: var(--accent); }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
    .dot.entity { background: var(--entity); }
    .dot.concept { background: var(--concept); }
    .toolbar-actions { display: flex; gap: 7px; margin-top: 11px; }
    .toolbar-actions .button { height: 32px; padding: 0 10px; font-size: 12px; }
    .stats {
      position: absolute; left: 16px; bottom: 16px; z-index: 8;
      display: flex; gap: 7px; flex-wrap: wrap; max-width: calc(100% - 32px);
    }
    .stat {
      min-width: 70px; padding: 7px 10px; border: 1px solid var(--border);
      border-radius: 9px; background: rgba(31,31,37,.86); backdrop-filter: blur(12px);
    }
    .stat strong { display: block; font-size: 15px; }
    .stat span { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
    .status {
      position: absolute; inset: 0; z-index: 7; display: grid; place-items: center;
      pointer-events: none;
    }
    .status[hidden] { display: none !important; }
    .status-card {
      max-width: 420px; margin: 20px; padding: 22px 24px; text-align: center;
      border: 1px solid var(--border); border-radius: 15px; background: var(--panel);
      box-shadow: var(--shadow); pointer-events: auto;
    }
    .status-card h2 { margin: 0 0 7px; font-size: 17px; }
    .status-card p { margin: 0; color: var(--muted); }
    .spinner {
      width: 24px; height: 24px; margin: 0 auto 12px; border: 2px solid #4b4958;
      border-top-color: var(--concept); border-radius: 50%; animation: spin .8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .detail {
      position: absolute; right: 0; top: 0; bottom: 0; z-index: 12; width: min(390px, 92vw);
      display: flex; flex-direction: column; border-left: 1px solid var(--border);
      background: var(--panel-solid); box-shadow: -22px 0 48px rgba(0,0,0,.3);
      transform: translateX(102%); transition: transform .22s ease;
    }
    .detail.is-open { transform: translateX(0); }
    .detail-head { padding: 18px 18px 14px; border-bottom: 1px solid var(--border); }
    .detail-top { display: flex; gap: 12px; align-items: flex-start; }
    .detail-title { flex: 1; min-width: 0; }
    .detail-title h2 { margin: 0; font-size: 20px; letter-spacing: -.035em; overflow-wrap: anywhere; }
    .path { margin-top: 4px; color: var(--muted); font: 11px ui-monospace, SFMono-Regular, monospace; }
    .icon-button {
      width: 32px; height: 32px; border: 1px solid var(--border); border-radius: 8px;
      background: var(--panel-soft); cursor: pointer;
    }
    .badges { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
    .badge { padding: 3px 8px; border-radius: 999px; background: #30303a; color: #c9c8d2; font-size: 11px; }
    .badge.entity { color: var(--entity); background: rgba(98,212,189,.1); }
    .badge.concept { color: #c0afff; background: rgba(169,144,255,.12); }
    .detail-body { overflow: auto; padding: 18px; }
    .section { margin-bottom: 22px; }
    .section h3 { margin: 0 0 8px; color: var(--muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    .section p { margin: 0; color: #d5d4de; white-space: pre-wrap; }
    .aliases { display: flex; flex-wrap: wrap; gap: 6px; }
    .relation-list { display: grid; gap: 6px; }
    .relation-button {
      width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 9px;
      border: 1px solid var(--border); border-radius: 8px; background: var(--panel-soft);
      text-align: left; cursor: pointer;
    }
    .relation-button:hover { border-color: #696678; }
    .relation-type { margin-left: auto; color: var(--muted); font-size: 10px; }
    pre {
      margin: 0; padding: 13px; overflow: auto; border: 1px solid var(--border);
      border-radius: 10px; background: #18181d; color: #cfced7;
      font: 12px/1.65 ui-monospace, SFMono-Regular, Menlo, monospace;
      white-space: pre-wrap; overflow-wrap: anywhere;
    }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
    @media (max-width: 760px) {
      .topbar { min-height: 112px; align-items: flex-start; flex-wrap: wrap; gap: 9px 12px; padding: 10px 12px; }
      .brand { min-width: 0; }
      .brand-subtitle, .top-meta { display: none; }
      .user-form { order: 3; flex-basis: 100%; max-width: none; }
      .toolbar { left: 10px; top: 10px; width: calc(100% - 20px); }
      .stats { left: 10px; bottom: 10px; }
      .detail { top: auto; width: 100%; height: 70%; border-left: 0; border-top: 1px solid var(--border); transform: translateY(102%); }
      .detail.is-open { transform: translateY(0); }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body data-user-id="__INITIAL_USER_ID__">
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">B</div>
        <div><div class="brand-title">Wiki Graph</div><div class="brand-subtitle">Personal knowledge map</div></div>
      </div>
      <form class="user-form" id="user-form">
        <label class="sr-only" for="user-id">사용자 ID</label>
        <div class="input-wrap"><span aria-hidden="true">@</span><input id="user-id" type="text" maxlength="128" required placeholder="사용자 ID"></div>
        <button class="button primary" type="submit">그래프 열기</button>
      </form>
      <div class="top-meta" id="version-label">Wiki version —</div>
    </header>
    <section class="workspace" aria-label="개인 Wiki 관계 그래프">
      <div class="graph-stage">
        <svg id="graph" role="application" aria-label="Entity와 Concept 관계 그래프" tabindex="0">
          <g id="viewport"><g id="edges"></g><g id="nodes"></g></g>
        </svg>
      </div>
      <aside class="toolbar" aria-label="그래프 검색 및 필터">
        <div class="search-row">
          <label class="sr-only" for="graph-search">Wiki 검색</label>
          <div class="input-wrap"><span aria-hidden="true">⌕</span><input id="graph-search" type="search" placeholder="제목, 별칭, subtype 검색"></div>
        </div>
        <div class="filters">
          <label class="check"><input id="filter-entity" type="checkbox" checked><span class="dot entity"></span>Entity</label>
          <label class="check"><input id="filter-concept" type="checkbox" checked><span class="dot concept"></span>Concept</label>
          <label class="check"><input id="filter-orphan" type="checkbox" checked>고립 Node</label>
        </div>
        <div class="toolbar-actions">
          <button class="button" id="fit-button" type="button">화면 맞춤</button>
          <button class="button" id="reheat-button" type="button">다시 펼치기</button>
        </div>
      </aside>
      <div class="stats" id="stats" aria-live="polite"></div>
      <div class="status" id="status"><div class="status-card"><div class="spinner"></div><h2>Wiki Graph 준비 중</h2><p>PostgreSQL에서 현재 지식 관계를 불러오고 있습니다.</p></div></div>
      <aside class="detail" id="detail" aria-label="Wiki 문서 상세" aria-hidden="true">
        <div class="detail-head">
          <div class="detail-top"><div class="detail-title"><h2 id="detail-title"></h2><div class="path" id="detail-path"></div></div><button class="icon-button" id="detail-close" type="button" aria-label="상세 패널 닫기">×</button></div>
          <div class="badges" id="detail-badges"></div>
        </div>
        <div class="detail-body">
          <section class="section"><h3>Summary</h3><p id="detail-summary"></p></section>
          <section class="section" id="aliases-section"><h3>Aliases</h3><div class="aliases" id="detail-aliases"></div></section>
          <section class="section"><h3>Connections</h3><div class="relation-list" id="detail-relations"></div></section>
          <section class="section"><h3>Markdown</h3><pre id="detail-markdown"></pre></section>
        </div>
      </aside>
    </section>
  </main>
  <script>
    (() => {
      "use strict";
      const apiPrefix = __API_PREFIX_JSON__;
      const svgNS = "http://www.w3.org/2000/svg";
      const graph = document.getElementById("graph");
      const viewport = document.getElementById("viewport");
      const edgesLayer = document.getElementById("edges");
      const nodesLayer = document.getElementById("nodes");
      const status = document.getElementById("status");
      const stats = document.getElementById("stats");
      const search = document.getElementById("graph-search");
      const entityFilter = document.getElementById("filter-entity");
      const conceptFilter = document.getElementById("filter-concept");
      const orphanFilter = document.getElementById("filter-orphan");
      const detail = document.getElementById("detail");
      const state = {
        data: null, nodes: [], edges: [], nodeMap: new Map(), positions: new Map(),
        transform: { x: 0, y: 0, scale: 1 }, selected: null, frame: null,
        alpha: 0, pan: null, drag: null
      };

      function element(name, attributes = {}) {
        const item = document.createElementNS(svgNS, name);
        Object.entries(attributes).forEach(([key, value]) => item.setAttribute(key, String(value)));
        return item;
      }

      function hash(text) {
        let value = 2166136261;
        for (let index = 0; index < text.length; index += 1) {
          value ^= text.charCodeAt(index); value = Math.imul(value, 16777619);
        }
        return value >>> 0;
      }

      function showStatus(title, message, loading = false) {
        status.hidden = false;
        status.replaceChildren();
        const card = document.createElement("div"); card.className = "status-card";
        if (loading) { const spinner = document.createElement("div"); spinner.className = "spinner"; card.append(spinner); }
        const heading = document.createElement("h2"); heading.textContent = title;
        const body = document.createElement("p"); body.textContent = message;
        card.append(heading, body); status.append(card);
      }

      function hideStatus() { status.hidden = true; }

      async function loadGraph(userId) {
        showStatus("Wiki Graph 불러오는 중", "현재 Entity·Concept와 관계를 조회하고 있습니다.", true);
        closeDetail();
        try {
          const response = await fetch(`${apiPrefix}/users/${encodeURIComponent(userId)}/wiki/graph`, { headers: { Accept: "application/json" } });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.message || `Graph API 오류 (${response.status})`);
          state.data = payload;
          document.getElementById("version-label").textContent = payload.wiki_version ? `Wiki version ${payload.wiki_version}` : "Wiki version —";
          history.replaceState(null, "", `/wiki-graph?user_id=${encodeURIComponent(userId)}`);
          buildVisibleGraph(true);
          if (!payload.nodes.length) showStatus("아직 연결할 Wiki가 없습니다", "클리핑 Worker를 실행해 Entity와 Concept을 먼저 생성해주세요.");
          else hideStatus();
        } catch (error) {
          state.data = null; clearGraph();
          showStatus("Graph를 불러오지 못했습니다", error instanceof Error ? error.message : "알 수 없는 오류가 발생했습니다.");
        }
      }

      function clearGraph() {
        if (state.frame) cancelAnimationFrame(state.frame);
        edgesLayer.replaceChildren(); nodesLayer.replaceChildren(); stats.replaceChildren();
        state.nodes = []; state.edges = []; state.nodeMap = new Map();
      }

      function buildVisibleGraph(resetPositions = false) {
        if (!state.data) return;
        const showEntity = entityFilter.checked;
        const showConcept = conceptFilter.checked;
        const showOrphan = orphanFilter.checked;
        state.nodes = state.data.nodes.filter(node =>
          (node.document_kind === "entity" ? showEntity : showConcept) && (showOrphan || node.degree > 0)
        );
        const visibleIds = new Set(state.nodes.map(node => node.id));
        state.edges = state.data.edges.filter(edge => visibleIds.has(edge.source) && visibleIds.has(edge.target));
        state.nodeMap = new Map(state.nodes.map(node => [node.id, node]));
        if (resetPositions) state.positions.clear();
        seedPositions(); renderGraph(); renderStats(); applySearch(); reheat(.85);
      }

      function seedPositions() {
        const width = graph.clientWidth || 1000; const height = graph.clientHeight || 700;
        state.nodes.forEach((node, index) => {
          if (state.positions.has(node.id)) return;
          const seed = hash(node.id); const angle = (index / Math.max(1, state.nodes.length)) * Math.PI * 2 + (seed % 100) / 100;
          const radius = 70 + Math.sqrt(index + 1) * 26;
          state.positions.set(node.id, { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius, vx: 0, vy: 0, fixed: false });
        });
      }

      function renderGraph() {
        edgesLayer.replaceChildren(); nodesLayer.replaceChildren();
        state.edges.forEach(edge => {
          const line = element("line", { class: "edge", "data-id": edge.id, "data-source": edge.source, "data-target": edge.target });
          edgesLayer.append(line); edge.element = line;
        });
        state.nodes.forEach(node => {
          const group = element("g", { class: `node ${node.document_kind}`, tabindex: "0", role: "button", "aria-label": `${node.title}, ${node.document_kind}, 연결 ${node.degree}개`, "data-id": node.id });
          const radius = Math.max(6, Math.min(15, 6 + Math.sqrt(node.degree + 1) * 2.1));
          const circle = element("circle", { r: radius });
          const label = element("text", { x: radius + 5, y: 4 });
          label.textContent = node.title.length > 28 ? `${node.title.slice(0, 27)}…` : node.title;
          group.append(circle, label);
          group.addEventListener("click", event => { event.stopPropagation(); selectNode(node.id); });
          group.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectNode(node.id); } });
          group.addEventListener("pointerdown", event => startNodeDrag(event, node.id));
          nodesLayer.append(group); node.element = group;
        });
        updatePositions();
      }

      function renderStats() {
        const entityCount = state.nodes.filter(node => node.document_kind === "entity").length;
        const conceptCount = state.nodes.length - entityCount;
        const items = [[state.nodes.length, "Nodes"], [state.edges.length, "Links"], [entityCount, "Entities"], [conceptCount, "Concepts"]];
        stats.replaceChildren(...items.map(([value, label]) => {
          const card = document.createElement("div"); card.className = "stat";
          const strong = document.createElement("strong"); strong.textContent = String(value);
          const span = document.createElement("span"); span.textContent = label;
          card.append(strong, span); return card;
        }));
      }

      function reheat(alpha = 1) {
        state.alpha = Math.max(state.alpha, alpha);
        if (state.frame) cancelAnimationFrame(state.frame);
        state.frame = requestAnimationFrame(simulate);
      }

      function simulate() {
        if (state.alpha < .012 || !state.nodes.length) { state.frame = null; return; }
        const positions = state.positions; const width = graph.clientWidth; const height = graph.clientHeight;
        const nodes = state.nodes;
        for (let i = 0; i < nodes.length; i += 1) {
          const a = positions.get(nodes[i].id); if (!a || a.fixed) continue;
          for (let j = i + 1; j < nodes.length; j += 1) {
            const b = positions.get(nodes[j].id); if (!b) continue;
            let dx = a.x - b.x; let dy = a.y - b.y; const distance2 = dx * dx + dy * dy + .1;
            const force = Math.min(4, (1500 * state.alpha) / distance2); const distance = Math.sqrt(distance2);
            dx /= distance; dy /= distance; a.vx += dx * force; a.vy += dy * force;
            if (!b.fixed) { b.vx -= dx * force; b.vy -= dy * force; }
          }
        }
        state.edges.forEach(edge => {
          const a = positions.get(edge.source); const b = positions.get(edge.target); if (!a || !b) return;
          const dx = b.x - a.x; const dy = b.y - a.y; const distance = Math.sqrt(dx * dx + dy * dy) || 1;
          const pull = (distance - 105) * .006 * state.alpha; const fx = (dx / distance) * pull; const fy = (dy / distance) * pull;
          if (!a.fixed) { a.vx += fx; a.vy += fy; } if (!b.fixed) { b.vx -= fx; b.vy -= fy; }
        });
        nodes.forEach(node => {
          const point = positions.get(node.id); if (!point || point.fixed) return;
          point.vx += (width / 2 - point.x) * .0008 * state.alpha; point.vy += (height / 2 - point.y) * .0008 * state.alpha;
          point.vx *= .86; point.vy *= .86; point.x += point.vx; point.y += point.vy;
        });
        state.alpha *= .972; updatePositions(); state.frame = requestAnimationFrame(simulate);
      }

      function updatePositions() {
        state.nodes.forEach(node => {
          const point = state.positions.get(node.id); if (point && node.element) node.element.setAttribute("transform", `translate(${point.x},${point.y})`);
        });
        state.edges.forEach(edge => {
          const a = state.positions.get(edge.source); const b = state.positions.get(edge.target);
          if (a && b && edge.element) { edge.element.setAttribute("x1", a.x); edge.element.setAttribute("y1", a.y); edge.element.setAttribute("x2", b.x); edge.element.setAttribute("y2", b.y); }
        });
      }

      function applyTransform() { viewport.setAttribute("transform", `translate(${state.transform.x},${state.transform.y}) scale(${state.transform.scale})`); }

      function startNodeDrag(event, nodeId) {
        if (event.button !== 0) return;
        event.stopPropagation(); graph.setPointerCapture(event.pointerId);
        const point = state.positions.get(nodeId); if (!point) return;
        state.drag = { id: nodeId, pointerId: event.pointerId }; point.fixed = true; graph.classList.add("is-dragging"); selectNode(nodeId);
      }

      function graphPoint(event) {
        const rect = graph.getBoundingClientRect();
        return { x: (event.clientX - rect.left - state.transform.x) / state.transform.scale, y: (event.clientY - rect.top - state.transform.y) / state.transform.scale };
      }

      function selectNode(nodeId) {
        const node = state.nodeMap.get(nodeId); if (!node) return;
        state.selected = nodeId;
        const neighborIds = new Set([nodeId]);
        state.edges.forEach(edge => { if (edge.source === nodeId) neighborIds.add(edge.target); if (edge.target === nodeId) neighborIds.add(edge.source); });
        state.nodes.forEach(item => { item.element?.classList.toggle("is-focus", item.id === nodeId); item.element?.classList.toggle("is-neighbor", item.id !== nodeId && neighborIds.has(item.id)); });
        state.edges.forEach(edge => edge.element?.classList.toggle("is-focus", edge.source === nodeId || edge.target === nodeId));
        renderDetail(node);
      }

      function closeDetail() {
        state.selected = null; detail.classList.remove("is-open"); detail.setAttribute("aria-hidden", "true");
        state.nodes.forEach(node => node.element?.classList.remove("is-focus", "is-neighbor")); state.edges.forEach(edge => edge.element?.classList.remove("is-focus"));
      }

      function badge(text, className = "") { const item = document.createElement("span"); item.className = `badge ${className}`; item.textContent = text; return item; }

      function renderDetail(node) {
        document.getElementById("detail-title").textContent = node.title;
        document.getElementById("detail-path").textContent = `${node.file_path} · v${node.version}`;
        const badges = document.getElementById("detail-badges"); badges.replaceChildren(badge(node.document_kind, node.document_kind), badge(node.subtype), badge(`${node.degree} links`));
        document.getElementById("detail-summary").textContent = node.summary || "요약이 없습니다.";
        const aliases = document.getElementById("detail-aliases"); aliases.replaceChildren(...node.aliases.map(value => badge(value)));
        document.getElementById("aliases-section").hidden = !node.aliases.length;
        document.getElementById("detail-markdown").textContent = node.markdown || "Markdown 본문이 없습니다.";
        const relations = document.getElementById("detail-relations");
        const connected = state.edges.filter(edge => edge.source === node.id || edge.target === node.id).map(edge => ({ edge, target: state.nodeMap.get(edge.source === node.id ? edge.target : edge.source) })).filter(item => item.target);
        if (!connected.length) { const empty = document.createElement("p"); empty.textContent = "연결된 문서가 없습니다."; relations.replaceChildren(empty); }
        else relations.replaceChildren(...connected.map(({ edge, target }) => {
          const button = document.createElement("button"); button.type = "button"; button.className = "relation-button";
          const dot = document.createElement("span"); dot.className = `dot ${target.document_kind}`;
          const label = document.createElement("span"); label.textContent = target.title;
          const type = document.createElement("span"); type.className = "relation-type"; type.textContent = edge.relation_type;
          button.append(dot, label, type); button.addEventListener("click", () => selectNode(target.id)); return button;
        }));
        detail.classList.add("is-open"); detail.setAttribute("aria-hidden", "false");
      }

      function applySearch() {
        const query = search.value.trim().toLocaleLowerCase();
        state.nodes.forEach(node => {
          const haystack = [node.title, node.document_key, node.subtype, ...node.aliases].join(" ").toLocaleLowerCase();
          node.element?.classList.toggle("is-muted", Boolean(query) && !haystack.includes(query));
        });
      }

      function fitGraph() {
        if (!state.nodes.length) return;
        const points = state.nodes.map(node => state.positions.get(node.id)).filter(Boolean);
        const minX = Math.min(...points.map(point => point.x)); const maxX = Math.max(...points.map(point => point.x));
        const minY = Math.min(...points.map(point => point.y)); const maxY = Math.max(...points.map(point => point.y));
        const width = graph.clientWidth; const height = graph.clientHeight; const contentWidth = Math.max(120, maxX - minX + 140); const contentHeight = Math.max(120, maxY - minY + 140);
        const scale = Math.max(.25, Math.min(1.6, Math.min(width / contentWidth, height / contentHeight)));
        state.transform = { x: width / 2 - ((minX + maxX) / 2) * scale, y: height / 2 - ((minY + maxY) / 2) * scale, scale }; applyTransform();
      }

      graph.addEventListener("pointerdown", event => {
        if (event.target.closest?.(".node") || event.button !== 0) return;
        graph.setPointerCapture(event.pointerId); state.pan = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, startX: state.transform.x, startY: state.transform.y }; graph.classList.add("is-panning");
      });
      graph.addEventListener("pointermove", event => {
        if (state.drag && state.drag.pointerId === event.pointerId) { const point = state.positions.get(state.drag.id); const cursor = graphPoint(event); if (point) { point.x = cursor.x; point.y = cursor.y; point.vx = 0; point.vy = 0; updatePositions(); } }
        if (state.pan && state.pan.pointerId === event.pointerId) { state.transform.x = state.pan.startX + event.clientX - state.pan.x; state.transform.y = state.pan.startY + event.clientY - state.pan.y; applyTransform(); }
      });
      graph.addEventListener("pointerup", event => {
        if (state.drag && state.drag.pointerId === event.pointerId) { const point = state.positions.get(state.drag.id); if (point) point.fixed = false; state.drag = null; graph.classList.remove("is-dragging"); reheat(.25); }
        if (state.pan && state.pan.pointerId === event.pointerId) { state.pan = null; graph.classList.remove("is-panning"); }
      });
      graph.addEventListener("pointercancel", () => { state.drag = null; state.pan = null; graph.classList.remove("is-dragging", "is-panning"); });
      graph.addEventListener("wheel", event => {
        event.preventDefault(); const rect = graph.getBoundingClientRect(); const mouseX = event.clientX - rect.left; const mouseY = event.clientY - rect.top;
        const oldScale = state.transform.scale; const newScale = Math.max(.2, Math.min(4, oldScale * Math.exp(-event.deltaY * .0012)));
        state.transform.x = mouseX - ((mouseX - state.transform.x) / oldScale) * newScale; state.transform.y = mouseY - ((mouseY - state.transform.y) / oldScale) * newScale; state.transform.scale = newScale; applyTransform();
      }, { passive: false });
      graph.addEventListener("click", event => { if (event.target === graph) closeDetail(); });
      document.getElementById("detail-close").addEventListener("click", closeDetail);
      document.getElementById("fit-button").addEventListener("click", fitGraph);
      document.getElementById("reheat-button").addEventListener("click", () => { state.positions.clear(); seedPositions(); reheat(1); });
      search.addEventListener("input", applySearch);
      [entityFilter, conceptFilter, orphanFilter].forEach(input => input.addEventListener("change", () => buildVisibleGraph(false)));
      document.getElementById("user-form").addEventListener("submit", event => { event.preventDefault(); const userId = document.getElementById("user-id").value.trim(); if (userId) loadGraph(userId); });
      window.addEventListener("resize", () => { if (state.nodes.length) fitGraph(); });
      const initialUserId = document.body.dataset.userId || "mock-clipping-user";
      document.getElementById("user-id").value = initialUserId; applyTransform(); loadGraph(initialUserId);
    })();
  </script>
</body>
</html>
"""


def render_wiki_graph_page(api_prefix: str, initial_user_id: str) -> str:
    """API Prefix와 초기 사용자 ID를 주입한 Wiki Graph HTML을 반환한다."""
    return _PAGE_TEMPLATE.replace(
        "__API_PREFIX_JSON__", json.dumps(api_prefix)
    ).replace("__INITIAL_USER_ID__", html.escape(initial_user_id, quote=True))
