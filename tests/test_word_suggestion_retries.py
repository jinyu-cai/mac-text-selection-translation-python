import asyncio
import importlib
import json
from uuid import uuid4

import httpx
import pytest

from mactranslator.backend import api
from mactranslator.contracts import Provider, Settings
from test_api import HEADERS, client, provider, save
from test_word_suggestions import candidate


SOURCE = "Planes take off here."


@pytest.mark.parametrize("invalid", [
    "PRIVATE INVALID RESPONSE",
    '{"suggestions": [{"term": "PRIVATE"}]}',
])
def test_invalid_format_retries_with_same_request_and_corrective_prompt(tmp_path, credentials, invalid):
    calls = []
    p = provider(name="Guess", model="guess", api_key="secret-key")
    # Provider.model_dump intentionally excludes the key; this is settings input.
    p["api_key"] = "secret-key"
    request_id = str(uuid4())

    async def generate(selected, key, prompt, text, identifier):
        calls.append((selected, key, prompt, text, identifier))
        if len(calls) == 1:
            yield invalid
        else:
            result = json.dumps({"suggestions": [candidate()]})
            yield result[:20]
            yield result[20:]

    with client(tmp_path, credentials) as c:
        save(c, [p], enable_notes=True, enable_word_suggestions=True,
             word_suggestions_provider_id=p["id"], word_suggestions_preferences="aviation",
             word_suggestions_prompt="prioritize collocations", word_suggestions_count=1)
        c.app.state.providers.translate = generate
        response = c.post("/api/v1/word-suggestions", json={"text": SOURCE, "request_id": request_id})

    assert response.status_code == 200, response.text
    assert response.json() == {"request_id": request_id, "provider_id": p["id"],
                               "backend_name": "Guess", "suggestions": [candidate()]}
    assert len(calls) == 2
    for selected, key, prompt, text, identifier in calls:
        assert str(selected.id) == p["id"] and selected.model == "guess"
        assert key == "secret-key" and text == SOURCE and str(identifier) == request_id
        assert "aviation" in prompt and "prioritize collocations" in prompt
        assert "Chinese" in prompt and "at most 1" in prompt
        assert "PRIVATE" not in prompt and "secret-key" not in prompt
    assert calls[1][2].startswith(calls[0][2]) and calls[1][2] != calls[0][2]
    assert "JSON" in calls[1][2][len(calls[0][2]):]


def test_invalid_format_stops_after_two_attempts_and_redacts_response(tmp_path, credentials):
    calls = 0

    async def generate(*args):
        nonlocal calls
        calls += 1
        yield "PRIVATE INVALID RESPONSE"

    with client(tmp_path, credentials) as c:
        p = provider()
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])
        c.app.state.providers.translate = generate
        response = c.post("/api/v1/word-suggestions", json={"text": SOURCE})

    assert calls == 2
    assert response.status_code == 502
    assert "invalid word suggestions" in response.json()["detail"]
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("output,expected", [
    ('{"suggestions": []}', []),
    ("[]", []),
    (json.dumps([candidate()]), [candidate()]),
    ('Here are the words:\n```json\n' + json.dumps({"suggestions": [candidate()]}) + '\n```\nDone.',
     [candidate()]),
    (json.dumps({"suggestions": [None, dict(candidate(), confidence=0.9)], "explanation": "useful"}),
     [candidate()]),
    (json.dumps({"suggestions": [candidate("absent", "Invented absent sentence.")]}), []),
])
def test_valid_or_locally_recoverable_output_does_not_retry(tmp_path, credentials, output, expected):
    calls = 0

    async def generate(*args):
        nonlocal calls
        calls += 1
        yield output

    with client(tmp_path, credentials) as c:
        p = provider()
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])
        c.app.state.providers.translate = generate
        response = c.post("/api/v1/word-suggestions", json={"text": SOURCE})

    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == expected
    assert calls == 1


@pytest.mark.parametrize("exception", [RuntimeError, ValueError])
def test_provider_errors_do_not_trigger_format_retry(tmp_path, credentials, exception):
    calls = 0

    async def generate(*args):
        nonlocal calls
        calls += 1
        yield '{"suggestions":'
        raise exception("PRIVATE PROVIDER ERROR")

    with client(tmp_path, credentials) as c:
        p = provider()
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])
        c.app.state.providers.translate = generate
        response = c.post("/api/v1/word-suggestions", json={"text": SOURCE})

    assert response.status_code == 502
    assert "PRIVATE" not in response.text
    assert calls == 1


