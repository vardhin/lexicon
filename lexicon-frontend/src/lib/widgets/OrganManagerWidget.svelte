<!--
  OrganManagerWidget.svelte - Streamlined organ manager + pattern scraper.

  Flow:
    1. Register organs (any URL = a browser tab)
    2. Launch/kill organ tabs
    3. Paste outer HTML of an element, name it, scrape all matching elements
    4. View scraped data grouped by class name
    5. Re-scrape saved patterns on demand
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  const BRAIN = 'http://127.0.0.1:8000';

  // Views
  let view = 'list'; // 'list' | 'organ' | 'data'

  // Organ list
  let organs = [];
  let loading = true;

  // New organ form
  let newId = '';
  let newUrl = '';
  let newName = '';
  let createMsg = '';

  // Selected organ
  let selected = null;
  let patterns = [];
  let scrapedData = {};

  // Pattern input
  let patternHtml = '';
  let patternName = '';
  let matchPreview = null;
  let scrapeMsg = '';
  let matching = false;

  // Polling
  let pollTimer = null;

  onMount(() => {
    fetchOrgans();
    pollTimer = setInterval(fetchOrgans, 5000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  // API helper
  async function api(path, opts = {}) {
    try {
      const r = await fetch(BRAIN + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      });
      return await r.json();
    } catch (e) {
      return { error: e.message };
    }
  }

  async function fetchOrgans() {
    const data = await api('/organs');
    organs = data.organs || [];
    loading = false;
    if (selected) {
      const upd = organs.find(o => o.organ_id === selected.organ_id);
      if (upd) selected = { ...selected, running: upd.running, status: upd.status, title: upd.title };
    }
  }

  // Organ CRUD
  async function createOrgan() {
    let id = newId.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
    let url = newUrl.trim();
    let name = newName.trim() || id;
    if (!id || !url) { createMsg = 'ID and URL required'; return; }
    if (!url.startsWith('http://') && !url.startsWith('https://')) url = 'https://' + url;
    createMsg = 'creating...';
    const data = await api('/organs', { method: 'POST', body: JSON.stringify({ organ_id: id, url, name }) });
    if (data.status === 'ok') {
      createMsg = 'created';
      newId = ''; newUrl = ''; newName = '';
      fetchOrgans();
    } else {
      createMsg = 'failed: ' + (data.detail || '');
    }
    setTimeout(() => { createMsg = ''; }, 2500);
  }

  async function deleteOrgan(organId) {
    await api('/organs/' + encodeURIComponent(organId), { method: 'DELETE' });
    if (selected && selected.organ_id === organId) { selected = null; view = 'list'; }
    fetchOrgans();
  }

  async function launchOrgan(organId) {
    await api('/organs/' + encodeURIComponent(organId) + '/launch', { method: 'POST' });
    setTimeout(fetchOrgans, 1000);
  }

  async function killOrgan(organId) {
    await api('/organs/' + encodeURIComponent(organId) + '/kill', { method: 'POST' });
    setTimeout(fetchOrgans, 500);
  }

  // Select organ -> show patterns + data
  async function selectOrgan(organ) {
    selected = organ;
    view = 'organ';
    matchPreview = null;
    patternHtml = '';
    patternName = '';
    scrapeMsg = '';
    await Promise.all([fetchPatterns(), fetchAllData()]);
  }

  async function fetchPatterns() {
    if (!selected) return;
    const data = await api('/organs/' + encodeURIComponent(selected.organ_id) + '/patterns');
    patterns = data.patterns || [];
  }

  async function fetchAllData() {
    if (!selected) return;
    const data = await api('/organs/' + encodeURIComponent(selected.organ_id) + '/data');
    const items = data.data || [];
    const map = {};
    for (const d of items) {
      map[d.class_name] = d;
    }
    scrapedData = map;
  }

  // Pattern matching + scraping
  async function previewMatch() {
    if (!selected || !patternHtml.trim()) return;
    matching = true;
    matchPreview = null;
    const data = await api('/organs/' + encodeURIComponent(selected.organ_id) + '/match', {
      method: 'POST',
      body: JSON.stringify({ outer_html: patternHtml.trim() }),
    });
    matchPreview = data;
    matching = false;
  }

  async function commitScrape() {
    if (!selected || !patternHtml.trim() || !patternName.trim()) return;
    scrapeMsg = 'scraping...';
    const data = await api('/organs/' + encodeURIComponent(selected.organ_id) + '/scrape', {
      method: 'POST',
      body: JSON.stringify({
        outer_html: patternHtml.trim(),
        class_name: patternName.trim(),
      }),
    });
    if (data.error) {
      scrapeMsg = 'error: ' + data.error;
    } else {
      scrapeMsg = data.count + ' items scraped as "' + data.class_name + '"';
      patternHtml = '';
      patternName = '';
      matchPreview = null;
      await Promise.all([fetchPatterns(), fetchAllData()]);
    }
    setTimeout(() => { scrapeMsg = ''; }, 3000);
  }

  async function rescrapeAll() {
    if (!selected) return;
    scrapeMsg = 're-scraping...';
    await api('/organs/' + encodeURIComponent(selected.organ_id) + '/rescrape', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    await fetchAllData();
    scrapeMsg = 're-scraped all patterns';
    setTimeout(() => { scrapeMsg = ''; }, 2500);
  }

  async function rescrapeOne(className) {
    scrapeMsg = 're-scraping ' + className + '...';
    await api('/organs/' + encodeURIComponent(selected.organ_id) + '/rescrape', {
      method: 'POST',
      body: JSON.stringify({ class_name: className }),
    });
    await fetchAllData();
    scrapeMsg = className + ' re-scraped';
    setTimeout(() => { scrapeMsg = ''; }, 2500);
  }

  async function deletePattern(className) {
    await api('/organs/' + encodeURIComponent(selected.organ_id) + '/patterns/' + encodeURIComponent(className), {
      method: 'DELETE',
    });
    await Promise.all([fetchPatterns(), fetchAllData()]);
  }

  function goBack() {
    if (view === 'data') { view = 'organ'; return; }
    selected = null;
    view = 'list';
    matchPreview = null;
  }

  // View all scraped data across all organs
  let allData = [];
  async function openDataView() {
    view = 'data';
    allData = [];
    for (const o of organs) {
      const d = await api('/organs/' + encodeURIComponent(o.organ_id) + '/data');
      for (const item of (d.data || [])) {
        allData.push({ ...item, organ_id: o.organ_id, organ_name: o.name || o.organ_id });
      }
    }
    allData = allData;
  }

  function truncate(s, n) {
    return s && s.length > n ? s.substring(0, n) + '...' : (s || '');
  }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="organ-mgr">
  <button class="dismiss" on:click={onDismiss}>&#10005;</button>

  <!-- Header -->
  <div class="header">
    {#if view !== 'list'}
      <button class="back-btn" on:click={goBack}>&#8592; back</button>
    {/if}
    <div class="title">
      {#if view === 'list'}&#129516; Organs{:else if view === 'organ'}&#129516; {selected?.name || selected?.organ_id}{:else}&#128202; All Scraped Data{/if}
    </div>
    {#if view === 'list'}
      <button class="data-btn" on:click={openDataView} title="View all scraped data">&#128202;</button>
    {/if}
  </div>

  <!-- LIST VIEW -->
  {#if view === 'list'}
    <div class="create-form">
      <input bind:value={newId} placeholder="id (e.g. github)" class="input sm" />
      <input bind:value={newUrl} placeholder="https://github.com" class="input grow" />
      <input bind:value={newName} placeholder="name (optional)" class="input sm" />
      <button class="btn green" on:click={createOrgan}>+ Add</button>
    </div>
    {#if createMsg}<div class="msg">{createMsg}</div>{/if}

    {#if loading}
      <div class="empty">loading...</div>
    {:else if organs.length === 0}
      <div class="empty">No organs yet. Add a URL above to start.</div>
    {:else}
      <div class="organ-list">
        {#each organs as organ}
          <div class="organ-row" on:click={() => selectOrgan(organ)}>
            <div class="organ-dot" class:running={organ.running}></div>
            <div class="organ-info">
              <div class="organ-name">{organ.name || organ.organ_id}</div>
              <div class="organ-url">{truncate(organ.url, 50)}</div>
            </div>
            <div class="organ-actions">
              {#if organ.running}
                <button class="btn tiny red" on:click|stopPropagation={() => killOrgan(organ.organ_id)} title="Kill tab">&#9632;</button>
              {:else}
                <button class="btn tiny green" on:click|stopPropagation={() => launchOrgan(organ.organ_id)} title="Launch tab">&#9654;</button>
              {/if}
              <button class="btn tiny dim" on:click|stopPropagation={() => deleteOrgan(organ.organ_id)} title="Delete organ">&#128465;</button>
            </div>
          </div>
        {/each}
      </div>
    {/if}

  <!-- ORGAN VIEW -->
  {:else if view === 'organ' && selected}
    <div class="organ-detail">
      <div class="status-bar">
        <span class="dot" class:running={selected.running}></span>
        <span class="status-text">{selected.running ? 'running' : 'stopped'}</span>
        <span class="status-url">{truncate(selected.url, 40)}</span>
        <div class="status-actions">
          {#if selected.running}
            <button class="btn tiny red" on:click={() => killOrgan(selected.organ_id)}>&#9632; Kill</button>
          {:else}
            <button class="btn tiny green" on:click={() => launchOrgan(selected.organ_id)}>&#9654; Launch</button>
          {/if}
        </div>
      </div>

      <div class="section-label">Paste outer HTML &#8594; name it &#8594; scrape</div>
      <div class="pattern-input">
        <textarea
          bind:value={patternHtml}
          placeholder="Paste outer HTML here (right-click element > Copy outer HTML)"
          class="html-input"
          rows="4"
          spellcheck="false"
        ></textarea>
        <div class="pattern-row">
          <input bind:value={patternName} placeholder="class name (e.g. contact, repo, message)" class="input grow" />
          <button class="btn blue" on:click={previewMatch} disabled={matching || !patternHtml.trim()}>
            {matching ? '...' : '&#128269;'} Preview
          </button>
          <button class="btn green" on:click={commitScrape} disabled={!patternHtml.trim() || !patternName.trim()}>
            &#128190; Scrape
          </button>
        </div>
      </div>

      {#if scrapeMsg}<div class="msg">{scrapeMsg}</div>{/if}

      <!-- Match preview -->
      {#if matchPreview}
        <div class="preview-box">
          <div class="preview-header">
            <span class="preview-count">{matchPreview.count || 0} matches found</span>
            {#if matchPreview.fingerprint}
              <span class="preview-fp">
                &lt;{matchPreview.fingerprint.tag}&gt;
                {#if matchPreview.fingerprint.classes && matchPreview.fingerprint.classes.length}
                  .{matchPreview.fingerprint.classes.slice(0, 3).join('.')}
                {/if}
              </span>
            {/if}
          </div>
          {#if matchPreview.matches && matchPreview.matches.length > 0}
            <div class="preview-list">
              {#each matchPreview.matches.slice(0, 20) as m, i}
                <div class="preview-item">
                  <span class="preview-idx">{i + 1}</span>
                  <span class="preview-text">{truncate(m.text || '(empty)', 80)}</span>
                  <span class="preview-score">{m.score}</span>
                </div>
              {/each}
              {#if matchPreview.count > 20}
                <div class="preview-more">... and {matchPreview.count - 20} more</div>
              {/if}
            </div>
          {:else if matchPreview.error}
            <div class="preview-error">{matchPreview.error}</div>
          {:else}
            <div class="preview-empty">No matches found. Try a different element.</div>
          {/if}
        </div>
      {/if}

      <!-- Saved patterns and scraped data -->
      {#if patterns.length > 0}
        <div class="section-label">
          Saved patterns
          <button class="btn tiny blue" on:click={rescrapeAll} title="Re-scrape all patterns">&#128260; Re-scrape all</button>
        </div>
        <div class="patterns-list">
          {#each patterns as pat}
            {@const data = scrapedData[pat.class_name]}
            <div class="pattern-card">
              <div class="pattern-head">
                <span class="pattern-tag">{pat.class_name}</span>
                <span class="pattern-count">{data?.count ?? '?'} items</span>
                <button class="btn tiny blue" on:click={() => rescrapeOne(pat.class_name)} title="Re-scrape">&#128260;</button>
                <button class="btn tiny dim" on:click={() => deletePattern(pat.class_name)} title="Delete">&#128465;</button>
              </div>
              {#if pat.fingerprint}
                <div class="pattern-fp">
                  &lt;{pat.fingerprint.tag}&gt;
                  {#if pat.fingerprint.classes && pat.fingerprint.classes.length}
                    .{pat.fingerprint.classes.slice(0, 4).join('.')}
                  {/if}
                </div>
              {/if}
              {#if data && data.values && data.values.length > 0}
                <div class="data-values">
                  {#each data.values.slice(0, 8) as val, i}
                    <div class="data-val">{truncate(val, 60)}</div>
                  {/each}
                  {#if data.values.length > 8}
                    <div class="data-more">... {data.values.length - 8} more</div>
                  {/if}
                </div>
              {:else}
                <div class="data-empty">no data yet - launch organ and re-scrape</div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>

  <!-- DATA VIEW -->
  {:else if view === 'data'}
    {#if allData.length === 0}
      <div class="empty">No scraped data yet. Open an organ and define patterns.</div>
    {:else}
      <div class="data-overview">
        {#each allData as d}
          <div class="data-card">
            <div class="data-head">
              <span class="data-organ">{d.organ_name}</span>
              <span class="data-class">{d.class_name}</span>
              <span class="data-ct">{d.count} items</span>
            </div>
            {#if d.values && d.values.length > 0}
              <div class="data-values">
                {#each d.values.slice(0, 10) as val}
                  <div class="data-val">{truncate(val, 70)}</div>
                {/each}
                {#if d.values.length > 10}
                  <div class="data-more">... {d.values.length - 10} more</div>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .organ-mgr {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    padding: 12px 14px;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    font-size: 12.5px;
    color: rgba(255,255,255,0.9);
    overflow-y: auto;
    overflow-x: hidden;
    box-sizing: border-box;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.15) transparent;
  }
  .organ-mgr :global(*) {
    box-sizing: border-box;
  }

  .dismiss {
    position: absolute; top: 6px; right: 10px;
    background: none; border: none; color: rgba(255,255,255,0.4);
    font-size: 14px; cursor: pointer; z-index: 10;
    padding: 2px 6px; border-radius: 4px;
  }
  .dismiss:hover { color: #ff5f57; background: rgba(255,95,87,0.15); }

  .header {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 10px; min-height: 28px;
    box-sizing: border-box; width: 100%;
  }
  .title {
    font-size: 14px; font-weight: 700;
    color: rgba(255,255,255,0.95);
    flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .back-btn {
    background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.6); font-size: 11px; padding: 3px 8px;
    border-radius: 4px; cursor: pointer;
  }
  .back-btn:hover { color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.12); }

  .data-btn {
    background: rgba(100,180,255,0.12); border: 1px solid rgba(100,180,255,0.2);
    color: rgba(100,180,255,0.8); font-size: 13px; padding: 3px 8px;
    border-radius: 4px; cursor: pointer;
  }
  .data-btn:hover { background: rgba(100,180,255,0.2); }

  .input {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
    color: white; font-size: 11.5px; padding: 5px 8px;
    border-radius: 4px; outline: none; font-family: inherit;
    box-sizing: border-box; min-width: 0;
  }
  .input:focus { border-color: rgba(100,180,255,0.4); }
  .input.sm { width: 90px; flex-shrink: 1; }
  .input.grow { flex: 1; min-width: 60px; }

  .btn {
    border: none; font-size: 11px; padding: 5px 10px;
    border-radius: 4px; cursor: pointer; font-weight: 600;
    white-space: nowrap; flex-shrink: 0; box-sizing: border-box;
  }
  .btn.green { background: rgba(37,211,102,0.2); color: rgba(37,211,102,0.9); }
  .btn.green:hover { background: rgba(37,211,102,0.3); }
  .btn.red { background: rgba(255,95,87,0.2); color: rgba(255,95,87,0.9); }
  .btn.red:hover { background: rgba(255,95,87,0.3); }
  .btn.blue { background: rgba(100,180,255,0.15); color: rgba(100,180,255,0.9); }
  .btn.blue:hover { background: rgba(100,180,255,0.25); }
  .btn.dim { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.4); }
  .btn.dim:hover { color: rgba(255,255,255,0.7); background: rgba(255,255,255,0.1); }
  .btn.tiny { font-size: 10px; padding: 2px 6px; }
  .btn:disabled { opacity: 0.3; cursor: default; }

  .msg {
    font-size: 11px; padding: 3px 0; color: rgba(100,180,255,0.8);
  }

  .create-form {
    display: flex; gap: 6px; margin-bottom: 8px;
    flex-wrap: wrap; width: 100%; box-sizing: border-box;
  }

  .empty {
    color: rgba(255,255,255,0.3); text-align: center;
    padding: 30px 0; font-size: 12px;
  }

  .organ-list {
    display: flex; flex-direction: column; gap: 4px;
  }
  .organ-row {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px; border-radius: 6px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    cursor: pointer; transition: background 0.15s;
    box-sizing: border-box; min-width: 0;
  }
  .organ-row:hover { background: rgba(255,255,255,0.08); }

  .organ-dot {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
    background: rgba(255,255,255,0.2);
  }
  .organ-dot.running { background: rgba(37,211,102,0.8); box-shadow: 0 0 6px rgba(37,211,102,0.4); }

  .organ-info { flex: 1; min-width: 0; }
  .organ-name { font-weight: 600; font-size: 12px; color: rgba(255,255,255,0.9); }
  .organ-url { font-size: 10px; color: rgba(255,255,255,0.35); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .organ-actions { display: flex; gap: 4px; flex-shrink: 0; }

  .organ-detail { display: flex; flex-direction: column; gap: 8px; min-width: 0; width: 100%; box-sizing: border-box; }

  .status-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 10px; border-radius: 5px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    box-sizing: border-box; min-width: 0;
  }
  .dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: rgba(255,255,255,0.2);
  }
  .dot.running { background: rgba(37,211,102,0.8); }
  .status-text { font-size: 11px; color: rgba(255,255,255,0.5); }
  .status-url { font-size: 10px; color: rgba(255,255,255,0.3); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .status-actions { flex-shrink: 0; }

  .section-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.6px; color: rgba(255,255,255,0.35);
    margin-top: 6px; display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap;
  }

  .pattern-input { display: flex; flex-direction: column; gap: 6px; min-width: 0; }

  .html-input {
    background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.8); font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 10.5px; padding: 8px; border-radius: 5px;
    resize: vertical; min-height: 60px; outline: none;
    line-height: 1.4; width: 100%; box-sizing: border-box;
  }
  .html-input:focus { border-color: rgba(100,180,255,0.3); }
  .html-input::placeholder { color: rgba(255,255,255,0.2); }

  .pattern-row { display: flex; gap: 6px; align-items: center; min-width: 0; flex-wrap: wrap; }

  .preview-box {
    background: rgba(0,0,0,0.2); border: 1px solid rgba(100,180,255,0.15);
    border-radius: 5px; padding: 8px; margin-top: 2px;
    min-width: 0; overflow: hidden;
  }
  .preview-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 6px; flex-wrap: wrap; gap: 4px;
  }
  .preview-count {
    font-size: 11px; font-weight: 600; color: rgba(100,180,255,0.9);
  }
  .preview-fp {
    font-size: 10px; color: rgba(255,255,255,0.3);
    font-family: monospace;
  }
  .preview-list {
    display: flex; flex-direction: column; gap: 2px;
    max-height: 160px; overflow-y: auto;
    scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent;
  }
  .preview-item {
    display: flex; align-items: center; gap: 6px;
    padding: 3px 6px; border-radius: 3px;
    background: rgba(255,255,255,0.03);
    font-size: 11px;
  }
  .preview-item:hover { background: rgba(255,255,255,0.06); }
  .preview-idx { color: rgba(255,255,255,0.25); font-size: 9px; width: 18px; text-align: right; flex-shrink: 0; }
  .preview-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: rgba(255,255,255,0.8); }
  .preview-score { font-size: 9px; color: rgba(255,189,46,0.7); flex-shrink: 0; }
  .preview-more { font-size: 10px; color: rgba(255,255,255,0.25); text-align: center; padding: 4px; }
  .preview-error { font-size: 11px; color: rgba(255,95,87,0.7); }
  .preview-empty { font-size: 11px; color: rgba(255,255,255,0.3); text-align: center; padding: 8px; }

  .patterns-list { display: flex; flex-direction: column; gap: 6px; }

  .pattern-card {
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
    border-radius: 6px; padding: 8px 10px;
  }
  .pattern-head {
    display: flex; align-items: center; gap: 6px; margin-bottom: 4px;
    flex-wrap: wrap; min-width: 0;
  }
  .pattern-tag {
    font-weight: 700; font-size: 12px; color: rgba(100,180,255,0.9);
    background: rgba(100,180,255,0.1); padding: 1px 6px; border-radius: 3px;
  }
  .pattern-count { font-size: 10px; color: rgba(255,255,255,0.4); flex: 1; }
  .pattern-fp { font-size: 9.5px; color: rgba(255,255,255,0.25); font-family: monospace; margin-bottom: 4px; }

  .data-values { display: flex; flex-direction: column; gap: 1px; }
  .data-val {
    font-size: 11px; color: rgba(255,255,255,0.7);
    padding: 2px 6px; border-radius: 2px;
    background: rgba(255,255,255,0.02);
  }
  .data-val:hover { background: rgba(255,255,255,0.06); }
  .data-more { font-size: 10px; color: rgba(255,255,255,0.2); text-align: center; padding: 2px; }
  .data-empty { font-size: 10px; color: rgba(255,255,255,0.2); font-style: italic; padding: 4px 0; }

  .data-overview { display: flex; flex-direction: column; gap: 8px; }

  .data-card {
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
    border-radius: 6px; padding: 8px 10px;
  }
  .data-head {
    display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
    flex-wrap: wrap; min-width: 0;
  }
  .data-organ { font-weight: 600; font-size: 11px; color: rgba(37,211,102,0.8); }
  .data-class { font-weight: 700; font-size: 12px; color: rgba(100,180,255,0.9); }
  .data-ct { font-size: 10px; color: rgba(255,255,255,0.3); margin-left: auto; }
</style>
