/* Small, same-origin Engine.IO v4 / Socket.IO v5 JSON client.
 * Only the default namespace, text events and acknowledgements are needed here.
 * Starts with WebSocket; falls back to HTTP long-polling. No CDN or build tools.
 */
class TailSocket {
  constructor() {
    this.handlers = new Map();
    this.acks = new Map();
    this.sequence = 0;
    this.generation = 0;
    this.attempt = 0;
    this.connected = false;
    this.stopped = true;
  }
  on(event, handler) {
    if (!this.handlers.has(event)) this.handlers.set(event, []);
    this.handlers.get(event).push(handler);
    return this;
  }
  notify(event, data) {
    for (const handler of this.handlers.get(event) || []) handler(data);
  }
  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.attempt = 0;
    this.open();
  }
  stop() {
    this.stopped = true;
    clearTimeout(this.retry);
    this.cleanup();
    this.notify('disconnected');
  }
  cleanup() {
    ++this.generation;
    clearTimeout(this.watchdog);
    this.connected = false;
    if (this.ws) { this.ws.onclose = null; this.ws.onerror = null; this.ws.close(); }
    this.ws = null;
    this.controller?.abort();
    for (const pending of this.acks.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error('Connection interrupted. Your draft is still here.'));
    }
    this.acks.clear();
  }
  lost() {
    if (this.stopped) return;
    this.cleanup();
    this.notify('disconnected');
    clearTimeout(this.retry);
    this.retry = setTimeout(() => this.open(), Math.min(1000 * 2 ** this.attempt++, 10000));
  }
  async open(polling = false) {
    if (this.stopped) return;
    this.cleanup();
    const generation = this.generation;
    this.controller = new AbortController();
    this.sid = null;
    this.polling = polling;
    this.postChain = Promise.resolve();
    this.timeout = 30000;
    this.arm(generation);
    if (!polling && typeof WebSocket !== 'undefined') {
      const url = new URL('/socket.io/?EIO=4&transport=websocket', location.href);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      let opened = false;
      this.ws = new WebSocket(url);
      this.ws.onmessage = ({data}) => {
        if (generation !== this.generation) return;
        opened = true;
        this.receive(data, generation);
      };
      const fail = () => {
        if (generation !== this.generation || this.stopped) return;
        if (!opened) this.open(true);
        else this.lost();
      };
      this.ws.onerror = fail;
      this.ws.onclose = fail;
      return;
    }
    this.polling = true;
    try {
      const response = await fetch(this.url(), {signal:this.controller.signal, cache:'no-store'});
      if (!response.ok) throw new Error('Handshake failed');
      this.receive(await response.text(), generation);
      while (generation === this.generation && !this.stopped) {
        const result = await fetch(this.url(), {signal:this.controller.signal, cache:'no-store'});
        if (!result.ok) throw new Error('Polling failed');
        this.receive(await result.text(), generation);
      }
    } catch (error) {
      if (generation === this.generation && !this.stopped) this.lost();
    }
  }
  url() {
    return '/socket.io/?EIO=4&transport=polling&t=' + Date.now() +
      (this.sid ? '&sid=' + encodeURIComponent(this.sid) : '');
  }
  arm(generation) {
    clearTimeout(this.watchdog);
    this.watchdog = setTimeout(() => {
      if (generation === this.generation) {
        if (!this.connected && !this.polling) this.open(true);
        else this.lost();
      }
    }, this.timeout);
  }
  receive(payload, generation) {
    try {
      for (const packet of payload.split('\x1e')) {
        if (generation !== this.generation) return;
        this.arm(generation);
        if (packet[0] === '0') {
          const hello = JSON.parse(packet.slice(1));
          this.sid = hello.sid;
          this.timeout = hello.pingInterval + hello.pingTimeout + 5000;
          this.arm(generation);
          this.write('40');
        } else if (packet[0] === '2') {
          this.write('3' + packet.slice(1));
        } else if (packet.startsWith('40')) {
          this.connected = true;
          this.attempt = 0;
          this.notify('connected', this.polling ? 'polling' : 'websocket');
        } else if (packet.startsWith('42')) {
          const event = JSON.parse(packet.slice(2));
          this.notify(event[0], event[1]);
        } else if (packet.startsWith('43')) {
          const match = /^43(\d+)(\[.*\])$/s.exec(packet);
          if (!match) continue;
          const pending = this.acks.get(Number(match[1]));
          if (pending) {
            this.acks.delete(Number(match[1]));
            clearTimeout(pending.timer);
            pending.resolve(JSON.parse(match[2])[0]);
          }
        } else if (packet.startsWith('44')) {
          this.stop();
          this.notify('rejected', 'Your session expired. Please join again.');
        } else if (packet === '1' || packet === '41') {
          this.lost();
        }
      }
    } catch (error) { this.lost(); }
  }
  write(packet) {
    const generation = this.generation;
    if (!this.polling) {
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(packet);
      else this.lost();
      return;
    }
    const url = this.url();
    const signal = this.controller.signal;
    this.postChain = this.postChain.then(async () => {
      if (generation !== this.generation) return;
      const response = await fetch(url, {method:'POST', body:packet, signal,
        headers:{'Content-Type':'text/plain;charset=UTF-8'}});
      if (!response.ok) throw new Error('Send failed');
    }).catch(() => { if (generation === this.generation) this.lost(); });
  }
  emit(event, data) {
    if (this.connected) this.write('42' + JSON.stringify([event, data]));
  }
  request(event, data) {
    if (!this.connected) return Promise.reject(new Error('Wait for the connection to return.'));
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.acks.delete(id);
        reject(new Error('No confirmation received. Retry to check delivery safely.'));
      }, 8000);
      this.acks.set(id, {resolve, reject, timer});
      this.write('42' + id + JSON.stringify([event, data]));
    });
  }
}
