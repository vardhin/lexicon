<!--
  NoteWidget.svelte — sticky note with editable text.
  Props: { props: { text }, onDismiss }
-->
<script>
  export let props = {};
  export let onDismiss = () => {};

  let text = props?.text || '';
  let editing = false;
  let textareaEl;

  function startEdit() {
    editing = true;
    setTimeout(() => { if (textareaEl) textareaEl.focus(); }, 50);
  }

  function stopEdit() {
    editing = false;
  }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="note-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>
  <div class="label">NOTE</div>

  {#if editing}
    <textarea
      bind:this={textareaEl}
      bind:value={text}
      on:blur={stopEdit}
      on:keydown={(e) => { if (e.key === 'Escape') stopEdit(); }}
      class="note-edit"
      spellcheck="false"
    ></textarea>
  {:else}
    <div class="note-text" on:click={startEdit}>
      {text || 'Click to edit...'}
    </div>
  {/if}

  <div class="note-footer">{text.length} chars</div>
</div>

<style>
  .note-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    color: rgba(255,255,255,0.92);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    padding: 12px;
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
  .label {
    font-size: 10px; letter-spacing: 3px; color: rgba(255,200,60,0.8);
    margin-bottom: 10px; font-weight: 600; text-align: center;
  }
  .note-text {
    flex: 1; padding: 8px;
    font-size: 13px; line-height: 1.5;
    color: rgba(255,255,255,0.8);
    cursor: text;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-y: auto;
    border-radius: 8px;
    transition: background 0.15s;
  }
  .note-text:hover { background: rgba(255,255,255,0.03); }
  .note-edit {
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,200,60,0.3);
    border-radius: 8px;
    color: rgba(255,255,255,0.9);
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px; line-height: 1.5;
    padding: 8px; resize: none; outline: none;
  }
  .note-footer {
    text-align: right;
    font-size: 9px;
    color: rgba(255,255,255,0.2);
    margin-top: 4px;
    letter-spacing: 0.5px;
  }
</style>
