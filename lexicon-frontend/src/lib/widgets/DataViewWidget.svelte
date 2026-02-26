<!--
  DataViewWidget.svelte — Recursive data renderer.

  Takes a declarative JSON layout tree in props.layout and recursively
  renders it using composable, nestable glass primitives.

  Node types:
    card     — glass container, optional title/subtitle/icon, holds children
    stack    — vertical flex container
    row      — horizontal flex container
    grid     — CSS grid (cols prop: 2, 3, etc.)
    text     — text node with optional variant (h1, h2, h3, body, caption, mono, label)
    badge    — colored pill tag
    list     — bullet or numbered list from items array
    divider  — thin separator line
    avatar   — circle/icon placeholder from initials or emoji
    stat     — big number + label (like a KPI card)
    bar      — progress/percentage bar with label
    image    — placeholder image box with alt text
    spacer   — empty vertical space
    pair     — key:value line

  Every node can have:
    type      — (required) one of the above
    children  — array of child nodes (for card, stack, row, grid)
    style     — optional inline style overrides
    ...       — type-specific props (see below)

  Example layout:
    {
      type: "card", title: "Contacts", icon: "👥",
      children: [
        { type: "grid", cols: 2, children: [
          { type: "card", variant: "subtle", children: [
            { type: "avatar", initials: "AB", color: "#7c8aff" },
            { type: "text", value: "Alice Bloom", variant: "h3" },
            { type: "badge", value: "online", color: "green" },
          ]},
          { type: "card", variant: "subtle", children: [
            { type: "avatar", initials: "CK", color: "#25d366" },
            { type: "text", value: "Charlie Kim", variant: "h3" },
            { type: "badge", value: "offline", color: "dim" },
          ]},
        ]},
      ],
    }
