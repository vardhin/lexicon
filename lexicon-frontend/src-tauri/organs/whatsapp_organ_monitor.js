/**
 * WhatsApp Organ Monitor — injected into the standalone WebKitGTK browser.
 *
 * Unlike the Tauri version, this one:
 *   - Uses fetch() directly to POST to Brain (no CSP issues — our own browser)
 *   - Uses window.webkit.messageHandlers.lexicon for back-to-Lexicon
 *   - Batches messages (500ms flush interval)
 *
 * DOM selectors (2026):
 *   - div.message-in / div.message-out — chat messages
 *   - ._ak8j — sidebar contact items
 *   - [title] — contact/group names
 *   - span — text content
 */

(function () {
  'use strict';

  var BRAIN = 'http://127.0.0.1:8000';
  var seenMessages = new Set();
  var seenSidebar = new Set();
  var observerStarted = false;
  var retryCount = 0;
  var MAX_RETRIES = 180;

  // ── Batching ──
  var messageQueue = [];
  var flushTimer = null;
  var FLUSH_INTERVAL = 500;

  function queueMessage(data) {
    messageQueue.push(data);
    if (!flushTimer) {
      flushTimer = setTimeout(flushQueue, FLUSH_INTERVAL);
    }
  }

  function flushQueue() {
    flushTimer = null;
    if (messageQueue.length === 0) return;
    var batch = messageQueue.slice();
    messageQueue = [];
    console.log('[lexicon/wa] Flushing', batch.length, 'messages');
    fetch(BRAIN + '/whatsapp/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(batch),
    }).catch(function (e) {
      console.warn('[lexicon/wa] Batch POST failed:', e);
    });
  }

  function relayStatus(status) {
    fetch(BRAIN + '/whatsapp/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: status, timestamp: new Date().toISOString() }),
    }).catch(function () {});
    // Also tell the Python host
    try {
      window.webkit.messageHandlers.lexicon.postMessage(
        JSON.stringify({ action: 'status', status: status })
      );
    } catch (_) {}
  }

  function backToLexicon() {
    try {
      window.webkit.messageHandlers.lexicon.postMessage(
        JSON.stringify({ action: 'back_to_lexicon' })
      );
    } catch (_) {}
  }

  // ── Keyboard: Escape -> back to Lexicon ──
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      backToLexicon();
    }
  }, true);

  // ── Floating back button ──
  function injectBackButton() {
    if (document.getElementById('lexicon-back-btn')) return;
    var btn = document.createElement('div');
    btn.id = 'lexicon-back-btn';
    btn.textContent = '\u27F5 Lexicon';
    btn.style.cssText = [
      'position:fixed', 'top:12px', 'right:16px', 'z-index:999999',
      'background:rgba(10,10,20,0.85)', 'color:rgba(124,138,255,0.95)',
      'font-family:monospace', 'font-size:12px', 'font-weight:700',
      'padding:6px 14px', 'border-radius:8px',
      'border:1px solid rgba(124,138,255,0.3)',
      'cursor:pointer', 'user-select:none',
      'backdrop-filter:blur(8px)',
      'box-shadow:0 2px 12px rgba(0,0,0,0.3)',
    ].join(';');
    btn.onmouseenter = function () { btn.style.background = 'rgba(124,138,255,0.2)'; };
    btn.onmouseleave = function () { btn.style.background = 'rgba(10,10,20,0.85)'; };
    btn.onclick = backToLexicon;
    document.body.appendChild(btn);
  }

  function ensureBackButton() {
    if (document.body) injectBackButton();
    setInterval(function () {
      if (document.body && !document.getElementById('lexicon-back-btn')) injectBackButton();
    }, 3000);
  }

  // ══════════════════════════════════════════════════════════════
  //  SCAN: Open chat (div.message-in)
  // ══════════════════════════════════════════════════════════════

  function getCurrentChatName() {
    var spans = document.querySelectorAll('#main header span[title]');
    for (var i = 0; i < spans.length; i++) {
      var t = spans[i].getAttribute('title');
      if (t && t.length > 0 && t.length < 120) return t;
    }
    return null;
  }

  function extractText(el) {
    var sel = el.querySelector('span.selectable-text');
    if (sel) {
      var inner = sel.querySelector('span');
      return inner ? inner.textContent.trim() : sel.textContent.trim();
    }
    var ds = el.querySelector('span[dir]');
    return ds ? ds.textContent.trim() : null;
  }

  function scanOpenChat() {
    var chatName = getCurrentChatName();
    if (!chatName) return;

    var msgs = document.querySelectorAll('div.message-in');
    for (var i = 0; i < msgs.length; i++) {
      var el = msgs[i];
      var dataId = el.getAttribute('data-id');
      if (!dataId) {
        var p = el.closest('[data-id]');
        if (p) dataId = p.getAttribute('data-id');
      }
      if (!dataId) {
        var rt = extractText(el);
        if (!rt) continue;
        dataId = 'p_' + chatName + '_' + i + '_' + rt.substring(0, 20);
      }
      if (seenMessages.has(dataId)) continue;

      var text = extractText(el);
      if (!text) continue;

      var sender = null;
      var pp = el.querySelector('[data-pre-plain-text]');
      if (pp) {
        var m = (pp.getAttribute('data-pre-plain-text') || '').match(/\]\s*(.+?):\s*$/);
        if (m) sender = m[1].trim();
      }

      seenMessages.add(dataId);
      queueMessage({
        contact: sender || chatName,
        chat: chatName,
        text: text,
        timestamp: new Date().toISOString(),
        message_id: dataId,
      });
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  SCAN: Sidebar (._ak8j items)
  // ══════════════════════════════════════════════════════════════

  function scanSidebar() {
    var items = document.querySelectorAll('._ak8j');
    if (!items.length) {
      items = document.querySelectorAll(
        '#pane-side [role="listitem"], #pane-side [role="row"], [data-testid="cell-frame-container"]'
      );
    }
    if (!items.length) {
      var pane = document.getElementById('pane-side');
      if (pane) items = pane.querySelectorAll('[tabindex="-1"]');
    }

    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var contact = null;
      var titles = item.querySelectorAll('[title]');
      for (var t = 0; t < titles.length; t++) {
        var tv = titles[t].getAttribute('title');
        var isTstp = /^\d{1,2}:\d{2}/.test(tv);
        var isYday = /^yesterday$/i.test(tv);
        if (tv && tv.length > 1 && !isTstp && !isYday) {
          contact = tv;
          break;
        }
      }
      if (!contact) continue;

      var unread = 0;
      var spans = item.querySelectorAll('span');
      for (var s = 0; s < spans.length; s++) {
        var st = spans[s].textContent.trim();
        if (/^\d{1,3}$/.test(st) && spans[s].offsetWidth < 40) {
          var n = parseInt(st, 10);
          if (n > 0 && n < 1000) { unread = n; break; }
        }
      }

      var preview = null;
      for (var j = spans.length - 1; j >= 0; j--) {
        var pt = spans[j].textContent.trim();
        if (!pt || pt.length <= 2 || pt === contact) continue;
        if (/^\d{1,2}:\d{2}(\s*(AM|PM))?$/i.test(pt)) continue;
        if (/^\d{1,3}$/.test(pt)) continue;
        if (/^yesterday$/i.test(pt)) continue;
        if (/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(pt)) continue;
        if (pt.length < 500) { preview = pt; break; }
      }
      if (!preview) continue;

      var key = 'sb_' + contact + '_' + preview.substring(0, 50);
      if (seenSidebar.has(key)) continue;
      seenSidebar.add(key);

      queueMessage({
        contact: contact,
        chat: contact,
        text: preview,
        timestamp: new Date().toISOString(),
        message_id: key,
        unread_count: unread,
      });
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  Observer
  // ══════════════════════════════════════════════════════════════

  var _debounce = null;

  function startObserver() {
    var app = document.getElementById('app') || document.body;
    new MutationObserver(function (muts) {
      var hasNew = false;
      for (var i = 0; i < muts.length; i++) {
        if (muts[i].addedNodes.length > 0) { hasNew = true; break; }
      }
      if (hasNew) {
        clearTimeout(_debounce);
        _debounce = setTimeout(scanOpenChat, 300);
      }
    }).observe(app, { childList: true, subtree: true });

    observerStarted = true;
    console.log('[lexicon/wa] Observer started');
    relayStatus('connected');

    setInterval(scanSidebar, 5000);
    setInterval(scanOpenChat, 3000);
    scanOpenChat();
    scanSidebar();
  }

  function waitForWhatsApp() {
    if (observerStarted) return;
    retryCount++;
    if (retryCount > MAX_RETRIES) { relayStatus('timeout'); return; }

    var loaded = document.getElementById('pane-side') ||
                 document.querySelector('._ak8j') ||
                 document.querySelector('[data-testid="chat-list"]') ||
                 document.querySelector('div.message-in') ||
                 document.querySelector('div.message-out');

    if (loaded) {
      console.log('[lexicon/wa] WhatsApp loaded');
      startObserver();
    } else {
      var qr = document.querySelector('canvas[aria-label]') ||
               document.querySelector('[data-testid="qrcode"]');
      if (qr && retryCount % 10 === 0) relayStatus('waiting_for_qr');
      setTimeout(waitForWhatsApp, 1000);
    }
  }

  // ── Boot ──
  console.log('[lexicon/wa] Organ monitor injected (standalone)');
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
