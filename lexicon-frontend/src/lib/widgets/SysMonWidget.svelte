<!--
  SysMonWidget.svelte — live CPU/RAM/disk monitor.
  Reads from /proc via a polling fetch to the backend.
  Falls back to a simple display if data unavailable.
  Props: { props, onDismiss }
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  let cpu = 0;
  let ram = { used: 0, total: 0, percent: 0 };
  let disk = { used: 0, total: 0, percent: 0 };
  let uptime = '';
  let interval;
  let error = false;

  async function fetchStats() {
    try {
      var res = await fetch('http://127.0.0.1:8000/system');
      if (res.ok) {
        var data = await res.json();
        cpu = data.cpu;
        ram = data.ram;
        disk = data.disk;
        uptime = data.uptime;
        error = false;
      } else {
        error = true;
      }
    } catch (_) {
      error = true;
    }
  }

  onMount(() => {
    fetchStats();
    interval = setInterval(fetchStats, 2000);
  });
  onDestroy(() => clearInterval(interval));

  function formatBytes(b) {
    if (b >= 1073741824) return (b / 1073741824).toFixed(1) + ' GB';
    if (b >= 1048576) return (b / 1048576).toFixed(0) + ' MB';
    return (b / 1024).toFixed(0) + ' KB';
  }
</script>

<div class="sysmon-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>
  <div class="label">SYSTEM</div>

  {#if error}
    <div class="err">Could not reach /system endpoint</div>
  {:else}
    <div class="row">
      <div class="metric">
        <div class="metric-label">CPU</div>
        <div class="bar-track"><div class="bar-fill cpu" style="width:{cpu}%"></div></div>
        <div class="metric-val">{cpu.toFixed(1)}%</div>
      </div>
    </div>

    <div class="row">
      <div class="metric">
        <div class="metric-label">RAM</div>
        <div class="bar-track"><div class="bar-fill ram" style="width:{ram.percent}%"></div></div>
        <div class="metric-val">{formatBytes(ram.used)} / {formatBytes(ram.total)}</div>
      </div>
    </div>

    <div class="row">
      <div class="metric">
        <div class="metric-label">DISK</div>
        <div class="bar-track"><div class="bar-fill disk" style="width:{disk.percent}%"></div></div>
        <div class="metric-val">{formatBytes(disk.used)} / {formatBytes(disk.total)}</div>
      </div>
    </div>

    {#if uptime}
      <div class="uptime">↑ {uptime}</div>
    {/if}
  {/if}
</div>

<style>
  .sysmon-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column; align-items: stretch; justify-content: center;
    color: rgba(255,255,255,0.92);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    padding: 16px 20px;
    box-sizing: border-box;
    gap: 10px;
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
    font-size: 10px; letter-spacing: 3px; color: rgba(0,200,255,0.8);
    font-weight: 600; text-align: center; margin-bottom: 2px;
  }
  .err { font-size: 11px; color: rgba(255,100,100,0.7); text-align: center; }
  .row { display: flex; }
  .metric { flex: 1; display: flex; flex-direction: column; gap: 3px; }
  .metric-label { font-size: 10px; letter-spacing: 2px; color: rgba(255,255,255,0.4); font-weight: 600; }
  .metric-val { font-size: 10px; color: rgba(255,255,255,0.35); }
  .bar-track {
    width: 100%; height: 6px; border-radius: 3px;
    background: rgba(255,255,255,0.06); overflow: hidden;
  }
  .bar-fill {
    height: 100%; border-radius: 3px;
    transition: width 0.5s ease;
  }
  .bar-fill.cpu { background: linear-gradient(90deg, #00c8ff, #0088cc); }
  .bar-fill.ram { background: linear-gradient(90deg, #a78bfa, #7c3aed); }
  .bar-fill.disk { background: linear-gradient(90deg, #50c878, #2e8b57); }
  .uptime {
    font-size: 10px; color: rgba(255,255,255,0.25);
    text-align: center; letter-spacing: 0.5px; margin-top: 2px;
  }
</style>
