import asyncio
import sys

import httpx
import pytest

from mactranslator.backend import gemini_cli
from mactranslator.backend.providers import ProviderClient, ProviderError
from mactranslator.presets import gemini_cli_provider


def fake_cli(tmp_path, body):
    path = tmp_path / "fake gemini"
    path.write_text(f"#!{sys.executable}\nimport json, sys, os, time\n" + body)
    path.chmod(0o700)
    p = gemini_cli_provider()
    p.cli_path = str(path)
    return p


async def test_real_subprocess_stream_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "secret")
    p = fake_cli(tmp_path, '''
assert 'GEMINI_API_KEY' not in os.environ
assert 'GOOGLE_API_KEY' not in os.environ
settings = json.load(open(os.environ['GEMINI_CLI_SYSTEM_SETTINGS_PATH']))
assert settings['security']['auth']['selectedType'] == 'oauth-personal'
assert settings['admin']['mcp']['enabled'] is False
assert settings['hooksConfig']['enabled'] is False
assert settings['tools']['core'] == ['__translator_no_tools__']
assert '--model=gemini-test' in sys.argv
assert 'PRIVATE' not in str(sys.argv)
payload = json.load(sys.stdin)
assert payload['source_text'] == 'PRIVATE $(touch /tmp/never-run) 你好'
assert payload['translation_policy'] == 'Translate'
print(json.dumps({'type': 'message', 'role': 'user', 'content': 'PRIVATE'}))
print(json.dumps({'type': 'message', 'role': 'assistant', 'content': '你', 'delta': True}))
print(json.dumps({'type': 'message', 'role': 'assistant', 'content': '好', 'delta': True}))
print(json.dumps({'type': 'result', 'status': 'success'}))
''')
    p.model = 'gemini-test'
    async with httpx.AsyncClient() as http:
        result = [x async for x in ProviderClient(http).translate(
            p, 'ignored', 'Translate', 'PRIVATE $(touch /tmp/never-run) 你好', None)]
    assert result == ['你', '好']


@pytest.mark.parametrize('body, expected', [
    ("print('PRIVATE not json')", 'Invalid'),
    ("print('[]')", 'Invalid'),
    ("print(json.dumps({'type':'result','status':'error','error':'PRIVATE'}))", 'failed'),
    ("print(json.dumps({'type':'error','message':'PRIVATE'}))", 'failed'),
    ("sys.stderr.write('PRIVATE'); sys.exit(1)", 'failed'),
    ("print(json.dumps({'type':'result','status':'success'}))", 'No translation'),
    ("print(json.dumps({'type':'message','role':'assistant','content':'partial'}))", 'failed'),
    ("print(json.dumps({'type':'tool_use','parameters':'PRIVATE'}))", 'tool call'),
])
async def test_failures_are_redacted(tmp_path, body, expected):
    p = fake_cli(tmp_path, body)
    with pytest.raises(ProviderError, match=expected) as error:
        _ = [x async for x in gemini_cli.translate(p, 'policy', 'text')]
    assert 'PRIVATE' not in str(error.value)


async def test_missing_executable(tmp_path):
    p = gemini_cli_provider()
    p.cli_path = str(tmp_path / 'missing')
    with pytest.raises(ProviderError, match='not found'):
        _ = [x async for x in gemini_cli.translate(p, '', '')]


@pytest.mark.parametrize('cancel', [False, True])
async def test_timeout_and_cancellation_reap_child(tmp_path, monkeypatch, cancel):
    marker = tmp_path / 'started'
    p = fake_cli(tmp_path, f"open({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n")
    processes = []
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kw):
        process = await original(*args, **kw)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(gemini_cli, 'TIMEOUT_SECONDS', 5 if cancel else .3)

    async def consume():
        return [x async for x in gemini_cli.translate(p, '', '')]

    task = asyncio.create_task(consume())
    if cancel:
        async with asyncio.timeout(3):
            while not marker.exists():
                await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ProviderError, match='timed out'):
            await task
    assert processes and processes[0].returncode is not None


async def test_default_model_and_verify(tmp_path):
    p = fake_cli(tmp_path, '''
assert not any(a.startswith('--model') for a in sys.argv)
assert json.load(sys.stdin)['source_text'] == 'Hello'
print(json.dumps({'type':'message','role':'assistant','content':'你好'}))
print(json.dumps({'type':'result','status':'success'}))
''')
    async with httpx.AsyncClient() as http:
        await ProviderClient(http).verify(p, '')
