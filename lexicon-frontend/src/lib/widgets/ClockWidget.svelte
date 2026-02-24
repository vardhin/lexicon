<!--
  ClockWidget.svelte — live updating clock.
  Props: { props, onDismiss }
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  let time = '';
  let interval;

  function updateTime() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    time = props?.show_seconds !== false ? `${h}:${m}:${s}` : `${h}:${m}`;
  }

  onMount(() => {
    updateTime();
    interval = setInterval(updateTime, 1000);
  });

  onDestroy(() => clearInterval(interval));
</script>

<div class="clock-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>
  <div class="label">CLOCK</div>
  <div class="time">{time}</div>
  <div class="sub">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</div>
</div>

<style>
  .clock-widget {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: rgba(255,255,255,0.92);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
  }
  .dismiss {
    position: absolute; top: 8px; right: 10px;
    background: none; border: none;
    color: rgba(255,255,255,0.3); font-size: 14px;
    cursor: pointer; padding: 4px 8px; border-radius: 4px;
  }
  .dismiss:hover { color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.08); }
  .label { font-size: 10px; letter-spacing: 3px; color: rgba(124,138,255,0.7); margin-bottom: 8px; font-weight: 600; }
  .time {
    font-size: 48px; font-weight: 700; letter-spacing: 4px; line-height: 1;
    background: linear-gradient(135deg, #7c8aff, #a78bfa, #818cf8);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }
  .sub { font-size: 12px; color: rgba(255,255,255,0.35); margin-top: 10px; letter-spacing: 1px; }
</style>
