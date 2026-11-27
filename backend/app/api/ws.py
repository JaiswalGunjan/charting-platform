"""WebSocket: live bars and quotes.

client -> server  {"op": "subscribe",   "symbol": "NSE:RELIANCE", "tf": "5m"}
                  {"op": "unsubscribe", "symbol": "NSE:RELIANCE", "tf": "5m"}   (tf optional)
                  {"op": "ping"}
server -> client  {"type": "subscribed", "symbol", "tf", "bar": {t,o,h,l,c,v}|null, "quote": {...}}
                  {"type": "bar",   "symbol", "tf", "bar": {t,o,h,l,c,v}}   (conflated, ~4/s)
                  {"type": "quote", "symbol", "ltp", "change", "change_pct", ...}
                  {"type": "error", "message"} | {"type": "pong"}
A "bar" whose t is newer than the last one starts a new bar (series.update semantics).
"""
import asyncio
import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from app.auth.deps import require_user, user_for_websocket
from app.live.service import LiveService

log = logging.getLogger(__name__)
router = APIRouter(tags=["live"])


def get_live(request: Request) -> LiveService:
    live = getattr(request.app.state, "live", None)
    if live is None:
        raise HTTPException(503, "live data disabled")
    return live


@router.get("/quotes", dependencies=[Depends(require_user)])
async def quotes(request: Request, symbols: str = Query(..., examples=["NSE:RELIANCE,NSE:TCS"])) -> list[dict]:
    """Latest quotes; starts streaming any symbol not already live (kept alive via pin)."""
    live = get_live(request)
    out = []
    for s in [x for x in symbols.split(",") if x.strip()][:50]:
        try:
            full = await live.pin(s)
        except LookupError:
            raise HTTPException(404, f"unknown symbol {s}") from None
        out.append(live.quote(full))
    return out


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    user = await asyncio.to_thread(user_for_websocket, ws)
    if user is None:
        await ws.close(code=4401, reason="not signed in")   # the UI goes to the sign-in page
        return
    await ws.accept()
    live = getattr(ws.app.state, "live", None)
    if live is None:
        await ws.send_json({"type": "error", "message": "live data disabled"})
        await ws.close()
        return
    conn = live.new_connection(ws.send_json, user_id=user.id)
    sender = asyncio.create_task(conn.run_sender())
    try:
        while True:
            msg = await ws.receive_json()
            op = msg.get("op") if isinstance(msg, dict) else None
            try:
                if op == "subscribe":
                    snap = await live.subscribe(conn, str(msg["symbol"]), str(msg.get("tf", "1m")))
                    await ws.send_json({"type": "subscribed", **snap})
                elif op == "unsubscribe":
                    await live.unsubscribe(conn, str(msg["symbol"]), msg.get("tf"))
                    await ws.send_json({"type": "unsubscribed", "symbol": msg["symbol"], "tf": msg.get("tf")})
                elif op == "ping":
                    await ws.send_json({"type": "pong"})
                else:
                    await ws.send_json({"type": "error", "message": f"unknown op {op!r}"})
            except (KeyError, ValueError, LookupError) as e:
                await ws.send_json({"type": "error", "message": str(e).strip("'\"")})
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
        await live.drop(conn)
