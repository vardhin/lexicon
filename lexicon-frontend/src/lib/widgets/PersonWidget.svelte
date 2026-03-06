<!--
  PersonWidget.svelte — Entity/Person node dashboard.

  Fetches resolved entity nodes from the Brain and renders them as
  rich profile cards using the DataView meta node primitives.

  Modes:
    - List mode (default): shows all entities in a searchable grid
    - Detail mode (props.entity_id): shows a single entity's full profile

  Conventions:
    - All root elements have lx-* CSS anchor classes for theme injection
    - All inner layout is composed from DataView meta node primitives
      (card, stack, row, grid, avatar, text, badge, pair, stat, divider)
    - The widget uses svelte:self recursion through DataViewWidget for
      rendering the layout tree
    - Accepts props: { entity_id?, title?, auto_refresh?, refresh_interval? }

  Props:
    entity_id       — (optional) show a single entity. Omit for list mode.
    title           — (optional) custom widget title
    auto_refresh    — (optional) poll for updates
    refresh_interval — (optional) poll interval in ms (default 15000)
-->
<!-- svelte-ignore export_let_unused -->
<script>
  import { onMount, onDestroy } from 'svelte';
  import DataViewWidget from './DataViewWidget.svelte';

  export let props = {};
  export let onDismiss = () => {};

  const BRAIN = 'http://127.0.0.1:8000';

  let entityId = props?.entity_id || null;
  let title = props?.title || (entityId ? '👤 Person' : '👥 People');
  let autoRefresh = props?.auto_refresh || false;
  let refreshInterval = props?.refresh_interval || 15000;
  let initialSearchQuery = props?.search_query || '';

  let loading = true;
  let error = null;
  let timer = null;

  // List mode state
  let entities = [];
  let stats = {};
  let searchQuery = initialSearchQuery;
  let selectedEntity = null;

  // Detail mode state
  let entity = null;

  onMount(() => {
    if (entityId) {
      fetchEntity(entityId);
    } else if (initialSearchQuery) {
      searchEntities();
    } else {
      fetchEntities();
    }
    if (autoRefresh) {
      timer = setInterval(() => {
        if (selectedEntity) {
          fetchEntity(selectedEntity.entity_id);
        } else if (entityId) {
          fetchEntity(entityId);
        } else {
          fetchEntities();
        }
      }, refreshInterval);
    }
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });

  async function fetchEntities() {
    loading = true;
    error = null;
    try {
      const r = await fetch(BRAIN + '/entities');
      const json = await r.json();
      entities = json.entities || [];
      stats = json.stats || {};
      loading = false;
    } catch (e) {
      error = e.message || 'Failed to fetch entities';
      loading = false;
    }
  }

  async function fetchEntity(eid) {
    loading = true;
    error = null;
    try {
      const r = await fetch(BRAIN + '/entities/' + encodeURIComponent(eid));
      const json = await r.json();
      if (json.error) {
        error = json.error;
      } else {
        entity = json.entity;
        if (!entityId) {
          // We're in list mode but viewing a detail — update selected
          selectedEntity = entity;
        }
      }
      loading = false;
    } catch (e) {
      error = e.message || 'Failed to fetch entity';
      loading = false;
    }
  }

  async function searchEntities() {
    if (!searchQuery.trim()) {
      fetchEntities();
      return;
    }
    loading = true;
    error = null;
    try {
      const r = await fetch(BRAIN + '/entities/search/' + encodeURIComponent(searchQuery.trim()));
      const json = await r.json();
      entities = json.results || [];
      loading = false;
    } catch (e) {
      error = e.message || 'Search failed';
      loading = false;
    }
  }

  async function resolveAll() {
    loading = true;
    try {
      await fetch(BRAIN + '/entities/resolve', { method: 'POST' });
      await fetchEntities();
    } catch (e) {
      error = e.message || 'Resolution failed';
      loading = false;
    }
  }

  function selectEntity(ent) {
    selectedEntity = ent;
    entity = ent;
  }

  function backToList() {
    selectedEntity = null;
    entity = null;
    fetchEntities();
  }

  function getInitials(name) {
    if (!name) return '?';
    var parts = name.split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.substring(0, 2).toUpperCase();
  }

  function getAvatarColor(name) {
    if (!name) return 'rgba(124,138,255,0.25)';
    var hash = 0;
    for (var i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    var hue = Math.abs(hash) % 360;
    return 'hsla(' + hue + ', 60%, 50%, 0.25)';
  }

  function formatSourceLabel(src) {
    var organ = src.organ_id || 'unknown';
    var cls = src.class_name || '';
    return cls ? organ + ' / ' + cls : organ;
  }

  function pluralize(n, singular, plural) {
    return n === 1 ? n + ' ' + singular : n + ' ' + (plural || singular + 's');
  }

  // Build a layout tree for a single entity (detail view)
  function buildDetailLayout(ent) {
    var children = [];

    // ── Header: avatar + name + aliases ──
    var avatarUrl = (ent.avatars && ent.avatars.length > 0) ? ent.avatars[0] : null;
    var headerChildren = [];

    if (avatarUrl) {
      headerChildren.push({ type: 'avatar', imgUrl: avatarUrl, size: 'lg' });
    } else {
      headerChildren.push({
        type: 'avatar', initials: getInitials(ent.canonical_name),
        color: getAvatarColor(ent.canonical_name), size: 'lg',
      });
    }

    var nameStack = [
      { type: 'text', value: ent.canonical_name || 'Unknown', variant: 'h1' },
    ];

    // Aliases (excluding the canonical name itself)
    var otherAliases = (ent.aliases || []).filter(function (a) {
      return a.toLowerCase() !== (ent.canonical_name || '').toLowerCase();
    });
    if (otherAliases.length > 0) {
      nameStack.push({
        type: 'text', value: 'aka ' + otherAliases.join(', '), variant: 'caption',
      });
    }

    headerChildren.push({ type: 'stack', gap: 2, children: nameStack });

    children.push({
      type: 'row', gap: 12, align: 'center',
      children: headerChildren,
    });

    // ── Badges: source count, multi-source indicator ──
    var badgeRow = [];
    var sourceCount = (ent.sources || []).length;
    if (sourceCount > 0) {
      badgeRow.push({ type: 'badge', value: pluralize(sourceCount, 'source'), color: 'blue' });
    }
    if (sourceCount > 1) {
      badgeRow.push({ type: 'badge', value: '✦ cross-linked', color: 'purple' });
    }
    if (badgeRow.length > 0) {
      children.push({ type: 'row', gap: 6, wrap: true, children: badgeRow });
    }

    children.push({ type: 'divider' });

    // ── Usernames ──
    if (ent.usernames && ent.usernames.length > 0) {
      var usernameBadges = [];
      for (var i = 0; i < ent.usernames.length; i++) {
        usernameBadges.push({ type: 'badge', value: '@' + ent.usernames[i], color: 'cyan' });
      }
      children.push({
        type: 'stack', gap: 4, children: [
          { type: 'text', value: 'HANDLES', variant: 'label' },
          { type: 'row', gap: 4, wrap: true, children: usernameBadges },
        ],
      });
    }

    // ── Contact info ──
    var contactPairs = [];
    if (ent.phones && ent.phones.length > 0) {
      for (var j = 0; j < ent.phones.length; j++) {
        contactPairs.push({ type: 'pair', key: '📞 Phone', value: ent.phones[j] });
      }
    }
    if (ent.emails && ent.emails.length > 0) {
      for (var k = 0; k < ent.emails.length; k++) {
        contactPairs.push({ type: 'pair', key: '📧 Email', value: ent.emails[k] });
      }
    }
    if (contactPairs.length > 0) {
      children.push({
        type: 'stack', gap: 4, children: [
          { type: 'text', value: 'CONTACT', variant: 'label' },
          ...contactPairs,
        ],
      });
    }

    // ── Avatar gallery (if multiple) ──
    if (ent.avatars && ent.avatars.length > 1) {
      var avatarNodes = [];
      for (var a = 0; a < ent.avatars.length; a++) {
        avatarNodes.push({ type: 'avatar', imgUrl: ent.avatars[a], size: 'sm' });
      }
      children.push({
        type: 'stack', gap: 4, children: [
          { type: 'text', value: 'AVATARS', variant: 'label' },
          { type: 'row', gap: 6, wrap: true, children: avatarNodes },
        ],
      });
    }

    children.push({ type: 'divider' });

    // ── Sources: where this person was seen ──
    if (ent.sources && ent.sources.length > 0) {
      var sourceCards = [];
      // Group by organ_id
      var byOrgan = {};
      for (var s = 0; s < ent.sources.length; s++) {
        var src = ent.sources[s];
        var oid = src.organ_id || 'unknown';
        if (!byOrgan[oid]) byOrgan[oid] = [];
        byOrgan[oid].push(src);
      }

      var organIds = Object.keys(byOrgan);
      for (var o = 0; o < organIds.length; o++) {
        var oSources = byOrgan[organIds[o]];
        var sourceChildren = [
          {
            type: 'row', gap: 6, align: 'center', children: [
              { type: 'text', value: '🧬', variant: 'body' },
              { type: 'text', value: organIds[o], variant: 'h3' },
              { type: 'badge', value: pluralize(oSources.length, 'record'), color: 'dim' },
            ],
          },
        ];

        // Show class names
        var classNames = {};
        for (var cs = 0; cs < oSources.length; cs++) {
          var cn = oSources[cs].class_name || 'data';
          classNames[cn] = (classNames[cn] || 0) + 1;
        }
        var classBadges = [];
        var cnKeys = Object.keys(classNames);
        for (var ci = 0; ci < cnKeys.length; ci++) {
          classBadges.push({
            type: 'badge',
            value: cnKeys[ci] + ' (' + classNames[cnKeys[ci]] + ')',
            color: 'blue',
          });
        }
        if (classBadges.length > 0) {
          sourceChildren.push({ type: 'row', gap: 4, wrap: true, children: classBadges });
        }

        sourceCards.push({
          type: 'card', variant: 'subtle', padding: 'sm',
          children: sourceChildren,
        });
      }

      children.push({
        type: 'stack', gap: 4, children: [
          { type: 'text', value: 'SOURCES', variant: 'label' },
          ...sourceCards,
        ],
      });
    }

    return { type: 'stack', gap: 10, children: children };
  }

  // Build a layout tree for the entity list view
  function buildListLayout() {
    var children = [];

    // Stats bar
    var totalEntities = stats.total_entities || entities.length;
    var multiSource = stats.multi_source_entities || 0;

    children.push({
      type: 'row', gap: 12, align: 'center', justify: 'center',
      children: [
        { type: 'stat', value: String(totalEntities), label: 'People', color: 'rgba(124,138,255,0.95)' },
        { type: 'stat', value: String(multiSource), label: 'Cross-linked', color: 'rgba(167,139,250,0.95)' },
      ],
    });

    children.push({ type: 'divider' });

    // Entity cards
    if (entities.length === 0) {
      children.push({
        type: 'card', variant: 'ghost',
        children: [
          { type: 'text', value: 'No entities resolved yet.', variant: 'caption' },
          { type: 'text', value: 'Scrape data from organs — entities are auto-resolved.', variant: 'caption' },
        ],
      });
    } else {
      var cards = [];
      for (var i = 0; i < entities.length; i++) {
        var ent = entities[i];
        cards.push(buildEntityCard(ent));
      }

      // Grid for few, stack for many
      if (cards.length <= 6) {
        children.push({
          type: 'grid', cols: cards.length <= 3 ? cards.length : 3, gap: 8,
          children: cards,
        });
      } else {
        children.push({
          type: 'grid', cols: 3, gap: 8,
          children: cards,
        });
      }
    }

    return { type: 'stack', gap: 8, children: children };
  }

  // Build a compact entity card for the list view
  function buildEntityCard(ent) {
    var avatarUrl = (ent.avatars && ent.avatars.length > 0) ? ent.avatars[0] : null;
    var cardChildren = [];

    // Avatar + name row
    var headerChildren = [];
    if (avatarUrl) {
      headerChildren.push({ type: 'avatar', imgUrl: avatarUrl, size: 'sm' });
    } else {
      headerChildren.push({
        type: 'avatar', initials: getInitials(ent.canonical_name),
        color: getAvatarColor(ent.canonical_name), size: 'sm',
      });
    }
    headerChildren.push({
      type: 'text', value: ent.canonical_name || 'Unknown', variant: 'h3',
    });
    cardChildren.push({
      type: 'row', gap: 6, align: 'center', children: headerChildren,
    });

    // Username badges
    if (ent.usernames && ent.usernames.length > 0) {
      var uBadges = [];
      for (var u = 0; u < Math.min(2, ent.usernames.length); u++) {
        uBadges.push({ type: 'badge', value: '@' + ent.usernames[u], color: 'cyan' });
      }
      if (ent.usernames.length > 2) {
        uBadges.push({ type: 'badge', value: '+' + (ent.usernames.length - 2), color: 'dim' });
      }
      cardChildren.push({ type: 'row', gap: 4, wrap: true, children: uBadges });
    }

    // Source count
    var sourceCount = (ent.sources || []).length;
    if (sourceCount > 0) {
      var metaChildren = [
        { type: 'badge', value: pluralize(sourceCount, 'source'), color: 'blue' },
      ];
      if (sourceCount > 1) {
        metaChildren.push({ type: 'badge', value: '✦', color: 'purple' });
      }
      cardChildren.push({ type: 'row', gap: 4, children: metaChildren });
    }

    return {
      type: 'card', variant: 'subtle', padding: 'sm',
      style: 'cursor: pointer;',
      children: cardChildren,
      // __entity_id is used by the click handler — not rendered
      __entity_id: ent.entity_id,
    };
  }

  $: listLayout = (!selectedEntity && !entityId) ? buildListLayout() : null;
  $: detailLayout = (selectedEntity || entity) ? buildDetailLayout(selectedEntity || entity) : null;
</script>

<div class="person-widget lx-person lx-widget">
  <button class="dismiss lx-dismiss" on:click={onDismiss}>✕</button>

  <div class="pw-header lx-person-header">
    {#if selectedEntity && !entityId}
      <button class="pw-back lx-person-back" on:click={backToList}>← Back</button>
    {/if}
    <div class="pw-title lx-person-title">{selectedEntity ? (selectedEntity.canonical_name || 'Person') : title}</div>
    <div class="pw-actions">
      {#if !selectedEntity && !entityId}
        <button class="pw-action lx-person-action" on:click={resolveAll} title="Re-resolve all entities">⟳</button>
      {/if}
    </div>
  </div>

  {#if !selectedEntity && !entityId}
    <div class="pw-search lx-person-search">
      <input
        class="pw-search-input lx-input"
        type="text"
        placeholder="Search people…"
        bind:value={searchQuery}
        on:input={searchEntities}
      />
    </div>
  {/if}

  <div class="pw-body lx-person-body">
    {#if loading}
      <div class="pw-empty lx-person-empty">Loading…</div>
    {:else if error}
      <div class="pw-empty pw-error lx-person-error">❌ {error}</div>
    {:else if detailLayout}
      <DataViewWidget props={{ __node: detailLayout }} onDismiss={() => {}} />
    {:else if listLayout}
      <!-- Render list with click handlers on entity cards -->
      <div class="pw-list">
        {#if entities.length === 0}
          <DataViewWidget props={{ __node: listLayout }} onDismiss={() => {}} />
        {:else}
          <!-- Stats -->
          <div class="pw-stats">
            <DataViewWidget
              props={{ __node: {
                type: 'row', gap: 12, align: 'center', justify: 'center',
                children: [
                  { type: 'stat', value: String(stats.total_entities || entities.length), label: 'People', color: 'rgba(124,138,255,0.95)' },
                  { type: 'stat', value: String(stats.multi_source_entities || 0), label: 'Cross-linked', color: 'rgba(167,139,250,0.95)' },
                ],
              }}}
              onDismiss={() => {}}
            />
          </div>

          <div class="pw-divider"></div>

          <!-- Clickable entity cards -->
          <div class="pw-grid" class:pw-grid-few={entities.length <= 3}>
            {#each entities as ent}
              <button class="pw-entity-card lx-person-card" on:click={() => selectEntity(ent)}>
                <div class="pw-card-inner">
                  {#if ent.avatars && ent.avatars.length > 0}
                    <div class="pw-avatar lx-person-avatar">
                      <img src={ent.avatars[0]} alt="" />
                    </div>
                  {:else}
                    <div class="pw-avatar pw-avatar-initials lx-person-avatar" style="background: {getAvatarColor(ent.canonical_name)}">
                      {getInitials(ent.canonical_name)}
                    </div>
                  {/if}

                  <div class="pw-card-info">
                    <div class="pw-card-name lx-person-name">{ent.canonical_name || 'Unknown'}</div>
                    {#if ent.usernames && ent.usernames.length > 0}
                      <div class="pw-card-handle lx-person-handle">@{ent.usernames[0]}</div>
                    {/if}
                  </div>

                  <div class="pw-card-meta">
                    {#if (ent.sources || []).length > 1}
                      <span class="pw-cross-badge lx-person-cross">✦</span>
                    {/if}
                    <span class="pw-source-count">{(ent.sources || []).length}</span>
                  </div>
                </div>
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {:else}
      <div class="pw-empty">No data</div>
    {/if}
  </div>
</div>

<style>
  /* ═══════════════════════════════════════════════
     ROOT — PersonWidget container
     All classes have lx-* anchors for theme injection.
     ═══════════════════════════════════════════════ */
  .person-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    color: rgba(255,255,255,0.92);
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    padding: 10px 14px;
    box-sizing: border-box;
    overflow: hidden;
  }

  .dismiss {
    position: absolute; top: 6px; right: 10px;
    background: none; border: none;
    color: rgba(255,255,255,0.3); font-size: 14px;
    cursor: pointer; z-index: 10;
    padding: 2px 6px; border-radius: 4px;
  }
  .dismiss:hover { color: #ff5f57; background: rgba(255,95,87,0.12); }

  /* ── Header ── */
  .pw-header {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 8px; flex-shrink: 0;
    min-height: 28px;
  }
  .pw-title {
    font-size: 13px; font-weight: 700;
    color: rgba(255,255,255,0.92);
    flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .pw-back {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.6); font-size: 11px;
    padding: 3px 10px; border-radius: 6px; cursor: pointer;
    font-family: inherit; flex-shrink: 0;
  }
  .pw-back:hover { color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.1); }
  .pw-actions { display: flex; gap: 4px; flex-shrink: 0; }
  .pw-action {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.5); font-size: 14px; width: 26px; height: 26px;
    border-radius: 6px; cursor: pointer; display: flex; align-items: center;
    justify-content: center; flex-shrink: 0;
  }
  .pw-action:hover { color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.1); }

  /* ── Search ── */
  .pw-search {
    margin-bottom: 8px; flex-shrink: 0;
  }
  .pw-search-input {
    width: 100%; padding: 6px 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    color: rgba(255,255,255,0.9);
    font-size: 12px;
    font-family: inherit;
    outline: none;
    box-sizing: border-box;
  }
  .pw-search-input::placeholder { color: rgba(255,255,255,0.25); }
  .pw-search-input:focus {
    border-color: rgba(124,138,255,0.4);
    background: rgba(255,255,255,0.06);
  }

  /* ── Body ── */
  .pw-body {
    flex: 1; overflow-y: auto; overflow-x: hidden;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.1) transparent;
  }

  .pw-empty {
    display: flex; align-items: center; justify-content: center;
    height: 100%; font-size: 12px; color: rgba(255,255,255,0.25);
    text-align: center; padding: 20px;
  }
  .pw-error { color: rgba(255,95,87,0.6); }

  /* ── Stats ── */
  .pw-stats { margin-bottom: 4px; }

  .pw-divider {
    height: 1px;
    background: rgba(255,255,255,0.06);
    margin: 4px 0 8px;
  }

  /* ── Entity card grid ── */
  .pw-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
  }
  .pw-grid-few {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  }

  .pw-entity-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
    padding: 10px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, transform 0.1s;
    text-align: left;
    font-family: inherit;
    color: inherit;
  }
  .pw-entity-card:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(124,138,255,0.2);
    transform: translateY(-1px);
  }
  .pw-entity-card:active {
    transform: translateY(0);
  }

  .pw-card-inner {
    display: flex; align-items: center; gap: 8px;
    min-width: 0;
  }

  .pw-avatar {
    width: 28px; height: 28px;
    border-radius: 50%;
    flex-shrink: 0;
    overflow: hidden;
    display: flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 700;
    color: rgba(255,255,255,0.9);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .pw-avatar img {
    width: 100%; height: 100%; object-fit: cover;
    border-radius: 50%;
  }

  .pw-card-info {
    flex: 1; min-width: 0;
  }
  .pw-card-name {
    font-size: 12px; font-weight: 600;
    color: rgba(255,255,255,0.85);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    line-height: 1.3;
  }
  .pw-card-handle {
    font-size: 10px;
    color: rgba(100,200,255,0.6);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    line-height: 1.3;
  }

  .pw-card-meta {
    display: flex; align-items: center; gap: 3px;
    flex-shrink: 0;
  }
  .pw-cross-badge {
    font-size: 10px;
    color: rgba(167,139,250,0.8);
  }
  .pw-source-count {
    font-size: 9px; font-weight: 600;
    color: rgba(255,255,255,0.25);
    background: rgba(255,255,255,0.05);
    padding: 1px 5px; border-radius: 8px;
  }

  /* ── List container ── */
  .pw-list {
    display: flex; flex-direction: column; gap: 4px;
  }
</style>
