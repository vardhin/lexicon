<!--
  DateWidget.svelte — rich date display with day progress.
  Props: { props, onDismiss }
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  let now = new Date();
  let interval;

  onMount(() => {
    interval = setInterval(() => { now = new Date(); }, 60000);
  });
  onDestroy(() => clearInterval(interval));

  $: dayOfYear = Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 86400000);
  $: totalDays = ((now.getFullYear() % 4 === 0 && now.getFullYear() % 100 !== 0) || now.getFullYear() % 400 === 0) ? 366 : 365;
  $: yearProgress = Math.round((dayOfYear / totalDays) * 100);
  $: weekNum = Math.ceil(dayOfYear / 7);
</script>

<div class="date-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>
  <div class="label">DATE</div>
  <div class="day-name">{now.toLocaleDateString('en-US', { weekday: 'long' })}</div>
  <div class="date-big">{now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</div>
  <div class="year">{now.getFullYear()}</div>

  <div class="meta">
    <span>Day {dayOfYear}</span>
    <span>·</span>
    <span>Week {weekNum}</span>
    <span>·</span>
    <span>{yearProgress}% of year</span>
  </div>

  <div class="progress-track">
    <div class="progress-fill" style="width:{yearProgress}%"></div>
  </div>
</div>

<style>
  .date-widget {
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
  .label { font-size: 10px; letter-spacing: 3px; color: rgba(80,200,120,0.8); margin-bottom: 4px; font-weight: 600; }
  .day-name { font-size: 14px; color: rgba(255,255,255,0.5); letter-spacing: 2px; margin-bottom: 4px; }
  .date-big {
    font-size: 36px; font-weight: 700; letter-spacing: 2px; line-height: 1.1;
    background: linear-gradient(135deg, #50c878, #3cb371, #2e8b57);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }
  .year { font-size: 14px; color: rgba(255,255,255,0.35); margin-top: 2px; letter-spacing: 3px; }
  .meta {
    display: flex; gap: 6px; margin-top: 10px;
    font-size: 10px; color: rgba(255,255,255,0.3); letter-spacing: 0.5px;
  }
  .progress-track {
    width: 80%; height: 3px; border-radius: 2px;
    background: rgba(255,255,255,0.06); overflow: hidden;
    margin-top: 8px;
  }
  .progress-fill {
    height: 100%; border-radius: 2px;
    background: linear-gradient(90deg, #50c878, #2e8b57);
  }
</style>
