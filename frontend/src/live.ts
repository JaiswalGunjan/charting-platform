import { signedOut } from "./auth";
// One shared WebSocket for the whole app: ref-counted subscriptions, auto-reconnect
// (re-subscribing everything), and a simple listener bus.
import type { LiveBar, Quote } from "./api";

export type ServerMsg =
  | { type: "subscribed"; symbol: string; tf: string; bar: LiveBar | null; quote: Quote }
  | { type: "bar"; symbol: string; tf: string; bar: LiveBar }
  | ({ type: "quote" } & Quote)
  | { type: "alert"; alert_id: number; symbol: string; message: string; price: number; ts: number }
  | { type: "error"; message: string }
  | { type: "unsubscribed" | "pong" };

type Listener = (m: ServerMsg) => void;
export type ConnState = "connecting" | "open" | "closed";

class LiveClient {
  private ws: WebSocket | null = null;
  private subs = new Map<string, number>(); // "SYM|tf" -> refcount
  private listeners = new Set<Listener>();
  private stateListeners = new Set<(s: ConnState) => void>();
  private retry = 0;
  state: ConnState = "closed";

  connect() {
    if (this.ws) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    this.ws = ws;
    this.setState("connecting");
    ws.onopen = () => {
      this.retry = 0;
      this.setState("open");
      for (const key of this.subs.keys()) this.sendSub("subscribe", key);
    };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data) as ServerMsg;
      this.listeners.forEach((l) => l(msg));
    };
    ws.onclose = (e) => {
      if (e.code === 4401) signedOut();               // the server refused the live connection: not signed in
      this.ws = null;
      this.setState("closed");
      const delay = Math.min(10_000, 500 * 2 ** this.retry++);
      setTimeout(() => this.connect(), delay);
    };
  }

  subscribe(symbol: string, tf: string): () => void {
    const key = `${symbol}|${tf}`;
    const n = this.subs.get(key) ?? 0;
    this.subs.set(key, n + 1);
    if (n === 0) this.sendSub("subscribe", key);
    return () => {
      const left = (this.subs.get(key) ?? 1) - 1;
      if (left > 0) return void this.subs.set(key, left);
      this.subs.delete(key);
      this.sendSub("unsubscribe", key);
    };
  }

  on(l: Listener): () => void {
    this.listeners.add(l);
    return () => void this.listeners.delete(l);
  }

  onState(l: (s: ConnState) => void): () => void {
    this.stateListeners.add(l);
    l(this.state);
    return () => void this.stateListeners.delete(l);
  }

  private setState(s: ConnState) {
    this.state = s;
    this.stateListeners.forEach((l) => l(s));
  }

  private sendSub(op: "subscribe" | "unsubscribe", key: string) {
    if (this.ws?.readyState !== WebSocket.OPEN) return; // re-sent on open
    const [symbol, tf] = key.split("|");
    this.ws.send(JSON.stringify({ op, symbol, tf }));
  }
}

export const live = new LiveClient();
