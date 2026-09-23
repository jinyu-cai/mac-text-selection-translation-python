import json
from uuid import uuid4

import httpx
import pytest

from mactranslator.backend.providers import ProviderClient, ProviderError, sse_data
from mactranslator.contracts import Provider


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
        with pytest.raises(ProviderError, match="没有收到"):
            _ = [v async for v in ProviderClient(http).translate(Provider(), "", "p", "t", uuid4())]


async def test_sse_multiline_comments_and_eof():
    async def lines():
        for line in [": ping", "event: token", 'data: {"value":', 'data: "yes"}', "", "data: [DONE]"]:
            yield line
    result = [v async for v in sse_data(lines())]
    assert json.loads(result[0]) == {"value": "yes"}
    assert result[-1] == "[DONE]"
