/**
 * WhatsApp DOM Monitor — injected into the WhatsApp organ WebView.
 *
 * Watches the DOM for incoming messages and sends them to the Rust
 * backend via Tauri IPC (bypasses CSP). Rust forwards to Brain HTTP.
 *
 * DOM structure findings (as of 2026):
 *   - Open chat messages: div.message-in (incoming), div.message-out (outgoing)
 *   - Message text: nested <span> tags inside the message div
 *   - Sidebar contacts panel: items have class _ak8j
 *   - Contact/group name: elements with title="..." attribute
 *   - Preview text + sender info: <span> tags inside sidebar items
 */

(function () {
  'use strict';

  var seenMessages = new Set();
  var seenSidebarItems = new Set();
  var observerStarted = false;
  var retryCount = 0;
  var MAX_RETRIES = 180;

  // ── Tauri IPC bridge ──

  function tauriInvoke(cmd, args) {
    try {
      if (window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke) {
        return window.__TAURI_INTERNALS__.invoke(cmd, args || {});
      }
    } catch (e) {
      console.warn('[lexicon/wa] Tauri IPC unavailable:', e);
    }
    return Promise.reject('no tauri');
  }

  function relayMessage(data) {
    console.log('[lexicon/wa] →', data.contact, ':', (data.text || '').substring(0, 60));
    tauriInvoke('wa_relay_message', { payload: JSON.stringify(data) }).then(function () {
      console.log('[lexicon/wa] ✓ relayed');
    }).catch(function (err) {
      console.warn('[lexicon/wa] IPC failed:', err, '— trying HTTP');
      try {
        fetch('http://127.0.0.1:8000/whatsapp/message', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        }).catch(function () {});
      } catch (_) {}
    });
  }

  function relayStatus(status) {
    console.log('[lexicon/wa] status:', status);
    tauriInvoke('wa_relay_status', { status: status }).catch(function () {
      try {
        fetch('http://127.0.0.1:8000/whatsapp/status', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: status, timestamp: new Date().toISOString() }),
        }).catch(function () {});
      } catch (_) {}
    });
  }

  // ── Keyboard shortcut: Escape → switch back to Lexicon ──
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      tauriInvoke('show_whatsapp_organ', { visible: false }).catch(function () {});
    }
  }, true);

  // ── Floating "Back to Lexicon" button ──
  function injectBackButton() {
    if (document.getElementById('lexicon-back-btn')) return;
    var btn = document.createElement('div');
    btn.id = 'lexicon-back-btn';
    btn.innerHTML = '⟵ Lexicon';
    btn.style.cssText = [
      'position:fixed', 'top:12px', 'right:16px', 'z-index:999999',
      'background:rgba(10,10,20,0.85)', 'color:rgba(124,138,255,0.95)',
      'font-family:monospace', 'font-size:12px', 'font-weight:700',
      'padding:6px 14px', 'border-radius:8px',
      'border:1px solid rgba(124,138,255,0.3)',
      'cursor:pointer', 'user-select:none',
      'backdrop-filter:blur(8px)', '-webkit-backdrop-filter:blur(8px)',
      'transition:all 0.15s ease',
      'box-shadow:0 2px 12px rgba(0,0,0,0.3)',
    ].join(';');
    btn.addEventListener('mouseenter', function () {
      btn.style.background = 'rgba(124,138,255,0.2)';
      btn.style.borderColor = 'rgba(124,138,255,0.6)';
    });
    btn.addEventListener('mouseleave', function () {
      btn.style.background = 'rgba(10,10,20,0.85)';
      btn.style.borderColor = 'rgba(124,138,255,0.3)';
    });
    btn.addEventListener('click', function () {
      tauriInvoke('show_whatsapp_organ', { visible: false }).catch(function () {});
    });
    document.body.appendChild(btn);
    console.log('[lexicon/wa] Back button injected');
  }

  function ensureBackButton() {
    if (document.body) injectBackButton();
    setInterval(function () {
      if (document.body && !document.getElementById('lexicon-back-btn')) {
        injectBackButton();
      }
    }, 3000);
  }

  // ══════════════════════════════════════════════════════════════
  //  STRATEGY 1: Scan the currently open chat (message-in class)
  //  Only works when a chat is open in the main panel (#main).
  // ══════════════════════════════════════════════════════════════

  function getCurrentChatName() {
    // The open chat header has a span with title="ContactName"
    var headerSpans = document.querySelectorAll('#main header span[title]');
    for (var i = 0; i < headerSpans.length; i++) {
      var t = headerSpans[i].getAttribute('title');
      if (t && t.length > 0 && t.length < 120) return t;
    }
    var fallback = document.querySelector('header span[title]');
    if (fallback) {
      var ft = fallback.getAttribute('title') || fallback.textContent.trim();
      if (ft && ft.length > 0 && ft.length < 120) return ft;
    }
    return null;
  }

  function extractTextFromMessage(msgEl) {
    // The actual text is in nested <span> tags.
    var selectable = msgEl.querySelector('span.selectable-text');
    if (selectable) {
      var inner = selectable.querySelector('span');
      if (inner) return inner.textContent.trim();
      return selectable.textContent.trim();
    }
    // Fallback: any span with dir attribute
    var dirSpan = msgEl.querySelector('span[dir]');
    if (dirSpan) return dirSpan.textContent.trim();
    return null;
  }

  function scanOpenChat() {
    var chatName = getCurrentChatName();
    if (!chatName) return;

    // message-in = incoming messages from friend/group member
    var incoming = document.querySelectorAll('div.message-in');
    var found = 0;

    for (var i = 0; i < incoming.length; i++) {
      var msgEl = incoming[i];

      // Build a unique ID
      var dataId = msgEl.getAttribute('data-id');
      if (!dataId) {
        var parent = msgEl.closest('[data-id]');
        if (parent) dataId = parent.getAttribute('data-id');
      }
      if (!dataId) {
        var rawText = extractTextFromMessage(msgEl);
        if (!rawText) continue;
        dataId = 'pos_' + chatName + '_' + i + '_' + rawText.substring(0, 30);
      }

      if (seenMessages.has(dataId)) continue;

      var text = extractTextFromMessage(msgEl);
      if (!text) continue;

      // Extract sender for group chats
      var sender = null;
      var prePlainEl = msgEl.querySelector('[data-pre-plain-text]');
      if (prePlainEl) {
        var pp = prePlainEl.getAttribute('data-pre-plain-text') || '';
        var m = pp.match(/\]\s*(.+?):\s*$/);
        if (m) sender = m[1].trim();
      }

      seenMessages.add(dataId);
      found++;

      relayMessage({
        contact: sender || chatName,
        chat: chatName,
        text: text,
        timestamp: new Date().toISOString(),
        message_id: dataId,
      });
    }

    if (found > 0) {
      console.log('[lexicon/wa] Open chat "' + chatName + '": ' + found + ' new');
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  STRATEGY 2: Scan sidebar contacts for preview text.
  //  Works without opening a chat. WhatsApp shows preview text
  //  for each contact/group in the sidebar.
  //
  //  Key: sidebar items have class _ak8j, names have title="...",
  //  preview text is in <span> tags.
  // ══════════════════════════════════════════════════════════════

  function scanSidebar() {
    // Try the known obfuscated class first, then structural fallbacks
    var items = document.querySelectorAll('._ak8j');
    if (!items.length) {
      items = document.querySelectorAll(
        '#pane-side [role="listitem"], ' +
        '#pane-side [role="row"], ' +
        '[data-testid="cell-frame-container"]'
      );
    }
    if (!items.length) {
      var pane = document.getElementById('pane-side');
      if (pane) items = pane.querySelectorAll('[tabindex="-1"]');
    }

    var found = 0;
    for (var i = 0; i < items.length; i++) {
      var item = items[i];

      // ── Find contact/group name via title attribute ──
      var contact = null;
      var titleEls = item.querySelectorAll('[title]');
      for (var t = 0; t < titleEls.length; t++) {
        var titleVal = titleEls[t].getAttribute('title');
        // Skip timestamps like "10:23" or "yesterday"
        var isTimestamp = /^\d{1,2}:\d{2}/.test(titleVal);
        var isYesterday = /^yesterday$/i.test(titleVal);
        if (titleVal && titleVal.length > 1 && !isTimestamp && !isYesterday) {
          contact = titleVal;
          break;
        }
      }
      if (!contact) continue;

      // ── Look for unread badge ──
      var unreadCount = 0;
      var allSpans = item.querySelectorAll('span');
      for (var s = 0; s < allSpans.length; s++) {
        var spanText = allSpans[s].textContent.trim();
        if (/^\d{1,3}$/.test(spanText) && allSpans[s].offsetWidth < 40) {
          var num = parseInt(spanText, 10);
          if (num > 0 && num < 1000) {
            unreadCount = num;
            break;
          }
        }
      }

      // ── Extract preview text ──
      // The last meaningful <span> with text is usually the preview.
      var preview = null;
      var spans = item.querySelectorAll('span');
      for (var p = spans.length - 1; p >= 0; p--) {
        var pText = spans[p].textContent.trim();
        if (!pText || pText.length <= 2) continue;
        if (pText === contact) continue;
        // Skip timestamps, dates, counts
        if (/^\d{1,2}:\d{2}(\s*(AM|PM))?$/i.test(pText)) continue;
        if (/^\d{1,3}$/.test(pText)) continue;
        if (/^yesterday$/i.test(pText)) continue;
        if (/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(pText)) continue;
        if (pText.length < 500) {
          preview = pText;
          break;
        }
      }

      if (!preview) continue;

      // Dedup: contact + preview text
      var sidebarKey = 'sb_' + contact + '_' + preview.substring(0, 50);
      if (seenSidebarItems.has(sidebarKey)) continue;
      seenSidebarItems.add(sidebarKey);
      found++;

      relayMessage({
        contact: contact,
        chat: contact,
        text: preview,
        timestamp: new Date().toISOString(),
        message_id: sidebarKey,
        unread_count: unreadCount,
      });
    }

    if (found > 0) {
      console.log('[lexicon/wa] Sidebar: ' + found + ' new items');
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  Observer + periodic scanning
  // ══════════════════════════════════════════════════════════════

  var _scanDebounce = null;

  function startObserver() {
    var appEl = document.getElementById('app') || document.body;

    var observer = new MutationObserver(function (mutations) {
      var hasNew = false;
      for (var i = 0; i < mutations.length; i++) {
        if (mutations[i].addedNodes.length > 0) { hasNew = true; break; }
      }
      if (hasNew) {
        clearTimeout(_scanDebounce);
        _scanDebounce = setTimeout(function () {
          scanOpenChat();
        }, 200);
      }
    });

    observer.observe(appEl, { childList: true, subtree: true });
    observerStarted = true;

    console.log('[lexicon/wa] DOM observer started');
    relayStatus('connected');

    // Periodic scans
    setInterval(scanSidebar, 4000);
    setInterval(scanOpenChat, 2000);

    // Initial scans
    scanOpenChat();
    scanSidebar();
  }

  // ── Wait for WhatsApp to load ──

  function waitForWhatsApp() {
    if (observerStarted) return;
    retryCount++;

    if (retryCount > MAX_RETRIES) {
      console.warn('[lexicon/wa] Gave up waiting');
      relayStatus('timeout');
      return;
    }

    var loaded = document.getElementById('pane-side') ||
                 document.querySelector('_ak8j') ||
                 document.querySelector('[data-testid="chat-list"]') ||
                 document.querySelector('message-in') ||
                 document.querySelector('message-out');

    if (loaded) {
      console.log('[lexicon/wa] WhatsApp loaded');
      startObserver();
    } else {
      var qr = document.querySelector('canvas[aria-label]') ||
               document.querySelector('[data-testid="qrcode"]');
      if (qr && retryCount % 10 === 0) {
        console.log('[lexicon/wa] QR visible — waiting for scan');
        relayStatus('waiting_for_qr');
      }
      setTimeout(waitForWhatsApp, 1000);
    }
  }

  // ── Boot ──
  console.log('[lexicon/wa] Monitor injected');
  console.log('[lexicon/wa] __TAURI_INTERNALS__:', !!window.__TAURI_INTERNALS__);

  ensureBackButton();

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(waitForWhatsApp, 500);
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      ensureBackButton();
      setTimeout(waitForWhatsApp, 500);
    });
  }
})();
