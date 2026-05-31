import { clearAuthTokens, getApiBase, getToken } from './api';

function getWebSocketBase() {
  const apiBase = getApiBase();
  if (apiBase.startsWith('https://')) return apiBase.replace('https://', 'wss://');
  if (apiBase.startsWith('http://')) return apiBase.replace('http://', 'ws://');
  return apiBase;
}

function redirectToLogin() {
  clearAuthTokens();
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

export class ResearchWebSocket {
  constructor(sessionId, handlers = {}) {
    this.sessionId = sessionId;
    this.handlers = handlers;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnects = 3;
  }

  connect() {
    const token = getToken();
    if (!token) {
      this.handlers.onError?.({ message: 'Authentication required' });
      redirectToLogin();
      return;
    }

    const url = `${getWebSocketBase()}/ws/${this.sessionId}?token=${encodeURIComponent(token)}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.handlers.onOpen?.();
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handlers.onEvent?.(data);

        switch (data.type) {
          case 'thinking': this.handlers.onThinking?.(data.data); break;
          case 'tool_call': this.handlers.onToolCall?.(data.data); break;
          case 'tool_result': this.handlers.onToolResult?.(data.data); break;
          case 'message': this.handlers.onMessage?.(data.data); break;
          case 'todo_update': this.handlers.onTodoUpdate?.(data.data); break;
          case 'metrics': this.handlers.onMetrics?.(data.data); break;
          case 'status': this.handlers.onStatus?.(data.data); break;
          case 'complete': this.handlers.onComplete?.(data.data); break;
          case 'error': this.handlers.onError?.(data.data); break;
          default: break;
        }
      } catch (error) {
        console.error('WebSocket parse error:', error);
      }
    };

    this.ws.onclose = (event) => {
      this.handlers.onClose?.(event);
      if ([4401, 4403, 4408, 1008].includes(event.code)) {
        this.handlers.onError?.({ message: 'Session expired or unauthorized' });
        redirectToLogin();
        return;
      }
      if (this.reconnectAttempts < this.maxReconnects) {
        this.reconnectAttempts += 1;
        setTimeout(() => this.connect(), 1000 * this.reconnectAttempts);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      this.handlers.onError?.({ message: 'Connection error' });
    };
  }

  send(data) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  }

  close() {
    this.maxReconnects = 0;
    this.ws?.close();
  }
}
