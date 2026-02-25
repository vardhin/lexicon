<!--
  WADebugWidget.svelte — WhatsApp DOM Inspector / Debug tool.

  Fetches a DOM snapshot from the WhatsApp organ (via Brain HTTP relay)
  and displays it as an interactive tree. You can:
    - Browse the DOM tree of the WhatsApp page
    - See tag names, classes, IDs, attributes
    - Test CSS selectors and see how many elements match
    - See what the monitor.js scanner currently identifies as:
      sidebar items, contact names, messages, previews, etc.
    - Highlight elements by sending highlight commands back to the organ

  Communication:
    monitor.js → POST /whatsapp/debug → Brain stores snapshot
    This widget → GET /whatsapp/debug → renders tree + selector tester
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  let snapshot = null;
  let selectorQuery = '';
  let selectorResults = [];
  let selectorCount = 0;
  let scanReport = null;
  let loading = true;
  let error = null;
  let autoRefresh = false;
  let refreshTimer = null;
  let expandedPaths = new Set();
  let activeTab = 'tree'; // 'tree' | 'selector' | 'scan' | 'raw'
  let maxDepth = 4;
  let filterTag = '';

  const BRAIN = 'http://127.0.0.1:8000';

  onMount(() => {
    fetchSnapshot();
  });

  onDestroy(() => {
    if (refreshTimer) clearInterval(refreshTimer);
  });

  function fetchSnapshot() {
    loading = true;
    error = null;
    fetch(BRAIN + '/whatsapp/debug')
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(data => {
        snapshot = data.snapshot || null;
        scanReport = data.scan_report || null;
        loading = false;
      })
      .catch(err => {
        error = err.message || 'Failed to fetch';
        loading = false;
      });
  }

  function testSelector() {
    if (!selectorQuery.trim()) return;
    fetch(BRAIN + '/whatsapp/debug/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selector: selectorQuery.trim() }),
    })
      .then(r => r.json())
      .then(data => {
        selectorResults = data.results || [];
        selectorCount = data.count || 0;
      })
      .catch(() => {
        selectorResults = [];
        selectorCount = -1;
      });
  }

  function toggleAutoRefresh() {
    autoRefresh = !autoRefresh;
    if (autoRefresh) {
      refreshTimer = setInterval(fetchSnapshot, 3000);
    } else {
      if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
    }
  }

  function togglePath(path) {
    if (expandedPaths.has(path)) {
      expandedPaths.delete(path);
    } else {
      expandedPaths.add(path);
    }
    expandedPaths = new Set(expandedPaths); // trigger reactivity
  }

  function truncate(s, n) {
    if (!s) return '';
    return s.length > n ? s.substring(0, n) + '…' : s;
  }

  function nodeLabel(node) {
    if (!node) return '?';
    var tag = node.tag || '?';
    var parts = [tag];
    if (node.id) parts.push('#' + node.id);
    if (node.classes && node.classes.length > 0) {
      parts.push('.' + node.classes.slice(0, 3).join('.'));
    }
    return parts.join('');
  }

  function nodeColor(node) {
    if (!node) return 'rgba(255,255,255,0.5)';
    var tag = (node.tag || '').toLowerCase();
    if (tag === 'div') return 'rgba(124,138,255,0.8)';
    if (tag === 'span') return 'rgba(37,211,102,0.8)';
    if (tag === 'img') return 'rgba(255,189,46,0.8)';
    if (tag === 'button' || tag === 'input') return 'rgba(255,95,87,0.8)';
    if (tag === 'header' || tag === 'footer' || tag === 'nav' || tag === 'main') return 'rgba(200,130,255,0.8)';
    if (tag === 'a') return 'rgba(100,200,255,0.8)';
    return 'rgba(255,255,255,0.5)';
  }

  function flattenTree(node, path, depth) {
    if (!node || depth > maxDepth) return [];
    var result = [{ node: node, path: path, depth: depth }];
    if (node.children && expandedPaths.has(path)) {
      for (var i = 0; i < node.children.length; i++) {
        var childPath = path + '/' + i;
        result = result.concat(flattenTree(node.children[i], childPath, depth + 1));
      }
    }
    return result;
  }

  $: flatNodes = snapshot ? flattenTree(snapshot, '0', 0) : [];
  $: filteredNodes = filterTag
    ? flatNodes.filter(n => {
        var tag = (n.node.tag || '').toLowerCase();
        var cls = (n.node.classes || []).join(' ').toLowerCase();
        var id = (n.node.id || '').toLowerCase();
        var f = filterTag.toLowerCase();
        return tag.includes(f) || cls.includes(f) || id.includes(f);
      })
    : flatNodes;
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="debug-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>

  <div class="debug-header">
    <span class="debug-icon">🔍</span>
    <span class="debug-title">WA DOM Inspector</span>
    <div class="debug-controls">
      <button class="dbtn" on:click={fetchSnapshot} title="Refresh">🔄</button>
      <button class="dbtn" class:active={autoRefresh} on:click={toggleAutoRefresh} title="Auto-refresh">
        {autoRefresh ? '⏸' : '▶'}
      </button>
    </div>
  </div>

  <!-- Tabs -->
  <div class="tab-bar">
    <button class="tab" class:active={activeTab === 'tree'} on:click={() => activeTab = 'tree'}>🌳 Tree</button>
    <button class="tab" class:active={activeTab === 'selector'} on:click={() => activeTab = 'selector'}>🎯 Selector</button>
    <button class="tab" class:active={activeTab === 'scan'} on:click={() => activeTab = 'scan'}>📊 Scan Report</button>
    <button class="tab" class:active={activeTab === 'raw'} on:click={() => activeTab = 'raw'}>📋 Raw</button>
  </div>

  <div class="debug-content">
    {#if loading}
      <div class="debug-empty">Loading DOM snapshot…</div>
    {:else if error}
      <div class="debug-empty error">❌ {error}<br><br>Make sure WhatsApp organ is running.<br>The monitor sends DOM snapshots every 10s.</div>
    {:else if activeTab === 'tree'}
      <!-- DOM Tree View -->
      <div class="tree-controls">
        <input class="filter-input" type="text" bind:value={filterTag} placeholder="Filter by tag/class/id…" />
        <div class="depth-ctrl">
          <span class="depth-label">Depth:</span>
          <button class="dbtn small" on:click={() => { maxDepth = Math.max(1, maxDepth - 1); }}>−</button>
          <span class="depth-val">{maxDepth}</span>
          <button class="dbtn small" on:click={() => { maxDepth = Math.min(12, maxDepth + 1); }}>+</button>
        </div>
      </div>

      {#if !snapshot}
        <div class="debug-empty">No snapshot available yet</div>
      {:else}
        <div class="tree-view">
          {#each filteredNodes as item}
            <div
              class="tree-node"
              style="padding-left:{item.depth * 16 + 8}px"
              on:click={() => togglePath(item.path)}
            >
              {#if item.node.children && item.node.children.length > 0}
                <span class="tree-arrow" class:expanded={expandedPaths.has(item.path)}>▶</span>
              {:else}
                <span class="tree-leaf">·</span>
              {/if}
              <span class="tree-tag" style="color:{nodeColor(item.node)}">{nodeLabel(item.node)}</span>
              {#if item.node.text}
                <span class="tree-text">"{truncate(item.node.text, 40)}"</span>
              {/if}
              {#if item.node.title}
                <span class="tree-attr" title="title attribute">[title="{truncate(item.node.title, 30)}"]</span>
              {/if}
              {#if item.node.role}
                <span class="tree-attr">[role="{item.node.role}"]</span>
              {/if}
              {#if item.node.dataTestid}
                <span class="tree-attr testid">[data-testid="{item.node.dataTestid}"]</span>
              {/if}
              {#if item.node.dataId}
                <span class="tree-attr dataid">[data-id]</span>
              {/if}
              {#if item.node.children}
                <span class="tree-count">({item.node.children.length})</span>
              {/if}
            </div>
          {/each}
        </div>
      {/if}

    {:else if activeTab === 'selector'}
      <!-- CSS Selector Tester -->
      <div class="selector-panel">
        <div class="selector-input-row">
          <input
            class="selector-input"
            type="text"
            bind:value={selectorQuery}
            placeholder="CSS selector, e.g. div.message-in, ._ak8j, #pane-side [title]"
            on:keydown={(e) => { if (e.key === 'Enter') testSelector(); }}
          />
          <button class="dbtn primary" on:click={testSelector}>Test</button>
        </div>

        {#if selectorCount >= 0}
          <div class="selector-count">
            Matched: <strong>{selectorCount}</strong> element{selectorCount !== 1 ? 's' : ''}
          </div>
        {:else if selectorCount === -1}
          <div class="selector-count error">Query failed</div>
        {/if}

        <div class="selector-results">
          {#each selectorResults as result, i}
            <div class="result-item">
              <div class="result-idx">#{i + 1}</div>
              <div class="result-info">
                <div class="result-tag" style="color:{nodeColor(result)}">{nodeLabel(result)}</div>
                {#if result.text}
                  <div class="result-text">"{truncate(result.text, 60)}"</div>
                {/if}
                {#if result.title}
                  <div class="result-attr">title: "{truncate(result.title, 40)}"</div>
                {/if}
                {#if result.outerHtml}
                  <div class="result-html">{truncate(result.outerHtml, 120)}</div>
                {/if}
              </div>
            </div>
          {/each}
        </div>

        <div class="selector-presets">
          <div class="preset-label">Quick selectors:</div>
          {#each [
            { label: 'Sidebar items', sel: '._ak8j' },
            { label: 'Contact names', sel: '[title]' },
            { label: 'Incoming msgs', sel: 'div.message-in' },
            { label: 'Outgoing msgs', sel: 'div.message-out' },
            { label: 'Chat header', sel: '#main header span[title]' },
            { label: 'Pane side', sel: '#pane-side' },
            { label: 'Unread badges', sel: 'span[aria-label*="unread"]' },
            { label: 'Profile pics', sel: 'img[src*="pps"]' },
            { label: 'Text spans', sel: 'span.selectable-text' },
            { label: 'Data-pre-plain', sel: '[data-pre-plain-text]' },
            { label: 'Cell frames', sel: '[data-testid="cell-frame-container"]' },
            { label: 'Chat list rows', sel: '#pane-side [role="listitem"], #pane-side [role="row"]' },
          ] as preset}
            <button class="preset-btn" on:click={() => { selectorQuery = preset.sel; testSelector(); }}>
              {preset.label}
            </button>
          {/each}
        </div>
      </div>

    {:else if activeTab === 'scan'}
      <!-- Scan Report — what the monitor.js currently identifies -->
      {#if !scanReport}
        <div class="debug-empty">No scan report yet. Wait for the monitor to send one.</div>
      {:else}
        <div class="scan-report">
          <div class="scan-section">
            <div class="scan-label">Current Open Chat</div>
            <div class="scan-value">{scanReport.currentChat || '(none open)'}</div>
          </div>
          <div class="scan-section">
            <div class="scan-label">Sidebar Contacts Found</div>
            <div class="scan-value">{scanReport.sidebarCount || 0}</div>
            {#if scanReport.sidebarItems}
              {#each scanReport.sidebarItems.slice(0, 15) as item}
                <div class="scan-item">
                  <span class="scan-contact">{item.contact || '?'}</span>
                  {#if item.preview}
                    <span class="scan-preview">— {truncate(item.preview, 40)}</span>
                  {/if}
                  {#if item.unread > 0}
                    <span class="scan-unread">({item.unread})</span>
                  {/if}
                </div>
              {/each}
            {/if}
          </div>
          <div class="scan-section">
            <div class="scan-label">Messages in Open Chat</div>
            <div class="scan-value">{scanReport.messageCount || 0}</div>
            {#if scanReport.messages}
              {#each scanReport.messages.slice(-10) as msg}
                <div class="scan-item">
                  {#if msg.sender}
                    <span class="scan-contact">{msg.sender}:</span>
                  {/if}
                  <span class="scan-preview">{truncate(msg.text, 50)}</span>
                </div>
              {/each}
            {/if}
          </div>
          <div class="scan-section">
            <div class="scan-label">DOM Selector Hits</div>
            {#if scanReport.selectorHits}
              {#each Object.entries(scanReport.selectorHits) as [sel, count]}
                <div class="scan-item">
                  <span class="scan-selector">{sel}</span>
                  <span class="scan-value">{count}</span>
                </div>
              {/each}
            {/if}
          </div>
        </div>
      {/if}

    {:else if activeTab === 'raw'}
      <!-- Raw JSON -->
      <div class="raw-view">
        <pre>{JSON.stringify(snapshot, null, 2)}</pre>
      </div>
    {/if}
  </div>
</div>

<style>
  .debug-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    color: rgba(255,255,255,0.9);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 11px;
    box-sizing: border-box; overflow: hidden;
  }
  .dismiss {
    position: absolute; top: 8px; right: 10px;
    background: none; border: none;
    color: rgba(255,255,255,0.3); font-size: 14px;
    cursor: pointer; padding: 4px 8px; border-radius: 4px; z-index: 2;
  }
  .dismiss:hover { color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.08); }

  .debug-header {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px 8px;
    border-bottom: 1px solid rgba(255,255,255,0.06); flex-shrink: 0;
  }
  .debug-icon { font-size: 16px; }
  .debug-title { font-size: 12px; font-weight: 700; color: rgba(255,189,46,0.9); letter-spacing: 0.4px; flex: 1; }
  .debug-controls { display: flex; gap: 4px; }

  .dbtn {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.6); font-size: 11px;
    padding: 3px 8px; border-radius: 5px; cursor: pointer; font-family: inherit;
  }
  .dbtn:hover { background: rgba(255,255,255,0.1); color: #fff; }
  .dbtn.active { background: rgba(37,211,102,0.15); border-color: rgba(37,211,102,0.3); color: rgba(37,211,102,0.9); }
  .dbtn.primary { background: rgba(124,138,255,0.12); border-color: rgba(124,138,255,0.25); color: rgba(124,138,255,0.9); }
  .dbtn.small { font-size: 10px; padding: 2px 6px; }

  .tab-bar {
    display: flex; gap: 2px; padding: 4px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.04); flex-shrink: 0;
  }
  .tab {
    background: none; border: none; border-bottom: 2px solid transparent;
    color: rgba(255,255,255,0.35); font-size: 10px; font-weight: 600;
    padding: 5px 10px; cursor: pointer; font-family: inherit;
    transition: all 0.12s;
  }
  .tab:hover { color: rgba(255,255,255,0.6); }
  .tab.active { color: rgba(255,189,46,0.9); border-bottom-color: rgba(255,189,46,0.6); }

  .debug-content { flex: 1; overflow-y: auto; }
  .debug-content::-webkit-scrollbar { width: 4px; }
  .debug-content::-webkit-scrollbar-track { background: transparent; }
  .debug-content::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.06); border-radius: 2px; }

  .debug-empty {
    display: flex; align-items: center; justify-content: center;
    height: 100%; font-size: 11px; color: rgba(255,255,255,0.2);
    text-align: center; padding: 20px; line-height: 1.6;
  }
  .debug-empty.error { color: rgba(255,95,87,0.6); }

  /* ── Tree View ── */
  .tree-controls {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.03); flex-shrink: 0;
  }
  .filter-input {
    flex: 1; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.8); font-size: 10px; padding: 4px 8px;
    border-radius: 4px; font-family: inherit; outline: none;
  }
  .filter-input:focus { border-color: rgba(255,189,46,0.3); }
  .depth-ctrl { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
  .depth-label { font-size: 9px; color: rgba(255,255,255,0.3); }
  .depth-val { font-size: 10px; color: rgba(255,189,46,0.7); min-width: 14px; text-align: center; }

  .tree-view { padding: 4px 0; }
  .tree-node {
    display: flex; align-items: center; gap: 4px;
    padding: 2px 0; cursor: pointer;
    transition: background 0.08s;
    white-space: nowrap;
  }
  .tree-node:hover { background: rgba(255,255,255,0.03); }
  .tree-arrow {
    font-size: 8px; color: rgba(255,255,255,0.25);
    transition: transform 0.12s; display: inline-block;
    width: 10px; text-align: center;
  }
  .tree-arrow.expanded { transform: rotate(90deg); }
  .tree-leaf { font-size: 8px; color: rgba(255,255,255,0.1); width: 10px; text-align: center; }
  .tree-tag { font-weight: 600; font-size: 10px; }
  .tree-text { font-size: 9px; color: rgba(255,189,46,0.5); margin-left: 4px; }
  .tree-attr { font-size: 8px; color: rgba(124,138,255,0.5); margin-left: 3px; }
  .tree-attr.testid { color: rgba(37,211,102,0.5); }
  .tree-attr.dataid { color: rgba(255,95,87,0.5); }
  .tree-count { font-size: 8px; color: rgba(255,255,255,0.15); margin-left: 2px; }

  /* ── Selector Tester ── */
  .selector-panel { padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }
  .selector-input-row { display: flex; gap: 6px; }
  .selector-input {
    flex: 1; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.85); font-size: 11px; padding: 6px 10px;
    border-radius: 6px; font-family: inherit; outline: none;
  }
  .selector-input:focus { border-color: rgba(124,138,255,0.4); }
  .selector-count {
    font-size: 10px; color: rgba(255,255,255,0.4);
    padding: 4px 0;
  }
  .selector-count strong { color: rgba(124,138,255,0.9); }
  .selector-count.error { color: rgba(255,95,87,0.7); }

  .selector-results { display: flex; flex-direction: column; gap: 4px; }
  .result-item {
    display: flex; gap: 8px; padding: 6px 10px;
    background: rgba(255,255,255,0.02); border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.03);
  }
  .result-idx { font-size: 9px; color: rgba(255,255,255,0.15); min-width: 20px; }
  .result-info { flex: 1; min-width: 0; }
  .result-tag { font-weight: 600; font-size: 10px; }
  .result-text { font-size: 9px; color: rgba(255,189,46,0.5); margin-top: 2px; }
  .result-attr { font-size: 8px; color: rgba(124,138,255,0.5); margin-top: 1px; }
  .result-html { font-size: 8px; color: rgba(255,255,255,0.2); margin-top: 2px; word-break: break-all; }

  .selector-presets {
    padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.04);
  }
  .preset-label { font-size: 9px; color: rgba(255,255,255,0.2); margin-bottom: 6px; }
  .preset-btn {
    display: inline-block;
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06);
    color: rgba(255,255,255,0.5); font-size: 9px;
    padding: 3px 8px; border-radius: 4px; cursor: pointer;
    font-family: inherit; margin: 2px 4px 2px 0;
    transition: all 0.12s;
  }
  .preset-btn:hover { background: rgba(124,138,255,0.12); color: rgba(124,138,255,0.9); border-color: rgba(124,138,255,0.2); }

  /* ── Scan Report ── */
  .scan-report { padding: 10px 14px; }
  .scan-section { margin-bottom: 12px; }
  .scan-label { font-size: 10px; font-weight: 700; color: rgba(255,189,46,0.7); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
  .scan-value { font-size: 11px; color: rgba(255,255,255,0.6); }
  .scan-item {
    padding: 3px 0 3px 12px; font-size: 10px;
    border-left: 2px solid rgba(255,255,255,0.04);
  }
  .scan-contact { color: rgba(37,211,102,0.7); font-weight: 600; }
  .scan-preview { color: rgba(255,255,255,0.35); }
  .scan-unread { color: rgba(255,189,46,0.7); font-weight: 700; font-size: 9px; }
  .scan-selector { color: rgba(124,138,255,0.6); font-size: 9px; }

  /* ── Raw View ── */
  .raw-view {
    padding: 10px 14px;
    overflow: auto;
  }
  .raw-view pre {
    font-size: 9px; color: rgba(255,255,255,0.4);
    white-space: pre-wrap; word-break: break-all;
    margin: 0;
  }
</style>
