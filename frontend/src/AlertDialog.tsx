import { useState, type FormEvent } from "react";
import { api, type AlertOp } from "./api";
import { fmt } from "./format";
import { Modal } from "./IndicatorDialogs";

const OPS: { op: AlertOp; label: string }[] = [
  { op: "crosses_above", label: "Crosses above" },
  { op: "crosses_below", label: "Crosses below" },
  { op: "above", label: "Is above" },
  { op: "below", label: "Is below" },
];

/** Create a price alert for the open symbol (top-bar Alert button, Alt+A). */
export default function AlertDialog(props: {
  symbol: string;
  lastPrice: number | null;
  onCreated: (toast: string) => void;
  onClose: () => void;
}) {
  const { symbol, lastPrice } = props;
  const [op, setOp] = useState<AlertOp>("crosses_above");
  const [price, setPrice] = useState(lastPrice != null ? lastPrice.toFixed(2) : "");
  const [once, setOnce] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const opLabel = OPS.find((o) => o.op === op)!.label.toLowerCase();
  const nudge = (pct: number) => {
    const base = Number(price) || lastPrice || 0;
    setPrice((base * (1 + pct / 100)).toFixed(2));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const p = Number(price);
    if (!Number.isFinite(p) || p <= 0) return setError("Enter a price above 0");
    setBusy(true);
    try {
      const msg = message.trim() || `${symbol} ${opLabel} ${fmt(p)}`;
      await api.createAlert(symbol, op, p, once, msg);
      props.onCreated(`🔔 Alert set: ${msg}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <Modal onClose={props.onClose} className="alert-dialog">
      <form onSubmit={submit} className="settings">
        <h3>Create alert on {symbol}</h3>
        <div className="form-grid">
          <label>
            <span>Condition</span>
            <select value={op} onChange={(e) => setOp(e.target.value as AlertOp)}>
              {OPS.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
            </select>
          </label>
          <label>
            <span>Price</span>
            <input type="number" step="any" min="0" value={price} autoFocus onChange={(e) => setPrice(e.target.value)} />
          </label>
          <div className="nudges">
            {[-5, -2, -1, 1, 2, 5].map((p) => (
              <button type="button" key={p} className="small" onClick={() => nudge(p)}>{p > 0 ? "+" : ""}{p}%</button>
            ))}
            {lastPrice != null && (
              <button type="button" className="small" onClick={() => setPrice(lastPrice.toFixed(2))}>Last {fmt(lastPrice)}</button>
            )}
          </div>
          <label>
            <span>Trigger</span>
            <select value={once ? "once" : "every"} onChange={(e) => setOnce(e.target.value === "once")}>
              <option value="once">Only once</option>
              <option value="every">Every time</option>
            </select>
          </label>
          <label className="col">
            <span>Message</span>
            <input value={message} maxLength={500} placeholder={`${symbol} ${opLabel} ${price || "…"}`}
              onChange={(e) => setMessage(e.target.value)} />
          </label>
          <div className="hint">Shown as a dashed line on the chart; you get a pop-up when it fires.
            Manage alerts in the Alerts tab.</div>
        </div>
        {error && <div className="error">{error}</div>}
        <div className="modal-actions">
          <span className="spacer" />
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button type="submit" className="primary" disabled={busy}>Create</button>
        </div>
      </form>
    </Modal>
  );
}
