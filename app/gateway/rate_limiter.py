
import asyncio
import time


class TokenBucketRateLimiter:
    def __init__(
        self,
        capacity: int = 5,
        refill_interval: float = 10.0,
    ):
        self.capacity = capacity
        self.refill_interval = refill_interval
        self.buckets = {}
        self.lock = asyncio.Lock()

    async def allow_request(self, client_id: str) -> bool:
        async with self.lock: 
            # ensures that two concurrent requests don't accidentally consume the same token.
            now = time.monotonic()

            if client_id not in self.buckets:
                self.buckets[client_id] = {
                    "tokens": self.capacity,
                    "last_refill": now,
                }

            bucket = self.buckets[client_id]

            elapsed = now - bucket["last_refill"]
            tokens_to_add = int(elapsed // self.refill_interval)

            if tokens_to_add > 0:
                bucket["tokens"] = min(
                    self.capacity,
                    bucket["tokens"] + tokens_to_add,
                )
                bucket["last_refill"] += (
                    tokens_to_add * self.refill_interval
                )

            if bucket["tokens"] <= 0:
                return False

            bucket["tokens"] -= 1
            return True
