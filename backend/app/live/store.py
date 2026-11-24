"""Live state store: latest quote + forming bars, readable by other services.

Redis keys (blueprint): quote:{symbol} (hash), bar:{symbol}:{tf} (hash).
Falls back to in-process memory when REDIS_URL is empty.
"""
import json
import logging
from typing import Protocol

log = logging.getLogger(__name__)


class LiveStore(Protocol):
    async def set_state(self, symbol: str, quote: dict, bars: dict[str, dict]) -> None: ...
    async def get_quote(self, symbol: str) -> dict | None: ...
    async def get_bar(self, symbol: str, tf: str) -> dict | None: ...
    async def close(self) -> None: ...


class MemoryStore:
    def __init__(self):
        self.quotes: dict[str, dict] = {}
        self.bars: dict[tuple[str, str], dict] = {}

    async def set_state(self, symbol: str, quote: dict, bars: dict[str, dict]) -> None:
        self.quotes[symbol] = quote
        for tf, b in bars.items():
            self.bars[(symbol, tf)] = b

    async def get_quote(self, symbol: str) -> dict | None:
        return self.quotes.get(symbol)

    async def get_bar(self, symbol: str, tf: str) -> dict | None:
        return self.bars.get((symbol, tf))

    async def close(self) -> None:
        pass


class RedisStore:
    def __init__(self, url: str):
        import redis.asyncio as aioredis

        self.r = aioredis.from_url(url, decode_responses=True)

    async def set_state(self, symbol: str, quote: dict, bars: dict[str, dict]) -> None:
        pipe = self.r.pipeline(transaction=False)
        pipe.hset(f"quote:{symbol}", mapping={k: json.dumps(v) for k, v in quote.items()})
        for tf, b in bars.items():
            pipe.hset(f"bar:{symbol}:{tf}", mapping={k: json.dumps(v) for k, v in b.items()})
        await pipe.execute()

    async def _hget(self, key: str) -> dict | None:
        raw = await self.r.hgetall(key)
        return {k: json.loads(v) for k, v in raw.items()} or None

    async def get_quote(self, symbol: str) -> dict | None:
        return await self._hget(f"quote:{symbol}")

    async def get_bar(self, symbol: str, tf: str) -> dict | None:
        return await self._hget(f"bar:{symbol}:{tf}")

    async def close(self) -> None:
        await self.r.aclose()


def make_store(redis_url: str) -> LiveStore:
    if redis_url:
        log.info("live store: redis %s", redis_url.split("@")[-1])
        return RedisStore(redis_url)
    log.info("live store: in-memory (set REDIS_URL to use Redis)")
    return MemoryStore()
