"""Two simulated providers; learn SSE, concurrency, and cleanup without credentials."""
import asyncio
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Streaming lesson")


class TranslationInput(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


@app.post("/translate")
async def translate(body: TranslationInput):
    request_id = str(uuid4())

    async def events():
        queue = asyncio.Queue(maxsize=16)

        async def provider(name, delay):
            # Echoing is intentional: this lesson does not perform translation.
            for piece in ["DEMO ONLY: ", body.text, " ✓"]:
                await asyncio.sleep(delay)
                await queue.put({"type": "delta", "provider_id": name, "text": piece})
            await queue.put({"type": "provider_done", "provider_id": name})

        tasks = [asyncio.create_task(provider("fast", 0.05)),
                 asyncio.create_task(provider("slow", 0.15))]
        remaining = len(tasks)
        try:
            while remaining:
                item = await queue.get()
                if item["type"] == "provider_done":
                    remaining -= 1
                item["request_id"] = request_id
                yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"type": "done", "request_id": request_id}) + "\n\n"
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return StreamingResponse(events(), media_type="text/event-stream")