-->
<!-- svelte-ignore export_let_unused -->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  const BRAIN = 'http://127.0.0.1:8000';

  // The layout tree — either passed directly or fetched from an organ
  let layout = props?.layout || null;
  let title = props?.title || 'Data View';
  let organId = props?.organ_id || null;
  let autoRefresh = props?.auto_refresh || false;
  let refreshInterval = props?.refresh_interval || 10000;
  let loading = !layout;
  let error = null;
  let timer = null;

  onMount(() => {
    if (!layout && organId) {
      fetchAndBuildLayout();
      if (autoRefresh) {
        timer = setInterval(fetchAndBuildLayout, refreshInterval);
      }
    } else if (!layout && !organId) {
      // Dashboard mode — fetch from all organs
      fetchAllOrgansLayout();
    }
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });

  async function fetchAllOrgansLayout() {
    loading = true;
    error = null;
    try {
      const r = await fetch(BRAIN + '/organs-data/all');
      const json = await r.json();
      const datasets = json.data || [];

      if (datasets.length === 0) {
        layout = {
          type: 'card', title: 'Dashboard', icon: '📊',
          children: [
            { type: 'text', value: 'No scraped data from any organ yet.', variant: 'caption' },
            { type: 'text', value: 'Use the Organ Manager to open sites and define scrape patterns.', variant: 'caption' },
          ],
        };
      } else {
        // Group by organ
        var byOrgan = {};
        for (var i = 0; i < datasets.length; i++) {
          var d = datasets[i];
          var oid = d.organ_id || 'unknown';
          if (!byOrgan[oid]) byOrgan[oid] = { name: d.organ_name || oid, datasets: [] };
          byOrgan[oid].datasets.push(d);
        }
        var organSections = [];
        var organIds = Object.keys(byOrgan);
        for (var k = 0; k < organIds.length; k++) {
          var info = byOrgan[organIds[k]];
          organSections.push({
            type: 'card', title: info.name, icon: '🧬', variant: 'subtle',
            children: buildAutoLayout(organIds[k], info.datasets).children,
          });
        }
        layout = { type: 'stack', gap: 10, children: organSections };
      }
      loading = false;
    } catch (e) {
      error = (e && e.message) ? e.message : 'Failed to fetch';
      loading = false;
    }
  }

  async function fetchAndBuildLayout() {
    loading = true;
    error = null;
    try {
      const r = await fetch(BRAIN + '/organs/' + encodeURIComponent(organId) + '/data');
      const json = await r.json();
      const datasets = json.data || [];

      if (datasets.length === 0) {
        layout = {
          type: 'card', title: organId, icon: '📭',
          children: [
            { type: 'text', value: 'No scraped data yet.', variant: 'caption' },
            { type: 'text', value: 'Open the Organ Manager, define patterns, then come back.', variant: 'caption' },
          ],
        };
      } else {
        // Auto-generate a beautiful layout from the scraped datasets
        layout = buildAutoLayout(organId, datasets);
      }
      loading = false;
    } catch (e) {
      error = (e && e.message) ? e.message : 'Failed to fetch';
      loading = false;
    }
  }

  function buildAutoLayout(organId, datasets) {
    var children = [];

    for (var i = 0; i < datasets.length; i++) {
      var ds = datasets[i];
      var className = ds.class_name || 'data';
      var values = ds.values || [];
      var count = ds.count || values.length;

      // Section header
      children.push({
        type: 'row', gap: 8, align: 'center',
        children: [
          { type: 'text', value: className, variant: 'label' },
          { type: 'badge', value: count + ' items', color: 'blue' },
        ],
      });

      if (values.length === 0) {
        children.push({ type: 'text', value: 'No data scraped yet', variant: 'caption' });
      } else {
        // Detect if values are structured objects or flat strings
        var isStructured = values.length > 0 && typeof values[0] === 'object' && values[0] !== null;

        if (isStructured) {
          // ── Structured data: render as rich cards ──
          var cards = [];
          var displayValues = values.slice(0, 50);
          for (var j = 0; j < displayValues.length; j++) {
            cards.push(buildStructuredCard(displayValues[j]));
          }
          // Use grid for small sets, stack for larger
          if (cards.length <= 4) {
            children.push({
              type: 'grid', cols: cards.length <= 2 ? cards.length : 2,
              gap: 8, children: cards,
            });
          } else {
            children.push({
              type: 'stack', gap: 6, children: cards,
            });
          }
          if (values.length > 50) {
            children.push({ type: 'text', value: '… and ' + (values.length - 50) + ' more', variant: 'caption' });
          }
        } else {
          // ── Flat strings: original behavior ──
          if (values.length <= 6) {
            var flatCards = [];
            for (var k = 0; k < values.length; k++) {
              flatCards.push({
                type: 'card', variant: 'subtle', padding: 'sm',
                children: [
                  { type: 'text', value: String(values[k]), variant: 'body' },
                ],
              });
            }
            children.push({
              type: 'grid', cols: values.length <= 3 ? values.length : 2,
              gap: 6, children: flatCards,
            });
          } else {
            var stringItems = [];
            for (var m = 0; m < Math.min(30, values.length); m++) {
              stringItems.push(String(values[m]));
            }
            children.push({
              type: 'list', items: stringItems,
              ordered: false,
              more: values.length > 30 ? (values.length - 30) : 0,
            });
          }
        }
      }

      // Add divider between datasets (not after the last)
      if (i < datasets.length - 1) {
        children.push({ type: 'spacer', size: 4 });
        children.push({ type: 'divider' });
        children.push({ type: 'spacer', size: 4 });
      }
    }

    return {
      type: 'stack', gap: 8,
      children: children,
    };
  }

  /**
   * Build a rich card layout for a single structured data object.
   * Detects field types (avatar URLs, links, timestamps, plain text)
   * and renders them appropriately.
   */
  function buildStructuredCard(obj) {
    var cardChildren = [];
    var headerParts = [];
    var metaParts = [];
    var bodyPairs = [];

    var keys = Object.keys(obj);
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      var val = obj[key];
      if (!val || key.startsWith('__')) continue;
      val = String(val).trim();
      if (!val) continue;

      var keyLower = key.toLowerCase();

      // ── Detect field type by label name ──
      if (keyLower === 'avatar' || keyLower === 'avatar_url' || keyLower === 'image' || keyLower === 'profile_image') {
        // Avatar image — show as avatar circle with initials or as image
        if (val.startsWith('http')) {
          headerParts.push({ type: 'avatar', initials: '📷', color: 'rgba(100,180,255,0.2)', size: 'sm' });
        }
      } else if (keyLower === 'user' || keyLower === 'username' || keyLower === 'name'
                 || keyLower === 'title' || keyLower === 'heading'
                 || keyLower.match(/^title_\d+$/)) {
        // Primary identity — show as heading
        headerParts.push({ type: 'text', value: val, variant: 'h3' });
      } else if (keyLower === 'time' || keyLower === 'date' || keyLower === 'timestamp' || keyLower === 'datetime') {
        // Timestamp — show as muted caption
        metaParts.push({ type: 'text', value: formatTime(val), variant: 'caption' });
      } else if (keyLower === 'language' || keyLower === 'lang' || keyLower === 'type' || keyLower === 'status'
                 || keyLower === 'programminglanguage' || keyLower.endsWith('_language')) {
        // Category/type — show as badge
        var badgeColors = { 'python': 'blue', 'javascript': 'yellow', 'typescript': 'blue',
          'rust': 'red', 'go': 'cyan', 'java': 'red', 'ruby': 'red',
          'online': 'green', 'offline': 'dim', 'active': 'green', 'inactive': 'dim' };
        var bc = badgeColors[val.toLowerCase()] || 'purple';
        metaParts.push({ type: 'badge', value: val, color: bc });
      } else if (keyLower.endsWith('_url') || keyLower === 'url' || keyLower === 'href' || keyLower === 'link') {
        // URL — show as monospace link
        if (val.length > 5) {
          bodyPairs.push({ type: 'pair', key: key.replace(/_/g, ' '), value: val });
        }
      } else if (keyLower === 'repo' || keyLower === 'repository' || keyLower === 'repo_info') {
        // Repo name — show prominently
        headerParts.push({ type: 'text', value: val, variant: 'body',
          style: 'color: rgba(100,180,255,0.9); font-weight: 600;' });
      } else if (keyLower === 'description' || keyLower === 'bio' || keyLower === 'summary'
                 || keyLower === 'meta' || keyLower === 'h3' || keyLower === 'h4'
                 || keyLower === 'heading_1' || keyLower === 'detail') {
        // Descriptive/meta text — show as caption
        metaParts.push({ type: 'text', value: val, variant: 'caption' });
      } else {
        // Generic field — show as key:value pair
        var displayKey = key.replace(/_/g, ' ');
        // Skip very long values or very short meaningless ones
        if (val.length > 1 && val.length < 300) {
          bodyPairs.push({ type: 'pair', key: displayKey, value: val });
        }
      }
    }

    // Assemble card: header row, then meta row, then body pairs
    if (headerParts.length > 0) {
      cardChildren.push({
        type: 'row', gap: 8, align: 'center', wrap: true,
        children: headerParts,
      });
    }
    if (metaParts.length > 0) {
      cardChildren.push({
        type: 'row', gap: 6, align: 'center', wrap: true,
        children: metaParts,
      });
    }
    for (var p = 0; p < bodyPairs.length; p++) {
      cardChildren.push(bodyPairs[p]);
    }

    // Fallback: if nothing was extracted, show raw JSON
    if (cardChildren.length === 0) {
      cardChildren.push({ type: 'text', value: JSON.stringify(obj).substring(0, 200), variant: 'mono' });
    }

    return {
      type: 'card', variant: 'subtle', padding: 'sm',
      children: cardChildren,
    };
  }

  /**
   * Format an ISO timestamp into a human-friendly string.
   */
  function formatTime(val) {
    try {
      var d = new Date(val);
      if (isNaN(d.getTime())) return val;
      var now = new Date();
      var diffMs = now - d;
      var diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 1) return 'just now';
      if (diffMins < 60) return diffMins + 'm ago';
      var diffHrs = Math.floor(diffMins / 60);
      if (diffHrs < 24) return diffHrs + 'h ago';
      var diffDays = Math.floor(diffHrs / 24);
      if (diffDays < 7) return diffDays + 'd ago';
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch (e) {
      return val;
    }
  }

  // Color presets for badges
  function badgeColor(c) {
    if (c === 'green')  return { bg: 'rgba(37,211,102,0.15)', fg: 'rgba(37,211,102,0.9)' };
    if (c === 'red')    return { bg: 'rgba(255,95,87,0.15)',   fg: 'rgba(255,95,87,0.9)' };
    if (c === 'blue')   return { bg: 'rgba(100,180,255,0.12)', fg: 'rgba(100,180,255,0.9)' };
    if (c === 'yellow') return { bg: 'rgba(255,200,60,0.15)',  fg: 'rgba(255,200,60,0.9)' };
    if (c === 'purple') return { bg: 'rgba(167,139,250,0.15)', fg: 'rgba(167,139,250,0.9)' };
    if (c === 'cyan')   return { bg: 'rgba(0,200,255,0.12)',   fg: 'rgba(0,200,255,0.9)' };
    return { bg: 'rgba(255,255,255,0.06)', fg: 'rgba(255,255,255,0.5)' };
  }

  // Avatar background colors
  function avatarBg(c) {
    if (c) return c;
    return 'rgba(124,138,255,0.25)';
  }

  // Bar fill colors
  function barFillColor(c) {
    if (c === 'green')  return 'linear-gradient(90deg, #25d366, #1da851)';
    if (c === 'red')    return 'linear-gradient(90deg, #ff5f57, #e04440)';
    if (c === 'yellow') return 'linear-gradient(90deg, #ffbd2e, #e0a020)';
    if (c === 'purple') return 'linear-gradient(90deg, #a78bfa, #7c3aed)';
    return 'linear-gradient(90deg, #64b4ff, #3a8ee6)';
  }

  function truncate(s, n) {
    return s && s.length > n ? s.substring(0, n) + '…' : (s || '');
  }

  // Are we being rendered as a recursive node, or as the root widget?
  $: isNode = !!props?.__node;
