import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse

from mactranslator.contracts import Note, NoteCreate, NoteUpdate, Settings, SpeechRequest, StreamEvent, TranslationRequest
from mactranslator.policies import system_prompt
from .credentials import CredentialError, KeychainCredentials
from .providers import ProviderClient, public_error
from .storage import Store, data_directory


def create_app(token: str, database: Path | None = None, credentials=None, transport=None, experimental=False):
    if not token:
        raise ValueError("A nonempty runtime token is required")
    credentials = credentials if credentials is not None else KeychainCredentials()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(database or data_directory() / "translator.sqlite3")
        try:
            async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(60, connect=15),
                                         trust_env=False, follow_redirects=False) as client:
                app.state.providers = ProviderClient(client)
                yield
        finally:
            app.state.store.close()

    async def authenticate(request: Request):
        if request.headers.get("origin") is not None or request.headers.get("sec-fetch-site") is not None:
            raise HTTPException(403, "浏览器访问未启用")
        authorization = request.headers.get("authorization", "")
        if not secrets.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise HTTPException(401, "需要本地应用身份验证")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(authenticate)])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default error includes the original input, potentially an API key.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": e["loc"], "type": e["type"], "msg": "输入值无效"} for e in exc.errors()]})

    @app.exception_handler(CredentialError)
    async def credential_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def find_provider(provider_id, kinds):
        p = next((p for p in app.state.store.settings().providers if p.id == provider_id), None)
        if not p or p.kind not in kinds or (p.kind == "dictionary" and not experimental):
            raise HTTPException(404, "后端不存在或未启用此功能")
        return p

    @app.get("/api/v1/health")
    async def health():
        return {"ready": True, "experimental_dictionary": experimental}

    @app.get("/api/v1/settings", response_model=Settings)
    async def settings():
        return app.state.store.settings()

    @app.put("/api/v1/settings", response_model=Settings)
    async def update_settings(body: Settings):
        if not experimental and any(p.kind == "dictionary" and p.enabled for p in body.providers):
            raise HTTPException(400, "微软词典仅在实验模式中可启用")
        return app.state.store.save_with_credentials(body, credentials)

    @app.post("/api/v1/providers/{provider_id}/test")
    async def test_provider(provider_id: UUID):
        p = find_provider(provider_id, {"translation", "dictionary"})
        try:
            await app.state.providers.verify(p, credentials.get(str(p.id)))
        except Exception as exc:
            raise HTTPException(502, public_error(exc)) from None
        return {"ok": True}

    @app.post("/api/v1/translate")
    async def translate(body: TranslationRequest):
        settings = app.state.store.settings()
        providers = [p for p in settings.providers if p.enabled and (
            p.kind == "translation" or (experimental and p.kind == "dictionary"))]
        if not providers:
            raise HTTPException(400, "请先在设置中添加并启用翻译后端。")
        prompt = system_prompt(settings.target_language, settings.custom_prompt)

        async def events():
            queue = asyncio.Queue(maxsize=128)

            def event(kind, p=None, **kw):
                return StreamEvent(type=kind, request_id=body.request_id, provider_id=p.id if p else None, **kw)

            async def produce(p):
                try:
                    key = credentials.get(str(p.id))
                    if p.kind == "dictionary":
                        data = await app.state.providers.dictionary(p, key, body.text)
                        await queue.put(event("dictionary", p, data=data))
                    else:
                        async for delta in app.state.providers.translate(p, key, prompt, body.text, body.request_id):
                            await queue.put(event("delta", p, text=delta))
                    await queue.put(event("provider_done", p))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await queue.put(event("provider_error", p, text=public_error(exc)))

            def encode(value):
                return "data: " + value.model_dump_json(exclude_none=True) + "\n\n"

            tasks = [asyncio.create_task(produce(p)) for p in providers]
            try:
                yield encode(event("start", providers=providers))
                remaining = len(tasks)
                while remaining:
                    try:
                        value = await asyncio.wait_for(queue.get(), timeout=10)
                    except TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    if value.type in ("provider_done", "provider_error"):
                        remaining -= 1
                    yield encode(value)
                yield encode(event("done"))
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/speech")
    async def speech(body: SpeechRequest):
        p = find_provider(body.provider_id, {"openai_tts", "dashscope_tts"})
        try:
            audio, media = await app.state.providers.speech(p, credentials.get(str(p.id)), body.text, body.language)
        except Exception as exc:
            raise HTTPException(502, public_error(exc)) from None
        return Response(audio, media_type=media, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/notes", response_model=list[Note])
    async def notes():
        return app.state.store.notes()

    @app.post("/api/v1/notes", response_model=Note, status_code=201)
    async def add_note(body: NoteCreate):
        return app.state.store.add_note(body)

    @app.get("/api/v1/notes/{note_id}", response_model=Note)
    async def note(note_id: UUID):
        result = app.state.store.note(note_id)
        if not result:
            raise HTTPException(404, "笔记不存在")
        return result

    @app.patch("/api/v1/notes/{note_id}", response_model=Note)
    async def update_note(note_id: UUID, body: NoteUpdate):
        result = app.state.store.update_note(note_id, body.user_note)
        if not result:
            raise HTTPException(404, "笔记不存在")
        return result

    @app.delete("/api/v1/notes/{note_id}", status_code=204)
    async def delete_note(note_id: UUID):
        if not app.state.store.delete_note(note_id):
            raise HTTPException(404, "笔记不存在")
        return Response(status_code=204)

    return app
