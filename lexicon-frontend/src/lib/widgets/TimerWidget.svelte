<!--
  TimerWidget.svelte — countdown timer with start/pause/reset.
  Props: { props: { seconds }, onDismiss }
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  let totalSeconds = props?.seconds || 300;
  let remaining = totalSeconds;
  let running = true;
  let interval = null;
  let done = false;

  function formatTime(s) {
    if (s <= 0) return '0:00';
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    return m + ':' + String(sec).padStart(2, '0');
  }

  function tick() {
    if (remaining > 0) {
      remaining--;
    }
    if (remaining <= 0) {
      done = true;
      running = false;
      clearInterval(interval);
      interval = null;
    }
  }

  function togglePause() {
    if (done) return;
    running = !running;
    if (running) {
      interval = setInterval(tick, 1000);
    } else {
      clearInterval(interval);
      interval = null;
    }
  }

  function reset() {
    remaining = totalSeconds;
    done = false;
    running = true;
    clearInterval(interval);
    interval = setInterval(tick, 1000);
  }

  onMount(() => {
    interval = setInterval(tick, 1000);
  });

  onDestroy(() => {
    if (interval) clearInterval(interval);
  });

  $: progress = totalSeconds > 0 ? (1 - remaining / totalSeconds) : 1;
</script>

<div class="timer-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>
  <div class="label">TIMER</div>
  <div class="time" class:done>{formatTime(remaining)}</div>

  <!-- progress bar -->
  <div class="progress-track">
    <div class="progress-fill" style="width:{progress * 100}%"></div>
  </div>

  <div class="controls">
    {#if done}
      <button class="ctrl-btn" on:click={reset}>↻ Reset</button>
    {:else}
      <button class="ctrl-btn" on:click={togglePause}>{running ? '⏸ Pause' : '▶ Resume'}</button>
      <button class="ctrl-btn" on:click={reset}>↻ Reset</button>
    {/if}
  </div>

  {#if done}
    <div class="done-msg">⏰ Time's up!</div>
  {/if}
</div>

<style>
  .timer-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
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
  }
  .dismiss:hover { color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.08); }
  .label { font-size: 10px; letter-spacing: 3px; color: rgba(255,170,80,0.8); margin-bottom: 6px; font-weight: 600; }
  .time {
    font-size: 44px; font-weight: 700; letter-spacing: 3px; line-height: 1;
    background: linear-gradient(135deg, #ffaa50, #ff6b6b, #ffa07a);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    margin-bottom: 12px;
  }
  .time.done {
    animation: pulse 0.6s ease-in-out infinite alternate;
  }
  @keyframes pulse {
    from { opacity: 0.5; }
    to { opacity: 1; }
  }
  .progress-track {
    width: 80%; height: 4px; border-radius: 2px;
    background: rgba(255,255,255,0.08);
    overflow: hidden; margin-bottom: 12px;
  }
  .progress-fill {
    height: 100%; border-radius: 2px;
    background: linear-gradient(90deg, #ffaa50, #ff6b6b);
    transition: width 1s linear;
  }
  .controls { display: flex; gap: 8px; }
  .ctrl-btn {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.6); border-radius: 8px;
    padding: 6px 14px; font-size: 11px; cursor: pointer;
    font-family: 'JetBrains Mono', monospace;
    transition: all 0.15s;
  }
  .ctrl-btn:hover {
    background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.9);
    border-color: rgba(255,255,255,0.2);
  }
  .done-msg {
    margin-top: 8px; font-size: 12px; color: #ff6b6b;
    letter-spacing: 1px; animation: pulse 0.6s ease-in-out infinite alternate;
  }
</style>
