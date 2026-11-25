// Position sizing exactly as the SwingScanner does it (swingbt/rules/sizing.py `shares`, without its cash and
// turnover caps): floor(equity x risk% x market multiplier x setup multiplier / (entry - stop)), capped so one
// position is at most max_alloc_pct of equity.
export interface SizeIn {
  equity: number;
  entry: number;
  stop: number;
  riskPct: number;       // % of equity risked per trade (scanner config risk_pct, 1)
  riskMult: number;      // market multiplier for the day (0.5 in a weak market)
  sizeMult?: number;     // setup multiplier (e.g. 0.5 for a mini coil without base and break)
  maxAllocPct?: number;  // cap per position (45%)
}

export interface Size {
  shares: number;
  value: number;          // shares x entry
  pctOfEquity: number;
  atRisk: number;         // the risk budget: equity x risk% x multipliers
  lossAtStop: number;     // shares x (entry - stop)
  sizedBy: "risk" | "max allocation" | "invalid stop";
}

export function positionSize(p: SizeIn): Size {
  const risk = p.entry - p.stop;
  const budget = p.equity * (p.riskPct / 100) * p.riskMult * (p.sizeMult ?? 1);
  if (!(risk > 0) || !(p.entry > 0) || !(p.equity > 0)) {
    return { shares: 0, value: 0, pctOfEquity: 0, atRisk: budget, lossAtStop: 0, sizedBy: "invalid stop" };
  }
  let shares = Math.floor(budget / risk + 1e-9);
  let sizedBy: Size["sizedBy"] = "risk";
  const cap = Math.floor((p.equity * (p.maxAllocPct ?? 45)) / 100 / p.entry + 1e-9);
  if (shares > cap) {
    shares = cap;
    sizedBy = "max allocation";
  }
  shares = Math.max(shares, 0);
  const value = shares * p.entry;
  return { shares, value, pctOfEquity: (value / p.equity) * 100, atRisk: budget, lossAtStop: shares * risk, sizedBy };
}

/** Indian-style amount: 10,00,000 -> "₹10 L", 2,50,00,000 -> "₹2.5 Cr". */
/** Dollars for US positions: $250,000, $1.25M. */
export function dollars(v: number): string {
  if (v >= 1e6) return `$${+(v / 1e6).toFixed(2)}M`;
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

export function lakhs(v: number): string {
  if (v >= 1e7) return `₹${+(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${+(v / 1e5).toFixed(2)} L`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}
