"""One asyncio worker owns Uvicorn and the desktop HTTP client."""
import asyncio
import concurrent.futures
import secrets
import socket
import threading

import httpx
import uvicorn

from mactranslator.backend.api import create_app
from mactranslator.backend.providers import sse_data


class BackendRuntime:
    def __init__(self, database=None, credentials=None, experimental=False):
        self.token = secrets.token_urlsafe(32)
        self.database, self.credentials, self.experimental = database, credentials, experimental
        self.loop = None
        self.thread = None
        self.server = None
        self.client = None
        self.base_url = None
        self.startup = concurrent.futures.Future()

    def start(self):
        self.thread = threading.Thread(target=self._run, name="translator-api", daemon=True)
        self.thread.start()
        return self.startup

    def _run(self):
        try:
            asyncio.run(self._serve())
        except BaseException as exc:
            if not self.startup.done():
                self.startup.set_exception(exc)

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        self.base_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        app = create_app(self.token, self.database, self.credentials, experimental=self.experimental)
        self.server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning",
                                                   lifespan="on", loop="asyncio", timeout_graceful_shutdown=3))
        task = asyncio.create_task(self.server.serve(sockets=[sock]))
        try:
            async with httpx.AsyncClient(base_url=self.base_url,
                                         headers={"Authorization": "Bearer " + self.token},
                                         timeout=httpx.Timeout(180, connect=5), trust_env=False) as client:
                self.client = client
                for _ in range(200):
                    if task.done():
                        await task
                        raise RuntimeError("本地服务启动失败。")
                    if self.server.started:
                        response = await client.get("/api/v1/health")
                        response.raise_for_status()
                        self.startup.set_result(response.json())
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise RuntimeError("本地服务启动超时。")
                await task
        finally:
            self.server.should_exit = True
            if not task.done():
                await task
            sock.close()
            self.client = None

    def submit(self, coroutine):
        if not self.loop or not self.loop.is_running():
            coroutine.close()
            raise RuntimeError("本地服务尚未就绪。")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    async def request(self, method, path, **kwargs):
        response = await self.client.request(method, "/api/v1" + path, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", "请求失败")
            except ValueError:
                detail = f"HTTP {response.status_code}"
            raise RuntimeError(str(detail))
        if response.status_code == 204:
            return None
        return response.json()

    async def stream(self, body, callback):
        import json
        async with self.client.stream("POST", "/api/v1/translate", json=body) as response:
            if response.is_error:
                await response.aread()
                raise RuntimeError(response.json().get("detail", "翻译失败"))
            async for value in sse_data(response.aiter_lines()):
                callback(json.loads(value))

    async def speech(self, body):
        response = await self.client.post("/api/v1/speech", json=body)
        if response.is_error:
            raise RuntimeError(response.json().get("detail", "朗读失败"))
        return response.content

    def stop(self):
        if self.loop and self.loop.is_running() and self.server:
            self.loop.call_soon_threadsafe(setattr, self.server, "should_exit", True)
        if self.thread:
            self.thread.join(timeout=5)