</script>

{#if !isNode}
<!-- ═══════════════════════════════════════════════════════
     ROOT CONTAINER — only rendered at the top level
     ═══════════════════════════════════════════════════════ -->
<div class="dv-root">
  <button class="dismiss" on:click={onDismiss}>✕</button>

  <div class="dv-header">
    <div class="dv-title">{title}</div>
    {#if organId}
      <button class="dv-refresh" on:click={fetchAndBuildLayout} title="Refresh">↻</button>
    {:else if !organId && !layout}
      <button class="dv-refresh" on:click={fetchAllOrgansLayout} title="Refresh">↻</button>
    {/if}
  </div>

  <div class="dv-body">
    {#if loading}
      <div class="dv-empty">Loading…</div>
    {:else if error}
      <div class="dv-empty dv-error">❌ {error}</div>
    {:else if layout}
      <svelte:self props={{ __node: layout }} onDismiss={() => {}} />
    {:else}
      <div class="dv-empty">No layout defined</div>
    {/if}
  </div>
</div>

{:else}
<!-- ═══════════════════════════════════════════════════════
     RECURSIVE NODE RENDERER
     Each node type is rendered here. When DataViewWidget
     is instantiated with props.__node, it renders just
     that subtree (no header/dismiss). This is how nesting works.
     ═══════════════════════════════════════════════════════ -->
  {@const node = props.__node}

  <!-- ── CARD ── -->
  {#if node.type === 'card'}
    <div
      class="n-card"
      class:n-card-subtle={node.variant === 'subtle'}
      class:n-card-outline={node.variant === 'outline'}
      class:n-card-ghost={node.variant === 'ghost'}
      class:n-pad-sm={node.padding === 'sm'}
      class:n-pad-lg={node.padding === 'lg'}
      class:n-pad-none={node.padding === 'none'}
      style={node.style || ''}
    >
      {#if node.icon || node.title || node.subtitle}
        <div class="n-card-head">
          {#if node.icon}
            <span class="n-card-icon">{node.icon}</span>
          {/if}
          <div class="n-card-titles">
            {#if node.title}
              <div class="n-card-title">{node.title}</div>
            {/if}
            {#if node.subtitle}
              <div class="n-card-sub">{node.subtitle}</div>
            {/if}
          </div>
        </div>
      {/if}
      {#if node.children}
        {#each node.children as child}
          <svelte:self props={{ __node: child }} onDismiss={() => {}} />
        {/each}
      {/if}
    </div>

  <!-- ── STACK (vertical) ── -->
  {:else if node.type === 'stack'}
    <div class="n-stack" style="gap:{node.gap || 6}px;{node.style || ''}">
      {#if node.children}
        {#each node.children as child}
          <svelte:self props={{ __node: child }} onDismiss={() => {}} />
        {/each}
      {/if}
    </div>

  <!-- ── ROW (horizontal) ── -->
  {:else if node.type === 'row'}
    <div
      class="n-row"
      style="gap:{node.gap || 8}px;
             justify-content:{node.justify || 'flex-start'};
             align-items:{node.align || 'flex-start'};
             flex-wrap:{node.wrap ? 'wrap' : 'nowrap'};
             {node.style || ''}"
    >
      {#if node.children}
        {#each node.children as child}
          <svelte:self props={{ __node: child }} onDismiss={() => {}} />
        {/each}
      {/if}
    </div>

  <!-- ── GRID ── -->
  {:else if node.type === 'grid'}
    <div
      class="n-grid"
      style="grid-template-columns:repeat({node.cols || 2}, 1fr);
             gap:{node.gap || 8}px;
             {node.style || ''}"
    >
      {#if node.children}
        {#each node.children as child}
          <svelte:self props={{ __node: child }} onDismiss={() => {}} />
        {/each}
      {/if}
    </div>

  <!-- ── TEXT ── -->
  {:else if node.type === 'text'}
    {#if node.variant === 'h1'}
      <div class="n-text n-h1" style={node.style || ''}>{node.value || ''}</div>
    {:else if node.variant === 'h2'}
      <div class="n-text n-h2" style={node.style || ''}>{node.value || ''}</div>
    {:else if node.variant === 'h3'}
      <div class="n-text n-h3" style={node.style || ''}>{node.value || ''}</div>
    {:else if node.variant === 'caption'}
      <div class="n-text n-caption" style={node.style || ''}>{node.value || ''}</div>
    {:else if node.variant === 'mono'}
      <div class="n-text n-mono" style={node.style || ''}>{node.value || ''}</div>
    {:else if node.variant === 'label'}
      <div class="n-text n-label" style={node.style || ''}>{node.value || ''}</div>
    {:else}
      <div class="n-text n-body" style={node.style || ''}>{node.value || ''}</div>
    {/if}

  <!-- ── BADGE ── -->
  {:else if node.type === 'badge'}
    {@const bc = badgeColor(node.color)}
    <span class="n-badge" style="background:{bc.bg}; color:{bc.fg}; {node.style || ''}">{node.value || ''}</span>

  <!-- ── LIST ── -->
  {:else if node.type === 'list'}
    <div class="n-list" style={node.style || ''}>
      {#each (node.items || []) as item, i}
        <div class="n-list-item">
          <span class="n-list-marker">{node.ordered ? (i + 1) + '.' : '·'}</span>
          <span class="n-list-text">{item}</span>
        </div>
      {/each}
      {#if node.more && node.more > 0}
        <div class="n-list-more">… and {node.more} more</div>
      {/if}
    </div>

  <!-- ── DIVIDER ── -->
  {:else if node.type === 'divider'}
    <div class="n-divider" style={node.style || ''}></div>

  <!-- ── AVATAR ── -->
  {:else if node.type === 'avatar'}
    <div
      class="n-avatar"
      class:n-avatar-sm={node.size === 'sm'}
      class:n-avatar-lg={node.size === 'lg'}
      style="background:{avatarBg(node.color)}; {node.style || ''}"
    >
      {node.initials || node.emoji || '?'}
    </div>

  <!-- ── STAT ── -->
  {:else if node.type === 'stat'}
    <div class="n-stat" style={node.style || ''}>
      <div class="n-stat-value" style="color:{node.color || 'rgba(100,180,255,0.95)'}">
        {node.value || '0'}
      </div>
      <div class="n-stat-label">{node.label || ''}</div>
    </div>

  <!-- ── BAR ── -->
  {:else if node.type === 'bar'}
    <div class="n-bar-wrap" style={node.style || ''}>
      {#if node.label}
        <div class="n-bar-head">
          <span class="n-bar-label">{node.label}</span>
          <span class="n-bar-pct">{node.percent || 0}%</span>
        </div>
      {/if}
      <div class="n-bar-track">
        <div
          class="n-bar-fill"
          style="width:{Math.min(100, Math.max(0, node.percent || 0))}%;
                 background:{barFillColor(node.color)}"
        ></div>
      </div>
    </div>

  <!-- ── IMAGE (placeholder) ── -->
  {:else if node.type === 'image'}
    <div class="n-image" style="aspect-ratio:{node.ratio || '16/9'}; {node.style || ''}">
      <span class="n-image-alt">{node.alt || '🖼'}</span>
    </div>

  <!-- ── SPACER ── -->
  {:else if node.type === 'spacer'}
    <div style="height:{node.size || 8}px"></div>

  <!-- ── PAIR (key: value) ── -->
  {:else if node.type === 'pair'}
    <div class="n-pair" style={node.style || ''}>
      <span class="n-pair-key">{node.key || ''}</span>
      <span class="n-pair-val">{node.value || ''}</span>
    </div>

  <!-- ── UNKNOWN ── -->
  {:else}
    <div class="n-unknown">? {node.type}</div>
  {/if}
{/if}


<style>
  /* ═══════════════════════════════════════════════
     ROOT CONTAINER (only rendered for top-level)
     ═══════════════════════════════════════════════ */
  .dv-root {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    color: rgba(255,255,255,0.9);
    padding: 10px 14px;
    box-sizing: border-box;
    overflow: hidden;
  }
  .dv-root :global(*) { box-sizing: border-box; }

  .dismiss {
    position: absolute; top: 6px; right: 10px;
    background: none; border: none; color: rgba(255,255,255,0.3);
    font-size: 14px; cursor: pointer; z-index: 10;
    padding: 2px 6px; border-radius: 4px;
  }
  .dismiss:hover { color: #ff5f57; background: rgba(255,95,87,0.12); }

  .dv-header {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 8px; flex-shrink: 0;
  }
  .dv-title {
    font-size: 13px; font-weight: 700;
    color: rgba(255,255,255,0.92);
    flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .dv-refresh {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.5); font-size: 14px; width: 26px; height: 26px;
    border-radius: 6px; cursor: pointer; display: flex; align-items: center;
    justify-content: center; flex-shrink: 0;
  }
  .dv-refresh:hover { color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.1); }

  .dv-body {
    flex: 1; overflow-y: auto; overflow-x: hidden;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.1) transparent;
  }

  .dv-empty {
    display: flex; align-items: center; justify-content: center;
    height: 100%; font-size: 12px; color: rgba(255,255,255,0.25);
    text-align: center; padding: 20px;
  }
  .dv-error { color: rgba(255,95,87,0.6); }

  /* ═══════════════════════════════════════════════
     NODE PRIMITIVES — must be :global because
     svelte:self recursion creates new component
     instances, and scoped styles don't cross
     component boundaries.
     ═══════════════════════════════════════════════ */

  /* ── CARD ── */
  :global(.n-card) {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 10px;
    padding: 12px;
    display: flex; flex-direction: column; gap: 6px;
    min-width: 0;
  }
  :global(.n-card-subtle) {
    background: rgba(255,255,255,0.025);
    border-color: rgba(255,255,255,0.05);
    border-radius: 8px;
  }
  :global(.n-card-outline) {
    background: transparent;
    border-color: rgba(255,255,255,0.1);
  }
  :global(.n-card-ghost) {
    background: transparent;
    border-color: transparent;
    padding: 4px 0;
  }
  :global(.n-pad-sm) { padding: 8px; }
  :global(.n-pad-lg) { padding: 16px; }
  :global(.n-pad-none) { padding: 0; }

  :global(.n-card-head) {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 4px;
  }
  :global(.n-card-icon) { font-size: 16px; flex-shrink: 0; }
  :global(.n-card-titles) { flex: 1; min-width: 0; }
  :global(.n-card-title) {
    font-size: 12px; font-weight: 700;
    color: rgba(255,255,255,0.9);
    letter-spacing: 0.2px;
  }
  :global(.n-card-sub) {
    font-size: 10px; color: rgba(255,255,255,0.35);
    margin-top: 1px;
  }

  /* ── STACK ── */
  :global(.n-stack) {
    display: flex; flex-direction: column;
    min-width: 0;
  }

  /* ── ROW ── */
  :global(.n-row) {
    display: flex; flex-direction: row;
    min-width: 0;
  }

  /* ── GRID ── */
  :global(.n-grid) {
    display: grid;
    min-width: 0;
  }

  /* ── TEXT ── */
  :global(.n-text) {
    min-width: 0; word-break: break-word;
  }
  :global(.n-h1) {
    font-size: 20px; font-weight: 800;
    color: rgba(255,255,255,0.95);
    letter-spacing: -0.3px; line-height: 1.2;
  }
  :global(.n-h2) {
    font-size: 15px; font-weight: 700;
    color: rgba(255,255,255,0.9);
    letter-spacing: -0.1px; line-height: 1.3;
  }
  :global(.n-h3) {
    font-size: 12.5px; font-weight: 600;
    color: rgba(255,255,255,0.85);
    line-height: 1.3;
  }
  :global(.n-body) {
    font-size: 12px;
    color: rgba(255,255,255,0.75);
    line-height: 1.5;
  }
  :global(.n-caption) {
    font-size: 10.5px;
    color: rgba(255,255,255,0.35);
    line-height: 1.4;
  }
  :global(.n-mono) {
    font-size: 11px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    color: rgba(100,180,255,0.8);
    line-height: 1.5;
    background: rgba(0,0,0,0.2);
    padding: 2px 6px; border-radius: 4px;
    display: inline-block;
  }
  :global(.n-label) {
    font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.8px;
    color: rgba(255,255,255,0.4);
  }

  /* ── BADGE ── */
  :global(.n-badge) {
    display: inline-flex; align-items: center;
    font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 20px;
    letter-spacing: 0.2px;
    white-space: nowrap;
    line-height: 1.4;
  }

  /* ── LIST ── */
  :global(.n-list) {
    display: flex; flex-direction: column; gap: 2px;
  }
  :global(.n-list-item) {
    display: flex; align-items: baseline; gap: 8px;
    padding: 3px 6px;
    border-radius: 4px;
    transition: background 0.1s;
  }
  :global(.n-list-item:hover) { background: rgba(255,255,255,0.03); }
  :global(.n-list-marker) {
    color: rgba(255,255,255,0.2);
    font-size: 12px; flex-shrink: 0;
    width: 16px; text-align: right;
  }
  :global(.n-list-text) {
    font-size: 12px; color: rgba(255,255,255,0.75);
    line-height: 1.5; min-width: 0;
    word-break: break-word;
  }
  :global(.n-list-more) {
    font-size: 10px; color: rgba(255,255,255,0.2);
    text-align: center; padding: 4px;
  }

  /* ── DIVIDER ── */
  :global(.n-divider) {
    height: 1px;
    background: rgba(255,255,255,0.06);
    margin: 2px 0;
  }

  /* ── AVATAR ── */
  :global(.n-avatar) {
    width: 36px; height: 36px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700;
    color: rgba(255,255,255,0.9);
    flex-shrink: 0;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  :global(.n-avatar-sm) { width: 26px; height: 26px; font-size: 10px; }
  :global(.n-avatar-lg) { width: 48px; height: 48px; font-size: 17px; }

  /* ── STAT ── */
  :global(.n-stat) {
    display: flex; flex-direction: column;
    align-items: center; gap: 2px;
    padding: 8px 4px;
  }
  :global(.n-stat-value) {
    font-size: 28px; font-weight: 800;
    letter-spacing: -1px; line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  :global(.n-stat-label) {
    font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px;
    color: rgba(255,255,255,0.35);
  }

  /* ── BAR ── */
  :global(.n-bar-wrap) {
    display: flex; flex-direction: column; gap: 3px;
  }
  :global(.n-bar-head) {
    display: flex; justify-content: space-between; align-items: center;
  }
  :global(.n-bar-label) {
    font-size: 10.5px; color: rgba(255,255,255,0.5);
  }
  :global(.n-bar-pct) {
    font-size: 10.5px; font-weight: 700;
    color: rgba(255,255,255,0.6);
    font-variant-numeric: tabular-nums;
  }
  :global(.n-bar-track) {
    height: 6px; border-radius: 3px;
    background: rgba(255,255,255,0.06);
    overflow: hidden;
  }
  :global(.n-bar-fill) {
    height: 100%; border-radius: 3px;
    transition: width 0.4s cubic-bezier(0.16,1,0.3,1);
  }

  /* ── IMAGE ── */
  :global(.n-image) {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden;
    min-height: 40px;
  }
  :global(.n-image-alt) {
    font-size: 20px; color: rgba(255,255,255,0.15);
  }

  /* ── PAIR ── */
  :global(.n-pair) {
    display: flex; align-items: baseline; gap: 8px;
    padding: 2px 0;
  }
  :global(.n-pair-key) {
    font-size: 10.5px; font-weight: 600;
    color: rgba(255,255,255,0.4);
    flex-shrink: 0;
    min-width: 60px;
  }
  :global(.n-pair-val) {
    font-size: 12px; color: rgba(255,255,255,0.8);
    min-width: 0; word-break: break-word;
  }

  /* ── UNKNOWN ── */
  :global(.n-unknown) {
    font-size: 10px; color: rgba(255,95,87,0.5);
    font-style: italic;
  }
</style>
