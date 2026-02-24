/**
 * Lexicon WebSocket client.
 * Connects to the FastAPI Brain, auto-reconnects.
 */

const WS_URL = 'ws://127.0.0.1:8000/ws';

export function createWS(onMessage, onStatus) {
  let ws = null;
  let closed = false;
  let retryMs = 2000;

  function connect() {
    if (closed) return;
    ws = new WebSocket(WS_URL);

    ws.onopen = function () {
      retryMs = 2000;
      onStatus(true);
    };

    ws.onmessage = function (e) {
      try {
        var data = JSON.parse(e.data);
        // skip handshake
        if (data.type !== 'connected') {
          onMessage(data);
        }
      } catch (_) {}
    };

    ws.onclose = function () {
      onStatus(false);
      if (!closed) setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 1.5, 30000);
    };

    ws.onerror = function () {};
  }

  connect();

  return {
    send: function (obj) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(obj));
      }
    },
    close: function () {
      closed = true;
      if (ws) ws.close();
    },
    isOpen: function () {
      return ws && ws.readyState === WebSocket.OPEN;
    },
  };
}
