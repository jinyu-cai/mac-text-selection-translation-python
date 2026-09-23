import asyncio
import io
import json
import wave
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from mactranslator.backend.api import create_app
from mactranslator.backend.credentials import CredentialError
from mactranslator.contracts import Provider, Settings

HEADERS = {"Authorization": "Bearer test-token"}


def client(tmp_path, credentials, handler=None, experimental=False):
    transport = httpx.MockTransport(handler) if handler else None
    return TestClient(create_app("test-token", tmp_path / "test.sqlite3", credentials, transport, experimental),
                      headers=HEADERS)


def provider(**kw):
    return Provider(**kw).model_dump(mode="json")


def save(c, providers, **kw):
    response = c.put("/api/v1/settings", json={"providers": providers, **kw})
    assert response.status_code == 200, response.text
    return response.json()


def events(response):
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_auth_browser_rejection_and_validation_redaction(tmp_path, credentials):
    with client(tmp_path, credentials) as c:
        assert c.get("/api/v1/health").json()["ready"]
        assert c.get("/api/v1/health", headers={"Authorization": "bad"}).status_code == 401
        assert c.get("/api/v1/health", headers={"Origin": "https://example.com"}).status_code == 403
        assert c.get("/api/v1/health", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 403
        assert c.get("/docs").status_code == 404
        p = provider()
        p.update(api_key="SECRET", endpoint="SECRET")
        result = c.put("/api/v1/settings", json={"providers": [p]})
        assert result.status_code == 422
        assert "SECRET" not in result.text


def test_settings_secrets_order_persistence_and_deletion(tmp_path, credentials):
    p, q = provider(name="first"), provider(name="second")
    p["api_key"] = "secret-key"
    with client(tmp_path, credentials) as c:
        result = save(c, [p, q])
        assert result["providers"][0]["has_api_key"]
        assert "secret-key" not in json.dumps(result)
        assert "api_key" not in result["providers"][0]
        result["providers"].reverse()
        c.put("/api/v1/settings", json=result).raise_for_status()
        assert credentials.get(p["id"]) == "secret-key"
    with client(tmp_path, credentials) as c:
        settings = c.get("/api/v1/settings").json()
        assert [p["name"] for p in settings["providers"]] == ["second", "first"]
        assert "secret-key" not in (tmp_path / "test.sqlite3").read_bytes().decode(errors="ignore")
        save(c, [q])
        assert not credentials.get(p["id"])


def test_inaccessible_key_does_not_corrupt_settings(tmp_path, credentials):
    with client(tmp_path, credentials) as c:
        original = save(c, [provider(name="original")])

        def fail(account, value):
            raise CredentialError("钥匙串无法访问，请重新输入。")
        credentials.set = fail
        p = provider(name="new")
        p["api_key"] = "private"
        assert c.put("/api/v1/settings", json={"providers": [p]}).status_code == 409
        assert c.get("/api/v1/settings").json() == original


def test_notes_survive_restart(tmp_path, credentials):
    with client(tmp_path, credentials) as c:
        response = c.post("/api/v1/notes", json={"source_text": "hello", "translated_text": "你好"})
        assert response.status_code == 201
        note = response.json()
        assert c.patch(f"/api/v1/notes/{note['id']}", json={"user_note": "remember"}).status_code == 200
    with client(tmp_path, credentials) as c:
        notes = c.get("/api/v1/notes").json()
        assert notes[0]["user_note"] == "remember"
        assert c.get(f"/api/v1/notes/{note['id']}").json()["translated_text"] == "你好"
        assert c.delete(f"/api/v1/notes/{note['id']}").status_code == 204
        assert c.delete(f"/api/v1/notes/{note['id']}").status_code == 404


class Fragments(httpx.AsyncByteStream):
    def __init__(self, body, size=3):
        self.body, self.size = body, size

    async def __aiter__(self):
        for i in range(0, len(self.body), self.size):
            yield self.body[i:i + self.size]


def test_parallel_stream_order_independent_errors_and_fragmented_unicode(tmp_path, credentials):
    called = set()

    async def handler(request):
        body = json.loads(request.content)
        called.add(body["model"])
        if body["model"] == "bad":
            return httpx.Response(401, text="secret-key must not be returned")
        for _ in range(100):
            if len(called) == 2:
                break
            await asyncio.sleep(.005)
        assert len(called) == 2, "providers must run concurrently"
        data = 'data: {"choices":[{"delta":{"content":"你好"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'
        return httpx.Response(200, stream=Fragments(data.encode()))

    p, q = provider(model="good"), provider(model="bad")
    request_id = str(uuid4())
    with client(tmp_path, credentials, handler) as c:
        save(c, [q, p])
        stream = events(c.post("/api/v1/translate", json={"text": "hello", "request_id": request_id}))
    assert [v["id"] for v in stream[0]["providers"]] == [q["id"], p["id"]]
    assert all(v["request_id"] == request_id for v in stream)
    assert any(v["type"] == "provider_error" and v["provider_id"] == q["id"] for v in stream)
    assert "secret-key" not in json.dumps(stream)
    assert "".join(v["text"] for v in stream if v["type"] == "delta") == "你好"
    assert stream[-1]["type"] == "done"


def test_dictionary_gated_in_config_and_runtime(tmp_path, credentials):
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200, json=[{"displaySource": "hello", "translations": []}])

    p = provider(kind="dictionary")
    p["api_key"] = "dict-key"
    with client(tmp_path, credentials, handler) as c:
        assert c.put("/api/v1/settings", json={"providers": [p]}).status_code == 400
        assert c.post(f"/api/v1/providers/{p['id']}/test").status_code == 404
    assert not called
    with client(tmp_path, credentials, handler, experimental=True) as c:
        save(c, [p])
        stream = events(c.post("/api/v1/translate", json={"text": "hello"}))
        assert any(v["type"] == "dictionary" for v in stream)
        assert called[0].headers["Ocp-Apim-Subscription-Key"] == "dict-key"
    called.clear()
    with client(tmp_path, credentials, handler) as c:
        assert c.post("/api/v1/translate", json={"text": "hello"}).status_code == 400
    assert not called


