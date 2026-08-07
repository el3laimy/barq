import time
import asyncio

class TokenBucket:
    def __init__(self, rate: int, capacity: int = None):
        """
        rate: Bytes per second.
        capacity: Max burst bytes. Defaults to rate.
        """
        self.rate = rate
        self.capacity = capacity if capacity else rate
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int):
        """
        Wait until enough tokens are available, then consume them.
        """
        if self.rate <= 0: # Unlimited
            return

        while tokens > 0:
            consume = min(tokens, self.capacity) if self.capacity > 0 else tokens
            wait_time = 0
            had_enough = True

            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill

                # Refill
                new_tokens = elapsed * self.rate
                if new_tokens > 0:
                    self._tokens = min(self.capacity, self._tokens + new_tokens)
                    self._last_refill = now

                if self._tokens >= consume:
                    self._tokens -= consume
                    tokens -= consume
                else:
                    # Not enough tokens — calculate wait time for the deficit
                    deficit = consume - self._tokens
                    wait_time = deficit / self.rate if self.rate > 0 else 0
                    # Consume whatever is available now, track partial progress
                    partial = self._tokens
                    self._tokens = 0
                    tokens -= partial
                    had_enough = False

            if not had_enough and wait_time > 0:
                await asyncio.sleep(wait_time)

class SpeedLimiter:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SpeedLimiter, cls).__new__(cls)
            cls._instance.bucket = TokenBucket(0) # Unlimited by default
        return cls._instance

    def set_limit(self, bytes_per_second: int):
        """Set global speed limit. 0 = Unlimited."""
        self.bucket.rate = bytes_per_second
        self.bucket.capacity = bytes_per_second if bytes_per_second > 0 else 0
        self.bucket._tokens = self.bucket.capacity
        self.bucket._last_refill = time.monotonic()

    async def acquire(self, amount: int):
        await self.bucket.acquire(amount)

# Global Instance
global_limiter = SpeedLimiter()
