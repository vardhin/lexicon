<!--
  TerminalWidget.svelte — output-only terminal display on the canvas.

  This widget renders PTY output from a shell session. It does NOT capture
  keyboard input — all input goes through the synapse bar. This makes the
  terminal feel like part of the canvas background rather than a separate window.

  Props: {
    session_id: string,   — PTY session id this widget displays
  }
-->
<script>
  import { onMount, onDestroy, tick } from 'svelte';
  import { Terminal } from '@xterm/xterm';
  import { FitAddon } from '@xterm/addon-fit';
  import { WebLinksAddon } from '@xterm/addon-web-links';
  import '@xterm/xterm/css/xterm.css';

  export let props = {};
  export let onDismiss = () => {};

  let containerEl;
  let term = null;
  let fitAddon = null;
  let alive = false;
  let shellName = 'shell';
  let connected = false;

  const sessionId = props.session_id || 'default';

  function sendWS(msg) {
    var ws = window.__lexicon_ws;
    if (ws && ws.isOpen()) ws.send(msg);
  }

  onMount(async () => {
    alive = true;

    term = new Terminal({
      cursorBlink: false,
      cursorStyle: 'underline',
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
      fontSize: 12,
      lineHeight: 1.3,
      disableStdin: true,
      theme: {
        background: '#0a0a14',
        foreground: 'rgba(255, 255, 255, 0.85)',
        cursor: '#7c8aff',
        cursorAccent: '#0a0a14',
        selectionBackground: 'rgba(124, 138, 255, 0.25)',
        black: '#1a1a2e',
        red: '#ff5f57',
        green: '#50c878',
        yellow: '#ffcc00',
        blue: '#7c8aff',
        magenta: '#c678dd',
        cyan: '#56b6c2',
        white: '#dcdfe4',
        brightBlack: '#5c6370',
        brightRed: '#ff6b6b',
        brightGreen: '#69db7c',
        brightYellow: '#ffd43b',
        brightBlue: '#91a7ff',
        brightMagenta: '#da77f2',
        brightCyan: '#66d9ef',
        brightWhite: '#ffffff',
      },
      allowTransparency: false,
      scrollback: 10000,
      convertEol: false,
    });

    fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());

    await tick();

    if (containerEl && alive) {
      term.open(containerEl);
      await tick();
      try { fitAddon.fit(); } catch (_) {}

      if (!window.__lexicon_terminals) window.__lexicon_terminals = {};
      window.__lexicon_terminals[sessionId] = {
        onOutput: function (data) { if (term) term.write(data); },
        onSpawned: function (info) {
          connected = true;
          shellName = info.shell || 'shell';
        },
        onExited: function (exitCode) {
          connected = false;
          if (term) {
            term.writeln('\r\n\x1b[1;31m● Shell exited (code ' + (exitCode ?? -1) + ')\x1b[0m');
            term.writeln('\x1b[90mType a command in the synapse bar to reconnect.\x1b[0m');
          }
        },
        onError: function (message) {
          connected = false;
          if (term) {
            term.writeln('\r\n\x1b[1;31m✖ ' + (message || 'Shell error') + '\x1b[0m');
          }
        },
      };

      term.onResize(function (size) {
        sendWS({ type: 'shell_resize', session_id: sessionId, cols: size.cols, rows: size.rows });
      });
    }
  });

  onDestroy(() => {
    alive = false;
    if (window.__lexicon_terminals) {
      delete window.__lexicon_terminals[sessionId];
    }
    if (resizeObserver) resizeObserver.disconnect();
    if (term) { term.dispose(); term = null; }
  });

  let resizeObserver;
  $: if (containerEl && fitAddon && term) {
    if (resizeObserver) resizeObserver.disconnect();
    resizeObserver = new ResizeObserver(function () {
      try { fitAddon.fit(); } catch (_) {}
    });
    resizeObserver.observe(containerEl);
  }
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="terminal-widget">
  <div class="tw-header">
    <span class="tw-title">
      <span class="tw-icon">🐚</span>
      <span class="tw-name">{shellName}</span>
      <span class="tw-sid">{sessionId}</span>
      {#if connected}
        <span class="tw-dot on">●</span>
      {:else}
        <span class="tw-dot off">●</span>
      {/if}
    </span>
    <div class="tw-actions">
      <!-- svelte-ignore a11y-click-events-have-key-events -->
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <span class="tw-btn" on:click={() => { if (term) term.clear(); }} title="Clear display">⌫</span>
      <!-- svelte-ignore a11y-click-events-have-key-events -->
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <span class="tw-btn dismiss" on:click={onDismiss} title="Close display">✕</span>
    </div>
  </div>
  <div class="tw-body" bind:this={containerEl}></div>
</div>

<style>
  .terminal-widget {
    width: 100%; height: 100%;
    display: flex; flex-direction: column;
    background: rgba(8, 8, 18, 0.85);
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.06);
    overflow: hidden;
    box-shadow: 0 4px 24px rgba(0,0,0,0.3);
  }
  .tw-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 12px;
    height: 28px; min-height: 28px;
    background: rgba(15, 15, 28, 0.8);
    user-select: none;
  }
  .tw-title {
    display: flex; align-items: center; gap: 6px;
    font-size: 10px; font-weight: 600;
    color: rgba(255,255,255,0.45);
    letter-spacing: 0.5px;
    overflow: hidden;
  }
  .tw-icon { font-size: 12px; }
  .tw-name { color: rgba(255,255,255,0.55); }
  .tw-sid {
    color: rgba(255,255,255,0.2);
    font-size: 9px; font-weight: 400;
    max-width: 100px;
    overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tw-dot { font-size: 7px; }
  .tw-dot.on { color: #28c840; }
  .tw-dot.off { color: #ff5f57; }
  .tw-actions { display: flex; gap: 2px; }
  .tw-btn {
    width: 22px; height: 22px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 5px; font-size: 11px;
    color: rgba(255,255,255,0.3);
    cursor: pointer; transition: all 0.12s;
  }
  .tw-btn:hover {
    color: rgba(255,255,255,0.7);
    background: rgba(255,255,255,0.06);
  }
  .tw-btn.dismiss:hover {
    color: #ff5f57;
    background: rgba(255,95,87,0.1);
  }
  .tw-body {
    flex: 1;
    padding: 4px 6px 6px;
    overflow: hidden;
  }
  .tw-body :global(.xterm) { height: 100%; }
  .tw-body :global(.xterm-viewport) { overflow-y: auto !important; }
  .tw-body :global(.xterm-screen) { height: 100%; }
</style>