def test_oversized_response_is_not_retried(tmp_path, credentials):
    calls = 0

    async def generate(*args):
        nonlocal calls
        calls += 1
        yield "PRIVATE" + " " * 100_000
        yield " " * 100_000

    with client(tmp_path, credentials) as c:
        p = provider()
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])
        c.app.state.providers.translate = generate
        response = c.post("/api/v1/word-suggestions", json={"text": SOURCE})

    assert response.status_code == 502
    assert "PRIVATE" not in response.text
    assert calls == 1


def test_retry_output_has_an_independent_size_limit(tmp_path, credentials):
    calls = 0

    async def generate(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield "INVALID" + " " * 100_000
        else:
            yield " " * 100_000 + json.dumps({"suggestions": [candidate()]})

    with client(tmp_path, credentials) as c:
        p = provider()
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])
        c.app.state.providers.translate = generate
        response = c.post("/api/v1/word-suggestions", json={"text": SOURCE})

    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == [candidate()]
    assert calls == 2


@pytest.mark.parametrize("kind", ["gemini_cli", "antigravity_cli", "codex_cli"])
def test_cli_format_retry_does_not_read_keychain(tmp_path, credentials, monkeypatch, kind):
    module = importlib.import_module("mactranslator.backend." + kind)
    calls = []

    async def generate(selected, prompt, text):
        calls.append((selected, prompt, text))
        yield "invalid" if len(calls) == 1 else json.dumps({"suggestions": [candidate()]})

    monkeypatch.setattr(module, "translate", generate)
    credentials.get = lambda _: pytest.fail("CLI should not read credentials")
    p = provider(kind=kind)
    with client(tmp_path, credentials) as c:
        save(c, [p], enable_notes=True, enable_word_suggestions=True, word_suggestions_provider_id=p["id"])
        response = c.post("/api/v1/word-suggestions", json={"text": SOURCE})

    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == [candidate()]
    assert len(calls) == 2
    assert all(str(selected.id) == p["id"] and text == SOURCE for selected, _, text in calls)
    assert calls[0][1] != calls[1][1]


async def test_disconnect_cancels_the_format_retry(tmp_path, credentials):
    app = api.create_app("test-token", tmp_path / "disconnect.sqlite3", credentials)
    started, closed, disconnect = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def generate(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield "invalid"
            return
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
        sent = []

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": json.dumps({"text": SOURCE}).encode(),
                        "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "method": "POST",
                 "path": "/api/v1/word-suggestions", "query_string": b"", "scheme": "http",
                 "headers": [(b"authorization", b"Bearer test-token"), (b"content-type", b"application/json")]}
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(started.wait(), 2)
            disconnect.set()
            await asyncio.wait_for(task, 2)
            assert calls == 2 and closed.is_set()
            assert next(message["status"] for message in sent if message["type"] == "http.response.start") == 499
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_format_retry_shares_the_original_timeout(tmp_path, credentials, monkeypatch):
    app = api.create_app("test-token", tmp_path / "timeout.sqlite3", credentials)
    original_timeout = asyncio.timeout
    scopes = []
    calls = 0
    closed = asyncio.Event()

    def controlled_timeout(delay):
        if delay != 150:
            return original_timeout(delay)
        scope = original_timeout(None)
        scopes.append(scope)
        return scope

    async def generate(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield "invalid"
            return
        try:
            # Expire the first attempt's deadline while the retry is active.
            # Rescheduling fails if that timeout scope has already been exited.
            scopes[0].reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()
            yield "unused"
        finally:
            closed.set()

    async with app.router.lifespan_context(app):
        p = Provider()
        app.state.store.save_settings(Settings(providers=[p], enable_notes=True, enable_word_suggestions=True,
                                              word_suggestions_provider_id=p.id))
        app.state.providers.translate = generate
        monkeypatch.setattr(api.asyncio, "timeout", controlled_timeout)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test",
                                    headers=HEADERS) as c:
            response = await asyncio.wait_for(c.post("/api/v1/word-suggestions", json={"text": SOURCE}), 2)

    assert response.status_code == 504, response.text
    assert "timed out" in response.json()["detail"]
    assert len(scopes) == 1 and calls == 2 and closed.is_set()