@pytest.mark.parametrize("kind", ["openai_tts", "dashscope_tts"])
def test_tts_body_audio_and_no_credential_forwarding(tmp_path, credentials, kind):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            assert "Authorization" not in request.headers
            return httpx.Response(200, content=b"AUDIO")
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer voice-key"
        if kind == "openai_tts":
            assert body["input"] == "A & B" and body["instructions"] == "calm"
            assert body["response_format"] == "mp3"
            return httpx.Response(200, content=b"AUDIO")
        assert body["input"]["sample_rate"] == 24000
        assert body["input"]["language_hints"] == ["en"]
        return httpx.Response(200, json={"output": {"audio": {"url": "http://audio.aliyuncs.com/file"}}})

    p = provider(kind=kind, instructions="calm")
    p["api_key"] = "voice-key"
    with client(tmp_path, credentials, handler) as c:
        save(c, [p])
        result = c.post("/api/v1/speech", json={"provider_id": p["id"], "text": "A &amp; B", "language": "en-US"})
        assert result.status_code == 200
        assert result.content == b"AUDIO" and result.headers["content-type"] == "audio/mpeg"
    if kind == "dashscope_tts":
        assert calls[-1].url.scheme == "https"


def test_pcm_wrapped_for_native_playback(tmp_path, credentials):
    p = provider(kind="openai_tts", response_format="pcm")
    with client(tmp_path, credentials, lambda r: httpx.Response(200, content=b"\x00\x00" * 16)) as c:
        save(c, [p])
        response = c.post("/api/v1/speech", json={"provider_id": p["id"], "text": "hello"})
    with wave.open(io.BytesIO(response.content)) as wav:
        assert wav.getframerate() == 24000 and wav.getnchannels() == 1


async def test_disconnect_cancels_upstream(tmp_path, credentials):
    closed = asyncio.Event()

    class Infinite(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"start"}}]}\n\n'
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    app = create_app("test-token", tmp_path / "db.sqlite3", credentials,
                     httpx.MockTransport(lambda r: httpx.Response(200, stream=Infinite())))
    async with app.router.lifespan_context(app):
        app.state.store.save_settings(Settings(providers=[Provider()]))
        disconnect = asyncio.Event()
        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": b'{"text":"hi"}', "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if b'"type":"delta"' in message.get("body", b""):
                disconnect.set()

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "method": "POST",
                 "path": "/api/v1/translate", "raw_path": b"/api/v1/translate", "query_string": b"",
                 "scheme": "http", "http_version": "1.1", "server": ("127.0.0.1", 80),
                 "client": ("127.0.0.1", 123), "headers": [(b"authorization", b"Bearer test-token"),
                                                          (b"content-type", b"application/json")]}
        await asyncio.wait_for(app(scope, receive, send), 5)
        await asyncio.wait_for(closed.wait(), 1)
