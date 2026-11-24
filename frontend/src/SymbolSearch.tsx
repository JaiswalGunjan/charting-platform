import { useEffect, useRef, useState } from "react";
import { api, type SymbolInfo } from "./api";

export default function SymbolSearch({ value, onPick }: { value: string; onPick: (s: string) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SymbolInfo[]>([]);
  const [hi, setHi] = useState(0);
  const [exchange, setExchange] = useState<string>("");
  const [exchanges, setExchanges] = useState<{ exchange: string; symbols: number }[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open && !exchanges.length) api.exchanges().then(setExchanges, () => {});
  }, [open, exchanges.length]);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(
      () => api.searchSymbols(q.trim(), exchange || undefined).then((r) => (setItems(r), setHi(0)), () => setItems([])),
      120,
    );
    return () => clearTimeout(t);
  }, [q, open, exchange]);

  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (s: SymbolInfo) => {
    onPick(s.symbol);
    setOpen(false);
    setQ("");
    input.current?.blur();
  };

  return (
    <div className="search" ref={ref}>
      <input
        ref={input}
        value={open ? q : value}
        placeholder="Search symbol or company"
        onFocus={() => setOpen(true)}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setHi((h) => Math.min(h + 1, items.length - 1));
          else if (e.key === "ArrowUp") setHi((h) => Math.max(h - 1, 0));
          else if (e.key === "Enter" && items[hi]) pick(items[hi]);
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && (
        <div className="dropdown">
          <div className="search-ex">
            {[{ exchange: "", symbols: exchanges.reduce((a, x) => a + x.symbols, 0) }, ...exchanges].map((x) => (
              <button key={x.exchange} className={exchange === x.exchange ? "active" : ""}
                onMouseDown={(e) => { e.preventDefault(); setExchange(x.exchange); }}
                title={`${x.symbols.toLocaleString()} symbols`}>
                {x.exchange || "All"} <span className="muted">{x.symbols.toLocaleString()}</span>
              </button>
            ))}
          </div>
          <ul>
            {items.map((s, i) => (
              <li key={s.symbol} className={i === hi ? "hi" : ""} onMouseDown={() => pick(s)} onMouseEnter={() => setHi(i)}>
                <b>{s.ticker}</b>
                <span className="muted" title={s.name}>{s.name}</span>
                {s.type !== "EQ" && <span className="tag">{s.type}</span>}
                <span className="tag">{s.exchange}</span>
              </li>
            ))}
            {!items.length && <li className="muted">No matches</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
