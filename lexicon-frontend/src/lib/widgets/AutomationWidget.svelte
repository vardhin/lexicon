<!--
  AutomationWidget.svelte — Programmable browser automation manager.

  Features:
    1. Create automation sequences (click, scroll, type, wait, navigate, extract, paginate)
    2. Save automations to an organ for re-use
    3. Run automations and see step-by-step progress + extracted data
    4. One-shot actions: click/type/scroll on an organ's live page
    5. Screenshot preview of organ pages
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  const BRAIN = 'http://127.0.0.1:8000';

  // Views
  let view = 'home'; // 'home' | 'build' | 'run' | 'actions'

  // Data
  let organs = [];
  let selectedOrganId = '';
  let automations = [];
  let loading = true;

  // Build mode
  let autoName = '';
  let autoDescription = '';
  let steps = [];
  let newStepType = 'click';
  let saveMsg = '';

  // Run mode
  let runResult = null;
  let running = false;
  let runProgress = null;

  // One-shot actions
  let actionType = 'click';
  let actionSelector = '';
  let actionText = '';
  let actionUrl = '';
  let actionJs = '';
  let actionDirection = 'down';
  let actionResult = null;
  let actionRunning = false;

  // Screenshot
  let screenshotData = null;

  let pollTimer = null;

  onMount(() => {
    fetchOrgans();
    pollTimer = setInterval(fetchOrgans, 8000);

    // Listen for automation progress via WebSocket
    if (window.__lexicon_ws) {
      window.__lexicon_automation_listener = onWsMessage;
      if (!window.__lexicon_automation_listeners) {
        window.__lexicon_automation_listeners = [];
      }
      window.__lexicon_automation_listeners.push(onWsMessage);
    }
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
    if (window.__lexicon_automation_listeners) {
      window.__lexicon_automation_listeners = window.__lexicon_automation_listeners.filter(
        fn => fn !== onWsMessage
      );
    }
  });

  function onWsMessage(msg) {
    if (msg.type === 'AUTOMATION_PROGRESS') {
      runProgress = msg;
    }
  }

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
    organs = (data.organs || []).filter(o => o.running);
    loading = false;
    if (selectedOrganId) {
      fetchAutomations();
    }
  }

  async function fetchAutomations() {
    if (!selectedOrganId) return;
    const data = await api(`/organs/${selectedOrganId}/automations`);
    automations = data.automations || [];
  }

  function selectOrgan(organId) {
    selectedOrganId = organId;
    fetchAutomations();
  }

  // ── Build automation ──

  const STEP_TYPES = [
    { value: 'click', label: '🖱️ Click', icon: '🖱️' },
    { value: 'type', label: '⌨️ Type', icon: '⌨️' },
    { value: 'scroll', label: '📜 Scroll', icon: '📜' },
    { value: 'wait', label: '⏳ Wait', icon: '⏳' },
    { value: 'navigate', label: '🔗 Navigate', icon: '🔗' },
    { value: 'extract', label: '📊 Extract', icon: '📊' },
    { value: 'paginate', label: '📄 Paginate', icon: '📄' },
    { value: 'eval_js', label: '💻 Eval JS', icon: '💻' },
  ];

  function addStep() {
    const defaults = {
      click: { type: 'click', selector: '', wait_after: 500 },
      type: { type: 'type', selector: '', text: '', press_enter: false },
      scroll: { type: 'scroll', direction: 'down', amount: 800, wait_after: 1000 },
      wait: { type: 'wait', delay: 2000 },
      navigate: { type: 'navigate', url: '' },
      extract: { type: 'extract', selector: '', attribute: 'textContent' },
      paginate: { type: 'paginate', next_selector: '', extract: { selector: '', attribute: 'textContent' }, max_pages: 3 },
      eval_js: { type: 'eval_js', js: '' },
    };
    steps = [...steps, { ...defaults[newStepType], _id: Date.now() }];
  }

  function removeStep(index) {
    steps = steps.filter((_, i) => i !== index);
  }

  function moveStep(index, direction) {
    if (direction === 'up' && index > 0) {
      [steps[index], steps[index - 1]] = [steps[index - 1], steps[index]];
      steps = [...steps];
    } else if (direction === 'down' && index < steps.length - 1) {
      [steps[index], steps[index + 1]] = [steps[index + 1], steps[index]];
      steps = [...steps];
    }
  }

  async function saveAutomation() {
    if (!autoName.trim() || steps.length === 0) {
      saveMsg = 'Name and at least one step required';
      return;
    }
    saveMsg = 'saving...';
    // Strip internal _id from steps before saving
    const cleanSteps = steps.map(s => {
      const { _id, ...rest } = s;
      return rest;
    });
    const data = await api(`/organs/${selectedOrganId}/automations`, {
      method: 'POST',
      body: JSON.stringify({
        name: autoName.trim(),
        description: autoDescription.trim(),
        steps: cleanSteps,
      }),
    });
    if (data.status === 'ok') {
      saveMsg = '✓ Saved';
      fetchAutomations();
    } else {
      saveMsg = 'Error: ' + (data.detail || 'unknown');
    }
    setTimeout(() => { saveMsg = ''; }, 3000);
  }

  async function loadAutomation(name) {
    const data = await api(`/organs/${selectedOrganId}/automations/${name}`);
    if (data.automation) {
      autoName = data.automation.name;
      autoDescription = data.automation.description || '';
      steps = (data.automation.steps || []).map((s, i) => ({ ...s, _id: Date.now() + i }));
      view = 'build';
    }
  }

  async function deleteAutomation(name) {
    await api(`/organs/${selectedOrganId}/automations/${name}`, { method: 'DELETE' });
    fetchAutomations();
  }

  // ── Run automation ──

  async function runAutomation(name) {
    running = true;
    runResult = null;
    runProgress = null;
    view = 'run';
    const data = await api(`/organs/${selectedOrganId}/automations/${name}/run`, {
      method: 'POST',
    });
    runResult = data;
    running = false;
    runProgress = null;
  }

  // ── One-shot actions ──

  async function executeAction() {
    actionRunning = true;
    actionResult = null;

    let path = `/organs/${selectedOrganId}/actions/${actionType}`;
    let body = {};

    if (actionType === 'click') body = { selector: actionSelector };
    else if (actionType === 'type') body = { selector: actionSelector, text: actionText, press_enter: true };
    else if (actionType === 'scroll') body = { direction: actionDirection };
    else if (actionType === 'navigate') body = { url: actionUrl };
    else if (actionType === 'eval') body = { js: actionJs };
    else if (actionType === 'screenshot') body = {};
    else if (actionType === 'extract') body = { selector: actionSelector, attribute: 'textContent' };

    const data = await api(path, { method: 'POST', body: JSON.stringify(body) });
    actionResult = data;
    actionRunning = false;

    // Handle screenshot
    if (actionType === 'screenshot' && data.success && data.data?.screenshot) {
      screenshotData = data.data.screenshot;
    }
  }

  function stepLabel(step) {
    const t = step.type;
    if (t === 'click') return `Click: ${step.selector || '?'}`;
    if (t === 'type') return `Type "${step.text || ''}" into ${step.selector || '?'}`;
    if (t === 'scroll') return `Scroll ${step.direction || 'down'}`;
    if (t === 'wait') return step.selector ? `Wait for: ${step.selector}` : `Wait ${step.delay || 0}ms`;
    if (t === 'navigate') return `Navigate: ${step.url || '?'}`;
    if (t === 'extract') return `Extract: ${step.selector || step.outer_html?.substring(0, 30) || '?'}`;
    if (t === 'paginate') return `Paginate: ${step.max_pages || 3} pages`;
    if (t === 'eval_js') return `Eval: ${(step.js || '').substring(0, 40)}`;
    return t;
  }
