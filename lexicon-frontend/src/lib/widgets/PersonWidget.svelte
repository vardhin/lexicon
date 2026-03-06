<!--
  PersonWidget.svelte — Entity/Person node dashboard.

  Features:
    - List mode: searchable grid of all entities with stats
    - Detail mode: full profile with expandable source data records
    - Delete: single entity delete button + clear all with confirmation
    - Each source record is individually expandable to inspect raw data
    - Organ name is shown as a field inside each data record

  Props:
    entity_id       — (optional) show a single entity. Omit for list mode.
    title           — (optional) custom widget title
    auto_refresh    — (optional) poll for updates
    refresh_interval — (optional) poll interval in ms (default 15000)
    search_query    — (optional) pre-fill search
-->
<!-- svelte-ignore export_let_unused -->
<script>
  import { onMount, onDestroy } from 'svelte';

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
  let confirmClear = false;

  // List mode state
  let entities = [];
  let stats = {};
  let searchQuery = initialSearchQuery;
  let selectedEntity = null;

  // Detail mode state
  let entity = null;

  // Track which source records are expanded (by index)
  let expandedSources = {};

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

  async function deleteEntity(eid) {
    try {
      await fetch(BRAIN + '/entities/' + encodeURIComponent(eid), { method: 'DELETE' });
      if (selectedEntity && selectedEntity.entity_id === eid) {
        selectedEntity = null;
        entity = null;
      }
      await fetchEntities();
    } catch (e) {
      error = e.message || 'Delete failed';
    }
  }

  async function clearAllEntities() {
    try {
      await fetch(BRAIN + '/entities', { method: 'DELETE' });
      entities = [];
      stats = {};
      selectedEntity = null;
      entity = null;
      confirmClear = false;
    } catch (e) {
      error = e.message || 'Clear failed';
    }
  }

  function selectEntity(ent) {
    selectedEntity = ent;
    entity = ent;
    expandedSources = {};
  }

  function backToList() {
    selectedEntity = null;
    entity = null;
    expandedSources = {};
    fetchEntities();
  }

  function toggleSource(idx) {
    expandedSources = { ...expandedSources, [idx]: !expandedSources[idx] };
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

  function pluralize(n, singular, plural) {
    return n === 1 ? n + ' ' + singular : n + ' ' + (plural || singular + 's');
  }

  /** Format raw data as a flat list of key-value pairs for display. */
  function flattenRaw(raw) {
    if (!raw) return [];
    if (typeof raw === 'string') return [{ key: 'value', val: raw }];
    if (typeof raw !== 'object') return [{ key: 'value', val: String(raw) }];
    var pairs = [];
    var keys = Object.keys(raw);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      var v = raw[k];
      if (v === null || v === undefined || v === '') continue;
      if (typeof v === 'object') {
        pairs.push({ key: k, val: JSON.stringify(v, null, 2), isJson: true });
      } else {
        var s = String(v);
        var isImg = isImageUrl(s);
        pairs.push({ key: k, val: s, isImage: isImg });
      }
    }
    return pairs;
  }

  /** Check if a URL points to an image (avatar/profile pic). */
  function isImageUrl(url) {
    if (!url) return false;
    if (url.startsWith('data:image/')) return true;
    if (url.startsWith('blob:')) return true;
    if (/\.(?:jpg|jpeg|png|gif|webp|svg|bmp|avif)(?:\?|#|$)/i.test(url)) return true;
    if (/(?:pps\.whatsapp\.net|avatars?\d*\.githubusercontent|pbs\.twimg|scontent|gravatar\.com\/avatar|cdn\.discord)/i.test(url)) return true;
    return false;
  }

  $: currentEntity = selectedEntity || entity;
  $: showingDetail = !!currentEntity;
  $: showingList = !showingDetail;
</script>

<div class="person-widget lx-person lx-widget">
  <button class="dismiss lx-dismiss" on:click={onDismiss}>✕</button>

  <!-- ═══ HEADER ═══ -->
  <div class="pw-header lx-person-header">
    {#if selectedEntity && !entityId}
      <button class="pw-back lx-person-back" on:click={backToList}>← Back</button>
    {/if}
    <div class="pw-title lx-person-title">
      {showingDetail ? (currentEntity.canonical_name || 'Person') : title}
    </div>
    <div class="pw-actions">
      {#if showingDetail}
        <button
          class="pw-action pw-action-danger lx-person-action"
          on:click={() => deleteEntity(currentEntity.entity_id)}
          title="Delete this person"
        >🗑</button>
      {:else}
        <button class="pw-action lx-person-action" on:click={resolveAll} title="Re-resolve all entities">⟳</button>
        {#if entities.length > 0}
          {#if confirmClear}
            <button class="pw-action pw-action-danger-confirm" on:click={clearAllEntities} title="Confirm clear all">Yes, clear all</button>
            <button class="pw-action" on:click={() => { confirmClear = false; }} title="Cancel">✕</button>
          {:else}
            <button class="pw-action pw-action-danger lx-person-action" on:click={() => { confirmClear = true; }} title="Clear all people">🗑</button>
          {/if}
        {/if}
      {/if}
    </div>
  </div>

  <!-- ═══ SEARCH (list mode only) ═══ -->
  {#if showingList}
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

  <!-- ═══ BODY ═══ -->
  <div class="pw-body lx-person-body">
    {#if loading}
      <div class="pw-empty lx-person-empty">Loading…</div>

    {:else if error}
      <div class="pw-empty pw-error lx-person-error">❌ {error}</div>

    <!-- ═══ DETAIL VIEW ═══ -->
    {:else if showingDetail}
      <div class="pw-detail">
        <!-- Avatar + name -->
        <div class="pw-detail-header">
          {#if currentEntity.avatars && currentEntity.avatars.length > 0}
            <div class="pw-avatar pw-avatar-lg lx-person-avatar">
              <img src={currentEntity.avatars[0]} alt="" />
            </div>
          {:else}
            <div class="pw-avatar pw-avatar-lg pw-avatar-initials lx-person-avatar"
                 style="background: {getAvatarColor(currentEntity.canonical_name)}">
              {getInitials(currentEntity.canonical_name)}
            </div>
          {/if}
          <div class="pw-detail-name-block">
            <div class="pw-detail-name lx-person-name">{currentEntity.canonical_name || 'Unknown'}</div>
            {#if currentEntity.aliases && currentEntity.aliases.filter(a => a.toLowerCase() !== (currentEntity.canonical_name || '').toLowerCase()).length > 0}
              <div class="pw-detail-aliases">
                aka {currentEntity.aliases.filter(a => a.toLowerCase() !== (currentEntity.canonical_name || '').toLowerCase()).join(', ')}
              </div>
            {/if}
          </div>
        </div>

        <!-- Badges -->
        <div class="pw-badge-row">
          {#if (currentEntity.sources || []).length > 0}
            <span class="pw-badge pw-badge-blue">{pluralize((currentEntity.sources || []).length, 'source')}</span>
          {/if}
          {#if (currentEntity.sources || []).length > 1}
            <span class="pw-badge pw-badge-purple">✦ cross-linked</span>
          {/if}
        </div>

        <div class="pw-divider"></div>

        <!-- Usernames -->
        {#if currentEntity.usernames && currentEntity.usernames.length > 0}
          <div class="pw-section">
            <div class="pw-section-label">HANDLES</div>
            <div class="pw-badge-row">
              {#each currentEntity.usernames as uname}
                <span class="pw-badge pw-badge-cyan">@{uname}</span>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Contact info -->
        {#if (currentEntity.phones && currentEntity.phones.length > 0) || (currentEntity.emails && currentEntity.emails.length > 0)}
          <div class="pw-section">
            <div class="pw-section-label">CONTACT</div>
            {#if currentEntity.phones}
              {#each currentEntity.phones as phone}
                <div class="pw-pair"><span class="pw-pair-key">📞 Phone</span><span class="pw-pair-val">{phone}</span></div>
              {/each}
            {/if}
            {#if currentEntity.emails}
              {#each currentEntity.emails as email}
                <div class="pw-pair"><span class="pw-pair-key">📧 Email</span><span class="pw-pair-val">{email}</span></div>
              {/each}
            {/if}
          </div>
        {/if}

        <!-- Avatar gallery -->
        {#if currentEntity.avatars && currentEntity.avatars.length > 1}
          <div class="pw-section">
            <div class="pw-section-label">AVATARS</div>
            <div class="pw-avatar-gallery">
              {#each currentEntity.avatars as av}
                <div class="pw-avatar pw-avatar-sm"><img src={av} alt="" /></div>
              {/each}
            </div>
          </div>
        {/if}

        <div class="pw-divider"></div>

        <!-- ═══ DATA RECORDS — all sources shown flat, visible at a glance ═══ -->
        {#if currentEntity.sources && currentEntity.sources.length > 0}
          <div class="pw-section">
            <div class="pw-section-label">DATA ({currentEntity.sources.length})</div>

            {#each currentEntity.sources as src, idx}
              <div class="pw-source-flat">
                <!-- Source header badge row -->
                <div class="pw-source-tag-row">
                  <span class="pw-source-idx">#{idx + 1}</span>
                  <span class="pw-badge pw-badge-dim">{src.organ_id || 'unknown'}</span>
                  {#if src.class_name}
                    <span class="pw-badge pw-badge-blue">{src.class_name}</span>
                  {/if}
                </div>

                <!-- All raw data fields — always visible -->
                <div class="pw-source-fields">
                  {#if src.raw}
                    {#each flattenRaw(src.raw) as field}
                      <div class="pw-data-pair" class:pw-data-pair-json={field.isJson}>
                        <span class="pw-data-key">{field.key}</span>
                        {#if field.isImage}
                          <img class="pw-data-img" src={field.val} alt="" />
                        {:else if field.isJson}
                          <pre class="pw-data-json">{field.val}</pre>
                        {:else}
                          <span class="pw-data-val">{field.val}</span>
                        {/if}
                      </div>
                    {/each}
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/if}

        <!-- Entity ID -->
        <div class="pw-section pw-section-meta">
          <div class="pw-pair">
            <span class="pw-pair-key">Entity ID</span>
            <span class="pw-pair-val pw-pair-mono">{currentEntity.entity_id}</span>
          </div>
        </div>
      </div>

    <!-- ═══ LIST VIEW ═══ -->
    {:else if showingList}
      <div class="pw-list">
        <div class="pw-stats-row">
          <div class="pw-stat">
            <span class="pw-stat-value">{stats.total_entities || entities.length}</span>
            <span class="pw-stat-label">People</span>
          </div>
          <div class="pw-stat">
            <span class="pw-stat-value pw-stat-purple">{stats.multi_source_entities || 0}</span>
            <span class="pw-stat-label">Cross-linked</span>
          </div>
          {#if stats.buffered_signals > 0}
            <div class="pw-stat">
              <span class="pw-stat-value pw-stat-amber">{stats.buffered_signals}</span>
              <span class="pw-stat-label">Buffered</span>
            </div>
          {/if}
        </div>

        <div class="pw-divider"></div>

        {#if entities.length === 0}
          <div class="pw-empty-hint">
            <div>No entities resolved yet.</div>
            <div class="pw-empty-sub">Scrape data from organs — entities are auto-resolved.</div>
          </div>
        {:else}
          <div class="pw-grid" class:pw-grid-few={entities.length <= 3}>
            {#each entities as ent}
              <button class="pw-entity-card lx-person-card" on:click={() => selectEntity(ent)}>
                <div class="pw-card-inner">
                  {#if ent.avatars && ent.avatars.length > 0}
                    <div class="pw-avatar lx-person-avatar">
                      <img src={ent.avatars[0]} alt="" />
                    </div>
                  {:else}
                    <div class="pw-avatar pw-avatar-initials lx-person-avatar"
                         style="background: {getAvatarColor(ent.canonical_name)}">
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
     ROOT
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
  .pw-actions { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
  .pw-action {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.5); font-size: 14px; width: 26px; height: 26px;
    border-radius: 6px; cursor: pointer; display: flex; align-items: center;
    justify-content: center; flex-shrink: 0; font-family: inherit;
  }
  .pw-action:hover { color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.1); }
  .pw-action-danger:hover { color: #ff5f57; background: rgba(255,95,87,0.12); border-color: rgba(255,95,87,0.2); }
  .pw-action-danger-confirm {
    background: rgba(255,95,87,0.15); border: 1px solid rgba(255,95,87,0.3);
    color: #ff5f57; font-size: 10px; width: auto; height: 26px;
    border-radius: 6px; cursor: pointer; display: flex; align-items: center;
    justify-content: center; flex-shrink: 0; padding: 0 10px;
    font-family: inherit; font-weight: 600;
  }
  .pw-action-danger-confirm:hover { background: rgba(255,95,87,0.25); }

  /* ── Search ── */
  .pw-search { margin-bottom: 8px; flex-shrink: 0; }
  .pw-search-input {
    width: 100%; padding: 6px 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    color: rgba(255,255,255,0.9);
    font-size: 12px; font-family: inherit;
    outline: none; box-sizing: border-box;
  }
  .pw-search-input::placeholder { color: rgba(255,255,255,0.25); }
  .pw-search-input:focus { border-color: rgba(124,138,255,0.4); background: rgba(255,255,255,0.06); }

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
  .pw-empty-hint {
    text-align: center; padding: 24px 16px;
    color: rgba(255,255,255,0.25); font-size: 12px;
  }
  .pw-empty-sub { margin-top: 4px; font-size: 11px; color: rgba(255,255,255,0.15); }

  .pw-divider {
    height: 1px; background: rgba(255,255,255,0.06);
    margin: 6px 0;
  }

  /* ── Stats row ── */
  .pw-stats-row {
    display: flex; gap: 16px; justify-content: center;
    padding: 4px 0;
  }
  .pw-stat { display: flex; flex-direction: column; align-items: center; gap: 1px; }
  .pw-stat-value {
    font-size: 18px; font-weight: 800;
    color: rgba(124,138,255,0.95);
    line-height: 1.2;
  }
  .pw-stat-purple { color: rgba(167,139,250,0.95); }
  .pw-stat-amber { color: rgba(251,191,36,0.85); }
  .pw-stat-label {
    font-size: 9px; font-weight: 600;
    color: rgba(255,255,255,0.3);
    text-transform: uppercase; letter-spacing: 0.5px;
  }

  /* ── Entity card grid ── */
  .pw-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
  }
  .pw-grid-few { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }

  .pw-entity-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px; padding: 10px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, transform 0.1s;
    text-align: left; font-family: inherit; color: inherit;
  }
  .pw-entity-card:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(124,138,255,0.2);
    transform: translateY(-1px);
  }
  .pw-entity-card:active { transform: translateY(0); }

  .pw-card-inner { display: flex; align-items: center; gap: 8px; min-width: 0; }

  .pw-avatar {
    width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
    overflow: hidden; display: flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 700;
    color: rgba(255,255,255,0.9);
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  .pw-avatar img { width: 100%; height: 100%; object-fit: cover; border-radius: 50%; }
  .pw-avatar-lg { width: 42px; height: 42px; font-size: 14px; }
  .pw-avatar-sm { width: 24px; height: 24px; font-size: 9px; }

  .pw-card-info { flex: 1; min-width: 0; }
  .pw-card-name {
    font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.85);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.3;
  }
  .pw-card-handle {
    font-size: 10px; color: rgba(100,200,255,0.6);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.3;
  }
  .pw-card-meta { display: flex; align-items: center; gap: 3px; flex-shrink: 0; }
  .pw-cross-badge { font-size: 10px; color: rgba(167,139,250,0.8); }
  .pw-source-count {
    font-size: 9px; font-weight: 600; color: rgba(255,255,255,0.25);
    background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 8px;
  }

  .pw-list { display: flex; flex-direction: column; gap: 4px; }

  /* ═══════════════════════════════════════════════
     DETAIL VIEW
     ═══════════════════════════════════════════════ */
  .pw-detail { display: flex; flex-direction: column; gap: 8px; }

  .pw-detail-header { display: flex; align-items: center; gap: 10px; }
  .pw-detail-name-block { flex: 1; min-width: 0; }
  .pw-detail-name {
    font-size: 16px; font-weight: 800; color: rgba(255,255,255,0.95); line-height: 1.25;
  }
  .pw-detail-aliases {
    font-size: 11px; color: rgba(255,255,255,0.3); margin-top: 2px;
    font-style: italic;
  }

  /* ── Section ── */
  .pw-section { display: flex; flex-direction: column; gap: 4px; }
  .pw-section-label {
    font-size: 9px; font-weight: 700; color: rgba(255,255,255,0.25);
    text-transform: uppercase; letter-spacing: 0.8px;
  }
  .pw-section-meta { margin-top: 8px; opacity: 0.5; }

  /* ── Badges ── */
  .pw-badge-row { display: flex; flex-wrap: wrap; gap: 4px; }
  .pw-badge {
    font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 6px;
    display: inline-flex; align-items: center;
  }
  .pw-badge-blue { background: rgba(59,130,246,0.15); color: rgba(96,165,250,0.9); }
  .pw-badge-purple { background: rgba(139,92,246,0.15); color: rgba(167,139,250,0.9); }
  .pw-badge-cyan { background: rgba(34,211,238,0.1); color: rgba(100,200,255,0.8); }
  .pw-badge-dim { background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.35); }

  /* ── Key-Value pairs ── */
  .pw-pair {
    display: flex; gap: 8px; align-items: baseline;
    font-size: 11px; line-height: 1.4;
  }
  .pw-pair-key { color: rgba(255,255,255,0.35); flex-shrink: 0; min-width: 70px; }
  .pw-pair-val { color: rgba(255,255,255,0.8); word-break: break-word; }
  .pw-pair-mono { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 10px; color: rgba(255,255,255,0.3); }

  /* ── Avatar gallery ── */
  .pw-avatar-gallery { display: flex; gap: 6px; flex-wrap: wrap; }

  /* ═══════════════════════════════════════════════
     DATA RECORDS — flat source entries (visible at a glance)
     ═══════════════════════════════════════════════ */
  .pw-source-flat {
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    overflow: hidden;
    padding: 8px 10px;
    background: rgba(255,255,255,0.02);
    display: flex; flex-direction: column; gap: 6px;
  }

  .pw-source-tag-row {
    display: flex; align-items: center; gap: 6px;
    padding-bottom: 4px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  .pw-source-idx {
    font-size: 10px; font-weight: 600; color: rgba(255,255,255,0.2);
    flex-shrink: 0;
  }

  .pw-source-fields {
    display: flex; flex-direction: column; gap: 3px;
  }

  .pw-data-pair {
    display: flex; gap: 8px; align-items: baseline;
    font-size: 11px; line-height: 1.4;
  }
  .pw-data-pair-json { align-items: flex-start; }
  .pw-data-key {
    color: rgba(124,138,255,0.6); font-weight: 600;
    flex-shrink: 0; min-width: 60px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 10px;
  }
  .pw-data-val {
    color: rgba(255,255,255,0.7); word-break: break-word;
    font-size: 11px;
  }
  .pw-data-img {
    width: 32px; height: 32px; border-radius: 6px;
    object-fit: cover; flex-shrink: 0;
    border: 1px solid rgba(255,255,255,0.08);
  }
  .pw-data-json {
    color: rgba(255,255,255,0.5); font-size: 10px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    margin: 0; white-space: pre-wrap; word-break: break-word;
    background: rgba(0,0,0,0.2); padding: 4px 6px; border-radius: 4px;
    line-height: 1.4;
  }
</style>
