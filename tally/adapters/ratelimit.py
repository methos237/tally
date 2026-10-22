"""Token bucket in Redis: one Lua script, so refill and spend are atomic.

A bucket holds `capacity` tokens and refills continuously at capacity/minute.
Each request spends one token. The script takes the clock as an argument, so
tests drive it deterministically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from django_redis import get_redis_connection

SCRIPT = """
local capacity = tonumber(ARGV[1])
local per_ms = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then tokens = capacity; ts = now end
tokens = math.min(capacity, tokens + math.max(0, now - ts) * per_ms)
local allowed = 0
if tokens >= 1 then tokens = tokens - 1; allowed = 1 end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', now)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / per_ms) + 1000)
return {allowed, tostring(tokens)}
"""


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int  # until the bucket is full again
    retry_after_seconds: int  # until one token is available; 0 when allowed


def take(bucket: str, limit_per_minute: int, now_ms: int) -> Decision:
    per_ms = limit_per_minute / 60_000
    script = get_redis_connection("default").register_script(SCRIPT)  # EVALSHA, EVAL on miss
    allowed, tokens = script(keys=[bucket], args=[limit_per_minute, per_ms, now_ms])
    tokens_f = float(tokens)
    return Decision(
        allowed=bool(allowed),
        limit=limit_per_minute,
        remaining=math.floor(tokens_f),
        reset_seconds=math.ceil((limit_per_minute - tokens_f) / per_ms / 1000),
        retry_after_seconds=0 if allowed else math.ceil((1 - tokens_f) / per_ms / 1000),
    )
