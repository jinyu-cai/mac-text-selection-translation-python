import asyncio
import sys

import pytest

from mactranslator.backend import antigravity_cli as cli
from mactranslator.backend.providers import ProviderError
from mactranslator.presets import antigravity_cli_provider


def fake(tmp_path, body):
    path = tmp_path / 'agy fake'
    path.write_text(f'#!{sys.executable}\nimport json, sys, os, pathlib, time\n' + body)
    path.chmod(0o700)
    p = antigravity_cli_provider()
    p.cli_path = str(path)
    return p


async def test_stream_input_and_deltas(tmp_path):
    p = fake(tmp_path, '''
a = sys.argv
assert '--input-format' in a and '--disable-slash-commands' in a
assert '--model=test-model' in a
assert 'PRIVATE' not in str(a)
agent = a[a.index('--agent') + 1]
assert 'tools: []' in pathlib.Path('.agents/agents', agent, 'agent.md').read_text()
payload = json.loads(json.load(sys.stdin)['message']['content'])
assert payload == {'translation_policy':'Translate', 'source_text':'PRIVATE'}
print(json.dumps({'event':'init','init':{'agent':agent,'tools':['run_command','view_file']}}))
for text in ['你','好']:
 print(json.dumps({'event':'step_update','step_update':{'step_type':'agent_response','text_delta':text}}))
print(json.dumps({'event':'result','result':{'status':'SUCCESS','response':'你好'}}))
''')
    p.model = 'test-model'
    assert [x async for x in cli.translate(p, 'Translate', 'PRIVATE')] == ['你','好']


@pytest.mark.parametrize('body, message', [
    ("print('PRIVATE')", 'Invalid'),
    ("print(json.dumps({'event':'result','result':{'status':'ERROR','error':'PRIVATE'}}))", 'failed'),
    ("print(json.dumps({'event':'init','init':{'agent':'wrong','tools':[]}}))", 'not selected'),
    ("print(json.dumps({'event':'step_update','step_update':{'step_type':'tool'}}))", 'tool call'),
    ("print(json.dumps({'event':'result','result':{'status':'SUCCESS','response':''}}))", 'No translation'),
    ("sys.exit(1)", 'failed'),
])
async def test_errors(tmp_path, body, message):
    with pytest.raises(ProviderError, match=message) as exc:
        _ = [x async for x in cli.translate(fake(tmp_path, body), '', '')]
    assert 'PRIVATE' not in str(exc.value)


async def test_result_fallback(tmp_path):
    p = fake(tmp_path, "print(json.dumps({'event':'result','result':{'status':'SUCCESS','response':'你好'}}))")
    assert [x async for x in cli.translate(p, '', '')] == ['你好']


@pytest.mark.parametrize('cancel', [False, True])
async def test_timeout_cancel(tmp_path, monkeypatch, cancel):
    processes = []
    original = asyncio.create_subprocess_exec

    async def spawn(*a, **kw):
        proc = await original(*a, **kw)
        processes.append(proc)
        return proc

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(cli, 'TIMEOUT_SECONDS', 5 if cancel else .2)
    p = fake(tmp_path, 'time.sleep(60)')

    async def consume():
        return [x async for x in cli.translate(p, '', '')]

    task = asyncio.create_task(consume())
    if cancel:
        async with asyncio.timeout(3):
            while not processes:
                await asyncio.sleep(.01)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else ProviderError):
        await task
    assert processes[0].returncode is not None


def test_model_error_is_actionable_and_redacted():
    message = cli.failure_message('invalid model selection (--model "PRIVATE"): requires --effort')
    assert 'agy models' in message
    assert 'PRIVATE' not in message
    assert 'sign in' not in message
    assert 'login is required' in cli.failure_message('authentication required PRIVATE')
    assert cli.failure_message(None) == cli.FAILURE
