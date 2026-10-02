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
from mactranslator.contracts import AntigravityLogin, AntigravityCode, CodexLogin
from .antigravity_account import AccountSession
from .codex_account import AccountSession as CodexAccountSession
from .credentials import CredentialError, KeychainCredentials
from .providers import ProviderClient, public_error
from .storage import Store, data_directory
from mactranslator.contracts import WordSuggestionsResponse
from mactranslator.word_suggestions import configuration_error, suggestion_prompt, parse_suggestions


def create_app(token: str, database: Path | None = None, credentials=None, transport=None, experimental=False):
    if not token:
        raise ValueError("A nonempty runtime token is required")
    credentials = credentials if credentials is not None else KeychainCredentials()

    @asynccontextmanager
    async def lifespan(app):
        app.state.antigravity_install_lock = asyncio.Lock()
        app.state.antigravity_account = AccountSession()
        app.state.codex_account = CodexAccountSession()
        app.state.codex_install_lock = asyncio.Lock()
        app.state.store = Store(database or data_directory() / "translator.sqlite3")
        try:
            async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(60, connect=15),
                                         trust_env=False, follow_redirects=False) as client:
                app.state.providers = ProviderClient(client)
                yield
        finally:
            await app.state.antigravity_account.close()
            await app.state.codex_account.close()
            app.state.store.close()

    async def authenticate(request: Request):
        if request.headers.get("origin") is not None or request.headers.get("sec-fetch-site") is not None:
            raise HTTPException(403, "Browser access is not enabled")
        authorization = request.headers.get("authorization", "")
        if not secrets.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise HTTPException(401, "Local app authentication is required")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(authenticate)])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default error includes the original input, potentially an API key.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": e["loc"], "type": e["type"], "msg": "Invalid input"} for e in exc.errors()]})

    @app.exception_handler(CredentialError)
    async def credential_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def find_provider(provider_id, kinds):
        p = next((p for p in app.state.store.settings().providers if p.id == provider_id), None)
        if not p or p.kind not in kinds or (p.kind == "dictionary" and not experimental):
            raise HTTPException(404, "Service not found or this feature is not enabled")
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
            raise HTTPException(400, "Microsoft Dictionary requires experimental mode")
        if error := configuration_error(body):
            raise HTTPException(400, error)
        return app.state.store.save_with_credentials(body, credentials)

    @app.post("/api/v1/codex/install")
    async def codex_install():
        from .codex_install import install
        if app.state.codex_install_lock.locked():
            raise HTTPException(409, "Installation is already in progress.")
        async with app.state.codex_install_lock:
            try:
                return {"cli_path": await install()}
            except Exception as exc:
                raise HTTPException(502, public_error(exc)) from None

    @app.post("/api/v1/codex/login")
    async def codex_login(body: CodexLogin):
        try:
            return await app.state.codex_account.start(body.cli_path)
        except Exception as exc:
            raise HTTPException(400, public_error(exc)) from None

    @app.get("/api/v1/codex/login")
    async def codex_status():
        return app.state.codex_account.snapshot()

    @app.delete("/api/v1/codex/login")
    async def codex_cancel():
        await app.state.codex_account.close()
        return {"ok": True}

    @app.post("/api/v1/antigravity/install")
    async def antigravity_install():
        from .antigravity_install import install
        if app.state.antigravity_install_lock.locked():
            raise HTTPException(409, "Installation is already in progress.")
        async with app.state.antigravity_install_lock:
            try:
                return {"cli_path": await install()}
            except Exception as exc:
                raise HTTPException(502, public_error(exc)) from None

    @app.post("/api/v1/antigravity/login")
    async def antigravity_login(body: AntigravityLogin):
        try:
            return await app.state.antigravity_account.start(body.cli_path)
        except Exception as exc:
            raise HTTPException(400, public_error(exc)) from None

    @app.get("/api/v1/antigravity/login")
    async def antigravity_status():
        return app.state.antigravity_account.snapshot()

    @app.post("/api/v1/antigravity/login/code")
    async def antigravity_code(body: AntigravityCode):
        try:
            return await app.state.antigravity_account.submit_code(body.code.get_secret_value())
        except Exception as exc:
            raise HTTPException(400, public_error(exc)) from None

    @app.delete("/api/v1/antigravity/login")
    async def antigravity_cancel():
        await app.state.antigravity_account.close()
        return {"ok": True}

    @app.post("/api/v1/providers/{provider_id}/test")
    async def test_provider(provider_id: UUID):
        p = find_provider(provider_id, {"translation", "gemini_cli", "antigravity_cli", "codex_cli", "dictionary"})
        try:
            await app.state.providers.verify(p, ("" if p.kind in ("gemini_cli", "antigravity_cli", "codex_cli") else credentials.get(str(p.id))))
        except Exception as exc:
            raise HTTPException(502, public_error(exc)) from None
        return {"ok": True}

    @app.post("/api/v1/word-suggestions", response_model=WordSuggestionsResponse)
    async def word_suggestions(body: TranslationRequest, request: Request):
        settings = app.state.store.settings()
        if not settings.enable_word_suggestions:
            raise HTTPException(400, "Enable AI word suggestions in Settings first.")
        if error := configuration_error(settings):
            raise HTTPException(400, error)
        provider = next(p for p in settings.providers if p.id == settings.word_suggestions_provider_id)

        async def generate():
            key = "" if provider.kind.endswith("_cli") else credentials.get(str(provider.id))
            chunks, size = [], 0
            async with asyncio.timeout(150):
                async for chunk in app.state.providers.translate(
                        provider, key, suggestion_prompt(settings), body.text, body.request_id):
                    size += len(chunk)
                    if size > 200_000:
                        raise ValueError("Oversized suggestions response")
                    chunks.append(chunk)
            return parse_suggestions("".join(chunks), body.text, settings.word_suggestions_count)

        async def disconnected():
            # The validated body is already consumed. Wait directly for disconnect;
            # is_disconnected() uses a cancellation scope that can swallow task cancellation.
            while (await request.receive())["type"] != "http.disconnect":
                pass

        work = asyncio.create_task(generate())
        disconnect = asyncio.create_task(disconnected())
        try:
            completed, _ = await asyncio.wait({work, disconnect}, return_when=asyncio.FIRST_COMPLETED)
            if disconnect in completed:
                raise HTTPException(499, "Request cancelled")
            return WordSuggestionsResponse(request_id=body.request_id, provider_id=provider.id,
                                           backend_name=provider.name, suggestions=await work)
        except ValueError:
            raise HTTPException(502, "AI returned invalid word suggestions. Check the prompt or try again.") from None
        except TimeoutError:
            raise HTTPException(504, "Word suggestions timed out. Try again.") from None
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, public_error(exc)) from None
        finally:
            work.cancel()
            disconnect.cancel()
            await asyncio.gather(work, disconnect, return_exceptions=True)

    @app.post("/api/v1/translate")
    async def translate(body: TranslationRequest):
        settings = app.state.store.settings()
        providers = [p for p in settings.providers if p.enabled and (
            p.kind in ("translation", "gemini_cli", "antigravity_cli", "codex_cli") or (experimental and p.kind == "dictionary"))]
        if not providers:
            raise HTTPException(400, "Add and enable a translation service in Settings first.")
        prompt = system_prompt(settings.target_language, settings.custom_prompt)

        async def events():
            queue = asyncio.Queue(maxsize=128)

            def event(kind, p=None, **kw):
                return StreamEvent(type=kind, request_id=body.request_id, provider_id=p.id if p else None, **kw)

            async def produce(p):
                try:
                    key = ("" if p.kind in ("gemini_cli", "antigravity_cli", "codex_cli") else credentials.get(str(p.id)))
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
            raise HTTPException(404, "Note not found")
        return result

    @app.patch("/api/v1/notes/{note_id}", response_model=Note)
    async def update_note(note_id: UUID, body: NoteUpdate):
        result = app.state.store.update_note(note_id, body.user_note)
        if not result:
            raise HTTPException(404, "Note not found")
        return result

    @app.delete("/api/v1/notes/{note_id}", status_code=204)
    async def delete_note(note_id: UUID):
        if not app.state.store.delete_note(note_id):
            raise HTTPException(404, "Note not found")
        return Response(status_code=204)

    return app
