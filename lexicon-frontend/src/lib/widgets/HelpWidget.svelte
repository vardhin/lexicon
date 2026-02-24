<!--
  HelpWidget.svelte — lists all available commands with icons, descriptions, and examples.
  Props: { props: { entries: [{ title, icon, description, examples }] }, onDismiss }
-->
<script>
  export let props = {};
  export let onDismiss = () => {};

  let entries = props?.entries || [];

  // Tip shown at the bottom
  let tips = [
    'Drag widgets by the dots ⋮⋮ at the top',
    'Press ↑↓ in the bar to cycle command history',
    'Press Escape to clear the input',
    'Widget positions are saved automatically',
    'Type "clear" to dismiss everything',
  ];
  let tipIdx = Math.floor(Math.random() * tips.length);
</script>

<div class="help-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>

  <div class="header">
    <div class="label">LEXICON HELP</div>
    <div class="subtitle">{entries.length} commands available</div>
  </div>

  <div class="entries">
    {#each entries as entry}
      <div class="entry">
        <div class="entry-head">
          <span class="entry-icon">{entry.icon}</span>
          <span class="entry-title">{entry.title}</span>
        </div>
        <div class="entry-desc">{entry.description}</div>
        <div class="entry-examples">
          {#each entry.examples as ex}
            <span class="example">{ex}</span>
          {/each}
        </div>
      </div>
    {/each}
  </div>

  <div class="tip">💡 {tips[tipIdx]}</div>
</div>

<style>
  .help-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    color: rgba(255,255,255,0.92);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    padding: 14px 16px 12px;
    box-sizing: border-box;
  }

  .dismiss {
    position: absolute; top: 8px; right: 10px;
    background: none; border: none;
    color: rgba(255,255,255,0.3); font-size: 14px;
    cursor: pointer; padding: 4px 8px; border-radius: 4px;
    z-index: 2;
  }
  .dismiss:hover { color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.08); }

  .header { text-align: center; margin-bottom: 12px; padding-top: 14px; }
  .label {
    font-size: 11px; letter-spacing: 3px;
    color: rgba(124,138,255,0.9);
    font-weight: 700; margin-bottom: 2px;
  }
  .subtitle { font-size: 10px; color: rgba(255,255,255,0.25); letter-spacing: 0.5px; }

  .entries {
    flex: 1;
    overflow-y: auto;
    display: flex; flex-direction: column; gap: 8px;
    padding-right: 4px;
  }
  /* thin scrollbar */
  .entries::-webkit-scrollbar { width: 3px; }
  .entries::-webkit-scrollbar-track { background: transparent; }
  .entries::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

  .entry {
    padding: 10px 12px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 10px;
    transition: background 0.15s, border-color 0.15s;
  }
  .entry:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(255,255,255,0.1);
  }

  .entry-head { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }
  .entry-icon { font-size: 15px; }
  .entry-title { font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.85); }

  .entry-desc { font-size: 11px; color: rgba(255,255,255,0.4); margin-bottom: 6px; line-height: 1.3; }

  .entry-examples { display: flex; flex-wrap: wrap; gap: 5px; }
  .example {
    font-size: 10px;
    padding: 3px 8px;
    background: rgba(124,138,255,0.1);
    border: 1px solid rgba(124,138,255,0.15);
    border-radius: 6px;
    color: rgba(124,138,255,0.8);
    letter-spacing: 0.3px;
  }

  .tip {
    margin-top: 10px; padding-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.05);
    font-size: 10px; color: rgba(255,255,255,0.2);
    text-align: center; letter-spacing: 0.3px;
  }
</style>
