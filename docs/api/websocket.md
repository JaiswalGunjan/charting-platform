# Live data: the WebSocket contract

`WS /ws` (in development `ws://localhost:5173/api/ws`, proxied to the backend) carries live bars and quotes to the
UI. Today a Python service (`backend/app/live/`, `backend/app/api/ws.py`) produces them. It can be replaced, for
example by the Go fan-out over Kafka and Redis that the blueprint plans, as long as these messages stay the same.
The UI (`frontend/src/live.ts`) relies on nothing else. HTTP endpoints are described in `openapi.json`, next to
this file.

## Client to server

| Message | Meaning |
|---|---|
| `{"op": "subscribe", "symbol": "NSE:RELIANCE", "tf": "5m"}` | stream this symbol's bars of this timeframe, and its quote |
| `{"op": "unsubscribe", "symbol": "NSE:RELIANCE", "tf": "5m"}` | stop; `tf` left out = every timeframe of the symbol |
| `{"op": "ping"}` | keep-alive |

## Server to client

| Message | Meaning |
|---|---|
| `{"type": "subscribed", "symbol", "tf", "bar": Bar \| null, "quote": Quote}` | the forming bar and the quote at the moment of subscribing |
| `{"type": "bar", "symbol", "tf", "bar": Bar}` | the forming bar changed (conflated, about 4 a second at most); a `t` newer than the last one starts a new bar |
| `{"type": "quote", "symbol", "ltp", "change", "change_pct", "prev_close", "ts", "open", "high", "low", "volume"}` | the latest quote |
| `{"type": "alert", "alert_id", "symbol", "message", "price", "ts", "condition": {"op", "price"}}` | a price alert fired (to every connection) |
| `{"type": "unsubscribed", "symbol", "tf"}` · `{"type": "pong"}` · `{"type": "error", "message"}` | replies |

`Bar` = `{"t", "o", "h", "l", "c", "v"}`, with `t` the bar's open time in epoch seconds. Intraday bars are anchored
at the market's session open in its own time zone (`GET /markets`). Daily bars are stamped at IST midnight of the
trading date, as in `GET /history`. Prices are in the market's currency.

## Where ticks come from

Each exchange has a feed (`TICK_SOURCES`, e.g. `NSE=kite,BSE=kite,NYSE=mypkg.vendor:Ticks`). Exchanges not named
use the default feed. A feed is any class with `start(on_tick)`, `stop()`, `subscribe(symbol, last_price)`,
`unsubscribe(symbol)` and a `feed` attribute (`backend/app/live/ticks.py`, `TickSource`). The `feed` attribute is
one of:

| `feed` | What it means for saving | What the chart badge shows |
|---|---|---|
| `live` | real trades: closed 1-minute bars are saved to the bar store | Live |
| `simulated` | made up: never saved over real history | Simulated ticks |
| `none` | no ticks: quotes stay at the last close | Last close |

`GET /health` → `feeds` reports each market's feed, and the chart's badge shows the feed of the symbol's exchange.
