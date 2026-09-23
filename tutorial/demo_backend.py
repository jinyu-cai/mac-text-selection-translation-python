"""The real backend with synthetic provider transport and isolated tutorial storage.

Run from this repository's root: .venv/bin/python -m uvicorn tutorial.demo_backend:create_demo_app \
    --factory --host 127.0.0.1 --port 8765
All provider traffic is handled by HTTPX MockTransport; no remote requests or Keychain calls.
"""
import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx

from mactranslator.backend.api import create_app
from mactranslator.backend.storage import Store
from mactranslator.contracts import Provider, Settings

DEMO_TOKEN = "tutorial-local-only"


class DemoCredentials:
    def __init__(self):
        self.values = {}

    def get(self, account):
        return self.values.get(account, "")

    def set(self, account, value):
        self.values[account] = value


class DemoStream(httpx.AsyncByteStream):
    def __init__(self, delay):
        self.delay = delay

    async def __aiter__(self):
        for text in ["这是", "演示输出", "，并非真实翻译。"]:
            await asyncio.sleep(self.delay)
            body = {"choices": [{"delta": {"content": text}}]}
            yield ("data: " + json.dumps(body, ensure_ascii=False) + "\n\n").encode()
        yield b"data: [DONE]\n\n"


async def mock_provider(request):
    if request.method != "POST" or not request.url.path.endswith("/chat/completions"):
        return httpx.Response(501, json={"error": "The tutorial simulates only translation providers."})
    body = json.loads(request.content)
    if body.get("stream"):
        delay = 0.03 if body.get("model") == "tutorial-fast" else 0.10
        return httpx.Response(200, stream=DemoStream(delay), headers={"Content-Type": "text/event-stream"})
    return httpx.Response(200, json={"choices": [{"message": {"content": "Connection test OK"}}]})


def create_demo_app(database: Path | None = None):
    database = database if database is not None else Path(__file__).parent / ".demo-data" / "translator.sqlite3"
    store = Store(database)
    try:
        if not store.settings().providers:
            store.save_settings(Settings(enable_notes=True, providers=[
                Provider(id=UUID("00000000-0000-4000-8000-000000000001"), name="Demo fast",
                         endpoint="https://tutorial.invalid/v1", model="tutorial-fast"),
                Provider(id=UUID("00000000-0000-4000-8000-000000000002"), name="Demo slow",
                         endpoint="https://tutorial.invalid/v1", model="tutorial-slow"),
            ]))
    finally:
        store.close()
    return create_app(DEMO_TOKEN, database, DemoCredentials(), httpx.MockTransport(mock_provider))
