<!--
  WeatherWidget.svelte — weather display (demo/placeholder).
  In production this would fetch from a weather API.
  Props: { props, onDismiss }
-->
<!-- svelte-ignore export_let_unused -->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  let hour = new Date().getHours();
  let interval;

  onMount(() => {
    interval = setInterval(() => { hour = new Date().getHours(); }, 60000);
  });
  onDestroy(() => clearInterval(interval));

  // Simple time-based "weather" for demo
  $: isNight = hour < 6 || hour >= 20;
  $: icon = isNight ? '🌙' : (hour >= 6 && hour < 10) ? '🌤' : (hour >= 10 && hour < 16) ? '☀️' : '🌅';
  $: condition = isNight ? 'Clear Night' : (hour >= 6 && hour < 10) ? 'Morning' : (hour >= 10 && hour < 16) ? 'Sunny' : 'Evening';
  $: temp = isNight ? '18°' : (hour >= 10 && hour < 16) ? '26°' : '22°';
</script>

<div class="weather-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>
  <div class="label">WEATHER</div>
  <div class="weather-icon">{icon}</div>
  <div class="temp">{temp}</div>
  <div class="condition">{condition}</div>
  <div class="note">Demo mode — connect API for real data</div>
</div>

<style>
  .weather-widget {
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
  .label { font-size: 10px; letter-spacing: 3px; color: rgba(255,180,50,0.8); margin-bottom: 6px; font-weight: 600; }
  .weather-icon { font-size: 48px; margin-bottom: 6px; line-height: 1; }
  .temp {
    font-size: 36px; font-weight: 700; letter-spacing: 2px; line-height: 1;
    background: linear-gradient(135deg, #ffb432, #ff8c00, #ff6347);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }
  .condition { font-size: 12px; color: rgba(255,255,255,0.5); margin-top: 4px; letter-spacing: 1px; }
  .note {
    position: absolute; bottom: 10px; left: 0; right: 0;
    font-size: 8px; color: rgba(255,255,255,0.15);
    text-align: center; letter-spacing: 0.5px;
  }
</style>
