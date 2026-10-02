import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from mactranslator.contracts import Note, Provider, Settings
from mactranslator.word_suggestions import configuration_error, parse_suggestions
from test_api import client, provider, save, create_app


def candidate(term="take off", context="Planes take off here."):
    return {"term": term, "meaning": "起飞", "context": context}


def test_defaults_and_legacy_notes():
    assert not Settings.model_validate({}).enable_word_suggestions
    assert Settings().word_suggestions_count == 3
    assert Note.model_validate({"source_text": "hello"}).context is None
    for count in [0, 6]:
        with pytest.raises(ValueError):
            Settings(word_suggestions_count=count)


def test_filter_limit_boundaries_unicode_and_fences():
    source = "Planes take off here. A partial plan. 学习中文。"
    items = [candidate(), candidate("TAKE OFF"), candidate("art", "A partial plan."),
             candidate("absent"), candidate("plan", "Invented plan."),
             candidate("中文", "学习中文。"), candidate("Planes")]
    output = '```json\n' + json.dumps({"suggestions": items}) + '\n```'
    assert [x.term for x in parse_suggestions(output, source, 5)] == ["take off", "中文", "Planes"]
    assert len(parse_suggestions(output, source, 1)) == 1
    assert parse_suggestions('{"suggestions": []}', source, 3) == []


@pytest.mark.parametrize("output", ["secret raw output", "[]", '{"suggestions": "bad"}',
                                     '{"suggestions": [{"term": " "}]}'])
def test_invalid_output(output):
    with pytest.raises(ValueError):
        parse_suggestions(output, "source", 3)


@pytest.mark.parametrize("kind,enabled", [("dictionary", True), ("translation", False), ("openai_tts", True)])
def test_invalid_service_settings(tmp_path, credentials, kind, enabled):
    p = provider(kind=kind, enabled=enabled)
    with client(tmp_path, credentials, experimental=True) as c:
        response = c.put("/api/v1/settings", json={"providers": [p], "enable_notes": True,
                          "enable_word_suggestions": True, "word_suggestions_provider_id": p["id"]})
        assert response.status_code == 400
    assert configuration_error(Settings(enable_word_suggestions=True)).startswith("Enable local notes")


def test_api_prompt_selected_service_and_note_persistence(tmp_path, credentials):
    p, other = provider(name="Guess", model="guess"), provider(model="unused")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["model"] == "guess"
        prompt = json.dumps(body["messages"], ensure_ascii=False)
        assert "intermediate aviation" in prompt and "Chinese" in prompt and "prioritize collocations" in prompt
        assert "PRIVATE HISTORY" not in prompt
        result = json.dumps({"suggestions": [candidate()]})
        return httpx.Response(200, text="data: " + json.dumps({"choices": [{"delta": {"content": result}}]}) + "\n\ndata: [DONE]\n\n")

    with client(tmp_path, credentials, handler) as c:
        c.post("/api/v1/notes", json={"source_text": "PRIVATE HISTORY"})
        save(c, [other, p], enable_notes=True, enable_word_suggestions=True,
             word_suggestions_provider_id=p["id"], word_suggestions_preferences="intermediate aviation",
             word_suggestions_prompt="prioritize collocations", word_suggestions_count=1)
        request_id = str(uuid4())
        result = c.post("/api/v1/word-suggestions", json={"request_id": request_id, "text": "Planes take off here."})
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["request_id"] == request_id and data["backend_name"] == "Guess"
        assert data["suggestions"] == [candidate()]
        note = c.post("/api/v1/notes", json={"source_text": "take off", "translated_text": "起飞",
                      "context": "Planes take off here.", "backend_name": "Guess"}).json()
    with client(tmp_path, credentials) as c:
        assert c.get(f"/api/v1/notes/{note['id']}").json()["context"] == "Planes take off here."
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["gemini_cli", "antigravity_cli", "codex_cli"])
def test_cli_suggestions_skip_keychain(tmp_path, credentials, monkeypatch, kind):
    import importlib
    module = importlib.import_module("mactranslator.backend." + kind)

    async def translate(p, prompt, text):
        yield '{"suggestions": []}'

    monkeypatch.setattr(module, "translate", translate)
    credentials.get = lambda _: pytest.fail("CLI should not read credentials")
    p = provider(kind=kind)
    with client(tmp_path, credentials) as c:
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])
        assert c.post("/api/v1/word-suggestions", json={"text": "hi"}).json()["suggestions"] == []


def test_disabled_missing_and_invalid_response(tmp_path, credentials):
    with client(tmp_path, credentials) as c:
        assert c.post("/api/v1/word-suggestions", json={"text": "hi"}).status_code == 400
        p = provider()
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])

        async def invalid(*args):
            yield "PRIVATE INVALID RESPONSE"

        c.app.state.providers.translate = invalid
        response = c.post("/api/v1/word-suggestions", json={"text": "hi"})
        assert response.status_code == 502
        assert "PRIVATE" not in response.text
        settings = c.app.state.store.settings()
        settings.providers = []
        c.app.state.store.save_settings(settings)
        response = c.post("/api/v1/word-suggestions", json={"text": "hi"})
        assert response.status_code == 400 and "Choose" in response.text


async def test_disconnect_cancels_suggestion_generation(tmp_path, credentials):
    app = create_app("test-token", tmp_path / "disconnect.sqlite3", credentials)
    started, closed, disconnect = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def generate(*args):
        try:
            started.set()
            await asyncio.Event().wait()
            yield "unused"
        finally:
            closed.set()

    async with app.router.lifespan_context(app):
        p = Provider()
        app.state.store.save_settings(Settings(providers=[p], enable_notes=True, enable_word_suggestions=True,
                                              word_suggestions_provider_id=p.id))
        app.state.providers.translate = generate
        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": b'{"text":"hi"}', "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        scope = {"type": "http", "asgi": {"version": "3.0"}, "method": "POST",
                 "path": "/api/v1/word-suggestions", "query_string": b"", "scheme": "http",
                 "headers": [(b"authorization", b"Bearer test-token"), (b"content-type", b"application/json")]}
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(started.wait(), 2)
            disconnect.set()
            await asyncio.wait_for(task, 2)
            assert closed.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