</script>

<div class="automation-widget lx-automation lx-widget">
  <button class="dismiss lx-dismiss" on:click={onDismiss}>✕</button>

  <!-- Header -->
  <div class="header lx-automation-header">
    <span class="label lx-label">🤖 AUTOMATIONS</span>
    {#if selectedOrganId}
      <span class="organ-badge lx-badge">{selectedOrganId}</span>
    {/if}
  </div>

  <!-- Nav tabs -->
  <div class="nav lx-automation-nav">
    <button class="tab" class:active={view === 'home'} on:click={() => view = 'home'}>Home</button>
    <button class="tab" class:active={view === 'build'} on:click={() => view = 'build'} disabled={!selectedOrganId}>Build</button>
    <button class="tab" class:active={view === 'actions'} on:click={() => view = 'actions'} disabled={!selectedOrganId}>Actions</button>
    {#if runResult || running}
      <button class="tab" class:active={view === 'run'} on:click={() => view = 'run'}>Results</button>
    {/if}
  </div>

  <!-- Body -->
  <div class="body lx-automation-body">

    <!-- HOME: select organ + list automations -->
    {#if view === 'home'}
      <div class="section">
        <div class="section-label">Select an organ (must be running)</div>
        {#if loading}
          <div class="muted">Loading...</div>
        {:else if organs.length === 0}
          <div class="muted">No running organs. Launch an organ first via the Organ Manager.</div>
        {:else}
          <div class="organ-list">
            {#each organs as org}
              <button
                class="organ-btn"
                class:selected={selectedOrganId === org.organ_id}
                on:click={() => selectOrgan(org.organ_id)}
              >
                <span class="dot running"></span>
                <span class="organ-name">{org.name || org.organ_id}</span>
              </button>
            {/each}
          </div>
        {/if}
      </div>

      {#if selectedOrganId}
        <div class="section">
          <div class="section-label">Saved Automations</div>
          {#if automations.length === 0}
            <div class="muted">No automations yet. Use "Build" to create one.</div>
          {:else}
            {#each automations as auto}
              <div class="auto-card">
                <div class="auto-info">
                  <span class="auto-name">{auto.name}</span>
                  {#if auto.description}
                    <span class="auto-desc">{auto.description}</span>
                  {/if}
                </div>
                <div class="auto-actions">
                  <button class="btn-sm btn-run" on:click={() => runAutomation(auto.name)} disabled={running}>▶ Run</button>
                  <button class="btn-sm btn-edit" on:click={() => loadAutomation(auto.name)}>✏️</button>
                  <button class="btn-sm btn-del" on:click={() => deleteAutomation(auto.name)}>🗑️</button>
                </div>
              </div>
            {/each}
          {/if}
        </div>
      {/if}

    <!-- BUILD: create/edit automation -->
    {:else if view === 'build'}
      <div class="section">
        <input class="input lx-input" bind:value={autoName} placeholder="Automation name" />
        <input class="input lx-input" bind:value={autoDescription} placeholder="Description (optional)" style="margin-top:6px" />
      </div>

      <div class="section">
        <div class="section-label">Steps ({steps.length})</div>
        <div class="steps-list">
          {#each steps as step, i (step._id)}
            <div class="step-card">
              <div class="step-header">
                <span class="step-num">#{i + 1}</span>
                <span class="step-type-badge">{step.type}</span>
                <span class="step-summary">{stepLabel(step)}</span>
                <div class="step-controls">
                  <button class="btn-xs" on:click={() => moveStep(i, 'up')} disabled={i === 0}>↑</button>
                  <button class="btn-xs" on:click={() => moveStep(i, 'down')} disabled={i === steps.length - 1}>↓</button>
                  <button class="btn-xs btn-del" on:click={() => removeStep(i)}>✕</button>
                </div>
              </div>
              <div class="step-params">
                {#if step.type === 'click'}
                  <input class="input-sm" bind:value={step.selector} placeholder="CSS selector" />
                {:else if step.type === 'type'}
                  <input class="input-sm" bind:value={step.selector} placeholder="CSS selector" />
                  <input class="input-sm" bind:value={step.text} placeholder="Text to type" />
                  <label class="check-label"><input type="checkbox" bind:checked={step.press_enter} /> Press Enter</label>
                {:else if step.type === 'scroll'}
                  <select class="input-sm" bind:value={step.direction}>
                    <option value="down">Down</option>
                    <option value="up">Up</option>
                    <option value="bottom">To Bottom</option>
                    <option value="top">To Top</option>
                  </select>
                  <input class="input-sm" type="number" bind:value={step.amount} placeholder="Pixels" />
                {:else if step.type === 'wait'}
                  <input class="input-sm" bind:value={step.selector} placeholder="CSS selector (optional)" />
                  <input class="input-sm" type="number" bind:value={step.delay} placeholder="Delay (ms)" />
                {:else if step.type === 'navigate'}
                  <input class="input-sm" bind:value={step.url} placeholder="URL" />
                {:else if step.type === 'extract'}
                  <input class="input-sm" bind:value={step.selector} placeholder="CSS selector" />
                  <select class="input-sm" bind:value={step.attribute}>
                    <option value="textContent">Text</option>
                    <option value="href">href</option>
                    <option value="src">src</option>
                    <option value="innerHTML">innerHTML</option>
                  </select>
                {:else if step.type === 'paginate'}
                  <input class="input-sm" bind:value={step.next_selector} placeholder="Next button selector" />
                  <input class="input-sm" bind:value={step.extract.selector} placeholder="Extract selector" />
                  <input class="input-sm" type="number" bind:value={step.max_pages} placeholder="Max pages" />
                {:else if step.type === 'eval_js'}
                  <textarea class="input-sm textarea" bind:value={step.js} placeholder="JavaScript code"></textarea>
                {/if}
              </div>
            </div>
          {/each}
        </div>

        <div class="add-step-row">
          <select class="input-sm" bind:value={newStepType}>
            {#each STEP_TYPES as st}
              <option value={st.value}>{st.label}</option>
            {/each}
          </select>
          <button class="btn-sm btn-add" on:click={addStep}>+ Add Step</button>
        </div>
      </div>

      <div class="section footer-row">
        <button class="btn-primary" on:click={saveAutomation} disabled={!autoName.trim() || steps.length === 0}>
          💾 Save Automation
        </button>
        {#if saveMsg}
          <span class="save-msg">{saveMsg}</span>
        {/if}
      </div>

    <!-- ACTIONS: one-shot actions -->
    {:else if view === 'actions'}
      <div class="section">
        <div class="section-label">Quick Actions on "{selectedOrganId}"</div>
        <div class="action-type-row">
          {#each [['click','🖱️'],['type','⌨️'],['scroll','📜'],['navigate','🔗'],['screenshot','📸'],['extract','📊'],['eval','💻']] as [t, icon]}
            <button class="action-chip" class:active={actionType === t} on:click={() => { actionType = t; actionResult = null; screenshotData = null; }}>
              {icon} {t}
            </button>
          {/each}
        </div>
      </div>

      <div class="section">
        {#if actionType === 'click' || actionType === 'extract'}
          <input class="input lx-input" bind:value={actionSelector} placeholder="CSS selector" />
        {:else if actionType === 'type'}
          <input class="input lx-input" bind:value={actionSelector} placeholder="CSS selector" />
          <input class="input lx-input" bind:value={actionText} placeholder="Text to type" style="margin-top:6px" />
        {:else if actionType === 'scroll'}
          <select class="input lx-input" bind:value={actionDirection}>
            <option value="down">Down</option>
            <option value="up">Up</option>
            <option value="bottom">To Bottom</option>
            <option value="top">To Top</option>
          </select>
        {:else if actionType === 'navigate'}
          <input class="input lx-input" bind:value={actionUrl} placeholder="URL" />
        {:else if actionType === 'eval'}
          <textarea class="input lx-input textarea" bind:value={actionJs} placeholder="JavaScript code"></textarea>
        {:else if actionType === 'screenshot'}
          <div class="muted">Click Execute to capture the organ's page.</div>
        {/if}

        <button class="btn-primary" style="margin-top:8px" on:click={executeAction} disabled={actionRunning}>
          {actionRunning ? '⏳ Running...' : '▶ Execute'}
        </button>
      </div>

      {#if actionResult}
        <div class="section">
          <div class="section-label">Result</div>
          <div class="result-card" class:success={actionResult.success} class:error={!actionResult.success}>
            <div class="result-status">{actionResult.success ? '✅ Success' : '❌ Failed'}</div>
            {#if actionResult.error}
              <div class="result-error">{actionResult.error}</div>
            {/if}
            {#if actionResult.duration_ms}
              <div class="result-time">{actionResult.duration_ms}ms</div>
            {/if}
            {#if actionResult.data && typeof actionResult.data !== 'string'}
              <pre class="result-data">{JSON.stringify(actionResult.data, null, 2).substring(0, 2000)}</pre>
            {/if}
          </div>
        </div>
      {/if}

      {#if screenshotData}
        <div class="section">
          <div class="section-label">Screenshot</div>
          <img class="screenshot-img" src="data:image/jpeg;base64,{screenshotData}" alt="organ screenshot" />
        </div>
      {/if}

    <!-- RUN: automation results -->
    {:else if view === 'run'}
      <div class="section">
        {#if running}
          <div class="running-indicator">
            <span class="spinner"></span>
            Running automation...
            {#if runProgress}
              <span class="progress-text">Step {runProgress.step}/{runProgress.total}: {runProgress.step_type}</span>
            {/if}
          </div>
        {:else if runResult}
          <div class="result-card" class:success={runResult.success} class:error={!runResult.success}>
            <div class="result-status">
              {runResult.success ? '✅ Completed' : '❌ Failed'}
              — {runResult.completed_steps}/{runResult.total_steps} steps
              in {runResult.duration_ms}ms
            </div>
            {#if runResult.error}
              <div class="result-error">{runResult.error}</div>
            {/if}
          </div>

          {#if runResult.steps && runResult.steps.length > 0}
            <div class="section-label" style="margin-top:12px">Step Results</div>
            {#each runResult.steps as step, i}
              <div class="step-result" class:step-ok={step.success} class:step-fail={!step.success}>
                <span class="step-num">#{step.index + 1}</span>
                <span class="step-type-badge">{step.type}</span>
                <span class="step-duration">{step.duration_ms}ms</span>
                {#if step.data_count > 0}
                  <span class="step-data-count">📊 {step.data_count} items</span>
                {/if}
                {#if step.error}
                  <span class="step-error">{step.error}</span>
                {/if}
              </div>
            {/each}
          {/if}

          {#if runResult.extracted_data && runResult.extracted_data.length > 0}
            <div class="section-label" style="margin-top:12px">Extracted Data ({runResult.extracted_data.length} items)</div>
            <div class="data-scroll">
              {#each runResult.extracted_data.slice(0, 20) as item, i}
                <div class="data-item">
                  <span class="data-idx">#{i + 1}</span>
                  <pre class="data-json">{JSON.stringify(item, null, 2)}</pre>
                </div>
              {/each}
              {#if runResult.extracted_data.length > 20}
                <div class="muted">...and {runResult.extracted_data.length - 20} more</div>
              {/if}
            </div>
          {/if}

          {#if runResult.entity_resolution}
            <div class="section-label" style="margin-top:12px">Entity Resolution</div>
            <div class="entity-stats">
              <span>Created: {runResult.entity_resolution.created}</span>
              <span>Merged: {runResult.entity_resolution.merged}</span>
              <span>Skipped: {runResult.entity_resolution.skipped}</span>
            </div>
          {/if}
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .automation-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    color: rgba(255,255,255,0.92);
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    padding: 10px 14px;
    box-sizing: border-box;
    overflow: hidden;
  }

  .header { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .label { font-size: 10px; letter-spacing: 3px; font-weight: 600; text-transform: uppercase; }
  .organ-badge {
    font-size: 10px; padding: 2px 8px; border-radius: 10px;
    background: rgba(0,200,255,0.15); color: rgba(0,200,255,0.9);
    font-weight: 600;
  }

  .nav { display: flex; gap: 4px; margin-bottom: 8px; }
  .tab {
    padding: 4px 12px; border-radius: 6px; border: none;
    background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.5);
    font-size: 11px; cursor: pointer; transition: all 0.15s;
  }
  .tab:hover { background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.8); }
  .tab.active { background: rgba(255,255,255,0.15); color: rgba(255,255,255,0.95); }
  .tab:disabled { opacity: 0.3; cursor: default; }

  .body { flex: 1; overflow-y: auto; scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent; }

  .section { margin-bottom: 12px; }
  .section-label { font-size: 10px; letter-spacing: 2px; color: rgba(255,255,255,0.4); text-transform: uppercase; margin-bottom: 6px; }
  .muted { font-size: 12px; color: rgba(255,255,255,0.35); font-style: italic; }

  .dismiss {
    position: absolute; top: 6px; right: 10px;
    background: none; border: none;
    color: rgba(255,255,255,0.3); font-size: 14px;
    cursor: pointer; z-index: 10;
    padding: 2px 6px; border-radius: 4px;
  }
  .dismiss:hover { color: #ff5f57; background: rgba(255,95,87,0.12); }

  /* Organ selection */
  .organ-list { display: flex; flex-wrap: wrap; gap: 6px; }
  .organ-btn {
    display: flex; align-items: center; gap: 6px;
    padding: 6px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.8);
    font-size: 12px; cursor: pointer; transition: all 0.15s;
  }
  .organ-btn:hover { background: rgba(255,255,255,0.08); }
  .organ-btn.selected { border-color: rgba(0,200,255,0.4); background: rgba(0,200,255,0.1); }
  .dot { width: 6px; height: 6px; border-radius: 50%; }
  .dot.running { background: #00ff41; box-shadow: 0 0 4px rgba(0,255,65,0.5); }
  .organ-name { font-weight: 500; }

  /* Automation cards */
  .auto-card {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 10px; border-radius: 8px;
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 6px;
  }
  .auto-info { display: flex; flex-direction: column; gap: 2px; }
  .auto-name { font-size: 13px; font-weight: 600; }
  .auto-desc { font-size: 10px; color: rgba(255,255,255,0.4); }
  .auto-actions { display: flex; gap: 4px; }

  /* Buttons */
  .btn-sm {
    padding: 3px 8px; border-radius: 5px; border: none;
    font-size: 11px; cursor: pointer; transition: all 0.15s;
    background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.7);
  }
  .btn-sm:hover { background: rgba(255,255,255,0.15); }
  .btn-run { background: rgba(0,200,100,0.15); color: rgba(0,255,120,0.9); }
  .btn-run:hover { background: rgba(0,200,100,0.25); }
  .btn-del { color: rgba(255,80,80,0.7); }
  .btn-del:hover { color: rgba(255,80,80,1); }
  .btn-xs { padding: 1px 5px; border-radius: 3px; border: none; background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.5); font-size: 10px; cursor: pointer; }
  .btn-primary {
    padding: 6px 16px; border-radius: 6px; border: none;
    background: rgba(0,150,255,0.25); color: rgba(100,200,255,0.95);
    font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s;
  }
  .btn-primary:hover { background: rgba(0,150,255,0.35); }
  .btn-primary:disabled { opacity: 0.4; cursor: default; }
  .btn-add { background: rgba(0,200,100,0.15); color: rgba(0,255,120,0.9); }

  /* Inputs */
  .input {
    width: 100%; padding: 6px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.9);
    font-size: 12px; outline: none; box-sizing: border-box;
  }
  .input:focus { border-color: rgba(0,150,255,0.4); }
  .input-sm {
    padding: 4px 8px; border-radius: 5px; border: 1px solid rgba(255,255,255,0.06);
    background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.85);
    font-size: 11px; outline: none; min-width: 80px; flex: 1;
  }
  .input-sm:focus { border-color: rgba(0,150,255,0.3); }
  .textarea { min-height: 50px; resize: vertical; font-family: 'JetBrains Mono', monospace; }

  /* Steps */
  .steps-list { max-height: 280px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent; }
  .step-card {
    padding: 6px 8px; border-radius: 6px;
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);
    margin-bottom: 4px;
  }
  .step-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
  .step-num { font-size: 10px; color: rgba(255,255,255,0.3); font-weight: 700; }
  .step-type-badge {
    font-size: 9px; padding: 1px 6px; border-radius: 4px;
    background: rgba(0,150,255,0.15); color: rgba(100,200,255,0.9);
    text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;
  }
  .step-summary { font-size: 11px; color: rgba(255,255,255,0.5); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .step-controls { display: flex; gap: 2px; }
  .step-params { display: flex; gap: 4px; flex-wrap: wrap; }
  .check-label { font-size: 11px; color: rgba(255,255,255,0.6); display: flex; align-items: center; gap: 4px; }

  .add-step-row { display: flex; gap: 6px; margin-top: 6px; align-items: center; }
  .footer-row { display: flex; align-items: center; gap: 10px; }
  .save-msg { font-size: 11px; color: rgba(0,255,120,0.7); }

  /* Action chips */
  .action-type-row { display: flex; flex-wrap: wrap; gap: 4px; }
  .action-chip {
    padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);
    background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.6);
    font-size: 11px; cursor: pointer; transition: all 0.15s;
  }
  .action-chip:hover { background: rgba(255,255,255,0.08); }
  .action-chip.active { border-color: rgba(0,200,255,0.4); background: rgba(0,200,255,0.1); color: rgba(255,255,255,0.95); }

  /* Results */
  .result-card {
    padding: 8px 10px; border-radius: 8px;
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06);
  }
  .result-card.success { border-color: rgba(0,255,100,0.2); }
  .result-card.error { border-color: rgba(255,80,80,0.2); }
  .result-status { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .result-error { font-size: 11px; color: rgba(255,80,80,0.8); }
  .result-time { font-size: 10px; color: rgba(255,255,255,0.35); }
  .result-data { font-size: 10px; color: rgba(255,255,255,0.6); background: rgba(0,0,0,0.3); padding: 6px; border-radius: 4px; overflow-x: auto; max-height: 200px; overflow-y: auto; margin-top: 6px; white-space: pre-wrap; word-break: break-all; }

  /* Run progress */
  .running-indicator { display: flex; align-items: center; gap: 8px; font-size: 13px; color: rgba(0,200,255,0.9); }
  .spinner {
    width: 14px; height: 14px; border: 2px solid rgba(0,200,255,0.3);
    border-top-color: rgba(0,200,255,0.9); border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .progress-text { font-size: 11px; color: rgba(255,255,255,0.5); }

  /* Step results */
  .step-result {
    display: flex; align-items: center; gap: 6px; padding: 4px 6px;
    border-radius: 4px; margin-bottom: 2px; font-size: 11px;
  }
  .step-ok { background: rgba(0,255,100,0.04); }
  .step-fail { background: rgba(255,80,80,0.06); }
  .step-duration { color: rgba(255,255,255,0.3); }
  .step-data-count { color: rgba(0,200,255,0.7); font-weight: 600; }
  .step-error { color: rgba(255,80,80,0.7); flex: 1; }

  /* Data display */
  .data-scroll { max-height: 200px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent; }
  .data-item { display: flex; gap: 6px; margin-bottom: 4px; align-items: flex-start; }
  .data-idx { font-size: 10px; color: rgba(255,255,255,0.25); font-weight: 700; min-width: 24px; }
  .data-json { font-size: 10px; color: rgba(255,255,255,0.6); background: rgba(0,0,0,0.2); padding: 4px 6px; border-radius: 4px; flex: 1; white-space: pre-wrap; word-break: break-all; margin: 0; }

  .entity-stats { display: flex; gap: 12px; font-size: 12px; color: rgba(255,255,255,0.6); }

  .screenshot-img { width: 100%; border-radius: 6px; border: 1px solid rgba(255,255,255,0.08); }
</style>
