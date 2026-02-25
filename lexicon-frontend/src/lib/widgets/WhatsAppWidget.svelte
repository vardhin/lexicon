<!--
  WhatsAppWidget.svelte — WhatsApp dashboard + organ tab controls.

  The WhatsApp "organ" is a real web.whatsapp.com tab in a separate
  Tauri WebviewWindow. It is NOT headless — you can switch to it at any
  time to log in (QR scan), browse full chats, etc.

  This widget shows:
    - Organ status (closed / background / visible)
    - "Open WhatsApp" button → switches to the WhatsApp tab
    - Recent messages received from the organ's injection script
    - Contact list with message counts

  Think of this widget as the WhatsApp "dashboard" on your canvas,
  while the real WhatsApp tab is a separate fullscreen view you can
  switch to and from.
-->
<script>
  import { onMount, onDestroy } from 'svelte';

  export let props = {};
  export let onDismiss = () => {};

  let ws = null;
  let organStatus = 'closed';   // 'closed' | 'background' | 'visible'
  let monitorStatus = 'unknown'; // 'connected' | 'waiting_for_qr' | 'disconnected'
  let chats = [];
  let contacts = [];
  let messages = [];
  let selectedContact = props?.filter_contact || null;
  let view = selectedContact ? 'messages' : 'chats';
  let loading = true;
  let tauriInvoke = null;

  if (typeof window !== 'undefined') {
    import('@tauri-apps/api/core').then(mod => {
      tauriInvoke = mod.invoke;
      // Poll organ status on load
      pollOrganStatus();
    }).catch(() => {});
  }

  onMount(() => {
    ws = window.__lexicon_ws;

    if (!window.__lexicon_whatsapp_listeners) {
      window.__lexicon_whatsapp_listeners = [];
    }
    window.__lexicon_whatsapp_listeners.push(onWaMessage);

    // Request initial data from Brain
    if (ws && ws.isOpen()) {
      ws.send({ type: 'whatsapp_get_chats', limit: 30 });
      if (selectedContact) {
        ws.send({ type: 'whatsapp_get_messages', contact: selectedContact, limit: 50 });
      }
    }

    // Fetch Brain-side monitor status
    fetchMonitorStatus();
  });

  onDestroy(() => {
    if (window.__lexicon_whatsapp_listeners) {
      window.__lexicon_whatsapp_listeners = window.__lexicon_whatsapp_listeners.filter(
        fn => fn !== onWaMessage
      );
    }
  });

  function onWaMessage(msg) {
    if (msg.type === 'WHATSAPP_CHATS') {
      chats = msg.chats || [];
      contacts = msg.contacts || [];
      monitorStatus = msg.organ_status || monitorStatus;
      loading = false;
    }
    else if (msg.type === 'WHATSAPP_MESSAGES') {
      if (msg.contact === selectedContact || !selectedContact) {
        messages = msg.messages || [];
      }
      loading = false;
    }
    else if (msg.type === 'WHATSAPP_MESSAGE') {
      var newMsg = {
        contact: msg.contact,
        chat: msg.chat,
        text: msg.text,
        timestamp: msg.timestamp,
        message_id: msg.message_id,
        unread_count: msg.unread_count || 0,
      };
      var found = false;
      chats = chats.map(function (c) {
        if (c.contact === msg.contact) {
          found = true;
          return Object.assign({}, c, { text: msg.text, timestamp: msg.timestamp, unread_count: msg.unread_count || 0 });
        }
        return c;
      });
      if (!found) {
        chats = [newMsg].concat(chats);
      }
      if (view === 'messages' && (!selectedContact || selectedContact === msg.contact)) {
        messages = messages.concat([newMsg]);
      }
    }
    else if (msg.type === 'WHATSAPP_STATUS') {
      monitorStatus = msg.status;
    }
  }

  function fetchMonitorStatus() {
    fetch('http://127.0.0.1:8000/whatsapp/status')
      .then(r => r.json())
      .then(data => { monitorStatus = data.status || 'disconnected'; })
      .catch(() => { monitorStatus = 'disconnected'; });
  }

  function pollOrganStatus() {
    if (!tauriInvoke) return;
    tauriInvoke('whatsapp_organ_status').then(status => {
      organStatus = status; // "closed" | "background" | "visible"
    }).catch(() => {});
  }

  // ── Tab switching ──

  /** Open or switch to the WhatsApp tab (real web.whatsapp.com) */
  function openWhatsAppTab() {
    if (!tauriInvoke) return;
    tauriInvoke('open_whatsapp_organ').then(() => {
      organStatus = 'visible';
    }).catch(err => {
      console.error('Failed to open WhatsApp tab:', err);
    });
  }

  /** Hide WhatsApp tab (sends it to background, keeps it running) */
  function hideWhatsAppTab() {
    if (!tauriInvoke) return;
    tauriInvoke('show_whatsapp_organ', { visible: false }).then(() => {
      organStatus = 'background';
    }).catch(() => {});
  }

  /** Close the WhatsApp tab entirely (kills the webview) */
  function closeWhatsAppTab() {
    if (!tauriInvoke) return;
    tauriInvoke('close_whatsapp_organ').then(() => {
      organStatus = 'closed';
      monitorStatus = 'disconnected';
    }).catch(() => {});
  }

  function selectContact(contact) {
    selectedContact = contact;
    view = 'messages';
    loading = true;
    if (ws && ws.isOpen()) {
      ws.send({ type: 'whatsapp_get_messages', contact: contact, limit: 50 });
    }
  }

  function backToChats() {
    selectedContact = null;
    view = 'chats';
    messages = [];
  }

  function formatTime(ts) {
    if (!ts) return '';
    try {
      var d = new Date(ts);
      var now = new Date();
      if (d.toDateString() === now.toDateString()) {
        return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
      }
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch (_) {
      return '';
    }
  }

  function organStatusColor(s) {
    if (s === 'visible') return '#7c8aff';
    if (s === 'background') return '#28c840';
    return '#ff5f57';
  }

  function organStatusLabel(s) {
    if (s === 'visible') return 'Active Tab';
    if (s === 'background') return 'Running';
    return 'Not Started';
  }

  function monitorColor(s) {
    if (s === 'connected') return '#28c840';
    if (s === 'waiting_for_qr') return '#ffbd2e';
    return '#ff5f57';
  }

  function monitorLabel(s) {
    if (s === 'connected') return 'Monitoring';
    if (s === 'waiting_for_qr') return 'Needs QR Login';
    return 'Offline';
  }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="wa-widget">
  <button class="dismiss" on:click={onDismiss}>✕</button>

  <!-- Header -->
  <div class="wa-header">
    {#if view === 'messages' && selectedContact}
      <span class="wa-back" on:click={backToChats}>←</span>
      <span class="wa-title">{selectedContact}</span>
    {:else}
      <span class="wa-icon">💬</span>
      <span class="wa-title">WhatsApp</span>
    {/if}
    <div class="wa-status-group">
      <span class="wa-status-dot" style="background:{organStatusColor(organStatus)}"></span>
      <span class="wa-status-label">{organStatusLabel(organStatus)}</span>
      {#if organStatus !== 'closed'}
        <span class="wa-status-sep">·</span>
        <span class="wa-status-dot" style="background:{monitorColor(monitorStatus)}"></span>
        <span class="wa-status-label">{monitorLabel(monitorStatus)}</span>
      {/if}
    </div>
  </div>

  <!-- Tab control bar -->
  <div class="wa-tab-bar">
    {#if organStatus === 'closed'}
      <!-- Not started yet — prominent "Open WhatsApp" button -->
      <button class="wa-tab-btn primary" on:click={openWhatsAppTab}>
        💬 Open WhatsApp Tab
      </button>
      <span class="wa-tab-hint">Opens web.whatsapp.com — log in with QR code</span>
    {:else if organStatus === 'background'}
      <!-- Running in background -->
      <button class="wa-tab-btn primary" on:click={openWhatsAppTab}>
        ↗ Switch to WhatsApp
      </button>
      <button class="wa-tab-btn danger" on:click={closeWhatsAppTab}>
        ✕ Close
      </button>
    {:else}
      <!-- Currently viewing WhatsApp tab -->
      <button class="wa-tab-btn" on:click={hideWhatsAppTab}>
        ← Back to Lexicon
      </button>
      <button class="wa-tab-btn danger" on:click={closeWhatsAppTab}>
        ✕ Close
      </button>
    {/if}
  </div>

  {#if organStatus !== 'closed' && monitorStatus === 'waiting_for_qr'}
    <div class="wa-qr-bar">
      ⚠ Switch to the WhatsApp tab and scan the QR code to log in
    </div>
  {/if}

  <!-- Content -->
  <div class="wa-content">
    {#if loading && chats.length === 0 && messages.length === 0}
      <div class="wa-empty">
        {#if organStatus === 'closed'}
          Open the WhatsApp tab to start receiving messages
        {:else if monitorStatus === 'connected'}
          Waiting for messages…
        {:else if monitorStatus === 'waiting_for_qr'}
          Log in to WhatsApp first
        {:else}
          Loading…
        {/if}
      </div>

    {:else if view === 'chats'}
      {#if chats.length === 0}
        <div class="wa-empty">No messages yet</div>
      {:else}
        {#each chats as chat}
          <div class="wa-chat-item" on:click={() => selectContact(chat.contact)}>
            <div class="wa-avatar">{chat.contact.charAt(0).toUpperCase()}</div>
            <div class="wa-chat-info">
              <div class="wa-chat-name">
                {chat.contact}
                {#if chat.unread_count > 0}
                  <span class="wa-unread-badge">{chat.unread_count}</span>
                {/if}
              </div>
              <div class="wa-chat-preview">{chat.text}</div>
            </div>
            <div class="wa-chat-time">{formatTime(chat.timestamp)}</div>
          </div>
        {/each}
      {/if}

    {:else if view === 'messages'}
      {#if messages.length === 0}
        <div class="wa-empty">No messages from {selectedContact}</div>
      {:else}
        <div class="wa-messages">
          {#each messages as msg}
            <div class="wa-msg incoming">
              <div class="wa-msg-text">{msg.text}</div>
              <div class="wa-msg-time">{formatTime(msg.timestamp)}</div>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  </div>

  <!-- Footer -->
  <div class="wa-footer">
    {contacts.length} contact{contacts.length !== 1 ? 's' : ''} · {chats.length} chat{chats.length !== 1 ? 's' : ''}
  </div>
</div>

<style>
  .wa-widget {
    position: relative; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    color: rgba(255,255,255,0.92);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    box-sizing: border-box;
    overflow: hidden;
  }

  .dismiss {
    position: absolute; top: 8px; right: 10px;
    background: none; border: none;
    color: rgba(255,255,255,0.3); font-size: 14px;
    cursor: pointer; padding: 4px 8px; border-radius: 4px;
    z-index: 2;
  }
  .dismiss:hover { color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.08); }

  /* ── Header ── */
  .wa-header {
    display: flex; align-items: center; gap: 8px;
    padding: 12px 14px 8px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    flex-shrink: 0;
  }
  .wa-icon { font-size: 18px; }
  .wa-title {
    font-size: 13px; font-weight: 700;
    color: rgba(37,211,102,0.9);
    letter-spacing: 0.5px;
    flex: 1;
  }
  .wa-back {
    font-size: 16px; cursor: pointer;
    color: rgba(37,211,102,0.7);
    padding: 2px 8px 2px 0;
    transition: color 0.15s;
  }
  .wa-back:hover { color: rgba(37,211,102,1); }
  .wa-status-group {
    display: flex; align-items: center; gap: 5px;
  }
  .wa-status-dot {
    width: 6px; height: 6px; border-radius: 50%;
    flex-shrink: 0;
  }
  .wa-status-label {
    font-size: 9px; color: rgba(255,255,255,0.35);
    letter-spacing: 0.3px;
  }
  .wa-status-sep {
    font-size: 9px; color: rgba(255,255,255,0.12);
    margin: 0 1px;
  }

  /* ── Tab control bar ── */
  .wa-tab-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 14px;
    background: rgba(255,255,255,0.02);
    border-bottom: 1px solid rgba(255,255,255,0.04);
    flex-shrink: 0;
    flex-wrap: wrap;
  }
  .wa-tab-btn {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.7);
    font-size: 11px; font-weight: 600;
    padding: 6px 14px; border-radius: 8px;
    cursor: pointer;
    font-family: inherit;
    transition: all 0.15s;
  }
  .wa-tab-btn:hover {
    background: rgba(255,255,255,0.1);
    border-color: rgba(255,255,255,0.18);
    color: rgba(255,255,255,0.9);
  }
  .wa-tab-btn.primary {
    background: rgba(37,211,102,0.15);
    border-color: rgba(37,211,102,0.25);
    color: rgba(37,211,102,0.95);
  }
  .wa-tab-btn.primary:hover {
    background: rgba(37,211,102,0.25);
    border-color: rgba(37,211,102,0.4);
  }
  .wa-tab-btn.danger {
    background: rgba(255,95,87,0.08);
    border-color: rgba(255,95,87,0.15);
    color: rgba(255,95,87,0.7);
    font-size: 10px;
  }
  .wa-tab-btn.danger:hover {
    background: rgba(255,95,87,0.18);
    border-color: rgba(255,95,87,0.3);
    color: rgba(255,95,87,0.9);
  }
  .wa-tab-hint {
    font-size: 9px; color: rgba(255,255,255,0.2);
    margin-left: 4px;
  }

  /* ── QR bar ── */
  .wa-qr-bar {
    padding: 8px 14px;
    font-size: 10px; font-weight: 600;
    color: rgba(255,189,46,0.85);
    background: rgba(255,189,46,0.06);
    border-bottom: 1px solid rgba(255,189,46,0.1);
    flex-shrink: 0;
  }

  /* ── Content ── */
  .wa-content {
    flex: 1; overflow-y: auto;
    padding: 4px 0;
  }
  .wa-content::-webkit-scrollbar { width: 3px; }
  .wa-content::-webkit-scrollbar-track { background: transparent; }
  .wa-content::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.06); border-radius: 2px; }

  .wa-empty {
    display: flex; align-items: center; justify-content: center;
    height: 100%;
    font-size: 11px; color: rgba(255,255,255,0.25);
    text-align: center;
    padding: 20px;
  }

  /* ── Chat list ── */
  .wa-chat-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px;
    cursor: pointer;
    transition: background 0.12s;
    border-bottom: 1px solid rgba(255,255,255,0.03);
  }
  .wa-chat-item:hover { background: rgba(255,255,255,0.04); }

  .wa-avatar {
    width: 36px; height: 36px; border-radius: 50%;
    background: rgba(37,211,102,0.15);
    color: rgba(37,211,102,0.9);
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700;
    flex-shrink: 0;
  }

  .wa-chat-info { flex: 1; min-width: 0; }
  .wa-chat-name {
    font-size: 12px; font-weight: 600;
    color: rgba(255,255,255,0.85);
    display: flex; align-items: center; gap: 6px;
  }
  .wa-chat-preview {
    font-size: 10px; color: rgba(255,255,255,0.35);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    margin-top: 2px;
  }
  .wa-chat-time {
    font-size: 9px; color: rgba(255,255,255,0.25);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .wa-unread-badge {
    background: rgba(37,211,102,0.8);
    color: #fff;
    font-size: 9px; font-weight: 700;
    padding: 1px 6px; border-radius: 10px;
    min-width: 14px; text-align: center;
  }

  /* ── Messages ── */
  .wa-messages {
    display: flex; flex-direction: column;
    gap: 6px; padding: 8px 14px;
  }
  .wa-msg {
    max-width: 85%;
    padding: 8px 12px;
    border-radius: 12px;
    position: relative;
  }
  .wa-msg.incoming {
    align-self: flex-start;
    background: rgba(37,211,102,0.08);
    border: 1px solid rgba(37,211,102,0.12);
    border-top-left-radius: 4px;
  }
  .wa-msg-text {
    font-size: 12px; line-height: 1.5;
    color: rgba(255,255,255,0.82);
    word-break: break-word;
  }
  .wa-msg-time {
    font-size: 8px; color: rgba(255,255,255,0.2);
    text-align: right; margin-top: 4px;
  }

  /* ── Footer ── */
  .wa-footer {
    padding: 6px 14px;
    font-size: 9px; color: rgba(255,255,255,0.15);
    text-align: center;
    border-top: 1px solid rgba(255,255,255,0.04);
    flex-shrink: 0;
  }
</style>
