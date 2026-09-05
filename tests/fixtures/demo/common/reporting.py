"""Used by service b only. Pulls in httpx, which service a never needs."""

import httpx


async def fetch_report(url: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.text
