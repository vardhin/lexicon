<script>
  import { onMount, onDestroy } from 'svelte';
  import { createWS } from '$lib/ws.js';
  import registry from '$lib/widgets/index.js';

  // ── state ──
  let ws = null;
  let connected = false;
  let query = '';
  let feedback = '';
  let feedbackTimer = null;
  let history = [];
  let historyIdx = -1;
  let inputEl;

  // The dynamic render list — CRUD'd by websocket messages.
  // Each entry: { id, type, x, y, w, h, props, component }
  let widgets = [];

  // ── lifecycle ──
  onMount(() => {
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
    clearTimeout(feedbackTimer);
  });

  function refocus() {
    setTimeout(function () { if (inputEl) inputEl.focus(); }, 50);
  }

  // ── save current widget state to backend ──
  function saveState() {
    if (!ws || !ws.isOpen()) return;
    // strip the component reference — only send serializable data
    var data = widgets.map(function (w) {
      return { id: w.id, type: w.type, x: w.x, y: w.y, w: w.w, h: w.h, props: w.props };
    });
    ws.send({ type: 'save_state', widgets: data });
  }

  // ── websocket message handler (CRUD on render list) ──
  function handleMessage(msg) {
    if (msg.type === 'RENDER_WIDGET') {
      addWidget(msg);
      saveState();
    }
    else if (msg.type === 'RESTORE_STATE') {
      // Re-hydrate widgets from saved state
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
  }

  function addWidget(msg) {
    var comp = registry[msg.widget_type];
    if (!comp) {
      showFeedback('Unknown widget: ' + msg.widget_type);
      return;
    }
    widgets = widgets.concat([{
      id:    msg.widget_id,
      type:  msg.widget_type,
      x:     msg.x,
      y:     msg.y,
      w:     msg.w,
      h:     msg.h,
      props: msg.props || {},
      component: comp,
    }]);
  }

  function showFeedback(text) {
    feedback = text;
    clearTimeout(feedbackTimer);
    feedbackTimer = setTimeout(function () { feedback = ''; }, 4000);
  }

  // ── dismiss a single widget ──
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
    // Only start drag from the widget frame header area (top 28px)
    var frame = e.currentTarget;
    var rect = frame.getBoundingClientRect();
    var localY = e.clientY - rect.top;
    if (localY > 28) return; // only drag from top strip

    e.preventDefault();
    e.stopPropagation();
    dragId = widgetId;
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;

    window.addEventListener('pointermove', onDragMove);
    window.addEventListener('pointerup', onDragEnd);
  }

  function onDragMove(e) {
    if (!dragId) return;
    var nx = Math.max(0, e.clientX - dragOffsetX);
    var ny = Math.max(0, e.clientY - dragOffsetY);
    widgets = widgets.map(function (w) {
      if (w.id === dragId) return Object.assign({}, w, { x: nx, y: ny });
      return w;
    });
  }

  function onDragEnd() {
    if (dragId) {
      dragId = null;
      saveState();
    }
    window.removeEventListener('pointermove', onDragMove);
    window.removeEventListener('pointerup', onDragEnd);
  }

  // ── input handling ──
  function submit() {
    var text = query.trim();
    if (!text) return;
    history = history.concat([text]);
    historyIdx = history.length;
    if (ws && ws.isOpen()) {
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
      query = '';
    }
  }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="overlay" on:click={() => { if (inputEl) inputEl.focus(); }}>

  <!-- connection dot -->
  <div class="dot" class:on={connected}></div>

  <!-- dynamic widget layer -->
  {#each widgets as w (w.id)}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div
      class="widget-frame"
      class:dragging={dragId === w.id}
      style="left:{w.x}px; top:{w.y}px; width:{w.w}px; height:{w.h}px;"
      on:pointerdown={(e) => onDragStart(e, w.id)}
    >
      <div class="drag-handle">
        <span class="drag-dots">⋮⋮</span>
      </div>
      <svelte:component this={w.component} props={w.props} onDismiss={() => dismiss(w.id)} />
    </div>
  {/each}

  <!-- feedback toast -->
  {#if feedback}
    <div class="toast">{feedback}</div>
  {/if}

  <!-- synapse bar -->
  <div class="bar-wrap">
    <div class="bar">
      <span class="icon">✦</span>
      <form on:submit|preventDefault={submit}>
        <input
          bind:this={inputEl}
          bind:value={query}
          on:keydown={onKey}
          class="input"
          placeholder="ask lexicon anything..."
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

  .overlay {
    position: fixed; inset: 0;
    background: rgba(15, 15, 25, 0.55);
    z-index: 9999;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
  }

  /* ── connection indicator ── */
  .dot {
    position: fixed; top: 16px; right: 16px;
    width: 8px; height: 8px; border-radius: 50%;
    background: #ff5f57;
    box-shadow: 0 0 8px rgba(255,95,87,0.5);
    z-index: 10010;
    transition: all 0.3s;
  }
  .dot.on {
    background: #28c840;
    box-shadow: 0 0 8px rgba(40,200,64,0.5);
  }

  /* ── widget frames ── */
  .widget-frame {
    position: absolute;
    background: rgba(20, 20, 35, 0.65);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    backdrop-filter: blur(12px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05);
    overflow: hidden;
    z-index: 10000;
    animation: pop 0.3s cubic-bezier(0.16,1,0.3,1) forwards;
    transition: box-shadow 0.15s;
  }
  .widget-frame.dragging {
    box-shadow: 0 16px 48px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.08);
    z-index: 10005;
    cursor: grabbing;
  }
  /* ── drag handle ── */
  .drag-handle {
    position: absolute; top: 0; left: 0; right: 0;
    height: 28px;
    display: flex; align-items: center; justify-content: center;
    cursor: grab; z-index: 2;
    user-select: none;
  }
  .drag-handle:active { cursor: grabbing; }
  .drag-dots {
    font-size: 10px; letter-spacing: 2px;
    color: rgba(255,255,255,0.12);
    transition: color 0.15s;
  }
  .drag-handle:hover .drag-dots { color: rgba(255,255,255,0.35); }
  @keyframes pop {
    from { opacity: 0; transform: scale(0.92) translateY(8px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
  }

  /* ── feedback toast ── */
  .toast {
    position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%);
    background: rgba(30,30,50,0.85);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    padding: 10px 20px;
    color: rgba(255,255,255,0.6);
    font-size: 12px;
    backdrop-filter: blur(8px);
    z-index: 10020;
    animation: fadein 0.25s ease-out;
    max-width: 500px; text-align: center;
  }
  @keyframes fadein {
    from { opacity: 0; transform: translateX(-50%) translateY(8px); }
    to   { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  /* ── synapse bar ── */
  .bar-wrap {
    position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);
    z-index: 10020;
    width: 560px; max-width: calc(100vw - 48px);
  }
  .bar {
    display: flex; align-items: center; gap: 12px;
    padding: 14px 20px;
    background: rgba(20,20,35,0.7);
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
  .icon { color: #7c8aff; font-size: 18px; opacity: 0.7; }
  form { flex: 1; display: flex; }
  .input {
    flex: 1; background: transparent; border: none; outline: none;
    color: rgba(255,255,255,0.9);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 14px; caret-color: #7c8aff; line-height: 1.5;
  }
  .input::placeholder { color: rgba(255,255,255,0.2); }
</style>
