<script>
  import { onMount, onDestroy, tick } from 'svelte';
  import { createWS } from '$lib/ws.js';
  import registry from '$lib/widgets/index.js';

  // ── Tauri IPC (for toggling overlay visibility) ──
  let tauriInvoke = null;
  let tauriWindow = null;
  if (typeof window !== 'undefined') {
    import('@tauri-apps/api/core').then(mod => {
      tauriInvoke = mod.invoke;
    }).catch(() => {});
    import('@tauri-apps/api/window').then(mod => {
      tauriWindow = mod.getCurrentWindow();
    }).catch(() => {});
  }

  // ── state ──
  let ws = null;
  let connected = false;
  let query = '';
  let feedback = '';
  let feedbackTimer = null;
  let history = [];
  let historyIdx = -1;
  let inputEl;
  let canvasEl;

  // Each entry: { id, type, x, y, w, h, props, component }
  let widgets = [];

  // ── pages ──
  let pageCount = 3;
  let pageHeight = 900; // safe default; updated on mount
  let currentPage = 0;

  // ── shell sections ──
  // { id, cmd, lines: string[], done: boolean, exitCode: number, y: number }
  let shellSections = [];

  // ── workspaces ──
  let workspaceList = ['default'];
  let currentWorkspace = 'default';
  let showWorkspaceMenu = false;
  let newWorkspaceName = '';

  // track the bottom of content for placing new shell sections
  function getNextShellY() {
    var y = 20;
    // below any existing shell sections
    for (var i = 0; i < shellSections.length; i++) {
      var s = shellSections[i];
      var h = 60 + (s.lines.length * 19) + 30;
      var bottom = s.y + h;
      if (bottom > y) y = bottom + 16;
    }
    return y;
  }

  // ── toggle overlay visibility (called via Spine → WebSocket → Rust IPC) ──
  function toggleOverlay() {
    if (tauriInvoke) {
      tauriInvoke('toggle_window').then(function () {
        // After showing, focus the input
        setTimeout(function () { if (inputEl) inputEl.focus(); }, 150);
      }).catch(function (err) {
        console.error('toggle_window failed:', err);
      });
    }
  }

  // ── lifecycle ──
  onMount(() => {
    // Measure page height immediately and on resize
    pageHeight = window.innerHeight || 900;
    window.addEventListener('resize', onResize);

    ws = createWS(handleMessage, function (s) { connected = s; });
    setTimeout(function () { if (inputEl) inputEl.focus(); }, 100);
    window.addEventListener('focus', refocus);
    window.addEventListener('beforeunload', saveState);
  });

  onDestroy(() => {
    saveState();
    if (ws) ws.close();
    window.removeEventListener('focus', refocus);
    window.removeEventListener('beforeunload', saveState);
    window.removeEventListener('resize', onResize);
    clearTimeout(feedbackTimer);
  });

  function onResize() {
    pageHeight = window.innerHeight || 900;
  }

  function refocus() {
    setTimeout(function () { if (inputEl) inputEl.focus(); }, 50);
  }

  // ── save current widget state to backend ──
  function saveState() {
    if (!ws || !ws.isOpen()) return;
    var data = widgets.map(function (w) {
      return { id: w.id, type: w.type, x: w.x, y: w.y, w: w.w, h: w.h, props: w.props };
    });
    ws.send({ type: 'save_state', widgets: data });
  }

  // ── page navigation ──
  function scrollToPage(idx) {
    if (!canvasEl) return;
    currentPage = idx;
    canvasEl.scrollTo({ top: idx * pageHeight, behavior: 'smooth' });
  }

  function onCanvasScroll() {
    if (!canvasEl || pageHeight <= 0) return;
    currentPage = Math.round(canvasEl.scrollTop / pageHeight);
    if (canvasEl.scrollTop + pageHeight * 1.5 > pageCount * pageHeight) {
      pageCount += 1;
    }
  }

  function ensurePages(bottomY) {
    var need = Math.ceil(bottomY / pageHeight) + 1;
    if (need > pageCount) pageCount = need;
  }

  // ── websocket message handler ──
  function handleMessage(msg) {
    if (msg.type === 'RENDER_WIDGET') {
      addWidget(msg);
      saveState();
    }
    else if (msg.type === 'RESTORE_STATE') {
      var restored = [];
      var list = msg.widgets || [];
      for (var i = 0; i < list.length; i++) {
        var w = list[i];
        var comp = registry[w.type];
        if (comp) {
          restored.push({
            id: w.id, type: w.type,
            x: w.x, y: w.y, w: w.w, h: w.h,
            props: w.props || {},
            component: comp,
          });
        }
      }
      if (restored.length > 0) {
        widgets = restored;
        for (var j = 0; j < restored.length; j++) {
          ensurePages(restored[j].y + restored[j].h);
        }
      }
    }
    else if (msg.type === 'REMOVE_WIDGET') {
      widgets = widgets.filter(function (w) { return w.id !== msg.widget_id; });
      saveState();
    }
    else if (msg.type === 'CLEAR_WIDGETS') {
      widgets = [];
      saveState();
    }
    else if (msg.type === 'FEEDBACK') {
      showFeedback(msg.message);
    }
    else if (msg.type === 'SHELL_OUTPUT') {
      appendShellLine(msg.shell_id, msg.text);
    }
    else if (msg.type === 'SHELL_DONE') {
      finishShell(msg.shell_id, msg.exit_code);
    }
    else if (msg.type === 'RESTORE_SHELL') {
      restoreShellSessions(msg.sessions || []);
    }
    else if (msg.type === 'CLEAR_SHELL') {
      shellSections = [];
    }
    else if (msg.type === 'WORKSPACE_INFO') {
      workspaceList = msg.workspaces || ['default'];
      currentWorkspace = msg.current || 'default';
    }
    else if (msg.type === 'TOGGLE_VISIBILITY') {
      toggleOverlay();
    }
  }

  function addWidget(msg) {
    var comp = registry[msg.widget_type];
    if (!comp) {
      showFeedback('Unknown widget: ' + msg.widget_type);
      return;
    }
    // Place widget on the current visible page
    var offsetY = canvasEl ? canvasEl.scrollTop : 0;
    var wy = msg.y + offsetY;
    widgets = widgets.concat([{
      id:    msg.widget_id,
      type:  msg.widget_type,
      x:     msg.x,
      y:     wy,
      w:     msg.w,
      h:     msg.h,
      props: msg.props || {},
      component: comp,
    }]);
    ensurePages(wy + msg.h);
  }

  function showFeedback(text) {
    feedback = text;
    clearTimeout(feedbackTimer);
    feedbackTimer = setTimeout(function () { feedback = ''; }, 4000);
  }

  // ── dismiss ──
  function dismiss(widgetId) {
    widgets = widgets.filter(function (w) { return w.id !== widgetId; });
    if (ws) ws.send({ type: 'dismiss_widget', widget_id: widgetId });
    saveState();
  }

  // ── widget dragging ──
  let dragId = null;
  let dragOffsetX = 0;
  let dragOffsetY = 0;

  function onDragStart(e, widgetId) {
    var frame = e.currentTarget;
    var rect = frame.getBoundingClientRect();
    var localY = e.clientY - rect.top;
    if (localY > 28) return;
    e.preventDefault();
    e.stopPropagation();
    dragId = widgetId;
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;
    window.addEventListener('pointermove', onDragMove);
    window.addEventListener('pointerup', onDragEnd);
  }

  function onDragMove(e) {
    if (!dragId || !canvasEl) return;
    var canvasRect = canvasEl.getBoundingClientRect();
    var scrollTop = canvasEl.scrollTop;
    var nx = Math.max(0, e.clientX - canvasRect.left - dragOffsetX);
    var ny = Math.max(0, e.clientY - canvasRect.top - dragOffsetY + scrollTop);
    widgets = widgets.map(function (w) {
      if (w.id === dragId) return Object.assign({}, w, { x: nx, y: ny });
      return w;
    });
  }

  function onDragEnd() {
    if (dragId) { dragId = null; saveState(); }
    window.removeEventListener('pointermove', onDragMove);
    window.removeEventListener('pointerup', onDragEnd);
  }

  // ── widget resizing ──
  let resizeId = null;
  let resizeStartX = 0;
  let resizeStartY = 0;
  let resizeStartW = 0;
  let resizeStartH = 0;

  function onResizeStart(e, widgetId) {
    e.preventDefault();
    e.stopPropagation();
    resizeId = widgetId;
    resizeStartX = e.clientX;
    resizeStartY = e.clientY;
    var w = widgets.find(function (w) { return w.id === widgetId; });
    if (w) { resizeStartW = w.w; resizeStartH = w.h; }
    window.addEventListener('pointermove', onResizeMove);
    window.addEventListener('pointerup', onResizeEnd);
  }

  function onResizeMove(e) {
    if (!resizeId) return;
    var nw = Math.max(160, resizeStartW + (e.clientX - resizeStartX));
    var nh = Math.max(100, resizeStartH + (e.clientY - resizeStartY));
    widgets = widgets.map(function (w) {
      if (w.id === resizeId) return Object.assign({}, w, { w: nw, h: nh });
      return w;
    });
  }

  function onResizeEnd() {
    if (resizeId) { resizeId = null; saveState(); }
    window.removeEventListener('pointermove', onResizeMove);
    window.removeEventListener('pointerup', onResizeEnd);
  }

  // ── shell execution ──
  function startShell(cmd) {
    var id = 'sh-' + Date.now().toString(36);
    var yPos = getNextShellY();
    // If there's a visible scroll, place relative to viewport
    if (canvasEl && canvasEl.scrollTop > 0) {
      var viewY = canvasEl.scrollTop + 30;
      if (viewY > yPos) yPos = viewY;
    }
    shellSections = shellSections.concat([{
      id: id, cmd: cmd, lines: [], done: false, exitCode: null, y: yPos,
    }]);
    ensurePages(yPos + 200);

    // Auto-scroll to the new section
    tick().then(function () {
      if (canvasEl) {
        canvasEl.scrollTo({ top: yPos - 30, behavior: 'smooth' });
      }
    });

    ws.send({ type: 'shell', cmd: cmd, shell_id: id });
  }

  function appendShellLine(shellId, text) {
    shellSections = shellSections.map(function (s) {
      if (s.id === shellId) {
        return Object.assign({}, s, { lines: s.lines.concat([text]) });
      }
      return s;
    });

    // Auto-scroll to follow output
    tick().then(function () {
      if (!canvasEl) return;
      var section = shellSections.find(function (s) { return s.id === shellId; });
      if (section) {
        var bottomY = section.y + 60 + (section.lines.length * 19) + 30;
        ensurePages(bottomY);
        var viewBottom = canvasEl.scrollTop + canvasEl.clientHeight;
        if (bottomY > viewBottom - 80) {
          canvasEl.scrollTo({ top: bottomY - canvasEl.clientHeight + 100, behavior: 'smooth' });
        }
      }
    });
  }

  function finishShell(shellId, exitCode) {
    shellSections = shellSections.map(function (s) {
      if (s.id === shellId) {
        return Object.assign({}, s, { done: true, exitCode: exitCode });
      }
      return s;
    });
  }

  function restoreShellSessions(sessions) {
    if (!sessions.length) return;
    var yPos = 20;
    var restored = [];
    for (var i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      var lines = s.output ? s.output.split('\n').map(function (l) { return l + '\n'; }) : [];
      // Remove trailing empty newline from split
      if (lines.length > 0 && lines[lines.length - 1] === '\n') lines.pop();
      restored.push({
        id: s.shell_id,
        cmd: s.cmd,
        lines: lines,
        done: true,
        exitCode: s.exit_code,
        y: yPos,
      });
      var sectionH = 60 + (lines.length * 19) + 30 + 16;
      yPos += sectionH;
    }
    if (restored.length > 0) {
      shellSections = restored;
      ensurePages(yPos + 100);
    }
  }

  // ── input handling ──
  var _shellPrefixRe = /^(ls|cd|cat|echo|pwd|mkdir|rm|cp|mv|grep|find|head|tail|wc|df|du|free|uname|whoami|which|env|export|curl|wget|git|docker|npm|bun|cargo|python|pip|make|gcc|neofetch|htop|top|ps|kill|ping|ssh|scp|tar|zip|unzip|chmod|chown|man|apt|pacman|yay|paru|systemctl|journalctl|ip|ss|mount|lsblk|bat|eza|fd|rg|fzf|sed|awk|sort|uniq|tee|xargs|date|touch|tree|less|more)\b/;

  function submit() {
    var text = query.trim();
    if (!text) return;
    history = history.concat([text]);
    historyIdx = history.length;

    var isShell = false;
    var shellCmd = text;
    if (text.charAt(0) === '!' || text.charAt(0) === '$') {
      isShell = true;
      shellCmd = text.substring(1).trim();
    } else if (_shellPrefixRe.test(text)) {
      isShell = true;
    }

    if (isShell && ws && ws.isOpen()) {
      startShell(shellCmd);
    } else if (ws && ws.isOpen()) {
      ws.send({ type: 'query', text: text });
    } else {
      showFeedback('Not connected to Lexicon Brain');
    }
    query = '';
  }

  function onKey(e) {
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (historyIdx > 0) { historyIdx--; query = history[historyIdx]; }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIdx < history.length - 1) { historyIdx++; query = history[historyIdx]; }
      else { historyIdx = history.length; query = ''; }
    } else if (e.key === 'Escape') {
      if (query === '' && tauriInvoke) {
        // If query is already empty, hide the overlay via Rust IPC
        tauriInvoke('toggle_window');
      } else {
        query = '';
      }
    } else if (e.key === 'c' && e.ctrlKey) {
      // Ctrl+C — kill running shell command
      e.preventDefault();
      killShell();
    }
  }

  function killShell() {
    if (!ws || !ws.isOpen()) return;
    var hasRunning = shellSections.some(function (s) { return !s.done; });
    if (hasRunning) {
      ws.send({ type: 'shell_kill' });
      showFeedback('^C');
    }
  }

  // ── workspace functions ──
  function getWidgetData() {
    return widgets.map(function (w) {
      return { id: w.id, type: w.type, x: w.x, y: w.y, w: w.w, h: w.h, props: w.props };
    });
  }

  function clearWorkspace() {
    if (!ws || !ws.isOpen()) return;
    ws.send({ type: 'clear_workspace' });
    widgets = [];
    shellSections = [];
    showFeedback('Workspace cleared');
    showWorkspaceMenu = false;
  }

  function switchWorkspace(name) {
    if (!ws || !ws.isOpen() || name === currentWorkspace) return;
    ws.send({ type: 'switch_workspace', name: name, current_widgets: getWidgetData() });
    showWorkspaceMenu = false;
  }

  function createWorkspace() {
    var name = newWorkspaceName.trim();
    if (!name || !ws || !ws.isOpen()) return;
    // Sanitize: lowercase, replace spaces with dashes
    name = name.toLowerCase().replace(/[^a-z0-9\-_]/g, '-').replace(/-+/g, '-');
    if (!name) return;
    ws.send({ type: 'create_workspace', name: name, current_widgets: getWidgetData() });
    newWorkspaceName = '';
    showWorkspaceMenu = false;
  }

  function deleteWorkspace(name) {
    if (!ws || !ws.isOpen() || name === 'default') return;
    ws.send({ type: 'delete_workspace', name: name });
  }

  function toggleWorkspaceMenu() {
    showWorkspaceMenu = !showWorkspaceMenu;
  }

  // ── computed ──
  $: totalHeight = Math.max(pageCount * pageHeight, pageHeight);
  $: pageIndices = Array.from({ length: pageCount }, function (_, i) { return i; });
  $: dividerPositions = pageIndices.slice(1).map(function (i) { return i * pageHeight; });
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="root">

  <!-- ── sidebar ── -->
  <div class="sidebar">
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="sidebar-logo" on:click={toggleWorkspaceMenu} title="Workspaces">✦</div>

    {#each pageIndices as idx}
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <div
        class="sidebar-dot"
        class:active={currentPage === idx}
        on:click={() => scrollToPage(idx)}
        title="Page {idx + 1}"
      >
        <span class="sidebar-num">{idx + 1}</span>
      </div>
    {/each}

    <div class="sidebar-bottom">
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <div class="sidebar-action" on:click={clearWorkspace} title="Clear workspace">🧹</div>
      <div class="ws-label" title={currentWorkspace}>{currentWorkspace.substring(0, 3)}</div>
      <div class="conn-dot" class:on={connected}></div>
    </div>
  </div>

  <!-- workspace menu popup -->
  {#if showWorkspaceMenu}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="ws-menu-backdrop" on:click={() => { showWorkspaceMenu = false; }}></div>
    <div class="ws-menu">
      <div class="ws-menu-title">Workspaces</div>
      {#each workspaceList as wsName}
        <div class="ws-menu-item" class:active={wsName === currentWorkspace}>
          <!-- svelte-ignore a11y-no-static-element-interactions -->
          <span class="ws-menu-name" on:click={() => switchWorkspace(wsName)}>{wsName}</span>
          {#if wsName === currentWorkspace}
            <span class="ws-menu-badge">●</span>
          {/if}
          {#if wsName !== 'default'}
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <span class="ws-menu-delete" on:click={() => deleteWorkspace(wsName)} title="Delete">×</span>
          {/if}
        </div>
      {/each}
      <div class="ws-menu-divider"></div>
      <div class="ws-menu-create">
        <input
          class="ws-menu-input"
          bind:value={newWorkspaceName}
          placeholder="new workspace…"
          on:keydown={(e) => { if (e.key === 'Enter') createWorkspace(); }}
          spellcheck="false"
        />
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <span class="ws-menu-add" on:click={createWorkspace}>+</span>
      </div>
      <div class="ws-menu-divider"></div>
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <div class="ws-menu-item ws-menu-clear" on:click={clearWorkspace}>
        <span class="ws-menu-name">🧹 Clear workspace</span>
      </div>
    </div>
  {/if}

  <!-- ── scrollable canvas ── -->
  <div
    class="canvas"
    bind:this={canvasEl}
    on:scroll={onCanvasScroll}
    on:click={() => { if (inputEl) inputEl.focus(); }}
  >
    <div class="canvas-inner" style="height:{totalHeight}px;">

      <!-- page dividers -->
      {#each dividerPositions as dy}
        <div class="divider" style="top:{dy}px;">
          <div class="divider-line"></div>
        </div>
      {/each}

      <!-- widget layer -->
      {#each widgets as w (w.id)}
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div
          class="widget-frame"
          class:dragging={dragId === w.id}
          class:resizing={resizeId === w.id}
          style="left:{w.x}px; top:{w.y}px; width:{w.w}px; height:{w.h}px;"
          on:pointerdown={(e) => onDragStart(e, w.id)}
        >
          <div class="drag-handle"><span class="drag-dots">⋮⋮</span></div>
          <svelte:component this={w.component} props={w.props} onDismiss={() => dismiss(w.id)} />
          <!-- svelte-ignore a11y-no-static-element-interactions -->
          <div class="resize-handle" on:pointerdown={(e) => onResizeStart(e, w.id)}>
            <svg width="10" height="10" viewBox="0 0 10 10"><path d="M9 1L1 9M9 5L5 9M9 9L9 9" stroke="rgba(255,255,255,0.15)" stroke-width="1.2" fill="none"/></svg>
          </div>
        </div>
      {/each}

      <!-- shell output sections -->
      {#each shellSections as sh (sh.id)}
        <div class="shell-section" style="top:{sh.y}px;">
          <div class="shell-divider"></div>
          <div class="shell-header">
            <span class="shell-prompt">❯</span>
            <span class="shell-cmd">{sh.cmd}</span>
            {#if sh.done}
              <span class="shell-exit" class:err={sh.exitCode !== 0}>exit {sh.exitCode}</span>
            {:else}
              <span class="shell-running">running…</span>
              <!-- svelte-ignore a11y-click-events-have-key-events -->
              <!-- svelte-ignore a11y-no-static-element-interactions -->
              <span class="shell-kill" on:click={killShell} title="Ctrl+C">^C</span>
            {/if}
          </div>
          <pre class="shell-output">{sh.lines.join('')}</pre>
          {#if sh.done}
            <div class="shell-divider bottom"></div>
          {/if}
        </div>
      {/each}

    </div>
  </div>

  <!-- feedback toast -->
  {#if feedback}
    <div class="toast">{feedback}</div>
  {/if}

  <!-- synapse bar -->
  <div class="bar-wrap">
    <div class="bar">
      <span class="bar-icon">✦</span>
      <form on:submit|preventDefault={submit}>
        <input
          bind:this={inputEl}
          bind:value={query}
          on:keydown={onKey}
          class="input"
          placeholder="ask lexicon anything… (prefix ! for shell)"
          spellcheck="false"
          autocomplete="off"
        />
      </form>
    </div>
  </div>
</div>

<style>
  :global(html, body) {
    margin: 0; padding: 0;
    background: transparent !important;
    overflow: hidden;
    height: 100%; width: 100%;
  }

  .root {
    position: fixed; inset: 0;
    display: flex;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    z-index: 9999;
  }

  /* ═══════════════ sidebar ═══════════════ */
  .sidebar {
    width: 44px; flex-shrink: 0;
    background: rgba(12, 12, 22, 0.7);
    border-right: 1px solid rgba(255,255,255,0.05);
    display: flex; flex-direction: column; align-items: center;
    padding: 14px 0;
    gap: 6px;
    backdrop-filter: blur(12px);
    z-index: 10020;
    overflow-y: auto;
  }
  .sidebar::-webkit-scrollbar { display: none; }
  .sidebar-logo {
    color: #7c8aff; font-size: 16px; opacity: 0.6;
    margin-bottom: 10px; user-select: none;
    cursor: pointer; transition: opacity 0.15s;
  }
  .sidebar-logo:hover { opacity: 1; }
  .sidebar-dot {
    width: 28px; height: 28px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer;
    background: rgba(255,255,255,0.03);
    border: 1px solid transparent;
    transition: all 0.2s;
  }
  .sidebar-dot:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(255,255,255,0.1);
  }
  .sidebar-dot.active {
    background: rgba(124,138,255,0.12);
    border-color: rgba(124,138,255,0.3);
  }
  .sidebar-num {
    font-size: 10px; font-weight: 600;
    color: rgba(255,255,255,0.25);
    transition: color 0.2s;
  }
  .sidebar-dot.active .sidebar-num { color: rgba(124,138,255,0.9); }
  .sidebar-dot:hover .sidebar-num { color: rgba(255,255,255,0.5); }
  .sidebar-bottom { margin-top: auto; padding-top: 10px; display: flex; flex-direction: column; align-items: center; gap: 8px; }
  .sidebar-action {
    width: 28px; height: 28px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; font-size: 14px;
    background: rgba(255,255,255,0.03);
    border: 1px solid transparent;
    transition: all 0.2s; user-select: none;
  }
  .sidebar-action:hover {
    background: rgba(255,255,255,0.08);
    border-color: rgba(255,255,255,0.1);
  }
  .ws-label {
    font-size: 8px; font-weight: 700; letter-spacing: 0.5px;
    color: rgba(124,138,255,0.5);
    text-transform: uppercase;
    max-width: 38px; overflow: hidden; text-overflow: ellipsis;
    text-align: center; user-select: none;
  }
  .conn-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: #ff5f57;
    box-shadow: 0 0 6px rgba(255,95,87,0.4);
    transition: all 0.3s;
  }
  .conn-dot.on {
    background: #28c840;
    box-shadow: 0 0 6px rgba(40,200,64,0.4);
  }

  /* ═══════════════ canvas ═══════════════ */
  .canvas {
    flex: 1;
    overflow-y: auto; overflow-x: hidden;
    background: rgba(15, 15, 25, 0.55);
    position: relative;
  }
  .canvas::-webkit-scrollbar { width: 4px; }
  .canvas::-webkit-scrollbar-track { background: transparent; }
  .canvas::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.06); border-radius: 2px; }
  .canvas::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.12); }

  .canvas-inner {
    position: relative; width: 100%; min-height: 100%;
  }

  /* ═══════════════ page dividers ═══════════════ */
  .divider {
    position: absolute; left: 0; right: 0; height: 1px;
    z-index: 5; pointer-events: none;
  }
  .divider-line {
    width: 100%; height: 1px;
    background: linear-gradient(90deg,
      transparent 0%,
      rgba(124,138,255,0.06) 10%,
      rgba(124,138,255,0.12) 50%,
      rgba(124,138,255,0.06) 90%,
      transparent 100%
    );
  }

  /* ═══════════════ widget frames ═══════════════ */
  .widget-frame {
    position: absolute;
    background: rgba(20, 20, 35, 0.65);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    backdrop-filter: blur(12px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05);
    overflow: hidden;
    z-index: 10;
    animation: pop 0.3s cubic-bezier(0.16,1,0.3,1) forwards;
    transition: box-shadow 0.15s;
  }
  .widget-frame.dragging {
    box-shadow: 0 16px 48px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.08);
    z-index: 15; cursor: grabbing;
  }
  .widget-frame.resizing { z-index: 15; }
  @keyframes pop {
    from { opacity: 0; transform: scale(0.92) translateY(8px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
  }

  /* drag handle */
  .drag-handle {
    position: absolute; top: 0; left: 0; right: 0;
    height: 28px;
    display: flex; align-items: center; justify-content: center;
    cursor: grab; z-index: 2; user-select: none;
  }
  .drag-handle:active { cursor: grabbing; }
  .drag-dots {
    font-size: 10px; letter-spacing: 2px;
    color: rgba(255,255,255,0.1);
    transition: color 0.15s;
  }
  .drag-handle:hover .drag-dots { color: rgba(255,255,255,0.3); }

  /* resize handle */
  .resize-handle {
    position: absolute; bottom: 0; right: 0;
    width: 18px; height: 18px;
    cursor: nwse-resize;
    display: flex; align-items: center; justify-content: center;
    z-index: 3; opacity: 0;
    transition: opacity 0.15s;
  }
  .widget-frame:hover .resize-handle { opacity: 1; }

  /* ═══════════════ shell sections ═══════════════ */
  .shell-section {
    position: absolute;
    left: 24px; right: 24px;
    z-index: 8;
    animation: fadein 0.2s ease-out;
  }
  .shell-divider {
    height: 1px; margin-bottom: 10px;
    background: linear-gradient(90deg,
      transparent 0%,
      rgba(80,200,120,0.12) 15%,
      rgba(80,200,120,0.22) 50%,
      rgba(80,200,120,0.12) 85%,
      transparent 100%
    );
  }
  .shell-divider.bottom { margin-top: 10px; margin-bottom: 0; }
  .shell-header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
  }
  .shell-prompt { color: rgba(80,200,120,0.8); font-size: 13px; font-weight: 700; }
  .shell-cmd { color: rgba(255,255,255,0.65); font-size: 12px; font-weight: 500; }
  .shell-exit {
    margin-left: auto; font-size: 10px;
    color: rgba(80,200,120,0.5); letter-spacing: 0.5px;
  }
  .shell-exit.err { color: rgba(255,95,87,0.7); }
  .shell-running {
    margin-left: auto; font-size: 10px;
    color: rgba(255,200,60,0.6); letter-spacing: 0.5px;
    animation: blink 1s ease-in-out infinite;
  }
  .shell-kill {
    font-size: 10px; font-weight: 700;
    color: rgba(255,95,87,0.7); letter-spacing: 0.5px;
    cursor: pointer; margin-left: 8px;
    padding: 2px 6px; border-radius: 4px;
    background: rgba(255,95,87,0.08);
    border: 1px solid rgba(255,95,87,0.15);
    transition: all 0.15s;
    user-select: none;
  }
  .shell-kill:hover {
    color: rgba(255,95,87,1);
    background: rgba(255,95,87,0.15);
    border-color: rgba(255,95,87,0.3);
  }
  @keyframes blink { 0%,100% { opacity: 0.6; } 50% { opacity: 1; } }
  .shell-output {
    margin: 0; padding: 10px 14px;
    background: rgba(10,10,20,0.5);
    border: 1px solid rgba(255,255,255,0.04);
    border-radius: 10px;
    color: rgba(255,255,255,0.65);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px; line-height: 1.5;
    white-space: pre-wrap; word-break: break-all;
  }

  /* ═══════════════ feedback toast ═══════════════ */
  .toast {
    position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%);
    background: rgba(30,30,50,0.85);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px; padding: 10px 20px;
    color: rgba(255,255,255,0.6); font-size: 12px;
    backdrop-filter: blur(8px); z-index: 10020;
    animation: fadein 0.25s ease-out;
    max-width: 500px; text-align: center;
  }
  @keyframes fadein {
    from { opacity: 0; transform: translateX(-50%) translateY(8px); }
    to   { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  /* ═══════════════ synapse bar ═══════════════ */
  .bar-wrap {
    position: fixed; bottom: 32px;
    left: calc(44px + ((100vw - 44px) / 2));
    transform: translateX(-50%);
    z-index: 10020;
    width: 560px; max-width: calc(100vw - 92px);
  }
  .bar {
    display: flex; align-items: center; gap: 12px;
    padding: 14px 20px;
    background: rgba(20,20,35,0.75);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 16px;
    backdrop-filter: blur(16px);
    box-shadow: 0 8px 40px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.06);
    transition: border-color 0.2s;
  }
  .bar:focus-within {
    border-color: rgba(124,138,255,0.4);
    box-shadow: 0 8px 40px rgba(0,0,0,0.35), 0 0 0 1px rgba(124,138,255,0.15);
  }
  .bar-icon { color: #7c8aff; font-size: 18px; opacity: 0.7; }
  form { flex: 1; display: flex; }
  .input {
    flex: 1; background: transparent; border: none; outline: none;
    color: rgba(255,255,255,0.9);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 14px; caret-color: #7c8aff; line-height: 1.5;
  }
  .input::placeholder { color: rgba(255,255,255,0.2); }

  /* ═══════════════ workspace menu ═══════════════ */
  .ws-menu-backdrop {
    position: fixed; inset: 0; z-index: 10030;
  }
  .ws-menu {
    position: fixed;
    top: 14px; left: 50px;
    z-index: 10040;
    background: rgba(18, 18, 30, 0.92);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 14px;
    backdrop-filter: blur(20px);
    box-shadow: 0 12px 48px rgba(0,0,0,0.5);
    padding: 12px 0;
    min-width: 220px;
    animation: fadein 0.15s ease-out;
  }
  .ws-menu-title {
    padding: 4px 16px 10px;
    font-size: 10px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase;
    color: rgba(124,138,255,0.6);
  }
  .ws-menu-item {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 16px;
    cursor: pointer;
    transition: background 0.1s;
  }
  .ws-menu-item:hover { background: rgba(255,255,255,0.04); }
  .ws-menu-item.active { background: rgba(124,138,255,0.08); }
  .ws-menu-name {
    flex: 1; font-size: 13px;
    color: rgba(255,255,255,0.7);
  }
  .ws-menu-item.active .ws-menu-name { color: rgba(124,138,255,0.9); font-weight: 600; }
  .ws-menu-badge {
    font-size: 8px; color: rgba(124,138,255,0.7);
  }
  .ws-menu-delete {
    font-size: 16px; font-weight: 300;
    color: rgba(255,95,87,0.4);
    cursor: pointer; padding: 0 4px;
    transition: color 0.15s;
    line-height: 1;
  }
  .ws-menu-delete:hover { color: rgba(255,95,87,0.9); }
  .ws-menu-divider {
    height: 1px; margin: 6px 12px;
    background: rgba(255,255,255,0.06);
  }
  .ws-menu-create {
    display: flex; align-items: center; gap: 6px;
    padding: 6px 12px;
  }
  .ws-menu-input {
    flex: 1; background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px; color: rgba(255,255,255,0.8);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    outline: none;
    caret-color: #7c8aff;
  }
  .ws-menu-input::placeholder { color: rgba(255,255,255,0.2); }
  .ws-menu-input:focus {
    border-color: rgba(124,138,255,0.3);
  }
  .ws-menu-add {
    width: 28px; height: 28px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 300;
    color: rgba(80,200,120,0.6);
    background: rgba(80,200,120,0.06);
    border: 1px solid rgba(80,200,120,0.1);
    cursor: pointer; transition: all 0.15s;
  }
  .ws-menu-add:hover {
    color: rgba(80,200,120,0.9);
    background: rgba(80,200,120,0.12);
    border-color: rgba(80,200,120,0.25);
  }
  .ws-menu-clear:hover { background: rgba(255,95,87,0.06); }
  .ws-menu-clear .ws-menu-name { color: rgba(255,255,255,0.5); }
</style>
