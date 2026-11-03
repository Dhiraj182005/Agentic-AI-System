"""Small bounded retry budget for search HTTP calls; never log request headers."""
import asyncio
import random
import httpx


async def request_with_retry(operation, attempts=3):
    for attempt in range(attempts):
        try:
            response = await operation()
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt + 1 == attempts:
                raise
        else:
            if response.status_code not in (429, 500, 502, 503, 504) or attempt + 1 == attempts:
                return response
            try:
                delay = float(response.headers.get("Retry-After", "0"))
            except ValueError:
                delay = 0
            if delay > 5:
                return response  # fail promptly; user can retry later
            await response.aclose()
            if delay > 0:
                await asyncio.sleep(delay)
                continue
        await asyncio.sleep(min(2 ** attempt + random.random() * .2, 5))
