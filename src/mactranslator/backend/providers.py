import asyncio
import io
import json
import wave
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

from mactranslator.contracts import Provider
from mactranslator.policies import endpoint, messages, parameters, should_retry, speech_text


class ProviderError(RuntimeError):
    pass


def public_error(exc: Exception) -> str:
    # Never reflect raw HTTP response bodies or URLs: either can contain credentials/source text.
    if isinstance(exc, ProviderError):
        return str(exc)
    from .credentials import CredentialError
    if isinstance(exc, CredentialError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        hint = {401: "请检查 API Key", 403: "没有访问权限", 404: "请检查地址或模型", 429: "请求过多或额度不足"}
        return f"请求失败 HTTP {code}：{hint.get(code, '服务暂不可用')}"
    if isinstance(exc, httpx.TransportError):
        return f"网络请求失败（{type(exc).__name__}），请检查网络和接口地址。"
    return f"无法处理服务响应（{type(exc).__name__}）。"


async def sse_data(lines):
    """Parse SSE frames, including CRLF, comments, multiple data fields, and EOF."""
    fields = []
    async for line in lines:
        if line == "":
            if fields:
                yield "\n".join(fields)
                fields = []
        elif line.startswith("data:"):
            fields.append(line[5:].removeprefix(" "))
    if fields:
        yield "\n".join(fields)


class ProviderClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    @staticmethod
    def headers(p: Provider, key: str, request_id=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        parsed = urlsplit(endpoint(p.endpoint, p.kind))
        host = parsed.hostname or ""
        if (host == "opencode.ai" or host.endswith(".opencode.ai")) and parsed.path.startswith("/zen/go/"):
            headers["x-opencode-session"] = str(request_id or uuid4()).lower()
        return headers

    async def translate(self, p, key, prompt, text, request_id):
        body = {"model": p.model, "stream": True, "messages": messages(p.model, prompt, text),
                **parameters(p.model, p.reasoning)}
        received = False
        for attempt in range(2):
            try:
                async with self.http.stream("POST", endpoint(p.endpoint, p.kind), json=body,
                                            headers=self.headers(p, key, request_id)) as response:
                    response.raise_for_status()
                    async for data in sse_data(response.aiter_lines()):
                        if data.strip() == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if chunk.get("error"):
                            raise ProviderError("翻译服务返回错误，请检查模型配置和额度。")
                        choices = chunk.get("choices") or []
                        content = (choices[0].get("delta") or {}).get("content") if choices else None
                        if isinstance(content, list):
                            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
                        if isinstance(content, str) and content:
                            received = True
                            yield content
                if not received:
                    raise ProviderError("没有收到翻译结果。")
                return
            except Exception as exc:
                if not should_retry(exc, attempt, received):
                    raise
                await asyncio.sleep(0.4)

    async def verify(self, p, key):
        if p.kind == "dictionary":
            await self.dictionary(p, key, "hello")
            return
        body = {"model": p.model, "stream": False,
                "messages": messages(p.model, "You are a translation engine.", "Connection test."),
                **parameters(p.model, p.reasoning)}
        for attempt in range(2):
            try:
                response = await self.http.post(endpoint(p.endpoint, p.kind), json=body,
                                                headers=self.headers(p, key))
                response.raise_for_status()
                if not response.json().get("choices"):
                    raise ProviderError("连接成功，但响应中没有 choices。")
                return
            except Exception as exc:
                if not should_retry(exc, attempt, False):
                    raise
                await asyncio.sleep(0.4)

    async def dictionary(self, p, key, text):
        if not key or not p.from_language.strip() or not p.to_language.strip():
            raise ProviderError("请填写微软词典 Key 和语言。")
        if len(text.strip()) > 100:
            raise ProviderError("微软词典仅支持不超过 100 字符的词语。")
        headers = {"Ocp-Apim-Subscription-Key": key, "X-ClientTraceId": str(uuid4())}
        if p.region.strip():
            headers["Ocp-Apim-Subscription-Region"] = p.region.strip()
        response = await self.http.post(endpoint(p.endpoint, p.kind), headers=headers,
                                        params={"api-version": "3.0", "from": p.from_language, "to": p.to_language},
                                        json=[{"Text": text.strip()}], timeout=25)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, list) or not result:
            raise ProviderError("没有收到词典结果。")
        return result[0]

    async def speech(self, p, key, text, language):
        text = speech_text(text)
        if not text:
            raise ProviderError("没有可朗读的文字。")
        if p.kind == "openai_tts":
            body = {"model": p.model.strip(), "input": text, "voice": p.voice.strip(),
                    "response_format": p.response_format}
            if p.instructions.strip():
                body["instructions"] = p.instructions.strip()
        else:
            if not key:
                raise ProviderError("请填写 DashScope API Key。")
            inputs = {"text": text, "voice": p.voice.strip(), "format": p.response_format, "sample_rate": 24000}
            if p.instructions.strip():
                inputs["instruction"] = p.instructions.strip()
            lang = (language or "").strip().replace("_", "-").lower().split("-")[0]
            if lang in {"zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar"}:
                inputs["language_hints"] = [lang]
            body = {"model": p.model.strip(), "input": inputs}
        response = await self.http.post(endpoint(p.endpoint, p.kind), json=body,
                                        headers=self.headers(p, key), timeout=120)
        response.raise_for_status()
        if p.kind == "dashscope_tts":
            result = response.json()
            if result.get("code"):
                raise ProviderError("DashScope 合成失败，请检查模型、音色和地域设置。")
            url = ((result.get("output") or {}).get("audio") or {}).get("url", "")
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
                raise ProviderError("服务返回了无效音频地址。")
            if parts.scheme == "http" and parts.hostname.endswith(".aliyuncs.com"):
                url = urlunsplit(parts._replace(scheme="https"))
            # No provider authorization is forwarded to the audio host.
            response = await self.http.get(url, timeout=60)
            response.raise_for_status()
        audio = response.content
        if not audio:
            raise ProviderError("没有收到音频。")
        fmt = p.response_format
        if fmt == "pcm":
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(audio)
            audio, fmt = output.getvalue(), "wav"
        media = {"mp3": "audio/mpeg", "wav": "audio/wav", "opus": "audio/ogg", "aac": "audio/aac",
                 "flac": "audio/flac"}[fmt]
        return audio, media
