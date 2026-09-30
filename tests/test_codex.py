import asyncio
import sys

import pytest

from mactranslator.backend import codex_cli as cli
from mactranslator.backend.codex_account import AccountSession, valid_login_url
from mactranslator.backend.providers import ProviderError
from mactranslator.presets import codex_cli_provider


def fake(tmp_path, *, failure='', login=False, effort='auto'):
    path = tmp_path / 'codex fake'
    path.write_text(f'''#!{sys.executable}
import json, sys, os, time
failure = {failure!r}
login = {login!r}
effort = {effort!r}
assert 'PRIVATE' not in str(sys.argv)
assert 'OPENAI_API_KEY' not in os.environ
assert 'features.shell_tool=false' in sys.argv

def emit(x):
 print(json.dumps(x), flush=True)
for line in sys.stdin:
 r=json.loads(line); method=r.get('method'); result={{}}
 if method=='initialized': continue
 if method=='account/read': result={{'account':None if login else {{'type':'chatgpt'}}}}
 if method=='account/login/start': result={{'loginId':'login', 'authUrl':'https://auth.openai.com/authorize?test=1'}}
 if method=='model/list': result={{'data':[{{'model':'test-model','displayName':'Test','isDefault':True,'defaultReasoningEffort':'medium','supportedReasoningEfforts':[{{'reasoningEffort':e}} for e in ['none','minimal','low','medium','high','xhigh','max','ultra']]}}], 'nextCursor':None}}
 if method=='config/read': result={{'config':{{'mcp_servers':{{'example':{{}}}}}}}}
 if method=='thread/start':
  p=r['params']; assert p['ephemeral'] and p['sandbox']=='read-only'
  assert p['environments']==[] and p['config']['mcp_servers.example.enabled'] is False
  assert p['developerInstructions']=='Translate'
  result={{'thread':{{'id':'thread'}}}}
 if method=='turn/start':
  assert r['params']['input'][0]['text']=='PRIVATE'
  assert ('effort' not in r['params']) if effort=='auto' else r['params']['effort']==('none' if effort=='off' else effort)
  if failure=='hang': time.sleep(60)
  if failure=='invalid': print('PRIVATE',flush=True); sys.exit()
  result={{'turn':{{'id':'turn'}}}}
 emit({{'id':r['id'],'result':result}})
 if method=='account/login/start':
  emit({{'method':'account/login/completed','params':{{'loginId':'login','success':True}}}})
 if method=='turn/start':
  emit({{'method':'item/completed','params':{{'threadId':'other','item':{{'type':'agentMessage','text':'WRONG'}}}}}})
  emit({{'method':'item/completed','params':{{'threadId':'thread','item':{{'type':'agentMessage','phase':'commentary','text':'COMMENT'}}}}}})
  emit({{'method':'item/completed','params':{{'threadId':'thread','item':{{'type':'commandExecution' if failure=='tool' else 'agentMessage','text':'你好'}}}}}})
  emit({{'method':'turn/completed','params':{{'threadId':'thread','turn':{{'status':'failed' if failure=='failed' else 'completed','error':{{'message':'PRIVATE'}}}}}}}})
''')
    path.chmod(0o700)
    p = codex_cli_provider()
    p.cli_path = str(path)
    p.reasoning = effort
    return p


@pytest.mark.parametrize('effort', ['auto','off','none','minimal','low','medium','high','xhigh','max','ultra'])
async def test_translation_protocol(tmp_path, monkeypatch, effort):
    monkeypatch.setenv('OPENAI_API_KEY', 'PRIVATE_KEY')
    assert [v async for v in cli.translate(fake(tmp_path, effort=effort), 'Translate', 'PRIVATE')] == ['你好']


@pytest.mark.parametrize('failure', ['failed', 'invalid', 'tool'])
async def test_errors_redacted(tmp_path, failure):
    with pytest.raises(ProviderError) as error:
        _ = [v async for v in cli.translate(fake(tmp_path, failure=failure), 'Translate', 'PRIVATE')]
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('cancel', [False, True])
async def test_timeout_and_cancel_stop_process(tmp_path, monkeypatch, cancel):
    processes = []
    spawn = asyncio.create_subprocess_exec

    async def tracked(*args, **kwargs):
        p = await spawn(*args, **kwargs)
        processes.append(p)
        return p

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', tracked)
    monkeypatch.setattr(cli, 'TIMEOUT_SECONDS', 5 if cancel else .2)

    async def consume():
        return [v async for v in cli.translate(fake(tmp_path, failure='hang'), 'Translate', 'PRIVATE')]

    task = asyncio.create_task(consume())
    if cancel:
        async with asyncio.timeout(3):
            while not processes:
                await asyncio.sleep(.01)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else ProviderError):
        await task
    assert processes[0].returncode is not None


@pytest.mark.parametrize('login', [True, False])
async def test_account_browser_and_cached_login(tmp_path, login):
    session = AccountSession()
    await session.start(fake(tmp_path, login=login).cli_path)
    await session.task
    assert session.snapshot()['status'] == 'ready'
    assert session.snapshot()['models'][0]['id'] == 'test-model'
    assert session.snapshot()['models'][0]['efforts'] == ['none','minimal','low','medium','high','xhigh','max','ultra']
    assert session.snapshot()['models'][0]['default_effort'] == 'medium'
    assert 'url' not in session.snapshot()
    await session.close()
    assert session.snapshot()['status'] == 'idle'


def test_login_url():
    assert valid_login_url('https://chatgpt.com/auth/authorize?state=abc')
    assert not valid_login_url('https://auth.openai.com.evil.test/authorize')
    assert not valid_login_url('https://user@auth.openai.com/authorize')
    assert not valid_login_url('http://auth.openai.com/authorize')


async def test_install_integrity_and_atomicity(tmp_path, monkeypatch):
    import hashlib
    import io
    import tarfile
    import httpx
    from mactranslator.backend import codex_install as installer
    target = tmp_path / 'bin/codex'
    target.parent.mkdir()
    target.write_bytes(b'old binary')
    monkeypatch.setattr(installer, 'managed_path', lambda: target)
    monkeypatch.setattr(installer.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(installer.platform, 'machine', lambda: 'arm64')
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as tar:
        item = tarfile.TarInfo('codex-aarch64-apple-darwin')
        item.size = 3
        tar.addfile(item, io.BytesIO(b'new'))
    payload = data.getvalue()
    checksum = '0' * 64

    def route(request):
        if request.url.host == 'api.github.com':
            return httpx.Response(200, json={'assets': [{'name':'codex-aarch64-apple-darwin.tar.gz',
                'digest':'sha256:' + checksum,
                'browser_download_url':'https://github.com/openai/codex/releases/download/test/binary'}]})
        return httpx.Response(200, content=payload)

    factory = httpx.AsyncClient
    monkeypatch.setattr(installer.httpx, 'AsyncClient', lambda **kw: factory(transport=httpx.MockTransport(route), **kw))
    with pytest.raises(ProviderError, match='checksum'):
        await installer.install()
    assert target.read_bytes() == b'old binary'
    checksum = hashlib.sha256(payload).hexdigest()
    assert await installer.install() == str(target)
    assert target.read_bytes() == b'new'


async def test_reject_unsupported_effort(tmp_path):
    p = fake(tmp_path, effort='high')
    path = __import__('pathlib').Path(p.cli_path)
    path.write_text(path.read_text().replace("['none','minimal','low','medium','high','xhigh','max','ultra']", "['low']"))
    with pytest.raises(ProviderError, match='does not support'):
        _ = [v async for v in cli.translate(p, 'Translate', 'PRIVATE')]
