import json
from uuid import uuid4

import httpx
import pytest

from mactranslator.backend.providers import ProviderClient, ProviderError, sse_data
from mactranslator.contracts import Provider
from mactranslator.presets import google_ai_studio_provider


async def test_google_ai_studio_verify_and_stream():
    p = google_ai_studio_provider()
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-google-key"
        assert "x-opencode-session" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == p.model
        assert body["messages"][0]["role"] == "system"
        assert "reasoning_effort" not in body
        if body["stream"]:
            assert body["messages"][1]["content"] == "Hello"
            return httpx.Response(200, text='data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
                                  'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
                                  'data: {"choices":[],"usage":{"total_tokens":10}}\n\n'
                                  'data: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ProviderClient(http)
        await client.verify(p, "synthetic-google-key")
        output = [part async for part in client.translate(p, "synthetic-google-key", "Translate", "Hello", uuid4())]
    assert output == ["你好"]
    assert len(calls) == 2
    assert google_ai_studio_provider().id != p.id


async def test_retry_before_output():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("lost")
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
    p = Provider(endpoint="https://opencode.ai/zen/go/v1")
    session = uuid4()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = [chunk async for chunk in ProviderClient(http).translate(p, "key", "prompt", "text", session)]
    assert result == ["ok"] and len(calls) == 2
    assert all(r.headers["x-opencode-session"] == str(session) for r in calls)


async def test_never_retry_after_output():
    calls = []

    class Failing(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadError("lost")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=Failing())
    output = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(httpx.ReadError):
            async for chunk in ProviderClient(http).translate(Provider(), "", "prompt", "text", uuid4()):
                output.append(chunk)
    assert output == ["partial"] and len(calls) == 1


async def test_empty_stream_is_error():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="data: [DONE]\n\n"))) as http:
        with pytest.raises(ProviderError, match="No translation"):
            _ = [v async for v in ProviderClient(http).translate(Provider(), "", "p", "t", uuid4())]


async def test_sse_multiline_comments_and_eof():
    async def lines():
        for line in [": ping", "event: token", 'data: {"value":', 'data: "yes"}', "", "data: [DONE]"]:
            yield line
    result = [v async for v in sse_data(lines())]
    assert json.loads(result[0]) == {"value": "yes"}
    assert result[-1] == "[DONE]"


async def test_gpt6_luna_verify_and_stream_omit_temperature():
    p = Provider(model="gpt-6-luna", reasoning="auto")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["model"] == "gpt-6-luna"
        assert "temperature" not in body
        assert "reasoning_effort" not in body
        if body["stream"]:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Bonjour"}}]}\n\n'
                                  'data: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "Bonjour"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ProviderClient(http)
        await client.verify(p, "synthetic-key")
        assert [text async for text in client.translate(p, "synthetic-key", "Translate", "Hello", uuid4())] == ["Bonjour"]
    assert [body["stream"] for body in calls] == [False, True]


async def test_stream_parameter_error_is_actionable_and_redacted():
    from mactranslator.backend.providers import public_error

    class ErrorStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps({"error": {"code": "unsupported_value", "param": "temperature",
                                        "message": "private-key and private-source"}}).encode()

    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(400, stream=ErrorStream()))) as http:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            _ = [v async for v in ProviderClient(http).translate(Provider(), "", "p", "t", uuid4())]
    error = public_error(caught.value)
    assert "temperature" in error
    assert "private" not in error
    assert "temporarily unavailable" not in error


@pytest.mark.parametrize("payload", [
    {"error": {"code": "unsupported_value", "param": "private-key", "message": "private-source"}},
    {"error": {"code": "private-key", "param": "model"}},
    {"error": ["private-key"]},
    ["private-key"],
])
def test_invalid_parameter_errors_never_reflect_untrusted_fields(payload):
    from mactranslator.backend.providers import public_error
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(400, json=payload, request=request)
    error = public_error(httpx.HTTPStatusError("private-key", request=request, response=response))
    assert "private" not in error
    assert "Check the model" in error
