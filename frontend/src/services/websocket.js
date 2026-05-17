const WS_BASE = 'ws://localhost:8000';

export class ResearchWebSocket {
  constructor(sessionId, handlers = {}) {
    this.sessionId = sessionId;
    this.handlers = handlers;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnects = 3;
  }

  connect() {
    this.ws = new WebSocket(`${WS_BASE}/ws/${this.sessionId}`);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.handlers.onOpen?.();
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handlers.onEvent?.(data);

        // Route to specific handlers
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
        }
      } catch (e) {
        console.error('WebSocket parse error:', e);
      }
    };

    this.ws.onclose = () => {
      this.handlers.onClose?.();
      if (this.reconnectAttempts < this.maxReconnects) {
        this.reconnectAttempts++;
        setTimeout(() => this.connect(), 1000 * this.reconnectAttempts);
      }
    };

    this.ws.onerror = (err) => {
      console.error('WebSocket error:', err);
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
