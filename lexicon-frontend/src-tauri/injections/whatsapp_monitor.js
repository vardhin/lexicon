/**
 * WhatsApp DOM Monitor — injected into the WhatsApp organ WebView.
 *
 * ARCHITECTURE: Batched message relay
 *   - DOM scans collect messages into a buffer
 *   - Buffer is flushed as a single batch every 500ms
 *   - Batch goes via Tauri IPC -> Rust -> single HTTP POST to Brain
 *   - Brain stores all at once, broadcasts once
 *   - This prevents 50+ rapid-fire events when opening a chat
 *
 * DOM selectors (2026):
 *   - div.message-in / div.message-out — chat messages
 *   - ._ak8j — sidebar contact items
 *   - [title] — contact/group names
 *   - <span> — text content
 */

(function () {
  'use strict';

  var seenMessages = new Set();
  var seenSidebar = new Set();
  var observerStarted = false;
  var retryCount = 0;
  var MAX_RETRIES = 180;

  // ── Batching ──
  // Messages are queued here and flushed periodically.
  var messageQueue = [];
  var flushTimer = null;
  var FLUSH_INTERVAL = 500; // ms

  // ── Tauri IPC bridge ──

  function tauriInvoke(cmd, args) {
    try {
      if (window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke) {
        return window.__TAURI_INTERNALS__.invoke(cmd, args || {});
      }
    } catch (e) {}
    return Promise.reject('no tauri');
  }

  function queueMessage(data) {
    messageQueue.push(data);
    // Schedule a flush if one isn't already pending
    if (!flushTimer) {
      flushTimer = setTimeout(flushQueue, FLUSH_INTERVAL);
    }
  }

  function flushQueue() {
    flushTimer = null;
    if (messageQueue.length === 0) return;

    var batch = messageQueue.slice();
    messageQueue = [];

    console.log('[lexicon/wa] Flushing batch:', batch.length, 'messages');

    var payload = JSON.stringify(batch);
    // Direct HTTP to Brain — child webviews from external URLs don't have __TAURI_INTERNALS__
    fetch('http://127.0.0.1:8000/whatsapp/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
    }).then(function () {
      console.log('[lexicon/wa] batch relayed via HTTP');
    }).catch(function (err) {
      console.warn('[lexicon/wa] batch relay failed:', err);
    });
  }

  function relayStatus(status) {
    fetch('http://127.0.0.1:8000/whatsapp/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: status, timestamp: new Date().toISOString() }),
    }).catch(function () {});
  }

  // ── Keyboard: Escape -> hide WhatsApp overlay, go back to Lexicon canvas ──
  // First Escape hides the WA organ overlay (back to Lexicon canvas).
  // If user wants to hide the whole Lexicon window, they press Escape again
  // in the main Svelte UI (which handles toggle_window).
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      // Hide just the WA overlay, keep Lexicon canvas visible
      fetch('http://127.0.0.1:8000/whatsapp/hide', { method: 'POST' }).catch(function () {});
    }
  }, true);

  // ── Floating back button — goes back to Lexicon canvas (hides WA overlay only) ──
  function injectBackButton() {
    if (document.getElementById('lexicon-back-btn')) return;
    var btn = document.createElement('div');
    btn.id = 'lexicon-back-btn';
    btn.innerHTML = '\u27F5 Lexicon';
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
    btn.onmouseenter = function () { btn.style.background = 'rgba(124,138,255,0.2)'; };
    btn.onmouseleave = function () { btn.style.background = 'rgba(10,10,20,0.85)'; };
    btn.onclick = function () {
      // Hide just the WA overlay, keep Lexicon canvas visible
      fetch('http://127.0.0.1:8000/whatsapp/hide', { method: 'POST' }).catch(function () {});
    };
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
    var fb = document.querySelector('header span[title]');
    if (fb) {
      var ft = fb.getAttribute('title') || fb.textContent.trim();
      if (ft && ft.length > 0 && ft.length < 120) return ft;
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

      // Contact name: first [title] that isn't a timestamp
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

      // Unread count
      var unread = 0;
      var spans = item.querySelectorAll('span');
      for (var s = 0; s < spans.length; s++) {
        var st = spans[s].textContent.trim();
        if (/^\d{1,3}$/.test(st) && spans[s].offsetWidth < 40) {
          var n = parseInt(st, 10);
          if (n > 0 && n < 1000) { unread = n; break; }
        }
      }

      // Preview: last meaningful span
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

    // Start debug snapshot + query polling
    setInterval(sendDebugSnapshot, 10000);
    setInterval(pollSelectorQuery, 1000);

    scanOpenChat();
    scanSidebar();
  }

  // ══════════════════════════════════════════════════════════════
  //  DEBUG: DOM snapshot + CSS selector query handler
  // ══════════════════════════════════════════════════════════════

  function snapshotNode(el, depth) {
    if (!el || depth > 6) return null;
    if (el.nodeType === 3) {
      var txt = el.textContent.trim();
      return txt ? { tag: '#text', text: txt.substring(0, 100) } : null;
    }
    if (el.nodeType !== 1) return null;

    var node = {
      tag: el.tagName.toLowerCase(),
    };

    if (el.id) node.id = el.id;
    if (el.className && typeof el.className === 'string') {
      var cls = el.className.trim().split(/\s+/).filter(function (c) { return c.length > 0; });
      if (cls.length > 0) node.classes = cls.slice(0, 8);
    }

    var title = el.getAttribute('title');
    if (title) node.title = title.substring(0, 80);

    var role = el.getAttribute('role');
    if (role) node.role = role;

    var testid = el.getAttribute('data-testid');
    if (testid) node.dataTestid = testid;

    var dataId = el.getAttribute('data-id');
    if (dataId) node.dataId = true;

    var prePlain = el.getAttribute('data-pre-plain-text');
    if (prePlain) node.dataPrePlain = prePlain.substring(0, 80);

    // Direct text content (not from children)
    var directText = '';
    for (var i = 0; i < el.childNodes.length; i++) {
      if (el.childNodes[i].nodeType === 3) {
        var t = el.childNodes[i].textContent.trim();
        if (t) directText += t + ' ';
      }
    }
    if (directText.trim()) node.text = directText.trim().substring(0, 100);

    // Children (limit to avoid huge payloads)
    if (depth < 6) {
      var children = [];
      var maxChildren = depth < 2 ? 20 : (depth < 4 ? 10 : 5);
      for (var c = 0; c < el.children.length && children.length < maxChildren; c++) {
        var child = snapshotNode(el.children[c], depth + 1);
        if (child) children.push(child);
      }
      if (children.length > 0) node.children = children;
      if (el.children.length > maxChildren) {
        node.truncated = el.children.length;
      }
    }

    return node;
  }

  function buildScanReport() {
    var report = {
      currentChat: getCurrentChatName(),
      sidebarCount: 0,
      sidebarItems: [],
      messageCount: 0,
      messages: [],
      selectorHits: {},
    };

    // Count selector hits
    var selectors = [
      '._ak8j',
      '#pane-side',
      '#pane-side [role="listitem"]',
      '#pane-side [role="row"]',
      '[data-testid="cell-frame-container"]',
      'div.message-in',
      'div.message-out',
      '#main header span[title]',
      'span.selectable-text',
      '[data-pre-plain-text]',
      '[data-id]',
      'img[src*="pps"]',
    ];
    for (var s = 0; s < selectors.length; s++) {
      try {
        report.selectorHits[selectors[s]] = document.querySelectorAll(selectors[s]).length;
      } catch (_) {
        report.selectorHits[selectors[s]] = -1;
      }
    }

    // Sidebar items
    var items = document.querySelectorAll('._ak8j');
    if (!items.length) items = document.querySelectorAll('#pane-side [role="listitem"], #pane-side [role="row"]');
    report.sidebarCount = items.length;
    for (var i = 0; i < Math.min(items.length, 15); i++) {
      var item = items[i];
      var contact = null;
      var titles = item.querySelectorAll('[title]');
      for (var ti = 0; ti < titles.length; ti++) {
        var tv = titles[ti].getAttribute('title');
        if (tv && tv.length > 1 && !/^\d{1,2}:\d{2}/.test(tv) && !/^yesterday$/i.test(tv)) {
          contact = tv;
          break;
        }
      }
      var preview = null;
      var spans = item.querySelectorAll('span');
      for (var si = spans.length - 1; si >= 0; si--) {
        var pt = spans[si].textContent.trim();
        if (pt && pt.length > 2 && pt !== contact && pt.length < 200 &&
            !/^\d{1,2}:\d{2}/.test(pt) && !/^\d{1,3}$/.test(pt) && !/^yesterday$/i.test(pt)) {
          preview = pt;
          break;
        }
      }
      var unread = 0;
      for (var ui = 0; ui < spans.length; ui++) {
        var ut = spans[ui].textContent.trim();
        if (/^\d{1,3}$/.test(ut) && spans[ui].offsetWidth < 40) {
          var n = parseInt(ut, 10);
          if (n > 0 && n < 1000) { unread = n; break; }
        }
      }
      report.sidebarItems.push({ contact: contact, preview: preview, unread: unread });
    }

    // Messages in open chat
    var msgs = document.querySelectorAll('div.message-in');
    report.messageCount = msgs.length;
    for (var mi = Math.max(0, msgs.length - 10); mi < msgs.length; mi++) {
      var mel = msgs[mi];
      var mtext = null;
      var selText = mel.querySelector('span.selectable-text');
      if (selText) {
        var inner = selText.querySelector('span');
        mtext = inner ? inner.textContent.trim() : selText.textContent.trim();
      }
      var sender = null;
      var pp = mel.querySelector('[data-pre-plain-text]');
      if (pp) {
        var m = (pp.getAttribute('data-pre-plain-text') || '').match(/\]\s*(.+?):\s*$/);
        if (m) sender = m[1].trim();
      }
      report.messages.push({ sender: sender, text: mtext ? mtext.substring(0, 80) : null });
    }

    return report;
  }

  function sendDebugSnapshot() {
    try {
      var app = document.getElementById('app') || document.body;
      var snapshot = snapshotNode(app, 0);
      var scanReport = buildScanReport();
      fetch('http://127.0.0.1:8000/whatsapp/debug', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot: snapshot, scan_report: scanReport }),
      }).catch(function () {});
    } catch (err) {
      console.warn('[lexicon/wa] debug snapshot failed:', err);
    }
  }

  function pollSelectorQuery() {
    fetch('http://127.0.0.1:8000/whatsapp/debug/pending')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.selector) return;
        var selector = data.selector;
        console.log('[lexicon/wa] debug query:', selector);
        try {
          var els = document.querySelectorAll(selector);
          var results = [];
          for (var i = 0; i < Math.min(els.length, 20); i++) {
            var el = els[i];
            var res = {
              tag: el.tagName.toLowerCase(),
            };
            if (el.id) res.id = el.id;
            if (el.className && typeof el.className === 'string') {
              var cls = el.className.trim().split(/\s+/).filter(function (c) { return c.length > 0; });
              if (cls.length > 0) res.classes = cls.slice(0, 6);
            }
            var title = el.getAttribute('title');
            if (title) res.title = title.substring(0, 80);
            var role = el.getAttribute('role');
            if (role) res.role = role;
            var testid = el.getAttribute('data-testid');
            if (testid) res.dataTestid = testid;

            // Text content
            var text = el.textContent ? el.textContent.trim().substring(0, 100) : null;
            if (text) res.text = text;

            // Outer HTML snippet
            try {
              res.outerHtml = el.outerHTML.substring(0, 200);
            } catch (_) {}

            results.push(res);
          }
          fetch('http://127.0.0.1:8000/whatsapp/debug/query/result', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ count: els.length, results: results }),
          }).catch(function () {});
        } catch (err) {
          fetch('http://127.0.0.1:8000/whatsapp/debug/query/result', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ count: -1, results: [], error: err.message }),
          }).catch(function () {});
        }
      })
      .catch(function () {});
  }

  // ── Wait for WhatsApp to load ──

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
  console.log('[lexicon/wa] Monitor injected (batched)');
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
