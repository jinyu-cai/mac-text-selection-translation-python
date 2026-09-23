"""Read the tutorial server's real SSE contract from a small Python client."""
import asyncio
import json

import httpx

from mactranslator.backend.providers import sse_data
from tutorial.demo_backend import DEMO_TOKEN


async def main(base_url="http://127.0.0.1:8765"):
    async with httpx.AsyncClient(base_url=base_url, trust_env=False,
                                 headers={"Authorization": "Bearer " + DEMO_TOKEN}, timeout=30) as client:
        response = await client.get("/api/v1/health")
        response.raise_for_status()
        print("Health:", response.json())
        async with client.stream("POST", "/api/v1/translate", json={"text": "Hello from a beginner"}) as stream:
            stream.raise_for_status()
            async for payload in sse_data(stream.aiter_lines()):
                event = json.loads(payload)
                print(event["type"], event.get("provider_id", ""), event.get("text", ""), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
