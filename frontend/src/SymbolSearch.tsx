import { useEffect, useRef, useState } from "react";
import { api, type SymbolInfo } from "./api";

export default function SymbolSearch({ value, onPick }: { value: string; onPick: (s: string) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SymbolInfo[]>([]);
  const [hi, setHi] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => api.searchSymbols(q.trim()).then((r) => (setItems(r), setHi(0)), () => setItems([])), 120);
    return () => clearTimeout(t);
  }, [q, open]);

  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (s: SymbolInfo) => {
    onPick(s.symbol);
    setOpen(false);
    setQ("");
  };

  return (
    <div className="search" ref={ref}>
      <input
        value={open ? q : value}
        placeholder="Search symbol"
        onFocus={() => setOpen(true)}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setHi((h) => Math.min(h + 1, items.length - 1));
          else if (e.key === "ArrowUp") setHi((h) => Math.max(h - 1, 0));
          else if (e.key === "Enter" && items[hi]) pick(items[hi]);
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && items.length > 0 && (
        <ul className="dropdown">
          {items.map((s, i) => (
            <li key={s.symbol} className={i === hi ? "hi" : ""} onMouseDown={() => pick(s)} onMouseEnter={() => setHi(i)}>
              <b>{s.ticker}</b>
              <span className="muted">{s.name}</span>
              <span className="tag">{s.exchange}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
