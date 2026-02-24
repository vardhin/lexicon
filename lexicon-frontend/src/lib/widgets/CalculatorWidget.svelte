<!--
  CalculatorWidget.svelte — shows expression and result.
  Props: { props: { expression, result }, onDismiss }
-->
<script>
  export let props = {};
  export let onDismiss = () => {};

  let expression = props?.expression || '';
  let result = props?.result || '0';
</script>

<div class="calc-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>
  <div class="label">CALC</div>
  <div class="expression">{expression}</div>
  <div class="equals">=</div>
  <div class="result">{result}</div>
</div>

<style>
  .calc-widget {
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
  .label { font-size: 10px; letter-spacing: 3px; color: rgba(200,150,255,0.8); margin-bottom: 8px; font-weight: 600; }
  .expression {
    font-size: 16px; color: rgba(255,255,255,0.5);
    letter-spacing: 1px; margin-bottom: 4px;
    word-break: break-all; text-align: center;
    max-width: 90%;
  }
  .equals { font-size: 14px; color: rgba(255,255,255,0.25); margin: 2px 0; }
  .result {
    font-size: 40px; font-weight: 700; letter-spacing: 2px; line-height: 1;
    background: linear-gradient(135deg, #c896ff, #a78bfa, #8b5cf6);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    word-break: break-all; text-align: center;
    max-width: 90%;
  }
</style>
